"""Exact models of a SimpleDiagrams document at package format 19, which SimpleDiagrams
5.2 writes and reads.

Every document the skill writes is package 19 / schema 18 and needs SimpleDiagrams 5.2
or later. Besides shapes, text and connectors it holds the shapes the app draws itself
(complex shapes: containers, swimlanes, tables, entity tables, callouts, UML lifelines,
rings, flows, pyramids and funnels, cycles and gauges), connector ends attached anywhere
along a lifeline, and label regions that start outside their shape.

A `.simplediagram` document is a folder holding `manifest.json`,
`document.json` and an `assets/` directory. These Pydantic models describe the
two JSON files for the *authoring profile*: everything an agent needs to place
shapes, text and connectors, and nothing that needs binary assets.

The profile is a strict subset of what SimpleDiagrams reads. Anything these
models accept, the app opens. They are deliberately stricter than the app in
one way: the app silently drops unknown keys at some levels, and here every
unknown key is an error, because a dropped key is a mistake the author should
hear about.

Left out of the profile, and therefore rejected here even though the app can
read them: embedded images and embedded library artwork, shape data, page
background images, print layout, unresolved legacy content, a container's Automatic
layout or artwork, and a place a person chose for a part's words.

`FORMAT_VERSION` and `SCHEMA_VERSION` are separate counters and both are
pinned. See VERSIONS.md before changing either.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Callable
from itertools import pairwise
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    ValidationInfo,
    model_serializer,
    model_validator,
)

FORMAT_NAME = "com.simplediagrams.document"
FORMAT_VERSION = 19
SCHEMA_VERSION = 18

# The app's limits on complex shapes (ComplexShape.Limits and the drawing constants).
MIN_SHARE = 0.000_001
MAX_SHARE = 1_000_000.0
MAX_LANES = 50
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 50
MAX_TABLE_CELLS = 2_000
MAX_HOLDER_NESTING = 4
MAX_COMPLEX_SHAPE_TEXTS = 100_000
# How much a complex shape and a page of them hold (document format 19, elements 12.11). A
# document over any of these is refused whole. Characters are Unicode scalars.
MAX_HOLDER_MEMBERS = 1_000
MAX_SWIMLANES_MEMBERS = 2_000
MAX_LANE_TITLE = 1_000
MAX_LANE_TITLE_RUNS = 100
MAX_CELL_CHARACTERS = 2_000
MAX_CELL_RUNS = 200
MAX_TABLE_CHARACTERS = 100_000
MAX_TABLE_RUNS = 10_000
MAX_PAGE_COMPLEX_SHAPES = 2_000
MAX_PAGE_HOLDERS = 500
MAX_PAGE_PART_CHARACTERS = 1_000_000
MAX_PART_TEXT = 500
MAX_ENTITY_FIELDS = 60
MAX_FIELD_MARKS = 8
FIELD_MARKS = ("primary_key", "foreign_key", "unique", "indexed", "nullable")
# The numbers from here up are the ones a shape's parts own.
FIRST_PART_POINT = 8
MIN_TABLE_COLUMN_WIDTH = 16.0
MIN_TABLE_ROW_HEIGHT = 12.0
# A new swimlanes' title strip and title band, and the thinnest either (or a lane) may be.
SWIMLANES_STRIP = 28.0
MAX_SWIMLANES_STRIP = 10_000.0
LIFELINE_HEAD_HEIGHT = {"box": 40.0, "actor": 72.0}
SHORTEST_LIFELINE_LINE = 20.0
DESTROY_MARK_SIZE = 24.0
# How the app lays out the shapes it draws from their parts, which fixes where their
# connection points are: from each generator's starting values.
FLOW_BASE_SHAPES = ("chevron", "arrow_box", "block_arrow", "rectangle", "rounded_rectangle", "circle", "hexagon")
FLOW_PLAIN_GAP = 12.0
FLOW_POINTING_GAP = 6.0
FLOW_LARGEST_GAP_SHARE = 0.25
FLOW_OVERLAP_SHARE = 0.2
FLOW_POINT_DEPTH_SHARE = 0.35
FLOW_POINTER_BASE_SHARE = 0.3
FLOW_POINTER_DEPTH_SHARE = 0.5
FLOW_SMALLEST_POINTER_DEPTH = 4.0
FLOW_LARGEST_POINTER_SHARE = 1 / 3
PYRAMID_GAP = 4.0
PYRAMID_LARGEST_GAP_SHARE = 0.25
FUNNEL_SPOUT_SHARE = 0.2
CYCLE_GAP = 4.0
CYCLE_LARGEST_GAP_SHARE = 0.25
CYCLE_LARGEST_REACH_SHARE = 0.75
CYCLE_HEAD_OVERHANG_SHARE = 0.25
CYCLE_POINT_DEPTH_SHARE = 0.35
CYCLE_LARGEST_POINT_SHARE = 0.5
GAUGE_CAPTION_ROOM_SHARE = 0.4
GAUGE_HUB_SHARE = 0.05
GAUGE_CAPTION_MARGIN = 6.0
# Where the eight numbered points of a ring or cycle lie, in degrees clockwise from three o'clock.
RING_POINT_ANGLES = {0: 180.0, 1: 0.0, 2: -90.0, 3: 90.0, 4: -135.0, 5: 135.0, 6: -45.0, 7: 45.0}
# The id of a lifeline's one attach line, its dashed line; attachments name it.
LIFELINE_ATTACH_LINE = 0
# How far a lane, row or column may fall short of its smallest size, as a fraction of it.
SMALLEST_SIZE_ALLOWANCE = 1e-9

MANIFEST_FILENAME = "manifest.json"
DOCUMENT_FILENAME = "document.json"
ASSETS_DIRECTORY = "assets"

MAX_PAGES = 100
MAX_ELEMENTS = 100_000
MAX_CONNECTIONS = 200_000
MAX_GROUPS = 100_000
MAX_GROUP_MEMBERS = 200_000
MAX_GROUP_DEPTH = 64
MAX_PATH_NODES = 1_000_000
MAX_QUICK_STYLES = 32
MAX_GUIDES = 1_000
MAX_CONNECTION_POINTS = 128
MAX_TEXT_RUNS = 100_000
MAX_NAME_BYTES = 512
MAX_QUICK_STYLE_NAME_BYTES = 128
MAX_TEXT_BYTES = 1_000_000
MAX_FONT_FAMILY_BYTES = 256
MAX_IDENTIFIER_BYTES = 256
MAX_COORDINATE = 1_000_000_000.0
MAX_DIMENSION = 10_000_000.0
MAX_REVISION = 1_000_000_000
# The app stores whole numbers as 64-bit signed integers.
INT64_MAX = 9_223_372_036_854_775_807
INT64_MIN = -INT64_MAX - 1

# ---------------------------------------------------------------------------
# Scalar types
# ---------------------------------------------------------------------------

UUIDString = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
    ),
    Field(description="A UUID in 8-4-4-4-12 form. The app writes upper case; either case opens."),
]
Color = Annotated[
    str,
    StringConstraints(pattern=r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"),
    Field(description="#RRGGBB or #RRGGBBAA. Use #00000000 for transparent; names are invalid."),
]
OpaqueColor = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$"),
    Field(description="#RRGGBB only."),
]
Coordinate = Annotated[
    float,
    Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE, allow_inf_nan=False),
]
Dimension = Annotated[float, Field(gt=0, le=MAX_DIMENSION, allow_inf_nan=False)]
UnitInterval = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
LineWidth = Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)]

ElementKind = Literal["rectangle", "ellipse", "note", "text", "symbol", "path", "complex_shape"]
Share = Annotated[
    float,
    Field(
        ge=MIN_SHARE, le=MAX_SHARE, allow_inf_nan=False,
        description="A lane's, row's or column's part of the whole: any positive number.",
    ),
]
StrokePattern = Literal["solid", "dashed", "dotted"]
PointKind = Literal["straight", "curve"]
FontWeight = Literal["regular", "medium", "bold"]
TextAlignment = Literal["leading", "center", "trailing", "justified"]
TextPosition = Literal["above", "top", "middle", "bottom", "below"]
NoteStyle = Literal["stickyNote", "indexCard", "tapedNote", "tag", "notebookPage", "pinnedNote"]
Ending = Literal[
    "none",
    "stop",
    "arrow",
    "solidArrow",
    "circle",
    "solidCircle",
    "openDiamond",
    "diamond",
    "halfCircle",
    "crowFoot",
    "one",
    "oneAndOnlyOne",
    "zeroOrOne",
    "oneOrMany",
    "zeroOrMany",
    "filledArrow",
    "slash",
    "circlePlus",
    "cross",
    "halfArrow",
]
# The spelling "Horiztonal" is the app's stored value, not a typo to correct.
Texture = Literal[
    "Horizontal",
    "Vertical",
    "Grid",
    "SingleHatch",
    "TripleHatch",
    "PencilFill",
    "PencilThinHoriztonalHatch",
    "PencilThinSquareHatch",
    "PencilThinCrossHatch",
    "PencilThinDiagonalHatch",
    "WatercolorFill",
    "Grain",
    "PencilVerticalHatch",
    "PencilTriangleHatch",
    "PencilRandomHatch",
    "PencilHorizontal",
    "Chalk",
]
GridLineStyle = Literal["none", "solid", "dashed", "dotted"]
GridMarker = Literal["none", "dot", "cross"]
GridMarkerPlacement = Literal["every", "major"]

def _has_control_or_format(value: str) -> bool:
    """True when text holds a Unicode control (Cc) or format (Cf) character.

    JSON Schema cannot express this, so the generated schema does not carry it.
    """
    return any(unicodedata.category(character) in ("Cc", "Cf") for character in value)


def _check_text(value: str, *, field: str, max_bytes: int) -> None:
    if "\0" in value:
        raise ValueError(f"{field} contains a NUL character")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} is longer than {max_bytes} UTF-8 bytes")


class WireModel(BaseModel):
    """Base for every record in the file: closed, strict and immutable."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


class Manifest(WireModel):
    """The whole of `manifest.json`. All three keys are required."""

    format: Literal["com.simplediagrams.document"]
    format_version: Literal[19] = Field(
        description="Package format, which SimpleDiagrams 5.2 and later read. document.json's "
        "schema_version is this minus one."
    )
    contains_legacy_source: Literal[False]


# ---------------------------------------------------------------------------
# Geometry and text
# ---------------------------------------------------------------------------


class Point(WireModel):
    """A position in page coordinates: points, origin top left, y down."""

    x: Coordinate
    y: Coordinate


class Rect(WireModel):
    """An unrotated rectangle in page coordinates. Zero sizes are invalid."""

    x: Coordinate
    y: Coordinate
    width: Dimension
    height: Dimension


