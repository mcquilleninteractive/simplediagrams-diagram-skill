"""Tests for the diagram spec compiler, layout checks and package writer.

The spec is how an agent actually authors a diagram, so these cover the
promises the skill makes about it: every compiled document is valid, shapes
resolve to ones the app ships, connectors attach and route cleanly, and the
package on disk has exactly the members the app accepts.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import fixtures
import sd_format as wire
from sd_package import PackageError, write_package
from sd_spec import (
    MAX_SPEC_BYTES,
    Catalog,
    CatalogShape,
    DiagramSpec,
    SpecError,
    app_requirements,
    compile_spec,
    lint,
    load_spec,
    terminal_safe,
)

SPEC_ID = "11111111-2222-4333-8444-555555555555"


def _spec(nodes: list[dict], edges: list[dict] | None = None) -> DiagramSpec:
    return DiagramSpec.model_validate(
        {"name": "Test", "id": SPEC_ID, "pages": [{"nodes": nodes, "edges": edges or []}]}
    )


def _box(key: str, col: float, row: float, **extra: object) -> dict:
    return {"key": key, "shape": "rectangle", "label": key, "col": col, "row": row} | extra


def _routes(document: wire.Document) -> list[list[tuple[float, float]]]:
    return [[(p.x, p.y) for p in c.content.points] for c in document.pages[0].connections]


def test_example_spec_compiles_clean() -> None:
    """The shipped example is what an agent copies first; it must build with
    no errors and no layout warnings."""
    spec = DiagramSpec.model_validate_json((ROOT / "assets" / "example-spec.json").read_bytes())
    assert lint(compile_spec(spec)) == []


def test_compiling_is_deterministic_for_a_given_document_id() -> None:
    """Rebuilding an edited spec must keep identifiers stable, so the result
    differs only where the spec did."""
    spec = _spec([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}])
    assert wire.dump(compile_spec(spec)) == wire.dump(compile_spec(spec))


def test_catalog_matches_what_the_compiler_writes() -> None:
    """Every catalogue shape must compile to a reference the catalogue itself
    resolves, or the app would draw placeholders."""
    catalog = Catalog.load()
    assert len(catalog.shapes) == 516
    # One library per page: a page holds at most 300 shapes and the catalogue has more.
    by_library: dict[str, list] = {}
    for shape in catalog.shapes:
        by_library.setdefault(shape.library_short_name, []).append(shape)
    placed = 0
    for library, shapes in by_library.items():
        nodes = [
            {"key": f"n{i}", "shape": f"{library}/{shape.item_id}", "x": i * 300.0, "y": 0.0}
            for i, shape in enumerate(shapes)
        ]
        document = compile_spec(_spec(nodes), catalog)
        assert [f for f in lint(document, catalog) if f.severity == "error"] == [], library
        placed += len(document.pages[0].elements)
    assert placed == len(catalog.shapes)
    document = compile_spec(
        _spec([{"key": "n0", "shape": "basic/Square", "x": 0.0, "y": 0.0}]), catalog
    )
    first = document.pages[0].elements[0].core
    assert (first.frame.width, first.frame.height) == (50, 50)
    assert first.style == wire.ElementStyle(fill_hex="#FFFFFF", stroke_hex="#000000", line_width=1.0)


def test_unknown_shape_is_refused_with_suggestions() -> None:
    """A misspelt shape must stop the build rather than become a placeholder."""
    with pytest.raises(SpecError, match="basic/Cylinder"):
        compile_spec(_spec([{"key": "a", "shape": "basic/cylinder", "col": 0, "row": 0}]))
    with pytest.raises(SpecError, match="not rectangle"):
        compile_spec(_spec([{"key": "a", "shape": "box", "col": 0, "row": 0}]))


def test_hand_written_unresolved_reference_is_a_lint_error() -> None:
    """The format allows any reference, so the check for shapes the app does
    not ship has to live in lint."""
    data = wire.dump(compile_spec(_spec([{"key": "a", "shape": "basic/Square", "col": 0, "row": 0}])))
    data["pages"][0]["elements"][0]["content"]["content"]["content"]["symbol_reference"]["asset_version"] = 2
    findings = lint(wire.Document.model_validate_json(json.dumps(data)))
    assert [f.code for f in findings if f.severity == "error"] == ["unresolved-shape"]


def test_nodes_are_centred_on_their_grid_position() -> None:
    """Centre placement is what lets different-sized shapes share a line."""
    document = compile_spec(
        _spec([_box("a", 0, 0), {"key": "b", "shape": "basic/Cylinder", "col": 1, "row": 0}])
    )
    frames = [element.core.frame for element in document.pages[0].elements]
    assert [frame.y + frame.height / 2 for frame in frames] == [160, 160]
    assert frames[1].x + frames[1].width / 2 == 440


def test_aligned_neighbours_get_one_straight_segment() -> None:
    """Nodes on one row connect with a single horizontal line, anchored
    mid-side on both shapes."""
    document = compile_spec(_spec([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}]))
    assert _routes(document) == [[(270, 160), (370, 160)]]
    core = document.pages[0].connections[0].content
    assert (core.start_attachment.connection_point_id, core.end_attachment.connection_point_id) == (1, 0)


def test_orthogonal_routes_have_no_diagonal_segments() -> None:
    """Every run of an orthogonal connector is horizontal or vertical, in
    every relative position and with forced sides."""
    positions = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (0.4, 1.3)]
    sides = [None, "left", "right", "top", "bottom"]
    for col, row in positions:
        for source_side in sides:
            for target_side in sides:
                edge = {"source": "a", "target": "b", "source_side": source_side, "target_side": target_side}
                document = compile_spec(_spec([_box("a", 0, 0), _box("b", col, row)], [edge]))
                points = _routes(document)[0]
                for (x1, y1), (x2, y2) in pairwise(points):
                    assert x1 == x2 or y1 == y2, (col, row, source_side, target_side, points)


def test_branches_from_one_anchor_share_a_channel() -> None:
    """Two connectors leaving the same side read as one branching line."""
    document = compile_spec(
        _spec(
            [_box("a", 0, 1), _box("b", 1, 0), _box("c", 1, 2)],
            [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
        )
    )
    first, second = _routes(document)
    assert first[1][0] == second[1][0]


def test_routes_avoid_shapes_in_the_way() -> None:
    """When the direct route would run through a third shape, another pair of
    sides is used instead."""
    document = compile_spec(
        _spec([_box("a", 0, 0), _box("m", 0, 1), _box("b", 1, 2)], [{"source": "a", "target": "b"}])
    )
    assert "connector-through-shape" not in {finding.code for finding in lint(document)}
    core = document.pages[0].connections[0].content
    assert (core.start_attachment.connection_point_id, core.end_attachment.connection_point_id) == (1, 0)


def test_unrelated_connectors_do_not_share_a_channel() -> None:
    """Two separate connectors must never be drawn on top of each other."""
    document = compile_spec(
        _spec(
            [_box("a", 0, 0), _box("b", 0, 1), _box("c", 1, 2), _box("d", 1, 3)],
            [{"source": "a", "target": "c"}, {"source": "b", "target": "d"}],
        )
    )
    first, second = _routes(document)
    assert abs(first[1][0] - second[1][0]) >= 16


def test_straight_and_curved_routes() -> None:
    """The two non-orthogonal styles keep both ends attached; curved adds one
    interior curve point."""
    nodes = [_box("a", 0, 0), _box("b", 1, 1)]
    straight = compile_spec(_spec(nodes, [{"source": "a", "target": "b", "route": "straight"}]))
    curved = compile_spec(_spec(nodes, [{"source": "a", "target": "b", "route": "curved"}]))
    assert len(_routes(straight)[0]) == 2
    assert [p.kind for p in curved.pages[0].connections[0].content.points] == ["straight", "curve", "straight"]


def test_short_outside_label_uses_the_shapes_own_label() -> None:
    """A label that fits the shape's width stays part of the shape, placed
    below it across the full width; the default stays inside."""
    document = compile_spec(
        _spec([
            {"key": "a", "shape": "biz/Database", "label": "DB", "col": 0, "row": 0, "scale": 2, "label_position": "below"},
            _box("b", 1, 0),
        ])
    )
    below, middle = (element.content.text_layout for element in document.pages[0].elements)
    assert (below.position, below.frame.x, below.frame.width) == ("below", 0, 1)
    assert middle is None
    assert document.pages[0].content.groups == []


def test_wide_outside_label_becomes_a_grouped_caption() -> None:
    """The app confines an outside label to its shape's width, so a label
    wider than a small icon is written as its own text, centred under the
    icon and grouped with it so the two move together."""
    document = compile_spec(
        _spec([{"key": "a", "shape": "biz/Database", "label": "Order database", "col": 0, "row": 0, "label_position": "below"}])
    )
    icon, caption = (element.core for element in document.pages[0].elements)
    assert (icon.text_content.string, caption.kind, caption.text_content.string) == ("", "text", "Order database")
    assert caption.frame.x + caption.frame.width / 2 == icon.frame.x + icon.frame.width / 2
    assert caption.frame.y >= icon.frame.y + icon.frame.height
    assert [{m.id for m in g.members} for g in document.pages[0].content.groups] == [{icon.id, caption.id}]
    assert lint(document) == []


def test_library_shapes_get_the_points_and_label_their_library_gives_them() -> None:
    """A shape placed by the skill must match one placed by hand in the app: a BPMN
    event's name sits below it, a task's text keeps clear of its picture, and a task
    mark offers connectors nothing to attach to (desktop ADR 0042)."""
    document = compile_spec(
        _spec([
            {"key": "start", "shape": "bpmn/start-event", "label": "Go", "col": 0, "row": 0},
            {"key": "task", "shape": "bpmn/user-task", "label": "Check", "col": 1, "row": 0},
            {"key": "loop", "shape": "bpmn/loop-mark", "col": 2, "row": 0},
            _box("plain", 3, 0),
        ])
    )
    start, task, loop, plain = (element for element in document.pages[0].elements)
    layout = start.content.text_layout
    assert (layout.position, layout.frame.x, layout.frame.width) == ("below", 0, 1)
    region = task.content.text_layout
    assert region.position == "middle"
    assert (region.frame.x, region.frame.y, region.frame.width, region.frame.height) == (
        0.07, 0.26, 0.86, 0.52
    )
    assert loop.core.connection_points == []
    assert start.core.connection_points == wire.standard_connection_points()
    assert plain.content.text_layout is None, "A shape whose library says nothing is unchanged."
    assert lint(document) == []


def test_the_spec_can_still_choose_the_label_position() -> None:
    """The library's placement is a default, not a rule: a spec that asks for the
    middle gets the middle, inside the library's own text area, as the Shape panel
    would give a copy placed by hand."""
    document = compile_spec(
        _spec([{"key": "e", "shape": "bpmn/start-event", "label": "Go", "col": 0, "row": 0,
                "label_position": "middle"}])
    )
    layout = document.pages[0].elements[0].content.text_layout
    assert (layout.position, layout.frame.width, layout.frame.height) == ("middle", 1, 1)


def test_an_edge_to_a_shape_without_connection_points_is_refused() -> None:
    """A task mark has no anchors, so a connector attached to it would name an anchor
    that does not exist and the app would refuse the whole document."""
    with pytest.raises(SpecError, match="has no connection points"):
        compile_spec(
            _spec(
                [_box("a", 0, 0), {"key": "loop", "shape": "bpmn/loop-mark", "col": 1, "row": 0}],
                [{"source": "a", "target": "loop"}],
            )
        )


def test_packaged_facts_come_from_the_apps_own_list() -> None:
    """The website copies the app's packaged libraries and may lag behind it, so a
    packaged library or shape it does not list yet is still offered, and a packaged
    shape's points and label come from the list made from the app, not from the website."""
    from sd_catalog import ShapeLibraryCatalogue, _bundled_catalogue

    bundled = json.loads(_bundled_catalogue().model_dump_json())
    without_bpmn = [
        library for library in bundled["libraries"]
        if library["readable_id"] != "com.simplediagrams.shapeLibrary.bpmn"
    ]
    assert len(without_bpmn) == len(bundled["libraries"]) - 1
    biz = next(lib for lib in without_bpmn if lib["readable_id"].endswith(".biz"))
    biz["shapes"] = [shape for shape in biz["shapes"] if shape["slug"] != "coin-yen"]
    website = ShapeLibraryCatalogue.model_validate_json(
        json.dumps(bundled | {"libraries": without_bpmn})
    )
    plain = Catalog.from_catalogue(website, source="live")
    assert plain.resolve("bpmn", "loop-mark") is None, "Without the app's list, nothing is added."

    merged = Catalog.from_catalogue(website, source="live", packaged=Catalog.load())
    mark = merged.resolve("bpmn", "loop-mark")
    assert mark is not None and mark.connection_points == ()
    assert merged.resolve("bpmn", "start-event").text_position == "below"
    assert merged.resolve("biz", "coin-yen") is not None, "A newer shape in a listed library."
    assert plain.resolve("biz", "coin-yen") is None
    assert len(merged.shapes) == len(Catalog.load().shapes)


