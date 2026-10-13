# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Search published shape metadata and show which references can be placed.

    uv run scripts/find_shapes.py
    uv run scripts/find_shapes.py currency --placeable
    uv run scripts/find_shapes.py capacitor --json

The skill uses the public catalogue, a validated cache, or its bundled offline
fallback. Downloaded shapes are discoverable; desktop 5.0.16 cannot yet resolve
their references in generated documents. Packaged selectors can be built.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sd_spec import Catalog, CatalogShape


def _match(shape: CatalogShape, query: str) -> bool:
    """Search meanings and aliases as well as visible names and identifiers."""
    text = " ".join((shape.item_id, shape.slug, shape.display_name, shape.description, *shape.keywords)).casefold()
    return all(word in text for word in query.casefold().split())


def _record(shape: CatalogShape) -> dict:
    """Expose the reference unchanged alongside a clear placement capability."""
    return {
        "selector": shape.selector,
        "library": shape.library_display_name,
        "readable_library_id": shape.readable_library_id,
        "display_name": shape.display_name,
        "description": shape.description,
        "keywords": list(shape.keywords),
        "default_width": shape.default_width,
        "default_height": shape.default_height,
        "placeable": shape.built_in,
        "page_url": shape.page_url,
        "reference": {
            "library_id": shape.library_id,
            "item_id": shape.item_id,
            "asset_version": shape.asset_version,
        },
    }


def main() -> int:
    """Load one snapshot and print a bounded search result or library summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?", default="", help="Text to search in names, descriptions and keywords")
    parser.add_argument("--library", default="", help="Library short name, readable ID or reference ID")
    parser.add_argument("--placeable", action="store_true", help="Show only packaged shapes the builder can place")
    parser.add_argument("--json", action="store_true", help="Show structured search results")
    parser.add_argument("--limit", type=int, default=30, help="At most 300 results; default 30")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many matches")
    parser.add_argument("--offline", action="store_true", help="Use cached or bundled metadata without a request")
    parser.add_argument("--refresh-catalogue", action="store_true", help="Revalidate the catalogue now")
    parser.add_argument("--catalogue-cache", type=Path, help="Use this cache file")
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 300 or arguments.offset < 0:
        parser.error("--limit must be 1 to 300 and --offset must be nonnegative")
    catalog = Catalog.load_current(
        cache_path=arguments.catalogue_cache,
        offline=arguments.offline,
        refresh=arguments.refresh_catalogue,
    )
    print(f"Catalogue: {catalog.source}", file=sys.stderr)
    if catalog.warning:
        print(catalog.warning, file=sys.stderr)
    shapes = [
        shape for shape in catalog.shapes
        if (not arguments.placeable or shape.built_in)
        and (not arguments.library or arguments.library.casefold() in {
            shape.library_short_name.casefold(), shape.readable_library_id.casefold(),
            shape.library_id.casefold(),
        })
        and _match(shape, arguments.query)
    ]
    if not arguments.query and not arguments.library and not arguments.json:
        libraries: dict[str, tuple[CatalogShape, int]] = {}
        for shape in shapes:
            previous = libraries.get(shape.library_id)
            libraries[shape.library_id] = (shape, 1 if previous is None else previous[1] + 1)
        for shape, count in libraries.values():
            status = "packaged" if shape.built_in else "discovery only"
            print(f"{shape.library_short_name:24} {shape.library_display_name:32} {count:4} shapes  {status}")
        return 0
    shown = shapes[arguments.offset:arguments.offset + arguments.limit]
    if arguments.json:
        print(json.dumps({"source": catalog.source, "total": len(shapes), "matches": [_record(shape) for shape in shown]}, ensure_ascii=False, indent=2))
    else:
        for shape in shown:
            status = "packaged" if shape.built_in else "discovery only"
            size = f"{shape.default_width:g} x {shape.default_height:g}"
            print(f"{shape.selector:50} {size:14} {shape.display_name}  [{status}]")
            if shape.description:
                print(f"  {shape.description}")
        print(f"{len(shown)} of {len(shapes)} matches; use --offset and --limit to see more.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
