"""Tests for complex shapes: the shapes SimpleDiagrams draws itself.

Containers, swimlanes, tables, callouts and UML lifelines are records the app reads
strictly and refuses a whole file for getting wrong, so these cover the exact records
the app reads and writes back unchanged, the containment and attachment rules it checks,
and the layouts the builder works out so an agent can name members and messages instead
of computing coordinates.
"""

from __future__ import annotations

import copy
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
from find_shapes import complex_shape_hints
from sd_package import write_package
from sd_spec import (
    DiagramSpec,
    SpecError,
    compile_spec,
    lint,
    load_spec,
)

SPEC_ID = "11111111-2222-4333-8444-555555555555"
EXAMPLES = ("example-bpmn-spec.json", "example-sequence-spec.json", "example-class-spec.json")


def _compile(nodes: list[dict], edges: list[dict] | None = None, **page: object) -> wire.Document:
    return compile_spec(
        DiagramSpec.model_validate(
            {"name": "Test", "id": SPEC_ID, "pages": [{"nodes": nodes, "edges": edges or [], **page}]}
        )
    )


def _box(key: str, col: float, row: float, **extra: object) -> dict:
    return {"key": key, "shape": "rectangle", "label": key, "col": col, "row": row} | extra


def _element(document: wire.Document, label: str) -> wire.Element:
    """The element whose text, or first lane title or cell, is `label`."""
    for element in document.pages[0].elements:
        texts = [element.core.text_content.string]
        if element.complex_shape is not None:
            texts += [text.string for text in element.complex_shape.texts]
        if label in texts:
            return element
    raise AssertionError(f"no element says {label!r}")


def _inside(inner: wire.Rect, outer: wire.Rect) -> bool:
    return (
        inner.x >= outer.x and inner.y >= outer.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def _sequence(edges: list[dict], *extra_nodes: dict, **lifeline: object) -> wire.Document:
    nodes = [
        {"key": "a", "shape": "lifeline", "label": "A", "col": 0, "row": 0},
        {"key": "b", "shape": "lifeline", "label": "B", "col": 1, "row": 0, **lifeline},
        *extra_nodes,
    ]
    return _compile(nodes, edges)


# ---------------------------------------------------------------------------
# What a document with complex shapes needs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node",
    [
        {"key": "c", "shape": "container", "label": "C", "members": ["a"]},
        {"key": "s", "shape": "swimlanes", "lanes": [{"title": "L", "members": ["a"]}]},
        {"key": "t", "shape": "table", "cells": [["x"]], "col": 2, "row": 0},
        {"key": "o", "shape": "callout", "label": "Hi", "col": 2, "row": 0},
        {"key": "l", "shape": "lifeline", "label": "L", "col": 2, "row": 0},
    ],
)
def test_each_complex_shape_is_an_ordinary_part_of_the_one_format(node: dict) -> None:
    """Every document is the package SimpleDiagrams 5.1.0 writes, so a complex shape needs
    no other format or version."""
    document = _compile([_box("a", 0, 0), node])
    assert document.schema_version == wire.SCHEMA_VERSION
    assert wire.manifest(document).format_version == wire.FORMAT_VERSION


# ---------------------------------------------------------------------------
# The records the app reads
# ---------------------------------------------------------------------------


def test_the_complex_profile_round_trips_unchanged() -> None:
    """Every key complex shapes add must survive a write and read, or the validator
    would not describe what the app keeps."""
    document = fixtures.complex_profile_document()
    dumped = wire.dump(document)
    assert wire.dump(wire.Document.model_validate_json(json.dumps(dumped))) == dumped


