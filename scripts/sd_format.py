"""Exact models of a SimpleDiagrams document at package formats 15 and 16.

Format 15 is what the skill writes by default; it opens in SimpleDiagrams 5.0.8 and
later. Format 16 adds one optional key, `required_libraries`, which names the
downloaded libraries a document's shapes come from (desktop ADR 0039). The skill writes
16 only for a document that places such a shape; every other record is the same.

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
from pydantic.json_schema import JsonDict, SkipJsonSchema

FORMAT_NAME = "com.simplediagrams.document"
FORMAT_VERSION = 15
SCHEMA_VERSION = 14
# The first package that may name the libraries a document needs, and its schema.
REQUIRED_LIBRARIES_FORMAT_VERSION = 16
REQUIRED_LIBRARIES_SCHEMA_VERSION = 15

# The app's bounds on the required-libraries list (DiagramRequiredLibrary).
MAX_REQUIRED_LIBRARIES = 64
MAX_REQUIRED_LIBRARY_NAME_SCALARS = 200
MAX_LIBRARY_REVISION = 1_000_000
# Characters that reorder the text around them; a library name may not contain one.
DIRECTION_CONTROLS = frozenset(
    chr(code)
    for code in (
        0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
        0x2066, 0x2067, 0x2068, 0x2069,
    )
)  # fmt: skip

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

ElementKind = Literal["rectangle", "ellipse", "note", "text", "symbol", "path"]
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
    # Added in SimpleDiagrams 5.0.11 without a format change: an earlier app refuses a
    # document that uses one. `requirements()` in sd_spec reports it.
    "circlePlus",
    "cross",
    "halfArrow",
]
# The endings an app before 5.0.11 does not know.
ENDINGS_FROM_5_0_11 = frozenset({"circlePlus", "cross", "halfArrow"})
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
    # In every app version that reads format 15.
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
    format_version: Literal[15, 16] = Field(
        description=(
            "Package format. document.json's schema_version is this minus one. 16 only for "
            "a document that names required libraries."
        )
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
    corner and stay inside the shape; width and height may run past it. With
    position `above` or `below` the label sits just outside the shape and the
    frame's y is ignored.
    """

    frame: TextLayoutFrame
    position: TextPosition
    rotation_degrees: Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False)] | None = None


class TextLayoutFrame(WireModel):
    """A label region in fractions of the owning shape's width and height."""

    x: UnitInterval
    y: UnitInterval
    width: Annotated[float, Field(ge=0.001, le=8, allow_inf_nan=False)]
    height: Annotated[float, Field(ge=0.001, le=8, allow_inf_nan=False)]


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
    """Names one shape in a library: one built into SimpleDiagrams, or a downloaded one.

    A built-in shape is named by the app's own library and item names. A downloaded
    shape is named by its library's and item's published UUIDs; the app puts its
    artwork in place when the document opens with that library installed (desktop
    ADR 0039), and the document lists the library in `required_libraries`. A reference
    the app cannot resolve still opens, but draws a dashed placeholder.
    """

    library_id: Annotated[str, Field(min_length=1)]
    item_id: Annotated[str, Field(min_length=1)]
    asset_version: Annotated[int, Field(gt=0, le=INT64_MAX)]

    @model_validator(mode="after")
    def _check_lengths(self) -> SymbolReference:
        _check_text(self.library_id, field="library_id", max_bytes=MAX_IDENTIFIER_BYTES)
        _check_text(self.item_id, field="item_id", max_bytes=MAX_IDENTIFIER_BYTES)
        return self


class RequiredLibrary(WireModel):
    """One library a document's shapes come from, so a reader who lacks it is told its name.

    The app has no network access, so the document carries the name beside the identifier.
    The entry is advisory: the app never draws, places or refuses anything because of it.
    These rules are the app's own (`DiagramRequiredLibrary`), so a list written here is
    never trimmed when the app reads it.
    """

    library_id: str = Field(
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$",
        max_length=MAX_IDENTIFIER_BYTES,
        description="The identifier the document's references use for the library: its "
        "published UUID. ASCII letters, digits, '.', '-' and '_', beginning and ending with "
        "a letter or digit.",
    )
    display_name: str = Field(
        min_length=1,
        max_length=MAX_REQUIRED_LIBRARY_NAME_SCALARS,
        description="The library's name, shown to a person: not blank, with no line breaks, "
        "control characters or direction controls.",
    )
    minimum_revision: Annotated[int, Field(ge=1, le=MAX_LIBRARY_REVISION)] | None = Field(
        default=None,
        description="The lowest library revision holding every shape used, when known.",
    )

    @model_validator(mode="after")
    def _check_entry(self) -> RequiredLibrary:
        # The identifier's rule is its pattern; a name's length counts Unicode scalars,
        # as Python's len does. Foundation's whitespace set, which the app trims with,
        # still holds U+200B ZERO WIDTH SPACE, so a name of only those is blank there too.
        name = self.display_name
        if (
            all(c.isspace() or c == "\u200b" for c in name)
            or any(
                c in DIRECTION_CONTROLS or unicodedata.category(c) in ("Cc", "Zl", "Zp")
                for c in name
            )
        ):
            raise ValueError(f"required library name {name!r} is not allowed")
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


