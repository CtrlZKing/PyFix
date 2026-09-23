from pyfix.packages.resolver import resolve_package
import pyfix.packages.resolver as resolver_module


def test_cv2_maps_to_opencv_python(monkeypatch):
    # Force the "not already installed" path so this test verifies the
    # verified-mapping table specifically, regardless of whether cv2
    # happens to be installed (under some distribution name) in the
    # environment running the test suite.
    monkeypatch.setattr(resolver_module, "_find_installed_distribution_for_module", lambda _: None)
    resolution = resolve_package("cv2")
    assert resolution.distribution_name == "opencv-python"
    assert resolution.confidence_score >= 0.9


def test_pygame_resolves_directly():
    resolution = resolve_package("pygame")
    assert resolution.resolved
    # pygame is not installed in this sandbox, so it falls through to
    # the heuristic path rather than installed-metadata; either is fine
    # so long as it resolves to a sane name.
    assert resolution.distribution_name == "pygame"


def test_unknown_gibberish_is_not_guessed_with_high_confidence():
    resolution = resolve_package("xyzzy_totally_made_up_998")
    # Should still resolve via heuristic (bare identifier) but with
    # LOW/MEDIUM confidence, never treated as a verified mapping.
    assert resolution.source != "verified-mapping"
    assert resolution.confidence_score < 0.95


def test_malicious_import_name_does_not_crash_resolver():
    resolution = resolve_package("os; rm -rf /")
    # Should not resolve as a clean package name via the heuristic path
    # (the space/semicolon means it fails the identifier regex).
    assert resolution.source == "unknown" or not resolution.resolved
