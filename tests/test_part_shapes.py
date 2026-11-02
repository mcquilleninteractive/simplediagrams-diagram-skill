"""Tests for the shapes SimpleDiagrams 5.2 draws from their parts, and what else 5.2 added.

Rings, flows, pyramids and funnels, cycles, gauges and entity tables place their own
connection points, which the file does not list, so these cover what each writes, the rules
the app refuses a whole file for breaking, where a connector ends on one, and how much text
5.2 reads before it refuses a document: a limit the skill must meet, since an agent would
otherwise hand over a document that does not open.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import fixtures
import sd_format as wire
from sd_spec import DiagramSpec, SpecError, compile_spec, lint

SPEC_ID = "11111111-2222-4333-8444-555555555555"


def _compile(*nodes: dict, edges: list[dict] | None = None) -> wire.Document:
    return compile_spec(
        DiagramSpec.model_validate({"name": "T", "id": SPEC_ID, "pages": [{"nodes": list(nodes), "edges": edges or []}]})
    )


def _shape(document: wire.Document, index: int = 0) -> tuple[wire.ComplexShape, wire.Rect]:
    element = document.pages[0].elements[index]
    assert element.complex_shape is not None
    return element.complex_shape, element.core.frame


def _rejected(node: dict) -> str:
    with pytest.raises(ValidationError) as failure:
        DiagramSpec.model_validate({"name": "T", "pages": [{"nodes": [node]}]})
    return str(failure.value)


@pytest.mark.parametrize(
    ("node", "settings", "roles", "points"),
    [
        ({"shape": "ring", "sections": ["a", "b"]}, {"ring_width": 40}, ["section"] * 2, [[8], [9]]),
        (
            {"shape": "flow", "steps": ["a", "b"]},
            {"base_shape": "chevron", "direction": "across", "spacing": "gap", "pointer": False},
            ["step"] * 2, [[8, 9], [10, 11]],
        ),
        ({"shape": "pyramid", "layers": ["a", "b"]}, {"form": "pyramid"}, ["layer"] * 2, [[8, 9], [10, 11]]),
        (
            {"shape": "cycle", "steps": ["a", "b", "c"]},
            {"ring_width": 50, "direction": "clockwise", "arrow_style": "arrow"},
            ["step"] * 3, [[8], [9], [10]],
        ),
        (
            {"shape": "gauge", "bands": ["a", "b"]},
            {"minimum": 0, "maximum": 100, "value": 50, "auto_rotate_labels": True},
            ["band", "band", "needle"], [None, None, None],
        ),
    ],
)
def test_each_kind_writes_its_tiles_settings_and_owns_its_points(node: dict, settings: dict, roles: list, points: list) -> None:
    """Every setting is required, a part's points are the next free numbers from 8, and the
    element lists none, or the app refuses the document."""
    document = _compile({"key": "n", "col": 0, "row": 0, **node})
    shape, _ = _shape(document)
    assert shape.settings == settings
    assert [part.role for part in shape.parts] == roles
    assert [part.point_ids for part in shape.parts] == points
    assert document.pages[0].elements[0].core.connection_points == []
    again = wire.Document.model_validate_json(json.dumps(wire.dump(document)))
    assert wire.dump(again) == wire.dump(document)


def test_a_funnel_is_a_pyramid_narrowing_to_a_spout() -> None:
    """A funnel is the pyramid's other form, wide at the top: its layers grow narrower going
    down, which is the opposite of a pyramid's."""
    shape, frame = _shape(_compile({"key": "n", "shape": "pyramid", "form": "funnel", "col": 0, "row": 0, "layers": ["a", "b", "c"]}))
    assert shape.settings["form"] == "funnel"
    layers = wire.pyramid_layers(shape, frame.width, frame.height)
    assert [layer.top_half_width > layer.bottom_half_width for layer in layers] == [True] * 3
    assert layers[-1].bottom_half_width == pytest.approx(frame.width / 2 * wire.FUNNEL_SPOUT_SHARE)


def test_a_part_keeps_its_own_paint_and_others_follow_the_shape() -> None:
    """A part with no paint of its own must not write an empty style, which the app refuses."""
    shape, _ = _shape(_compile({"key": "n", "shape": "ring", "col": 0, "row": 0, "sections": [{"label": "a", "fill": "#F59F00"}, "b"]}))
    assert shape.parts[0].style == wire.PartStyle(fill_hex="#F59F00")
    assert shape.parts[1].style is None


