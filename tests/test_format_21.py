"""Tests for what document formats 20 and 21 added, which SimpleDiagrams 5.4 writes.

Lists in a label, collapsed notes and three more note looks, a label beside each end of a
connector, a ring's shares and its up to 20 sections, a table's `uml_box`, the audience and
the Gantt chart. These cover what the builder writes for each, the rules the app refuses a
whole document for breaking, and where the builder works out the connection points the file
does not list. `maintainers/check_against_app.py` shows the same documents to the app's own
reader; these keep the builder to what that run established.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import fixtures
import sd_format as wire
from sd_spec import DiagramSpec, SpecError, compile_spec, lint, list_text

SPEC_ID = "11111111-2222-4333-8444-555555555555"
PLAN = [
    {"label": "Plan", "tasks": [
        {"label": "Research", "key": "research", "start": "2026-11-09", "days": 5},
        {"label": "Sketches", "days": 5, "done": True},
    ]},
    {"label": "Build", "fill": "#F59F00", "tasks": [
        {"label": "Prototype", "after": "research", "days": 10, "critical": True},
        {"label": "Launch", "milestone": True},
    ]},
]


def _compile(*nodes: dict, edges: list[dict] | None = None) -> wire.Document:
    return compile_spec(
        DiagramSpec.model_validate({"name": "T", "id": SPEC_ID, "pages": [{"nodes": list(nodes), "edges": edges or []}]})
    )


def _refused(node: dict, **page: object) -> str:
    """Why a spec with this node is refused, when it is checked or when it is compiled."""
    with pytest.raises((ValidationError, SpecError)) as failure:
        compile_spec(DiagramSpec.model_validate({"name": "T", "pages": [{"nodes": [node], **page}]}))
    return str(failure.value)


def _record(document: wire.Document, index: int = 0) -> dict:
    return wire.dump(document.pages[0].elements[index])["complex_shape"]


def _changed(document: wire.Document, change) -> str:
    """Why the models refuse a written document after `change` to its first page's elements."""
    dumped = json.loads(json.dumps(wire.dump(document)))
    change(dumped["pages"][0]["elements"])
    with pytest.raises(ValidationError) as failure:
        wire.Document.model_validate_json(json.dumps(dumped))
    return str(failure.value)


def _parts(elements: list, kind: str) -> list[dict]:
    return next(item for item in elements if item.get("complex_shape", {}).get("type") == kind)["complex_shape"]["parts"]


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def test_marked_lines_become_list_items_without_their_marks() -> None:
    """The app draws bullets and counts numbers itself, so a mark left in the words would
    show twice; items in a row of one kind and level share a run, as the app writes them."""
    document = _compile({
        "key": "n", "shape": "note", "note_style": "documentation", "lists": True, "x": 0, "y": 0,
        "label": "Before shipping\n1. Check the order\n  - Stock\n  - Price\n2. Pack it\n    - Box",
    })
    text = wire.dump(document.pages[0].elements[0].core.text_content)
    assert text["string"] == "Before shipping\nCheck the order\nStock\nPrice\nPack it\nBox"
    assert text["paragraph_runs"] == [
        {"alignment": "leading", "list": {"kind": "number", "level": 1}, "range": {"location": 16, "length": 16}},
        {"alignment": "leading", "list": {"kind": "bullet", "level": 2}, "range": {"location": 32, "length": 12}},
        {"alignment": "leading", "list": {"kind": "number", "level": 1}, "range": {"location": 44, "length": 8}},
        {"alignment": "leading", "list": {"kind": "bullet", "level": 3}, "range": {"location": 52, "length": 3}},
    ]


def test_a_label_keeps_its_marks_unless_lists_is_asked_for() -> None:
    """Spec version 1 keeps its meaning: a label written before lists existed, with a line
    starting '- ', must still be written exactly as it was."""
    document = _compile({"key": "n", "shape": "rectangle", "x": 0, "y": 0, "label": "Totals\n- before tax"})
    text = document.pages[0].elements[0].core.text_content
    assert (text.string, text.paragraph_runs) == ("Totals\n- before tax", [])


