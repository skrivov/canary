#!/usr/bin/env bash
# Qualify and build a Canary release, optionally vendoring the wheel.
#
#   scripts/release.sh               test, then build the wheel and sdist into dist/
#   scripts/release.sh <app-dir>     ...and copy the wheel into <app-dir>/vendor/
#
# The script never edits the application's pyproject.toml or lockfile: it
# prints the stanza to apply there under that project's own review.
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "usage: scripts/release.sh [<application-project-dir>]" >&2
  exit 2
fi

consumer="${1:-}"
if [ -n "$consumer" ] && [ ! -d "$consumer" ]; then
  echo "application project directory does not exist: $consumer" >&2
  exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
python="$root/.venv/bin/python"

if [ ! -x "$python" ]; then
  echo "local virtual environment is missing: $python (run: uv sync --extra schema)" >&2
  exit 1
fi

"$python" -m pytest -q
uv build --project "$root" --out-dir "$root/dist"

version="$("$python" -c 'import pathlib, sys, tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])' "$root/pyproject.toml")"
wheel="$root/dist/canary-$version-py3-none-any.whl"
if [ ! -f "$wheel" ]; then
  echo "expected wheel was not built: $wheel" >&2
  exit 1
fi
digest="$("$python" -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$wheel")"

echo "Built:   $wheel"
echo "SHA-256: $digest"

if [ -z "$consumer" ]; then
  echo
  echo "Publish by tagging this commit v$version and attaching the wheel and its"
  echo "SHA-256 to the release notes."
  exit 0
fi

mkdir -p "$consumer/vendor"
cp "$wheel" "$consumer/vendor/"

echo "Copied to: $consumer/vendor/"
echo
echo "Apply in the application under its own review:"
echo
echo 'dependencies = ["canary"]'
echo '[tool.uv.sources]'
echo "canary = { path = \"vendor/canary-$version-py3-none-any.whl\" }"
echo
echo "Then run: uv lock"