def test_the_build_names_what_needs_a_newer_app() -> None:
    """A document is not wrong for needing a newer app, but whoever sends it must be
    able to say which version opens it: 5.0.11 for the newer line endings, and the
    release that first ships BPMN for its shapes."""
    plain = compile_spec(_spec([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}]))
    assert app_requirements(plain) == []
    newer = compile_spec(
        _spec(
            [_box("a", 0, 0), {"key": "e", "shape": "bpmn/end-event", "label": "Done", "col": 1, "row": 0}],
            [{"source": "a", "target": "e", "end_ending": "cross"}],
        )
    )
    needs = app_requirements(newer)
    assert len(needs) == 2
    assert needs[0].startswith("SimpleDiagrams 5.0.11 or later") and "cross" in needs[0]
    assert needs[1].startswith("the first SimpleDiagrams release after 5.0.16 or a later one")
    assert needs[1].endswith("1 BPMN shape added in that release; an earlier app draws it as a dashed placeholder")
    assert lint(newer) == [], "Needing a newer app is reported, never as a warning."


def test_each_newer_packaged_shape_names_the_release_that_added_it() -> None:
    """Biz and UI Flow grew after the format began; a document using a newer shape must
    say which release shows it, one line per release, oldest first, and a shape every
    app has must add nothing."""
    original = compile_spec(_spec([{"key": "m", "shape": "biz/Man", "col": 0, "row": 0}]))
    assert app_requirements(original) == []

    newer = compile_spec(
        _spec([
            {"key": "yen", "shape": "biz/coin-yen", "col": 0, "row": 0},
            {"key": "prompt", "shape": "uiFlow/ai-prompt-field", "col": 1, "row": 0},
            {"key": "yuan", "shape": "biz/coin-yuan", "col": 2, "row": 0},
            {"key": "m", "shape": "biz/Man", "col": 3, "row": 0},
        ])
    )
    assert app_requirements(newer) == [
        (
            "SimpleDiagrams 5.0.12 or later, for 1 UI Flow shape added in that release; an "
            "earlier app draws it as a dashed placeholder"
        ),
        (
            "SimpleDiagrams 5.0.16 or later, for 2 Biz shapes added in that release; an "
            "earlier app draws them as dashed placeholders"
        ),
    ]