def test_a_list_items_run_is_counted_in_utf16_units() -> None:
    """A run's range counts UTF-16 units, so an emoji before an item counts twice; counted in
    characters, the run would start inside a word and the app would refuse the document."""
    words, runs = list_text("café \U0001F600\n- one\n- two\n")
    assert words == "café \U0001F600\none\ntwo\n"
    assert [(run.range.location, run.range.length) for run in runs] == [(8, 8)]
    wire.text_content(words, paragraph_runs=runs)


def test_a_list_run_covers_whole_paragraphs_and_at_most_three_levels() -> None:
    """A paragraph is an item when its first character is in the run, so a run cut short
    would make half an item; the app refuses a level over 3 and a kind it does not know."""
    item = {"range": {"location": 4, "length": 3}, "alignment": "leading", "list": {"kind": "bullet", "level": 1}}
    text = wire.dump(wire.text_content("One\nTwo")) | {"paragraph_runs": [item]}
    wire.TextContent.model_validate_json(json.dumps(text))
    for change in (
        {"range": {"location": 5, "length": 2}},
        {"list": {"kind": "bullet", "level": 4}},
        {"list": {"kind": "dash", "level": 1}},
    ):
        with pytest.raises(ValidationError):
            wire.TextContent.model_validate_json(json.dumps(text | {"paragraph_runs": [item | change]}))


def test_a_line_that_only_looks_like_a_list_item_is_refused() -> None:
    """A mark or indent the builder does not read would be kept as words, and the list would
    come out wrong without a word of warning; the builder stops and says what an item is."""
    for line in ("* Stock", "1) Stock", " - Stock", "      - Stock"):
        reason = _refused({"key": "n", "shape": "note", "lists": True, "x": 0, "y": 0, "label": f"Check\n{line}"})
        assert "looks like a list item" in reason and "node 'n'" in reason


def test_lists_are_refused_on_a_shape_whose_words_are_in_parts() -> None:
    """The builder turns list marks into items only in a shape's own label; on a table or a
    chart the field would be silently ignored, so it is refused instead."""
    assert "lists is for" in _refused({"key": "t", "shape": "table", "lists": True, "cells": [["- a"]], "x": 0, "y": 0})


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("look", "size", "paint"),
    [
        ("documentation", (300, 220), ("#FFFFFF", "#C5CBD3", 1)),
        ("textAnnotation", (120, 60), ("#FFFFFF", "#212529", 1)),
        ("umlNote", (120, 80), ("#FFFFFF", "#212529", 1)),
    ],
)
def test_the_three_newer_note_looks_arrive_as_their_tiles_do(look: str, size: tuple, paint: tuple) -> None:
    """Each look comes with a size, colours and leading words of its own in the app; a note
    placed at the sticky note's would not look like the one a person drags out."""
    element = _compile({"key": "n", "shape": "note", "note_style": look, "label": "Words", "x": 0, "y": 0}).pages[0].elements[0]
    core = element.core
    assert element.content.note_style == look
    assert (core.frame.width, core.frame.height) == size
    assert (core.style.fill_hex, core.style.stroke_hex, core.style.line_width) == paint
    assert core.text_content.base_alignment == "leading"


def test_a_collapsed_note_is_written_only_as_true_and_only_on_a_note() -> None:
    """The app refuses `collapsed` on any other kind, and a writer leaves the key out for a
    note shown in full."""
    document = _compile(
        {"key": "n", "shape": "note", "collapsed": True, "label": "Why", "x": 0, "y": 0},
        {"key": "m", "shape": "note", "label": "Shown", "x": 300, "y": 0},
    )
    first, second = (wire.dump(element)["content"] for element in document.pages[0].elements)
    assert first["collapsed"] is True and "collapsed" not in second
    assert "collapsed is for a note" in _refused({"key": "r", "shape": "rectangle", "collapsed": True, "x": 0, "y": 0})
    assert "collapsed" in _changed(document, lambda elements: elements[1]["content"].update(collapsed=False))


