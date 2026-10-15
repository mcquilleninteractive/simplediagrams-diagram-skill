"""Writes the `.simplediagram` folder around the two JSON files.

A document is a folder, not a zip. SimpleDiagrams refuses a package that has
any member besides `manifest.json`, `document.json` and `assets/`, including
`.DS_Store`, and requires `assets/` to exist even when empty.
"""

from __future__ import annotations

import json
from pathlib import Path

import sd_format as wire
from pydantic import ValidationError

PACKAGE_SUFFIX = ".simplediagram"


class PackageError(Exception):
    """The package could not be written."""


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
        PackageError: The destination already exists or cannot be written, or the text
            about to be written would not read back as a valid package.
    """
    if destination.suffix != PACKAGE_SUFFIX:
        raise PackageError(f"The document name must end in {PACKAGE_SUFFIX}: {destination}")
    manifest_text = _json(wire.dump(wire.manifest(document)))
    document_text = _json(wire.dump(document))
    # The exact text about to be written must read back as a valid package, as the app
    # will read it; this is checked in memory, so nothing is read from disk.
    try:
        wire.Manifest.model_validate_json(manifest_text)
        wire.Document.model_validate_json(document_text)
    except ValidationError as failure:
        raise PackageError(f"The document would not read back as valid; nothing written: {failure}") from failure
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
