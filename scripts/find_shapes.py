# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Search published shape metadata and show which references can be placed.

    uv run scripts/find_shapes.py
    uv run scripts/find_shapes.py currency --packaged
    uv run scripts/find_shapes.py capacitor --json

The skill asks the public catalogue once per run and stores nothing; offline, or if the
request fails, it uses its bundled list of packaged shapes. Every shape can be placed. A packaged shape ships inside SimpleDiagrams; a
downloadable one needs its library installed, and a document that uses one names that
library. A search for something SimpleDiagrams draws itself,
such as a pool, a class box or a lifeline, also names the complex shape to use.
"""

from __future__ import annotations

import sys

# The skill writes nothing but the output it is asked for, not even Python's bytecode.
sys.dont_write_bytecode = True

import argparse
import json

from sd_spec import Catalog, CatalogShape, echo

# The shapes SimpleDiagrams draws itself are not catalogue shapes: a spec names them
# by kind, with their own fields (SKILL.md, "Complex shapes"). A search using one of these
# words says which kind draws it.
COMPLEX_SHAPE_HINTS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "container",
        (
            "a box that holds shapes: a BPMN expanded sub-process, a UML system boundary, or a "
            "sequence diagram's frame or alt, loop or opt fragment"
        ),
        frozenset({"container", "boundary", "frame", "fragment", "sub-process", "subprocess", "alt", "loop", "opt"}),
    ),
    (
        "swimlanes",
        "lanes of a process, such as a BPMN pool and its lanes",
        frozenset({"swimlane", "swimlanes", "lane", "lanes", "pool", "pools"}),
    ),
    (
        "table",
        "rows and columns of text, such as a UML class, interface, enumeration or database entity",
        frozenset({"table", "class", "interface", "enumeration", "enum", "entity", "erd"}),
    ),
    (
        "callout",
        "a speech bubble whose tail points at a shape",
        frozenset({"callout", "speech", "bubble"}),
    ),
    (
        "lifeline",
        "a UML sequence diagram's participant, its messages attached along its line",
        frozenset({"lifeline", "lifelines", "sequence", "message", "messages", "participant"}),
    ),
)


def complex_shape_hints(query: str) -> list[dict[str, str]]:
    """The complex shapes a search's words name, each with what it draws."""
    words = set(query.casefold().split())
    return [{"shape": kind, "draws": draws} for kind, draws, names in COMPLEX_SHAPE_HINTS if words & names]


def _match(shape: CatalogShape, query: str) -> bool:
    """Search meanings and aliases as well as visible names and identifiers."""
    text = " ".join(
        (
            shape.item_id,
            shape.slug,
            shape.display_name,
            shape.description,
            *shape.keywords,
        )
    ).casefold()
    return all(word in text for word in query.casefold().split())


def _one_line(text: str) -> str:
    """Catalogue text on one line, so a line break in it cannot pose as another result."""
    return " ".join(text.split())


def _points_text(shape: CatalogShape) -> str:
    """A shape's own connection points as `id (x, y)`, in fractions of its frame."""
    points = shape.connection_points or ()
    if not points:
        return "none; connectors cannot attach to it"
    return ", ".join(f"{point_id} ({x:.3g}, {y:.3g})" for point_id, x, y in points)


def _record(shape: CatalogShape, catalog: Catalog) -> dict[str, object]:
    """Expose the reference unchanged alongside a clear placement capability."""
    return {
        "selector": catalog.selector(shape),
        "library": shape.library_display_name,
        "readable_library_id": shape.readable_library_id,
        "display_name": shape.display_name,
        "description": shape.description,
        "keywords": list(shape.keywords),
        "default_width": shape.default_width,
        "default_height": shape.default_height,
        "placeable": True,
        "packaged": shape.built_in,
        "connection_points": (
            "standard"
            if shape.connection_points is None
            else [{"id": i, "x": x, "y": y} for i, x, y in shape.connection_points]
        ),
        "page_url": shape.page_url,
        "reference": {
            "library_id": shape.library_id,
            "item_id": shape.item_id,
            "asset_version": shape.asset_version,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Load one snapshot and print a bounded search result or library summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "query",
        nargs="?",
        default="",
        help="Text to search in names, descriptions and keywords",
    )
    parser.add_argument(
        "--library", default="", help="Library short name, readable ID or reference ID"
    )
    parser.add_argument(
        "--packaged",
        "--placeable",
        dest="packaged",
        action="store_true",
        help="Show only packaged shapes, which need no library installed "
        "(--placeable is the old name)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Show structured search results"
    )
    parser.add_argument(
        "--limit", type=int, default=30, help="At most 300 results; default 30"
    )
    parser.add_argument("--offset", type=int, default=0, help="Skip this many matches")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the packaged shapes only, without a request",
    )
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.limit <= 300 or arguments.offset < 0:
        parser.error("--limit must be 1 to 300 and --offset must be nonnegative")
    catalog = Catalog.load_current(offline=arguments.offline)
    echo(f"Catalogue: {catalog.source}", file=sys.stderr)
    if catalog.warning:
        echo(catalog.warning, file=sys.stderr)
    shapes = [
        shape
        for shape in catalog.shapes
        if (not arguments.packaged or shape.built_in)
        and (
            not arguments.library
            or arguments.library.casefold()
            in {
                shape.library_short_name.casefold(),
                shape.readable_library_id.casefold(),
                shape.library_id.casefold(),
            }
        )
        and _match(shape, arguments.query)
    ]
    if not arguments.query and not arguments.library and not arguments.json:
        libraries: dict[str, tuple[CatalogShape, int]] = {}
        for shape in shapes:
            previous = libraries.get(shape.library_id)
            libraries[shape.library_id] = (
                shape,
                1 if previous is None else previous[1] + 1,
            )
        for shape, count in libraries.values():
            status = "packaged" if shape.built_in else "downloadable"
            echo(
                f"{shape.library_short_name:24} {_one_line(shape.library_display_name):32} {count:4} shapes  {status}"
            )
        return 0
    shown = shapes[arguments.offset : arguments.offset + arguments.limit]
    hints = complex_shape_hints(arguments.query)
    if arguments.json:
        echo(
            json.dumps(
                {
                    "source": catalog.source,
                    "total": len(shapes),
                    "matches": [_record(shape, catalog) for shape in shown],
                    **({"complex_shapes": hints} if hints else {}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for shape in shown:
            status = "packaged" if shape.built_in else "downloadable"
            size = f"{shape.default_width:g} x {shape.default_height:g}"
            echo(f"{catalog.selector(shape):50} {size:14} {_one_line(shape.display_name)}  [{status}]")
            if shape.description:
                echo(f"  {_one_line(shape.description)}")
            if shape.connection_points is not None:
                echo(f"  points: {_points_text(shape)}")
        echo(
            f"{len(shown)} of {len(shapes)} matches; use --offset and --limit to see more."
        )
        for hint in hints:
            echo(
                f"Also: shape \"{hint['shape']}\" draws {hint['draws']}; SimpleDiagrams draws it "
                "itself (SKILL.md, Complex shapes)."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