def test_routes_do_not_run_through_labels_under_icons() -> None:
    """A connector leaving downward would cross a label placed below, so
    another side is chosen."""
    document = compile_spec(
        _spec(
            [{"key": "a", "shape": "biz/Database", "label": "Order database", "col": 0, "row": 0, "label_position": "below"}, _box("b", 0, 2)],
            [{"source": "a", "target": "b"}],
        )
    )
    assert "connector-through-label" not in {finding.code for finding in lint(document)}


def test_crowded_channels_stay_between_the_shapes() -> None:
    """Many unrelated connectors across one gap are packed closer rather than
    pushed into the shapes on either side."""
    nodes = [_box(f"l{i}", 0, i) for i in range(8)] + [_box(f"r{i}", 1, i) for i in range(8)]
    edges = [{"source": f"l{i}", "target": f"r{7 - i}"} for i in range(8)]
    document = compile_spec(_spec(nodes, edges))
    for route in _routes(document):
        assert all(280 <= x <= 360 for x, _ in route[1:-1]), route
    assert "connector-through-shape" not in {finding.code for finding in lint(document)}


def test_forced_sides_never_produce_empty_or_diagonal_segments() -> None:
    """Any pair of sides yields a drawable route, even an awkward one."""
    for col, row in [(1, 0), (-1, -1), (0, 1), (1.5, -2), (0.3, 0.2)]:
        for source_side in ("left", "right", "top", "bottom"):
            for target_side in ("left", "right", "top", "bottom"):
                edge = {"source": "a", "target": "b", "source_side": source_side, "target_side": target_side}
                points = _routes(compile_spec(_spec([_box("a", 0, 0), _box("b", col, row)], [edge])))[0]
                for (x1, y1), (x2, y2) in pairwise(points):
                    assert (x1 == x2) != (y1 == y2), (col, row, source_side, target_side, points)