class CharacterStyle(WireModel):
    """Font settings for a run of text."""

    font_family: str | None = Field(
        default=None, description="Omit to use the app's standard font."
    )
    font_size: Annotated[float, Field(ge=1, le=720, allow_inf_nan=False)]
    weight: FontWeight
    is_italic: bool
    is_underlined: bool
    color_hex: Color
    highlight_hex: Color | None = Field(default=None, description="A highlight behind these characters.")

    @model_validator(mode="after")
    def _check_font_family(self) -> CharacterStyle:
        family = self.font_family
        if family is not None:
            _check_text(family, field="font_family", max_bytes=MAX_FONT_FAMILY_BYTES)
            if not family.strip() or _has_control_or_format(family):
                raise ValueError("font_family is blank or contains control characters")
        return self


class TextRange(WireModel):
    """A span of text measured in UTF-16 code units, not characters."""

    location: Annotated[int, Field(ge=0, le=INT64_MAX)]
    length: Annotated[int, Field(gt=0, le=INT64_MAX)]


class CharacterRun(WireModel):
    """A style override for one span of the text."""

    range: TextRange
    style: CharacterStyle


class ParagraphRun(WireModel):
    """An alignment override for one span of the text."""

    range: TextRange
    alignment: TextAlignment


class TextContent(WireModel):
    """The label of an element or connector. Every key is required.

    Runs are only allowed over plain ASCII text. The app requires each run to
    start and end between whole user-perceived characters, which for accented
    letters, emoji and other combined characters cannot be checked here.
    """

    string: str
    base_style: CharacterStyle
    character_runs: list[CharacterRun]
    base_alignment: TextAlignment
    paragraph_runs: list[ParagraphRun]

    @model_validator(mode="after")
    def _check_runs(self) -> TextContent:
        _check_text(self.string, field="text", max_bytes=MAX_TEXT_BYTES)
        if len(self.character_runs) + len(self.paragraph_runs) > MAX_TEXT_RUNS:
            raise ValueError("too many text runs")
        if not (self.character_runs or self.paragraph_runs):
            return self
        if not self.string.isascii() or "\r" in self.string:
            raise ValueError(
                "character_runs and paragraph_runs are only allowed when the text is plain "
                "ASCII without carriage returns; leave both arrays empty otherwise"
            )
        total = len(self.string)
        for name, ranges in (
            ("character_runs", [run.range for run in self.character_runs]),
            ("paragraph_runs", [run.range for run in self.paragraph_runs]),
        ):
            previous_end = 0
            for span in ranges:
                end = span.location + span.length
                if span.location < previous_end:
                    raise ValueError(f"{name} must be ascending and must not overlap")
                if end > total:
                    raise ValueError(f"{name} range {span.location}+{span.length} runs past the text")
                previous_end = end
        return self


class TextLayout(WireModel):
    """Where a label sits, relative to its own shape.

    `frame` is in fractions of the shape: x and y are the region's top left
    corner; width and height may run past the shape. The region may start outside
    it, as a name SimpleDiagrams centres below a narrow shape does, while some of it
    still touches the shape. With position `above` or `below` the label sits just
    outside the shape, wrapping at the region's width, and the frame's y is ignored.
    """

    frame: TextLayoutFrame
    position: TextPosition
    rotation_degrees: Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False)] | None = None


class TextLayoutFrame(WireModel):
    """A label region in fractions of the owning shape's width and height.

    Its corner may lie as far before the shape as the region is long, so the region
    still touches the shape.
    """

    x: Annotated[float, Field(ge=-8, le=1, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=-8, le=1, allow_inf_nan=False)]
    width: Annotated[float, Field(ge=0.001, le=8, allow_inf_nan=False)]
    height: Annotated[float, Field(ge=0.001, le=8, allow_inf_nan=False)]

    @model_validator(mode="after")
    def _check_touches(self) -> TextLayoutFrame:
        if self.x < -self.width or self.y < -self.height:
            raise ValueError("a label region must still touch its shape")
        return self



# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


class ElementStyle(WireModel):
    """Fill and outline of an element. The three paint keys are required."""

    fill_hex: Color
    stroke_hex: Color
    line_width: LineWidth
    fill_texture: Texture | None = None
    stroke_texture: Texture | None = None
    stroke_pattern_override: StrokePattern | None = None


class SymbolReference(WireModel):
    """Names one shape in a library built into SimpleDiagrams, by the app's own library
    and item names. A reference the app cannot resolve still opens, but draws a dashed
    placeholder.
    """

    library_id: Annotated[str, Field(min_length=1)]
    item_id: Annotated[str, Field(min_length=1)]
    asset_version: Annotated[int, Field(gt=0, le=INT64_MAX)]

    @model_validator(mode="after")
    def _check_lengths(self) -> SymbolReference:
        _check_text(self.library_id, field="library_id", max_bytes=MAX_IDENTIFIER_BYTES)
        _check_text(self.item_id, field="item_id", max_bytes=MAX_IDENTIFIER_BYTES)
        return self


class ConnectionPointAnchor(WireModel):
    """A place on an element where a connector can attach.

    `x` and `y` are fractions of the element's frame. `id` is what a
    connector's attachment names.
    """

    id: Annotated[int, Field(ge=0, le=INT64_MAX)]
    x: UnitInterval
    y: UnitInterval


def standard_connection_points() -> list[ConnectionPointAnchor]:
    """The eight anchors the app gives every shape.

    0 left, 1 right, 2 top, 3 bottom (all mid-side), then the corners:
    4 top left, 5 bottom left, 6 top right, 7 bottom right.
    """
    return [
        ConnectionPointAnchor(id=0, x=0, y=0.5),
        ConnectionPointAnchor(id=1, x=1, y=0.5),
        ConnectionPointAnchor(id=2, x=0.5, y=0),
        ConnectionPointAnchor(id=3, x=0.5, y=1),
        ConnectionPointAnchor(id=4, x=0, y=0),
        ConnectionPointAnchor(id=5, x=0, y=1),
        ConnectionPointAnchor(id=6, x=1, y=0),
        ConnectionPointAnchor(id=7, x=1, y=1),
    ]


class PathNode(WireModel):
    """One node of a freeform path.

    Coordinates are relative to the top left corner of the element's frame,
    not to the page.
    """

    point: Point
    control_point: Point | None = None
    second_control_point: Point | None = None
    kind: PointKind

    @model_validator(mode="after")
    def _check_controls(self) -> PathNode:
        if self.second_control_point is not None and self.control_point is None:
            raise ValueError("second_control_point needs control_point")
        return self


class Path(WireModel):
    """The geometry of a `path` element."""

    nodes: Annotated[list[PathNode], Field(min_length=2)]
    is_closed: bool
    is_smoothed: bool
    stroke_pattern: StrokePattern
    start_ending: Ending
    end_ending: Ending

    @model_validator(mode="after")
    def _check_closed(self) -> Path:
        if self.is_closed and len(self.nodes) < 3:
            raise ValueError("a closed path needs at least 3 nodes")
        return self


class ElementCore(WireModel):
    """The innermost element record: identity, kind, geometry, text and paint."""

    id: UUIDString
    kind: ElementKind
    frame: Rect
    rotation_degrees: Coordinate
    z_index: Annotated[int, Field(ge=INT64_MIN, le=INT64_MAX)]
    text_content: TextContent
    style: ElementStyle
    connection_points: Annotated[list[ConnectionPointAnchor], Field(max_length=MAX_CONNECTION_POINTS)]
    symbol_reference: SymbolReference | None = None
    path: Path | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> ElementCore:
        if (self.kind == "symbol") != (self.symbol_reference is not None):
            raise ValueError("symbol_reference is required on kind 'symbol' and forbidden elsewhere")
        if (self.kind == "path") != (self.path is not None):
            raise ValueError("path is required on kind 'path' and forbidden elsewhere")
        ids = [anchor.id for anchor in self.connection_points]
        if len(ids) != len(set(ids)):
            raise ValueError("connection_points ids must be unique within the element")
        return self


class ElementLock(WireModel):
    """Wraps the element core with its lock flag."""

    content: ElementCore
    is_locked: bool


class ElementPresentation(WireModel):
    """Wraps the locked element with flips and label placement."""

    content: ElementLock
    flip_horizontal: bool
    flip_vertical: bool
    text_layout: TextLayout | None = None
    note_style: NoteStyle | None = None
    preserves_aspect_ratio: bool | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> ElementPresentation:
        kind = self.content.content.kind
        if self.note_style is not None and kind != "note":
            raise ValueError("note_style is only allowed on kind 'note'")
        if self.text_layout is not None and kind == "path":
            raise ValueError("text_layout is not allowed on kind 'path'")
        return self


class Attachment(WireModel):
    """Binds a connector end, or a callout's tail, to a place on an element of the same page.

    The place is one of the element's numbered anchors (`connection_point_id`) or a point
    `distance` points along one of its attach lines from the line's start
    (`attach_line_id`): a UML lifeline's dashed line, whose id is 0, is the only one.
    A record holds exactly one of the two forms. A callout's tail uses an anchor only.
    """

    element_id: UUIDString
    connection_point_id: Annotated[int, Field(ge=0, le=INT64_MAX)] | None = None
    attach_line_id: Annotated[int, Field(ge=0, le=INT64_MAX)] | None = None
    distance: Annotated[float, Field(ge=0, le=MAX_DIMENSION, allow_inf_nan=False)] | None = Field(
        default=None, description="Points along the attach line from its start; with attach_line_id only."
    )

    @model_validator(mode="after")
    def _check_form(self) -> Attachment:
        on_point = self.connection_point_id is not None
        on_line = self.attach_line_id is not None and self.distance is not None
        if on_point == on_line or (on_point and (self.attach_line_id, self.distance) != (None, None)):
            raise ValueError(
                "an attachment names connection_point_id, or attach_line_id with distance, "
                "and nothing else"
            )
        return self

    @property
    def on_line(self) -> bool:
        """Whether the end is on an attach line rather than a numbered point."""
        return self.attach_line_id is not None


# ---------------------------------------------------------------------------
# Complex shapes: one structure, read against the complex-shape catalogue
# ---------------------------------------------------------------------------


Word = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", max_length=32),
    Field(description="A machine word: lower-case letters and digits in groups joined by single underscores."),
]
SettingValue = bool | float | Word | Point | Attachment


def _refuse_null(data: Any, info: ValidationInfo) -> Any:
    """The app refuses `null` anywhere in a complex shape's record but its texts, where
    elsewhere it reads one as absent. Only a file can hold one: a builder's None is left out."""
    if info.mode == "json" and isinstance(data, dict) and None in data.values():
        raise ValueError("a complex shape's record holds no null; leave the key out")
    return data