def test_a_parts_paint_and_alignment_reach_the_file() -> None:
    """Each channel a spec gives a part is its own in the file, and `align` reaches its words."""
    shape, _ = _shape(_compile({"key": "n", "shape": "flow", "col": 0, "row": 0, "align": "leading",
                                "steps": [{"label": "a", "stroke": "#112233", "line_width": 3}, "b"]}))
    assert shape.parts[0].style == wire.PartStyle(stroke_hex="#112233", line_width=3)
    assert shape.parts[0].text is not None and shape.parts[0].text.base_alignment == "leading"


def test_a_gauge_can_keep_its_band_words_level() -> None:
    """A spec's choice must not fall back to the default, which is the opposite."""
    shape, _ = _shape(_compile({"key": "n", "shape": "gauge", "col": 0, "row": 0, "bands": ["a"], "auto_rotate_labels": False}))
    assert shape.settings["auto_rotate_labels"] is False


def test_a_cycles_points_follow_its_direction_and_style() -> None:
    """An anticlockwise cycle is the clockwise one mirrored, so a connector to a step ends on
    the other side; a chevron's point sits elsewhere on its step than an arrow's."""
    def first_step(**settings: object) -> tuple[float, float]:
        shape, frame = _shape(_compile({"key": "n", "shape": "cycle", "col": 0, "row": 0, "width": 240, "steps": ["a", "b", "c"], **settings}))
        return wire.shape_points(shape, frame.width, frame.height)[9]

    clockwise, mirrored = first_step(), first_step(direction="anticlockwise")
    assert mirrored == pytest.approx((1 - clockwise[0], clockwise[1]))
    assert first_step(arrow_style="chevron") != pytest.approx(clockwise)
    shape, _ = _shape(_compile({"key": "n", "shape": "cycle", "col": 0, "row": 0, "steps": ["a", "b", "c"], "arrow_style": "chevron"}))
    assert shape.settings["arrow_style"] == "chevron"


def test_a_gauge_says_where_its_needle_points() -> None:
    """The needle is a part with no words, last; its value defaults to the middle of its range."""
    shape, _ = _shape(_compile({"key": "n", "shape": "gauge", "label": "Load", "col": 0, "row": 0, "bands": ["a"], "minimum": 10, "maximum": 30}))
    assert shape.settings["value"] == 20
    assert shape.parts[-1].role == "needle" and shape.parts[-1].text is None
    document = _compile({"key": "n", "shape": "gauge", "label": "Load", "col": 0, "row": 0, "bands": ["a"]})
    assert document.pages[0].elements[0].core.text_content.string == "Load"


