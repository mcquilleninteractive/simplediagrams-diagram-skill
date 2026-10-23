"""Exact models of a SimpleDiagrams document at package format 18, which SimpleDiagrams
5.1.0 writes and reads.

Every document the skill writes is package 18 / schema 17 and needs SimpleDiagrams
5.1.0 or later. Besides shapes, text and connectors it holds the shapes the app draws
itself (complex shapes: containers, swimlanes, tables, callouts and UML lifelines), connector
ends attached anywhere along a lifeline, and label regions that start outside their
shape.

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
background images, print layout, and unresolved legacy content.

`FORMAT_VERSION` and `SCHEMA_VERSION` are separate counters and both are
pinned. See VERSIONS.md before changing either.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

FORMAT_NAME = "com.simplediagrams.document"
FORMAT_VERSION = 18
SCHEMA_VERSION = 17

# The app's limits on complex shapes (ComplexShape.Limits and the drawing constants).
MIN_SHARE = 0.000_001
MAX_SHARE = 1_000_000.0
MAX_LANES = 50
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 50
MAX_TABLE_CELLS = 2_000
MAX_HOLDER_NESTING = 4
MAX_COMPLEX_SHAPE_TEXTS = 100_000
MIN_TABLE_COLUMN_WIDTH = 16.0
MIN_TABLE_ROW_HEIGHT = 12.0
# A new swimlanes' title strip and title band, and the thinnest either (or a lane) may be.
SWIMLANES_STRIP = 28.0
MAX_SWIMLANES_STRIP = 10_000.0
LIFELINE_HEAD_HEIGHT = {"box": 40.0, "actor": 72.0}
SHORTEST_LIFELINE_LINE = 20.0
DESTROY_MARK_SIZE = 24.0
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
NoteStyle = Literal["stickyNote", "indexCard"]
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
    format_version: Literal[18] = Field(
        description="Package format, which SimpleDiagrams 5.1.0 and later read. document.json's "
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
    """The label of an element or connector. Every key except background_hex is required.

    Runs are only allowed over plain ASCII text. The app requires each run to
    start and end between whole user-perceived characters, which for accented
    letters, emoji and other combined characters cannot be checked here.
    """

    string: str
    base_style: CharacterStyle
    character_runs: list[CharacterRun]
    base_alignment: TextAlignment
    paragraph_runs: list[ParagraphRun]
    background_hex: Color | None = None

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
# Complex shapes: shapes the app draws from a few stored values
# ---------------------------------------------------------------------------


class HolderMember(WireModel):
    """One thing a container or a lane holds: a shape, or a whole group that is in no
    other group. Never a connector, never swimlanes, and never a piece of a group."""

    kind: Literal["element", "group"]
    id: UUIDString


class Lane(WireModel):
    """One lane of a swimlanes shape. Its id is unique within its shape."""

    id: UUIDString
    title: TextContent
    size: Share
    members: Annotated[list[HolderMember], Field(max_length=MAX_ELEMENTS)]


# The keys each type of complex shape may carry beyond `type` and `hand_drawn`, and the
# ones it must, as the app reads and writes them.
COMPLEX_SHAPE_KEYS: dict[str, frozenset[str]] = {
    "container": frozenset({"members", "title_style"}),
    "swimlanes": frozenset({"direction", "lanes", "title_strip_size", "title_band_size"}),
    "table": frozenset({"row_sizes", "column_sizes", "cells", "header_row"}),
    "callout": frozenset({"tail_tip", "tail_attachment"}),
    "lifeline": frozenset({"head_style", "ends_in_destroy_mark"}),
}
COMPLEX_SHAPE_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "container": frozenset({"members"}),
    "swimlanes": frozenset({"direction", "lanes"}),
    "table": frozenset({"row_sizes", "column_sizes", "cells"}),
    "callout": frozenset(),
    "lifeline": frozenset(),
}
StripSize = Annotated[float, Field(ge=SWIMLANES_STRIP, le=MAX_SWIMLANES_STRIP, allow_inf_nan=False)]


class ComplexShape(WireModel):
    """The `complex_shape` record of an element of kind `complex_shape`.

    It holds only the keys its `type` uses. Each optional key is written only when it
    differs from the default the app reads in its place: `hand_drawn` only as false,
    `title_style` only as `corner_tag` (the default is the band), `header_row` only as
    false, `head_style` only as `actor` (the default is a box) and `ends_in_destroy_mark`
    only as true. A container's members and a table's sizes and cells are always written.

    - container: `members`, in order; `title_style`.
    - swimlanes: `direction`; `lanes`, each with an id unique in the shape, a title, a
      size as a share of the whole, and members; the title strip's and band's thickness
      when wider than 28.
    - table: `row_sizes` and `column_sizes` as shares; `cells`, row by row, one text per
      column; `header_row`.
    - callout: `tail_tip`, the tail's tip in points from the frame's centre, along the
      bubble's own axes before flipping; no tip means no tail. `tail_attachment` locks
      the tail to another shape's anchor and needs a tip, saved where it is drawn.
    - lifeline: `head_style`; `ends_in_destroy_mark`.
    """

    type: Literal["container", "swimlanes", "table", "callout", "lifeline"]
    hand_drawn: Literal[False] | None = None
    members: Annotated[list[HolderMember], Field(max_length=MAX_ELEMENTS)] | None = None
    title_style: Literal["corner_tag"] | None = None
    direction: Literal["horizontal", "vertical"] | None = None
    lanes: Annotated[list[Lane], Field(min_length=1, max_length=MAX_LANES)] | None = None
    title_strip_size: StripSize | None = None
    title_band_size: StripSize | None = None
    row_sizes: Annotated[list[Share], Field(min_length=1, max_length=MAX_TABLE_ROWS)] | None = None
    column_sizes: Annotated[list[Share], Field(min_length=1, max_length=MAX_TABLE_COLUMNS)] | None = None
    cells: (
        Annotated[
            list[Annotated[list[TextContent], Field(max_length=MAX_TABLE_COLUMNS)]],
            Field(max_length=MAX_TABLE_ROWS),
        ]
        | None
    ) = None
    header_row: Literal[False] | None = None
    tail_tip: Point | None = None
    tail_attachment: Attachment | None = None
    head_style: Literal["actor"] | None = None
    ends_in_destroy_mark: Literal[True] | None = None

    @model_validator(mode="after")
    def _check_type(self) -> ComplexShape:
        present = {
            key for key in frozenset().union(*COMPLEX_SHAPE_KEYS.values())
            if getattr(self, key) is not None
        }
        stray = present - COMPLEX_SHAPE_KEYS[self.type]
        if stray:
            raise ValueError(f"a {self.type} does not take {', '.join(sorted(stray))}")
        missing = COMPLEX_SHAPE_REQUIRED_KEYS[self.type] - present
        if missing:
            raise ValueError(f"a {self.type} needs {', '.join(sorted(missing))}")
        for members in [self.members or []] + [lane.members for lane in self.lanes or []]:
            listed = [(member.kind, member.id.upper()) for member in members]
            if len(listed) != len(set(listed)):
                raise ValueError(f"a {self.type} lists a member twice")
        if self.lanes is not None and len({lane.id.upper() for lane in self.lanes}) != len(self.lanes):
            raise ValueError("two lanes of one swimlanes share an id")
        if self.type == "table":
            rows, columns = len(self.row_sizes or []), len(self.column_sizes or [])
            cells = self.cells or []
            if len(cells) != rows or any(len(row) != columns for row in cells):
                raise ValueError("a table has one row of cells per row size and one cell per column size")
            if rows * columns > MAX_TABLE_CELLS:
                raise ValueError(f"a table has at most {MAX_TABLE_CELLS} cells")
        if self.tail_attachment is not None:
            if self.tail_tip is None:
                raise ValueError("a callout's locked tail also needs its tail_tip, where it is drawn")
            if self.tail_attachment.on_line:
                raise ValueError("a callout's tail locks to a connection point, never along a line")
        return self

    @property
    def holds_shapes(self) -> bool:
        """Whether it is a container or swimlanes, which hold other shapes."""
        return self.type in ("container", "swimlanes")

    @property
    def all_members(self) -> list[HolderMember]:
        """What a container or every lane of swimlanes holds, in order."""
        return list(self.members or []) + [member for lane in self.lanes or [] for member in lane.members]

    @property
    def texts(self) -> list[TextContent]:
        """The lane titles or table cells it holds besides its own text."""
        if self.type == "swimlanes":
            return [lane.title for lane in self.lanes or []]
        return [cell for row in self.cells or [] for cell in row]


def _lengths(shares: list[float], length: float) -> list[float]:
    """Shares as lengths that add up to `length`, as the app divides them."""
    total = sum(shares)
    return [share / total * length for share in shares]


def lifeline_line(shape: ComplexShape, frame: Rect) -> tuple[float, float]:
    """Where a lifeline's dashed line starts and ends, in points down from its frame's top:
    from the bottom of its head to the frame's bottom, or to half a destroy mark above it."""
    head = LIFELINE_HEAD_HEIGHT[shape.head_style or "box"]
    inset = DESTROY_MARK_SIZE / 2 if shape.ends_in_destroy_mark else 0.0
    start = min(head, frame.height)
    return start, max(start, frame.height - inset)


