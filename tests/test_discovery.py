"""Verify catalogue search and document building share exact references and availability.

The real commands run in this process with the catalogue's one network request replaced
by a controlled snapshot, so no production service is contacted and nothing is cached.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import sd_catalog
import sd_format as wire
from sd_spec import Catalog, DiagramSpec, SpecError, compile_spec, lint
from test_catalog import _document

Serve = Callable[..., sd_catalog.ShapeLibraryCatalogue]


def _website_payload() -> dict[str, Any]:
    """One packaged and one downloadable library, as the website lists them."""
    payload = _document()
    downloaded = copy.deepcopy(payload["libraries"][0])
    downloaded.update(
        library_id="00000000-0000-4000-8000-000000000002",
        readable_id="com.simplediagrams.shapeLibrary.electronics",
        display_name="Electronics",
        built_in=False,
        page_url="https://simplediagrams.com/shape-libraries/electronics/",
    )
    shape = downloaded["shapes"][0]
    shape.update(
        item_id="00000000-0000-4000-8000-000000000003",
        slug="capacitor",
        display_name="Capacitor",
        description="Stores an electric charge.",
        keywords=["charge"],
        reference={
            "library_id": downloaded["library_id"],
            "item_id": "00000000-0000-4000-8000-000000000003",
            "asset_version": 1,
        },
    )
    payload["libraries"].append(downloaded)
    return payload


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Serve:
    """Answer the catalogue request with a snapshot, changed first when a test needs it."""

    def answer(change: Callable[[dict[str, Any]], None] | None = None) -> sd_catalog.ShapeLibraryCatalogue:
        payload = _website_payload()
        if change is not None:
            change(payload)
        catalogue = sd_catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(payload))
        monkeypatch.setattr(sd_catalog, "_fetch", lambda: catalogue)
        return catalogue

    return answer


def _run(capsys: pytest.CaptureFixture[str], script: str, *arguments: object) -> SimpleNamespace:
    """Run a command's `main` in this process and capture what it prints."""
    module = importlib.import_module(script.removesuffix(".py"))
    code = module.main([str(argument) for argument in arguments])
    captured = capsys.readouterr()
    return SimpleNamespace(returncode=code, stdout=captured.out, stderr=captured.err)


def _downloadable(payload: dict[str, Any]) -> dict[str, Any]:
    """The downloadable shape in the website snapshot."""
    library = next(lib for lib in payload["libraries"] if not lib["built_in"])
    return library["shapes"][0]