def test_a_collapsed_note_stands_on_the_page_as_its_icon() -> None:
    """The app takes a collapsed note as the small icon at the top right of its frame: that
    is what a person sees, and where its connectors are drawn to. So the node's position is
    the icon's, its frame may lie over another shape without a warning, and a connector is
    stored ending on the icon, not on the frame the note has when it is opened."""
    note = {"key": "n", "shape": "note", "note_style": "documentation", "collapsed": True, "label": "Why", "x": 300, "y": 200}
    box = {"key": "b", "shape": "rectangle", "label": "Task", "x": 220, "y": 300}
    link = {"source": "n", "target": "b", "pattern": "dotted", "end_ending": "none"}
    document = _compile(note, box, edges=[link | {"route": "straight"}])
    frame = document.pages[0].elements[0].core.frame
    # The 28-point icon is centred on the node's position; the 300 by 220 note opens from it.
    assert (frame.x + frame.width - 14, frame.y + 14) == (300, 200)
    assert (frame.width, frame.height) == (300, 220)
    start = document.pages[0].connections[0].content.points[0]
    assert (start.x, start.y) == (300, 214)
    assert lint(document) == []
    assert "route 'straight'" in _refused(note, nodes=[note, box], edges=[link])


# ---------------------------------------------------------------------------
# Labels beside a connector's ends
# ---------------------------------------------------------------------------


def test_end_labels_are_written_where_the_app_places_new_ones() -> None:
    """A UML multiplicity sits beside its end; it is placed by its distance from that end,
    so the builder writes the app's own starting place and leaves the layout to the app."""
    document = _compile(
        {"key": "a", "shape": "rectangle", "label": "Order", "x": 0, "y": 0},
        {"key": "b", "shape": "rectangle", "label": "Line", "x": 400, "y": 0},
        edges=[{"source": "a", "target": "b", "source_label": "1", "target_label": "0..*\nitems"}],
    )
    connection = wire.dump(document.pages[0].connections[0])
    assert (connection["start_label"]["content"]["string"], connection["end_label"]["content"]["string"]) == ("1", "0..*\nitems")
    assert (connection["end_label"]["distance"], connection["end_label"]["normal_offset"]) == (4.0, -2.0)
    assert "label" not in connection["content"]


def test_end_labels_of_lines_sharing_a_point_take_opposite_sides() -> None:
    """Two owners' lines arrive at one point of the thing they own, each with its share
    beside that end. At the app's one starting place the second would cover the first, so
    it goes to the line's other side; a label alone at its point stays where the app puts it."""
    document = _compile(
        {"key": "a", "shape": "rectangle", "label": "Trust", "x": 0, "y": 0},
        {"key": "b", "shape": "rectangle", "label": "Founder", "x": 600, "y": 0},
        {"key": "c", "shape": "rectangle", "label": "Holdings", "x": 300, "y": 300},
        {"key": "d", "shape": "rectangle", "label": "Subsidiary", "x": 300, "y": 600},
        edges=[
            {"source": "a", "target": "c", "target_label": "60%", "source_side": "bottom", "target_side": "top"},
            {"source": "b", "target": "c", "target_label": "40%", "source_side": "bottom", "target_side": "top"},
            {"source": "c", "target": "d", "target_label": "100%", "source_side": "bottom", "target_side": "top"},
        ],
    )
    first, second, alone = (wire.dump(connection) for connection in document.pages[0].connections)
    assert first["content"]["end_attachment"] == second["content"]["end_attachment"]
    assert [c["end_label"]["normal_offset"] for c in (first, second, alone)] == [-2.0, 2.0, -2.0]


def test_an_end_label_holds_at_most_200_characters() -> None:
    """The app refuses a document whose end label is longer, so the spec stops it first."""
    with pytest.raises(ValidationError):
        DiagramSpec.model_validate({"name": "T", "pages": [{
            "nodes": [{"key": "a", "shape": "rectangle", "x": 0, "y": 0}, {"key": "b", "shape": "rectangle", "x": 300, "y": 0}],
            "edges": [{"source": "a", "target": "b", "target_label": "x" * 201}],
        }]})
    with pytest.raises(ValidationError):
        wire.end_label(wire.text_content("x" * 201))


# ---------------------------------------------------------------------------
# Tables and rings
# ---------------------------------------------------------------------------