@pytest.mark.parametrize(
    ("nodes", "edges", "code"),
    [
        ([_box("a", 0, 0), _box("b", 0.2, 0)], [], "shapes-overlap"),
        (
            [_box("a", 0, 0), _box("m", 1, 0), _box("b", 2, 0)],
            [{"source": "a", "target": "b", "route": "straight"}],
            "connector-through-shape",
        ),
        ([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}], "connectors-overlap"),
        ([_box("a", 0, 0, rotation=30), _box("b", 1, 0)], [{"source": "a", "target": "b"}], "rotated-end"),
        (
            [{"key": "a", "shape": "biz/Database", "label": "DB", "col": 0, "row": 0, "label_position": "below"}, _box("b", 0, 1)],
            [{"source": "a", "target": "b", "source_side": "bottom", "target_side": "top"}],
            "connector-through-label",
        ),
        (
            [_box("a", 0, 0), _box("b", 1, 0)],
            [{"source": "a", "target": "b", "source_side": "left", "target_side": "right"}],
            "connector-through-shape",
        ),
        ([_box("a", 0, 0, width=60, label="a much longer label than fits")], [], "label-overflow"),
        (
            [_box("a", 0, 0), _box("b", 1, 0), _box("c", 0, 1), _box("d", 1, 1)],
            [{"source": "a", "target": "d", "route": "straight"}, {"source": "b", "target": "c", "route": "straight"}],
            "connectors-cross",
        ),
    ],
)
def test_lint_reports_layout_problems(nodes: list[dict], edges: list[dict], code: str) -> None:
    """Each layout check fires on the arrangement it exists to catch."""
    assert code in {finding.code for finding in lint(compile_spec(_spec(nodes, edges)))}


@pytest.mark.parametrize(
    "bad",
    [
        {"nodes": [_box("a", 0, 0), _box("a", 1, 0)]},
        {"nodes": [_box("a", 0, 0)], "edges": [{"source": "a", "target": "ghost"}]},
        {"nodes": [_box("a", 0, 0)], "edges": [{"source": "a", "target": "a"}]},
        {"nodes": [{"key": "a", "shape": "rectangle", "col": 0}]},
        {"nodes": [{"key": "a", "shape": "rectangle", "col": 0, "row": 0, "x": 1, "y": 1}]},
        {"nodes": [_box("a", 0, 0, colour="#FFFFFF")]},
        {"nodes": [_box("a", 0, 0, label="bell\x01")]},
        {"nodes": [_box("a", 0, 0, label="x" * 2001)]},
        {"name": "tab\there", "nodes": [_box("a", 0, 0)]},
        {"nodes": [_box(f"n{i}", i, 0) for i in range(301)]},
        {"nodes": [_box("a", 0, 0), _box("b", 1, 0)], "edges": [{"source": "a", "target": "b"}] * 401},
        {"nodes": [_box("a", float("inf"), 0)]},
        {"nodes": [_box("a", 0, 0, width=float("nan"))]},
        {"nodes": [{"key": "a", "shape": "basic/Square", "col": 0, "row": 0, "scale": 1e308}]},
        {"nodes": []},
    ],
)
def test_malformed_specs_are_refused(bad: dict) -> None:
    """Spec mistakes are reported before anything is written."""
    with pytest.raises(ValidationError):
        DiagramSpec.model_validate({"name": "Bad", "pages": [bad]})


def test_package_has_exactly_the_three_members(tmp_path: Path) -> None:
    """The app refuses a package with any other member, or without assets/."""
    path = write_package(fixtures.full_profile_document(), tmp_path / "Doc.simplediagram")
    assert sorted(entry.name for entry in path.iterdir()) == ["assets", "document.json", "manifest.json"]
    assert list((path / "assets").iterdir()) == []
    written = wire.Document.model_validate_json((path / "document.json").read_text())
    assert written == fixtures.full_profile_document()


def test_nothing_that_exists_is_ever_overwritten(tmp_path: Path) -> None:
    """There is no way to tell a document this skill wrote from one a person
    made, so an existing path is always left exactly as it was."""
    document = fixtures.minimal_document()
    path = write_package(document, tmp_path / "Doc.simplediagram")
    before = (path / "document.json").read_bytes()
    with pytest.raises(PackageError, match="will not be overwritten"):
        write_package(fixtures.full_profile_document(), path)
    assert (path / "document.json").read_bytes() == before
    for kind in ("folder", "empty-folder", "file", "link"):
        other = tmp_path / f"{kind}.simplediagram"
        if kind == "folder":
            other.mkdir()
            (other / "keep.txt").write_text("mine")
        elif kind == "empty-folder":
            other.mkdir()
        elif kind == "file":
            other.write_text("mine")
        else:
            other.symlink_to(tmp_path / "missing")
        with pytest.raises(PackageError, match="will not be overwritten"):
            write_package(document, other)
    assert (tmp_path / "folder.simplediagram" / "keep.txt").read_text() == "mine"
    assert list((tmp_path / "empty-folder.simplediagram").iterdir()) == []
    assert (tmp_path / "file.simplediagram").read_text() == "mine"
    with pytest.raises(PackageError, match="must end in"):
        write_package(document, tmp_path / "Doc.json")


def _run(script: str, *arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--offline", *map(str, arguments)],
        capture_output=True, text=True, check=False, cwd="/",
    )


def test_build_checks_without_writing_then_writes_once(tmp_path: Path) -> None:
    """An agent corrects a spec by checking it repeatedly, so checking must
    write nothing, and the scripts must work from any working directory."""
    spec = ROOT / "assets" / "example-spec.json"
    checked = _run("build_diagram.py", spec)
    assert checked.returncode == 0 and "nothing written" in checked.stdout
    assert list(tmp_path.iterdir()) == []
    target = tmp_path / "Order flow.simplediagram"
    built = _run("build_diagram.py", spec, target)
    assert built.returncode == 0 and "Wrote" in built.stdout
    again = _run("build_diagram.py", spec, target)
    assert again.returncode == 1 and "will not be overwritten" in again.stdout
    assert wire.Document.model_validate_json((target / "document.json").read_text())


def test_build_refuses_bad_specs_before_writing(tmp_path: Path) -> None:
    """A spec that is too large, malformed or names an unknown shape is
    reported and leaves nothing on disk."""
    target = tmp_path / "Out.simplediagram"
    huge = tmp_path / "huge.json"
    huge.write_text(" " * (2 * 1024 * 1024 + 1))
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"name": "X", "pages": [{"nodes": [{"key": "a", "shape": "aws/S3", "col": 0, "row": 0}]}]}))
    for spec, message in ((huge, "limit"), (unknown, "not in the selected catalogue"), (tmp_path / "absent.json", "Cannot read")):
        result = _run("build_diagram.py", spec, target)
        assert result.returncode == 1 and message in result.stdout, result.stdout
    assert not target.exists()