def test_search_offers_downloaded_match_with_exact_reference(
    serve: Serve, capsys: pytest.CaptureFixture[str]
) -> None:
    """A downloadable shape can be placed, and says it is not packaged, so an agent can
    still prefer a packaged shape where one fits as well."""
    catalogue = serve()
    result = _run(capsys, "find_shapes.py", "charge", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source"] == "live" and payload["total"] == 1
    match = payload["matches"][0]
    assert match["selector"] == "electronics/capacitor"
    assert match["placeable"] is True
    assert match["packaged"] is False
    assert match["reference"] == catalogue.libraries[1].shapes[0].reference.model_dump()
    assert match["page_url"].endswith("/electronics/")
    assert match["connection_points"] == "standard"
    for flag in ("--packaged", "--placeable"):
        filtered = _run(capsys, "find_shapes.py", "charge", flag, "--json")
        assert json.loads(filtered.stdout)["matches"] == [], flag


def test_search_lists_a_shapes_own_connection_points(
    serve: Serve, capsys: pytest.CaptureFixture[str]
) -> None:
    """An agent wiring a component must see its lead ends to name one, in JSON and in the
    readable listing, and must be told when a shape takes no connector at all."""
    points = [{"id": 8, "x": 0.0082, "y": 0.0736}, {"id": 9, "x": 0.9918, "y": 0.0736}]
    serve(lambda payload: _downloadable(payload).update(connection_points=points))

    match = json.loads(_run(capsys, "find_shapes.py", "charge", "--json").stdout)["matches"][0]
    assert match["connection_points"] == [
        {"id": 8, "x": 0.0082, "y": 0.0736}, {"id": 9, "x": 0.9918, "y": 0.0736},
    ]
    listing = _run(capsys, "find_shapes.py", "charge").stdout
    assert "points: 8 (0.0082, 0.0736), 9 (0.992, 0.0736)" in listing


def test_catalogue_text_is_listed_without_control_codes(
    serve: Serve, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catalogue text is untrusted; a direction control could reorder the listing, so it
    prints as a visible escape, and a tab or line break prints as a plain space."""
    serve(lambda payload: _downloadable(payload).update(description="Stores\u202e a\tcharge.\nFAKE  line"))

    listing = _run(capsys, "find_shapes.py", "charge").stdout
    assert "Stores\\u202e a charge. FAKE line" in listing
    assert "\u202e" not in listing and "\t" not in listing


def _circuit_spec(tmp_path: Path, shape: str) -> Path:
    """A one-node spec file placing `shape`."""
    spec = tmp_path / "diagram.json"
    spec.write_text(
        json.dumps(
            {
                "name": "Circuit",
                "pages": [{"nodes": [{"key": "c", "shape": shape, "x": 0, "y": 0}]}],
            }
        )
    )
    return spec


def test_downloaded_build_writes_format_16_naming_the_library(
    serve: Serve, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A downloaded shape is placed by its published reference, and the document names its
    library so the app can put the artwork in place or say which library to get."""
    catalogue = serve()
    target = tmp_path / "Circuit.simplediagram"
    result = _run(capsys, "build_diagram.py", _circuit_spec(tmp_path, "electronics/capacitor"), target)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((target / "manifest.json").read_text())
    raw = json.loads((target / "document.json").read_text())
    assert manifest["format_version"] == 16 and raw["schema_version"] == 15
    library = catalogue.libraries[1]
    assert raw["required_libraries"] == [
        {"library_id": library.library_id, "display_name": "Electronics"}
    ]
    document = wire.Document.model_validate_json((target / "document.json").read_text())
    catalog = Catalog.from_catalogue(catalogue, source="live")
    assert not [finding for finding in lint(document, catalog) if finding.severity == "error"]
    actual = document.pages[0].elements[0].core.symbol_reference
    assert actual is not None
    assert actual.model_dump() == library.shapes[0].reference.model_dump()
    assert "the Electronics library installed" in result.stdout
    assert "5.0.16 or later to open the file" in result.stdout


def test_packaged_build_stays_at_format_15(
    serve: Serve, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A document with only packaged shapes must keep opening in every app since 5.0.8."""
    serve()
    target = tmp_path / "Box.simplediagram"
    result = _run(capsys, "build_diagram.py", _circuit_spec(tmp_path, "basic/Square"), target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((target / "manifest.json").read_text())["format_version"] == 15
    raw = json.loads((target / "document.json").read_text())
    assert raw["schema_version"] == 14 and "required_libraries" not in raw


def test_packaged_build_copies_reference_and_round_trips(
    serve: Serve, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Public matching UUIDs must not replace the desktop's placement identifiers."""
    catalogue = serve()
    spec = tmp_path / "diagram.json"
    spec.write_text(
        json.dumps(
            {
                "name": "Box",
                "pages": [
                    {"nodes": [{"key": "box", "shape": "basic/Square", "x": 0, "y": 0}]}
                ],
            }
        )
    )
    target = tmp_path / "Box.simplediagram"
    result = _run(capsys, "build_diagram.py", spec, target)
    assert result.returncode == 0, result.stdout + result.stderr
    catalog = Catalog.from_catalogue(catalogue, source="live")
    document = wire.Document.model_validate_json((target / "document.json").read_text())
    assert not [finding for finding in lint(document, catalog) if finding.severity == "error"]
    actual = document.pages[0].elements[0].core.symbol_reference
    assert actual is not None
    assert (
        actual.model_dump() == catalogue.libraries[0].shapes[0].reference.model_dump()
    )


def test_offline_currency_search_includes_old_and_new_coins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fallback must carry meanings for the original Biz shapes too."""
    result = _run(capsys, "find_shapes.py", "currency", "--library", "biz", "--json", "--offline")
    payload = json.loads(result.stdout)
    assert payload["source"] == "bundled"
    found = {shape["selector"] for shape in payload["matches"]}
    assert {
        "biz/CoinEuro",
        "biz/CoinDollar",
        "biz/CoinPound",
        "biz/coin-yen",
        "biz/coin-yuan",
        "biz/coin-swiss-franc",
    } <= found


def test_packaged_item_case_is_preserved() -> None:
    """Distinct shipped Burst/burst items must survive API conversion unchanged."""
    snapshot = sd_catalog.load_catalogue(offline=True)
    catalog = Catalog.from_catalogue(snapshot.catalogue, source="bundled")
    for item in ("Burst", "burst", "Star", "star"):
        definition = catalog.resolve("3DBasicHatch", item)
        assert definition is not None and definition.item_id == item


def test_short_name_collision_requires_full_library_id() -> None:
    """One publisher must not silently replace another's short library selector."""
    payload = _website_payload()
    payload["libraries"][1]["readable_id"] = "com.another.basic"
    catalog = Catalog.from_catalogue(
        sd_catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(payload)),
        source="live",
    )
    assert catalog.resolve("basic", "Square") is None
    assert (
        catalog.resolve("com.simplediagrams.shapeLibrary.basic", "Square") is not None
    )
    spec = DiagramSpec.model_validate(
        {
            "name": "Ambiguous",
            "pages": [
                {"nodes": [{"key": "box", "shape": "basic/Square", "x": 0, "y": 0}]}
            ],
        }
    )
    with pytest.raises(SpecError):
        compile_spec(spec, catalog)