@pytest.mark.parametrize(
    ("node", "message"),
    [
        ({"shape": "flow", "steps": ["a"]}, "at least 2 items"),
        ({"shape": "cycle", "steps": ["a", "b"]}, "3 to 8 steps"),
        ({"shape": "cycle", "steps": list("abcdefghi")}, "3 to 8 steps"),
        ({"shape": "pyramid", "layers": ["a"]}, "at least 2 items"),
        ({"shape": "gauge", "bands": list("abcdef")}, "at most 5 items"),
        ({"shape": "ring", "sections": ["a"], "label": "x"}, "remove label"),
        ({"shape": "ring", "sections": ["a"], "ring_width": 45}, "multiple of 10"),
        ({"shape": "cycle", "steps": ["a", "b", "c"], "ring_width": "full"}, "only a ring"),
        ({"shape": "flow", "steps": ["a", "b"], "spacing": "overlap"}, "only rectangle"),
        ({"shape": "flow", "steps": ["a", "b"], "base_shape": "hexagon", "pointer": True}, "only rectangle"),
        ({"shape": "flow", "steps": ["a", "b"], "direction": "vertical"}, "across or down"),
        ({"shape": "swimlanes", "lanes": [{"title": "a"}], "direction": "across"}, "horizontal or vertical"),
        ({"shape": "gauge", "bands": ["a"], "minimum": 5, "maximum": 1}, "below its maximum"),
        ({"shape": "gauge", "bands": ["a"], "value": 500}, "must lie"),
        ({"shape": "gauge", "bands": ["a"], "label": "c" * 501}, "caption"),
        ({"shape": "ring", "sections": ["c" * 501]}, "over 500"),
        ({"shape": "entity_table", "label": "E"}, "needs fields"),
        ({"shape": "entity_table", "fields": [{"name": "a", "marks": ["unique", "unique"]}]}, "repeats a mark"),
        ({"shape": "entity_table", "fields": [{"name": "a", "marks": ["sparkly"]}]}, "marks"),
        ({"shape": "rectangle", "steps": ["a", "b"]}, "steps is for"),
        ({"shape": "cycle", "steps": ["a", "b", "c"], "direction": "across"}, "clockwise or anticlockwise"),
        ({"shape": "ring", "sections": ["a"], "scale": 2}, "scale is for library shapes"),
        ({"shape": "entity_table", "fields": [{"name": "a"}], "align": "trailing"}, "remove align"),
        ({"shape": "note", "note_style": "scroll"}, "note_style"),
        ({"shape": "rectangle", "note_style": "tag"}, "note_style is for"),
    ],
)
def test_what_the_app_refuses_is_refused_in_the_spec(node: dict, message: str) -> None:
    """Each breaks a rule the app refuses a whole document for, so an agent hears it by name
    before there is a document."""
    assert message in _rejected({"key": "n", "col": 0, "row": 0, **node})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda shape: shape["settings"].update(pointer=True),  # a chevron has none
        lambda shape: shape["settings"].update(spacing="overlap"),
        lambda shape: shape["parts"][0].pop("point_ids"),
        lambda shape: shape["parts"][0].update(point_ids=[7, 8]),
        lambda shape: shape["parts"][1].update(point_ids=shape["parts"][0]["point_ids"]),
        lambda shape: shape["parts"][1].update(id=shape["parts"][0]["id"]),
        lambda shape: shape["parts"][0].update(style={}),
        lambda shape: shape["parts"][0].update(style={"fill_texture": "Grain"}),
        lambda shape: shape["parts"][0].pop("text"),
        lambda shape: shape["parts"].pop(),  # one step
        lambda shape: shape.update(members=[]),
    ],
)
def test_the_models_refuse_a_flow_record_the_app_would(mutate) -> None:
    """The models stand between the builder and a file the app refuses, so a fault here must
    never reach a document."""
    dumped = wire.dump(_compile({"key": "n", "shape": "flow", "col": 0, "row": 0, "steps": ["a", "b"]}))
    mutate(dumped["pages"][0]["elements"][0]["complex_shape"])
    with pytest.raises(ValidationError):
        wire.Document.model_validate_json(json.dumps(dumped))


def test_the_elements_keys_follow_the_type() -> None:
    """A shape that places its own points lists none, and one with no text of its own keeps
    its string empty, or the app refuses it."""
    dumped = wire.dump(_compile({"key": "n", "shape": "ring", "col": 0, "row": 0, "sections": ["a"]}))
    core = dumped["pages"][0]["elements"][0]["content"]["content"]["content"]
    core["connection_points"] = [{"id": 0, "x": 0, "y": 0}]
    with pytest.raises(ValidationError, match="lists none"):
        wire.Document.model_validate_json(json.dumps(dumped))
    core["connection_points"] = []
    core["text_content"]["string"] = "hidden"
    with pytest.raises(ValidationError, match="own text must be empty"):
        wire.Document.model_validate_json(json.dumps(dumped))


# ---------------------------------------------------------------------------
# Where connectors end
# ---------------------------------------------------------------------------


def _end(document: wire.Document, edge: int = 0) -> tuple[wire.ConnectorPoint, wire.ConnectorPoint]:
    points = document.pages[0].connections[edge].content.points
    return points[0], points[-1]


def test_a_connector_to_a_ring_section_ends_on_the_circle_at_its_middle() -> None:
    """A section's point is the middle of its outer edge. A ring stays round in any frame, so
    the point is on the circle, not at the frame's fraction of it."""
    document = _compile(
        {"key": "r", "shape": "ring", "x": 300, "y": 300, "width": 400, "height": 200, "sections": ["a", "b"]},
        {"key": "z", "shape": "rectangle", "label": "z", "x": 800, "y": 300},
        edges=[{"source": "r", "target": "z", "source_point": 8}],
    )
    start, _ = _end(document)
    # Section 0 of 2 reaches from twelve o'clock to six, so its middle is at three o'clock.
    assert (start.x, start.y) == pytest.approx((300 + 100, 300))