def test_preview_is_well_formed_and_does_not_replace_files(tmp_path: Path) -> None:
    """A spec preview escapes text and preserves any existing output."""
    from xml.etree import ElementTree

    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"name": "P", "pages": [{"nodes": [_box("a", 0, 0, label="R&D <\"fast\">")]}]}))
    assert _run("preview_diagram.py", spec, tmp_path / "from-spec.svg").returncode == 0
    ElementTree.parse(tmp_path / "from-spec.svg")

    preview = tmp_path / "from-spec.svg"
    before = preview.read_bytes()
    assert _run("preview_diagram.py", spec, preview).returncode == 1
    assert preview.read_bytes() == before
    package = write_package(fixtures.minimal_document(), tmp_path / "Existing.simplediagram")
    assert _run("preview_diagram.py", package, tmp_path / "unused.svg").returncode == 1
    assert not (tmp_path / "unused.svg").exists()

    two_pages = tmp_path / "two-pages.json"
    two_pages.write_text(json.dumps({
        "name": "Two pages",
        "pages": [
            {"name": "One", "nodes": [_box("a", 0, 0)]},
            {"name": "Two", "nodes": [_box("b", 0, 0)]},
        ],
    }))
    (tmp_path / "two-2.svg").write_text("keep")
    assert _run("preview_diagram.py", two_pages, tmp_path / "two.svg").returncode == 1
    assert not (tmp_path / "two.svg").exists()
    assert (tmp_path / "two-2.svg").read_text() == "keep"


def test_versions_are_stated_consistently() -> None:
    """The skill, format, catalogue and minimum app versions each appear in
    several files; a release that updates only some of them would mislead."""
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    versions = (ROOT / "VERSIONS.md").read_text()
    catalog = json.loads((ROOT / "assets" / "built-in-shapes.json").read_text())
    assert f"| Skill | {plugin['version']} |" in versions
    assert f"| Package format | {wire.FORMAT_VERSION} |" in versions
    assert f"| Document schema | {wire.SCHEMA_VERSION} |" in versions
    assert f"| Package format, downloadable shapes | {wire.REQUIRED_LIBRARIES_FORMAT_VERSION} |" in versions
    assert f"| Document schema, downloadable shapes | {wire.REQUIRED_LIBRARIES_SCHEMA_VERSION} |" in versions
    assert f"from SimpleDiagrams {catalog['source_app_version']}" in versions
    assert catalog["source_app_version"] in (ROOT / "README.md").read_text()
    for name in (f"simplediagram-document-{wire.FORMAT_VERSION}", f"simplediagram-manifest-{wire.FORMAT_VERSION}", "diagram-spec-1"):
        assert (ROOT / "schema" / f"{name}.schema.json").is_file()


# ---------------------------------------------------------------------------
# Shapes from downloaded libraries (desktop ADR 0039)
# ---------------------------------------------------------------------------

NOTEBOOK_ID = "79FFE4B7-EA0D-87C3-AE89-D4CD62AF5202"
GARDEN_ID = "11111111-2222-4333-8444-666666666666"


def _downloaded(
    library_id: str, short: str, name: str, item: str, slug: str,
    points: tuple[tuple[int, float, float], ...] | None = None,
) -> CatalogShape:
    """A downloadable catalogue shape, with its own connection points when given."""
    return CatalogShape(
        library_id=library_id, library_short_name=short, library_display_name=name,
        asset_version=1, item_id=item, display_name=slug.title(), default_width=61,
        default_height=37.375, built_in=False, slug=slug, connection_points=points,
    )


def _catalog_with_downloads() -> Catalog:
    """The packaged list plus two invented downloadable libraries."""
    packaged = Catalog.load().shapes
    return Catalog(
        packaged
        + [
            _downloaded(NOTEBOOK_ID, "notebook", "Hobby Electronics Notebook",
                        "A5C619FD-0E22-8EF7-8299-45280EA3F738", "transformer"),
            _downloaded(NOTEBOOK_ID, "notebook", "Hobby Electronics Notebook",
                        "0B6E2C1A-6F3D-8E21-9C4B-7D5A1E2F3C4D", "switch"),
            _downloaded(GARDEN_ID, "garden", "Green Walls",
                        "22222222-3333-4444-8555-666666666666", "planter"),
        ],
        "test",
    )


def _downloaded_spec(*shapes: str) -> DiagramSpec:
    """One page placing each selector in a row."""
    return DiagramSpec.model_validate(
        {
            "name": "Downloaded shapes",
            "pages": [
                {
                    "nodes": [
                        {"key": f"n{index}", "shape": shape, "col": index, "row": 0}
                        for index, shape in enumerate(shapes)
                    ]
                }
            ],
        }
    )


def test_downloaded_shapes_are_placed_by_their_published_reference() -> None:
    """The app resolves the reference only if it is exactly the catalogue's."""
    document = compile_spec(_downloaded_spec("notebook/transformer"), _catalog_with_downloads())

    reference = document.pages[0].elements[0].core.symbol_reference
    assert reference is not None
    assert (reference.library_id, reference.item_id, reference.asset_version) == (
        NOTEBOOK_ID, "A5C619FD-0E22-8EF7-8299-45280EA3F738", 1,
    )


def test_each_downloaded_library_is_named_once_in_the_order_first_used() -> None:
    """The app names missing libraries from this list, so each appears once, by its name."""
    document = compile_spec(
        _downloaded_spec("notebook/transformer", "garden/planter", "notebook/switch", "basic/Square"),
        _catalog_with_downloads(),
    )

    assert document.schema_version == 15
    assert [(lib.library_id, lib.display_name) for lib in document.required_libraries or []] == [
        (NOTEBOOK_ID, "Hobby Electronics Notebook"), (GARDEN_ID, "Green Walls"),
    ]
    assert all(lib.minimum_revision is None for lib in document.required_libraries or [])