def test_a_table_says_which_uml_box_it_stands_for() -> None:
    """Format 21 requires `uml_box` on every table; a class box says so, so the app treats
    it as one, and an ordinary table says `none`."""
    document = _compile(
        {"key": "c", "shape": "table", "uml_box": "class", "cells": [["Order"], ["id"]], "x": 0, "y": 0},
        {"key": "t", "shape": "table", "cells": [["a", "b"]], "x": 400, "y": 0},
    )
    assert [_record(document, index)["settings"]["uml_box"] for index in (0, 1)] == ["class", "none"]
    assert "uml_box" in _changed(document, lambda elements: _parts(elements, "table") and elements[0]["complex_shape"]["settings"].pop("uml_box"))


def test_a_rings_shares_are_whole_percentages_that_fit_the_circle() -> None:
    """A section without a share takes an equal part of what the others leave, at least 1,
    and the shares never pass 100: the app refuses a ring breaking either."""
    document = _compile({"key": "r", "shape": "ring", "x": 0, "y": 0, "sections": [{"label": "a", "share": 30}, "b", "c"]})
    shape = document.pages[0].elements[0].complex_shape
    assert [part.size for part in shape.parts] == [30, None, None]
    assert wire.ring_shares(shape) == [30, 35, 35]
    for sections in ([{"label": "a", "share": 60}, {"label": "b", "share": 41}], [{"label": "a", "share": 99}, "b", "c"]):
        assert "add up to at most 100" in _refused({"key": "r", "shape": "ring", "x": 0, "y": 0, "sections": sections})
    assert "whole number" in _changed(document, lambda elements: _parts(elements, "ring")[0].update(size=30.5))
    assert "share is for a ring" in _refused(
        {"key": "f", "shape": "flow", "x": 0, "y": 0, "steps": [{"label": "a", "share": 50}, "b"]}
    )


def test_a_ring_holds_up_to_twenty_sections() -> None:
    """Format 21 widened a ring from 12 sections to 20; the app refuses a twenty-first."""
    _compile({"key": "r", "shape": "ring", "x": 0, "y": 0, "width": 400, "sections": [f"s{index}" for index in range(20)]})
    with pytest.raises(ValidationError):
        DiagramSpec.model_validate({"name": "T", "pages": [{"nodes": [
            {"key": "r", "shape": "ring", "x": 0, "y": 0, "sections": [f"s{index}" for index in range(21)]}
        ]}]})


def test_a_sections_point_is_at_the_middle_of_its_share() -> None:
    """A connector to a section is stored ending at its point, which lies half way round its
    own share of the circle, not half way round an equal one."""
    document = _compile({"key": "r", "shape": "ring", "ring_width": "full", "x": 0, "y": 0,
                         "sections": [{"label": "a", "share": 50}, {"label": "b", "share": 25}, {"label": "c", "share": 25}]})
    shape = document.pages[0].elements[0].complex_shape
    points = wire.shape_points(shape, 200, 200)
    # Half of the first half is three o'clock; the middles of the two quarters lie either side of nine.
    assert points[8] == pytest.approx((1.0, 0.5))
    assert points[9] == pytest.approx((0.5 - 0.5 * 2**-0.5, 0.5 + 0.5 * 2**-0.5))
    assert points[10] == pytest.approx((0.5 - 0.5 * 2**-0.5, 0.5 - 0.5 * 2**-0.5))


def test_a_pie_of_many_named_slices_is_given_room_for_their_names() -> None:
    """A thin slice's name is set outside the circle in what room the frame leaves beside it,
    so a pie left to the builder grows until its names fit there or in their slices, and one
    sized too small for them is reported."""
    names = ["North", "South", "East", "West", "Centre", "Coast", "Islands", "Abroad", "Online", "Other"]
    grown = _compile({"key": "r", "shape": "ring", "ring_width": "full", "x": 0, "y": 0, "sections": names})
    assert grown.pages[0].elements[0].core.frame.width > 200 and lint(grown) == []
    small = _compile({"key": "r", "shape": "ring", "ring_width": "full", "x": 0, "y": 0, "width": 200, "sections": names})
    assert {finding.code for finding in lint(small)} == {"label-overflow"}


