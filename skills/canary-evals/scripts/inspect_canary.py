#!/usr/bin/env python3
"""Fail closed when a wheel or environment is not the Canary evaluation kernel."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any


PRIVATE_CLASSIFIER = "Private :: Do Not Upload"
REQUIRED_RUBRICS = frozenset(
    {
        "hallucination",
        "tool_invocation",
        "tool_response_handling",
        "tool_selection",
        "user_friction",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_name(value: str) -> str:
    return value.casefold().replace("-", "_").replace(".", "_")


def base_checks(
    *,
    name: str,
    version: str,
    classifiers: list[str],
    require_version: str | None,
) -> dict[str, bool]:
    return {
        "distribution_name_is_canary": normalized_name(name) == "canary",
        "private_classifier_present": PRIVATE_CLASSIFIER in classifiers,
        "required_version_matches": (
            require_version is None or version == require_version
        ),
    }


def inspect_wheel(
    path: Path,
    *,
    require_version: str | None,
    expected_sha256: str | None,
) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"wheel does not exist: {resolved}")
    digest = sha256_file(resolved)
    with zipfile.ZipFile(resolved) as archive:
        names = tuple(archive.namelist())
        metadata_paths = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError(
                f"expected one wheel METADATA file, found {len(metadata_paths)}"
            )
        metadata = BytesParser(policy=default).parsebytes(
            archive.read(metadata_paths[0])
        )
        distribution_name = str(metadata.get("Name", ""))
        version = str(metadata.get("Version", ""))
        classifiers = list(metadata.get_all("Classifier", []))
        rubric_names = sorted(
            Path(name).stem
            for name in names
            if name.startswith("canary/rubrics/") and name.endswith(".json")
        )
        checks = base_checks(
            name=distribution_name,
            version=version,
            classifiers=classifiers,
            require_version=require_version,
        )
        checks.update(
            {
                "expected_sha256_matches": (
                    expected_sha256 is None or digest == expected_sha256.casefold()
                ),
                "package_present": "canary/__init__.py" in names,
                "required_rubrics_present": REQUIRED_RUBRICS.issubset(rubric_names),
                "third_party_notice_present": any(
                    name.endswith(".dist-info/licenses/THIRD_PARTY_NOTICES.md")
                    for name in names
                ),
            }
        )
    return {
        "target": "wheel",
        "path": str(resolved),
        "name": distribution_name,
        "version": version,
        "sha256": digest,
        "classifiers": classifiers,
        "rubrics": rubric_names,
        "checks": checks,
        "ok": all(checks.values()),
    }


def inspect_installed(*, require_version: str | None) -> dict[str, Any]:
    distribution = importlib.metadata.distribution("canary")
    distribution_name = str(distribution.metadata.get("Name", ""))
    version = str(distribution.metadata.get("Version", ""))
    classifiers = list(distribution.metadata.get_all("Classifier", []))
    checks = base_checks(
        name=distribution_name,
        version=version,
        classifiers=classifiers,
        require_version=require_version,
    )
    rubric_names: list[str] = []
    module_path: str | None = None
    taxonomy_version: str | None = None
    import_error: str | None = None

    if checks["distribution_name_is_canary"] and checks[
        "private_classifier_present"
    ]:
        try:
            package = importlib.import_module("canary")
            rubrics = importlib.import_module("canary.rubrics")
            module_path = str(Path(package.__file__).resolve())
            taxonomy_version = str(package.TAXONOMY_VERSION)
            rubric_names = sorted(rubrics.available_rubrics())
        except Exception as exc:  # pragma: no cover - environment-specific
            import_error = f"{type(exc).__name__}: {exc}"

    checks.update(
        {
            "package_imports": import_error is None and module_path is not None,
            "taxonomy_is_versioned": bool(taxonomy_version),
            "required_rubrics_present": REQUIRED_RUBRICS.issubset(rubric_names),
        }
    )
    return {
        "target": "installed",
        "name": distribution_name,
        "version": version,
        "distribution_root": str(distribution.locate_file("").resolve()),
        "module_path": module_path,
        "taxonomy_version": taxonomy_version,
        "classifiers": classifiers,
        "rubrics": rubric_names,
        "import_error": import_error,
        "checks": checks,
        "ok": all(checks.values()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a wheel or installed distribution is the Canary "
            "evaluation kernel, not the unrelated PyPI package of the same name."
        )
    )
    parser.add_argument("--wheel", type=Path, help="candidate wheel to inspect")
    parser.add_argument(
        "--require-version",
        help="fail unless the distribution has this exact version",
    )
    parser.add_argument(
        "--expected-sha256",
        help="fail unless the wheel has this lowercase SHA-256 hex digest",
    )
    args = parser.parse_args()
    if args.expected_sha256 and not args.wheel:
        parser.error("--expected-sha256 requires --wheel")
    if args.expected_sha256 and (
        len(args.expected_sha256) != 64
        or any(
            character not in "0123456789abcdefABCDEF"
            for character in args.expected_sha256
        )
    ):
        parser.error("--expected-sha256 must be 64 hexadecimal characters")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.wheel:
            report = inspect_wheel(
                args.wheel,
                require_version=args.require_version,
                expected_sha256=args.expected_sha256,
            )
        else:
            report = inspect_installed(require_version=args.require_version)
    except Exception as exc:
        report = {
            "target": "wheel" if args.wheel else "installed",
            "path": str(args.wheel.resolve()) if args.wheel else None,
            "error": f"{type(exc).__name__}: {exc}",
            "ok": False,
        }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
