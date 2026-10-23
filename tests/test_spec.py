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
import shutil
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
    assert len(catalog.shapes) == 534
    # One library per page: a page holds at most 300 shapes and the catalogue has more.
    by_library: dict[str, list] = {}
    for shape in catalog.shapes:
        by_library.setdefault(shape.library_short_name, []).append(shape)
    placed = 0
    for library, shapes in by_library.items():
        nodes = [
            {"key": f"n{i}", "shape": f"{library}/{shape.item_id}", "label": "Name",
             "x": i * 300.0, "y": 0.0}
            for i, shape in enumerate(shapes)
        ]
        document = compile_spec(_spec(nodes), catalog)
        assert [f for f in lint(document, catalog) if f.severity == "error"] == [], library
        # A library's own label region is written exactly as the app gives a placed copy.
        for element, shape in zip(document.pages[0].elements, shapes, strict=True):
            layout = element.content.text_layout
            if shape.text_region is not None:
                assert layout is not None, shape.item_id
                frame = layout.frame
                assert (frame.x, frame.y, frame.width, frame.height) == shape.text_region, shape.item_id
        placed += sum(1 for e in document.pages[0].elements if e.core.symbol_reference)
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


def test_wide_outside_label_gets_a_wider_region_centred_on_its_shape() -> None:
    """An outside label wraps at its region's width, so a label wider than a small icon
    keeps to the icon but in a region as wide as it needs, centred on the icon, as the
    app's own libraries centre a long name; the region still touches the shape."""
    document = compile_spec(
        _spec([{"key": "a", "shape": "biz/Database", "label": "Order database", "col": 0, "row": 0, "label_position": "below"}])
    )
    (icon,) = document.pages[0].elements
    layout = icon.content.text_layout
    assert icon.core.text_content.string == "Order database" and layout is not None
    assert layout.position == "below" and layout.frame.width > 1
    assert layout.frame.x == pytest.approx((1 - layout.frame.width) / 2, abs=0.001)
    assert document.pages[0].content.groups == []
    assert lint(document) == []


def test_an_outside_region_is_at_most_eight_times_its_shape() -> None:
    """Eight times the shape is the widest region the app keeps; past it the label wraps."""
    document = compile_spec(_spec([{"key": "a", "shape": "rectangle", "label": "x" * 400, "col": 0, "row": 0,
                                    "width": 10, "height": 10, "label_position": "above"}]))
    layout = document.pages[0].elements[0].content.text_layout
    assert layout is not None and layout.frame.width == 8 and layout.frame.x == -3.5


def test_library_shapes_get_the_points_and_label_their_library_gives_them() -> None:
    """A shape placed by the skill must match one placed by hand in the app: a BPMN
    event's name sits below it, a task's text keeps clear of its picture, and a task
    mark offers connectors nothing to attach to."""
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
    assert (layout.position, layout.frame.x, layout.frame.width) == ("below", -0.977, 2.954)
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
    assert (layout.position, layout.frame.width, layout.frame.height) == ("middle", 2.954, 1)


def test_a_name_wider_than_its_shape_is_written_as_its_library_centres_it() -> None:
    """A shipped library may centre a name wider than its shape, such as the UML Actor's,
    starting left of the shape. The skill writes that region exactly as the app gives a copy
    placed by hand, whatever the name's length; a long name wraps in it."""
    actor = Catalog.load().resolve("uml", "actor")
    assert actor is not None and actor.text_region is not None and actor.text_region[0] < 0

    document = compile_spec(
        _spec([
            {"key": "short", "shape": "uml/actor", "label": "A", "col": 0, "row": 0},
            {"key": "long", "shape": "uml/actor", "label": "Customer service agent", "col": 1, "row": 0},
        ])
    )
    assert len(document.pages[0].elements) == 2 and document.pages[0].content.groups == []
    for element in document.pages[0].elements:
        layout = element.content.text_layout
        assert layout is not None and element.core.text_content.string in ("A", "Customer service agent")
        assert (layout.frame.x, layout.frame.y, layout.frame.width, layout.frame.height) == actor.text_region


