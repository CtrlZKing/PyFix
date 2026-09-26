"""PyFix command-line interface.

    pyfix run <file>          run a program, diagnose+fix on failure
    pyfix doctor              scan the project for problems
    pyfix explain <error>     explain a traceback (text or file)
    pyfix environment         show detected Python environment
    pyfix dependencies        check requirements vs installed packages
    pyfix diff                show the last proposed/applied diff
    pyfix undo                revert the most recent PyFix edit
    pyfix logs / clear-logs   local diagnostic logs
    pyfix --version

Presentation flags (--beginner / --advanced) work either before or
after the subcommand, and are mutually exclusive:

    pyfix --advanced run file.py
    pyfix run file.py --advanced
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pyfix import __version__
from pyfix.analysis.runner import run_static_analysis
from pyfix.core.models import RepairOutcome, RepairProposal
from pyfix.core.orchestrator import (
    MAX_REPAIR_ITERATIONS,
    PyFixSession,
    apply_proposal,
    diagnose_run_result,
    diagnose_traceback,
)
from pyfix.diagnostics.models import Diagnostic
from pyfix.environment.info import detect_environment, find_project_root
from pyfix.execution.runner import run_script
from pyfix.git.repo import detect_git
from pyfix.safety.undo import UndoLog
from pyfix.source.ast_utils import SourceAnalysis
from pyfix.source.import_editor import restore_from_backup
from pyfix.state.diagnostic_log import DiagnosticLog, DiagnosticLogEntry
from pyfix.state.diff_store import DiffStore
from pyfix.traceback.parser import parse_traceback
from pyfix.ui import console


def _add_presentation_flags(parser: argparse.ArgumentParser, *, suppress_default: bool) -> None:
    """Adds a mutually-exclusive ``--beginner``/``--advanced`` pair to
    ``parser``.

    Used on both the top-level parser (flag *before* the subcommand)
    and every subcommand that renders a proposal/diagnostic (flag
    *after* the subcommand) — argparse re-parses the remaining argv
    with the subparser into the *same* namespace, so on the subcommand
    copies ``default=argparse.SUPPRESS`` is critical: it means "if the
    user didn't pass this after the subcommand, don't touch the
    namespace," instead of silently overwriting a value already set by
    a flag given before the subcommand (the bug this fixes).
    """

    default = argparse.SUPPRESS if suppress_default else False
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--beginner", action="store_true", default=default, help="Use beginner-friendly explanations.")
    group.add_argument("--advanced", action="store_true", default=default, help="Show full technical detail.")


def _presentation_parent() -> argparse.ArgumentParser:
    """A ``parents=[...]``-ready fragment carrying the subcommand-side
    (SUPPRESS-default) presentation flags."""

    p = argparse.ArgumentParser(add_help=False)
    _add_presentation_flags(p, suppress_default=True)
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyfix", description="Python errors, explained and fixed.")
    parser.add_argument("--version", action="store_true", help="Show the PyFix version and exit.")
    _add_presentation_flags(parser, suppress_default=False)

    sub_presentation = _presentation_parent()
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser(
        "run", parents=[sub_presentation], help="Run a Python program and repair failures interactively."
    )
    run_p.add_argument("script", type=str)
    run_p.add_argument("--dry-run", action="store_true", help="Diagnose and propose, but change nothing.")
    run_p.add_argument("--yes", action="store_true", help="Auto-approve safe (non-destructive) fixes.")
    run_p.add_argument(
        "args",
        nargs="*",
        help="Arguments to pass to the target script. Put a literal -- before "
        "them if any look like flags, e.g.: pyfix run game.py -- --level 3",
    )

    sub.add_parser("doctor", parents=[sub_presentation], help="Scan the current project for problems.")

    analyze_p = sub.add_parser(
        "analyze",
        parents=[sub_presentation],
        help="Run static (no-execution) multi-issue analysis on one file.",
    )
    analyze_p.add_argument("script", type=str)
    analyze_p.add_argument("--json", action="store_true", help="Machine-readable JSON output instead of text.")

    explain_p = sub.add_parser("explain", parents=[sub_presentation], help="Explain a traceback.")
    explain_p.add_argument("source", type=str, help="Either raw error text or a path to a traceback file.")

    sub.add_parser("environment", help="Show the detected Python environment.")
    sub.add_parser("dependencies", help="Check requirements files against installed packages.")
    sub.add_parser("diff", help="Show the most recent PyFix-proposed diff.")
    sub.add_parser("undo", help="Revert the most recent PyFix change.")

    logs_p = sub.add_parser("logs", parents=[sub_presentation], help="Show local PyFix diagnostic logs.")
    logs_p.add_argument(
        "--limit", type=int, default=20, help="Show at most this many most-recent entries (default 20)."
    )

    clear_logs_p = sub.add_parser("clear-logs", help="Clear local PyFix diagnostic logs.")
    clear_logs_p.add_argument("--yes", action="store_true", help="Clear without an interactive confirmation prompt.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"pyfix {__version__}")
        return 0

    if getattr(args, "beginner", False) and getattr(args, "advanced", False):
        # Possible when the two flags are split across the top-level
        # parser and the subcommand parser (e.g. `pyfix --beginner run
        # file.py --advanced`) — a single parser's mutually-exclusive
        # group can't catch that combination, so it's checked here.
        parser.error("argument --advanced: not allowed with argument --beginner")

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "explain":
        return _cmd_explain(args)
    if args.command == "environment":
        return _cmd_environment(args)
    if args.command == "dependencies":
        return _cmd_dependencies(args)
    if args.command == "undo":
        return _cmd_undo(args)
    if args.command == "diff":
        return _cmd_diff(args)
    if args.command == "logs":
        return _cmd_logs(args)
    if args.command == "clear-logs":
        return _cmd_clear_logs(args)

    parser.print_help()
    return 0


def _session_for(script: Path, dry_run: bool) -> PyFixSession:
    project_root = find_project_root(script)
    env = detect_environment(project_root)
    return PyFixSession(
        script_path=script,
        project_root=project_root,
        python_executable=env.python_executable,
        backup_dir=project_root / ".pyfix" / "backups",
        dry_run=dry_run,
    )


def _log_entry(
    session: PyFixSession,
    command: str,
    *,
    category: str = "",
    severity: str = "",
    confidence: str = "",
    what_happened: str = "",
    proposed_repair: str = "",
    applied: bool = False,
    apply_succeeded: bool | None = None,
    verified: bool | None = None,
    iteration: int | None = None,
    rollback: bool = False,
    unresolved_reason: str = "",
) -> None:
    log = DiagnosticLog(session.project_root)
    log.record(
        DiagnosticLogEntry(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            command=command,
            target=str(session.script_path),
            category=category,
            severity=severity,
            confidence=confidence,
            what_happened=what_happened,
            proposed_repair=proposed_repair,
            applied=applied,
            apply_succeeded=apply_succeeded,
            verified=verified,
            iteration=iteration,
            rollback=rollback,
            unresolved_reason=unresolved_reason,
        )
    )


def _log_and_save_diff(
    session: PyFixSession,
    command: str,
    proposal: RepairProposal,
    *,
    applied: bool,
    iteration: int | None = None,
    apply_succeeded: bool | None = None,
    verified: bool | None = None,
    rollback: bool = False,
) -> None:
    _log_entry(
        session,
        command,
        category=proposal.category,
        severity=proposal.severity.value,
        confidence=f"{proposal.confidence.value} ({proposal.confidence_score:.0%})",
        what_happened=proposal.what_happened,
        proposed_repair=proposal.proposed_changes[0].description if proposal.proposed_changes else "",
        applied=applied,
        apply_succeeded=apply_succeeded,
        verified=verified,
        iteration=iteration,
        rollback=rollback,
        unresolved_reason=proposal.unresolved_reason,
    )
    DiffStore(session.project_root).save(proposal, command=command, applied=applied)


def _cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.script)
    if not script.exists():
        print(f"pyfix: no such file: {script}")
        return 1

    session = _session_for(script, dry_run=args.dry_run)
    git_status = detect_git(session.project_root)

    print(console.banner())
    print()

    for iteration in range(1, MAX_REPAIR_ITERATIONS + 1):
        print(f"Running {script.name}...")
        print()

        run_result = run_script(script, session.python_executable, args.args)

        if run_result.succeeded:
            if iteration == 1:
                print("✓ Program ran successfully. No problems detected.")
            else:
                print("✓ Problem fixed")
                print("✓ Program started successfully")
            return 0

        proposal = diagnose_run_result(session, run_result)

        if proposal is None:
            print("❌ The program failed, but PyFix does not yet recognize this specific error.")
            print()
            print(run_result.stderr)
            _log_entry(
                session,
                "run",
                category="unrecognized",
                iteration=iteration,
                unresolved_reason="not_recognized",
            )
            _report_other_static_issues(script, blocked_line=None)
            return 1

        print("❌ Problem detected")
        print()
        print(console.render_proposal(proposal, beginner=args.beginner))

        if not proposal.can_auto_fix:
            _log_and_save_diff(session, "run", proposal, applied=False, iteration=iteration)
            blocked_line = _line_from_location(proposal.location)
            _report_other_static_issues(script, blocked_line=blocked_line)
            return 1

        if git_status.is_repo and git_status.working_tree_clean is False and proposal.proposed_changes:
            print()
            print("Git repository detected.")
            print(f"Current branch: {git_status.branch or 'unknown'}")
            print("⚠ Your working tree has uncommitted changes. PyFix will still show a diff")
            print("  before touching any file, and will never discard your work.")

        if args.dry_run:
            print()
            print("(dry run: no changes were made)")
            _log_and_save_diff(session, "run", proposal, applied=False, iteration=iteration)
            return 0

        approved = args.yes or _ask_yes_no("\nApply this fix? [Y/N] ")
        if not approved:
            print("No changes made.")
            _log_and_save_diff(session, "run", proposal, applied=False, iteration=iteration)
            return 1

        outcome = apply_proposal(session, proposal)
        print()
        print(console.render_outcome(outcome))
        _log_and_save_diff(
            session,
            "run",
            proposal,
            applied=True,
            iteration=iteration,
            apply_succeeded=outcome.execution_succeeded,
            verified=outcome.verified,
            rollback=outcome.executed and not outcome.execution_succeeded,
        )

        if not outcome.execution_succeeded:
            return 1  # applied-but-failed: never loop on a broken apply

        if outcome.verified:
            return 0  # fully resolved — no need to re-diagnose again

        # Execution succeeded but verification failed (program still
        # errors, possibly a *different* error now) — loop back to
        # RUN and try the next diagnosis, up to MAX_REPAIR_ITERATIONS.
        print()
        print(f"(iteration {iteration}/{MAX_REPAIR_ITERATIONS}: trying again with the new error)")
        print()

    print(f"⚠ Reached the maximum of {MAX_REPAIR_ITERATIONS} automatic repair attempts. Stopping.")
    print("  Remaining problems will need manual attention.")
    _report_other_static_issues(script, blocked_line=None)
    return 1


def _line_from_location(location: str) -> int | None:
    """Best-effort ``"file, line N"`` -> ``N`` extraction, for de-duplicating
    the issue PyFix just explained against the static whole-file scan below."""

    import re

    match = re.search(r"line (\d+)", location)
    return int(match.group(1)) if match else None


def _report_other_static_issues(script: Path, blocked_line: int | None) -> None:
    """Run a whole-file static scan after PyFix can no longer continue via
    execution, so one error that blocks the program from running never
    prevents PyFix from telling the user about everything else it can
    statically see. This is the fix for the architectural bug where a
    single unrecognized or explanation-only issue ended the entire
    debugging session (see the "critical bug" note in the 3.0 design
    notes: PyFix must keep searching, not just stop).
    """

    try:
        source = script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    diagnostics = run_static_analysis(source, script)
    diagnostics = [d for d in diagnostics if d.line != blocked_line]
    if not diagnostics:
        return

    print()
    print(
        f"PyFix could not get past the issue above by running the program, but a "
        f"static scan of the rest of {script.name} found "
        f"{len(diagnostics)} other statically-detectable issue"
        f"{'s' if len(diagnostics) != 1 else ''}:"
    )
    print()
    for d in diagnostics:
        icon = "❌" if d.severity.value in ("ERROR", "CRITICAL") else "⚠️"
        print(f"  {icon} {script.name}:{d.line}  {d.message}")
    print()
    print(
        "Note: these were found by static analysis only, without running the "
        "program past the point above — some may not be reachable, and this is "
        "not a guarantee that fixing them is enough for the program to run. "
        "Run 'pyfix analyze "
        f"{script.name}' for full detail on each one."
    )


def _diagnostic_to_json(d: Diagnostic) -> dict:
    return {
        "file": str(d.file),
        "line": d.line,
        "column": d.column,
        "end_line": d.end_line,
        "end_column": d.end_column,
        "category": d.category.value,
        "severity": d.severity.value,
        "confidence": d.confidence.value,
        "message": d.message,
        "what_happened": d.what_happened,
        "why_it_happened": d.why_it_happened,
        "offending_expression": d.offending_expression,
        "evidence": [e.description for e in d.evidence],
        "proposed_fix_summary": d.proposed_fix_summary,
        "safe_to_apply": d.safe_to_apply,
    }


def _cmd_analyze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    if not script.exists():
        if args.json:
            print(json.dumps({"error": f"no such file: {script}"}))
        else:
            print(f"pyfix: no such file: {script}")
        return 1

    # `analyze` is static-only by design: it must never execute the
    # target file's top-level code (see the module docstring / README
    # for the analyze-vs-run distinction). run_static_analysis only
    # ever parses and inspects the AST.
    source = script.read_text(encoding="utf-8")
    diagnostics = run_static_analysis(source, script)

    if args.json:
        print(
            json.dumps(
                {
                    "file": str(script),
                    "issue_count": len(diagnostics),
                    "issues": [_diagnostic_to_json(d) for d in diagnostics],
                },
                indent=2,
            )
        )
        return 0 if not diagnostics else 1

    if not diagnostics:
        print(f"✓ PyFix found no statically-detectable issues in {script.name}.")
        print()
        print(
            "Note: PyFix can automatically diagnose and safely repair certain "
            "high-confidence Python problems. More complex bugs may only be "
            "diagnosed or explained, or may only surface when the program runs."
        )
        return 0

    print(f"PyFix found {len(diagnostics)} issue{'s' if len(diagnostics) != 1 else ''}:")
    print()
    for d in diagnostics:
        icon = "❌" if d.severity.value in ("ERROR", "CRITICAL") else "⚠️"
        print(f"{icon} line {d.line}  {d.message}")
        if getattr(args, "advanced", False):
            if d.offending_expression:
                print(f"      {d.offending_expression}")
            if d.why_it_happened:
                print(f"      why: {d.why_it_happened}")
            if d.proposed_fix_summary:
                print(f"      {d.proposed_fix_summary}")
            print(f"      confidence: {d.confidence.value}")
    print()
    print(
        "Note: PyFix can automatically diagnose and safely repair certain "
        "high-confidence Python problems. More complex bugs may only be "
        "diagnosed or explained, or may only surface when the program runs."
    )
    return 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    env = detect_environment(project_root)
    git_status = detect_git(project_root)

    lines: list[str] = []
    problems = 0

    lines.append("Python")
    lines.append(f"  ✓ Python {env.python_version}")
    lines.append("")

    lines.append("Environment")
    if env.is_virtualenv:
        lines.append(f"  ✓ virtual environment detected ({env.venv_name})")
    else:
        lines.append("  ⚠ no virtual environment detected (using system/global Python)")
        problems += 1

    lines.append("")
    lines.append("Dependencies")
    missing = _scan_missing_imports(project_root)
    if missing:
        for name in missing:
            lines.append(f"  ⚠ {name} is imported but not installed")
            problems += 1
    else:
        lines.append("  ✓ no missing imports detected among scanned files")

    lines.append("")
    lines.append("Source")
    bad_files = _scan_syntax_errors(project_root)
    if bad_files:
        for f, err in bad_files:
            lines.append(f"  ⚠ {f}: {err}")
            problems += 1
    else:
        lines.append("  ✓ Syntax valid")

    lines.append("")
    lines.append("Configuration")
    if (project_root / "requirements.txt").exists():
        lines.append("  ✓ requirements.txt found")
    else:
        lines.append("  ⚠ no requirements.txt found")

    lines.append("")
    lines.append("Code (static analysis)")
    code_diagnostics = _scan_static_diagnostics(project_root)
    if code_diagnostics:
        for d in code_diagnostics[:10]:
            lines.append(f"  ⚠ {d.file.relative_to(project_root)}:{d.line}  {d.message}")
            problems += 1
        if len(code_diagnostics) > 10:
            lines.append(f"  ... and {len(code_diagnostics) - 10} more (run 'pyfix analyze <file>' for details)")
    else:
        lines.append("  ✓ no statically-detectable issues found")

    if git_status.is_repo:
        lines.append("")
        lines.append("Git")
        lines.append(f"  ✓ repository detected (branch: {git_status.branch or 'unknown'})")
        if git_status.working_tree_clean is False:
            lines.append("  ⚠ working tree has uncommitted changes")

    lines.append("")
    lines.append(f"{problems} problem{'s' if problems != 1 else ''} found.")

    print(console.render_doctor_report(lines))
    return 0 if problems == 0 else 1


def _cmd_explain(args: argparse.Namespace) -> int:
    source_arg = Path(args.source)
    if source_arg.exists():
        text = source_arg.read_text(encoding="utf-8")
    else:
        text = args.source

    tb_info = parse_traceback(text)
    if tb_info is None:
        print("PyFix could not recognize a Python traceback in that input.")
        return 1

    project_root = find_project_root(Path.cwd())
    env = detect_environment(project_root)
    script_guess = Path(tb_info.last_frame.file) if tb_info.last_frame else Path.cwd()

    session = PyFixSession(
        script_path=script_guess,
        project_root=project_root,
        python_executable=env.python_executable,
        backup_dir=project_root / ".pyfix" / "backups",
        dry_run=True,
    )

    proposal = diagnose_traceback(session, tb_info)

    print(f"Technical error:\n    {tb_info.exception_type}")
    print()
    if proposal is not None:
        print(console.render_proposal(proposal, beginner=args.beginner))
        _log_and_save_diff(session, "explain", proposal, applied=False)
    else:
        print("Simple explanation:")
        print(f"    {tb_info.message or 'PyFix does not yet have a detailed explanation for this error.'}")
        if tb_info.last_frame:
            print()
            print(f"Location:\n    {tb_info.last_frame.file}, line {tb_info.last_frame.line}")
        _log_entry(session, "explain", category="unrecognized", unresolved_reason="not_recognized")
    return 0


def _cmd_environment(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    env = detect_environment(project_root)
    print("\n".join(env.summary_lines()))
    return 0


def _cmd_dependencies(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    req_file = project_root / "requirements.txt"
    if not req_file.exists():
        print("No requirements.txt found in this project.")
        return 0

    from importlib import metadata as importlib_metadata

    problems = 0
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split(">=")[0].split("<=")[0].strip()
        required_version = line.split("==")[1].strip() if "==" in line else None
        try:
            installed_version = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            print(f"⚠ {name} is listed in requirements.txt but not installed.")
            problems += 1
            continue
        if required_version and installed_version != required_version:
            print(
                f"⚠ Environment differs from project requirements: "
                f"{name}=={required_version} required, {installed_version} installed."
            )
            problems += 1

    if problems == 0:
        print("✓ Environment matches requirements.txt")
    return 0 if problems == 0 else 1


def _cmd_undo(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    undo_log = UndoLog(project_root / ".pyfix" / "backups" / "undo_log.json")
    entry = undo_log.pop_last()
    if entry is None:
        print("Nothing to undo.")
        return 0

    target = Path(entry.target_path)
    backup = Path(entry.backup_path)
    if not backup.exists():
        print(f"Cannot undo: backup file missing ({backup}).")
        return 1

    restore_from_backup(target, backup)
    print(f"✓ Reverted: {entry.description}")
    print(f"  ({target} restored from {backup.name})")

    DiagnosticLog(project_root).record(
        DiagnosticLogEntry(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            command="undo",
            target=str(target),
            what_happened=entry.description,
            rollback=True,
        )
    )
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    record = DiffStore(project_root).load()
    if record is None:
        print("No PyFix-proposed diff is available yet.")
        print("Run 'pyfix run <file>', 'pyfix explain <error>', or 'pyfix analyze <file>' first.")
        return 0

    status = "applied" if record.applied else "proposed (not applied)"
    print(f"Most recent PyFix diff — {status}")
    print(f"Command: pyfix {record.command}    Category: {record.category}    When: {record.timestamp}")
    if not record.files:
        print()
        print("(this proposal had no file changes to show)")
        return 0
    for f in record.files:
        print()
        print(f"{f.description}")
        print(f.diff_text)
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    log = DiagnosticLog(project_root)
    entries, corrupt = log.read_all()

    if not entries and corrupt == 0:
        print("No PyFix diagnostic logs yet.")
        print("Logs are recorded automatically by 'pyfix run' and 'pyfix undo'.")
        return 0

    shown = entries[-args.limit :] if args.limit > 0 else entries
    print(f"PyFix diagnostic log ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'}", end="")
    if len(shown) < len(entries):
        print(f", showing last {len(shown)}", end="")
    print(")")
    print()

    advanced = getattr(args, "advanced", False)
    for entry in shown:
        if advanced:
            for line in entry.detail_lines():
                print(line)
            print()
        else:
            print(entry.summary_line())

    if corrupt:
        print()
        print(f"⚠ Skipped {corrupt} corrupted log entr{'y' if corrupt == 1 else 'ies'}.")
    return 0


def _cmd_clear_logs(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path.cwd())
    log = DiagnosticLog(project_root)
    entries, _ = log.read_all()

    if not entries and not log.exists():
        print("No PyFix diagnostic logs to clear.")
        return 0

    print(f"This will permanently delete {len(entries)} local PyFix log entr{'y' if len(entries) == 1 else 'ies'}.")
    print(f"  ({log.path})")
    print("This does NOT touch your source files, backups, or Git history.")

    if not args.yes and not _ask_yes_no("\nClear PyFix logs? [Y/N] "):
        print("No changes made.")
        return 1

    cleared = log.clear()
    print(f"✓ Cleared {cleared} log entr{'y' if cleared == 1 else 'ies'}.")
    return 0


def _scan_missing_imports(project_root: Path) -> list[str]:
    from pyfix.packages.resolver import is_module_installed

    missing: set[str] = set()
    for py_file in project_root.rglob("*.py"):
        if ".venv" in py_file.parts or ".git" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        analysis = SourceAnalysis(source)
        if not analysis.is_valid:
            continue
        for imp in analysis.imports():
            top = imp.module.split(".")[0]
            if top and not is_module_installed(top) and top not in sys.builtin_module_names:
                missing.add(top)
    return sorted(missing)


def _scan_syntax_errors(project_root: Path) -> list[tuple[str, str]]:
    bad = []
    for py_file in project_root.rglob("*.py"):
        if ".venv" in py_file.parts or ".git" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        analysis = SourceAnalysis(source)
        if not analysis.is_valid and analysis.syntax_error:
            bad.append((str(py_file.relative_to(project_root)), str(analysis.syntax_error)))
    return bad


def _scan_static_diagnostics(project_root: Path, max_files: int = 50):
    all_diagnostics = []
    for i, py_file in enumerate(project_root.rglob("*.py")):
        if i >= max_files:
            break
        if ".venv" in py_file.parts or ".git" in py_file.parts or ".pyfix" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        all_diagnostics.extend(run_static_analysis(source, py_file))
    all_diagnostics.sort(key=lambda d: (str(d.file), d.line))
    return all_diagnostics


def _ask_yes_no(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


if __name__ == "__main__":
    sys.exit(main())
