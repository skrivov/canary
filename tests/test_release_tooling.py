from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.sh"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PINNED_DOCS = (
    ROOT / "README.md",
    ROOT / "TUTORIAL.md",
    ROOT / "docs" / "integration.md",
    ROOT / "skills" / "canary-evals" / "references" / "workflows.md",
)
# Every way the docs pin a release: a Git tag, a GitHub archive, or a wheel.
PIN = re.compile(r'(?:--tag v|@v|refs/tags/v|tag = "v|canary-)(\d+\.\d+\.\d+)')


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


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


def test_claude_plugin_serves_the_skill_from_the_current_release_tag() -> None:
    """A stale entry would hand new plugin users an old release's skill."""

    version = _version()
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    (plugin,) = marketplace["plugins"]

    assert marketplace["name"] == plugin["name"] == "canary"
    assert plugin["version"] == version
    assert plugin["source"] == {
        "source": "github",
        "repo": "skrivov/canary",
        "ref": f"v{version}",
    }
    assert (ROOT / "skills" / "canary-evals" / "SKILL.md").is_file()
    # GitHub is the only contact channel.
    assert "email" not in marketplace["owner"]
    assert "email" not in plugin["author"]


def test_every_documented_install_pins_the_current_release() -> None:
    # The pattern must see a stale pin, or this test is green for nothing.
    assert PIN.findall('uv add "git+https://github.com/skrivov/canary" --tag v0.0.1') == [
        "0.0.1"
    ]
    assert PIN.findall("tar -xzf - canary-0.0.1/skills/canary-evals") == ["0.0.1"]

    version = _version()
    pins = {
        (path.relative_to(ROOT).as_posix(), found)
        for path in PINNED_DOCS
        for found in PIN.findall(path.read_text(encoding="utf-8"))
    }
    assert pins, "no pinned installs found: the pattern has drifted from the docs"
    stale = sorted(pin for pin in pins if pin[1] != version)
    assert not stale, f"install commands pin an old release: {stale}"
