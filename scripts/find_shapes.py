"""Lists the library shapes a diagram spec can use, with their natural sizes.

    python3 scripts/find_shapes.py              # every library and its size
    python3 scripts/find_shapes.py arrow        # shapes whose name contains "arrow"
    python3 scripts/find_shapes.py --library biz

The `shape` column is the value to write in a node's `shape`. Needs no
packages beyond the standard library.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "assets" / "built-in-shapes.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?", default="", help="Text to look for in a shape's name")
    parser.add_argument("--library", default="", help="Limit to one library, by short name")
    arguments = parser.parse_args()

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    query = arguments.query.lower()
    if not query and not arguments.library:
        for library in catalog["libraries"]:
            print(f"{library['short_name']:14}{library['display_name']:18}{len(library['shapes'])} shapes")
        print("\nPass a word to search, or --library NAME to list one library.")
        return

    matches = 0
    for library in catalog["libraries"]:
        if arguments.library and library["short_name"].lower() != arguments.library.lower():
            continue
        for shape in library["shapes"]:
            if query in shape["item_id"].lower() or query in shape["display_name"].lower():
                reference = f"{library['short_name']}/{shape['item_id']}"
                size = f"{shape['default_width']:g} x {shape['default_height']:g}"
                print(f"{reference:44}{size:12}{shape['display_name']}")
                matches += 1
    if not matches:
        print("No shape matches. Run without arguments to see the libraries.")


if __name__ == "__main__":
    main()