def test_a_ring_with_a_thin_section_is_drawn_on_a_smaller_circle() -> None:
    """SimpleDiagrams 5.4 sets a thin section's name outside the circle and draws the circle
    smaller to make room, which moves every connection point; the builder ends connectors
    there."""
    wide = _compile({"key": "r", "shape": "ring", "ring_width": "full", "x": 0, "y": 0, "sections": ["a", "b", "c"]})
    thin = _compile({"key": "r", "shape": "ring", "ring_width": "full", "x": 0, "y": 0, "width": 200,
                     "sections": [{"label": "Mostly", "share": 96}, {"label": "Remainder", "share": 4}]})
    wide_shape, thin_shape = (document.pages[0].elements[0].complex_shape for document in (wide, thin))
    assert wire.ring_thin_sections(wide_shape, 200, 200) == [] and wire.ring_radius(wide_shape, 200, 200) == 100
    assert wire.ring_thin_sections(thin_shape, 200, 200) == [1]
    assert wire.ring_radius(thin_shape, 200, 200) == pytest.approx(70)
    assert wire.shape_points(thin_shape, 200, 200)[1] == pytest.approx((0.85, 0.5))


# ---------------------------------------------------------------------------
# The audience
# ---------------------------------------------------------------------------


def test_an_audience_is_groups_of_seats_each_in_a_colour_of_its_own() -> None:
    """A group is only a number of seats and its paint; without a colour of its own every
    group would be drawn alike, so the builder gives each the app's next colour."""
    document = _compile({"key": "u", "shape": "audience", "x": 0, "y": 0, "show_total": False,
                         "groups": [50, {"seats": 30, "fill": "#F59F00"}, 20]})
    record = _record(document)
    assert record["settings"] == {"show_total": False}
    assert [(part["role"], part["size"], part["style"]["fill_hex"]) for part in record["parts"]] == [
        ("group", 50, "#6CA0BB"), ("group", 30, "#F59F00"), ("group", 20, "#ED692F"),
    ]
    assert all(set(part) == {"role", "id", "size", "style"} for part in record["parts"])
    element = document.pages[0].elements[0]
    assert element.core.connection_points == [] and element.core.text_content.string == ""


def test_an_audience_holds_at_most_a_thousand_seats_and_no_words() -> None:
    """The app refuses an audience over 1,000 seats, or with words of its own: its total is
    worked out, never typed."""
    assert "at most 1000 seats" in _refused({"key": "u", "shape": "audience", "x": 0, "y": 0, "groups": [600, 401]})
    assert "groups" in _refused({"key": "u", "shape": "audience", "x": 0, "y": 0, "groups": [True]})
    assert "remove label" in _refused({"key": "u", "shape": "audience", "label": "Board", "x": 0, "y": 0, "groups": [3]})
    document = _compile({"key": "u", "shape": "audience", "x": 0, "y": 0, "groups": [600, 400]})
    assert "at most 1000 seats" in _changed(document, lambda elements: _parts(elements, "audience")[0].update(size=601))
    assert "group" in _changed(document, lambda elements: _parts(elements, "audience")[0].update(marks=["done"]))


def test_an_audiences_points_lie_on_its_arch_and_its_base_line() -> None:
    """The arch is the half circle that fits the frame, centred, so in a tall frame its
    points are nowhere near the frame's corners, where a connector would otherwise end."""
    shape = wire.audience_shape([wire.seat_group(fixtures._uuid(1), 10)])
    points = wire.shape_points(shape, 240, 140)
    # A radius of 120, its base line 130 down: 10 above the bottom of the frame.
    assert points[0] == pytest.approx((0.0, 130 / 140)) and points[1] == pytest.approx((1.0, 130 / 140))
    assert points[2] == pytest.approx((0.5, 10 / 140)) and points[3] == pytest.approx((0.5, 130 / 140))
    assert points[5] == pytest.approx(((120 - 84) / 240, 130 / 140))
    tall = wire.shape_points(shape, 100, 300)
    assert tall[2] == pytest.approx((0.5, 125 / 300)) and tall[3] == pytest.approx((0.5, 175 / 300))


# ---------------------------------------------------------------------------
# The Gantt chart
# ---------------------------------------------------------------------------


