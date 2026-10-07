"""Tests for the diagram spec compiler, layout checks and package writer.

The spec is how an agent actually authors a diagram, so these cover the
promises the skill makes about it: every compiled document is valid, shapes
resolve to ones the app ships, connectors attach and route cleanly, and the
package on disk has exactly the members the app accepts.
"""

from __future__ import annotations

import json
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
from sd_package import PackageError, check_package, write_package
from sd_spec import Catalog, DiagramSpec, SpecError, compile_spec, lint

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
    assert len(catalog.shapes) == 280
    nodes = [
        {"key": f"n{i}", "shape": f"{shape.library_short_name}/{shape.item_id}", "x": i * 300.0, "y": 0.0}
        for i, shape in enumerate(catalog.shapes)
    ]
    document = compile_spec(_spec(nodes), catalog)
    assert [f for f in lint(document, catalog) if f.severity == "error"] == []
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
    document, findings = check_package(path)
    assert document == fixtures.full_profile_document()
    assert [f for f in findings if f.severity == "error"] == []


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
    assert check_package(target)[1] == []


def test_build_refuses_bad_specs_before_writing(tmp_path: Path) -> None:
    """A spec that is too large, malformed or names an unknown shape is
    reported and leaves nothing on disk."""
    target = tmp_path / "Out.simplediagram"
    huge = tmp_path / "huge.json"
    huge.write_text(" " * (2 * 1024 * 1024 + 1))
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"name": "X", "pages": [{"nodes": [{"key": "a", "shape": "aws/S3", "col": 0, "row": 0}]}]}))
    for spec, message in ((huge, "limit"), (unknown, "not a shape built into"), (tmp_path / "absent.json", "Cannot read")):
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


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (lambda p: (p / ".DS_Store").write_text("x"), "unexpected-member"),
        (lambda p: (p / "assets" / ".DS_Store").write_text("x"), "unexpected-asset"),
        (lambda p: (p / "assets").rmdir(), "missing-member"),
        (lambda p: (p / "manifest.json").write_text('{"format":"com.simplediagrams.document","format_version":16,"contains_legacy_source":false}'), "invalid-manifest"),
        (lambda p: (p / "document.json").write_text("{}"), "invalid-document"),
        (lambda p: (p / "document.json").write_text("not json"), "invalid-json"),
        (
            lambda p: (p / "document.json").write_text(
                (p / "document.json").read_text().replace('"schema_version": 14', '"schema_version": 15, "schema_version": 14')
            ),
            "duplicate-key",
        ),
    ],
)
def test_check_package_reports_what_the_app_would_refuse(tmp_path: Path, damage, code: str) -> None:
    """Stray files and a wrong version are the usual ways a finished package
    is broken after it was built."""
    path = write_package(fixtures.minimal_document(), tmp_path / "Doc.simplediagram")
    damage(path)
    document, findings = check_package(path)
    assert document is None
    assert code in {finding.code for finding in findings}


def test_check_package_refuses_a_file(tmp_path: Path) -> None:
    """A zip or JSON file is not a document; the app needs the folder."""
    file = tmp_path / "Doc.simplediagram"
    file.write_text("{}")
    assert check_package(file)[1][0].code == "not-a-package"


def test_versions_are_stated_consistently() -> None:
    """The skill, format, catalogue and minimum app versions each appear in
    several files; a release that updates only some of them would mislead."""
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    versions = (ROOT / "VERSIONS.md").read_text()
    catalog = json.loads((ROOT / "assets" / "built-in-shapes.json").read_text())
    assert f"| Skill | {plugin['version']} |" in versions
    assert f"| Package format | {wire.FORMAT_VERSION} |" in versions
    assert f"| Document schema | {wire.SCHEMA_VERSION} |" in versions
    assert f"from SimpleDiagrams {catalog['source_app_version']}" in versions
    assert catalog["source_app_version"] in (ROOT / "README.md").read_text()
    for name in (f"simplediagram-document-{wire.FORMAT_VERSION}", f"simplediagram-manifest-{wire.FORMAT_VERSION}", "diagram-spec-1"):
        assert (ROOT / "schema" / f"{name}.schema.json").is_file()
