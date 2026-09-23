# PyFix

**Python errors, explained and fixed.**

PyFix is a safety-first developer tool that helps Python developers —
especially beginners — understand and safely fix common Python errors.
It now spans two levels of troubleshooting:

- **Level 1** — environment, dependency, and import problems (the
  original V1: missing packages, missing imports, wrong virtual
  environment, missing files, syntax/indentation errors).
- **Level 2** — code-level programming mistakes: wrong function
  arguments, undefined-variable/keyword-argument typos, unreachable
  code, statically-provable indexing errors, obvious type mismatches,
  and attribute typos on builtins/known-safe stdlib modules.

```
RUN → CAPTURE → LOCATE → CLASSIFY → ANALYZE → EXPLAIN → PROPOSE
→ SHOW DIFF → ASK PERMISSION → BACKUP → APPLY → RERUN → VERIFY
→ ROLLBACK IF NECESSARY
```

PyFix can automatically diagnose and safely repair certain
**high-confidence** Python problems. More complex bugs may only be
diagnosed or explained — PyFix never invents a fix it isn't confident
in, and it never pretends a guess is certain.

It is not a reckless auto-fixer. PyFix never installs a package,
edits a file, or runs a command without first explaining what's wrong,
showing you exactly what it wants to do, and asking permission.

## Install

```bash
pip install -e .
```

This registers a `pyfix` command (see `[project.scripts]` in
`pyproject.toml`).

## Quick start

```bash
pyfix run game.py            # run a script; diagnose + fix failures (loops up to 5x, see below)
pyfix run game.py --dry-run  # show what PyFix would do, change nothing
pyfix run game.py --yes      # auto-approve safe (non-destructive) fixes
pyfix doctor                 # scan the current project: environment, deps, AND code issues
pyfix analyze file.py        # static, no-execution multi-issue report for one file
pyfix explain traceback.txt  # explain a saved traceback in plain English
pyfix environment            # show the detected Python interpreter/venv
pyfix dependencies           # compare requirements.txt vs. what's installed
pyfix undo                   # revert the most recent PyFix edit
```

## What V1 (Level 1) does

The full Detection → Diagnosis → Confidence → Proposed action →
Permission → Execution → Verification pipeline, for:

| Category | Behavior |
|---|---|
| `ModuleNotFoundError` / `ImportError` | Resolves the import name to a real PyPI package (installed-metadata → verified mapping table → cautious heuristic) and proposes `<current-python> -m pip install <package>` |
| Package installed in the **wrong environment** | Detects when the missing package exists under a *different* interpreter than the one running your program |
| `NameError` from a forgotten `import` | AST-based: checks whether the name is used like a module and maps to a real package |
| `SyntaxError`, `IndentationError`, `TabError` | Explanation-only, with precise file/line location |
| `FileNotFoundError` | Suggests similarly-named files in the project — never changes a path automatically |
| `pyfix doctor` | Python version, virtualenv detection, missing imports, syntax validity, `requirements.txt`, Git status, **and now code-level static analysis** |
| `pyfix dependencies` | Compares `requirements.txt` pins against what's actually installed |

## What V2 (Level 2) adds

Built entirely on top of the V1 architecture — no existing detector,
safety check, or CLI command was removed or altered in behavior.