class Element(WireModel):
    """One entry in a page's `elements` array.

    Exactly three keys, and the app rejects any other. Both shape-data keys
    must be present; in this profile they are always `null` and `[]`.
    """

    content: ElementPresentation
    shape_data_definition_id: None
    shape_data_values: Annotated[list[Any], Field(max_length=0)]

    @model_serializer(mode="wrap")
    def _keep_null_definition(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # The app requires this key to be present even when it is null, so it
        # must survive an exclude_none dump.
        data: dict[str, Any] = handler(self)
        data["shape_data_definition_id"] = None
        return data

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


class Attachment(WireModel):
    """Binds a connector end to an anchor on an element of the same page."""

    element_id: UUIDString
    connection_point_id: Annotated[int, Field(ge=0, le=INT64_MAX)]


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


def _without_default(schema: JsonDict) -> None:
    """Leaves a key the file omits without a schema default, so no reader fills in null."""
    schema.pop("default", None)


class Document(WireModel):
    """The whole of `document.json`: these nine keys, all required, and from schema 15
    `required_libraries` when the document names any."""

    id: UUIDString
    schema_version: Literal[14, 15] = Field(
        description="14 for package format 15, 15 for package format 16. Schema 15 is "
        "written only with required_libraries."
    )
    revision: Annotated[int, Field(ge=0, le=MAX_REVISION)] = Field(
        description="Edit counter. A new document is 0."
    )
    name: str
    selected_page_id: UUIDString
    pages: Annotated[list[Page], Field(min_length=1, max_length=MAX_PAGES)]
    quick_styles: Annotated[list[QuickStyle], Field(max_length=MAX_QUICK_STYLES)]
    embedded_assets: Annotated[list[Any], Field(max_length=0)]
    shape_data_definitions: Annotated[list[Any], Field(max_length=0)]
    # None stands for the key left out, so the schema does not offer null: the app takes a
    # key that is present, even as null, to need schema 15.
    required_libraries: (
        Annotated[list[RequiredLibrary], Field(min_length=1, max_length=MAX_REQUIRED_LIBRARIES)]
        | SkipJsonSchema[None]
    ) = Field(
        default=None,
        description="The downloaded libraries the document's shapes come from. Schema 15 "
        "only, and only when not empty; left out otherwise, never null.",
        json_schema_extra=_without_default,
    )

    @model_validator(mode="after")
    def _check_document(self) -> Document:
        _check_text(self.name, field="document name", max_bytes=MAX_NAME_BYTES)
        # The app refuses the list before schema 15, and the skill writes schema 15 only
        # for a document that has one, so a 15 without it would be a needless format bump.
        if "required_libraries" in self.model_fields_set and self.required_libraries is None:
            # The app takes a key that is present, even as null, to need schema 15.
            raise ValueError("required_libraries is left out, never written as null")
        has_libraries = self.required_libraries is not None
        if has_libraries != (self.schema_version == REQUIRED_LIBRARIES_SCHEMA_VERSION):
            raise ValueError(
                "required_libraries is written exactly when schema_version is "
                f"{REQUIRED_LIBRARIES_SCHEMA_VERSION}"
            )
        named = [library.library_id.lower() for library in self.required_libraries or []]
        if len(named) != len(set(named)):
            raise ValueError("required_libraries names the same library twice")
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
        for page_index, page in enumerate(self.pages):
            where = f"pages[{page_index}]"
            claim(page.core.id, "page")
            for guide in page.content.guides or []:
                claim(guide.id, "guide")

            anchors: dict[str, set[int]] = {}
            for element in page.elements:
                core = element.core
                claim(core.id, "element")
                anchors[core.id.upper()] = {anchor.id for anchor in core.connection_points}
                node_total += len(core.path.nodes) if core.path else 0

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
                    available = anchors.get(attachment.element_id.upper())
                    if available is None:
                        raise ValueError(
                            f"{where}: connection {core.id} {end} names element "
                            f"{attachment.element_id}, which is not on this page"
                        )
                    if attachment.connection_point_id not in available:
                        raise ValueError(
                            f"{where}: connection {core.id} {end} names connection point "
                            f"{attachment.connection_point_id}, which that element does not have"
                        )

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
        if self.selected_page_id.upper() not in {page.core.id.upper() for page in self.pages}:
            raise ValueError("selected_page_id does not name a page in this document")
        return self

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
) -> Element:
    """Wraps one shape in the four records an element needs."""
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
    required_libraries: list[RequiredLibrary] | None = None,
) -> Document:
    """A new document showing its first page, with the app's six Quick Styles.

    A document that names required libraries is written at schema 15 (package 16); any
    other stays at schema 14 (package 15), so it still opens in every app since 5.0.8.
    """
    # The key is left out, not set to None, when there are none: a document given the key
    # holds a list.
    libraries = {"required_libraries": required_libraries} if required_libraries else {}
    return Document(
        id=id,
        schema_version=REQUIRED_LIBRARIES_SCHEMA_VERSION if required_libraries else SCHEMA_VERSION,
        revision=revision, name=name,
        selected_page_id=selected_page_id or pages[0].core.id, pages=pages,
        quick_styles=default_quick_styles() if quick_styles is None else quick_styles,
        embedded_assets=[], shape_data_definitions=[],
        **libraries,
    )



def dump(model: BaseModel) -> dict[str, Any]:
    """Serializes a model the way it belongs in the file.

    Optional keys are left out rather than written as null, except the one
    key the app requires to be present.
    """
    return model.model_dump(mode="json", exclude_none=True)