def test_a_connector_to_a_flow_step_ends_at_its_front() -> None:
    """A chevron's front is the tip of its point; a flow going down has them along its height."""
    document = _compile(
        {"key": "f", "shape": "flow", "x": 400, "y": 200, "width": 360, "height": 80, "steps": ["a", "b", "c"]},
        {"key": "z", "shape": "rectangle", "label": "z", "x": 400, "y": 500},
        edges=[{"source": "f", "target": "z", "source_point": 13}],
    )
    start, _ = _end(document)
    assert (start.x, start.y) == pytest.approx((400 + 180, 200))
    document = _compile(
        {"key": "f", "shape": "flow", "direction": "down", "x": 400, "y": 400, "width": 200, "height": 600, "steps": ["a", "b", "c"]},
        {"key": "z", "shape": "rectangle", "label": "z", "x": 900, "y": 400},
        edges=[{"source": "f", "target": "z", "source_point": 13}],
    )
    start, _ = _end(document)
    assert (start.x, start.y) == pytest.approx((400, 400 + 300))


def test_a_relationship_can_end_on_a_field() -> None:
    """Each field owns two points, its row's ends, so a relationship names the field itself."""
    document = _compile(
        {"key": "a", "shape": "entity_table", "label": "A", "x": 200, "y": 200, "fields": [{"name": "id"}, {"name": "b_id"}]},
        {"key": "b", "shape": "entity_table", "label": "B", "x": 700, "y": 200, "fields": [{"name": "id"}]},
        edges=[{"source": "a", "target": "b", "source_point": 11, "target_point": 8}],
    )
    shape, frame = _shape(document)
    assert [part.point_ids for part in shape.parts if part.role == "field"] == [[8, 9], [10, 11]]
    start, _ = _end(document)
    third = frame.height / 3
    assert (start.x, start.y) == pytest.approx((frame.x + frame.width, frame.y + 2.5 * third))


def test_a_connector_to_a_point_a_shape_lacks_is_refused_naming_its_points() -> None:
    """A pyramid has only its top and bottom among the first eight, and its layers' sides."""
    with pytest.raises(SpecError, match="no connection point 0. Its points are 2, 3, 8, 9, 10, 11"):
        _compile(
            {"key": "p", "shape": "pyramid", "col": 0, "row": 0, "layers": ["a", "b"]},
            {"key": "z", "shape": "rectangle", "label": "z", "col": 2, "row": 0},
            edges=[{"source": "p", "target": "z", "source_point": 0}],
        )
    assert _compile(
        {"key": "p", "shape": "pyramid", "col": 0, "row": 0, "layers": ["a", "b"]},
        {"key": "z", "shape": "rectangle", "label": "z", "col": 2, "row": 0},
        edges=[{"source": "p", "target": "z"}],
    ).pages[0].connections


def test_a_callout_can_lock_its_tail_to_a_part() -> None:
    """The tail locks to any connection point the shape has, its parts' included."""
    document = _compile(
        {"key": "r", "shape": "ring", "col": 0, "row": 0, "sections": ["a"]},
        {"key": "c", "shape": "callout", "label": "Hi", "col": 2, "row": 0, "tail_to": "r", "tail_point": 8},
    )
    shape, _ = _shape(document, 1)
    assert shape.tail_attachment is not None and shape.tail_attachment.connection_point_id == 8


# ---------------------------------------------------------------------------
# Sizes and whether words fit
# ---------------------------------------------------------------------------


def test_a_shape_grows_until_its_words_fit() -> None:
    """Words too long for a tile's size are the commonest fault in these shapes, and an agent
    should not have to find the size by trial; a size the spec gives is never changed."""
    long = ["Customer service", "Fulfilment", "Accounts payable"]
    shape, frame = _shape(_compile({"key": "n", "shape": "ring", "col": 0, "row": 0, "sections": long}))
    assert frame.width > 200 and frame.width == frame.height
    assert shape.settings["ring_width"] > 40 and shape.settings["ring_width"] % 10 == 0
    document = _compile({"key": "n", "shape": "ring", "col": 0, "row": 0, "width": 200, "sections": long})
    assert _shape(document)[1].width == 200
    assert {finding.code for finding in lint(document)} == {"label-overflow"}