| Category | Confidence model | Behavior |
|---|---|---|
| `NameError` — **undefined variable typo** | HIGH (single close match) / LOW (multiple candidates) / UNKNOWN (nothing close) | HIGH → proposes a diff-reviewed, line-scoped rename (`usernmae` → `username`). LOW → lists candidates, explains only. UNKNOWN → explains only |
| `TypeError` — **wrong argument count** (missing / too many / duplicate) | CERTAIN | Explanation-only — PyFix never invents a value for a missing argument or guesses which extra one to drop |
| `TypeError` — **unexpected keyword argument** | HIGH (single close match to a real parameter) / explanation-only otherwise | HIGH → proposes a line-scoped rename of just the keyword (`taxes=` → `tax=`) |
| `AttributeError` — **builtin type typo** (`list`, `dict`, `str`, `set`, `tuple`, `int`, `float`, `bytes`, `frozenset`) | HIGH (one close match) / MEDIUM (a couple) / explanation-only | Always explanation-only by design — PyFix doesn't know every call site, so it reports the correction and lets you apply it |
| `AttributeError` — **stdlib module typo** (`os`, `pathlib`, `sys`, `math`, `json`, `re`, `random`, `datetime`, `subprocess`, `shutil`, `collections`, `itertools`, `typing` — see `SAFE_INTROSPECTION_MODULES`) | Same as above | Only these modules are ever imported for introspection; anything else (including your own project modules, and third-party packages like `requests`) is explicitly declined rather than imported |
| **Unreachable code** (after `return`/`raise`/`break`/`continue`) | CERTAIN | Static-only (`pyfix analyze` / `doctor`) — never fires from a runtime traceback, since unreachable code doesn't raise |
| **`break`/`continue` outside a loop** | CERTAIN | Static-only (in practice Python's compiler already raises `SyntaxError` for a whole invalid file first; this exists for defensive/partial-file analysis) |
| **Statically-constant conditions** (`if 1 == 2:`, `while True:` with no visible exit) | CERTAIN (constant condition) / LOW (possible infinite loop) | Static-only, explanation-only |
| **Out-of-bounds indexing** into a literal or single-assignment list/tuple | CERTAIN (literal index) / LOW (dynamic index) | Static-only, explanation-only — a dynamic index is flagged as "possible", never as certain |
| **Obvious `str + int` type mismatch** | HIGH | Static-only, explanation-only — PyFix states it can't safely determine whether `str(x)` or `int(x)` was intended |
| **Wrong argument count, statically** (calling a locally-defined function) | CERTAIN | Folded into `pyfix analyze` / `doctor` for multi-diagnostic reporting, without needing to actually run the program |

**`pyfix run`'s iterative loop (Level-2 §17):** each run attempts at
most **5** automatic repair iterations (run → diagnose → propose → ask
→ apply → verify → re-run if a *new* fixable error appears). It never
loops silently — every iteration's proposal still requires the same
`[Y/N]` approval (or `--yes`), and it stops immediately if a fix
can't be auto-applied or if verification fails outright.

**`pyfix analyze <file>`** is the new multi-diagnostic entry point:
unlike `pyfix run`, it never executes your program — it's a pure
static pass that can report several issues from one file at once
(matching the flagship example: a wrong-argument-count call *and* an
undefined-variable typo, found together, with exact line numbers).

## Safety model (unchanged, and extended)

Every repair is still represented internally as a `RepairProposal`
(`pyfix.core.models`) carrying its category, explanation, confidence
score, risk level, affected files, exact diff, exact command argv, and
a verification plan. Level-2 static findings use a separate,
richer `Diagnostic` model (`pyfix.diagnostics.models`, 5-tier
confidence: CERTAIN/HIGH/MEDIUM/LOW/UNKNOWN) that only becomes an
executable `RepairProposal` when PyFix is actually confident enough to
act — most Level-2 findings are, by design, explanation-only.

- **Never** builds shell strings; every command is an argv list run
  with `shell=False`.
- **Never** guesses a package name, a variable name, or a keyword
  argument name with confidence it doesn't have. The new
  `pyfix.analysis.typo_resolution` module is shared by every "did you
  mean...?" check so the same HIGH/LOW/UNKNOWN rules apply everywhere.
- **Never** renames more than the single, exact occurrence PyFix
  diagnosed. The new `pyfix.source.rename_editor` is line-scoped and
  word-boundary matched — it will not touch a same-named identifier
  on another line, and it will not match `cat` inside `concatenate`.
- **Never** imports a module just to inspect its attributes unless
  that module is in a small, hardcoded, standard-library-only
  allow-list (`AttributeTypoDetector.SAFE_INTROSPECTION_MODULES`) —
  your own project modules and third-party packages are never
  imported for this purpose, because that would execute untrusted code.
- **Never** edits source with string replacement — insertion/rename
  points come from the real AST or precise line/word-boundary
  matching, every edit produces a unified diff, and a timestamped
  backup is written before the file is touched (undo-able via
  `pyfix undo`).
- **Never** installs into the wrong interpreter — always
  `<sys.executable> -m pip install ...`.
- **Validates** every package name and command argv against an
  allow-list before execution, rejecting shell metacharacters.
- **Validates** that any file PyFix touches resolves to inside the
  project root.
- **Never** claims a fix worked without re-running the program and
  checking the result.
- **Never** discards uncommitted Git work.
- **Bounds** the new iterative repair loop to 5 attempts — no infinite
  automatic-repair loops.

## Project layout

```
src/pyfix/
├── cli/            # argparse-based CLI (pyfix run/doctor/analyze/explain/...)
├── core/           # RepairProposal data model + the orchestrator pipeline (+ MAX_REPAIR_ITERATIONS)
├── analysis/        # NEW — reusable static analysis: scope, typo resolution, control-flow/
│                    #        indexing/type-mismatch checks, the multi-diagnostic runner
├── diagnostics/      # NEW — the Diagnostic data model (5-tier confidence), separate from RepairProposal
├── detectors/      # one class per error category — the extensibility seam
│                    #   + wrong_arguments.py, attribute_typo.py (NEW)
├── packages/       # import-name → PyPI-name resolution
├── environment/    # interpreter/venv/conda detection
├── execution/      # pip install + program re-run, both via safe argv
├── safety/         # input validation + the undo/backup log
├── source/         # AST analysis + diff-producing, backed-up source edits
│                    #   + rename_editor.py (NEW) — precise, line-scoped identifier renames
├── traceback/      # deterministic traceback parser (no LLM)
├── git/            # read-only git status awareness
└── ui/             # plain-text terminal rendering
tests/
├── level2/         # NEW — Level-2 unit + integration + security tests
├── fixtures/level2/ # NEW — small realistic buggy programs used by the Level-2 tests
└── ...             # existing V1 test tree, unmodified in structure
tools/microtest.py  # see "Running tests" below
```

Adding a new error category means writing one class implementing
`pyfix.detectors.base.Detector` (for a runtime-traceback-triggered
check) or a function added to `pyfix.analysis.runner.run_static_analysis`
(for a static, no-execution check) — nothing else changes.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

### Verification status of this build

This environment has **no network access**, so real `pytest` could
not be installed here. Everything below is reported honestly against
that constraint, per the project's own "no fake functionality" rule:

**VERIFIED WITH MICROTEST** (`python3 tools/microtest.py` — a small,
dependency-free stand-in implementing just the pytest features this
suite uses: fixtures, `tmp_path`, `monkeypatch`, `capsys`,
`parametrize`, `raises`, `mark.skip`; it runs the actual test files in
`tests/` unmodified in logic):
- **85 passed, 0 failed, 1 skipped**, covering: V1 detectors and
  pipeline (unchanged), safety/validation (including malicious
  package names, argv, and paths), the traceback parser, the package
  resolver, and — new in this update — Level-2 static analysis on all
  ten `tests/fixtures/level2/*.py` programs, the wrong-arguments and
  attribute-typo detectors, the full detect→propose→apply→verify→undo
  pipeline for a variable typo and a keyword typo, and Level-2-specific
  security tests (rename-editor word-boundary safety, the
  attribute-introspection allow-list, malicious traceback content).
- The one skip is a real `pip install`, which needs network access and
  is intentionally not run automatically.

**VERIFIED** (manually, through the actual installed `pyfix` CLI
against disposable temp projects, not against a real project):
- The flagship Level-2 success-criterion program (wrong-argument-count
  call + undefined-variable typo in the same file) — `pyfix analyze`
  correctly reports both issues with exact line numbers, in one pass,
  without executing the program.
- `pyfix run --dry-run` on the same program stops at the first runtime
  exception (the missing-argument `TypeError`) and explicitly states
  it will not guess a value — makes zero changes.
- The keyword-argument-typo case (`taxes=` → `tax=`) — proposed,
  diffed, applied with `--yes`, and verified by re-running, in a
  single clean pass.
- The builtin attribute-typo case (`list.apend` → `.append()`) and the
  stdlib module attribute-typo case (`math.sqrtt`) — both correctly
  diagnosed and explanation-only.
- Confirmed the attribute-typo detector does **not** attempt to
  introspect `requests` (or any other non-allow-listed module) even
  when the AttributeError message looks identical in shape.
- All pre-existing V1 flows re-run and confirmed unaffected: the
  pygame missing-package flow, `pyfix doctor` (now additionally
  showing a "Code (static analysis)" section), `--help` listing every
  original command plus the new `analyze` command, and the argparse
  flag-ordering fix for global `--advanced`/`--beginner` flags.
- The real installed `pyfix` console command (not just module
  invocation) was exercised for `run`, `doctor`, `analyze`, `undo`,
  and `explain`.

**NOT EXECUTED:**
- The real `pytest` suite (blocked by no network access in this
  sandbox — the test files need no changes to run under it elsewhere).
- Any test requiring an actual `pip install` against PyPI.
- Windows-specific launcher paths (`.venv\Scripts\python.exe`,
  `py.exe`) — handled as data via `pathlib`, but not exercised through
  a real Windows interpreter in this Linux sandbox.

**KNOWN LIMITATIONS (Level 2):**
- The static index-bounds check only tracks a variable assigned a
  literal list/tuple **exactly once** in the file; if the list is
  later mutated (`.append(...)`) or reassigned, PyFix's tracked length
  can go stale and it will decline to flag that variable further
  (it errs toward silence, not a false positive, in ambiguous cases —
  but this means some genuinely-out-of-bounds accesses after mutation
  won't be caught).
- Attribute-typo suggestions are always explanation-only, even at HIGH
  confidence — PyFix does not attempt to locate and edit the call
  site automatically for this category, unlike variable/keyword typos.
- The static wrong-argument-count check only understands
  locally-defined functions in the same file (no cross-file / cross-
  module call graph).
- `break`/`continue`-outside-loop and most control-flow checks only
  run via the static `analyze`/`doctor` path; Python's own compiler
  already raises a `SyntaxError` for a whole file containing invalid
  control flow before PyFix would ever get a clean AST to analyze at
  runtime.
- `pyfix logs`, `pyfix clear-logs`, and `pyfix diff` remain stubs from
  V1 — they say so rather than faking output.
- This build was developed and tested on Linux; Windows is the
  product's first-class target per spec but wasn't exercised on an
  actual Windows machine.

## Full status of the original V1 limitations

All limitations documented in the original V1 README still apply
except where superseded above (undefined-variable typos and unexpected-
keyword typos are no longer "explanation-only" — they're now
Level-2's flagship safe auto-fixes).