def test_a_gantt_chart_writes_its_sections_then_its_tasks() -> None:
    """A section's size says how many of the tasks that follow are its own, a task names the
    task it follows by id, and a milestone holds no length: each is a rule the app refuses a
    chart for breaking."""
    document = _compile({"key": "g", "shape": "gantt", "label": "Launch", "x": 0, "y": 0, "plan": PLAN})
    record = _record(document)
    assert record["settings"] == {"skip_weekends": False}
    sections, tasks = record["parts"][:2], record["parts"][2:]
    assert [(part["role"], part["text"]["string"], part["size"]) for part in sections] == [("section", "Plan", 2), ("section", "Build", 2)]
    assert [part["style"]["fill_hex"] for part in sections] == ["#6CA0BB", "#F59F00"]
    assert [part["point_ids"] for part in tasks] == [[8, 9], [10, 11], [12, 13], [14, 15]]
    assert tasks[0]["start"] == "2026-11-09" and "after" not in tasks[0]
    assert tasks[1]["marks"] == ["done"] and "start" not in tasks[1]
    assert tasks[2]["after"] == [tasks[0]["id"]] and tasks[2]["marks"] == ["crit"]
    assert tasks[3]["marks"] == ["milestone"] and "size" not in tasks[3]
    # A name reads from the start of its bar, as the app's do; the title is centred.
    assert {part["text"]["base_alignment"] for part in record["parts"]} == {"leading"}
    element = document.pages[0].elements[0]
    assert element.core.text_content.string == "Launch" and element.core.connection_points == []
    # A row of the tile's height for each task, at the tile's width.
    assert (element.core.frame.width, element.core.frame.height) == (480, 220)


def test_tasks_fall_on_the_days_the_app_works_out() -> None:
    """A day's end is the next day's start, a task with no start follows the one above it,
    and a milestone takes no time; with weekends skipped a length counts weekdays only and a
    start that lands on a Saturday moves to the Monday."""
    def spans(skip: bool) -> list[tuple[int, int]]:
        document = _compile({"key": "g", "shape": "gantt", "x": 0, "y": 0, "skip_weekends": skip, "plan": PLAN})
        return wire.gantt_spans(document.pages[0].elements[0].complex_shape)

    monday = wire.day_number("2026-11-09")
    # Research Monday to Saturday; Sketches the next five days; Prototype after Research;
    # Launch on the day Prototype ends.
    assert spans(False) == [(monday, monday + 5), (monday + 5, monday + 10), (monday + 5, monday + 15), (monday + 15, monday + 15)]
    # Research still ends where Saturday begins, but what follows it starts on the Monday.
    assert spans(True) == [(monday, monday + 5), (monday + 7, monday + 12), (monday + 7, monday + 19), (monday + 21, monday + 21)]


def test_a_tasks_points_are_the_ends_of_its_bar() -> None:
    """A connector to a task is stored ending at the start or end of its bar, which depends
    on the days the axis spans: here one week-long task on a week axis, half a week either side."""
    document = _compile(
        {"key": "g", "shape": "gantt", "x": 400, "y": 300, "plan": [{"tasks": [{"label": "Only", "start": "2026-11-09", "days": 7}]}]},
        {"key": "b", "shape": "rectangle", "label": "Next", "x": 900, "y": 300},
        edges=[{"source": "g", "target": "b", "source_point": 9}],
    )
    element = document.pages[0].elements[0]
    frame = element.core.frame
    points = wire.shape_points(element.complex_shape, frame.width, frame.height)
    # The time area runs from 104 to 472 across 14 days; the one row is 160 tall, from 32.
    assert points[8] == pytest.approx((196 / 480, 112 / 220)) and points[9] == pytest.approx((380 / 480, 112 / 220))
    start = document.pages[0].connections[0].content.points[0]
    assert (start.x, start.y) == pytest.approx((frame.x + 380, frame.y + 112))


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda tasks: tasks[0].pop("start"), "first task needs a start"),
        (lambda tasks: tasks[1].update(start="2026-11-20", after="research"), "a start and an after"),
        (lambda tasks: tasks[1].update(after="nobody"), "not the key of another"),
        (lambda tasks: tasks[1].pop("days"), "needs days"),
        (lambda tasks: tasks[1].update(milestone=True), "remove its days"),
        (lambda tasks: tasks[0].update(start="2026-02-30"), "not a real day"),
        (lambda tasks: tasks[0].update(start="2199-12-30"), "1900-01-01 to 2199-12-31"),
    ],
)
def test_a_plan_the_app_would_refuse_is_refused_with_its_reason(change, reason: str) -> None:
    """Each of these makes a chart the app refuses whole, so the builder stops and says
    which task to fix."""
    tasks = [
        {"label": "Research", "key": "research", "start": "2026-11-09", "days": 5},
        {"label": "Sketches", "days": 5},
    ]
    change(tasks)
    assert reason in _refused({"key": "g", "shape": "gantt", "x": 0, "y": 0, "plan": [{"label": "Plan", "tasks": tasks}]})