@pytest.mark.parametrize(
    "node",
    [
        {"shape": "ring", "sections": ["North", "South", "East", "West"]},
        {"shape": "ring", "sections": ["North", "South"], "ring_width": "full"},
        {"shape": "flow", "steps": ["Discover the need", "Design", "Launch"]},
        {"shape": "flow", "direction": "down", "steps": ["Discover", "Design", "Launch"]},
        {"shape": "flow", "base_shape": "circle", "steps": ["One", "Two"]},
        {"shape": "pyramid", "layers": ["Vision", "Goals", "Tasks"]},
        {"shape": "pyramid", "form": "funnel", "layers": ["Visitors", "Leads", "Sales"]},
        {"shape": "cycle", "steps": ["Plan", "Do", "Check", "Act"]},
        {"shape": "gauge", "label": "Load", "bands": ["Low", "Normal", "High"]},
    ],
)
def test_ordinary_words_build_without_a_warning(node: dict) -> None:
    """An agent is told to fix warnings; left to its defaults the builder must not raise any."""
    assert lint(_compile({"key": "n", "col": 0, "row": 0, **node})) == []


def test_a_gauges_caption_counts_towards_its_size_and_its_warnings() -> None:
    """The caption has one line's room below the needle at a gauge's tile size, so a long one
    must grow the gauge, or be reported when the spec fixes its size."""
    caption = "A caption much too long for the one line of room below this gauge's needle"
    grown = _compile({"key": "g", "shape": "gauge", "label": caption, "col": 0, "row": 0, "bands": ["Low"]})
    assert _shape(grown)[1].width > 200 and lint(grown) == []
    fixed = _compile({"key": "g", "shape": "gauge", "label": caption, "col": 0, "row": 0, "width": 200, "bands": ["Low"]})
    assert [finding.code for finding in lint(fixed)] == ["label-overflow"]
    plain = _compile({"key": "g", "shape": "gauge", "label": "Team load", "col": 0, "row": 0, "bands": ["Low"]})
    assert _shape(plain)[1].width == 200 and lint(plain) == []


def test_a_shape_smaller_than_the_app_draws_is_refused() -> None:
    """Below its smallest the app shrinks the smallest drawing, so its connection points are
    not where the frame says, and a connector would end elsewhere."""
    with pytest.raises(SpecError, match="at least 48 by 48"):
        _compile({"key": "n", "shape": "cycle", "col": 0, "row": 0, "width": 40, "steps": ["a", "b", "c"]})
    with pytest.raises(SpecError, match="at least 32 by 16"):
        _compile({"key": "n", "shape": "flow", "col": 0, "row": 0, "width": 20, "height": 80, "steps": ["a", "b"]})


def test_an_entity_tables_column_widths_are_what_the_spec_says() -> None:
    """Widths a spec gives are not widened to the size a new table starts at."""
    shape, frame = _shape(_compile({"key": "n", "shape": "entity_table", "label": "E", "col": 0, "row": 0, "column_widths": [100, 60], "fields": [{"name": "a"}]}))
    assert shape.column_sizes == [100, 60] and frame.width == 160


def test_an_entity_table_is_sized_to_its_text_and_refused_below_its_smallest_row() -> None:
    """Its type column is the app's smaller grey words, and its header runs across both."""
    document = _compile({"key": "n", "shape": "entity_table", "label": "Customer", "col": 0, "row": 0,
                         "fields": [{"name": "id", "type": "uuid", "marks": ["primary_key"]}, {"name": "note"}]})
    shape, frame = _shape(document)
    assert frame.width >= 220 and shape.settings == {}
    header, *fields = shape.row_parts
    assert header.cells is not None and header.cells[0].string == "Customer" and header.cells[1].string == ""
    assert fields[0].marks == ["primary_key"] and fields[1].marks == []
    assert fields[0].cells is not None
    name, kind = fields[0].cells
    assert (name.base_alignment, kind.base_alignment) == ("leading", "trailing")
    assert kind.base_style.font_size == 12 and kind.base_style.color_hex == "#6C757D"
    assert document.pages[0].elements[0].core.text_content.string == ""
    with pytest.raises(SpecError, match="under 12 points"):
        _compile({"key": "n", "shape": "entity_table", "label": "E", "col": 0, "row": 0, "height": 30, "fields": [{"name": "a"}, {"name": "b"}]})