def test_a_fork_join_bar_keeps_its_thickness() -> None:
    """The app keeps a Fork / Join Bar's height, its thickness, whatever a person does, so
    a spec's width or scale lengthens it and never thickens it, and a height for it is
    refused rather than silently dropped."""
    bar = Catalog.load().resolve("uml", "fork-join-bar")
    assert bar is not None and bar.resizing == "width_only"

    document = compile_spec(
        _spec([
            {"key": "wide", "shape": "uml/fork-join-bar", "width": 200, "col": 0, "row": 0},
            {"key": "scaled", "shape": "uml/fork-join-bar", "scale": 2, "col": 0, "row": 1},
        ])
    )
    wide, scaled = (element.core.frame for element in document.pages[0].elements)
    assert (wide.width, wide.height) == (200, bar.default_height)
    assert (scaled.width, scaled.height) == (bar.default_width * 2, bar.default_height)

    with pytest.raises(SpecError, match="keeps its own thickness"):
        compile_spec(
            _spec([{"key": "b", "shape": "uml/fork-join-bar", "width": 200, "height": 40, "col": 0, "row": 0}])
        )


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


def test_a_document_of_packaged_shapes_needs_nothing_more() -> None:
    """Every packaged shape and line ending is in the SimpleDiagrams that opens the file,
    so nothing is a warning."""
    document = compile_spec(
        _spec(
            [_box("a", 0, 0), {"key": "e", "shape": "bpmn/end-event", "label": "Done", "col": 1, "row": 0}],
            [{"source": "a", "target": "e", "end_ending": "cross"}],
        )
    )
    assert lint(document) == []


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
        [sys.executable, str(ROOT / "scripts" / script), *map(str, arguments)],
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
    for spec, message in ((huge, "limit"), (unknown, "not one of the shapes packaged"), (tmp_path / "absent.json", "Cannot read")):
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
    # Every document needs the SimpleDiagrams the catalogue comes from, which has shipped.
    for path in ("VERSIONS.md", "README.md", "SKILL.md", "references/document-format.md"):
        text = (ROOT / path).read_text()
        assert f"SimpleDiagrams {catalog['source_app_version']} or later" in text, path
        assert "not yet released" not in text, path
    assert f"from SimpleDiagrams {catalog['source_app_version']}" in versions
    assert catalog["source_app_version"] in (ROOT / "README.md").read_text()
    for name in (f"simplediagram-document-{wire.FORMAT_VERSION}", f"simplediagram-manifest-{wire.FORMAT_VERSION}", "diagram-spec-1"):
        assert (ROOT / "schema" / f"{name}.schema.json").is_file()


# ---------------------------------------------------------------------------
# Only packaged shapes
# ---------------------------------------------------------------------------


def test_a_shape_from_a_downloadable_library_is_refused() -> None:
    """The skill knows only the shapes packaged with SimpleDiagrams; a selector for any
    other library must stop the build and say so, never write a placeholder."""
    spec = _spec([{"key": "t", "shape": "notebook/transformer", "x": 0, "y": 0}])
    with pytest.raises(SpecError, match="not one of the shapes packaged with SimpleDiagrams 5.1.0"):
        compile_spec(spec)


def test_lint_flags_a_reference_the_app_does_not_package() -> None:
    """A document whose reference is not in the packaged list would open with a dashed
    placeholder, so the validator reports it as an error naming the reference."""
    outsider = CatalogShape(
        library_id="79FFE4B7-EA0D-87C3-AE89-D4CD62AF5202", library_short_name="notebook",
        library_display_name="Notebook", asset_version=1,
        item_id="A5C619FD-0E22-8EF7-8299-45280EA3F738", display_name="Transformer",
        default_width=61, default_height=37.375,
    )
    catalog = Catalog(Catalog.load().shapes + [outsider], "test")
    document = compile_spec(_spec([{"key": "t", "shape": "notebook/A5C619FD-0E22-8EF7-8299-45280EA3F738", "x": 0, "y": 0}]), catalog)

    assert not [f for f in lint(document, catalog) if f.code == "unresolved-shape"]
    errors = [f for f in lint(document) if f.severity == "error"]
    assert [f.code for f in errors] == ["unresolved-shape"]
    assert "not packaged with SimpleDiagrams 5.1.0" in errors[0].message


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
    return CatalogShape(
        library_id="com.simplediagrams.shapeLibrary.parts", library_short_name="parts",
        library_display_name="Parts", asset_version=1, item_id=slug, display_name=slug.title(),
        default_width=61, default_height=37.375, connection_points=points,
    )


def _wired(nodes: list[dict], edges: list[dict]) -> DiagramSpec:
    """A one-page spec from raw node and edge dictionaries."""
    return DiagramSpec.model_validate({"name": "Wired", "pages": [{"nodes": nodes, "edges": edges}]})


def _end_points(document: wire.Document) -> list[tuple[int, float, float]]:
    """Each connector end as (anchor id, x, y), start then end."""
    ends = []
    for connection in document.pages[0].connections:
        core = connection.content
        for attachment, point in ((core.start_attachment, core.points[0]), (core.end_attachment, core.points[-1])):
            assert attachment is not None and attachment.connection_point_id is not None
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