def test_optional_complex_keys_are_written_only_when_they_differ_from_the_default() -> None:
    """The app leaves a default out; writing it would make the skill's files differ from
    the app's for the same shape."""
    document = _compile([
        {"key": "c", "shape": "container", "label": "C", "members": ["a"]},
        _box("a", 0, 0),
        {"key": "t", "shape": "table", "cells": [["x"]], "col": 2, "row": 0},
        {"key": "l", "shape": "lifeline", "label": "L", "col": 3, "row": 0},
    ])
    records = {
        element.complex_shape.type: wire.dump(element)["complex_shape"]
        for element in document.pages[0].elements if element.complex_shape
    }
    assert set(records["container"]) == {"type", "members"}
    assert set(records["table"]) == {"type", "row_sizes", "column_sizes", "cells"}
    assert records["lifeline"] == {"type": "lifeline"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda shape: shape.update(layout="automatic"), "Extra inputs"),
        (lambda shape: shape.update(direction="vertical"), "container does not take direction"),
        (lambda shape: shape.pop("members"), "container needs members"),
        (lambda shape: shape.update(type="sticker"), "type"),
        (lambda shape: shape.update(hand_drawn=True), "hand_drawn"),
        (lambda shape: shape.update(title_style="band"), "title_style"),
    ],
)
def test_a_complex_record_holds_only_the_keys_its_type_uses(mutate, message: str) -> None:
    """The app refuses a record with a key its type does not use, or an unknown one."""
    dumped = wire.dump(fixtures.complex_profile_document())
    container = next(e for e in dumped["pages"][0]["elements"] if e.get("complex_shape", {}).get("type") == "container")
    mutate(container["complex_shape"])
    with pytest.raises(ValidationError, match=message):
        wire.Document.model_validate_json(json.dumps(dumped))


def _mutated(change) -> str:
    dumped = wire.dump(fixtures.complex_profile_document())
    change(dumped["pages"][0])
    with pytest.raises(ValidationError) as failure:
        wire.Document.model_validate_json(json.dumps(dumped))
    return str(failure.value)


def _of(page: dict, kind: str) -> dict:
    return next(e for e in page["elements"] if e.get("complex_shape", {}).get("type") == kind)


def _core(element: dict) -> dict:
    return element["content"]["content"]["content"]


def test_the_rules_the_app_reads_a_complex_shape_by() -> None:
    """Each is a rule SimpleDiagrams refuses a whole file for breaking."""
    assert "complex_shape is required" in _mutated(lambda p: _of(p, "table").pop("complex_shape"))
    assert "no text_layout" in _mutated(
        lambda p: _of(p, "table")["content"].update(
            text_layout={"frame": {"x": 0, "y": 0, "width": 1, "height": 1}, "position": "middle"}
        )
    )
    assert "cannot be flipped" in _mutated(lambda p: _of(p, "table")["content"].update(flip_horizontal=True))
    assert "its own text must be empty" in _mutated(
        lambda p: _core(_of(p, "table"))["text_content"].update(string="no")
    )
    assert "smaller than" in _mutated(lambda p: _core(_of(p, "table"))["frame"].update(height=20))
    assert "smaller than" in _mutated(lambda p: _core(_of(p, "lifeline"))["frame"].update(height=50))
    assert "one row of cells per row size" in _mutated(lambda p: _of(p, "table")["complex_shape"]["cells"].pop())
    assert "share an id" in _mutated(
        lambda p: _of(p, "swimlanes")["complex_shape"]["lanes"][1].update(
            id=_of(p, "swimlanes")["complex_shape"]["lanes"][0]["id"]
        )
    )
    assert "needs its tail_tip" in _mutated(
        lambda p: next(
            e for e in p["elements"] if e.get("complex_shape", {}).get("tail_attachment")
        )["complex_shape"].pop("tail_tip")
    )


def test_the_rules_complex_shapes_add_to_a_page() -> None:
    """Members, nesting and tail locks involve other shapes, and the app checks them
    across the page."""
    def outer(page: dict) -> dict:
        return next(e for e in page["elements"] if e.get("complex_shape", {}).get("title_style") == "corner_tag")

    assert "which is in a group" in _mutated(
        lambda p: outer(p)["complex_shape"]["members"].append({"kind": "element", "id": fixtures._uuid(2)})
    )
    assert "held by two" in _mutated(
        lambda p: _of(p, "swimlanes")["complex_shape"]["lanes"][1]["members"].append(
            {"kind": "element", "id": fixtures._uuid(1)}
        )
    )
    assert "swimlanes are never held" in _mutated(
        lambda p: outer(p)["complex_shape"]["members"].append({"kind": "element", "id": fixtures._uuid(6)})
    )
    assert "not another shape" in _mutated(
        lambda p: outer(p)["complex_shape"]["members"].append({"kind": "element", "id": fixtures._uuid(30)})
    )
    assert "in a loop" in _mutated(
        lambda p: _of(p, "container")["complex_shape"]["members"].append({"kind": "element", "id": fixtures._uuid(30)})
    )
    assert "does not have" in _mutated(
        lambda p: next(
            e for e in p["elements"] if e.get("complex_shape", {}).get("tail_attachment")
        )["complex_shape"]["tail_attachment"].update(connection_point_id=99)
    )