# ---------------------------------------------------------------------------
# Notes, highlights and proportional containers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("look", "size", "fill"),
    [("stickyNote", (180, 170), "#FFF1A8"), ("indexCard", (250, 150), "#FFFFFF"), ("tapedNote", (200, 150), "#FBF8F1"), ("tag", (230, 100), "#F3E2B8"), ("notebookPage", (200, 250), "#FFFFFF"), ("pinnedNote", (180, 160), "#E6F0FC")],
)
def test_a_note_takes_its_looks_size_and_colours(look: str, size: tuple, fill: str) -> None:
    """Each look arrives as its tile places it, unless the spec says otherwise."""
    element = _compile({"key": "n", "shape": "note", "note_style": look, "col": 0, "row": 0}).pages[0].elements[0]
    assert element.content.note_style == look
    assert (element.core.frame.width, element.core.frame.height) == size
    assert element.core.style.fill_hex == fill
    painted = _compile({"key": "n", "shape": "note", "note_style": look, "fill": "#000000", "width": 90, "col": 0, "row": 0})
    assert painted.pages[0].elements[0].core.style.fill_hex == "#000000"
    assert painted.pages[0].elements[0].core.frame.width == 90


def test_a_decorated_note_keeps_its_words_clear_of_its_decorations() -> None:
    """A place written inside such a note would replace the one the app keeps clear of its
    tape, hole or pin; above or below it is still the spec's to choose."""
    node = {"key": "n", "shape": "note", "note_style": "tag", "col": 0, "row": 0}
    assert "clear of its decorations" in _rejected(node | {"label_position": "top"})
    assert _compile(node | {"label": "x", "label_position": "below"}).pages[0].elements[0].content.text_layout is not None
    assert _compile(node | {"label": "x"}).pages[0].elements[0].content.text_layout is None


def test_a_plain_note_is_unchanged() -> None:
    """A spec that names no look keeps its meaning: a sticky note at the size it always had."""
    element = _compile({"key": "n", "shape": "note", "col": 0, "row": 0}).pages[0].elements[0]
    assert element.content.note_style is None and element.core.frame.width == 140


def test_a_highlight_goes_behind_the_words_wherever_they_are() -> None:
    """Format 19's highlight belongs to a text's style, in a label and in a part alike."""
    document = _compile(
        {"key": "a", "shape": "rectangle", "label": "a", "highlight": "#FFF3BF", "col": 0, "row": 0},
        {"key": "b", "shape": "flow", "steps": ["x", "y"], "highlight": "#FFF3BF", "col": 0, "row": 1},
    )
    plain, flow = document.pages[0].elements
    assert plain.core.text_content.base_style.highlight_hex == "#FFF3BF"
    assert flow.complex_shape is not None
    assert flow.complex_shape.parts[0].text is not None
    assert flow.complex_shape.parts[0].text.base_style.highlight_hex == "#FFF3BF"
    assert "highlight_hex" not in json.dumps(wire.dump(_compile({"key": "c", "shape": "rectangle", "col": 0, "row": 0})))


def test_a_proportional_container_says_so() -> None:
    """Proportional is a layout setting, and a container's Automatic layout stays out of the profile."""
    document = _compile({"key": "a", "shape": "rectangle", "col": 0, "row": 0}, {"key": "c", "shape": "container", "label": "C", "members": ["a"], "layout": "proportional"})
    assert _shape(document, 1)[0].settings["layout"] == "proportional"
    assert "layout" in _rejected({"key": "c", "shape": "container", "col": 0, "row": 0, "layout": "automatic"})


# ---------------------------------------------------------------------------
# How much SimpleDiagrams 5.2 reads
# ---------------------------------------------------------------------------


def test_a_lane_title_over_the_limit_is_refused_in_the_spec() -> None:
    """5.2 refuses a whole document for one lane title over 1,000 characters."""
    failure = _rejected({"key": "s", "shape": "swimlanes", "x": 0, "y": 0, "lanes": [{"title": "L" * 1001}]})
    assert "lanes.0.title" in failure and "at most 1000" in failure
    DiagramSpec.model_validate({"name": "T", "pages": [{"nodes": [{"key": "s", "shape": "swimlanes", "x": 0, "y": 0, "lanes": [{"title": "L" * 1000}]}]}]})


