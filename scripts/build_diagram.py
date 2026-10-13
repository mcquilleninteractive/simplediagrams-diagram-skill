# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Checks a diagram spec and, given a name, builds the SimpleDiagrams document.

    uv run scripts/build_diagram.py spec.json                              # check only
    uv run scripts/build_diagram.py spec.json "Order flow.simplediagram"   # check, then write

The spec is the JSON described by schema/diagram-spec-1.schema.json. Without
an output name nothing is written, so a spec can be corrected and rechecked
freely. An existing document is never overwritten: build to a new name.
Exit status is 0 when the diagram is valid, 1 when it is not or could not be
written, and 2 with `--strict` when it is valid but has layout warnings.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError
from sd_package import PackageError, check_package, write_package
from sd_spec import Catalog, SpecError, compile_spec, lint, load_spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="Diagram spec JSON file")
    parser.add_argument(
        "output", type=Path, nargs="?", help="New document to write, ending in .simplediagram"
    )
    parser.add_argument("--strict", action="store_true", help="Treat layout warnings as a failure")
    parser.add_argument("--offline", action="store_true", help="Use cached or bundled metadata without a request")
    parser.add_argument("--refresh-catalogue", action="store_true", help="Revalidate the catalogue now")
    parser.add_argument("--catalogue-cache", type=Path, help="Use this cache file")
    arguments = parser.parse_args()

    catalog = Catalog.load_current(
        cache_path=arguments.catalogue_cache,
        offline=arguments.offline,
        refresh=arguments.refresh_catalogue,
    )
    print(f"Catalogue: {catalog.source}", file=sys.stderr)
    if catalog.warning:
        print(catalog.warning, file=sys.stderr)
    try:
        document = compile_spec(load_spec(arguments.spec), catalog)
    except (SpecError, ValidationError) as failure:
        for line in str(failure).splitlines():
            print(f"error   {line}")
        return 1

    findings = lint(document, catalog)
    errors = [finding for finding in findings if finding.severity == "error"]
    written: Path | None = None
    if arguments.output is not None and not errors:
        try:
            written = write_package(document, arguments.output)
        except PackageError as failure:
            print(f"error   {failure}")
            return 1
        # Read the package back, so what is reported is what is on disk.
        _, findings = check_package(written, catalog)
        errors = [finding for finding in findings if finding.severity == "error"]

    for finding in findings:
        print(f"{finding.severity:8}{finding.code}: {finding.message}")
    elements = sum(len(page.elements) for page in document.pages)
    connectors = sum(len(page.connections) for page in document.pages)
    summary = (
        f"{len(document.pages)} page(s), {elements} shape(s), {connectors} connector(s); "
        f"{len(errors)} error(s), {len(findings) - len(errors)} warning(s)"
    )
    if written is not None:
        print(f"Wrote {written} ({summary})")
    elif arguments.output is not None:
        print(f"Nothing written because of the errors above ({summary})")
    else:
        print(f"Checked {arguments.spec}; nothing written ({summary})")
    if errors:
        return 1
    return 2 if arguments.strict and findings else 0


if __name__ == "__main__":
    sys.exit(main())