def test_a_document_of_packaged_shapes_names_no_library() -> None:
    """Only a downloaded shape makes a document format 16."""
    document = compile_spec(_downloaded_spec("basic/Square"), _catalog_with_downloads())

    assert document.schema_version == 14 and document.required_libraries is None


def test_lint_accepts_downloaded_shapes_and_still_flags_unknown_ones() -> None:
    """A catalogued downloaded shape is not a defect; a reference nothing knows still is."""
    catalog = _catalog_with_downloads()
    document = compile_spec(_downloaded_spec("notebook/transformer"), catalog)

    assert not [f for f in lint(document, catalog) if f.code == "unresolved-shape"]
    assert [f.code for f in lint(document) if f.severity == "error"] == ["unresolved-shape"]


def test_the_build_says_which_library_and_app_a_document_needs() -> None:
    """Whoever sends the file must be able to say what opens it and what shows its shapes."""
    needs = app_requirements(compile_spec(_downloaded_spec("notebook/transformer"), _catalog_with_downloads()))

    assert any(
        "Hobby Electronics Notebook library installed" in need
        and "first SimpleDiagrams release after 5.0.16" in need
        for need in needs
    )
    assert any("5.0.16 or later to open the file" in need for need in needs)


def test_paint_on_a_downloaded_shape_is_reported_as_unused() -> None:
    """The app draws a downloaded shape in its library's own colours, so a spec's paint on
    one would silently vanish; the same paint on a packaged shape is used and not reported."""
    catalog = _catalog_with_downloads()
    spec = _downloaded_spec("notebook/transformer", "basic/Square")
    painted = spec.model_copy(deep=True)
    for node in painted.pages[0].nodes:
        node.fill = "#FF0000"

    def codes(document_spec: DiagramSpec) -> list[str]:
        return [f.code for f in lint(compile_spec(document_spec, catalog), catalog)]

    assert codes(painted).count("downloaded-shape-paint") == 1
    assert "downloaded-shape-paint" not in codes(spec)


@pytest.mark.parametrize("name", ["Bad\nName", "\u202eEvil", "   ", "\u200b"])
def test_a_library_name_a_document_cannot_hold_stops_the_build_plainly(name: str) -> None:
    """Catalogue text is untrusted; a name the app would drop must fail the build with a
    message naming the library, not a validation dump."""
    odd = _downloaded(GARDEN_ID, "garden", name, "22222222-3333-4444-8555-666666666666", "planter")
    catalog = Catalog(Catalog.load().shapes + [odd], "test")
    with pytest.raises(SpecError, match=GARDEN_ID):
        compile_spec(_downloaded_spec("garden/planter"), catalog)


def test_more_libraries_than_a_document_can_name_stops_the_build_plainly() -> None:
    """The app keeps at most 64 entries, so a 65th library is refused with the reason."""
    shapes = [
        _downloaded(f"00000000-0000-4000-8000-{index:012d}", f"lib{index}", f"Library {index}",
                    f"00000000-0000-4000-9000-{index:012d}", "shape")
        for index in range(wire.MAX_REQUIRED_LIBRARIES + 1)
    ]
    catalog = Catalog(Catalog.load().shapes + shapes, "test")
    selectors = [f"lib{index}/shape" for index in range(wire.MAX_REQUIRED_LIBRARIES + 1)]
    with pytest.raises(SpecError, match="at most 64"):
        compile_spec(_downloaded_spec(*selectors), catalog)


def test_a_wide_label_on_a_downloaded_shape_becomes_a_grouped_caption() -> None:
    """A downloaded shape's label follows the same caption rule as a packaged one's."""
    spec = _downloaded_spec("notebook/transformer")
    node = spec.pages[0].nodes[0]
    node.label, node.label_position = "A label far wider than the shape", "below"
    page = compile_spec(spec, _catalog_with_downloads()).pages[0]

    shape, caption = page.elements
    assert shape.core.symbol_reference is not None and shape.core.text_content.string == ""
    assert caption.core.kind == "text"
    assert caption.core.text_content.string == "A label far wider than the shape"
    assert [{m.id for m in g.members} for g in page.content.groups] == [{shape.core.id, caption.core.id}]


def test_a_shared_short_name_gets_a_selector_that_still_builds() -> None:
    """Two libraries may share a short name; the selector offered must name one of them."""
    other = _downloaded(GARDEN_ID, "notebook", "Another Notebook",
                        "22222222-3333-4444-8555-777777777777", "transformer")
    catalog = Catalog(_catalog_with_downloads().shapes + [other], "test")
    selector = catalog.selector(other)

    assert selector == f"{GARDEN_ID}/transformer"
    reference = compile_spec(_downloaded_spec(selector), catalog).pages[0].elements[0].core.symbol_reference
    assert reference is not None and reference.item_id == other.item_id


def test_a_missing_downloadable_shape_says_how_to_find_it() -> None:
    """With only packaged shapes (offline, or after a failed request) the error says a
    downloadable shape needs the catalogue; with it, a mistyped slug is matched."""
    with pytest.raises(SpecError, match="needs a successful catalogue request"):
        compile_spec(_downloaded_spec("notebook/transformer"), Catalog.load())
    with pytest.raises(SpecError, match="notebook/transformer") as failure:
        compile_spec(_downloaded_spec("notebook/transform"), _catalog_with_downloads())
    assert "successful catalogue request" not in str(failure.value)


# ---------------------------------------------------------------------------
# Connection points: where a library puts them, and naming one
# ---------------------------------------------------------------------------

# A part with the standard eight plus a lead end near each corner, as electronics
# libraries give their components.
LEADS = (
    (0, 0.0, 0.5), (1, 1.0, 0.5), (2, 0.5, 0.0), (3, 0.5, 1.0), (4, 0.0, 0.0),
    (5, 0.0, 1.0), (6, 1.0, 0.0), (7, 1.0, 1.0), (8, 0.0082, 0.0736),
    (9, 0.0082, 0.9298), (10, 0.9918, 0.0736), (11, 0.9918, 0.9298),
)