def test_a_table_over_the_limit_is_refused_in_the_spec() -> None:
    """5.2 refuses a whole document for a table over 100,000 characters, though each cell is
    within its own 2,000."""
    cells = [["x" * 1900 for _ in range(10)] for _ in range(6)]
    assert "at most 100000 characters" in _rejected({"key": "t", "shape": "table", "col": 0, "row": 0, "cells": cells})
    fields = [{"name": "x" * 2000, "type": "y" * 2000} for _ in range(26)]
    assert "at most 100000 characters" in _rejected({"key": "t", "shape": "entity_table", "col": 0, "row": 0, "fields": fields})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda shape: shape["parts"][0]["text"].update(string="L" * 1001), "lane title holds at most"),
        (lambda shape: shape["parts"][0].update(members=[{"kind": "element", "id": fixtures._uuid(n)} for n in range(1001, 2002)]), "List should have at most 1000"),
    ],
)
def test_the_models_hold_a_lane_to_its_limits(change, message: str) -> None:
    """The models, not only the spec, stand between a fault and a document 5.2 refuses."""
    dumped = wire.dump(fixtures.complex_profile_document())
    swimlanes = next(e for e in dumped["pages"][0]["elements"] if e.get("complex_shape", {}).get("type") == "swimlanes")
    change(swimlanes["complex_shape"])
    with pytest.raises(ValidationError, match=message):
        wire.Document.model_validate_json(json.dumps(dumped))


def test_the_models_refuse_one_shape_in_two_lanes_of_one_pool() -> None:
    """The app refuses a shape held twice even by one holder, so the check across holders must
    not pass it merely because both lanes belong to the same shape."""
    dumped = wire.dump(fixtures.complex_profile_document())
    swimlanes = next(e for e in dumped["pages"][0]["elements"] if e.get("complex_shape", {}).get("type") == "swimlanes")
    lanes = swimlanes["complex_shape"]["parts"]
    lanes[1]["members"] = list(lanes[0]["members"])
    with pytest.raises(ValidationError, match="lists a member twice"):
        wire.Document.model_validate_json(json.dumps(dumped))


@pytest.mark.parametrize(
    "change",
    [
        lambda ring: ring["parts"][1].update(style=None),
        lambda ring: ring["parts"][0]["style"].update(stroke_hex=None),
        lambda ring: ring.update(hand_drawn=None),
        lambda ring: ring.update(members=None),
    ],
)
def test_a_null_in_a_complex_record_is_refused(change) -> None:
    """The app refuses null there, though it reads one as absent elsewhere in a document."""
    dumped = wire.dump(fixtures.complex_profile_document())
    ring = next(e for e in dumped["pages"][0]["elements"] if e.get("complex_shape", {}).get("type") == "ring")
    change(ring["complex_shape"])
    with pytest.raises(ValidationError, match="holds no null"):
        wire.Document.model_validate_json(json.dumps(dumped))


def test_a_proportional_container_is_never_turned() -> None:
    """The app refuses a turned one, though a free container may be turned."""
    dumped = wire.dump(fixtures.complex_profile_document())
    element = next(e for e in dumped["pages"][0]["elements"] if e.get("complex_shape", {}).get("settings", {}).get("layout") == "proportional")
    core = element["content"]["content"]["content"]
    core["rotation_degrees"] = 30
    with pytest.raises(ValidationError, match="never turned"):
        wire.Document.model_validate_json(json.dumps(dumped))
    core["rotation_degrees"] = 360
    wire.Document.model_validate_json(json.dumps(dumped))


def test_the_models_hold_a_table_and_a_cell_to_their_limits() -> None:
    """Characters are counted as Unicode scalars, so an accented cell counts as the app counts it."""
    cell = lambda text: wire.text_content(text)
    with pytest.raises(ValidationError, match="table cell holds at most"):
        wire.table_shape([1.0], [1.0], [[cell("é" * 2001)]])
    wire.table_shape([1.0], [1.0], [[cell("é" * 2000)]])
    with pytest.raises(ValidationError, match="table holds at most"):
        wire.table_shape([1.0] * 6, [1.0] * 10, [[cell("x" * 1900) for _ in range(10)] for _ in range(6)])