class HolderMember(WireModel):
    """One thing a container or a lane holds: a shape, or a whole group that is in no
    other group. Never a connector, never swimlanes, and never a piece of a group."""

    kind: Literal["element", "group"]
    id: UUIDString


class PartStyle(WireModel):
    """A part's own paint. A missing channel follows the element's style, and a texture
    comes only with its colour."""

    fill_hex: Color | None = None
    fill_texture: Texture | None = None
    stroke_hex: Color | None = None
    stroke_texture: Texture | None = None
    line_width: LineWidth | None = None

    _no_null = model_validator(mode="before")(_refuse_null)

    @model_validator(mode="after")
    def _check_channels(self) -> PartStyle:
        if not any(value is not None for value in self.__dict__.values()):
            raise ValueError("a part's style holds at least one channel")
        if (self.fill_texture and not self.fill_hex) or (self.stroke_texture and not self.stroke_hex):
            raise ValueError("a part's texture comes only with its colour")
        return self


class Part(WireModel):
    """One piece of a complex shape a person can touch: a lane, a row, a section, a step.

    Every part has a `role`; which of the other keys it holds is the catalogue entry's to
    say. A place a person chose for a part's words (`text_layout`) is not written by this
    profile.
    """

    role: Word
    id: UUIDString | None = None
    text: TextContent | None = None
    style: PartStyle | None = None
    size: Share | None = None
    members: Annotated[list[HolderMember], Field(max_length=MAX_HOLDER_MEMBERS)] | None = None
    cells: Annotated[list[TextContent], Field(max_length=MAX_TABLE_COLUMNS)] | None = None
    marks: Annotated[list[Word], Field(max_length=MAX_FIELD_MARKS)] | None = None
    point_ids: (
        Annotated[list[Annotated[int, Field(ge=FIRST_PART_POINT, le=INT64_MAX)]], Field(max_length=2)] | None
    ) = None

    _no_null = model_validator(mode="before")(_refuse_null)

    @property
    def texts(self) -> list[TextContent]:
        """The words this part holds."""
        return ([self.text] if self.text is not None else []) + list(self.cells or [])


def _word_in(*words: str) -> Callable[[SettingValue], bool]:
    return lambda value: value in words and isinstance(value, str)


def _is_boolean(value: SettingValue) -> bool:
    return isinstance(value, bool)


