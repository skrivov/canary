"""Guards that hold from the first commit.

The import boundary is the load-bearing one: canary's design premise is that
model access enters through an injected port, so each application's traced,
schema-enforced seam stays the only path to a provider. A single convenience
import here would quietly create a second, untraced path. The environment
guard is its twin: canary never reads API keys or configuration from the
process environment, so credentials stay wholly inside the application that
owns them. The scans walk the AST rather than grepping text so an import or
lookup inside a function body or a ``try`` block counts the same as a
top-level one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import canary

SRC = Path(canary.__file__).resolve().parent

#: Provider SDKs and HTTP transports. Nothing in canary may talk to a
#: network, so the transports are banned alongside the SDKs rather than
#: left as a loophole.
FORBIDDEN_ROOTS = {
    "openai",
    "anthropic",
    "litellm",
    "langchain",
    "llama_index",
    "google",
    "vertexai",
    "azure",
    "boto3",
    "botocore",
    "cohere",
    "groq",
    "mistralai",
    "ollama",
    "requests",
    "httpx",
    "httpx2",
    "aiohttp",
    "urllib3",
    "urllib",
    "http",
    "grpc",
    "pycurl",
    "socket",
    "ftplib",
    "smtplib",
    "websocket",
    "websockets",
    "subprocess",
}

#: Every way a module could read (or rewrite) the process environment, plus
#: loaders that would pull a ``.env`` file into it.
ENVIRONMENT_ACCESS = {"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"}
ENVIRONMENT_LOADERS = {"dotenv", "decouple", "environs"}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_no_provider_or_transport_imports() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(hits)
        for path in SRC.rglob("*.py")
        if (hits := _import_roots(path) & FORBIDDEN_ROOTS)
    }
    assert not offenders, (
        f"provider/transport imports crossed the ModelPort boundary: {offenders}"
    )


def test_guard_sees_forbidden_imports(tmp_path: Path) -> None:
    """The falsification half: the scanner must catch what it exists to catch."""

    sample = tmp_path / "smuggle.py"
    sample.write_text(
        "def call():\n    import openai\n    from httpx import Client\n",
        encoding="utf-8",
    )
    assert _import_roots(sample) & FORBIDDEN_ROOTS == {"openai", "httpx"}


def _environment_reads(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ENVIRONMENT_ACCESS:
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "os":
                found.update(
                    alias.name for alias in node.names if alias.name in ENVIRONMENT_ACCESS
                )
            if node.module.split(".")[0] in ENVIRONMENT_LOADERS:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found.update(
                alias.name.split(".")[0]
                for alias in node.names
                if alias.name.split(".")[0] in ENVIRONMENT_LOADERS
            )
    return found


def test_package_reads_no_environment_variables() -> None:
    """API keys and settings belong to the application, never to canary."""

    offenders = {
        str(path.relative_to(SRC)): sorted(hits)
        for path in SRC.rglob("*.py")
        if (hits := _environment_reads(path))
    }
    assert not offenders, f"canary modules read the process environment: {offenders}"


def test_environment_guard_sees_environment_reads(tmp_path: Path) -> None:
    """The falsification half: every spelling of an environment read is caught."""

    sample = tmp_path / "leak.py"
    sample.write_text(
        "import os\n"
        "from os import getenv\n"
        "import dotenv\n"
        "\n"
        "def key():\n"
        "    dotenv.load_dotenv()\n"
        "    return os.environ['PROVIDER_API_KEY'] or getenv('FALLBACK')\n",
        encoding="utf-8",
    )
    assert _environment_reads(sample) == {"environ", "getenv", "dotenv"}


def test_package_imports() -> None:
    assert canary.__doc__ is not None


def test_pure_modules_import_no_clock_or_randomness() -> None:
    """Scoring history must never depend on ambient time or chance."""

    pure = [
        SRC / "compare.py",
        SRC / "diff.py",
        SRC / "ruler.py",
        SRC / "stability.py",
        *sorted((SRC / "metrics").glob("*.py")),
    ]
    forbidden_imports = {"random", "secrets", "time"}
    offenders = {
        str(path.relative_to(SRC)): sorted(_import_roots(path) & forbidden_imports)
        for path in pure
        if _import_roots(path) & forbidden_imports
    }
    ambient_calls: dict[str, list[str]] = {}
    for path in pure:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "today", "utcnow"}
        ]
        if calls:
            ambient_calls[str(path.relative_to(SRC))] = sorted(calls)
    assert not offenders
    assert not ambient_calls


def test_ledger_is_the_only_package_file_writer() -> None:
    """Keep generated artifacts caller-owned and all canary writes append-only."""

    write_methods = {
        "mkdir",
        "open",
        "rename",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
    offenders: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        if path.name == "ledger.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in write_methods
        ]
        builtin_open = [
            "open"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ]
        if calls or builtin_open:
            offenders[str(path.relative_to(SRC))] = sorted(calls + builtin_open)
    assert not offenders, f"file writer exists outside ledger.py: {offenders}"
