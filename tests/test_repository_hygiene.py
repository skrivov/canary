"""No credential may sit in any file the repository could publish.

Canary never needs an API key: model access is supplied by the application
through ``ModelPort``, and the boundary tests forbid canary from reading the
environment at all. A key-shaped string anywhere in the repository is
therefore always a mistake — in a script, an example, a fixture, or a doc. The
scan covers every file ``git add --all`` would publish (tracked files plus
untracked files that ``.gitignore`` does not exclude), so a developer's ignored
local ``.env`` never trips it while a committed one always does.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "private key block": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "credential assignment": re.compile(
        r"(?i)(?:api[_-]?key|secret|token|password|passwd)\w*[\"']?\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']"
    ),
}


def _findings(text: str) -> list[str]:
    return sorted(name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text))


def _publishable_files() -> list[Path]:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout; repository hygiene applies to source checkouts")
    names = listing.stdout.decode("utf-8").split("\0")
    return [ROOT / name for name in names if name and (ROOT / name).is_file()]


def test_no_publishable_file_contains_a_credential() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _publishable_files():
        data = path.read_bytes()
        if b"\0" in data:
            continue
        if hits := _findings(data.decode("utf-8", errors="ignore")):
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, f"credential-shaped strings in publishable files: {offenders}"


def test_no_environment_file_is_publishable() -> None:
    env_files = sorted(
        str(path.relative_to(ROOT))
        for path in _publishable_files()
        if path.name == ".env"
        or (path.name.startswith(".env.") and path.name != ".env.example")
    )
    assert not env_files, f"environment files must stay local and ignored: {env_files}"


def test_scanner_sees_what_it_exists_to_see() -> None:
    """The falsification half. Fakes are assembled at runtime so this file
    itself never contains a matching literal."""

    assert _findings("sk-" + "proj-" + "A1b2" * 8) == ["OpenAI-style key"]
    assert _findings("sk-" + "ant-" + "api03-" + "Z9y8" * 8) == ["Anthropic key"]
    assert _findings("AKIA" + "ABCDEFGHIJKLMNOP") == ["AWS access key id"]
    assert _findings("ghp_" + "a1B2" * 9) == ["GitHub token"]
    assert _findings("-----BEGIN " + "OPENSSH PRIVATE KEY-----") == ["private key block"]
    assert _findings('PROVIDER_API_KEY = "' + "x7" * 10 + '"') == ["credential assignment"]
    assert _findings("client = AsyncOpenAI()  # reads OPENAI_API_KEY itself") == []
    assert _findings('api_key=os.environ["PROVIDER_API_KEY"]') == []
    assert _findings("max_tokens=16000, input_tokens: int = 0") == []