def lifeline_smallest_height(shape: ComplexShape) -> float:
    """The shortest frame a lifeline may have: its head, the shortest line, and half a
    destroy mark when it ends in one."""
    head = LIFELINE_HEAD_HEIGHT[shape.head_style or "box"]
    return head + SHORTEST_LIFELINE_LINE + (DESTROY_MARK_SIZE / 2 if shape.ends_in_destroy_mark else 0.0)


def swimlane_frames(shape: ComplexShape, frame: Rect) -> list[Rect]:
    """Each lane's frame on the page, in lane order, for an unturned swimlanes: below the
    title band, sharing the rest by their shares, as the app draws them."""
    band = min(shape.title_band_size or SWIMLANES_STRIP, frame.height)
    lanes = shape.lanes or []
    frames = []
    if shape.direction == "horizontal":
        y = frame.y + band
        for size in _lengths([lane.size for lane in lanes], max(0.0, frame.height - band)):
            frames.append(Rect(x=frame.x, y=y, width=frame.width, height=max(size, 1e-9)))
            y += size
    else:
        x = frame.x
        for size in _lengths([lane.size for lane in lanes], frame.width):
            frames.append(Rect(x=x, y=frame.y + band, width=max(size, 1e-9), height=max(frame.height - band, 1e-9)))
            x += size
    return frames