@pytest.mark.parametrize(
    ("flip_horizontal", "flip_vertical"), [(True, False), (False, True), (True, True)],
    ids=["across", "down", "both"],
)
def test_a_flipped_shape_draws_its_points_mirrored_and_keeps_their_ids(
    flip_horizontal: bool, flip_vertical: bool
) -> None:
    """The app mirrors a flipped shape's connection points with its artwork, in the shape's
    own axes, and keeps each point's id and stored position. A connector naming a lead end
    must meet that end where the mirrored artwork draws it."""
    catalog = _parts_catalog(_part("block", LEADS))
    spec = _wired(
        [{"key": "b", "shape": "parts/block", "x": 300, "y": 300, "scale": 2,
          "flip_horizontal": flip_horizontal, "flip_vertical": flip_vertical},
         {"key": "far", "shape": "rectangle", "x": 700, "y": 600}],
        [{"source": "b", "target": "far", "source_point": 8, "end_ending": "none"}],
    )
    document = compile_spec(spec, catalog)

    element = document.pages[0].elements[0]
    assert (element.content.flip_horizontal, element.content.flip_vertical) == (flip_horizontal, flip_vertical)
    stored = {anchor.id: (anchor.x, anchor.y) for anchor in element.core.connection_points}
    assert stored[8] == (0.0082, 0.0736)
    fx = 1 - 0.0082 if flip_horizontal else 0.0082
    fy = 1 - 0.0736 if flip_vertical else 0.0736
    frame = element.core.frame
    point_id, x, y = _end_points(document)[0]
    assert point_id == 8
    assert (x, y) == pytest.approx((frame.x + fx * frame.width, frame.y + fy * frame.height), abs=0.001)
    assert _axis_aligned(document)
    assert "connector-through-shape" not in {f.code for f in lint(document, catalog)}


def test_a_side_of_a_flipped_shape_is_the_side_it_is_drawn_on() -> None:
    """After a flip across, the anchor numbered for the left is drawn on the right. A side
    in the spec names where the connector meets the shape on the page, so it must use the
    anchor drawn there, chosen automatically or not."""
    for edge in ({"source": "a", "target": "b"}, {"source": "a", "target": "b", "source_side": "right"}):
        spec = _wired(
            [{"key": "a", "shape": "rectangle", "x": 0, "y": 100, "flip_horizontal": True},
             {"key": "b", "shape": "rectangle", "x": 300, "y": 100}],
            [edge],
        )
        document = compile_spec(spec)
        frame = document.pages[0].elements[0].core.frame
        assert _end_points(document)[0] == (0, frame.x + frame.width, pytest.approx(frame.y + frame.height / 2))
        assert _axis_aligned(document)


def test_text_cannot_be_flipped() -> None:
    """The app never flips text, which has no artwork to mirror; the spec says so rather
    than write a flip the app would not make."""
    with pytest.raises(ValidationError, match="no artwork to flip"):
        _wired([{"key": "t", "shape": "text", "label": "Note", "x": 0, "y": 0, "flip_horizontal": True}], [])


# ---------------------------------------------------------------------------
# Edges within one node, and naming shapes in findings
# ---------------------------------------------------------------------------


def _strictly_inside(x: float, y: float, frame: wire.Rect) -> bool:
    """Whether a point lies inside a frame, not on or beyond its edge."""
    return frame.x < x < frame.x + frame.width and frame.y < y < frame.y + frame.height


@pytest.mark.parametrize(
    ("source_point", "target_point"),
    [(8, 11), (8, 9), (0, 1), (2, 3), (4, 7)],
    ids=["opposite-leads", "same-side-leads", "left-to-right", "top-to-bottom", "corners"],
)
def test_an_edge_joins_two_points_of_one_node_around_the_shape(
    source_point: int, target_point: int
) -> None:
    """Two points of one shape may be joined directly. The connector must attach at both,
    stay square, and go around the shape: the usual run midway between the ends would
    cross the shape's own middle."""
    catalog = _parts_catalog(_part("block", LEADS))
    spec = _wired(
        [{"key": "b", "shape": "parts/block", "x": 300, "y": 300, "scale": 2}],
        [{"source": "b", "target": "b", "source_point": source_point,
          "target_point": target_point, "end_ending": "none"}],
    )
    document = compile_spec(spec, catalog)

    frame = document.pages[0].elements[0].core.frame
    anchors = {point_id: (fx, fy) for point_id, fx, fy in LEADS}
    for point_id, x, y in _end_points(document):
        fx, fy = anchors[point_id]
        assert (x, y) == pytest.approx((frame.x + fx * frame.width, frame.y + fy * frame.height), abs=0.001)
    assert [end[0] for end in _end_points(document)] == [source_point, target_point]
    assert _axis_aligned(document)
    route = document.pages[0].connections[0].content.points
    assert not any(_strictly_inside(point.x, point.y, frame) for point in route[1:-1])
    assert "connector-through-shape" not in {f.code for f in lint(document, catalog)}