def test_an_end_along_a_line_names_a_lifelines_line_only() -> None:
    """Only a lifeline offers an attach line, its dashed line, numbered 0."""
    def onto(element: int, line: int):
        def change(page: dict) -> None:
            page["content"]["content"]["connections"][0]["content"]["end_attachment"] = {
                "element_id": fixtures._uuid(element), "attach_line_id": line, "distance": 5,
            }
        return change

    assert "attach line 0, which that element does not have" in _mutated(onto(8, 0))
    assert "attach line 1" in _mutated(onto(14, 1))
    with pytest.raises(ValidationError, match="and nothing else"):
        wire.Attachment(element_id=fixtures._uuid(1), connection_point_id=1, attach_line_id=0, distance=3)
    with pytest.raises(ValidationError, match="and nothing else"):
        wire.Attachment(element_id=fixtures._uuid(1), attach_line_id=0)


def test_containers_nest_four_deep_at_most() -> None:
    """A fifth level of containers is refused by the app, and by the builder first."""
    def nested(levels: int) -> list[dict]:
        return [_box("x", 0, 0)] + [
            {"key": f"c{level}", "shape": "container", "label": f"L{level}",
             "members": [f"c{level + 1}" if level < levels else "x"]}
            for level in range(1, levels + 1)
        ]

    with pytest.raises(SpecError, match="4 deep at most"):
        _compile(nested(5))
    document = _compile(nested(4))
    frames = [_element(document, f"L{level}").core.frame for level in range(1, 5)]
    for outer, inner in pairwise(frames):
        assert _inside(inner, outer)


# ---------------------------------------------------------------------------
# Containers and swimlanes
# ---------------------------------------------------------------------------


def test_a_container_is_fitted_around_its_members_below_its_title() -> None:
    """The app joins a shape to a container only when it lies wholly inside; members that
    sat on the title would hide it."""
    document = _compile([
        {"key": "c", "shape": "container", "label": "Billing", "members": ["a", "b"]},
        _box("a", 0, 0), _box("b", 1, 0), _box("out", 3, 0),
    ])
    container = _element(document, "Billing")
    assert container.complex_shape is not None
    frame = container.core.frame
    members = [member.id for member in container.complex_shape.members or []]
    assert members == [_element(document, "a").core.id, _element(document, "b").core.id]
    for key in ("a", "b"):
        member = _element(document, key).core.frame
        assert _inside(member, frame) and member.y - frame.y >= 32
    assert not _inside(_element(document, "out").core.frame, frame)
    assert container.core.text_content.base_alignment == "leading"


def test_a_fitted_container_leaves_room_for_a_label_below_a_member() -> None:
    """A label drawn below an icon is not part of the shape the app checks, but a container
    fitted around the icon still holds the label, or the label would hang out of it."""
    document = _compile([
        {"key": "db", "shape": "basic/Cylinder", "label": "A long database label", "col": 0, "row": 0, "label_position": "below"},
        {"key": "c", "shape": "container", "label": "Data", "members": ["db"]},
    ])
    container, icon = _element(document, "Data"), _element(document, "A long database label")
    assert container.complex_shape is not None
    assert container.complex_shape.members == [wire.HolderMember(kind="element", id=icon.core.id)]
    layout = icon.content.text_layout
    assert layout is not None
    area = wire.Rect(
        x=icon.core.frame.x + layout.frame.x * icon.core.frame.width, y=icon.core.frame.y + icon.core.frame.height,
        width=layout.frame.width * icon.core.frame.width, height=20,
    )
    assert _inside(area, container.core.frame)


def test_a_placed_container_must_hold_its_members_wholly() -> None:
    """A container given its own position is checked, since the builder cannot move it."""
    nodes = [_box("a", 0, 0), {"key": "c", "shape": "container", "label": "C", "x": 200, "y": 160, "width": 400, "height": 200, "members": ["a"]}]
    assert _element(_compile(nodes), "C").complex_shape is not None
    nodes[1] |= {"x": 900}
    with pytest.raises(SpecError, match="does not lie wholly inside"):
        _compile(nodes)