def _parts_catalog(*shapes: CatalogShape) -> Catalog:
    """The packaged list plus the given test parts."""
    return Catalog(Catalog.load().shapes + list(shapes), "test")


def _part(slug: str, points: tuple[tuple[int, float, float], ...] | None) -> CatalogShape:
    """An invented part in a 'parts' library, with the given connection points."""
    return _downloaded(NOTEBOOK_ID, "parts", "Parts", f"00000000-0000-4000-8000-{len(slug):012d}", slug, points)


def _wired(nodes: list[dict], edges: list[dict]) -> DiagramSpec:
    """A one-page spec from raw node and edge dictionaries."""
    return DiagramSpec.model_validate({"name": "Wired", "pages": [{"nodes": nodes, "edges": edges}]})


def _end_points(document: wire.Document) -> list[tuple[int, float, float]]:
    """Each connector end as (anchor id, x, y), start then end."""
    ends = []
    for connection in document.pages[0].connections:
        core = connection.content
        for attachment, point in ((core.start_attachment, core.points[0]), (core.end_attachment, core.points[-1])):
            assert attachment is not None
            ends.append((attachment.connection_point_id, point.x, point.y))
    return ends


def _axis_aligned(document: wire.Document) -> bool:
    """Whether every connector segment on the first page is horizontal or vertical."""
    return all(
        abs(a.x - b.x) < 0.01 or abs(a.y - b.y) < 0.01
        for connection in document.pages[0].connections
        for a, b in pairwise(connection.content.points)
    )


def test_a_named_point_is_where_the_connector_attaches_and_starts() -> None:
    """A component's lead end is the point the wire meets; the route must start exactly
    there and stay square, or the app moves the end and bends the wire."""
    catalog = _parts_catalog(_part("transformer", LEADS))
    spec = _wired(
        [{"key": "t", "shape": "parts/transformer", "x": 100, "y": 100, "scale": 2},
         {"key": "load", "shape": "rectangle", "x": 400, "y": 100}],
        [{"source": "t", "target": "load", "source_point": 10, "end_ending": "none"}],
    )
    document = compile_spec(spec, catalog)

    frame = document.pages[0].elements[0].core.frame
    point_id, x, y = _end_points(document)[0]
    assert point_id == 10
    assert (x, y) == pytest.approx((frame.x + 0.9918 * frame.width, frame.y + 0.0736 * frame.height), abs=0.001)
    assert _axis_aligned(document)
    assert not [f for f in lint(document, catalog) if f.severity == "error"]


def test_a_lead_point_inside_a_large_shape_is_not_taken_for_a_crossing() -> None:
    """At a large scale a lead end sits several points inside the frame; the stub leaving
    it is not the connector running back through its own end."""
    catalog = _parts_catalog(_part("transformer", LEADS))
    spec = _wired(
        [{"key": "t", "shape": "parts/transformer", "x": 400, "y": 400, "scale": 8},
         {"key": "load", "shape": "rectangle", "x": 900, "y": 400}],
        [{"source": "t", "target": "load", "source_point": 10, "end_ending": "none"}],
    )
    document = compile_spec(spec, catalog)
    assert "connector-through-shape" not in {f.code for f in lint(document, catalog)}


def test_a_side_uses_the_librarys_own_position_for_its_anchor() -> None:
    """Anchor 0 is the left anchor wherever the library puts it; a route to it must end
    where it is, not at the middle of the side."""
    low_left = ((0, 0.0, 0.8), (1, 1.0, 0.5), (2, 0.5, 0.0), (3, 0.5, 1.0))
    catalog = _parts_catalog(_part("plug", low_left))
    spec = _wired(
        [{"key": "a", "shape": "rectangle", "x": 0, "y": 100},
         {"key": "p", "shape": "parts/plug", "x": 300, "y": 100, "scale": 2}],
        [{"source": "a", "target": "p", "target_side": "left"}],
    )
    document = compile_spec(spec, catalog)

    frame = document.pages[0].elements[1].core.frame
    assert _end_points(document)[1] == (0, frame.x, pytest.approx(frame.y + 0.8 * frame.height))
    assert _axis_aligned(document)


def test_only_sides_a_shape_has_an_anchor_on_are_chosen() -> None:
    """A shape with anchors only top and bottom is reached there, not refused because the
    first side tried had none."""
    catalog = _parts_catalog(_part("rail", ((2, 0.5, 0.0), (3, 0.5, 1.0))))
    spec = _wired(
        [{"key": "a", "shape": "rectangle", "x": 0, "y": 100},
         {"key": "r", "shape": "parts/rail", "x": 300, "y": 100}],
        [{"source": "a", "target": "r"}],
    )
    document = compile_spec(spec, catalog)

    assert _end_points(document)[1][0] in {2, 3}
    assert _axis_aligned(document)


def test_a_shape_with_only_lead_ends_asks_for_one_by_name() -> None:
    """With no anchor in the middle of a side there is nothing to choose automatically; the
    message lists the points so the next attempt can name one."""
    catalog = _parts_catalog(_part("diode", ((8, 0.0, 0.5), (9, 1.0, 0.5))))
    nodes = [{"key": "d", "shape": "parts/diode", "x": 0, "y": 0},
             {"key": "b", "shape": "rectangle", "x": 300, "y": 0}]
    with pytest.raises(SpecError, match=r"name one of its points with source_point: 8, 9"):
        compile_spec(_wired(nodes, [{"source": "d", "target": "b"}]), catalog)

    document = compile_spec(_wired(nodes, [{"source": "d", "target": "b", "source_point": 9}]), catalog)
    assert _end_points(document)[0][0] == 9


def test_a_point_the_shape_lacks_is_refused_with_the_ones_it_has() -> None:
    """A mistyped point id must not attach somewhere else."""
    nodes = [{"key": "a", "shape": "rectangle", "x": 0, "y": 0},
             {"key": "b", "shape": "rectangle", "x": 300, "y": 0}]
    with pytest.raises(SpecError, match=r"no connection point 42\. Its points are 0, 1, 2, 3, 4, 5, 6, 7"):
        compile_spec(_wired(nodes, [{"source": "a", "target": "b", "target_point": 42}]))