def _is_number(value: SettingValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number_from(low: float, high: float) -> Callable[[SettingValue], bool]:
    return lambda value: _is_number(value) and low <= value <= high


def _is_band_width(value: SettingValue) -> bool:
    """A multiple of 10 from 10 to 10,000."""
    return _is_number(value) and 10 <= value <= 10_000 and value % 10 == 0


def _is_point(value: SettingValue) -> bool:
    return isinstance(value, Point)


def _is_attachment(value: SettingValue) -> bool:
    return isinstance(value, Attachment) and not value.on_line


class _Role(NamedTuple):
    """What a catalogue entry declares for one role of part."""

    name: str
    fewest: int
    most: int
    required: frozenset[str]
    optional: frozenset[str] = frozenset()
    points: int = 0


class _Entry(NamedTuple):
    """What the complex-shape catalogue declares for one type at version 1."""

    settings: dict[str, Callable[[SettingValue], bool]]
    roles: tuple[_Role, ...] = ()
    optional_settings: frozenset[str] = frozenset()
    holds_members: bool = False
    has_own_text: bool = True
    # The numbers from 0 to 7 of a shape that places its own points; None for a shape whose
    # element lists its points as any element does.
    own_points: frozenset[int] | None = None


_LABELLED = frozenset({"id", "text"})
_PAINTABLE = frozenset({"style"})
_EIGHT = frozenset(range(8))
_ROW = frozenset({"id", "size", "cells"})

CATALOGUE: dict[str, _Entry] = {
    "container": _Entry(
        settings={"layout": _word_in("free", "proportional"), "title_style": _word_in("band", "corner_tag")},
        holds_members=True,
    ),
    "swimlanes": _Entry(
        settings={
            "direction": _word_in("horizontal", "vertical"),
            "title_strip_size": _number_from(SWIMLANES_STRIP, MAX_SWIMLANES_STRIP),
            "title_band_size": _number_from(SWIMLANES_STRIP, MAX_SWIMLANES_STRIP),
        },
        roles=(_Role("lane", 1, MAX_LANES, frozenset({"id", "text", "size", "members"})),),
    ),
    "table": _Entry(
        settings={"header_row": _is_boolean},
        roles=(
            _Role("column", 1, MAX_TABLE_COLUMNS, frozenset({"size"})),
            _Role("row", 1, MAX_TABLE_ROWS, frozenset({"size", "cells"})),
        ),
        has_own_text=False,
    ),
    "entity_table": _Entry(
        settings={},
        roles=(
            _Role("column", 2, 2, frozenset({"size"})),
            _Role("header", 1, 1, _ROW),
            _Role("field", 1, MAX_ENTITY_FIELDS, _ROW | {"marks", "point_ids"}, points=2),
        ),
        has_own_text=False,
        own_points=_EIGHT,
    ),
    "callout": _Entry(
        settings={"tail_tip": _is_point, "tail_attachment": _is_attachment},
        optional_settings=frozenset({"tail_tip", "tail_attachment"}),
    ),
    "lifeline": _Entry(settings={"head_style": _word_in("box", "actor"), "ends_in_destroy_mark": _is_boolean}),
    "ring": _Entry(
        settings={"ring_width": lambda value: value == "full" or _is_band_width(value)},
        roles=(_Role("section", 1, 12, _LABELLED | {"point_ids"}, _PAINTABLE, points=1),),
        has_own_text=False,
        own_points=_EIGHT,
    ),
    "flow": _Entry(
        settings={
            "base_shape": _word_in(*FLOW_BASE_SHAPES),
            "direction": _word_in("across", "down"),
            "spacing": _word_in("gap", "touch", "overlap"),
            "pointer": _is_boolean,
        },
        roles=(_Role("step", 2, 12, _LABELLED | {"point_ids"}, _PAINTABLE, points=2),),
        has_own_text=False,
        own_points=_EIGHT,
    ),
    "pyramid": _Entry(
        settings={"form": _word_in("pyramid", "funnel")},
        roles=(_Role("layer", 2, 8, _LABELLED | {"point_ids"}, _PAINTABLE, points=2),),
        has_own_text=False,
        own_points=frozenset({2, 3}),
    ),
    "cycle": _Entry(
        settings={
            "ring_width": _is_band_width,
            "direction": _word_in("clockwise", "anticlockwise"),
            "arrow_style": _word_in("arrow", "chevron"),
        },
        roles=(_Role("step", 3, 8, _LABELLED | {"point_ids"}, _PAINTABLE, points=1),),
        has_own_text=False,
        own_points=_EIGHT,
    ),
    "gauge": _Entry(
        settings={
            "minimum": _number_from(-1_000_000, 1_000_000),
            "maximum": _number_from(-1_000_000, 1_000_000),
            "value": _number_from(-1_000_000, 1_000_000),
            "auto_rotate_labels": _is_boolean,
        },
        roles=(
            _Role("band", 1, 5, _LABELLED, _PAINTABLE),
            _Role("needle", 1, 1, frozenset({"id"}), _PAINTABLE),
        ),
        own_points=_EIGHT,
    ),
}
# The kinds whose words sit in parts of their own, each at most MAX_PART_TEXT characters.
SHORT_TEXT_ROLES = frozenset({"section", "step", "layer", "band"})
ComplexShapeType = Literal[
    "container", "swimlanes", "table", "entity_table", "callout", "lifeline", "ring", "flow", "pyramid", "cycle", "gauge"
]


class ComplexShape(WireModel):
    """The `complex_shape` record of an element of kind `complex_shape`: a type and version,
    its settings, its parts and, for a container, its members.

    The structure is the same for every type, and nothing drawn is saved: SimpleDiagrams
    draws the shape from these and the element's frame each time. Every setting its type
    declares is written, even at its default, and a part's role says which keys it holds;
    `_check_entry` holds a record to its type's entry, as the app does when it reads one.
    `hand_drawn` is written only as false.
    """

    type: ComplexShapeType
    version: Literal[1]
    settings: Annotated[dict[Word, SettingValue], Field(max_length=16)]
    parts: Annotated[list[Part], Field(max_length=256)]
    members: Annotated[list[HolderMember], Field(max_length=MAX_HOLDER_MEMBERS)] | None = None
    hand_drawn: Literal[False] | None = None

    _no_null = model_validator(mode="before")(_refuse_null)

    @model_validator(mode="after")
    def _check_entry(self) -> ComplexShape:
        entry = CATALOGUE[self.type]
        missing = set(entry.settings) - entry.optional_settings - set(self.settings)
        stray = set(self.settings) - set(entry.settings)
        if missing or stray:
            raise ValueError(
                f"a {self.type} holds the settings {', '.join(sorted(entry.settings)) or 'none'}; "
                f"missing {sorted(missing)}, not its own {sorted(stray)}"
            )
        for name, value in self.settings.items():
            if not entry.settings[name](value):
                raise ValueError(f"a {self.type}'s {name} cannot be {value!r}")
        if entry.holds_members != (self.members is not None):
            raise ValueError(f"a {self.type} {'needs' if entry.holds_members else 'does not take'} members")
        self._check_parts(entry)
        # Across all of its lanes too: one shape in two lanes of one swimlanes is refused.
        listed = [(member.kind, member.id.upper()) for member in self.all_members]
        if len(listed) != len(set(listed)):
            raise ValueError(f"a {self.type} lists a member twice")
        getattr(self, f"_check_{self.type}", lambda: None)()
        return self

    def _check_parts(self, entry: _Entry) -> None:
        """The parts come in the entry's roles and order, each with exactly its role's keys."""
        roles = {role.name: role for role in entry.roles}
        order = [part.role for part in self.parts]
        expected = [role.name for role in entry.roles for _ in range(order.count(role.name))]
        if order != expected or not set(order) <= set(roles):
            raise ValueError(f"a {self.type}'s parts come in the order {', '.join(roles) or 'of none at all'}")
        for role in entry.roles:
            if not role.fewest <= order.count(role.name) <= role.most:
                raise ValueError(f"a {self.type} has {role.fewest} to {role.most} parts of role {role.name}")
        for part in self.parts:
            role = roles[part.role]
            present = {key for key in Part.model_fields if key != "role" and getattr(part, key) is not None}
            if present - role.required - role.optional or role.required - present:
                raise ValueError(f"a {self.type}'s {part.role} holds {', '.join(sorted(role.required))}")
            if len(part.point_ids or []) != role.points:
                raise ValueError(f"a {self.type}'s {part.role} owns {role.points} connection points")
            if part.role in SHORT_TEXT_ROLES and part.text is not None and len(part.text.string) > MAX_PART_TEXT:
                raise ValueError(f"a {part.role}'s words hold at most {MAX_PART_TEXT} characters")
        identities = [part.id.upper() for part in self.parts if part.id is not None]
        if len(identities) != len(set(identities)):
            raise ValueError(f"two parts of one {self.type} share an id")
        points = [point for part in self.parts for point in part.point_ids or []]
        if len(points) != len(set(points)):
            raise ValueError(f"a {self.type} lists a connection point twice")

    def _check_container(self) -> None:
        if len(self.members or []) > MAX_HOLDER_MEMBERS:
            raise ValueError(f"a container holds at most {MAX_HOLDER_MEMBERS} shapes")

    def _check_swimlanes(self) -> None:
        for lane in self.lanes:
            assert lane.text is not None
            if len(lane.text.string) > MAX_LANE_TITLE:
                raise ValueError(f"a lane title holds at most {MAX_LANE_TITLE} characters")
            if len(lane.text.character_runs) + len(lane.text.paragraph_runs) > MAX_LANE_TITLE_RUNS:
                raise ValueError(f"a lane title has at most {MAX_LANE_TITLE_RUNS} runs")
        if sum(len(lane.members or []) for lane in self.lanes) > MAX_SWIMLANES_MEMBERS:
            raise ValueError(f"the lanes of one swimlanes hold at most {MAX_SWIMLANES_MEMBERS} shapes")

    def _check_table(self) -> None:
        columns = self.column_sizes
        rows = self.cell_rows
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("a table has one cell per column in every row")
        if len(rows) * len(columns) > MAX_TABLE_CELLS:
            raise ValueError(f"a table has at most {MAX_TABLE_CELLS} cells")
        cells = [cell for row in rows for cell in row]
        for cell in cells:
            if len(cell.string) > MAX_CELL_CHARACTERS:
                raise ValueError(f"a table cell holds at most {MAX_CELL_CHARACTERS} characters")
            if len(cell.character_runs) + len(cell.paragraph_runs) > MAX_CELL_RUNS:
                raise ValueError(f"a table cell has at most {MAX_CELL_RUNS} runs")
        if sum(len(cell.string) for cell in cells) > MAX_TABLE_CHARACTERS:
            raise ValueError(f"a table holds at most {MAX_TABLE_CHARACTERS} characters")
        if sum(len(cell.character_runs) + len(cell.paragraph_runs) for cell in cells) > MAX_TABLE_RUNS:
            raise ValueError(f"a table has at most {MAX_TABLE_RUNS} runs")

    def _check_entity_table(self) -> None:
        self._check_table()
        for part in self.parts:
            if part.role == "header" and (part.cells or [])[1:] and (part.cells or [])[1].string:
                raise ValueError("an entity table's header holds its name and then an empty text")
            for mark in part.marks or []:
                if mark not in FIELD_MARKS:
                    raise ValueError(f"an entity table's field cannot be marked {mark}")
            if len(set(part.marks or [])) != len(part.marks or []):
                raise ValueError("an entity table's field repeats a mark")

    def _check_callout(self) -> None:
        if "tail_attachment" in self.settings and "tail_tip" not in self.settings:
            raise ValueError("a callout's locked tail also needs its tail_tip, where it is drawn")

    def _check_flow(self) -> None:
        takes_more = self.settings["base_shape"] in ("rectangle", "rounded_rectangle", "circle")
        if not takes_more and (self.settings["spacing"] == "overlap" or self.settings["pointer"] is True):
            raise ValueError(f"a {self.settings['base_shape']} flow has no overlap and no pointer")

    def _check_gauge(self) -> None:
        low, high, value = (float(self.settings[name]) for name in ("minimum", "maximum", "value"))  # type: ignore[arg-type]
        if not low < high or not low <= value <= high:
            raise ValueError("a gauge's minimum is below its maximum, and its value lies between them")

    def _of_role(self, role: str) -> list[Part]:
        return [part for part in self.parts if part.role == role]

    @property
    def holds_shapes(self) -> bool:
        """Whether it is a container or swimlanes, which hold other shapes."""
        return self.type in ("container", "swimlanes")

    @property
    def all_members(self) -> list[HolderMember]:
        """What a container or every lane of swimlanes holds, in order."""
        return list(self.members or []) + [member for part in self.parts for member in part.members or []]

    @property
    def texts(self) -> list[TextContent]:
        """The lane titles, cells and part labels it holds besides its own text."""
        return [text for part in self.parts for text in part.texts]

    @property
    def lanes(self) -> list[Part]:
        return self._of_role("lane")

    @property
    def column_sizes(self) -> list[float]:
        return [part.size or 0.0 for part in self._of_role("column")]

    @property
    def row_parts(self) -> list[Part]:
        """A table's rows, or an entity table's header and fields."""
        return [part for part in self.parts if part.role in ("row", "header", "field")]

    @property
    def row_sizes(self) -> list[float]:
        return [part.size or 0.0 for part in self.row_parts]

    @property
    def cell_rows(self) -> list[list[TextContent]]:
        return [list(part.cells or []) for part in self.row_parts]

    @property
    def title_style(self) -> str:
        return str(self.settings.get("title_style", "band"))

    @property
    def tail_tip(self) -> Point | None:
        tip = self.settings.get("tail_tip")
        return tip if isinstance(tip, Point) else None

    @property
    def tail_attachment(self) -> Attachment | None:
        attachment = self.settings.get("tail_attachment")
        return attachment if isinstance(attachment, Attachment) else None

    @property
    def own_point_ids(self) -> set[int] | None:
        """The numbers of the connection points a shape that places its own has: its entry's
        and its parts'. None for a shape whose element lists its points."""
        own = CATALOGUE[self.type].own_points
        return None if own is None else set(own) | {point for part in self.parts for point in part.point_ids or []}


def _lengths(shares: list[float], length: float) -> list[float]:
    """Shares as lengths that add up to `length`, as the app divides them."""
    total = sum(shares)
    return [share / total * length for share in shares]


def lifeline_line(shape: ComplexShape, frame: Rect) -> tuple[float, float]:
    """Where a lifeline's dashed line starts and ends, in points down from its frame's top:
    from the bottom of its head to the frame's bottom, or to half a destroy mark above it."""
    head = LIFELINE_HEAD_HEIGHT[str(shape.settings["head_style"])]
    inset = DESTROY_MARK_SIZE / 2 if shape.settings["ends_in_destroy_mark"] else 0.0
    start = min(head, frame.height)
    return start, max(start, frame.height - inset)


def lifeline_smallest_height(shape: ComplexShape) -> float:
    """The shortest frame a lifeline may have: its head, the shortest line, and half a
    destroy mark when it ends in one."""
    head = LIFELINE_HEAD_HEIGHT[str(shape.settings["head_style"])]
    return head + SHORTEST_LIFELINE_LINE + (DESTROY_MARK_SIZE / 2 if shape.settings["ends_in_destroy_mark"] else 0.0)


def swimlane_frames(shape: ComplexShape, frame: Rect) -> list[Rect]:
    """Each lane's frame on the page, in lane order, for an unturned swimlanes: below the
    title band, sharing the rest by their shares, as the app draws them."""
    band = min(float(shape.settings["title_band_size"]), frame.height)  # type: ignore[arg-type]
    lanes = shape.lanes
    shares = [lane.size or 0.0 for lane in lanes]
    frames = []
    if shape.settings["direction"] == "horizontal":
        y = frame.y + band
        for size in _lengths(shares, max(0.0, frame.height - band)):
            frames.append(Rect(x=frame.x, y=y, width=frame.width, height=max(size, 1e-9)))
            y += size
    else:
        x = frame.x
        for size in _lengths(shares, frame.width):
            frames.append(Rect(x=x, y=frame.y + band, width=max(size, 1e-9), height=max(frame.height - band, 1e-9)))
            x += size
    return frames


class FlowStep(NamedTuple):
    """Where one step of a flow lies along it and across it, in points of the flow drawn
    across: a flow running down is this reflected in the diagonal through the top left."""

    x: float
    y: float
    length: float
    thickness: float
    pointer_depth: float
    back: float
    front: float


def flow_steps(shape: ComplexShape, width: float, height: float) -> list[FlowStep]:
    """Each step of a flow, worked out as the app lays them out."""
    down = shape.settings["direction"] == "down"
    length, thickness = (height, width) if down else (width, height)
    base = str(shape.settings["base_shape"])
    spacing = shape.settings["spacing"]
    count = len(shape.parts)
    points_the_way = base in ("chevron", "arrow_box", "block_arrow")

    def point_depth(step_length: float) -> float:
        return min(thickness * FLOW_POINT_DEPTH_SHARE, step_length / 2)

    def advance(step_length: float) -> float:
        nesting = point_depth(step_length) if base == "chevron" else 0.0
        if spacing == "gap":
            half = thickness / 2
            gap = FLOW_POINTING_GAP if points_the_way else FLOW_PLAIN_GAP
            if base == "chevron" and half > 0:
                gap = FLOW_POINTING_GAP * math.hypot(point_depth(step_length), half) / half
            return step_length - nesting + min(gap, step_length * FLOW_LARGEST_GAP_SHARE)
        if spacing == "touch":
            return step_length - nesting
        return step_length - nesting - step_length * FLOW_OVERLAP_SHARE

    low, high = 0.0, max(0.0, length)
    for _ in range(64):
        middle = (low + high) / 2
        if middle + (count - 1) * advance(middle) <= length:
            low = middle
        else:
            high = middle
    share = low
    if base == "circle":
        side = min(share, thickness)
        top = (thickness - side) / 2
        if spacing == "gap":
            pitch = (length - side) / (count - 1)
            start = 0.0
        else:
            pitch = side if spacing == "touch" else side * (1 - FLOW_OVERLAP_SHARE)
            start = (length - side - (count - 1) * pitch) / 2
        boxes = [(start + index * pitch, top, side, side) for index in range(count)]
        lead = start
    else:
        pitch = advance(share)
        boxes = [(index * pitch, 0.0, share, thickness) for index in range(count)]
        lead = 0.0
    x, y, last_length, last_thickness = boxes[-1]
    boxes[-1] = (length - lead - last_length, y, last_length, last_thickness)
    steps = []
    for index, (x, y, step_length, step_thickness) in enumerate(boxes):
        depth = 0.0
        if shape.settings["pointer"] is True and index < count - 1:
            depth = min(
                max(step_thickness * FLOW_POINTER_BASE_SHARE * FLOW_POINTER_DEPTH_SHARE, FLOW_SMALLEST_POINTER_DEPTH),
                step_length * FLOW_LARGEST_POINTER_SHARE,
            )
        back = x + (point_depth(step_length) if base == "chevron" else 0.0)
        steps.append(FlowStep(x, y, step_length, step_thickness, depth, back, x + step_length + depth))
    return steps


class PyramidLayer(NamedTuple):
    """One layer of a pyramid or funnel, in points from the frame's top and middle line."""

    top: float
    bottom: float
    top_half_width: float
    bottom_half_width: float


def pyramid_layers(shape: ComplexShape, width: float, height: float) -> list[PyramidLayer]:
    """Each layer, top to bottom, as the app cuts the figure."""
    count = len(shape.parts)
    layer_height = (height - (count - 1) * PYRAMID_GAP) / count
    gap = PYRAMID_GAP
    if gap > layer_height * PYRAMID_LARGEST_GAP_SHARE:
        layer_height = height / (count + (count - 1) * PYRAMID_LARGEST_GAP_SHARE)
        gap = layer_height * PYRAMID_LARGEST_GAP_SHARE
    half = width / 2

    def reach(y: float) -> float:
        if shape.settings["form"] == "pyramid":
            return half * y / height
        return half * (1 - (1 - FUNNEL_SPOUT_SHARE) * y / height)

    layers = []
    for index in range(count):
        top = index * (layer_height + gap)
        bottom = height if index == count - 1 else top + layer_height
        layers.append(PyramidLayer(top, bottom, reach(top), reach(bottom)))
    return layers


class CycleBand(NamedTuple):
    """A cycle's circle and band, in points; `share`, `gap` and `depth` are degrees."""

    radius: float
    outer: float
    inner: float
    share: float
    gap: float
    depth: float


def cycle_band(shape: ComplexShape, width: float, height: float) -> CycleBand:
    """A cycle's band and how its steps share it, as the app works them out."""
    radius = min(width, height) / 2
    arrow = shape.settings["arrow_style"] == "arrow"
    overhang_share = CYCLE_HEAD_OVERHANG_SHARE if arrow else 0.0
    band = min(
        float(shape.settings["ring_width"]),  # type: ignore[arg-type]
        CYCLE_LARGEST_REACH_SHARE * radius / (1 + 2 * overhang_share),
    )
    overhang = band * overhang_share
    outer = radius - overhang
    inner = outer - band
    share = 360 / len(shape.parts)
    middle = (outer + inner) / 2
    share_length = middle * share * math.pi / 180
    slope = 1.0 if arrow else math.hypot(0.5, CYCLE_POINT_DEPTH_SHARE) / 0.5
    gap_length = min(CYCLE_GAP * slope, share_length * CYCLE_LARGEST_GAP_SHARE)
    depth_length = min(
        (band + 2 * overhang) * CYCLE_POINT_DEPTH_SHARE, (share_length - gap_length) * CYCLE_LARGEST_POINT_SHARE
    )
    return CycleBand(radius, outer, inner, share, gap_length / middle * 180 / math.pi, depth_length / middle * 180 / math.pi)


def gauge_circle(width: float, height: float) -> tuple[float, float, float, float]:
    """A gauge's half circle: its centre's x and y, its radius, and the caption room's bottom."""
    radius = min(width / 2, height / (1 + GAUGE_CAPTION_ROOM_SHARE))
    top = (height - radius * (1 + GAUGE_CAPTION_ROOM_SHARE)) / 2
    return width / 2, top + radius, radius, top + radius + radius * GAUGE_CAPTION_ROOM_SHARE


def gauge_caption_room(width: float, height: float) -> tuple[float, float]:
    """The box a gauge's caption sits in: from its hub to the bottom of the caption's room, as
    wide as its half circle less a margin each side."""
    _, centre_y, radius, bottom = gauge_circle(width, height)
    return 2 * radius - 2 * GAUGE_CAPTION_MARGIN, bottom - centre_y - radius * GAUGE_HUB_SHARE


def _on_circle(cx: float, cy: float, distance: float, degrees: float) -> tuple[float, float]:
    """The point at `distance` from a centre at `degrees`, clockwise on screen from three o'clock."""
    turn = math.radians(degrees)
    return cx + distance * math.cos(turn), cy + distance * math.sin(turn)


def shape_points(shape: ComplexShape, width: float, height: float) -> dict[int, tuple[float, float]]:
    """Where each connection point of a shape that places its own is drawn, as fractions of
    its frame. The file lists none of these; the app works them out as it reads the document,
    and draws a connector's end there, so a route is stored ending at the same place."""
    cx, cy = width / 2, height / 2
    points: dict[int, tuple[float, float]] = {}
    if shape.type == "entity_table":
        points = {anchor.id: (anchor.x * width, anchor.y * height) for anchor in standard_connection_points()}
        top = 0.0
        for part, size in zip(shape.row_parts, _lengths(shape.row_sizes, height), strict=True):
            if part.point_ids:
                points[part.point_ids[0]] = (0.0, top + size / 2)
                points[part.point_ids[1]] = (width, top + size / 2)
            top += size
    elif shape.type == "ring":
        radius = min(width, height) / 2
        points = {point: _on_circle(cx, cy, radius, degrees) for point, degrees in RING_POINT_ANGLES.items()}
        share = 360 / len(shape.parts)
        for index, part in enumerate(shape.parts):
            assert part.point_ids is not None
            points[part.point_ids[0]] = _on_circle(cx, cy, radius, -90 + index * share + share / 2)
    elif shape.type == "flow":
        steps = flow_steps(shape, width, height)
        down = shape.settings["direction"] == "down"
        place = (lambda x, y: (y, x)) if down else (lambda x, y: (x, y))
        for step, part in zip(steps, shape.parts, strict=True):
            assert part.point_ids is not None
            middle = step.y + step.thickness / 2
            points[part.point_ids[0]] = place(step.back, middle)
            points[part.point_ids[1]] = place(step.front, middle)
        # The box around what is drawn: a row of circles may not fill its frame.
        left = min(step.x for step in steps)
        right = max(step.x + step.length for step in steps)
        top = min(step.y for step in steps)
        bottom = max(step.y + step.thickness for step in steps)
        (x0, y0), (x1, y1) = place(left, top), place(right, bottom)
        for anchor in standard_connection_points():
            points[anchor.id] = (x0 + anchor.x * (x1 - x0), y0 + anchor.y * (y1 - y0))
    elif shape.type == "pyramid":
        points = {2: (cx, 0.0), 3: (cx, height)}
        for layer, part in zip(pyramid_layers(shape, width, height), shape.parts, strict=True):
            assert part.point_ids is not None
            reach = (layer.top_half_width + layer.bottom_half_width) / 2
            middle = (layer.top + layer.bottom) / 2
            points[part.point_ids[0]] = (cx - reach, middle)
            points[part.point_ids[1]] = (cx + reach, middle)
    elif shape.type == "cycle":
        band = cycle_band(shape, width, height)
        points = {point: _on_circle(cx, cy, band.outer, degrees) for point, degrees in RING_POINT_ANGLES.items()}
        mirrored = shape.settings["direction"] == "anticlockwise"
        for index, part in enumerate(shape.parts):
            assert part.point_ids is not None
            back = -90 + index * band.share - band.share / 2 + band.gap / 2
            tip = back + band.share - band.gap
            angle = (back + tip - band.depth) / 2 if shape.settings["arrow_style"] == "arrow" else (back + tip) / 2 - band.depth
            x, y = _on_circle(cx, cy, band.outer, angle)
            points[part.point_ids[0]] = (width - x if mirrored else x, y)
    elif shape.type == "gauge":
        gx, gy, radius, bottom = gauge_circle(width, height)
        points = {point: _on_circle(gx, gy, radius, RING_POINT_ANGLES[point]) for point in (0, 1, 2, 4, 6)}
        points |= {3: (gx, bottom), 5: (gx - radius, bottom), 7: (gx + radius, bottom)}
    return {point: (x / width, y / height) for point, (x, y) in points.items()}


def _meets_smallest_sizes(shape: ComplexShape, width: float, height: float) -> bool:
    """Whether every lane, row and column is at least its smallest size, and a lifeline
    its head and shortest line, as the app checks when it reads a file."""

    def at_least(value: float, minimum: float) -> bool:
        return value >= minimum * (1 - SMALLEST_SIZE_ALLOWANCE)

    if shape.type in ("table", "entity_table"):
        return all(at_least(row, MIN_TABLE_ROW_HEIGHT) for row in _lengths(shape.row_sizes, height)) and all(
            at_least(column, MIN_TABLE_COLUMN_WIDTH) for column in _lengths(shape.column_sizes, width)
        )
    if shape.type == "swimlanes":
        strip = float(shape.settings["title_strip_size"])  # type: ignore[arg-type]
        band = min(float(shape.settings["title_band_size"]), height)  # type: ignore[arg-type]
        shares = [lane.size or 0.0 for lane in shape.lanes]
        if shape.settings["direction"] == "horizontal":
            return at_least(width, strip) and all(
                at_least(lane, SWIMLANES_STRIP) for lane in _lengths(shares, max(0.0, height - band))
            )
        return at_least(height - band, strip) and all(
            at_least(lane, SWIMLANES_STRIP) for lane in _lengths(shares, width)
        )
    if shape.type == "lifeline":
        return at_least(height, lifeline_smallest_height(shape))
    return True


class Element(WireModel):
    """One entry in a page's `elements` array.

    Three keys, and a fourth, `complex_shape`, on an element of that kind and no other;
    the app rejects any other key. Both shape-data keys must be
    present; in this profile they are always `null` and `[]`.
    """

    content: ElementPresentation
    shape_data_definition_id: None
    shape_data_values: Annotated[list[Any], Field(max_length=0)]
    complex_shape: ComplexShape | None = None

    @model_serializer(mode="wrap")
    def _keep_null_definition(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # The app requires this key to be present even when it is null, so it
        # must survive an exclude_none dump.
        data: dict[str, Any] = handler(self)
        data["shape_data_definition_id"] = None
        return data

    @model_validator(mode="after")
    def _check_complex_shape(self) -> Element:
        core, shape = self.core, self.complex_shape
        if (core.kind == "complex_shape") != (shape is not None):
            raise ValueError("complex_shape is required on kind 'complex_shape' and forbidden elsewhere")
        if shape is None:
            return self
        entry = CATALOGUE[shape.type]
        if self.content.text_layout is not None:
            raise ValueError("a complex shape's text sits in a fixed place, so it has no text_layout")
        if shape.type != "callout" and (self.content.flip_horizontal or self.content.flip_vertical):
            raise ValueError(f"a {shape.type} cannot be flipped; only a callout can")
        if not entry.has_own_text and core.text_content.string:
            raise ValueError(f"a {shape.type}'s text is all in its parts; its own text must be empty")
        if shape.type == "gauge" and len(core.text_content.string) > MAX_PART_TEXT:
            raise ValueError(f"a gauge's caption holds at most {MAX_PART_TEXT} characters")
        if entry.own_points is not None:
            if core.connection_points:
                raise ValueError(f"a {shape.type} places its own connection points, so its element lists none")
            if self.content.preserves_aspect_ratio and shape.type != "entity_table":
                raise ValueError(f"a {shape.type} says itself how it resizes; remove preserves_aspect_ratio")
        if shape.settings.get("layout") == "proportional" and core.rotation_degrees % 360:
            raise ValueError("a proportional container is never turned")
        if not _meets_smallest_sizes(shape, core.frame.width, core.frame.height):
            raise ValueError(
                f"a {shape.type} {core.frame.width:g} by {core.frame.height:g} is smaller than its "
                "lanes, rows, columns or line allow"
            )
        texts = [core.text_content, *shape.texts]
        if sum(len(text.string.encode("utf-8")) for text in texts) > MAX_TEXT_BYTES:
            raise ValueError(f"a complex shape's texts together exceed {MAX_TEXT_BYTES} UTF-8 bytes")
        if sum(len(text.character_runs) + len(text.paragraph_runs) for text in texts) > MAX_TEXT_RUNS:
            raise ValueError("a complex shape's texts together have too many runs")
        if shape.tail_tip is not None:
            centre = max(abs(core.frame.x + core.frame.width / 2), abs(core.frame.y + core.frame.height / 2))
            if centre + math.hypot(shape.tail_tip.x, shape.tail_tip.y) > MAX_COORDINATE:
                raise ValueError("a callout's tail tip lies beyond the page's coordinates")
        if shape.tail_attachment is not None and shape.tail_attachment.element_id.upper() == core.id.upper():
            raise ValueError("a callout's tail cannot lock to the callout itself")
        return self

    @property
    def core(self) -> ElementCore:
        return self.content.content.content


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


class ConnectorPoint(WireModel):
    """One point along a connector, in page coordinates."""

    x: Coordinate
    y: Coordinate
    kind: PointKind


class ConnectorLabel(WireModel):
    """Text placed along a connector."""

    content: TextContent
    position: UnitInterval = Field(description="0 is the start, 1 the end.")
    normal_offset: Coordinate


class ConnectionCore(WireModel):
    """A connector's route, attachments and paint.

    `points` is the whole route and is always required. When an end is
    attached, the app redraws that end at the anchor, but the stored point
    should still be the anchor's position.
    """

    id: UUIDString
    points: Annotated[list[ConnectorPoint], Field(min_length=2)]
    start_attachment: Attachment | None = None
    end_attachment: Attachment | None = None
    stroke_hex: Color
    line_width: LineWidth
    stroke_pattern: StrokePattern
    start_ending: Ending
    end_ending: Ending
    stroke_texture: Texture | None = None
    label: ConnectorLabel | None = None


class Connection(WireModel):
    """One entry in a page's `connections` array.

    `routing` is absent for a direct line, which passes through every stored point, and
    `right_angle` for the app's right-angle connector. The skill writes `right_angle` only with
    a route it worked out itself: corners that keep every segment horizontal or vertical, which
    the app keeps as a hand-adjusted route, or, for two points, a straight run between anchors
    on facing frame edges, which the app's own router also draws straight.
    """

    content: ConnectionCore
    is_locked: bool
    routing: Literal["right_angle"] | None = Field(
        default=None,
        description="right_angle for a right-angle connector; absent for a direct line.",
    )

    @model_validator(mode="after")
    def _right_angle_runs_square(self) -> Connection:
        if self.routing == "right_angle":
            points = self.content.points
            for a, b in pairwise(points):
                if abs(a.x - b.x) > 0.01 and abs(a.y - b.y) > 0.01:
                    raise ValueError("a right-angle connector's segments must be horizontal or vertical")
            if any(point.kind != "straight" for point in points):
                raise ValueError("a right-angle connector's points are all straight")
        return self


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


class GridAppearance(WireModel):
    """How the page grid is drawn. It never affects snapping."""

    minor_line: GridLineStyle
    major_line: GridLineStyle
    major_interval: Annotated[int, Field(ge=2, le=20)]
    marker: GridMarker
    marker_placement: GridMarkerPlacement
    color: OpaqueColor | None = None
    strength: Annotated[float, Field(ge=0.02, le=1, allow_inf_nan=False)]


class Grid(WireModel):
    """The page's snapping grid."""

    spacing_x: Annotated[float, Field(ge=4, le=10_000, allow_inf_nan=False)]
    spacing_y: Annotated[float, Field(ge=4, le=10_000, allow_inf_nan=False)]
    origin: Point
    visible: bool | None = None
    appearance: GridAppearance | None = None


class PageCore(WireModel):
    """The innermost page record. Its two arrays are always empty.

    `width` and `height` are a reference size only: the canvas is unbounded
    and nothing is clipped to them.
    """

    id: UUIDString
    name: str
    width: Dimension
    height: Dimension
    elements: Annotated[list[Any], Field(max_length=0)]
    connections: Annotated[list[Any], Field(max_length=0)]
    grid: Grid
    export_frame: Rect | None = None

    @model_validator(mode="after")
    def _check_name(self) -> PageCore:
        _check_text(self.name, field="page name", max_bytes=MAX_NAME_BYTES)
        return self


class PageConnections(WireModel):
    """Wraps the page core and holds the page's connectors.

    `elements` and `groups` at this level are always empty.
    """

    content: PageCore
    elements: Annotated[list[Any], Field(max_length=0)]
    connections: list[Connection]
    groups: Annotated[list[Any], Field(max_length=0)]


class Background(WireModel):
    """The page background: none, or one solid color."""

    kind: Literal["none", "solid"]
    color_hex: Color | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> Background:
        if (self.kind == "solid") != (self.color_hex is not None):
            raise ValueError("color_hex is required for kind 'solid' and forbidden for 'none'")
        return self


class GroupMember(WireModel):
    """One member of a group, on the same page as the group."""

    kind: Literal["element", "connection", "group"]
    id: UUIDString


class Group(WireModel):
    """A set of elements, connectors and other groups that move together."""

    id: UUIDString
    members: Annotated[list[GroupMember], Field(min_length=2)]
    is_locked: bool
    rotation_degrees: Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False)]