def test_the_corner_tag_and_alignment_are_written() -> None:
    """A UML frame's tag and a centred System Boundary title are what the app's tiles place."""
    document = _compile([
        _box("a", 0, 0), _box("b", 2, 0),
        {"key": "f", "shape": "container", "label": "sd Login", "title_style": "corner_tag", "members": ["a"]},
        {"key": "s", "shape": "container", "label": "System", "align": "center", "members": ["b"], "hand_drawn": False},
    ])
    frame, system = _element(document, "sd Login"), _element(document, "System")
    assert frame.complex_shape is not None and frame.complex_shape.title_style == "corner_tag"
    assert system.complex_shape is not None and system.complex_shape.title_style is None
    assert system.complex_shape.hand_drawn is False
    assert system.core.text_content.base_alignment == "center"


def test_horizontal_swimlanes_fit_each_lane_around_its_members() -> None:
    """The app puts a shape in the lane holding its centre, so each lane must hold its own
    members' centres and the swimlanes all of every member."""
    document = _compile([
        {"key": "pool", "shape": "swimlanes", "label": "Pool", "lanes": [
            {"title": "One", "members": ["a", "b"]}, {"title": "Two", "members": ["c"]}]},
        _box("a", 0, 0), _box("b", 1, 0), _box("c", 1, 1),
    ])
    pool = _element(document, "Pool")
    shape = pool.complex_shape
    assert shape is not None and shape.direction == "horizontal"
    lanes = wire.swimlane_frames(shape, pool.core.frame)
    for lane, keys in zip(lanes, (("a", "b"), ("c",)), strict=True):
        for key in keys:
            frame = _element(document, key).core.frame
            assert _inside(frame, pool.core.frame)
            assert lane.y <= frame.y + frame.height / 2 <= lane.y + lane.height
            assert frame.x >= pool.core.frame.x + wire.SWIMLANES_STRIP
    assert [lane.title.string for lane in shape.lanes or []] == ["One", "Two"]


def test_vertical_swimlanes_fit_their_columns() -> None:
    """Lanes that run down the page hold their members across it, below the title strips."""
    document = _compile([
        {"key": "pool", "shape": "swimlanes", "label": "Columns", "direction": "vertical", "lanes": [
            {"title": "Left", "members": ["a"]}, {"title": "Right", "members": ["b", "c"]}]},
        _box("a", 0, 0), _box("b", 1, 0), _box("c", 1, 1),
    ])
    pool = _element(document, "Columns")
    assert pool.complex_shape is not None and pool.complex_shape.direction == "vertical"
    lanes = wire.swimlane_frames(pool.complex_shape, pool.core.frame)
    for lane, keys in zip(lanes, (("a",), ("b", "c")), strict=True):
        for key in keys:
            frame = _element(document, key).core.frame
            assert lane.x <= frame.x + frame.width / 2 <= lane.x + lane.width
            assert frame.y >= lane.y + wire.SWIMLANES_STRIP


@pytest.mark.parametrize(
    ("lanes", "message"),
    [
        ([{"title": "One", "members": ["a", "b"]}, {"title": "Two", "members": []}], "holds nothing"),
        ([{"title": "One", "members": ["a", "c"]}, {"title": "Two", "members": ["b"]}], "overlap"),
        ([{"title": "One", "members": ["a"], "size": 2}], "size is for swimlanes given a position"),
    ],
)
def test_swimlanes_that_cannot_be_fitted_are_refused_plainly(lanes: list[dict], message: str) -> None:
    """A lane needs members of its own rows to be fitted around them."""
    with pytest.raises((SpecError, ValidationError), match=message):
        _compile([{"key": "p", "shape": "swimlanes", "lanes": lanes}, _box("a", 0, 0), _box("b", 1, 0), _box("c", 0, 1)])


def test_placed_swimlanes_check_each_member_is_in_its_lane() -> None:
    """Placed swimlanes divide by their lanes' sizes, and a member outside its lane would
    join another one in the app."""
    nodes = [
        {"key": "p", "shape": "swimlanes", "label": "P", "x": 400, "y": 300, "width": 600, "height": 328,
         "lanes": [{"title": "Top", "size": 1, "members": ["a"]}, {"title": "Bottom", "size": 2, "members": []}]},
        {"key": "a", "shape": "rectangle", "label": "a", "x": 300, "y": 190, "width": 100, "height": 40},
    ]
    shape = _element(_compile(nodes), "P").complex_shape
    assert shape is not None and [lane.size for lane in shape.lanes or []] == [1, 2]
    nodes[1] |= {"y": 380}
    with pytest.raises(SpecError, match="with its centre in that lane"):
        _compile(nodes)


