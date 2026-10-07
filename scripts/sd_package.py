"""Reads and writes the `.simplediagram` folder around the two JSON files.

A document is a folder, not a zip. SimpleDiagrams refuses a package that has
any member besides `manifest.json`, `document.json` and `assets/`, including
`.DS_Store`, and requires `assets/` to exist even when empty.
"""

from __future__ import annotations

import json
from pathlib import Path

import sd_format as wire
from pydantic import ValidationError
from sd_spec import Catalog, Finding, lint

PACKAGE_SUFFIX = ".simplediagram"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
EXPECTED_MEMBERS = {wire.MANIFEST_FILENAME, wire.DOCUMENT_FILENAME, wire.ASSETS_DIRECTORY}


class PackageError(Exception):
    """The package could not be written."""


class _DuplicateKey(ValueError):
    """A JSON object repeats a key."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _json(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n"


def write_package(document: wire.Document, destination: Path) -> Path:
    """Writes a document as a new package folder and returns its path.

    Nothing that already exists is ever replaced or removed: there is no
    reliable way to tell a document this skill wrote from one a person made.
    The destination directory is created exclusively before its files are
    written. A disk error can leave an incomplete new package at that path;
    the caller must choose a different name for a retry.

    Raises:
        PackageError: The destination already exists or cannot be written.
    """
    if destination.suffix != PACKAGE_SUFFIX:
        raise PackageError(f"The document name must end in {PACKAGE_SUFFIX}: {destination}")
    manifest_text = _json(wire.dump(wire.manifest()))
    document_text = _json(wire.dump(document))
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()
    except FileExistsError as failure:
        raise PackageError(
            f"{destination} already exists and will not be overwritten. Choose another name."
        ) from failure
    except OSError as failure:
        raise PackageError(f"Could not create {destination}: {failure.strerror}") from failure
    try:
        (destination / wire.ASSETS_DIRECTORY).mkdir()
        (destination / wire.MANIFEST_FILENAME).write_text(manifest_text, encoding="utf-8")
        (destination / wire.DOCUMENT_FILENAME).write_text(document_text, encoding="utf-8")
    except OSError as failure:
        raise PackageError(
            f"Could not complete {destination}: {failure.strerror}. The incomplete new package remains."
        ) from failure
    return destination


def _describe(error: ValidationError, filename: str) -> list[Finding]:
    findings = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "(top level)"
        findings.append(
            Finding(severity="error", code="invalid-" + filename.split(".")[0], message=f"{filename}: {location}: {detail['msg']}")
        )
    return findings


def check_package(path: Path, catalog: Catalog | None = None) -> tuple[wire.Document | None, list[Finding]]:
    """Checks a package folder the way SimpleDiagrams will when it opens it.

    Returns the parsed document when the files are valid, with every finding:
    errors that stop the app opening or drawing it, then layout warnings.
    """

    def error(code: str, message: str) -> Finding:
        return Finding(severity="error", code=code, message=message)

    if path.is_symlink() or not path.is_dir():
        return None, [error("not-a-package", f"{path} is not a folder. A document is a folder, not a zip.")]
    members = {entry.name: entry for entry in path.iterdir()}
    findings: list[Finding] = []
    for name in sorted(set(members) - EXPECTED_MEMBERS):
        findings.append(error("unexpected-member", f"Remove '{name}' from the package: the app rejects any extra member."))
    for name in sorted(EXPECTED_MEMBERS - set(members)):
        findings.append(error("missing-member", f"The package has no '{name}'."))
    for name, entry in members.items():
        if entry.is_symlink():
            findings.append(error("symlink", f"'{name}' is a symbolic link; the app rejects it."))
    assets = members.get(wire.ASSETS_DIRECTORY)
    if assets is not None and not assets.is_symlink():
        if not assets.is_dir():
            findings.append(error("missing-member", "'assets' must be a folder."))
        elif any(assets.iterdir()):
            findings.append(
                error("unexpected-asset", "'assets' must be empty: this skill writes no embedded files, and stray files such as .DS_Store are rejected.")
            )
    if findings:
        return None, findings

    limits = ((wire.MANIFEST_FILENAME, MAX_MANIFEST_BYTES), (wire.DOCUMENT_FILENAME, MAX_DOCUMENT_BYTES))
    raw: dict[str, bytes] = {}
    for name, limit in limits:
        file = members[name]
        if not file.is_file():
            return None, [error("missing-member", f"'{name}' must be a file.")]
        if file.stat().st_size > limit:
            return None, [error("too-large", f"'{name}' is larger than {limit} bytes.")]
        raw[name] = file.read_bytes()

    for name, content in raw.items():
        try:
            json.loads(content, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateKey as failure:
            # The app keeps the first of two equal keys and most parsers keep
            # the last, so such a file means different things to each.
            return None, [error("duplicate-key", f"{name}: the key '{failure}' appears twice in one object.")]
        except ValueError as failure:
            return None, [error("invalid-json", f"{name}: {failure}")]
    try:
        wire.Manifest.model_validate_json(raw[wire.MANIFEST_FILENAME])
    except ValidationError as failure:
        return None, _describe(failure, wire.MANIFEST_FILENAME)
    try:
        document = wire.Document.model_validate_json(raw[wire.DOCUMENT_FILENAME])
    except ValidationError as failure:
        return None, _describe(failure, wire.DOCUMENT_FILENAME)
    return document, lint(document, catalog)
