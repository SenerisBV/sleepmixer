"""Tests for the import guard mechanism itself.

A guard with no test of its own is how round 1 shipped. This verifies that
forbidden_imports correctly catches all spelling variations and handles
legitimate imports correctly.
"""
from pathlib import Path

from .import_guard import forbidden_imports, resolved_imports


def test_guard_catches_all_forbidden_spellings(tmp_path):
    """Verify the guard catches every spelling of numpy imports."""
    # Create a mock package structure: tmp_path/sleepmix/night/
    pkg_root = tmp_path / "sleepmix" / "night"
    pkg_root.mkdir(parents=True)

    # List of forbidden spellings to test
    forbidden_imports_spellings = [
        "import numpy",
        "import numpy as np",
        "import numpy.fft",
        "from numpy import array",
        "from numpy.random import default_rng",
    ]

    for i, spelling in enumerate(forbidden_imports_spellings):
        module_file = pkg_root / f"test_{i}.py"
        module_file.write_text(f"{spelling}\n")

        violations = forbidden_imports(module_file, tmp_path, {"numpy"})
        assert violations, (
            f"Guard failed to catch: {spelling}. "
            f"Resolved: {resolved_imports(module_file, tmp_path)}"
        )


def test_guard_catches_forbidden_modules(tmp_path):
    """Verify the guard catches sleepmix.audio and relative spellings."""
    pkg_root = tmp_path / "sleepmix" / "night"
    pkg_root.mkdir(parents=True)

    forbidden_audio_spellings = [
        "from sleepmix import audio",
        "from sleepmix.audio import AudioBuffer",
        "from ..audio import AudioBuffer",
        "from .palette import render_voice",
        "from . import palette",
        "import sleepmix.audio as a",
    ]

    for i, spelling in enumerate(forbidden_audio_spellings):
        module_file = pkg_root / f"test_{i}.py"
        module_file.write_text(f"{spelling}\n")

        violations = forbidden_imports(
            module_file, tmp_path, {"sleepmix.audio", "sleepmix.night.palette"}
        )
        assert violations, (
            f"Guard failed to catch: {spelling}. "
            f"Resolved: {resolved_imports(module_file, tmp_path)}"
        )


def test_guard_allows_legitimate_imports(tmp_path):
    """Verify the guard allows imports that should be allowed."""
    pkg_root = tmp_path / "sleepmix" / "night"
    pkg_root.mkdir(parents=True)

    # These imports should be allowed for plan.py
    legitimate_imports = [
        "from ..util import lerp",
        "from .clock import arc_at",
        "from ..config import StemDecayConfig",
    ]

    for i, spelling in enumerate(legitimate_imports):
        module_file = pkg_root / f"plan_{i}.py"
        module_file.write_text(f"{spelling}\n")

        violations = forbidden_imports(
            module_file, tmp_path, {"numpy", "sleepmix.audio"}
        )
        assert not violations, (
            f"Guard incorrectly flagged legitimate import: {spelling}. "
            f"Violations: {violations}"
        )


def test_resolved_imports_handles_absolute_imports(tmp_path):
    """Test that resolved_imports correctly handles absolute imports."""
    pkg_root = tmp_path / "sleepmix"
    pkg_root.mkdir(parents=True)

    # Create a module
    module_file = pkg_root / "audio.py"
    module_file.write_text("import numpy\nimport scipy.signal\n")

    resolved = resolved_imports(module_file, tmp_path)
    assert "numpy" in resolved
    assert "scipy.signal" in resolved


def test_resolved_imports_handles_from_imports(tmp_path):
    """Test that resolved_imports correctly handles from imports."""
    pkg_root = tmp_path / "sleepmix"
    pkg_root.mkdir(parents=True)

    # Create a module
    module_file = pkg_root / "audio.py"
    module_file.write_text("from numpy import array\nfrom scipy import signal\n")

    resolved = resolved_imports(module_file, tmp_path)
    # When importing from a module, both the module and module.name are added
    assert "numpy" in resolved or "numpy.array" in resolved
    assert "scipy" in resolved or "scipy.signal" in resolved


def test_resolved_imports_handles_relative_imports(tmp_path):
    """Test that resolved_imports correctly resolves relative imports."""
    pkg_root = tmp_path / "sleepmix" / "night"
    pkg_root.mkdir(parents=True)

    # Create a module plan.py in sleepmix/night/
    module_file = pkg_root / "plan.py"
    module_file.write_text("from ..audio import AudioBuffer\nfrom .clock import arc_at\n")

    resolved = resolved_imports(module_file, tmp_path)
    # from ..audio (up one level from sleepmix.night to sleepmix, then audio)
    assert "sleepmix.audio" in resolved or "sleepmix.audio.AudioBuffer" in resolved
    # from .clock (same level as sleepmix.night)
    assert "sleepmix.night.clock" in resolved or "sleepmix.night.clock.arc_at" in resolved


def test_forbidden_imports_uses_prefix_matching(tmp_path):
    """Test that forbidden_imports uses dotted-prefix matching, not equality."""
    pkg_root = tmp_path / "sleepmix"
    pkg_root.mkdir(parents=True)

    module_file = pkg_root / "audio.py"
    module_file.write_text("import numpy.fft\n")

    # Forbidding "numpy" should catch "numpy.fft"
    violations = forbidden_imports(module_file, tmp_path, {"numpy"})
    assert "numpy.fft" in violations

    # Forbidding "numpy.fft" should catch "numpy.fft" but not just "numpy"
    violations2 = forbidden_imports(module_file, tmp_path, {"numpy.fft"})
    assert "numpy.fft" in violations2