def test_a_node_is_held_once_and_swimlanes_never() -> None:
    """The app refuses a shape held twice, and swimlanes held at all."""
    with pytest.raises(SpecError, match="is held by"):
        _compile([_box("a", 0, 0), {"key": "c", "shape": "container", "members": ["a"]},
                  {"key": "d", "shape": "container", "members": ["a"]}])
    with pytest.raises(SpecError, match="swimlanes are never inside"):
        _compile([_box("a", 0, 0), {"key": "p", "shape": "swimlanes", "lanes": [{"members": ["a"]}]},
                  {"key": "c", "shape": "container", "members": ["p"]}])


# ---------------------------------------------------------------------------
# Tables and callouts
# ---------------------------------------------------------------------------


def test_a_table_holds_its_cells_sized_to_their_text() -> None:
    """A class box is a one-column table whose rows fit their lines, its header centred and
    its body aligned as the spec says."""
    document = _compile([{"key": "t", "shape": "table", "align": "leading", "col": 0, "row": 0,
                          "cells": [["Order"], ["id: UUID\ntotal: Money"], ["place()"]]}])
    (element,) = document.pages[0].elements
    shape = element.complex_shape
    assert shape is not None and shape.header_row is None and element.core.text_content.string == ""
    assert [[cell.string for cell in row] for row in shape.cells or []] == [["Order"], ["id: UUID\ntotal: Money"], ["place()"]]
    assert [row[0].base_alignment for row in shape.cells or []] == ["center", "leading", "leading"]
    rows = shape.row_sizes or []
    assert rows[1] > rows[0] == rows[2]
    assert sum(rows) == pytest.approx(element.core.frame.height)


def test_table_sizes_and_header_can_be_chosen() -> None:
    """Given widths and heights are the shares; a table too small for its rows is refused."""
    document = _compile([{"key": "t", "shape": "table", "col": 0, "row": 0, "header_row": False,
                          "column_widths": [60, 120], "row_heights": [30, 50], "cells": [["a", "b"], ["c", "d"]]}])
    shape = document.pages[0].elements[0].complex_shape
    assert shape is not None and shape.header_row is False
    assert (shape.column_sizes, shape.row_sizes) == ([60, 120], [30, 50])
    with pytest.raises(SpecError, match="under 12 points"):
        _compile([{"key": "t", "shape": "table", "col": 0, "row": 0, "height": 20, "cells": [["a"], ["b"]]}])


@pytest.mark.parametrize(
    "node",
    [
        {"key": "t", "shape": "table", "col": 0, "row": 0, "cells": [["a", "b"], ["c"]]},
        {"key": "t", "shape": "table", "col": 0, "row": 0, "label": "x", "cells": [["a"]]},
        {"key": "t", "shape": "table", "col": 0, "row": 0},
        {"key": "t", "shape": "table", "col": 0, "row": 0, "cells": [["a"]], "column_widths": [1, 2]},
    ],
)
def test_malformed_tables_are_refused(node: dict) -> None:
    """Uneven rows, a table's own label, no cells or mismatched sizes cannot be written."""
    with pytest.raises(ValidationError):
        DiagramSpec.model_validate({"name": "T", "pages": [{"nodes": [node]}]})


def test_a_callout_tail_locks_to_the_nearest_point_where_it_is_drawn() -> None:
    """A locked tail follows its shape in the app; its saved tip must be where the point
    is, from the bubble's centre, or the app would draw it elsewhere until moved."""
    document = _compile([_box("a", 0, 0), {"key": "o", "shape": "callout", "label": "Note", "col": 1, "row": -1, "tail_to": "a"}])
    bubble = _element(document, "Note")
    shape = bubble.complex_shape
    target = _element(document, "a")
    assert shape is not None and shape.tail_attachment is not None and shape.tail_tip is not None
    assert shape.tail_attachment.element_id == target.core.id
    assert shape.tail_attachment.connection_point_id == 6  # the top right corner faces the bubble
    frame, box = bubble.core.frame, target.core.frame
    assert (frame.x + frame.width / 2 + shape.tail_tip.x, frame.y + frame.height / 2 + shape.tail_tip.y) == pytest.approx(
        (box.x + box.width, box.y)
    )


