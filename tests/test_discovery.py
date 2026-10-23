"""Verify that searching and building agree on the packaged shapes' exact references.

The real commands run in this process against the bundled list, the only shapes the
skill knows, so what search offers is exactly what the build places.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import sd_format as wire
from sd_spec import Catalog, lint


def _run(capsys: pytest.CaptureFixture[str], script: str, *arguments: object) -> SimpleNamespace:
    """Run a command's `main` in this process and capture what it prints."""
    module = importlib.import_module(script.removesuffix(".py"))
    code = module.main([str(argument) for argument in arguments])
    captured = capsys.readouterr()
    return SimpleNamespace(returncode=code, stdout=captured.out, stderr=captured.err)


def test_currency_search_includes_old_and_new_coins(capsys: pytest.CaptureFixture[str]) -> None:
    """Search reads descriptions and keywords, which must carry meanings for the original
    Biz shapes as well as the newer ones."""
    result = _run(capsys, "find_shapes.py", "currency", "--library", "biz", "--json")
    payload = json.loads(result.stdout)
    found = {shape["selector"] for shape in payload["matches"]}
    assert {
        "biz/CoinEuro", "biz/CoinDollar", "biz/CoinPound",
        "biz/coin-yen", "biz/coin-yuan", "biz/coin-swiss-franc",
    } <= found


def test_a_result_gives_its_selector_and_exact_reference(capsys: pytest.CaptureFixture[str]) -> None:
    """An agent copies the selector into a spec; the reference shown must be the one the
    build writes, and nothing in a result may point anywhere else."""
    match = json.loads(_run(capsys, "find_shapes.py", "cylinder", "--library", "basic", "--json").stdout)["matches"][0]
    assert match["selector"] == "basic/Cylinder"
    assert match["reference"] == {
        "library_id": "com.simplediagrams.shapeLibrary.basic", "item_id": "Cylinder", "asset_version": 1,
    }
    assert match["connection_points"] == "standard"
    assert not {"packaged", "placeable", "page_url", "source"} & set(match)


def test_search_lists_a_shapes_own_connection_points(capsys: pytest.CaptureFixture[str]) -> None:
    """An agent wiring a shape must see its own points to name one, in JSON and in the
    readable listing, and must be told when a shape takes no connector at all."""
    match = json.loads(_run(capsys, "find_shapes.py", "fork", "--library", "uml", "--json").stdout)["matches"][0]
    assert match["selector"] == "uml/fork-join-bar"
    assert match["connection_points"][0] == {"id": 0, "x": 0, "y": 0.5}
    assert "points: 0 (0, 0.5), 1 (1, 0.5)" in _run(capsys, "find_shapes.py", "fork", "--library", "uml").stdout
    marks = _run(capsys, "find_shapes.py", "loop", "--library", "bpmn").stdout
    assert "points: none; connectors cannot attach to it" in marks


def test_listing_names_the_eight_packaged_libraries(capsys: pytest.CaptureFixture[str]) -> None:
    """Run without a query, search lists each library once with its shape count."""
    lines = _run(capsys, "find_shapes.py").stdout.splitlines()
    assert [line.split()[0] for line in lines] == [
        "basic", "basicClean", "3DBasicHatch", "wordBubbles", "biz", "uiFlow", "bpmn", "uml",
    ]
    assert lines[-1].split()[-2:] == ["8", "shapes"]


def _one_node_spec(tmp_path: Path, shape: str) -> Path:
    """A one-node spec file placing `shape`."""
    spec = tmp_path / "diagram.json"
    spec.write_text(json.dumps({"name": "One", "pages": [{"nodes": [{"key": "n", "shape": shape, "x": 0, "y": 0}]}]}))
    return spec


def test_the_build_copies_the_packaged_reference_and_round_trips(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The app resolves a packaged shape only by its own names, so the build must write the
    reference search showed, unchanged, in a document that reads back without errors."""
    target = tmp_path / "Box.simplediagram"
    result = _run(capsys, "build_diagram.py", _one_node_spec(tmp_path, "basic/Square"), target)
    assert result.returncode == 0, result.stdout + result.stderr
    raw = json.loads((target / "document.json").read_text())
    assert raw["schema_version"] == 17 and "required_libraries" not in raw
    document = wire.Document.model_validate_json((target / "document.json").read_text())
    assert not [finding for finding in lint(document) if finding.severity == "error"]
    reference = document.pages[0].elements[0].core.symbol_reference
    assert reference is not None
    assert (reference.library_id, reference.item_id, reference.asset_version) == (
        "com.simplediagrams.shapeLibrary.basic", "Square", 1,
    )
    shape = Catalog.load().resolve("basic", "Square")
    assert shape is not None and shape.item_id == reference.item_id


def test_the_build_refuses_a_shape_it_does_not_package(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A shape from a downloadable library cannot be placed; the build writes nothing and
    says the shape is not packaged with SimpleDiagrams."""
    target = tmp_path / "Circuit.simplediagram"
    result = _run(capsys, "build_diagram.py", _one_node_spec(tmp_path, "notebook/transformer"), target)
    assert result.returncode == 1
    assert "not one of the shapes packaged with SimpleDiagrams 5.1.0" in result.stdout
    assert not target.exists()