def test_tasks_that_follow_one_another_in_a_loop_are_refused() -> None:
    """Following `after` from task to task must never come back to where it began; the app
    refuses such a chart, and so do the spec and the models."""
    tasks = [
        {"label": "Fixed", "start": "2026-11-09", "days": 1},
        {"label": "A", "key": "a", "after": "b", "days": 2},
        {"label": "B", "key": "b", "after": "a", "days": 2},
    ]
    assert "in a loop" in _refused({"key": "g", "shape": "gantt", "x": 0, "y": 0, "plan": [{"tasks": tasks}]})


def test_the_models_hold_a_gantt_chart_to_its_rules() -> None:
    """The models, not only the spec, stand between a fault and a document the app refuses."""
    document = _compile({"key": "g", "shape": "gantt", "x": 0, "y": 0, "plan": PLAN})
    tasks = lambda elements: [part for part in _parts(elements, "gantt") if part["role"] == "task"]
    for change, reason in (
        (lambda elements: _parts(elements, "gantt")[0].update(size=3), "add up to the number of its tasks"),
        (lambda elements: tasks(elements)[1].update(marks=["active"]), "marks are any of"),
        (lambda elements: tasks(elements)[2].update(after=[_parts(elements, "gantt")[0]["id"]]), "names one other task"),
        (lambda elements: tasks(elements)[3].update(size=2), "exactly when it is not a milestone"),
        (lambda elements: tasks(elements)[0].update(start="2026-11-9"), "start"),
        (lambda elements: tasks(elements)[1].update(size=3651), "whole number from 1 to 3650"),
    ):
        assert reason in _changed(document, change)


def test_a_connector_between_two_tasks_runs_straight_across_their_chart() -> None:
    """A task's points lie inside its chart, so a route worked out to keep off shapes would
    leave the chart and come back; the line between two tasks is straight, and crossing its
    own chart is not a fault to report."""
    chart = {"key": "g", "shape": "gantt", "x": 400, "y": 300, "plan": PLAN}
    link = {"source": "g", "target": "g", "source_point": 9, "target_point": 12}
    document = _compile(chart, edges=[link | {"route": "straight"}])
    assert len(document.pages[0].connections[0].content.points) == 2
    assert lint(document) == []
    assert "route 'straight'" in _refused(chart, edges=[link])


def test_a_task_name_too_long_for_its_place_is_reported() -> None:
    """A task's name is set beside its bar in what is left of the chart's width, on one row,
    so a long one is cut short in the app unless the chart is made wider."""
    plan = [{"label": "Plan", "tasks": [{"label": "Agree the scope of the research with every team lead", "start": "2026-11-09", "days": 5}]}]
    document = _compile({"key": "g", "shape": "gantt", "x": 400, "y": 300, "plan": plan})
    assert [finding.code for finding in lint(document)] == ["label-overflow"]
    wide = _compile({"key": "g", "shape": "gantt", "x": 400, "y": 300, "width": 1000, "plan": plan})
    assert lint(wide) == []


def test_a_gantt_chart_too_small_for_its_rows_is_refused() -> None:
    """Below its smallest frame the app draws the chart shrunk, so its points would not be
    where the frame says and a connector would end beside its task."""
    assert "at least 200 by 108" in _refused({"key": "g", "shape": "gantt", "x": 0, "y": 0, "height": 90, "plan": PLAN})