def test_a_callout_tail_can_name_a_point_aim_freely_or_keep_the_default() -> None:
    """A flipped bubble keeps its tip in its own unflipped axes, as the app does."""
    document = _compile([
        _box("a", 0, 0),
        {"key": "p", "shape": "callout", "label": "Point", "col": 1, "row": 0, "tail_to": "a", "tail_point": 3},
        {"key": "f", "shape": "callout", "label": "Free", "col": 2, "row": 0, "tail_at": {"x": 800, "y": 400}, "flip_horizontal": True},
        {"key": "d", "shape": "callout", "label": "Default", "col": 3, "row": 0},
    ])
    named = _element(document, "Point").complex_shape
    assert named is not None and named.tail_attachment is not None
    assert named.tail_attachment.connection_point_id == 3
    free = _element(document, "Free")
    assert free.complex_shape is not None and free.complex_shape.tail_attachment is None
    assert free.complex_shape.tail_tip == wire.Point(x=-(800 - 680.0), y=400 - 160.0)
    default = _element(document, "Default").complex_shape
    assert default is not None and default.tail_tip == wire.Point(x=-40, y=70)
    with pytest.raises(SpecError, match="no connection point 9"):
        _compile([_box("a", 0, 0), {"key": "o", "shape": "callout", "col": 1, "row": 0, "tail_to": "a", "tail_point": 9}])


def test_only_a_callout_can_be_flipped_and_no_complex_shape_turned() -> None:
    """The app refuses a flipped container, swimlanes, table or lifeline."""
    for shape in ("container", "table", "lifeline"):
        with pytest.raises(ValidationError, match="only a callout can"):
            DiagramSpec.model_validate({"name": "F", "pages": [{"nodes": [
                {"key": "x", "shape": shape, "col": 0, "row": 0, "cells": [["a"]] if shape == "table" else None, "flip_vertical": True}
            ]}]})
    with pytest.raises(ValidationError, match="remove rotation"):
        DiagramSpec.model_validate({"name": "R", "pages": [{"nodes": [
            {"key": "x", "shape": "callout", "col": 0, "row": 0, "rotation": 30}]}]})


def test_kind_specific_fields_belong_to_their_kind() -> None:
    """A misplaced field would be silently meaningless, so it is an error naming the kind."""
    with pytest.raises(ValidationError, match="cells is for a table node"):
        DiagramSpec.model_validate({"name": "K", "pages": [{"nodes": [_box("a", 0, 0, cells=[["x"]])]}]})
    with pytest.raises(ValidationError, match="label_position"):
        DiagramSpec.model_validate({"name": "K", "pages": [{"nodes": [
            {"key": "c", "shape": "callout", "col": 0, "row": 0, "label_position": "below"}]}]})
    with pytest.raises(ValidationError, match="unknown node"):
        DiagramSpec.model_validate({"name": "K", "pages": [{"nodes": [
            {"key": "c", "shape": "container", "members": ["ghost"]}]}]})


# ---------------------------------------------------------------------------
# Lifelines and messages
# ---------------------------------------------------------------------------


def test_messages_attach_along_lifelines_in_order_down_the_page() -> None:
    """A message stores how far down each line it is, as the app does, and its points are
    the same places, so the app draws it where the file says."""
    document = _sequence([
        {"source": "a", "target": "b", "label": "ask", "end_ending": "filledArrow"},
        {"source": "b", "target": "a", "label": "answer", "pattern": "dashed", "end_ending": "arrow"},
    ])
    page = document.pages[0]
    first, second = (connection.content for connection in page.connections)
    a, b = (_element(document, key).core.frame for key in ("A", "B"))
    assert a.y == b.y  # heads line up
    for connection in (first, second):
        start, end = connection.start_attachment, connection.end_attachment
        assert start is not None and end is not None and start.on_line and end.on_line
        assert connection.points[0].y == connection.points[-1].y  # straight across
        for attachment, point in ((start, connection.points[0]), (end, connection.points[-1])):
            frame = a if attachment.element_id == _element(document, "A").core.id else b
            assert attachment.distance is not None
            assert point.y == pytest.approx(frame.y + 40 + attachment.distance)
            assert point.x == pytest.approx(frame.x + frame.width / 2)
    assert second.points[0].y > first.points[0].y
    for element in page.elements:
        assert element.core.connection_points == [wire.ConnectionPointAnchor(id=2, x=0.5, y=0)]


