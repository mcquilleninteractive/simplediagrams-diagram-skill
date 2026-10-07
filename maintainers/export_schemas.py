# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Regenerates the JSON Schema files in schema/ from the Pydantic models.

The models in scripts/ are the source of truth. Run this after changing them;
tests fail if the committed schemas are stale.

    uv run maintainers/export_schemas.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sd_format as wire
from sd_spec import SPEC_VERSION, DiagramSpec

SCHEMA_BASE = "https://simplediagrams.com/schemas"


def schemas() -> dict[str, dict]:
    results = {}
    for filename, model, title in (
        (f"simplediagram-manifest-{wire.FORMAT_VERSION}.schema.json", wire.Manifest, "SimpleDiagrams manifest.json"),
        (f"simplediagram-document-{wire.FORMAT_VERSION}.schema.json", wire.Document, "SimpleDiagrams document.json"),
        (f"diagram-spec-{SPEC_VERSION}.schema.json", DiagramSpec, "SimpleDiagrams diagram spec"),
    ):
        schema = model.model_json_schema()
        results[filename] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{SCHEMA_BASE}/{filename}",
            **schema,
            "title": title,
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail if a committed schema is stale")
    arguments = parser.parse_args()
    stale = []
    for filename, schema in schemas().items():
        path = ROOT / "schema" / filename
        text = json.dumps(schema, indent=1, ensure_ascii=False) + "\n"
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(filename)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"Wrote {path.relative_to(ROOT)}")
    if stale:
        print("Stale schema files: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