def test_an_edge_within_one_node_goes_around_on_the_clearer_side() -> None:
    """With a neighbour close above, the loop must go below rather than through it."""
    spec = _wired(
        [{"key": "a", "shape": "rectangle", "x": 300, "y": 300},
         {"key": "cap", "shape": "rectangle", "x": 300, "y": 235, "height": 40}],
        [{"source": "a", "target": "a", "source_point": 0, "target_point": 1}],
    )
    document = compile_spec(spec)

    frame = document.pages[0].elements[0].core.frame
    route = document.pages[0].connections[0].content.points
    assert max(point.y for point in route) > frame.y + frame.height
    assert "connector-through-shape" not in {f.code for f in lint(document)}


def test_an_edge_within_one_node_keeps_off_a_run_another_connector_takes() -> None:
    """A connector arriving at a neighbouring point turns in at the same distance outside
    the shape as a loop's run. With both sides clear of shapes, the loop must take the side
    no connector runs along, or the two lines lie on top of each other and read as joined.
    The loop comes first in the spec, so it is routed after the other connector but stays
    first in the document."""
    edge_points = tuple(
        [(0, 0.0, 0.5), (1, 1.0, 0.5), (2, 0.5, 0.0), (3, 0.5, 1.0)]
        + [(10 + i, 0.2 * (i + 1), 0.0) for i in range(4)]
        + [(20 + i, 0.2 * (i + 1), 1.0) for i in range(4)]
    )
    panel = _part("panel", edge_points).model_copy(update={"default_width": 400, "default_height": 80})
    catalog = _parts_catalog(panel)
    spec = _wired(
        [{"key": "p", "shape": "parts/panel", "x": 400, "y": 300},
         {"key": "feed", "shape": "rectangle", "x": 0, "y": 300}],
        [{"source": "p", "target": "p", "source_point": 11, "target_point": 21, "end_ending": "none"},
         {"source": "feed", "target": "p", "target_point": 10, "end_ending": "none"}],
    )
    document = compile_spec(spec, catalog)

    loop, feed = document.pages[0].connections
    panel_id = document.pages[0].elements[0].core.id
    assert loop.content.start_attachment.element_id == loop.content.end_attachment.element_id == panel_id
    assert feed.content.end_attachment.connection_point_id == 10
    frame = document.pages[0].elements[0].core.frame
    assert max(point.x for point in loop.content.points) > frame.x + frame.width
    assert "connectors-overlap" not in {f.code for f in lint(document, catalog)}


@pytest.mark.parametrize(
    "ends",
    [{}, {"source_point": 1}, {"target_point": 1}, {"source_point": 1, "target_point": 1}],
    ids=["no-points", "source-point-only", "target-point-only", "same-point"],
)
def test_an_edge_within_one_node_needs_two_different_points(ends: dict) -> None:
    """Without two different named points there is nothing to join on one shape, so the
    spec is refused, saying what to give."""
    with pytest.raises(ValidationError, match="two different points with source_point and target_point"):
        _wired([{"key": "a", "shape": "rectangle", "x": 0, "y": 0}],
               [{"source": "a", "target": "a", **ends}])


def test_a_shape_without_a_label_is_named_by_its_node_key() -> None:
    """A finding must name something the spec's author can find in the spec. An element
    id cannot be traced back to a node; a node key can. Without the spec, the old naming
    by kind and id remains."""
    spec = _spec([_box("north", 0, 0, label=""), _box("south", 0.2, 0, label="")])
    document = compile_spec(spec)

    def overlap(found: list) -> list[str]:
        return [finding.message for finding in found if finding.code == "shapes-overlap"]

    assert overlap(lint(document, spec=spec)) == ["Page 1: node 'north' and node 'south' overlap."]
    assert overlap(lint(document)) == [
        f"Page 1: rectangle {element.core.id[:8]} and rectangle {other.core.id[:8]} overlap."
        for element, other in [document.pages[0].elements]
    ]