class DrawableReference(WireModel):
    """One entry in an explicit drawing order, listed back to front."""

    kind: Literal["element", "connection"]
    id: UUIDString


class Guide(WireModel):
    """A manual ruler guide."""

    id: UUIDString
    axis: Literal["horizontal", "vertical"]
    position: Coordinate


class PageLayout(WireModel):
    """Wraps the connector layer with background, groups, guides and order.

    `drawableOrder` and `guides` are camelCase in the file. Without
    `drawableOrder`, connectors draw behind elements and elements stack by
    `z_index`; if it is present it must list every element and connector on
    the page exactly once, back to front.
    """

    content: PageConnections
    background: Background
    elements: Annotated[list[Any], Field(max_length=0)]
    groups: list[Group]
    drawableOrder: list[DrawableReference] | None = None
    guides: Annotated[list[Guide], Field(max_length=MAX_GUIDES)] | None = None


class Page(WireModel):
    """One entry in the document's `pages` array. Exactly two keys."""

    content: PageLayout
    elements: list[Element]

    @property
    def core(self) -> PageCore:
        return self.content.content.content

    @property
    def connections(self) -> list[Connection]:
        return self.content.content.connections


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class QuickStyleAppearance(WireModel):
    """The paint a Quick Style applies."""

    fill_hex: Color
    stroke_hex: Color
    line_width: Annotated[float, Field(ge=1, le=100, allow_inf_nan=False)]
    fill_texture: Texture | None = None
    stroke_texture: Texture | None = None
    stroke_pattern: StrokePattern | None = None


