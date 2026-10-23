"""Check the bundled list of packaged shapes, and that the skill never reaches the network.

The list in assets/built-in-shapes.json is the skill's only source of library shapes.
These tests hold it to the rules the app applies to its own libraries, so a refresh
that breaks one fails here, and keep every script free of networking code, so the skill
stays as simple and as safe to run as it promises.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sd_spec import LIBRARY_PREFIX, Catalog

# Standard-library and common third-party modules that open connections. None of the
# skill's scripts may import one.
NETWORK_MODULES = frozenset(
    {
        "urllib", "http", "socket", "ssl", "ftplib", "smtplib", "imaplib", "poplib",
        "telnetlib", "xmlrpc", "asyncio", "requests", "httpx", "aiohttp", "urllib3",
    }
)


def _bundled() -> dict:
    return json.loads((ROOT / "assets" / "built-in-shapes.json").read_text(encoding="utf-8"))


def test_no_script_imports_a_networking_module() -> None:
    """The skill makes no network request; an import of a networking module is the first
    sign that one has crept back in, so it fails here before it can run."""
    found = []
    for path in sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "maintainers").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            found += [f"{path.name}: {name}" for name in names if name.split(".")[0] in NETWORK_MODULES]
    assert found == []


def test_the_list_holds_only_the_shapes_packaged_with_the_app() -> None:
    """Every library is one SimpleDiagrams ships, named by the app's own identifiers, and
    nothing in the list points at the website, so no shape can need a download."""
    bundled = _bundled()
    assert bundled["source_app_version"] == "5.1.0"
    assert [library["short_name"] for library in bundled["libraries"]] == [
        "basic", "basicClean", "3DBasicHatch", "wordBubbles", "biz", "uiFlow", "bpmn", "uml",
    ]
    for library in bundled["libraries"]:
        assert library["library_id"] == LIBRARY_PREFIX + library["short_name"]
    text = json.dumps(bundled)
    assert "published" not in text and "http" not in text
    assert len(Catalog.load().shapes) == 534


def test_every_selector_names_one_shape() -> None:
    """A spec names a shape as `<short name>/<item>`, so no two shapes may share one;
    item IDs differ only by case in a few places (Burst and burst), which must survive."""
    catalog = Catalog.load()
    selectors = [shape.selector for shape in catalog.shapes]
    assert len(selectors) == len(set(selectors))
    for item in ("Burst", "burst", "Star", "star"):
        shape = catalog.resolve("3DBasicHatch", item)
        assert shape is not None and shape.item_id == item


def test_connection_points_are_unique_and_inside_the_frame() -> None:
    """A repeated anchor number cannot say where a connector attaches, and a point
    outside the frame would pull the connector away from the shape."""
    for shape in Catalog.load().shapes:
        points = shape.connection_points or ()
        assert len({point_id for point_id, _, _ in points}) == len(points), shape.selector
        assert all(0 <= x <= 1 and 0 <= y <= 1 for _, x, y in points), shape.selector


def test_label_regions_take_the_apps_two_forms() -> None:
    """The app accepts a label region inside its shape, or one centred on it and wider for a
    name below a narrow shape (a BPMN event, the UML Actor); it refuses a file holding any
    other form, so a refreshed list must hold only these."""
    regions = [shape for shape in Catalog.load().shapes if shape.text_region is not None]
    assert regions
    for shape in regions:
        x, y, width, height = shape.text_region
        assert width > 0 and 0 < height and y >= 0 and y + height <= 1, shape.selector
        if x >= 0:
            assert x + width <= 1, shape.selector
        else:
            assert width == pytest.approx(1 - 2 * x) and width <= 8, shape.selector