def test_a_page_holds_only_so_many_complex_shapes() -> None:
    """5.2 refuses a document with a page over its limit, however small each shape is."""
    style = wire.ElementStyle(fill_hex="#FFFFFF", stroke_hex="#000000", line_width=1.0)
    elements = [
        wire.element(
            id=fixtures._uuid(index + 1), kind="complex_shape", frame=wire.Rect(x=0.0, y=0.0, width=180.0, height=80.0),
            style=style, complex_shape=wire.callout_shape(),
        )
        for index in range(wire.MAX_PAGE_COMPLEX_SHAPES + 1)
    ]
    with pytest.raises(ValidationError, match="at most 2000 complex shapes"):
        wire.document(id=fixtures.DOCUMENT_ID, name="Many", pages=[wire.page(id=fixtures._uuid(9_999), name="P", elements=elements)])


def test_the_preview_leaves_a_transparent_part_unfilled(tmp_path: Path) -> None:
    """A wireframe that filled a see-through part with black would hide its words."""
    spec = tmp_path / "clear.json"
    spec.write_text(json.dumps({"name": "C", "pages": [{"nodes": [
        {"key": "f", "shape": "flow", "col": 0, "row": 0, "steps": [{"label": "a", "fill": "#00000000"}, "b"]}]}]}))
    target = tmp_path / "clear.svg"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "preview_diagram.py"), str(spec), str(target)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'fill="none"' in target.read_text()


def test_the_preview_draws_each_kind_with_its_words(tmp_path: Path) -> None:
    """An agent checks a layout in the preview before building, so every kind must draw there,
    and a part's words must show."""
    spec = tmp_path / "all.json"
    spec.write_text(json.dumps({"name": "All", "pages": [{"nodes": [
        {"key": "r", "shape": "ring", "col": 0, "row": 0, "sections": ["Ringword", "Other"]},
        {"key": "o", "shape": "ring", "col": 1, "row": 0, "sections": ["Solo"]},
        {"key": "f", "shape": "flow", "col": 2, "row": 0, "steps": ["Flowword", "B"], "direction": "down"},
        {"key": "p", "shape": "pyramid", "col": 0, "row": 2, "layers": ["Layerword", "B"]},
        {"key": "c", "shape": "cycle", "col": 1, "row": 2, "steps": ["Cycleword", "B", "C"], "direction": "anticlockwise"},
        {"key": "g", "shape": "gauge", "col": 2, "row": 2, "label": "Caption", "bands": ["Band"]},
        {"key": "e", "shape": "entity_table", "col": 3, "row": 2, "label": "Entity", "fields": [{"name": "Fieldword", "type": "uuid"}]},
    ]}]}))
    target = tmp_path / "all.svg"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "preview_diagram.py"), str(spec), str(target)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    drawn = target.read_text()
    ET.fromstring(drawn)
    for word in ("Ringword", "Solo", "Flowword", "Layerword", "Cycleword", "Caption", "Band", "Entity", "Fieldword"):
        assert word in drawn


def test_a_word_bubbles_label_keeps_to_its_bubble() -> None:
    """5.1.1 gave word bubbles a label area clear of their tail; a copy the skill places must
    have it too, or its words sit across the tail."""
    element = _compile({"key": "b", "shape": "wordBubbles/wordBubble25", "label": "Hi", "col": 0, "row": 0}).pages[0].elements[0]
    layout = element.content.text_layout
    assert layout is not None
    assert (layout.frame.x, layout.frame.y, layout.frame.width, layout.frame.height) == (0.172, 0.184, 0.664, 0.54)


def test_the_cycle_geometry_keeps_the_band_inside_its_circle() -> None:
    """A band wider than the circle allows is drawn narrower, as the app draws it, so the
    points stay on the shape however wide a spec asks for."""
    made = _compile({"key": "n", "shape": "cycle", "col": 0, "row": 0, "width": 100, "ring_width": 900, "steps": ["", "", ""]})
    shape, frame = _shape(made)
    band = wire.cycle_band(shape, frame.width, frame.height)
    assert 0 < band.inner < band.outer <= band.radius == 50
    for x, y in wire.shape_points(shape, frame.width, frame.height).values():
        assert math.hypot(x * 100 - 50, y * 100 - 50) <= band.outer + 1e-6