class QuickStyle(WireModel):
    """One preset in the document's Quick Styles panel."""

    id: UUIDString
    name: Annotated[str, Field(min_length=1)]
    style: QuickStyleAppearance

    @model_validator(mode="after")
    def _check_name(self) -> QuickStyle:
        _check_text(self.name, field="Quick Style name", max_bytes=MAX_QUICK_STYLE_NAME_BYTES)
        if self.name != self.name.strip() or _has_control_or_format(self.name):
            raise ValueError("Quick Style name has surrounding space or control characters")
        return self


def default_quick_styles() -> list[QuickStyle]:
    """The six presets the app gives every new document, with their fixed ids."""

    def preset(index: int, name: str, fill: str, stroke: str, width: float, **extra: Any) -> QuickStyle:
        return QuickStyle(
            id=f"51554943-4B53-4000-8000-{index:012X}",
            name=name,
            style=QuickStyleAppearance(
                fill_hex=fill, stroke_hex=stroke, line_width=width, **extra
            ),
        )

    return [
        preset(1, "Outline", "#00000000", "#000000", 1),
        preset(2, "Paper", "#FFFFFF", "#343A40", 2),
        preset(3, "Note", "#FFF1A8", "#8A7636", 2),
        preset(4, "Sky", "#D8ECFF", "#46637F", 2),
        preset(5, "Mint", "#DDF5E3", "#446B4C", 2),
        preset(
            6, "Sketch", "#F8F9FA", "#343A40", 2,
            fill_texture="PencilFill", stroke_texture="PencilFill",
        ),
    ]