def _meets_smallest_sizes(shape: ComplexShape, width: float, height: float) -> bool:
    """Whether every lane, row and column is at least its smallest size, and a lifeline
    its head and shortest line, as the app checks when it reads a file."""

    def at_least(value: float, minimum: float) -> bool:
        return value >= minimum * (1 - SMALLEST_SIZE_ALLOWANCE)

    if shape.type == "table":
        return all(at_least(row, MIN_TABLE_ROW_HEIGHT) for row in _lengths(shape.row_sizes or [], height)) and all(
            at_least(column, MIN_TABLE_COLUMN_WIDTH) for column in _lengths(shape.column_sizes or [], width)
        )
    if shape.type == "swimlanes":
        strip = shape.title_strip_size or SWIMLANES_STRIP
        band = min(shape.title_band_size or SWIMLANES_STRIP, height)
        shares = [lane.size for lane in shape.lanes or []]
        if shape.direction == "horizontal":
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
        if self.content.text_layout is not None:
            raise ValueError("a complex shape's text sits in a fixed place, so it has no text_layout")
        if shape.type != "callout" and (self.content.flip_horizontal or self.content.flip_vertical):
            raise ValueError(f"a {shape.type} cannot be flipped; only a callout can")
        if shape.type == "table" and core.text_content.string:
            raise ValueError("a table's text is all in its cells; its own text must be empty")
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
    """One entry in a page's `connections` array."""

    content: ConnectionCore
    is_locked: bool


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
    schema_version: Literal[17] = Field(description="17, for package format 18.")
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
                anchors[core.id.upper()] = {anchor.id for anchor in core.connection_points}
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
        tail locks to an anchor that another shape on the page has.
        """
        shapes = {element.core.id.upper(): element.complex_shape for element in page.elements}
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
) -> CharacterStyle:
    """A text style starting from the app's standard one."""
    return CharacterStyle(
        font_family=font_family, font_size=font_size, weight=weight, is_italic=is_italic,
        is_underlined=is_underlined, color_hex=color_hex,
    )


def text_content(
    string: str = "",
    *,
    base_style: CharacterStyle | None = None,
    base_alignment: str = "center",
    character_runs: list[CharacterRun] | None = None,
    paragraph_runs: list[ParagraphRun] | None = None,
    background_hex: str | None = None,
) -> TextContent:
    """Centred text in one style, which is what a label normally is."""
    return TextContent(
        string=string, base_style=base_style or character_style(), base_alignment=base_alignment,
        character_runs=character_runs or [], paragraph_runs=paragraph_runs or [],
        background_hex=background_hex,
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
) -> Connection:
    """A connector in the app's standard gray, with an arrow at its end."""
    return Connection(
        content=ConnectionCore(
            id=id, points=points, start_attachment=start_attachment, end_attachment=end_attachment,
            stroke_hex=stroke_hex, line_width=line_width, stroke_pattern=stroke_pattern,
            start_ending=start_ending, end_ending=end_ending, stroke_texture=stroke_texture, label=label,
        ),
        is_locked=is_locked,
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