@pytest.mark.parametrize(
    ("nodes", "edges", "flagged"),
    [
        (
            [_box("hub", 0, 0), _box("a", 1, -1), _box("b", 1, 1)],
            [{"source": "a", "target": "hub", "target_point": 1},
             {"source": "hub", "target": "b", "source_point": 1}],
            False,
        ),
        (
            [_box("a", 0, 0), _box("b", 1, 0)],
            [{"source": "a", "target": "a", "source_point": 0, "target_point": 1, "end_ending": "none"},
             {"source": "a", "target": "b", "source_point": 1}],
            False,
        ),
        (
            [_box("a", 0, 1), _box("b", 1, 0), _box("c", 1, 2)],
            [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
            False,
        ),
        ([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}], True),
        ([_box("a", 0, 0), _box("b", 1, 0)], [{"source": "a", "target": "b"}] * 2, True),
    ],
    ids=["pass-through-point", "loop-and-outside-connector", "branches", "two-way-pair", "duplicate"],
)
def test_connectors_meeting_at_one_point_are_not_an_overlap(
    nodes: list[dict], edges: list[dict], flagged: bool
) -> None:
    """Connectors that meet at one point join there, whichever way each runs, so sharing
    its stub is a junction, not an overlap. Two that join the same two points lie on top of
    each other along their whole length, and must still be reported."""
    codes = {finding.code for finding in lint(compile_spec(_spec(nodes, edges)))}
    assert ("connectors-overlap" in codes) is flagged


def test_the_build_names_shapes_without_labels_by_their_node_keys(tmp_path: Path) -> None:
    """The build is where an agent reads the warnings, so it must check with the spec."""
    spec = tmp_path / "overlap.json"
    spec.write_text(json.dumps({"name": "Overlap", "pages": [{"nodes": [
        {"key": "north", "shape": "rectangle", "col": 0, "row": 0},
        {"key": "south", "shape": "rectangle", "col": 0.2, "row": 0},
    ]}]}))
    result = _run("build_diagram.py", spec)
    assert result.returncode == 0 and "node 'north' and node 'south' overlap" in result.stdout, result.stdout


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
    environment = {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    before = _bytecode(ROOT)
    for script, output in (("build_diagram.py", "Out.simplediagram"), ("preview_diagram.py", "out.svg")):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), str(spec), output],
            capture_output=True, text=True, check=False, cwd=work, env=environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert list(home.iterdir()) == []
    assert sorted(path.name for path in work.iterdir()) == ["Out.simplediagram", "out.svg"]
    assert _bytecode(ROOT) == before, "a script left Python bytecode in the skill folder"


def _bytecode(folder: Path) -> dict[str, int]:
    """Every compiled Python file under `folder`, with when it was written."""
    return {str(path): path.stat().st_mtime_ns for path in folder.rglob("__pycache__/*")}


def test_the_scripts_write_no_bytecode_even_when_python_would(tmp_path: Path) -> None:
    """An installed skill must stay as it was installed: each command turns off Python's
    bytecode itself, so no cache folder appears beside the scripts whatever the
    environment says. Run in a copy, so a failure leaves nothing in the skill."""
    copy = tmp_path / "skill"
    shutil.copytree(ROOT / "scripts", copy / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "assets", copy / "assets")
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
    spec = copy / "assets" / "example-spec.json"
    for command in (
        ["build_diagram.py", str(spec), str(tmp_path / "Out.simplediagram")],
        ["preview_diagram.py", str(spec), str(tmp_path / "out.svg")],
        ["find_shapes.py", "database"],
    ):
        result = subprocess.run(
            [sys.executable, str(copy / "scripts" / command[0]), *command[1:]],
            capture_output=True, text=True, check=False, cwd=tmp_path, env=environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert list(copy.rglob("__pycache__")) == []


def test_the_build_prints_a_bounded_number_of_findings_of_one_kind(tmp_path: Path) -> None:
    """A large diagram can repeat one problem hundreds of times; the build shows the first
    of each kind and counts the rest, so the output stays readable and bounded."""
    nodes = [
        {"key": f"n{index}", "shape": "rectangle", "label": "x", "x": 100 + index, "y": 100}
        for index in range(30)
    ]
    spec = tmp_path / "crowded.json"
    spec.write_text(json.dumps({"name": "Crowded", "pages": [{"nodes": nodes}]}), encoding="utf-8")
    result = _run("build_diagram.py", spec)
    assert result.returncode == 0, result.stdout + result.stderr
    pairs = 30 * 29 // 2
    overlaps = [line for line in result.stdout.splitlines() if line.startswith("warning shapes-overlap")]
    assert len(overlaps) == 21
    assert overlaps[-1] == f"warning shapes-overlap: {pairs - 20} more like these, not shown"
    assert f"{pairs} warning(s)" in result.stdout


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

