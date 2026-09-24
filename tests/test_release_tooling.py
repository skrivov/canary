from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.sh"


def test_release_script_is_executable_shell_and_never_edits_pyproject() -> None:
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$root/.venv/bin/python" in text
    assert "cp \"$wheel\"" in text
    assert "SHA-256" in text
    assert "uv lock" in text
    assert "sed -i" not in text


def test_release_script_refuses_bad_arguments_before_building(tmp_path: Path) -> None:
    """Both refusals happen before the suite runs, so neither can recurse."""

    too_many = subprocess.run(
        ["bash", str(SCRIPT), "one", "two"], capture_output=True, text=True
    )
    assert too_many.returncode == 2
    assert "usage:" in too_many.stderr

    missing = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path / "absent")], capture_output=True, text=True
    )
    assert missing.returncode == 1
    assert "does not exist" in missing.stderr