def test_a_side_and_a_point_for_one_end_are_refused() -> None:
    """They name two different anchors; the spec must say which."""
    with pytest.raises(ValidationError, match="source_side or source_point, not both"):
        _wired(
            [{"key": "a", "shape": "rectangle", "x": 0, "y": 0},
             {"key": "b", "shape": "rectangle", "x": 300, "y": 0}],
            [{"source": "a", "target": "b", "source_side": "right", "source_point": 1}],
        )


def test_a_straight_line_with_one_fixed_side_keeps_the_best_other_side() -> None:
    """The wider side search scores orthogonal routes; a straight or curved line must keep
    the plain choice, or it starts on a side facing away and cuts through both shapes."""
    for route in ("straight", "curved"):
        spec = _wired(
            [{"key": "a", "shape": "rectangle", "col": 0, "row": 0},
             {"key": "b", "shape": "rectangle", "col": 1, "row": 0}],
            [{"source": "a", "target": "b", "target_side": "right", "route": route}],
        )
        document = compile_spec(spec)
        assert [end[0] for end in _end_points(document)] == [1, 1], route


def test_a_corner_point_leaves_by_the_side_facing_the_other_end() -> None:
    """A corner lies on two sides; the route leaves by the one toward its target."""
    spec = _wired(
        [{"key": "a", "shape": "rectangle", "x": 0, "y": 0},
         {"key": "b", "shape": "rectangle", "x": 400, "y": 0}],
        [{"source": "a", "target": "b", "source_point": 6}],
    )
    points = compile_spec(spec).pages[0].connections[0].content.points
    assert points[0].y == points[1].y and points[1].x > points[0].x


# ---------------------------------------------------------------------------
# Untrusted input: bounded reads and what reaches the terminal
# ---------------------------------------------------------------------------

def test_a_spec_is_read_only_up_to_its_limit(tmp_path: Path) -> None:
    """The size a file reports can be wrong, so the bytes actually read are what count:
    a pipe is refused at once rather than read without end, and an oversized file is
    refused by what was read."""
    pipe = tmp_path / "spec.json"
    os.mkfifo(pipe)
    with pytest.raises(SpecError, match="not a regular file"):
        load_spec(pipe)
    large = tmp_path / "large.json"
    large.write_bytes(b" " * (MAX_SPEC_BYTES + 1))
    with pytest.raises(SpecError, match=f"over the limit of {MAX_SPEC_BYTES} bytes"):
        load_spec(large)


def test_an_oversized_file_is_not_read_past_its_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing after reading everything would still let a huge file exhaust memory; the
    reader must stop one byte past the limit."""
    import sd_spec

    consumed: list[int] = []

    class Counting(io.BufferedReader):
        def read(self, size: int | None = -1) -> bytes:
            data = super().read(size)
            consumed.append(len(data))
            return data

    monkeypatch.setattr(sd_spec.os, "fdopen", lambda descriptor, mode: Counting(io.FileIO(descriptor, mode)))
    big = tmp_path / "big.json"
    big.write_bytes(b" " * 10_000)
    with pytest.raises(sd_spec.FileTooLarge):
        sd_spec.read_limited(big, 100)
    assert sum(consumed) == 101


def test_building_and_previewing_store_nothing_but_the_named_output(tmp_path: Path) -> None:
    """The skill keeps no state: with an empty home and working folder, a build and a
    preview leave exactly the document and picture they were asked for."""
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    spec = ROOT / "assets" / "example-spec.json"
    environment = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    for script, output in (("build_diagram.py", "Out.simplediagram"), ("preview_diagram.py", "out.svg")):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--offline", str(spec), output],
            capture_output=True, text=True, check=False, cwd=work, env=environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert list(home.iterdir()) == []
    assert sorted(path.name for path in work.iterdir()) == ["Out.simplediagram", "out.svg"]


def test_a_folder_is_refused_as_a_spec(tmp_path: Path) -> None:
    """A folder where a file belongs is the commonest wrong path; it must get the plain
    message, and reading it must not leave a file open."""
    folder = tmp_path / "spec.json"
    folder.mkdir()
    before = len(os.listdir("/dev/fd"))
    for _ in range(5):
        with pytest.raises(SpecError, match="not a regular file"):
            load_spec(folder)
    assert len(os.listdir("/dev/fd")) == before




def test_a_selector_with_a_control_character_is_refused() -> None:
    """A selector is echoed in messages, so it may not carry terminal control codes."""
    with pytest.raises(ValidationError, match="control character U\\+001B"):
        _spec([{"key": "a", "shape": "basic/\x1b]52;c;SGk=\x07", "col": 0, "row": 0}])


def test_control_codes_in_input_reach_the_terminal_only_as_escapes(tmp_path: Path) -> None:
    """An unknown key is echoed in the error, and a spec can name any key; an escape
    sequence there (this one would set the clipboard) must print as visible text."""
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "name": "Escapes",
        "pages": [{"nodes": [{"key": "a", "shape": "rectangle", "col": 0, "row": 0,
                              "\x1b]52;c;SGk=\x07": 1}]}],
    }))
    result = _run("build_diagram.py", spec)

    assert result.returncode == 1
    assert "\x1b" not in result.stdout and "\x07" not in result.stdout
    assert "\\u001b]52;c;SGk=\\u0007" in result.stdout


def test_terminal_safe_keeps_line_breaks_and_json_meaning() -> None:
    """Escaping must not change what JSON output says, only how it can act on a terminal."""
    text = json.dumps({"name": "a\u202eb\u009bc"}, ensure_ascii=False, indent=1)
    safe = terminal_safe(text)
    assert "\u202e" not in safe and "\u009b" not in safe and "\n" in safe
    assert json.loads(safe) == json.loads(text)