class Document(WireModel):
    """The whole of `document.json`: these nine keys, all required."""

    id: UUIDString
    schema_version: Literal[18] = Field(description="18, for package format 19.")
    revision: Annotated[int, Field(ge=0, le=MAX_REVISION)] = Field(
        description="Edit counter. A new document is 0."
    )
    name: str
    selected_page_id: UUIDString
    pages: Annotated[list[Page], Field(min_length=1, max_length=MAX_PAGES)]
    quick_styles: Annotated[list[QuickStyle], Field(max_length=MAX_QUICK_STYLES)]
    embedded_assets: Annotated[list[Any], Field(max_length=0)]
    shape_data_definitions: Annotated[list[Any], Field(max_length=0)]

    @model_validator(mode="after")
    def _check_document(self) -> Document:
        _check_text(self.name, field="document name", max_bytes=MAX_NAME_BYTES)
        # One identifier space covers the document, quick styles, pages,
        # elements, connectors, groups and guides.
        seen: set[str] = set()

        def claim(identifier: str, what: str) -> None:
            key = identifier.upper()
            if key in seen:
                raise ValueError(f"{what} id {identifier} is used more than once in the document")
            seen.add(key)

        claim(self.id, "document")
        for preset in self.quick_styles:
            claim(preset.id, "quick style")

        element_total = connection_total = group_total = member_total = node_total = 0
        complex_text_total = 0
        for page_index, page in enumerate(self.pages):
            where = f"pages[{page_index}]"
            claim(page.core.id, "page")
            for guide in page.content.guides or []:
                claim(guide.id, "guide")

            anchors: dict[str, set[int]] = {}
            # The attach lines each element offers: a lifeline's dashed line, and no other.
            lines: dict[str, set[int]] = {}
            for element in page.elements:
                core = element.core
                claim(core.id, "element")
                placed_by_shape = element.complex_shape.own_point_ids if element.complex_shape else None
                anchors[core.id.upper()] = (
                    {anchor.id for anchor in core.connection_points} if placed_by_shape is None else placed_by_shape
                )
                is_lifeline = element.complex_shape is not None and element.complex_shape.type == "lifeline"
                lines[core.id.upper()] = {LIFELINE_ATTACH_LINE} if is_lifeline else set()
                node_total += len(core.path.nodes) if core.path else 0
                complex_text_total += len(element.complex_shape.texts) if element.complex_shape else 0

            connection_ids: set[str] = set()
            for connection in page.connections:
                core = connection.content
                claim(core.id, "connection")
                connection_ids.add(core.id.upper())
                node_total += len(core.points)
                for end, attachment in (
                    ("start_attachment", core.start_attachment),
                    ("end_attachment", core.end_attachment),
                ):
                    if attachment is None:
                        continue
                    self._check_attachment(attachment, anchors, lines, f"{where}: connection {core.id} {end}")

            order = page.content.drawableOrder
            if order is not None:
                listed = [(entry.kind, entry.id.upper()) for entry in order]
                expected = {("element", key) for key in anchors} | {
                    ("connection", key) for key in connection_ids
                }
                if len(listed) != len(set(listed)) or set(listed) != expected:
                    raise ValueError(
                        f"{where}: drawableOrder must list every element and connection "
                        "on the page exactly once"
                    )

            self._check_groups(page.content.groups, set(anchors), connection_ids, where)
            self._check_complex_shapes(page, anchors, lines, where)
            for group in page.content.groups:
                claim(group.id, "group")
                member_total += len(group.members)

            element_total += len(page.elements)
            connection_total += len(page.connections)
            group_total += len(page.content.groups)

        if element_total > MAX_ELEMENTS:
            raise ValueError(f"more than {MAX_ELEMENTS} elements")
        if connection_total > MAX_CONNECTIONS:
            raise ValueError(f"more than {MAX_CONNECTIONS} connections")
        if group_total > MAX_GROUPS or member_total > MAX_GROUP_MEMBERS:
            raise ValueError("too many groups or group members")
        if node_total > MAX_PATH_NODES:
            raise ValueError(f"more than {MAX_PATH_NODES} path and connector points")
        if complex_text_total > MAX_COMPLEX_SHAPE_TEXTS:
            raise ValueError(f"more than {MAX_COMPLEX_SHAPE_TEXTS} lane titles and table cells")
        if self.selected_page_id.upper() not in {page.core.id.upper() for page in self.pages}:
            raise ValueError("selected_page_id does not name a page in this document")
        return self

    @staticmethod
    def _check_attachment(
        attachment: Attachment, anchors: dict[str, set[int]], lines: dict[str, set[int]], what: str
    ) -> None:
        """An attachment names an element of the page and a place that element has."""
        key = attachment.element_id.upper()
        if key not in anchors:
            raise ValueError(f"{what} names element {attachment.element_id}, which is not on this page")
        if attachment.on_line:
            if attachment.attach_line_id not in lines[key]:
                raise ValueError(
                    f"{what} names attach line {attachment.attach_line_id}, which that element "
                    "does not have; only a lifeline has one, line 0"
                )
        elif attachment.connection_point_id not in anchors[key]:
            raise ValueError(
                f"{what} names connection point {attachment.connection_point_id}, which that "
                "element does not have"
            )

    @staticmethod
    def _check_complex_shapes(
        page: Page, anchors: dict[str, set[int]], lines: dict[str, set[int]], where: str
    ) -> None:
        """The rules complex shapes add that involve other shapes on their page, as the app
        checks them when it reads a file.

        Every member exists on the page and is held by one container or lane at most. A
        member is a shape that is in no group, or a whole group that is in no other group;
        never the holder itself, never swimlanes. A container or swimlanes is never in a
        group, and containers hold containers at most four deep, never in a loop. A callout's
        tail locks to an anchor that another shape on the page has. A page holds only so many
        complex shapes.
        """
        shapes = {element.core.id.upper(): element.complex_shape for element in page.elements}
        complex_shapes = [shape for shape in shapes.values() if shape is not None]
        if len(complex_shapes) > MAX_PAGE_COMPLEX_SHAPES:
            raise ValueError(f"{where}: a page holds at most {MAX_PAGE_COMPLEX_SHAPES} complex shapes")
        if sum(shape.holds_shapes for shape in complex_shapes) > MAX_PAGE_HOLDERS:
            raise ValueError(f"{where}: a page holds at most {MAX_PAGE_HOLDERS} containers and swimlanes")
        if sum(len(text.string) for shape in complex_shapes for text in shape.texts) > MAX_PAGE_PART_CHARACTERS:
            raise ValueError(f"{where}: a page's complex shapes hold at most {MAX_PAGE_PART_CHARACTERS} characters")
        grouped_elements: set[str] = set()
        grouped_groups: set[str] = set()
        for group in page.content.groups:
            for member in group.members:
                if member.kind == "element":
                    grouped_elements.add(member.id.upper())
                elif member.kind == "group":
                    grouped_groups.add(member.id.upper())
        group_ids = {group.id.upper() for group in page.content.groups}
        holder_of: dict[tuple[str, str], str] = {}
        for element in page.elements:
            shape, own = element.complex_shape, element.core.id.upper()
            if shape is None:
                continue
            if shape.tail_attachment is not None:
                Document._check_attachment(shape.tail_attachment, anchors, lines, f"{where}: callout {own}'s tail")
            if not shape.holds_shapes:
                continue
            if own in grouped_elements:
                raise ValueError(f"{where}: {shape.type} {own} is in a group, which a holder never is")
            for held in shape.all_members:
                key = held.id.upper()
                if held.kind == "element":
                    if key not in shapes or key == own:
                        raise ValueError(f"{where}: {shape.type} {own} holds element {key}, which is not another shape on this page")
                    held_shape = shapes[key]
                    if held_shape is not None and held_shape.type == "swimlanes":
                        raise ValueError(f"{where}: {shape.type} {own} holds swimlanes {key}; swimlanes are never held")
                    if key in grouped_elements:
                        raise ValueError(f"{where}: {shape.type} {own} holds element {key}, which is in a group; hold the whole group")
                else:
                    if key not in group_ids:
                        raise ValueError(f"{where}: {shape.type} {own} holds group {key}, which is not on this page")
                    if key in grouped_groups:
                        raise ValueError(f"{where}: {shape.type} {own} holds group {key}, which is inside another group")
                if holder_of.setdefault((held.kind, key), own) != own:
                    raise ValueError(f"{where}: {held.kind} {key} is held by two containers or lanes")
        holders = [
            element.core.id.upper() for element in page.elements
            if element.complex_shape is not None and element.complex_shape.holds_shapes
        ]
        for start in holders:
            seen, current, depth = {start}, start, 1
            while ("element", current) in holder_of:
                current = holder_of[("element", current)]
                depth += 1
                if current in seen:
                    raise ValueError(f"{where}: containers hold one another in a loop")
                if depth > MAX_HOLDER_NESTING:
                    raise ValueError(f"{where}: containers nest more than {MAX_HOLDER_NESTING} deep")
                seen.add(current)

    @staticmethod
    def _check_groups(
        groups: list[Group], element_ids: set[str], connection_ids: set[str], where: str
    ) -> None:
        group_ids = [group.id.upper() for group in groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError(f"{where}: two groups share an id")
        known_groups = set(group_ids)
        parent_of_member: dict[tuple[str, str], str] = {}
        parent_of_group: dict[str, str] = {}
        for group in groups:
            own = group.id.upper()
            members = [(member.kind, member.id.upper()) for member in group.members]
            if len(members) != len(set(members)):
                raise ValueError(f"{where}: group {group.id} lists a member twice")
            for kind, identifier in members:
                resolves = (
                    (kind == "element" and identifier in element_ids)
                    or (kind == "connection" and identifier in connection_ids)
                    or (kind == "group" and identifier != own and identifier in known_groups)
                )
                if not resolves:
                    raise ValueError(
                        f"{where}: group {group.id} member {kind} {identifier} is not on this page"
                    )
                if (kind, identifier) in parent_of_member:
                    raise ValueError(
                        f"{where}: {kind} {identifier} belongs to more than one group"
                    )
                parent_of_member[(kind, identifier)] = own
                if kind == "group":
                    parent_of_group[identifier] = own
        for start in known_groups:
            visited = {start}
            current = start
            depth = 1
            while current in parent_of_group:
                current = parent_of_group[current]
                if current in visited:
                    raise ValueError(f"{where}: groups nest in a cycle")
                visited.add(current)
                depth += 1
                if depth > MAX_GROUP_DEPTH:
                    raise ValueError(f"{where}: groups nest deeper than {MAX_GROUP_DEPTH}")


TextLayout.model_rebuild()


# ---------------------------------------------------------------------------
# Builders
#
# The models above have no defaults for any key the app requires, so that a
# missing key is an error when a file is read. These functions supply the
# values SimpleDiagrams itself uses, for code that writes documents.
# ---------------------------------------------------------------------------


def manifest(document: Document | None = None) -> Manifest:
    """The manifest for `document`: its package format is its schema version plus one."""
    format_version = FORMAT_VERSION if document is None else document.schema_version + 1
    return Manifest(format=FORMAT_NAME, format_version=format_version, contains_legacy_source=False)


def character_style(
    *,
    font_size: float = 15.0,
    weight: str = "medium",
    is_italic: bool = False,
    is_underlined: bool = False,
    color_hex: str = "#212529",
    font_family: str | None = None,
    highlight_hex: str | None = None,
) -> CharacterStyle:
    """A text style starting from the app's standard one."""
    return CharacterStyle(
        font_family=font_family, font_size=font_size, weight=weight, is_italic=is_italic,
        is_underlined=is_underlined, color_hex=color_hex, highlight_hex=highlight_hex,
    )


def text_content(
    string: str = "",
    *,
    base_style: CharacterStyle | None = None,
    base_alignment: str = "center",
    character_runs: list[CharacterRun] | None = None,
    paragraph_runs: list[ParagraphRun] | None = None,
) -> TextContent:
    """Centred text in one style, which is what a label normally is."""
    return TextContent(
        string=string, base_style=base_style or character_style(), base_alignment=base_alignment,
        character_runs=character_runs or [], paragraph_runs=paragraph_runs or [],
    )


def element(
    *,
    id: str,
    kind: str,
    frame: Rect,
    style: ElementStyle,
    text: TextContent | None = None,
    rotation_degrees: float = 0.0,
    z_index: int = 0,
    connection_points: list[ConnectionPointAnchor] | None = None,
    symbol_reference: SymbolReference | None = None,
    path: Path | None = None,
    is_locked: bool = False,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
    text_layout: TextLayout | None = None,
    note_style: str | None = None,
    preserves_aspect_ratio: bool | None = None,
    complex_shape: ComplexShape | None = None,
) -> Element:
    """Wraps one shape in the four records an element needs, with its complex shape
    record when it is one."""
    return Element(
        content=ElementPresentation(
            content=ElementLock(
                content=ElementCore(
                    id=id, kind=kind, frame=frame, rotation_degrees=rotation_degrees, z_index=z_index,
                    text_content=text or text_content(), style=style,
                    connection_points=(
                        standard_connection_points() if connection_points is None else connection_points
                    ),
                    symbol_reference=symbol_reference, path=path,
                ),
                is_locked=is_locked,
            ),
            flip_horizontal=flip_horizontal, flip_vertical=flip_vertical, text_layout=text_layout,
            note_style=note_style, preserves_aspect_ratio=preserves_aspect_ratio,
        ),
        shape_data_definition_id=None,
        shape_data_values=[],
        complex_shape=complex_shape,
    )


def _record(
    type: ComplexShapeType, settings: dict[str, Any], parts: list[Part] | None = None, *,
    members: list[HolderMember] | None = None, hand_drawn: bool | None = None,
) -> ComplexShape:
    return ComplexShape(
        type=type, version=1, settings=settings, parts=parts or [], members=members,
        hand_drawn=False if hand_drawn is False else None,
    )


def container_shape(
    members: list[HolderMember], *, title_style: str = "band", layout: str = "free", hand_drawn: bool | None = None
) -> ComplexShape:
    """A container's record: what it holds, where its title sits, and its layout."""
    return _record("container", {"layout": layout, "title_style": title_style}, members=members, hand_drawn=hand_drawn)


def swimlanes_shape(
    lanes: list[Part], *, direction: str = "horizontal", title_strip_size: float = SWIMLANES_STRIP,
    title_band_size: float = SWIMLANES_STRIP, hand_drawn: bool | None = None,
) -> ComplexShape:
    """A swimlanes record, with lanes made by `lane`."""
    settings = {"direction": direction, "title_strip_size": title_strip_size, "title_band_size": title_band_size}
    return _record("swimlanes", settings, lanes, hand_drawn=hand_drawn)


def lane(id: str, title: TextContent, size: float, members: list[HolderMember]) -> Part:
    """One lane of swimlanes: its title, its share of the whole, and what it holds."""
    return Part(role="lane", id=id, text=title, size=size, members=members)


def table_shape(
    row_sizes: list[float], column_sizes: list[float], cells: list[list[TextContent]], *,
    header_row: bool = True, hand_drawn: bool | None = None,
) -> ComplexShape:
    """A table's record: all its columns, then all its rows with their cells."""
    parts = [Part(role="column", size=size) for size in column_sizes]
    parts += [Part(role="row", size=size, cells=row) for size, row in zip(row_sizes, cells, strict=True)]
    return _record("table", {"header_row": header_row}, parts, hand_drawn=hand_drawn)


class EntityField(NamedTuple):
    """One field of an entity table."""

    id: str
    name: TextContent
    type: TextContent
    size: float
    marks: list[str]


def entity_table_shape(
    column_sizes: list[float], header_id: str, name: TextContent, header_size: float, empty: TextContent,
    fields: list[EntityField], *, hand_drawn: bool | None = None,
) -> ComplexShape:
    """An entity table's record. Each field owns the next two free points, its left and right ends."""
    parts = [Part(role="column", size=size) for size in column_sizes]
    parts.append(Part(role="header", id=header_id, size=header_size, cells=[name, empty]))
    parts += [
        Part(
            role="field", id=field.id, size=field.size, cells=[field.name, field.type], marks=field.marks,
            point_ids=[FIRST_PART_POINT + 2 * index, FIRST_PART_POINT + 2 * index + 1],
        )
        for index, field in enumerate(fields)
    ]
    return _record("entity_table", {}, parts, hand_drawn=hand_drawn)


def callout_shape(
    tail_tip: Point | None = None, tail_attachment: Attachment | None = None, *, hand_drawn: bool | None = None
) -> ComplexShape:
    """A callout's record: no tip means no tail."""
    settings = {
        name: value for name, value in (("tail_tip", tail_tip), ("tail_attachment", tail_attachment))
        if value is not None
    }
    return _record("callout", settings, hand_drawn=hand_drawn)


def lifeline_shape(
    head_style: str = "box", ends_in_destroy_mark: bool = False, *, hand_drawn: bool | None = None
) -> ComplexShape:
    """A lifeline's record."""
    return _record(
        "lifeline", {"head_style": head_style, "ends_in_destroy_mark": ends_in_destroy_mark}, hand_drawn=hand_drawn
    )


def labelled_part(
    role: str, id: str, text: TextContent, style: PartStyle | None = None, points: int = 0, index: int = 0
) -> Part:
    """A section, step, layer or band: its words, its paint, and the points it owns, the
    next `points` free numbers for the part at `index`."""
    owned = [FIRST_PART_POINT + points * index + offset for offset in range(points)] if points else None
    return Part(role=role, id=id, text=text, style=style, point_ids=owned)


def ring_shape(sections: list[Part], ring_width: float | str = 40, *, hand_drawn: bool | None = None) -> ComplexShape:
    """A ring's record; `ring_width` is the word `full` for a solid disc."""
    return _record("ring", {"ring_width": ring_width}, sections, hand_drawn=hand_drawn)


def flow_shape(
    steps: list[Part], *, base_shape: str = "chevron", direction: str = "across", spacing: str = "gap",
    pointer: bool = False, hand_drawn: bool | None = None,
) -> ComplexShape:
    """A flow's record."""
    settings = {"base_shape": base_shape, "direction": direction, "spacing": spacing, "pointer": pointer}
    return _record("flow", settings, steps, hand_drawn=hand_drawn)


def pyramid_shape(layers: list[Part], *, form: str = "pyramid", hand_drawn: bool | None = None) -> ComplexShape:
    """A pyramid's or funnel's record, its layers from the top."""
    return _record("pyramid", {"form": form}, layers, hand_drawn=hand_drawn)


def cycle_shape(
    steps: list[Part], *, ring_width: float = 50, direction: str = "clockwise", arrow_style: str = "arrow",
    hand_drawn: bool | None = None,
) -> ComplexShape:
    """A cycle's record."""
    settings = {"ring_width": ring_width, "direction": direction, "arrow_style": arrow_style}
    return _record("cycle", settings, steps, hand_drawn=hand_drawn)


def gauge_shape(
    bands: list[Part], needle_id: str, *, minimum: float = 0, maximum: float = 100, value: float = 50,
    auto_rotate_labels: bool = True, hand_drawn: bool | None = None,
) -> ComplexShape:
    """A gauge's record: its bands from the minimum to the maximum, then its needle."""
    settings = {"minimum": minimum, "maximum": maximum, "value": value, "auto_rotate_labels": auto_rotate_labels}
    return _record("gauge", settings, [*bands, Part(role="needle", id=needle_id)], hand_drawn=hand_drawn)


def connection(
    *,
    id: str,
    points: list[ConnectorPoint],
    start_attachment: Attachment | None = None,
    end_attachment: Attachment | None = None,
    stroke_hex: str = "#495057",
    line_width: float = 2.0,
    stroke_pattern: str = "solid",
    start_ending: str = "none",
    end_ending: str = "arrow",
    stroke_texture: str | None = None,
    label: ConnectorLabel | None = None,
    is_locked: bool = False,
    right_angle: bool = False,
) -> Connection:
    """A connector in the app's standard gray, with an arrow at its end; a right-angle
    connector when `right_angle`, else a direct line."""
    return Connection(
        content=ConnectionCore(
            id=id, points=points, start_attachment=start_attachment, end_attachment=end_attachment,
            stroke_hex=stroke_hex, line_width=line_width, stroke_pattern=stroke_pattern,
            start_ending=start_ending, end_ending=end_ending, stroke_texture=stroke_texture, label=label,
        ),
        is_locked=is_locked,
        routing="right_angle" if right_angle else None,
    )


def page(
    *,
    id: str,
    name: str,
    elements: list[Element] | None = None,
    connections: list[Connection] | None = None,
    groups: list[Group] | None = None,
    background: Background | None = None,
    grid: Grid | None = None,
    width: float = 2000.0,
    height: float = 1200.0,
    export_frame: Rect | None = None,
    drawable_order: list[DrawableReference] | None = None,
    guides: list[Guide] | None = None,
) -> Page:
    """Wraps a page's content in the four records a page needs."""
    return Page(
        content=PageLayout(
            content=PageConnections(
                content=PageCore(
                    id=id, name=name, width=width, height=height, elements=[], connections=[],
                    grid=grid or Grid(spacing_x=20.0, spacing_y=20.0, origin=Point(x=0.0, y=0.0)),
                    export_frame=export_frame,
                ),
                elements=[], connections=connections or [], groups=[],
            ),
            background=background or Background(kind="none"),
            elements=[], groups=groups or [], drawableOrder=drawable_order, guides=guides,
        ),
        elements=elements or [],
    )


def document(
    *,
    id: str,
    name: str,
    pages: list[Page],
    selected_page_id: str | None = None,
    revision: int = 0,
    quick_styles: list[QuickStyle] | None = None,
) -> Document:
    """A new document showing its first page, with the app's six Quick Styles."""
    return Document(
        id=id,
        schema_version=SCHEMA_VERSION,
        revision=revision, name=name,
        selected_page_id=selected_page_id or pages[0].core.id, pages=pages,
        quick_styles=default_quick_styles() if quick_styles is None else quick_styles,
        embedded_assets=[], shape_data_definitions=[],
    )



def dump(model: BaseModel) -> dict[str, Any]:
    """Serializes a model the way it belongs in the file.

    Optional keys are left out rather than written as null, except the one
    key the app requires to be present.
    """
    return model.model_dump(mode="json", exclude_none=True)

