"""Verify catalogue search and document building share exact references and availability.

Controlled cache snapshots exercise the real CLIs without production requests.
A downloadable match must be discoverable without becoming a successful missing
shape in a generated document.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import sd_catalog
from sd_package import check_package
from sd_spec import Catalog, DiagramSpec, SpecError, compile_spec
from test_catalog import _document


@pytest.fixture
def catalogue_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, sd_catalog.ShapeLibraryCatalogue]:
    """Keep one packaged and one downloadable reference in an isolated cache."""
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
    catalogue = sd_catalog.ShapeLibraryCatalogue.model_validate_json(
        json.dumps(payload)
    )
    monkeypatch.setattr(sd_catalog, "_fetch", lambda etag: (catalogue, '"controlled"'))
    path = tmp_path / "catalogue.json"
    result = sd_catalog.load_catalogue(cache_path=path)
    assert result.source == "live"
    return path, catalogue


def _run(
    script: str, cache: Path, *arguments: object
) -> subprocess.CompletedProcess[str]:
    """Exercise CLI entry points against an explicit offline snapshot."""
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / script),
            "--offline",
            "--catalogue-cache",
            str(cache),
            *map(str, arguments),
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd="/",
    )


def test_search_discloses_downloaded_match_and_exact_reference(
    catalogue_cache: tuple[Path, sd_catalog.ShapeLibraryCatalogue],
) -> None:
    """A semantic match stays useful without pretending its artwork can be placed."""
    cache, catalogue = catalogue_cache
    result = _run("find_shapes.py", cache, "charge", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source"] == "cache" and payload["total"] == 1
    match = payload["matches"][0]
    assert match["selector"] == "electronics/capacitor"
    assert match["placeable"] is False
    assert match["reference"] == catalogue.libraries[1].shapes[0].reference.model_dump()
    assert match["page_url"].endswith("/electronics/")
    filtered = _run("find_shapes.py", cache, "charge", "--placeable", "--json")
    assert json.loads(filtered.stdout)["matches"] == []


def test_downloaded_build_refuses_before_writing(
    catalogue_cache: tuple[Path, sd_catalog.ShapeLibraryCatalogue], tmp_path: Path
) -> None:
    """An installed-library assumption must never produce a placeholder-only success."""
    cache, _ = catalogue_cache
    spec = tmp_path / "diagram.json"
    spec.write_text(
        json.dumps(
            {
                "name": "Circuit",
                "pages": [
                    {
                        "nodes": [
                            {
                                "key": "c",
                                "shape": "electronics/capacitor",
                                "x": 0,
                                "y": 0,
                            }
                        ]
                    }
                ],
            }
        )
    )
    target = tmp_path / "Circuit.simplediagram"
    result = _run("build_diagram.py", cache, spec, target)
    assert result.returncode == 1
    assert "even when installed" in result.stdout
    assert not target.exists()


def test_packaged_build_copies_reference_and_round_trips(
    catalogue_cache: tuple[Path, sd_catalog.ShapeLibraryCatalogue], tmp_path: Path
) -> None:
    """Public matching UUIDs must not replace the desktop's placement identifiers."""
    cache, catalogue = catalogue_cache
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
    result = _run("build_diagram.py", cache, spec, target)
    assert result.returncode == 0, result.stdout + result.stderr
    catalog = Catalog.from_catalogue(catalogue, source="cache")
    document, findings = check_package(target, catalog)
    assert document is not None and not [
        finding for finding in findings if finding.severity == "error"
    ]
    actual = document.pages[0].elements[0].core.symbol_reference
    assert actual is not None
    assert (
        actual.model_dump() == catalogue.libraries[0].shapes[0].reference.model_dump()
    )


def test_offline_currency_search_includes_old_and_new_coins(tmp_path: Path) -> None:
    """The fallback must carry meanings for the original Biz shapes too."""
    result = _run(
        "find_shapes.py",
        tmp_path / "absent.json",
        "currency",
        "--library",
        "biz",
        "--json",
    )
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
    snapshot = sd_catalog.load_catalogue(
        offline=True, cache_path=Path("/nonexistent/no-cache.json")
    )
    catalog = Catalog.from_catalogue(snapshot.catalogue, source="bundled")
    for item in ("Burst", "burst", "Star", "star"):
        definition = catalog.resolve("3DBasicHatch", item)
        assert definition is not None and definition.item_id == item


def test_short_name_collision_requires_full_library_id(
    catalogue_cache: tuple[Path, sd_catalog.ShapeLibraryCatalogue],
) -> None:
    """One publisher must not silently replace another's short library selector."""
    _, snapshot = catalogue_cache
    payload = snapshot.model_dump(mode="json")
    payload["libraries"][1]["readable_id"] = "com.another.basic"
    catalog = Catalog.from_catalogue(
        sd_catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(payload)),
        source="cache",
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