def test_a_message_to_its_own_lifeline_loops_out_and_back_lower() -> None:
    """A call to itself has two different places on one line; the app draws a loop."""
    document = _sequence([{"source": "a", "target": "a", "label": "think"}])
    (connection,) = document.pages[0].connections
    start, end = connection.content.start_attachment, connection.content.end_attachment
    assert start is not None and end is not None
    assert end.distance is not None and start.distance is not None and end.distance > start.distance
    assert len(connection.content.points) == 4
    assert connection.content.label is not None and connection.content.label.normal_offset < 0


def test_lifelines_are_long_enough_and_a_destroyed_one_ends_after_its_last_message() -> None:
    """The app keeps line below the last message, and draws the destroy mark at the line's
    end, so a destroyed lifeline ends just below its last message."""
    document = _sequence(
        [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}, {"source": "a", "target": "a"}],
        ends_in_destroy_mark=True, head="actor",
    )
    page = document.pages[0]
    a, b = _element(document, "A"), _element(document, "B")
    assert b.complex_shape == wire.ComplexShape(type="lifeline", head_style="actor", ends_in_destroy_mark=True)
    last = max(point.y for connection in page.connections for point in connection.content.points)
    assert a.core.frame.y + a.core.frame.height - last >= 16
    _, b_end = wire.lifeline_line(b.complex_shape, b.core.frame)
    second = page.connections[1].content.points[0].y
    assert b.core.frame.y + b_end - second == pytest.approx(20)
    assert b.core.frame.y + b.core.frame.height < a.core.frame.y + a.core.frame.height


def test_an_explicit_lifeline_height_too_short_for_its_messages_is_refused() -> None:
    """A message past the end of a line would attach where nothing is drawn."""
    with pytest.raises(SpecError, match="below the end of lifeline 'b'"):
        _sequence([{"source": "a", "target": "b"}] * 6, height=100)


@pytest.mark.parametrize(
    ("edge", "message"),
    [
        ({"source": "a", "target": "x"}, "a lifeline's connectors are messages"),
        ({"source": "a", "target": "b", "source_side": "right"}, "remove its sides and points"),
    ],
)
def test_a_lifeline_connects_only_to_lifelines_by_messages(edge: dict, message: str) -> None:
    """A lifeline's only numbered point is the top of its head; messages go along its line."""
    with pytest.raises(SpecError, match=message):
        _sequence([edge], _box("x", 2, 0))


def test_a_fragment_encloses_its_messages_with_room_for_its_tag() -> None:
    """Alt, loop and opt fragments are corner-tag containers drawn around messages, behind
    them, with a dashed divider between an alt's operands."""
    document = _sequence(
        [
            {"key": "m1", "source": "a", "target": "b"},
            {"key": "m2", "source": "b", "target": "a"},
            {"key": "m3", "source": "a", "target": "b"},
            {"key": "m4", "source": "b", "target": "a"},
        ],
        {"key": "alt", "shape": "container", "title_style": "corner_tag", "label": "alt [ok]",
         "messages": ["m2", "m3"], "dividers": [{"before": "m3", "label": "[else]"}]},
        {"key": "loop", "shape": "container", "title_style": "corner_tag", "label": "loop", "messages": ["m3"]},
    )
    page = document.pages[0]
    alt, loop = _element(document, "alt [ok]").core.frame, _element(document, "loop").core.frame
    ys = [connection.content.points[0].y for connection in page.connections[:4]]
    assert alt.y + 28 < ys[1] and ys[2] < alt.y + alt.height and ys[3] > alt.y + alt.height
    assert ys[0] < alt.y
    assert _inside(loop, alt) and loop.y + 28 < ys[2]
    divider = page.connections[4].content
    assert divider.stroke_pattern == "dashed" and divider.start_attachment is None
    assert ys[1] < divider.points[0].y < loop.y and divider.label is not None
    order = page.content.drawableOrder
    assert order is not None and order[0].id == _element(document, "alt [ok]").core.id
    assert order[1].id == _element(document, "loop").core.id
    assert all(entry.kind == "connection" for entry in order[2:7])


def test_fragments_that_partly_overlap_or_enclose_no_messages_are_refused() -> None:
    """One fragment must hold the other or share no message, and fragments hold messages."""
    edges = [{"key": f"m{n}", "source": "a", "target": "b"} for n in range(3)]
    frag = lambda key, messages: {"key": key, "shape": "container", "title_style": "corner_tag", "messages": messages}
    with pytest.raises(SpecError, match="neither holds"):
        _sequence(edges, frag("f", ["m0", "m1"]), frag("g", ["m1", "m2"]))
    with pytest.raises(SpecError, match="not a message"):
        _compile([_box("a", 0, 0), _box("b", 1, 0), frag("f", ["e"])], [{"key": "e", "source": "a", "target": "b"}])
    with pytest.raises(SpecError, match="after its first"):
        _sequence(edges, frag("f", ["m0", "m1"]) | {"dividers": [{"before": "m0"}]})


def test_a_frame_around_lifelines_holds_them() -> None:
    """An sd frame lists the lifelines as members, so moving it moves the diagram."""
    document = _sequence(
        [{"source": "a", "target": "b"}],
        {"key": "sd", "shape": "container", "title_style": "corner_tag", "label": "sd Talk", "members": ["a", "b"]},
    )
    frame = _element(document, "sd Talk")
    for key in ("A", "B"):
        head = _element(document, key).core.frame
        assert _inside(head, frame.core.frame) and head.y >= frame.core.frame.y + 28


# ---------------------------------------------------------------------------
# Examples, checks and discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXAMPLES)
def test_the_complex_shape_examples_build_clean(name: str) -> None:
    """The worked examples are what an agent copies; they must build with no errors and
    no layout warnings."""
    spec = load_spec(ROOT / "assets" / name)
    assert lint(compile_spec(spec), spec=spec) == []


def test_complex_shapes_do_not_raise_overlap_or_crossing_warnings() -> None:
    """Members lie inside their container and connectors run into it by design."""
    document = _compile(
        [{"key": "c", "shape": "container", "label": "C", "members": ["a", "b"]}, _box("a", 0, 0), _box("b", 1, 0), _box("z", 3, 0)],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "z"}],
    )
    assert lint(document) == []


def test_a_lane_title_longer_than_its_lane_is_reported() -> None:
    """A horizontal lane's title runs along its strip; a longer one cannot be read."""
    document = _compile([
        {"key": "p", "shape": "swimlanes", "lanes": [{"title": "A very long lane title for one row", "members": ["a"]}]},
        _box("a", 0, 0),
    ])
    assert [finding.code for finding in lint(document)] == ["label-overflow"]


def test_a_complex_document_is_written_and_read_back(tmp_path: Path) -> None:
    """The package on disk carries manifest 18 and the records, and reads back as written."""
    document = compile_spec(load_spec(ROOT / "assets" / "example-sequence-spec.json"))
    written = write_package(document, tmp_path / "Sequence.simplediagram")
    manifest = json.loads((written / "manifest.json").read_text())
    assert manifest["format_version"] == 18
    again = wire.Document.model_validate_json((written / "document.json").read_text())
    assert wire.dump(again) == wire.dump(document)


def test_the_build_writes_a_complex_example(tmp_path: Path) -> None:
    """The command an agent runs builds a complex-shape example cleanly, with no findings."""
    target = tmp_path / "Classes.simplediagram"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_diagram.py"),
         str(ROOT / "assets" / "example-class-spec.json"), str(target)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [line for line in result.stdout.splitlines() if line.startswith(("warning", "error"))]
    assert json.loads((target / "manifest.json").read_text())["format_version"] == 18


def test_a_search_for_a_complex_shape_names_the_kind() -> None:
    """Pools, class boxes and lifelines are not catalogue shapes; a search must still lead
    an agent to them."""
    assert [hint["shape"] for hint in complex_shape_hints("BPMN pool")] == ["swimlanes"]
    assert [hint["shape"] for hint in complex_shape_hints("class")] == ["table"]
    assert {hint["shape"] for hint in complex_shape_hints("sequence lifeline")} == {"lifeline"}
    assert complex_shape_hints("database") == []


def test_the_complex_profile_names_each_key_once_removed_without_breaking() -> None:
    """Every copy lacking one optional key that the models accept is still a document;
    the app-reader check shows each to SimpleDiagrams."""
    full = wire.dump(fixtures.complex_profile_document())
    accepted = 0
    for _, trimmed in fixtures.documents_with_one_key_removed(copy.deepcopy(full)):
        try:
            wire.Document.model_validate_json(json.dumps(trimmed))
            accepted += 1
        except ValidationError:
            continue
    assert accepted >= 15
