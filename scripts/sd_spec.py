"""A flat diagram description and its compiler to the document format.

The document format nests every element four records deep and repeats many
required keys. Writing it by hand is where mistakes happen, so an agent writes
a `DiagramSpec` instead: nodes with a shape, a label and a grid position, and
edges between node keys. `compile_spec` turns that into an exact
`sd_format.Document`, choosing identifiers, sizes, anchors and connector routes.

The spec is a convenience of this skill, not part of the SimpleDiagrams file
format. Its own version is `SPEC_VERSION`.
"""

from __future__ import annotations

import json
import math
import os
import stat
import sys
import unicodedata
import uuid
from itertools import pairwise, product
from pathlib import Path
from typing import Annotated, Literal, NamedTuple, TextIO

import sd_format as wire
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

SPEC_VERSION = 1
CATALOG_PATH = Path(__file__).resolve().parent.parent / "assets" / "built-in-shapes.json"
LIBRARY_PREFIX = "com.simplediagrams.shapeLibrary."
CATALOG_NAME = "com.simplediagrams.skill.built-in-shapes"
CATALOG_VERSION = 1

NATIVE_KINDS = ("rectangle", "ellipse", "note", "text")
# Shapes SimpleDiagrams draws itself from a few stored values (complex shapes). Containers
# and swimlanes hold other shapes.
COMPLEX_KINDS = ("container", "swimlanes", "table", "callout", "lifeline")
HOLDER_KINDS = ("container", "swimlanes")
# What the app itself gives each kind when a person draws one.
DEFAULT_STYLE: dict[str, tuple[str, str, float]] = {
    "rectangle": ("#D8ECFF", "#343A40", 2),
    "ellipse": ("#DDF5E3", "#343A40", 2),
    "note": ("#FFF1A8", "#8A7636", 2),
    "text": ("#00000000", "#00000000", 0),
    "symbol": ("#FFFFFF", "#000000", 1),
    "complex_shape": ("#FFFFFF", "#000000", 1),
}
# The size each kind is placed at when the spec gives none: the app's own, from the Library
# panel's tiles for complex shapes. A table and a lifeline are sized to what they hold.
DEFAULT_SIZE: dict[str, tuple[float, float]] = {
    "rectangle": (140, 70),
    "ellipse": (140, 70),
    "note": (140, 100),
    "container": (320, 200),
    "swimlanes": (600, 328),
    "callout": (180, 80),
}
# A lifeline's width, from the UML library's tiles, and its height with no messages.
LIFELINE_WIDTH = {"box": 120.0, "actor": 100.0}
LIFELINE_HEIGHT = 320.0
# A new callout's tail: its tip from the bubble's centre, as the app places one.
CALLOUT_TAIL = (-40.0, 70.0)

# How the builder lays out complex shapes, in points.
HOLDER_PADDING = 20  # between a fitted container's or lane's sides and what it holds
CONTAINER_TITLE_BAND = 32  # a container's title band, which its members sit below
CORNER_TAG_HEIGHT = 28  # a one-line corner tag
FIRST_MESSAGE_GAP = 30  # from the lowest head to the first message
MESSAGE_STEP = 40  # between one message and the next
SELF_MESSAGE_DROP = 20  # how much lower a message to its own lifeline returns
SELF_LOOP_WIDTH = 30  # how far right the app draws that loop
LIFELINE_END_MARGIN = 30  # line kept below the last message (the app keeps at least 16)
DESTROYED_LINE_MARGIN = 20  # line kept below a destroyed lifeline's last message
DESTROYED_FRAGMENT_CLEARANCE = 4  # between a fragment's bottom and a destroy mark below it
FRAGMENT_SIDE = 30  # how far a fragment reaches past the lifelines its messages join
FRAGMENT_NEST_STEP = 12  # and how much further for each fragment inside it
FRAGMENT_TAG_GAP = 16  # between a fragment's tag and its first message
FRAGMENT_END_ROOM = 12  # below a fragment's last message, per fragment ending there
DIVIDER_ROOM = 20  # added before a message that a divider precedes
# Mid-side anchors of the eight every shape carries.
SIDE_ANCHOR = {"left": 0, "right": 1, "top": 2, "bottom": 3}
SIDE_VECTOR = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}
OPPOSITE_SIDE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
# The app's standard eight anchors, as fractions of the frame, for a shape that names none.
STANDARD_POINTS = {anchor.id: (anchor.x, anchor.y) for anchor in wire.standard_connection_points()}

# Rough advance of the app's standard font, as a fraction of the font size.
AVERAGE_GLYPH_WIDTH = 0.56
LINE_HEIGHT = 1.3
CHANNEL_SPACING = 16
CHANNEL_MARGIN = 10
STUB = 24
# A label above or below a shape may be centred in a region up to this many times the
# shape's width, the most the app allows, with this much room beside its text.
MAX_LABEL_REGION = 8.0
LABEL_ROOM = 8

# Bounds on a spec. They keep a build quick, since some layout checks compare
# every pair of shapes or connectors, and are far above what one readable page
# holds; a subject that needs more belongs on several pages.
MAX_SPEC_BYTES = 2 * 1024 * 1024
MAX_SPEC_PAGES = 30
MAX_NODES_PER_PAGE = 300
MAX_EDGES_PER_PAGE = 400
MAX_LABEL_CHARACTERS = 2_000
MAX_NAME_CHARACTERS = 200

Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
# Generous for any real diagram, and far inside what the document format allows.
PagePosition = Annotated[float, Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)]
GridPosition = Annotated[float, Field(ge=-10_000, le=10_000, allow_inf_nan=False)]
Size = Annotated[float, Field(ge=1, le=100_000, allow_inf_nan=False)]
Pitch = Annotated[float, Field(ge=10, le=10_000, allow_inf_nan=False)]
Side = Literal["left", "right", "top", "bottom"]
PointId = Annotated[int, Field(ge=0, le=wire.INT64_MAX)]


def _check_plain_text(value: str, *, allow_newlines: bool) -> str:
    """Refuses control characters, which no label needs and XML cannot carry."""
    for character in value:
        if character == "\n" and allow_newlines:
            continue
        if unicodedata.category(character) == "Cc" or character in "\ufffe\uffff":
            raise ValueError(
                f"contains the control character U+{ord(character):04X}; "
                + ("use \\n for a line break and no other control characters" if allow_newlines else "remove it")
            )
    return value


Label = Annotated[
    str,
    StringConstraints(max_length=MAX_LABEL_CHARACTERS),
    AfterValidator(lambda value: _check_plain_text(value, allow_newlines=True)),
]
Name = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_NAME_CHARACTERS),
    AfterValidator(lambda value: _check_plain_text(value, allow_newlines=False)),
]
# A native kind or '<library>/<item>': a library ID is at most 256 characters and an item
# name at most 200, so this is generous.
Selector = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
    AfterValidator(lambda value: _check_plain_text(value, allow_newlines=False)),
]


class SpecModel(BaseModel):
    """Base for the authoring spec: closed, so a misspelt key is an error."""

    model_config = ConfigDict(extra="forbid")


class GridLayout(SpecModel):
    """Turns `col` and `row` into page coordinates.

    A node's centre sits at `origin + (col * column_pitch, row * row_pitch)`.
    Fractional columns and rows are allowed for staggered layouts.
    """

    origin_x: PagePosition = Field(default=200, description="Page x of column 0's centre line.")
    origin_y: PagePosition = Field(default=160, description="Page y of row 0's centre line.")
    column_pitch: Pitch = Field(default=240, description="Distance between column centres.")
    row_pitch: Pitch = Field(default=160, description="Distance between row centres.")


class PagePoint(SpecModel):
    """A point on the page."""

    x: PagePosition
    y: PagePosition


class LaneSpec(SpecModel):
    """One lane of a swimlanes node: its title and the nodes it holds."""

    title: Label = ""
    members: list[Key] = Field(
        default=[], max_length=MAX_NODES_PER_PAGE,
        description="Keys of the nodes in this lane. Each lies wholly inside the swimlanes, "
        "with its centre in this lane.",
    )
    size: Size | None = Field(
        default=None,
        description="The lane's thickness in points, only for swimlanes given a position; "
        "lanes of fitted swimlanes are fitted to their members.",
    )


class DividerSpec(SpecModel):
    """A dashed line across a fragment, between two of its operands, as for UML's alt."""

    before: Key = Field(description="Key of the message the line goes just above.")
    label: Label = Field(default="", description="A guard such as [else], shown on the line.")


# The node fields that belong to some kinds only.
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "members": ("container",),
    "title_style": ("container",),
    "messages": ("container",),
    "dividers": ("container",),
    "direction": ("swimlanes",),
    "lanes": ("swimlanes",),
    "cells": ("table",),
    "header_row": ("table",),
    "column_widths": ("table",),
    "row_heights": ("table",),
    "tail_to": ("callout",),
    "tail_point": ("callout",),
    "tail_at": ("callout",),
    "head": ("lifeline",),
    "ends_in_destroy_mark": ("lifeline",),
    "hand_drawn": COMPLEX_KINDS,
}


class NodeSpec(SpecModel):
    """One shape on the page.

    Give either `col` and `row`, or `x` and `y`. Both name the node's centre,
    so nodes of different sizes still line up along shared centre lines. A
    container or swimlanes may be given neither, and is then fitted around the
    nodes it holds.
    """

    key: Key = Field(description="Your own name for this node, unique on the page.")
    shape: Selector = Field(
        description=(
            "rectangle, ellipse, note or text for a plain drawn shape; container, "
            "swimlanes, table, callout or lifeline for a shape SimpleDiagrams draws "
            "itself; or '<library>/<item>' for a shape from a library packaged with "
            "SimpleDiagrams, for example 'basic/Cylinder'. Use a selector returned by "
            "find_shapes.py, which searches assets/built-in-shapes.json."
        )
    )
    label: Label = ""
    col: GridPosition | None = None
    row: GridPosition | None = None
    x: PagePosition | None = None
    y: PagePosition | None = None
    width: Size | None = None
    height: Size | None = None
    scale: float = Field(
        default=1, ge=0.1, le=100, allow_inf_nan=False,
        description="Multiplies a library shape's natural size, keeping its proportions.",
    )
    label_position: wire.TextPosition | None = Field(
        default=None,
        description=(
            "Use 'below' or 'above' for icons whose artwork would hide a label. A label wider "
            "than its shape is centred on it, as wide as it needs up to eight times the shape. "
            "Leave it out to use the library's own placement, such as below a BPMN event; "
            "a shape whose library says nothing puts its label in the middle."
        ),
    )
    fill: wire.Color | None = None
    stroke: wire.Color | None = None
    line_width: float | None = Field(default=None, ge=0, le=10_000, allow_inf_nan=False)
    text_color: wire.Color | None = None
    font_size: float = Field(default=15, ge=1, le=720, allow_inf_nan=False)
    bold: bool = False
    rotation: float = Field(default=0, ge=-360, le=360, allow_inf_nan=False)
    flip_horizontal: bool = Field(
        default=False,
        description=(
            "Mirrors the shape's artwork left to right, as a flip in the app does. Its "
            "connection points move with the artwork and keep their ids; its label stays "
            "readable."
        ),
    )
    flip_vertical: bool = Field(
        default=False, description="Mirrors the shape's artwork top to bottom, as flip_horizontal does across."
    )
    align: Literal["leading", "center", "trailing"] | None = Field(
        default=None,
        description="How the label's lines are aligned, and a table's cells below its header "
        "row. A container's title starts at its leading edge unless this says otherwise; "
        "everything else is centred.",
    )
    hand_drawn: bool | None = Field(
        default=None,
        description="Complex shapes are drawn with gently uneven lines; false draws them exactly.",
    )
    members: list[Key] | None = Field(
        default=None, max_length=MAX_NODES_PER_PAGE,
        description="container: keys of the nodes it holds, each lying wholly inside it. "
        "Without a position the container is fitted around them.",
    )
    title_style: Literal["band", "corner_tag"] | None = Field(
        default=None,
        description="container: 'band', the title across its top (the default), or "
        "'corner_tag', a UML frame's name tag in its top-left corner.",
    )
    messages: list[Key] | None = Field(
        default=None, max_length=MAX_EDGES_PER_PAGE,
        description="container: keys of the messages a UML fragment (alt, loop, opt) encloses; "
        "it is fitted from the first to the last of them, across the lifelines they join.",
    )
    dividers: list[DividerSpec] | None = Field(
        default=None, max_length=MAX_EDGES_PER_PAGE,
        description="container with messages: dashed lines across it between operands, as UML's alt draws them.",
    )
    direction: Literal["horizontal", "vertical"] | None = Field(
        default=None,
        description="swimlanes: 'horizontal' lanes run across the page as rows (the default); "
        "'vertical' lanes run down it as columns.",
    )
    lanes: list[LaneSpec] | None = Field(
        default=None, min_length=1, max_length=wire.MAX_LANES,
        description="swimlanes: the lanes in order, top to bottom or left to right.",
    )
    cells: list[list[Label]] | None = Field(
        default=None, min_length=1, max_length=wire.MAX_TABLE_ROWS,
        description="table: the text of each cell, row by row; every row has the same number of cells.",
    )
    header_row: bool | None = Field(
        default=None, description="table: whether the first row is drawn as a header (the default)."
    )
    column_widths: list[Size] | None = Field(
        default=None, max_length=wire.MAX_TABLE_COLUMNS,
        description="table: each column's width; by default each is sized to its text.",
    )
    row_heights: list[Size] | None = Field(
        default=None, max_length=wire.MAX_TABLE_ROWS,
        description="table: each row's height; by default each is sized to its text.",
    )
    tail_to: Key | None = Field(
        default=None,
        description="callout: key of the node its tail is locked to, at its connection point "
        "nearest the callout unless tail_point names one.",
    )
    tail_point: PointId | None = Field(
        default=None, description="callout: the id of tail_to's connection point to lock the tail to."
    )
    tail_at: PagePoint | None = Field(
        default=None, description="callout: the page point a free tail aims at."
    )
    head: Literal["box", "actor"] | None = Field(
        default=None,
        description="lifeline: 'box', a participant's name in a box (the default), or 'actor', "
        "a stick figure with the name below it.",
    )
    ends_in_destroy_mark: bool | None = Field(
        default=None,
        description="lifeline: whether its line ends in UML's destroy mark, an X, just below "
        "its last message.",
    )

    @model_validator(mode="after")
    def _check_position(self) -> NodeSpec:
        grid = self.col is not None and self.row is not None
        absolute = self.x is not None and self.y is not None
        partial = (self.col is None) != (self.row is None) or (self.x is None) != (self.y is None)
        if partial or (grid and absolute) or not (grid or absolute or self.fitted):
            raise ValueError(
                f"node '{self.key}' needs either col and row, or x and y"
                + (
                    ", or neither to fit it around its members"
                    if self.shape in HOLDER_KINDS
                    else ""
                )
            )
        if self.shape == "text" and (self.flip_horizontal or self.flip_vertical):
            raise ValueError(f"node '{self.key}' is text, which has no artwork to flip; remove its flip")
        for field, kinds in KIND_FIELDS.items():
            if getattr(self, field) is not None and self.shape not in kinds:
                raise ValueError(
                    f"node '{self.key}': {field} is for a {' or '.join(kinds)} node, and this is "
                    f"'{self.shape}'"
                )
        if self.shape in COMPLEX_KINDS:
            self._check_complex()
        return self

    @property
    def fitted(self) -> bool:
        """Whether this container or swimlanes is fitted around what it holds: it has no position."""
        return self.shape in HOLDER_KINDS and None in (self.col, self.row) and None in (self.x, self.y)

    def _check_complex(self) -> None:
        """The rules a complex shape's own fields follow."""
        where = f"node '{self.key}' ({self.shape})"
        if self.label_position is not None:
            raise ValueError(f"{where}: its text sits in a fixed place; remove label_position")
        if self.rotation % 360:
            raise ValueError(f"{where}: the builder does not turn complex shapes; remove rotation")
        if self.shape != "callout" and (self.flip_horizontal or self.flip_vertical):
            raise ValueError(f"{where} cannot be flipped; only a callout can")
        if self.fitted and (self.width is not None or self.height is not None):
            raise ValueError(
                f"{where} is fitted around what it holds, so it takes no width or height; give it "
                "a position too, to place and size it yourself"
            )
        if self.shape == "container":
            if self.fitted and not (self.members or self.messages):
                raise ValueError(f"{where} needs members or messages to fit around, or a position")
            if self.messages and not self.fitted:
                raise ValueError(f"{where} encloses messages, so the builder places it; remove its position")
            if self.dividers and not self.messages:
                raise ValueError(f"{where}: dividers go across a fragment, which needs messages")
        if self.shape == "swimlanes":
            if not self.lanes:
                raise ValueError(f"{where} needs lanes")
            if self.fitted and any(lane.size is not None for lane in self.lanes):
                raise ValueError(f"{where}: a lane's size is for swimlanes given a position; fitted lanes fit their members")
        if self.shape == "table":
            if not self.cells:
                raise ValueError(f"{where} needs cells, its text row by row")
            if self.label:
                raise ValueError(f"{where}: a table's text is all in its cells; remove label")
            columns = len(self.cells[0])
            if columns == 0 or any(len(row) != columns for row in self.cells):
                raise ValueError(f"{where}: every row of cells needs the same number of cells, at least one")
            if columns > wire.MAX_TABLE_COLUMNS or columns * len(self.cells) > wire.MAX_TABLE_CELLS:
                raise ValueError(
                    f"{where}: a table has at most {wire.MAX_TABLE_COLUMNS} columns and "
                    f"{wire.MAX_TABLE_CELLS} cells"
                )
            if self.column_widths is not None and len(self.column_widths) != columns:
                raise ValueError(f"{where}: column_widths needs one width per column, {columns}")
            if self.row_heights is not None and len(self.row_heights) != len(self.cells):
                raise ValueError(f"{where}: row_heights needs one height per row, {len(self.cells)}")
        if self.shape == "callout":
            if self.tail_point is not None and self.tail_to is None:
                raise ValueError(f"{where}: tail_point names a point of the node in tail_to")
            if self.tail_to is not None and self.tail_at is not None:
                raise ValueError(f"{where}: give tail_to or tail_at, not both")
            if self.tail_to == self.key:
                raise ValueError(f"{where}: a callout's tail cannot lock to the callout itself")


class EdgeSpec(SpecModel):
    """A connector between two nodes. Between two lifelines it is a message."""

    key: Key | None = Field(
        default=None,
        description="Your own name for this edge, unique among the page's edges, for a "
        "fragment's messages or dividers to name it.",
    )
    source: Key = Field(description="Key of the node the connector leaves.")
    target: Key = Field(
        description="Key of the node the connector arrives at. It may be the source node when "
        "source_point and target_point name two different points of it; the connector is then "
        "routed around the shape."
    )
    label: Label = ""
    route: Literal["orthogonal", "straight", "curved"] = Field(
        default="orthogonal",
        description=(
            "orthogonal: horizontal and vertical runs only. straight: one direct line. "
            "curved: one direct line with a gentle bow."
        ),
    )
    source_side: Side | None = Field(
        default=None,
        description="The side the connector leaves from, at the shape's anchor on that side "
        "(its middle on most shapes). Chosen "
        "automatically when neither this nor source_point is given.",
    )
    target_side: Side | None = Field(
        default=None,
        description="The side the connector arrives at, at the shape's anchor on that side "
        "(its middle on most shapes). Chosen "
        "automatically when neither this nor target_point is given.",
    )
    source_point: PointId | None = Field(
        default=None,
        description="The id of the source shape's connection point to leave from, as "
        "find_shapes.py lists it, such as a component's lead end. Instead of source_side.",
    )
    target_point: PointId | None = Field(
        default=None,
        description="The id of the target shape's connection point to arrive at. Instead of "
        "target_side.",
    )
    start_ending: wire.Ending = "none"
    end_ending: wire.Ending = "arrow"
    pattern: wire.StrokePattern = "solid"
    stroke: wire.Color = "#495057"
    line_width: float = Field(default=2, ge=0, le=10_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _one_way_to_attach(self) -> EdgeSpec:
        if self.source_side is not None and self.source_point is not None:
            raise ValueError("give source_side or source_point, not both")
        if self.target_side is not None and self.target_point is not None:
            raise ValueError("give target_side or target_point, not both")
        return self


class PageSpec(SpecModel):
    """One page of the diagram."""

    name: Name = "Page 1"
    grid: GridLayout = GridLayout()
    background: wire.Color | None = None
    nodes: list[NodeSpec] = Field(min_length=1, max_length=MAX_NODES_PER_PAGE)
    edges: list[EdgeSpec] = Field(default=[], max_length=MAX_EDGES_PER_PAGE)

    @model_validator(mode="after")
    def _check_keys(self) -> PageSpec:
        keys = [node.key for node in self.nodes]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"page '{self.name}' repeats node keys: {', '.join(duplicates)}")
        edge_keys = [edge.key for edge in self.edges if edge.key is not None]
        duplicates = sorted({key for key in edge_keys if edge_keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"page '{self.name}' repeats edge keys: {', '.join(duplicates)}")
        shapes = {node.key: node.shape for node in self.nodes}
        for edge in self.edges:
            for end in (edge.source, edge.target):
                if end not in shapes:
                    raise ValueError(f"page '{self.name}' has an edge to unknown node '{end}'")
            # A message from a lifeline to itself is a call to itself, drawn as a loop.
            if edge.source == edge.target and shapes[edge.source] != "lifeline" and (
                None in (edge.source_point, edge.target_point) or edge.source_point == edge.target_point
            ):
                raise ValueError(
                    f"page '{self.name}' has an edge from '{edge.source}' to itself; an edge "
                    "within one node must name two different points with source_point and "
                    "target_point"
                )
        known_edges = set(edge_keys)
        for node in self.nodes:
            named = [*(node.members or []), *(member for lane in node.lanes or [] for member in lane.members)]
            if node.tail_to is not None:
                named.append(node.tail_to)
            for key in named:
                if key not in shapes:
                    raise ValueError(f"page '{self.name}': node '{node.key}' names unknown node '{key}'")
                if key == node.key and node.shape in HOLDER_KINDS:
                    raise ValueError(f"page '{self.name}': node '{node.key}' cannot hold itself")
            for key in [*(node.messages or []), *(divider.before for divider in node.dividers or [])]:
                if key not in known_edges:
                    raise ValueError(f"page '{self.name}': node '{node.key}' names unknown edge '{key}'")
        return self


class DiagramSpec(SpecModel):
    """A whole diagram, written by an agent and compiled to a document."""

    spec_version: Literal[1] = SPEC_VERSION
    name: Name = Field(description="The document's name.")
    id: wire.UUIDString | None = Field(
        default=None,
        description="Document id. Omit for a new diagram; a fresh one is generated.",
    )
    pages: list[PageSpec] = Field(min_length=1, max_length=MAX_SPEC_PAGES)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class CatalogShape(BaseModel):
    """One shape from a library packaged with SimpleDiagrams, with its exact placement
    reference: the app's own library ID, item ID and asset version."""

    model_config = ConfigDict(frozen=True)

    library_id: str
    library_short_name: str
    library_display_name: str
    asset_version: int
    item_id: str
    display_name: str
    default_width: float
    default_height: float
    slug: str = ""
    description: str = ""
    keywords: tuple[str, ...] = ()
    # (id, x, y) for each anchor; None means the standard eight every shape has. An empty
    # tuple is a shape connectors may not attach to, such as a BPMN task mark.
    connection_points: tuple[tuple[int, float, float], ...] | None = None
    # (x, y, width, height) as fractions of the frame; None means the app's own inset. A shipped
    # library may centre a name wider than its shape (x < 0), which the compiler writes as is.
    text_region: tuple[float, float, float, float] | None = None
    # The library's label position; None means the middle unless the spec says otherwise.
    text_position: wire.TextPosition | None = None
    # How the app lets a person resize the shape. "width_only" means its height is its
    # thickness, as on a fork / join bar, and the compiler keeps it. The maintainers
    # regenerate the bundled catalogue from the app's own library bundle, and that step
    # refuses any other rule until the compiler is taught it.
    resizing: Literal["free", "width_only"] = "free"

    @property
    def selector(self) -> str:
        """`<short name>/<item>`, the name a spec gives the shape."""
        return f"{self.library_short_name}/{self.item_id}"


class Catalog:
    """The shapes packaged with SimpleDiagrams, read from the list bundled with the skill.

    The list is the skill's only source of library shapes: nothing is fetched, and a
    shape it does not hold cannot be placed.
    """

    def __init__(self, shapes: list[CatalogShape], source_app_version: str) -> None:
        self.shapes = shapes
        self.source_app_version = source_app_version
        self._by_reference = {(shape.library_id, shape.item_id): shape for shape in shapes}
        self._short_names = {shape.library_short_name.lower(): shape.library_id for shape in shapes}
        self._library_ids = {shape.library_id for shape in shapes}

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> Catalog:
        """Read the bundled list of packaged shapes."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("catalog"), data.get("catalog_version")) != (CATALOG_NAME, CATALOG_VERSION):
            raise ValueError(f"{path} is not shape catalogue version {CATALOG_VERSION}")
        shapes = [
            CatalogShape(
                library_id=library["library_id"],
                library_short_name=library["short_name"],
                library_display_name=library["display_name"],
                asset_version=library["asset_version"],
                item_id=item["item_id"],
                display_name=item["display_name"],
                default_width=item["default_width"],
                default_height=item["default_height"],
                slug=item.get("slug", item["item_id"]),
                description=item.get("description", ""),
                keywords=tuple(item.get("keywords", [])),
                connection_points=None
                if item.get("connection_points") is None
                else tuple((point["id"], point["x"], point["y"]) for point in item["connection_points"]),
                text_region=None
                if item.get("text_region") is None
                else tuple(item["text_region"][key] for key in ("x", "y", "width", "height")),
                text_position=item.get("text_position"),
                resizing=item.get("resizing", "free"),
            )
            for library in data["libraries"]
            for item in library["shapes"]
        ]
        return cls(shapes, data["source_app_version"])

    def find_library(self, library: str) -> str | None:
        """The library a selector names, by full library id or short name."""
        if library in self._library_ids:
            return library
        return self._short_names.get(library.lower())

    def resolve(self, library: str, item: str) -> CatalogShape | None:
        """Finds a shape by full library id or short name. Item ids are case sensitive."""
        library_id = self.find_library(library)
        if library_id is None:
            return None
        return self._by_reference.get((library_id, item))

    def find_reference(self, library_id: str, item_id: str, asset_version: int) -> CatalogShape | None:
        """The packaged shape a reference names, at exactly its asset version."""
        shape = self._by_reference.get((library_id, item_id))
        return shape if shape and shape.asset_version == asset_version else None

    def suggestions(self, library: str, item: str) -> list[str]:
        """Close names to offer when a shape is not found, matched on its item ID."""
        wanted = item.lower()
        found = [
            shape.selector
            for shape in self.shapes
            if wanted in shape.item_id.lower() or shape.item_id.lower() in wanted
        ]
        return sorted(found)[:8]


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class SpecError(ValueError):
    """A spec that is well formed but cannot be turned into a document."""


class NotRegularFile(ValueError):
    """A path that names a pipe, device or folder where a file was expected."""


class FileTooLarge(ValueError):
    """A file holding more bytes than the reader allows."""


def read_limited(path: Path, limit: int) -> bytes:
    """Reads a regular file of at most `limit` bytes, counting the bytes actually read.

    The size a file reports can be wrong (a pipe reports 0) or grow before it is read,
    so the read itself is bounded. Where the system allows, the file is opened without
    waiting, so a pipe with no writer is refused at once instead of stalling.

    Raises:
        OSError: The file cannot be opened or read.
        NotRegularFile: The path is not a regular file, such as a folder or a pipe.
        FileTooLarge: It holds more than `limit` bytes.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NotRegularFile(f"{path} is not a regular file")
        source = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise FileTooLarge(f"{path} is larger than {limit} bytes")
    return data


# Characters that reorder the text around them; a diagnostic prints each as an escape.
DIRECTION_CONTROLS = frozenset(
    chr(code)
    for code in (
        0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
        0x2066, 0x2067, 0x2068, 0x2069,
    )
)  # fmt: skip


def terminal_safe(text: str) -> str:
    """`text` with control characters other than line breaks, and direction controls,
    written as `\\uXXXX` escapes.

    Values from a spec or a file name reach the terminal in diagnostics; an
    escape sequence among them could drive the terminal, and a direction control could
    reorder the line. JSON output stays valid: inside a string the escape means the same
    character, and JSON already escapes control characters itself.
    """
    return "".join(
        f"\\u{ord(character):04x}"
        if (unicodedata.category(character) == "Cc" and character != "\n")
        or character in DIRECTION_CONTROLS
        else character
        for character in text
    )


def echo(text: str, *, file: TextIO | None = None) -> None:
    """Prints one diagnostic, made safe for the terminal by `terminal_safe`."""
    print(terminal_safe(text), file=file or sys.stdout)


def load_spec(path: Path) -> DiagramSpec:
    """Reads a spec file, refusing an oversized one before parsing it.

    Raises:
        SpecError: The file is missing, not a regular file, too large, or not a valid spec.
    """
    try:
        data = read_limited(path, MAX_SPEC_BYTES)
    except OSError as failure:
        raise SpecError(f"Cannot read the spec {path}: {failure.strerror}") from failure
    except NotRegularFile as failure:
        raise SpecError(f"The spec {path} is not a regular file.") from failure
    except FileTooLarge as failure:
        raise SpecError(f"The spec {path} is over the limit of {MAX_SPEC_BYTES} bytes.") from failure
    try:
        return DiagramSpec.model_validate_json(data)
    except ValidationError as failure:
        lines = [
            f"spec: {'.'.join(str(part) for part in detail['loc']) or '(top level)'}: {detail['msg']}"
            for detail in failure.errors()
        ]
        raise SpecError("\n".join(lines)) from failure


def estimate_text_size(text: str, font_size: float, bold: bool = False) -> tuple[float, float]:
    """A rough width and height for unwrapped text. It errs slightly wide."""
    lines = text.split("\n") or [""]
    factor = AVERAGE_GLYPH_WIDTH * (1.08 if bold else 1)
    width = max(len(line) for line in lines) * font_size * factor
    return width, len(lines) * font_size * LINE_HEIGHT


def _new_id(namespace: uuid.UUID, name: str) -> str:
    return str(uuid.uuid5(namespace, name)).upper()


def _node_id(document_id: str, page_index: int, key: str) -> str:
    """The element id a node gets: the same for a given document id, so a rebuild keeps it,
    and so `lint` can name a shape by the key the spec gave it."""
    return _new_id(uuid.UUID(document_id), f"page:{page_index}:node:{key}")


def _snap(value: float) -> float:
    return float(round(value * 1000) / 1000)


class _Anchor(NamedTuple):
    """A connection point of a placed node: its id, where it is on the page, and the sides
    a route may leave it by, which are those of the frame edges nearest to it."""

    id: int
    x: float
    y: float
    exits: tuple[str, ...]


class _Placed:
    """A node after sizing, with the geometry edges are routed against."""

    def __init__(
        self, spec: NodeSpec, element_id: str, x: float, y: float, w: float, h: float,
        points: dict[int, tuple[float, float]] | None = None, display_name: str = "",
    ) -> None:
        self.spec = spec
        self.element_id = element_id
        self.x, self.y, self.w, self.h = x, y, w, h
        # Where each anchor is drawn, as fractions of the frame: the library's for a library
        # shape, else the app's standard eight, mirrored as the app mirrors a flipped shape's
        # points with its artwork (in the shape's own axes, before any turn). Connectors
        # attach only to these. The element still stores the unmirrored positions.
        self.points = {
            point_id: (1 - x if spec.flip_horizontal else x, 1 - y if spec.flip_vertical else y)
            for point_id, (x, y) in (STANDARD_POINTS if points is None else points).items()
        }
        self.display_name = display_name or spec.key

    def anchor(self, point_id: int) -> _Anchor:
        """Where a connection point is on the page, and the sides a route may leave it by."""
        fx, fy = self.points[point_id]
        distances = {
            "left": fx * self.w, "right": (1 - fx) * self.w,
            "top": fy * self.h, "bottom": (1 - fy) * self.h,
        }
        nearest = min(distances.values())
        exits = tuple(side for side, distance in distances.items() if distance - nearest < 0.5)
        return _Anchor(point_id, self.x + fx * self.w, self.y + fy * self.h, exits)

    def side_anchor(self, side: str) -> _Anchor | None:
        """The anchor the app numbers for a side (0 left, 1 right, 2 top, 3 bottom), leaving
        by that side, when the shape has it and it lies on that side. A flip draws the
        anchor numbered for the opposite side there."""
        flipped = self.spec.flip_horizontal if side in ("left", "right") else self.spec.flip_vertical
        point_id = SIDE_ANCHOR[OPPOSITE_SIDE[side] if flipped else side]
        if point_id not in self.points:
            return None
        anchor = self.anchor(point_id)
        return anchor._replace(exits=(side,)) if side in anchor.exits else None

    @property
    def point_ids(self) -> str:
        """The shape's anchor ids, for a message saying which can be named."""
        return ", ".join(str(point_id) for point_id in sorted(self.points))

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def rect(self) -> wire.Rect:
        return wire.Rect(x=self.x, y=self.y, width=float(self.w), height=float(self.h))


def _node_size(node: NodeSpec, catalog_shape: CatalogShape | None) -> tuple[float, float]:
    if catalog_shape is not None and catalog_shape.resizing == "width_only":
        # The height is the shape's thickness, which the app keeps whatever a person does, so
        # width and scale change only its length. Its weight comes from the line width.
        length = node.width or catalog_shape.default_width * node.scale
        return (float(length), float(catalog_shape.default_height))
    if catalog_shape is not None:
        natural = (catalog_shape.default_width * node.scale, catalog_shape.default_height * node.scale)
    elif node.shape == "text":
        text_width, text_height = estimate_text_size(node.label or " ", node.font_size, node.bold)
        natural = (math.ceil(text_width + 24), math.ceil(text_height + 18))
    else:
        natural = DEFAULT_SIZE[node.shape]
    return (float(node.width or natural[0]), float(node.height or natural[1]))


def outside_label_rect(frame: wire.Rect, layout: wire.TextLayout, text: wire.TextContent) -> wire.Rect | None:
    """Where a label placed above or below its shape is drawn, approximately."""
    if layout.position not in ("above", "below") or not text.string:
        return None
    region_width = max(1.0, layout.frame.width * frame.width)
    width, line_height = estimate_text_size(
        text.string.replace("\n", " "), text.base_style.font_size, text.base_style.weight == "bold"
    )
    lines = max(text.string.count("\n") + 1, math.ceil(width / region_width))
    height = lines * line_height
    top = frame.y - height if layout.position == "above" else frame.y + frame.height
    return wire.Rect(x=frame.x + layout.frame.x * frame.width, y=top, width=region_width, height=height)


def _candidate_sides(a: _Placed, b: _Placed) -> list[tuple[str, str]]:
    """Side pairs worth trying, best first.

    The first pair leaves toward the target along whichever axis has the
    clearer gap. The rest are the other axis and the two single-corner routes,
    used only when the first would run through another shape.
    """
    gap_x = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
    gap_y = max(b.y - (a.y + a.h), a.y - (b.y + b.h))
    horizontal_first = gap_x >= gap_y if (gap_x > 0 or gap_y > 0) else abs(b.cx - a.cx) >= abs(b.cy - a.cy)
    horizontal = ("right", "left") if b.cx >= a.cx else ("left", "right")
    vertical = ("bottom", "top") if b.cy >= a.cy else ("top", "bottom")
    first, second = (horizontal, vertical) if horizontal_first else (vertical, horizontal)
    return [first, second, (first[0], second[1]), (second[0], first[1])]


def _named_point(end: _Placed, point_id: int, other: _Placed) -> list[_Anchor]:
    """A named anchor, once for each side it may leave by, the side facing `other` first."""
    anchor = end.anchor(point_id)
    toward = (other.cx - anchor.x, other.cy - anchor.y)

    def facing(side: str) -> float:
        return -(SIDE_VECTOR[side][0] * toward[0] + SIDE_VECTOR[side][1] * toward[1])

    return [anchor._replace(exits=(side,)) for side in sorted(anchor.exits, key=facing)]


def _choose_route(
    edge: EdgeSpec, source: _Placed, target: _Placed, obstacles: list[wire.Rect],
    taken: list[tuple[float, float, float, float]],
) -> tuple[_Anchor, _Anchor, _Route]:
    """Picks the anchors and the route between them that keep off everything else.

    A loop from a shape to itself, among its options that cross the fewest shapes, also
    keeps the one that runs along fewest of the `taken` segments of connectors already
    routed, so it is not read as joining a line it lies on.

    A named point is used as given. A named side, or a side chosen automatically, is the
    anchor the app numbers for that side, and only a side the shape has an anchor on is
    tried. The best side pairs for the shapes' placement are tried first. When none of those
    is available, or each crosses a shape or label, an orthogonal route searches every pair,
    keeping the one crossing fewest; a straight or curved line, which the orthogonal score
    does not describe, first takes any fixed side with the best other side, as it always
    has. Each returned anchor carries the one side it leaves by.
    """
    named_source = (
        _named_point(source, edge.source_point, target) if edge.source_point is not None else None
    )
    named_target = (
        _named_point(target, edge.target_point, source) if edge.target_point is not None else None
    )
    preferred = _candidate_sides(source, target)
    fallback = (edge.source_side or preferred[0][0], edge.target_side or preferred[0][1])
    everything = [fallback] + [pair for pair in product(SIDE_ANCHOR, SIDE_ANCHOR) if pair != fallback]
    tried: list[tuple[_Anchor, _Anchor]] = []
    passes = (preferred, everything) if edge.route == "orthogonal" else (preferred, [fallback], everything)
    best: tuple[tuple[int, int], _Anchor, _Anchor, _Route] | None = None
    for pairs in passes:
        candidates: list[tuple[_Anchor, _Anchor]] = []
        for side_a, side_b in pairs:
            if edge.source_side not in (None, side_a) or edge.target_side not in (None, side_b):
                continue
            side_source, side_target = source.side_anchor(side_a), target.side_anchor(side_b)
            starts = named_source if named_source is not None else [side_source] if side_source else []
            ends = named_target if named_target is not None else [side_target] if side_target else []
            candidates += [(a, b) for a in starts for b in ends if (a, b) not in candidates + tried]
        tried += candidates
        for start, end in candidates:
            route = _orthogonal((start.x, start.y), start.exits[0], (end.x, end.y), end.exits[0])
            for option in (_around(route, source) if source is target else []) or [route]:
                segments = [(p[0], p[1], q[0], q[1]) for p, q in pairwise(option.points)]
                hits = sum(
                    any(_segment_hits_rect(segment, obstacle) for segment in segments)
                    for obstacle in [*obstacles, source.rect, target.rect]
                )
                shared = (
                    sum(any(_collinear_overlap(segment, run) for run in taken) for segment in segments)
                    if source is target
                    else 0
                )
                if best is None or (hits, shared) < best[0]:
                    best = ((hits, shared), start, end, option)
            if best is not None and best[0] == (0, 0):
                break
        # A later pass is tried only when this one found nothing, or, for an orthogonal
        # route, nothing clear of every shape; the score describes orthogonal routes only.
        if best is not None and (best[0] == (0, 0) or edge.route != "orthogonal"):
            break
    assert best is not None, "the caller checks that each end has an anchor to use"
    return best[1], best[2], best[3]


def _around(route: _Route, shape: _Placed) -> list[_Route]:
    """For a connector from a shape to itself, the route with its free run moved just
    outside the shape, once on each side; empty when the run is already outside it.

    The run is otherwise midway between the two ends, which on one shape is through its
    middle. The caller keeps whichever of the two crosses least.
    """
    if route.channel is None:
        return []
    axis = route.channel[0]
    low, high = (shape.x, shape.x + shape.w) if axis == "x" else (shape.y, shape.y + shape.h)
    if not low < route.channel_value < high:
        return []
    options = []
    for value in (low - STUB, high + STUB):
        option = _Route(list(route.points), route.channel)
        option.move_channel(value)
        options.append(option)
    return options


class _Route:
    """An orthogonal route with at most one free channel that may be shifted.

    `channel` is the axis the channel's shared coordinate lies on and the
    index of the first of its two points. `limits`, when set, is the range
    that coordinate may take without leaving the gap between the two shapes.
    """

    def __init__(
        self,
        points: list[tuple[float, float]],
        channel: tuple[str, int] | None = None,
        limits: tuple[float, float] | None = None,
    ) -> None:
        self.points = points
        self.channel = channel
        self.limits = limits

    def move_channel(self, value: float) -> None:
        if self.channel is None:
            return
        axis, index = self.channel
        for offset in (0, 1):
            px, py = self.points[index + offset]
            self.points[index + offset] = (value, py) if axis == "x" else (px, value)

    @property
    def channel_value(self) -> float:
        axis, index = self.channel  # type: ignore[misc]
        return self.points[index][0 if axis == "x" else 1]

    @property
    def channel_span(self) -> tuple[float, float]:
        axis, index = self.channel  # type: ignore[misc]
        other = 1 if axis == "x" else 0
        low, high = sorted((self.points[index][other], self.points[index + 1][other]))
        return low, high


def _orthogonal(a: tuple[float, float], side_a: str, b: tuple[float, float], side_b: str) -> _Route:
    """Routes between two anchors using only horizontal and vertical runs.

    Each end leaves its shape perpendicular to the side it is on. Work is done
    with the source side treated as horizontal; a vertical source side is
    handled by swapping the axes on the way in and out.
    """
    if SIDE_VECTOR[side_a][0] == 0:
        swap = {"top": "left", "bottom": "right", "left": "top", "right": "bottom"}
        mirrored = _orthogonal((a[1], a[0]), swap[side_a], (b[1], b[0]), swap[side_b])
        return _Route(
            [(y, x) for x, y in mirrored.points],
            (("y" if mirrored.channel[0] == "x" else "x"), mirrored.channel[1]) if mirrored.channel else None,
            mirrored.limits,
        )

    ax, ay = a
    bx, by = b
    out = SIDE_VECTOR[side_a][0]
    into = SIDE_VECTOR[side_b]

    if into[0] != 0:
        if into[0] == -out and (bx - ax) * out > 2 * CHANNEL_MARGIN:
            # Facing sides with room between them: straight, or one offset.
            if abs(ay - by) < 0.5:
                return _Route([a, (bx, ay)])
            middle = (ax + bx) / 2
            limits = tuple(sorted((ax + out * CHANNEL_MARGIN, bx - out * CHANNEL_MARGIN)))
            return _Route([a, (middle, ay), (middle, by), b], ("x", 1), limits)
        if into[0] == out:
            # Both ends on the same side: loop around beyond the farther one.
            reach = (max(ax, bx) + STUB) if out > 0 else (min(ax, bx) - STUB)
            return _Route([a, (reach, ay), (reach, by), b], ("x", 1))
        # Facing sides but the target is behind the source: out, across, back.
        leave, arrive = ax + out * STUB, bx - out * STUB
        middle = (ay + by) / 2
        return _Route([a, (leave, ay), (leave, middle), (arrive, middle), (arrive, by), b], ("y", 2))

    # The target side is horizontal-facing up or down.
    if (bx - ax) * out > 0 and (ay - by) * into[1] > 0:
        return _Route([a, (bx, ay), b])
    leave, arrive = ax + out * STUB, by + into[1] * STUB
    return _Route([a, (leave, ay), (leave, arrive), (bx, arrive), b])


def _without_repeats(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drops points that coincide with the one before, which would draw nothing."""
    kept = [points[0]]
    for point in points[1:]:
        if abs(point[0] - kept[-1][0]) > 0.01 or abs(point[1] - kept[-1][1]) > 0.01:
            kept.append(point)
    return kept if len(kept) >= 2 else [points[0], points[-1]]


def _spread_channels(routes: list[tuple[_Route, tuple, tuple]]) -> None:
    """Separates unrelated connectors that would otherwise share one channel.

    Connectors that leave the same anchor, or arrive at the same anchor, are
    meant to share a run: that reads as one branching line. Others that land
    on the same channel are spaced apart, staying inside the gap between the
    shapes; when the gap is too narrow for the usual spacing they sit closer.
    """
    remaining = [entry for entry in routes if entry[0].channel is not None]
    while remaining:
        first = remaining.pop(0)
        axis = first[0].channel[0]
        cluster = [first]
        for entry in list(remaining):
            route = entry[0]
            if route.channel[0] != axis or abs(route.channel_value - first[0].channel_value) > 1:
                continue
            low, high = route.channel_span
            if any(low < other[0].channel_span[1] and other[0].channel_span[0] < high for other in cluster):
                cluster.append(entry)
                remaining.remove(entry)
        buses: list[list[tuple[_Route, tuple, tuple]]] = []
        for entry in cluster:
            for bus in buses:
                if any(entry[1] == other[1] or entry[2] == other[2] for other in bus):
                    bus.append(entry)
                    break
            else:
                buses.append([entry])
        if len(buses) < 2:
            continue
        centre = first[0].channel_value
        bounds = [entry[0].limits for entry in cluster if entry[0].limits]
        low = max((limit[0] for limit in bounds), default=-math.inf)
        high = min((limit[1] for limit in bounds), default=math.inf)
        spacing = CHANNEL_SPACING
        if low <= high and math.isfinite(high - low):
            spacing = min(spacing, (high - low) / (len(buses) - 1))
            half = spacing * (len(buses) - 1) / 2
            centre = min(max(centre, low + half), high - half)
        buses.sort(key=lambda bus: min(entry[0].channel_span[0] for entry in bus))
        for index, bus in enumerate(buses):
            value = centre + (index - (len(buses) - 1) / 2) * spacing
            for entry in bus:
                entry[0].move_channel(value)


def compile_spec(spec: DiagramSpec, catalog: Catalog | None = None) -> wire.Document:
    """Builds the exact document a spec describes.

    The document is package format 18, which SimpleDiagrams 5.1.0 and later open. Its
    library shapes all come from the libraries packaged with the app, so it needs nothing
    installed.

    Raises:
        SpecError: A node names a shape the catalogue does not have, or complex shapes
            cannot be laid out as the spec asks.
    """
    catalog = catalog or Catalog.load()
    document_id = spec.id.upper() if spec.id else str(uuid.uuid4()).upper()
    pages = [
        _PageCompiler(page, page_index, document_id, catalog).compile()
        for page_index, page in enumerate(spec.pages)
    ]
    return wire.document(id=document_id, name=spec.name, pages=pages)


class _Look(NamedTuple):
    """What the compiler decided about a plain or library node's label."""

    kind: str
    catalog_shape: CatalogShape | None
    text: wire.TextContent
    text_layout: wire.TextLayout | None
    # Where a label above or below its shape is drawn, approximately.
    label_area: wire.Rect | None


class _Unit(NamedTuple):
    """One thing a container or lane holds: a node."""

    key: str
    member: wire.HolderMember
    # The frame the app counts, for whether it lies inside.
    frame: wire.Rect
    # The frame and a label drawn above or below it, for fitting a holder around it.
    extent: wire.Rect


class _Message(NamedTuple):
    """Where one message between lifelines is drawn and how its ends attach along them."""

    points: list[tuple[float, float]]
    start: wire.Attachment
    end: wire.Attachment


def _union(rects: list[wire.Rect]) -> wire.Rect:
    """The smallest rectangle around every one of `rects`."""
    left = min(rect.x for rect in rects)
    top = min(rect.y for rect in rects)
    right = max(rect.x + rect.width for rect in rects)
    bottom = max(rect.y + rect.height for rect in rects)
    return wire.Rect(x=left, y=top, width=right - left, height=bottom - top)


def _lies_inside(inner: wire.Rect, outer: wire.Rect) -> bool:
    """Whether `inner` lies wholly inside `outer`, allowing for rounding."""
    slack = 0.01
    return (
        inner.x >= outer.x - slack
        and inner.y >= outer.y - slack
        and inner.x + inner.width <= outer.x + outer.width + slack
        and inner.y + inner.height <= outer.y + outer.height + slack
    )


class _PageCompiler:
    """Turns one page of a spec into a page of the document.

    Plain and library nodes are placed first, then lifelines and the messages between them,
    then tables and callouts, then containers and swimlanes, innermost first, each placed
    where the spec says or fitted around what it holds, and last the callouts' tails and
    the connectors. Elements are written in the spec's order.
    """

    def __init__(
        self, page: PageSpec, page_index: int, document_id: str, catalog: Catalog
    ) -> None:
        self.page = page
        self.page_index = page_index
        self.document_id = document_id
        self.namespace = uuid.UUID(document_id)
        self.catalog = catalog
        self.nodes = {node.key: node for node in page.nodes}
        self.placed: dict[str, _Placed] = {}
        self.looks: dict[str, _Look] = {}
        self.records: dict[str, wire.ComplexShape] = {}
        # Messages by edge index; fragments fitted around messages by node key; the dashed
        # lines across fragments as (fragment key, page y, label).
        self.messages: dict[int, _Message] = {}
        self.fragments: dict[str, wire.Rect] = {}
        self.dividers: list[tuple[str, float, str]] = []
        # Each holder's depth: how many holders around it, itself included.
        self.depth: dict[str, int] = {}

    def _id(self, name: str) -> str:
        return _new_id(self.namespace, f"page:{self.page_index}:{name}")

    def compile(self) -> wire.Page:
        for node in self.page.nodes:
            if node.shape not in COMPLEX_KINDS:
                self._place_plain(node)
        self._lay_out_sequence()
        for node in self.page.nodes:
            if node.shape == "table":
                widths, heights = self._table_tracks(node)
                self._place_at_centre(node, node.width or sum(widths), node.height or sum(heights))
            elif node.shape == "callout":
                width, height = DEFAULT_SIZE["callout"]
                self._place_at_centre(node, node.width or width, node.height or height)
        for key in self._holders_innermost_first():
            self._place_holder(self.nodes[key])
        connections = self._connections()
        elements = self._elements()
        holders = sorted(
            (node for node in self.page.nodes if node.shape in HOLDER_KINDS),
            key=lambda node: self.depth[node.key],
        )
        order: list[wire.DrawableReference] | None = None
        if holders:
            # Containers and swimlanes are drawn behind everything, the outermost furthest
            # back, so a UML fragment drawn around messages never covers them; then the
            # connectors, then the other shapes, as on a page without an order.
            back = {self.placed[node.key].element_id for node in holders}
            order = (
                [wire.DrawableReference(kind="element", id=self.placed[node.key].element_id) for node in holders]
                + [wire.DrawableReference(kind="connection", id=c.content.id) for c in connections]
                + [
                    wire.DrawableReference(kind="element", id=element.core.id)
                    for element in elements
                    if element.core.id not in back
                ]
            )
        return wire.page(
            id=_new_id(self.namespace, f"page:{self.page_index}"),
            name=self.page.name,
            elements=elements,
            connections=connections,
            background=wire.Background(kind="solid", color_hex=self.page.background) if self.page.background else None,
            drawable_order=order,
        )

    # -- Placing nodes ------------------------------------------------------------------

    def _centre(self, node: NodeSpec) -> tuple[float, float]:
        if node.col is not None and node.row is not None:
            grid = self.page.grid
            return grid.origin_x + node.col * grid.column_pitch, grid.origin_y + node.row * grid.row_pitch
        assert node.x is not None and node.y is not None
        return node.x, node.y

    def _put(
        self, node: NodeSpec, x: float, y: float, width: float, height: float, *,
        points: dict[int, tuple[float, float]] | None = None, name: str = "",
    ) -> _Placed:
        placed = _Placed(
            node, _node_id(self.document_id, self.page_index, node.key), _snap(x), _snap(y),
            float(width), float(height), points=points, display_name=name or node.shape.capitalize(),
        )
        self.placed[node.key] = placed
        return placed

    def _place_at_centre(self, node: NodeSpec, width: float, height: float) -> _Placed:
        centre_x, centre_y = self._centre(node)
        points = {2: (0.5, 0.0)} if node.shape == "lifeline" else None
        return self._put(node, centre_x - width / 2, centre_y - height / 2, width, height, points=points)

    @staticmethod
    def _text_style(node: NodeSpec) -> wire.CharacterStyle:
        return wire.character_style(
            font_size=float(node.font_size),
            weight="bold" if node.bold else "medium",
            color_hex=node.text_color or "#212529",
        )

    def _place_plain(self, node: NodeSpec) -> None:
        """Places a plain or library node and decides where its label goes."""
        catalog_shape: CatalogShape | None = None
        if node.shape in NATIVE_KINDS:
            kind = node.shape
        else:
            library, separator, item = node.shape.partition("/")
            if not separator:
                raise SpecError(
                    f"node '{node.key}': shape '{node.shape}' is not rectangle, ellipse, note, "
                    "text, container, swimlanes, table, callout, lifeline or '<library>/<item>'"
                )
            catalog_shape = self.catalog.resolve(library, item)
            if catalog_shape is None:
                hint = self.catalog.suggestions(library, item)
                raise SpecError(
                    f"node '{node.key}': '{node.shape}' is not one of the shapes packaged with "
                    f"SimpleDiagrams {self.catalog.source_app_version}."
                    + (f" Did you mean: {', '.join(hint)}?" if hint else "")
                )
            if catalog_shape.resizing == "width_only" and node.height is not None:
                raise SpecError(
                    f"node '{node.key}': '{node.shape}' keeps its own thickness and takes "
                    "only a width; remove its height."
                )
            kind = "symbol"

        width, height = _node_size(node, catalog_shape)
        centre_x, centre_y = self._centre(node)
        placed = self._put(
            node, centre_x - width / 2, centre_y - height / 2, width, height,
            points=(
                {point_id: (x, y) for point_id, x, y in catalog_shape.connection_points}
                if catalog_shape is not None and catalog_shape.connection_points is not None
                else None
            ),
            name=catalog_shape.display_name if catalog_shape else node.key,
        )
        base_style = self._text_style(node)
        # The spec's choice, else the library's (a BPMN event's name goes below it),
        # else the middle, which is what a placed shape has always had.
        position = node.label_position or (
            catalog_shape.text_position if catalog_shape else None
        ) or "middle"
        region = catalog_shape.text_region if catalog_shape else None
        outside = position in ("above", "below") and bool(node.label) and kind != "text"
        text_layout: wire.TextLayout | None = None
        if (position != "middle" or region is not None) and kind != "text":
            if region is not None:
                # The library's own label area, as the app gives a copy placed by hand. Some
                # libraries centre a name wider than the shape below it.
                frame = wire.TextLayoutFrame(x=region[0], y=region[1], width=region[2], height=region[3])
            elif outside:
                # A label above or below its shape wraps at its region's width, so a label
                # wider than the shape gets a region as wide as it needs, up to eight times
                # the shape's, centred on the shape, as the app's own libraries centre a name.
                label_width, _ = estimate_text_size(node.label, node.font_size, node.bold)
                share = _snap(min(MAX_LABEL_REGION, max(1.0, (label_width + LABEL_ROOM) / width)))
                frame = wire.TextLayoutFrame(x=_snap((1 - share) / 2), y=0.0, width=share, height=1.0)
            else:
                # The app's own default label region: a 10 by 8 point inset.
                inset_x, inset_y = min(10, max(0, (width - 1) / 2)), min(8, max(0, (height - 1) / 2))
                frame = wire.TextLayoutFrame(
                    x=inset_x / width, y=inset_y / height,
                    width=max(0.001, (width - 2 * inset_x) / width),
                    height=max(0.001, (height - 2 * inset_y) / height),
                )
            text_layout = wire.TextLayout(frame=frame, position=position)
        text = wire.text_content(node.label, base_style=base_style, base_alignment=node.align or "center")
        label_area = outside_label_rect(placed.rect, text_layout, text) if text_layout is not None else None
        self.looks[node.key] = _Look(kind, catalog_shape, text, text_layout, label_area)

    def _table_tracks(self, node: NodeSpec) -> tuple[list[float], list[float]]:
        """A table's column widths and row heights: as the spec gives them, or each sized
        to its cells' text with room around it, as the app's cells keep 6 points across and
        3 down."""
        cells = node.cells
        assert cells is not None
        header = node.header_row is not False
        size = node.font_size

        def measure(row: int, column: int) -> tuple[float, float]:
            return estimate_text_size(cells[row][column], size, node.bold or (header and row == 0))

        rows, columns = range(len(cells)), range(len(cells[0]))
        widths = (
            [float(width) for width in node.column_widths]
            if node.column_widths
            else [max(40.0, float(math.ceil(max(measure(r, c)[0] for r in rows) + 28))) for c in columns]
        )
        heights = (
            [float(height) for height in node.row_heights]
            if node.row_heights
            else [
                float(math.ceil(max(max(1, cells[r][c].count("\n") + 1) for c in columns) * size * LINE_HEIGHT + 14))
                for r in rows
            ]
        )
        return widths, heights

    # -- Sequence diagrams --------------------------------------------------------------

    def _lay_out_sequence(self) -> None:
        """Places the page's lifelines and works out where each message between them, and
        each UML fragment around messages, goes.

        Messages run down the page in the spec's order, MESSAGE_STEP apart, with room above
        each fragment's first message for its tag. Lifelines line up their heads and are made
        long enough for every message; one that ends in a destroy mark ends just below its
        last message. A message attaches anywhere along each lifeline's line, at its distance
        down the line, as SimpleDiagrams stores it.
        """
        edges = self.page.edges
        order: list[int] = []
        for index, edge in enumerate(edges):
            on_lifelines = (self.nodes[edge.source].shape == "lifeline", self.nodes[edge.target].shape == "lifeline")
            if all(on_lifelines):
                if any(v is not None for v in (edge.source_side, edge.target_side, edge.source_point, edge.target_point)):
                    raise SpecError(
                        f"edge {edge.source} -> {edge.target}: a message attaches anywhere along its "
                        "lifelines, at its place in the sequence; remove its sides and points"
                    )
                order.append(index)
            elif any(on_lifelines):
                raise SpecError(
                    f"edge {edge.source} -> {edge.target}: a lifeline's connectors are messages to "
                    "lifelines; draw other connectors between the shapes a lifeline stands for"
                )
        position = {edges[index].key: k for k, index in enumerate(order) if edges[index].key is not None}
        fragments = [node for node in self.page.nodes if node.shape == "container" and node.messages]
        spans: dict[str, tuple[int, int]] = {}
        for node in fragments:
            assert node.messages is not None
            ranks = []
            for key in node.messages:
                if key not in position:
                    raise SpecError(
                        f"node '{node.key}': edge '{key}' is not a message between two lifelines, "
                        "which is all a fragment encloses"
                    )
                ranks.append(position[key])
            spans[node.key] = (min(ranks), max(ranks))
            for divider in node.dividers or []:
                rank = position.get(divider.before)
                if rank is None or not spans[node.key][0] < rank <= spans[node.key][1]:
                    raise SpecError(
                        f"node '{node.key}': a divider goes before one of the fragment's messages "
                        f"after its first, and '{divider.before}' is not one"
                    )
        lifelines = [node for node in self.page.nodes if node.shape == "lifeline"]
        if not lifelines:
            return

        # Fragments nest or stand apart. Of two around the same messages, the first listed
        # is the outer one.
        inside: dict[str, list[str]] = {key: [] for key in spans}
        keys = list(spans)
        for number, one in enumerate(keys):
            for other in keys[number + 1 :]:
                (a0, a1), (b0, b1) = spans[one], spans[other]
                if a1 < b0 or b1 < a0:
                    continue
                if a0 <= b0 and b1 <= a1:
                    inside[one].append(other)
                elif b0 <= a0 and a1 <= b1:
                    inside[other].append(one)
                else:
                    raise SpecError(
                        f"fragments '{one}' and '{other}' share some messages but neither holds "
                        "the other's; one must enclose the other, or they must share none"
                    )

        # How many levels of fragments each holds, worked out once each, innermost first,
        # so fragments nested hundreds deep cost no more than the pairs compared above.
        levels: dict[str, int] = {}
        for key in sorted(spans, key=lambda key: len(inside[key])):
            levels[key] = 1 + max((levels[inner] for inner in inside[key]), default=-1)

        def nesting(key: str) -> int:
            return levels[key]

        def tag_room(key: str) -> float:
            node = self.nodes[key]
            _, text_height = estimate_text_size(node.label or " ", node.font_size, node.bold)
            return max(CORNER_TAG_HEIGHT, text_height + 8) + FRAGMENT_TAG_GAP

        # Each message's height below the first, then each fragment's top and bottom.
        drops = [SELF_MESSAGE_DROP if edges[index].source == edges[index].target else 0.0 for index in order]
        rel: list[float] = []
        divider_rel: list[tuple[str, float, str]] = []
        y = bottom = 0.0
        for rank in range(len(order)):
            y += sum(tag_room(key) for key, span in spans.items() if span[0] == rank)
            here = [
                (key, divider)
                for key in spans
                for divider in self.nodes[key].dividers or []
                if position[divider.before] == rank
            ]
            if here:
                y += DIVIDER_ROOM
            rel.append(y)
            divider_rel += [(key, (bottom + y) / 2, divider.label) for key, divider in here]
            bottom = y + drops[rank]
            y = bottom + MESSAGE_STEP + FRAGMENT_END_ROOM * sum(1 for span in spans.values() if span[1] == rank)
        tops_rel: dict[str, float] = {}
        bottoms_rel: dict[str, float] = {}
        for key, (first, last) in spans.items():
            tops_rel[key] = rel[first] - tag_room(key) - sum(
                tag_room(inner) for inner in inside[key] if spans[inner][0] == first
            )
            bottoms_rel[key] = rel[last] + drops[last] + 14 + 10 * sum(
                1 for inner in inside[key] if spans[inner][1] == last
            )
        content_bottom = max([bottom, *bottoms_rel.values()])

        # The lifelines, their heads in line when they share a row.
        heads = {node.key: wire.LIFELINE_HEAD_HEIGHT[node.head or "box"] for node in lifelines}
        full = (
            max(heads.values()) + FIRST_MESSAGE_GAP + content_bottom + LIFELINE_END_MARGIN
            if order
            else LIFELINE_HEIGHT
        )
        tops: dict[str, float] = {}
        for node in lifelines:
            _, centre_y = self._centre(node)
            tops[node.key] = _snap(centre_y - (node.height or full) / 2)
        base = max(tops[key] + heads[key] for key in tops) + FIRST_MESSAGE_GAP
        for node in lifelines:
            centre_x, _ = self._centre(node)
            label_width, _ = estimate_text_size(node.label, node.font_size, node.bold)
            head = node.head or "box"
            width = node.width or max(LIFELINE_WIDTH[head], math.ceil(label_width + (24 if head == "box" else 12)))
            height = node.height or full
            if node.ends_in_destroy_mark and node.height is None:
                # The line ends just below the lifeline's last message, in the destroy mark,
                # which clears the bottom of every fragment around that message.
                ranks = [
                    rank for rank, index in enumerate(order)
                    if node.key in (edges[index].source, edges[index].target)
                ]
                if ranks:
                    last = ranks[-1]
                    end = max(
                        [rel[last] + drops[last] + DESTROYED_LINE_MARGIN]
                        + [
                            bottoms_rel[key] + DESTROYED_FRAGMENT_CLEARANCE + wire.DESTROY_MARK_SIZE / 2
                            for key, (first, final) in spans.items()
                            if first <= last <= final
                        ]
                    )
                    height = base + end - tops[node.key] + wire.DESTROY_MARK_SIZE / 2
                else:
                    height = heads[node.key] + FIRST_MESSAGE_GAP + DESTROYED_LINE_MARGIN + wire.DESTROY_MARK_SIZE / 2
            smallest = heads[node.key] + wire.SHORTEST_LIFELINE_LINE + (
                wire.DESTROY_MARK_SIZE / 2 if node.ends_in_destroy_mark else 0
            )
            if height < smallest:
                raise SpecError(f"node '{node.key}': a lifeline is at least {smallest:g} tall; raise its height")
            self._put(node, centre_x - width / 2, tops[node.key], width, height, points={2: (0.5, 0.0)})

        for rank, index in enumerate(order):
            edge = edges[index]
            source, target = self.placed[edge.source], self.placed[edge.target]
            ends: list[tuple[wire.Attachment, float]] = []
            for placed, at in ((source, base + rel[rank]), (target, base + rel[rank] + drops[rank])):
                start = placed.y + heads[placed.spec.key]
                stop = placed.y + placed.h - (wire.DESTROY_MARK_SIZE / 2 if placed.spec.ends_in_destroy_mark else 0)
                if not start <= at <= stop:
                    raise SpecError(
                        f"edge {edge.source} -> {edge.target}: the message lies below the end of "
                        f"lifeline '{placed.spec.key}'; leave out its height, or make it taller"
                    )
                distance = _snap(at - start)
                ends.append(
                    (wire.Attachment(element_id=placed.element_id, attach_line_id=wire.LIFELINE_ATTACH_LINE, distance=distance), start + distance)
                )
            (start_end, y_start), (end_end, y_end) = ends
            if source is target:
                # A call to itself: the app draws it out to the right of the line and back.
                points = [
                    (source.cx, y_start), (source.cx + SELF_LOOP_WIDTH, y_start),
                    (source.cx + SELF_LOOP_WIDTH, y_end), (source.cx, y_end),
                ]
            else:
                points = [(source.cx, y_start), (target.cx, y_end)]
            self.messages[index] = _Message(points, start_end, end_end)

        for key, (first, last) in spans.items():
            node = self.nodes[key]
            low: list[float] = []
            high: list[float] = []
            for index in order[first : last + 1]:
                edge = edges[index]
                for joined in (edge.source, edge.target):
                    low.append(self.placed[joined].cx)
                    high.append(self.placed[joined].cx + (SELF_LOOP_WIDTH if edge.source == edge.target else 0))
            side = FRAGMENT_SIDE + FRAGMENT_NEST_STEP * nesting(key)
            left, right = min(low) - side, max(high) + side
            label_width, _ = estimate_text_size(node.label or " ", node.font_size, node.bold)
            # Room for the corner tag: its title, the title's insets and the cut corner.
            right = max(right, left + label_width + 12 + 16 + 24)
            top, bottom_y = base + tops_rel[key], base + bottoms_rel[key]
            self.fragments[key] = wire.Rect(
                x=_snap(left), y=_snap(top), width=_snap(right - left), height=_snap(bottom_y - top)
            )
        self.dividers = [(key, _snap(base + at), label) for key, at, label in divider_rel]

    # -- Containers and swimlanes -------------------------------------------------------

    def _members(self, node: NodeSpec) -> list[str]:
        if node.shape == "container":
            return list(node.members or [])
        return [key for lane in node.lanes or [] for key in lane.members]

    def _holders_innermost_first(self) -> list[str]:
        """The page's containers and swimlanes, each after every holder it holds, having
        checked that each node is held once at most, swimlanes never, and containers at most
        four deep without a loop."""
        holder_of: dict[str, str] = {}
        holders = [node for node in self.page.nodes if node.shape in HOLDER_KINDS]
        for node in holders:
            for key in self._members(node):
                if self.nodes[key].shape == "swimlanes":
                    raise SpecError(
                        f"node '{node.key}' holds swimlanes '{key}'; swimlanes are never inside a "
                        "container or other swimlanes"
                    )
                if key in holder_of:
                    raise SpecError(
                        f"node '{key}' is held by '{holder_of[key]}' and by '{node.key}'"
                        if holder_of[key] != node.key
                        else f"node '{node.key}' lists '{key}' twice"
                    )
                holder_of[key] = node.key
        for node in holders:
            seen, current, depth = {node.key}, node.key, 1
            while current in holder_of:
                current = holder_of[current]
                depth += 1
                if current in seen:
                    raise SpecError(f"node '{node.key}' is inside a loop of containers holding one another")
                if depth > wire.MAX_HOLDER_NESTING:
                    raise SpecError(
                        f"node '{node.key}' is inside more containers than SimpleDiagrams allows; "
                        f"containers nest {wire.MAX_HOLDER_NESTING} deep at most"
                    )
                seen.add(current)
            self.depth[node.key] = depth
        return [node.key for node in sorted(holders, key=lambda node: -self.depth[node.key])]

    def _unit(self, key: str) -> _Unit:
        """What a holder holds for node `key`: its shape, with its label for fitting."""
        placed = self.placed[key]
        look = self.looks.get(key)
        frame = placed.rect
        member = wire.HolderMember(kind="element", id=placed.element_id)
        extent = _union([frame, look.label_area]) if look is not None and look.label_area is not None else frame
        return _Unit(key, member, frame, extent)

    def _place_holder(self, node: NodeSpec) -> None:
        if node.shape == "container":
            self._place_container(node)
        else:
            self._place_swimlanes(node)

    def _place_given(self, node: NodeSpec) -> _Placed:
        default_width, default_height = DEFAULT_SIZE[node.shape]
        return self._place_at_centre(node, node.width or default_width, node.height or default_height)

    def _place_container(self, node: NodeSpec) -> None:
        units = [self._unit(key) for key in node.members or []]
        corner = node.title_style == "corner_tag"
        label_width, label_height = estimate_text_size(node.label or " ", node.font_size, node.bold)
        if not node.fitted:
            placed = self._place_given(node)
            for unit in units:
                if not _lies_inside(unit.frame, placed.rect):
                    raise SpecError(
                        f"node '{unit.key}' is in container '{node.key}' but does not lie wholly "
                        f"inside it; move it, or leave out '{node.key}''s position to fit it around "
                        "its members"
                    )
        else:
            boxes = [self.fragments[node.key]] if node.key in self.fragments else []
            if units:
                around = _union([unit.extent for unit in units])
                top = max(CORNER_TAG_HEIGHT, label_height + 8) + FRAGMENT_TAG_GAP if corner else CONTAINER_TITLE_BAND + 8
                boxes.append(
                    wire.Rect(
                        x=around.x - HOLDER_PADDING, y=around.y - top,
                        width=around.width + 2 * HOLDER_PADDING, height=around.height + top + HOLDER_PADDING,
                    )
                )
            frame = _union(boxes)
            # Room for the title on one line: in the band within its padding, or in the tag.
            width = max(frame.width, label_width + (12 + 16 + 24 if corner else 24 + 8))
            self._put(node, frame.x, frame.y, math.ceil(width), math.ceil(frame.height))
        self.records[node.key] = wire.ComplexShape(
            type="container",
            hand_drawn=False if node.hand_drawn is False else None,
            members=[unit.member for unit in units],
            title_style="corner_tag" if corner else None,
        )

    def _place_swimlanes(self, node: NodeSpec) -> None:
        assert node.lanes is not None
        horizontal = node.direction != "vertical"
        strip = band = wire.SWIMLANES_STRIP
        lane_units = [[self._unit(key) for key in lane.members] for lane in node.lanes]
        names = [f"lane {index + 1}" + (f" ('{lane.title}')" if lane.title else "") for index, lane in enumerate(node.lanes)]
        if node.fitted:
            extents = []
            for name, units in zip(names, lane_units, strict=True):
                if not units:
                    raise SpecError(
                        f"node '{node.key}': {name} holds nothing, so it cannot be fitted; give it a "
                        "member, or give the swimlanes a position, width and height"
                    )
                extents.append(_union([unit.extent for unit in units]))

            def along(rect: wire.Rect) -> tuple[float, float]:
                return (rect.y, rect.y + rect.height) if horizontal else (rect.x, rect.x + rect.width)

            def across(rect: wire.Rect) -> tuple[float, float]:
                return (rect.x, rect.x + rect.width) if horizontal else (rect.y, rect.y + rect.height)

            spans = [along(extent) for extent in extents]
            for index in range(len(spans) - 1):
                if spans[index][1] >= spans[index + 1][0]:
                    raise SpecError(
                        f"node '{node.key}': the members of {names[index]} and {names[index + 1]} "
                        f"overlap; put each lane's members {'below' if horizontal else 'to the right of'} "
                        "the previous lane's"
                    )
            bounds = (
                [spans[0][0] - HOLDER_PADDING]
                + [(spans[index][1] + spans[index + 1][0]) / 2 for index in range(len(spans) - 1)]
                + [spans[-1][1] + HOLDER_PADDING]
            )
            low = min(across(extent)[0] for extent in extents) - HOLDER_PADDING - strip
            high = max(across(extent)[1] for extent in extents) + HOLDER_PADDING
            label_width, _ = estimate_text_size(node.label or " ", node.font_size, node.bold)
            if horizontal:
                high = max(high, low + label_width + 32)
                frame = wire.Rect(x=low, y=bounds[0] - band, width=high - low, height=bounds[-1] - bounds[0] + band)
            else:
                frame = wire.Rect(
                    x=bounds[0], y=low - band, width=max(bounds[-1] - bounds[0], label_width + 32),
                    height=high - low + band,
                )
            self._put(node, frame.x, frame.y, _snap(frame.width), _snap(frame.height))
            sizes = [_snap(bounds[index + 1] - bounds[index]) for index in range(len(spans))]
            if not horizontal and frame.width > bounds[-1] - bounds[0]:
                # A title wider than the lanes widens the last lane.
                sizes[-1] = _snap(sizes[-1] + frame.width - (bounds[-1] - bounds[0]))
        else:
            self._place_given(node)
            sizes = [float(lane.size) if lane.size is not None else 1.0 for lane in node.lanes]
        style = self._text_style(node)
        record = wire.ComplexShape(
            type="swimlanes",
            hand_drawn=False if node.hand_drawn is False else None,
            direction="horizontal" if horizontal else "vertical",
            lanes=[
                wire.Lane(
                    id=self._id(f"lane:{node.key}:{index}"),
                    title=wire.text_content(lane.title, base_style=style),
                    size=size,
                    members=[unit.member for unit in units],
                )
                for index, (lane, size, units) in enumerate(zip(node.lanes, sizes, lane_units, strict=True))
            ],
        )
        placed = self.placed[node.key]
        lane_frames = wire.swimlane_frames(record, placed.rect)
        for name, lane_frame, units in zip(names, lane_frames, lane_units, strict=True):
            thickness = lane_frame.height if horizontal else lane_frame.width
            if thickness < wire.SWIMLANES_STRIP - 1e-6:
                raise SpecError(
                    f"node '{node.key}': {name} is {thickness:g} thick, and a lane is at least "
                    f"{wire.SWIMLANES_STRIP:g}; make the swimlanes larger or the lane's size larger"
                )
            for unit in units:
                centre = (unit.frame.x + unit.frame.width / 2, unit.frame.y + unit.frame.height / 2)
                in_lane = (
                    lane_frame.x <= centre[0] <= lane_frame.x + lane_frame.width
                    and lane_frame.y <= centre[1] <= lane_frame.y + lane_frame.height
                )
                if not (_lies_inside(unit.frame, placed.rect) and in_lane):
                    raise SpecError(
                        f"node '{unit.key}' is in {name} of '{node.key}' but does not lie wholly inside "
                        "the swimlanes with its centre in that lane; move it, or leave out the "
                        "swimlanes' position to fit them around their members"
                    )
        if (placed.w if horizontal else placed.h - band) < strip - 1e-6:
            raise SpecError(f"node '{node.key}': the swimlanes are too small for their title strips")
        self.records[node.key] = record

    # -- Callouts and tables ------------------------------------------------------------

    def _callout(self, node: NodeSpec) -> wire.ComplexShape:
        """A callout's tail: locked to a node's connection point, aimed at a page point, or
        where a new callout's tail is. Its tip is kept along the bubble's own axes before
        flipping, from its centre, as SimpleDiagrams stores it."""
        bubble = self.placed[node.key]
        attachment: wire.Attachment | None = None
        if node.tail_to is not None:
            target = self.placed[node.tail_to]
            where = f"node '{node.key}': the tail's target {target.display_name} ('{node.tail_to}')"
            if not target.points:
                raise SpecError(f"{where} has no connection points; lock the tail to the shape it marks")
            if node.tail_point is not None and node.tail_point not in target.points:
                raise SpecError(f"{where} has no connection point {node.tail_point}. Its points are {target.point_ids}.")
            point_id = node.tail_point if node.tail_point is not None else min(
                target.points,
                key=lambda point: (math.hypot(target.anchor(point).x - bubble.cx, target.anchor(point).y - bubble.cy), point),
            )
            anchor = target.anchor(point_id)
            tip = (anchor.x - bubble.cx, anchor.y - bubble.cy)
            attachment = wire.Attachment(element_id=target.element_id, connection_point_id=point_id)
        elif node.tail_at is not None:
            tip = (node.tail_at.x - bubble.cx, node.tail_at.y - bubble.cy)
        else:
            tip = CALLOUT_TAIL
        if node.tail_to is not None or node.tail_at is not None:
            tip = (-tip[0] if node.flip_horizontal else tip[0], -tip[1] if node.flip_vertical else tip[1])
        return wire.ComplexShape(
            type="callout",
            hand_drawn=False if node.hand_drawn is False else None,
            tail_tip=wire.Point(x=_snap(tip[0]), y=_snap(tip[1])),
            tail_attachment=attachment,
        )

    def _table(self, node: NodeSpec) -> wire.ComplexShape:
        assert node.cells is not None
        widths, heights = self._table_tracks(node)
        placed = self.placed[node.key]
        for name, tracks, length, smallest in (
            ("column", widths, placed.w, wire.MIN_TABLE_COLUMN_WIDTH),
            ("row", heights, placed.h, wire.MIN_TABLE_ROW_HEIGHT),
        ):
            if min(tracks) / sum(tracks) * length < smallest:
                raise SpecError(
                    f"node '{node.key}': a table {name} would be under {smallest:g} points; make the "
                    "table larger, or leave out its width and height to size it to its cells"
                )
        style = self._text_style(node)
        header = node.header_row is not False
        return wire.ComplexShape(
            type="table",
            hand_drawn=False if node.hand_drawn is False else None,
            row_sizes=[_snap(height) for height in heights],
            column_sizes=[_snap(width) for width in widths],
            cells=[
                [
                    wire.text_content(
                        cell, base_style=style,
                        base_alignment="center" if header and row == 0 else node.align or "center",
                    )
                    for cell in cells
                ]
                for row, cells in enumerate(node.cells)
            ],
            header_row=None if header else False,
        )

    # -- Connectors ---------------------------------------------------------------------

    def _connections(self) -> list[wire.Connection]:
        edges = self.page.edges
        placed = self.placed
        # Containers, swimlanes and fragments are open: connectors run into them freely. A
        # lifeline is open but for its head.
        obstacles_by_key: dict[str, wire.Rect] = {}
        for key, item in placed.items():
            shape = item.spec.shape
            if shape in HOLDER_KINDS:
                continue
            if shape == "lifeline":
                head = wire.LIFELINE_HEAD_HEIGHT[item.spec.head or "box"]
                obstacles_by_key[key] = wire.Rect(x=item.x, y=item.y, width=item.w, height=head)
            else:
                obstacles_by_key[key] = item.rect
        label_areas = [look.label_area for look in self.looks.values() if look.label_area is not None]
        # Loops from a shape to itself are routed after every other connector, so each can
        # keep off the runs the others take; the document still lists them in spec order.
        by_index: dict[int, tuple[EdgeSpec, _Placed, _Placed, _Anchor, _Anchor, _Route | None]] = {}
        taken: list[tuple[float, float, float, float]] = []
        for index in sorted(range(len(edges)), key=lambda i: edges[i].source == edges[i].target):
            if index in self.messages:
                continue
            edge = edges[index]
            source, target = placed[edge.source], placed[edge.target]
            for end, role, side, point in (
                (source, "source", edge.source_side, edge.source_point),
                (target, "target", edge.target_side, edge.target_point),
            ):
                where = f"edge {edge.source} -> {edge.target}: {end.display_name} ('{end.spec.key}')"
                if not end.points:
                    raise SpecError(
                        f"{where} has no connection points, because it is meant to sit on "
                        "another shape. Connect the shape it marks instead."
                    )
                if point is not None and point not in end.points:
                    raise SpecError(
                        f"{where} has no connection point {point}. Its points are "
                        f"{end.point_ids}."
                    )
                if side is not None and end.side_anchor(side) is None:
                    raise SpecError(
                        f"{where} has no connection point on its {side}. Choose "
                        f"another side, or name one of its points with {role}_point: "
                        f"{end.point_ids}."
                    )
                if point is None and side is None and not any(
                    end.side_anchor(each) for each in SIDE_ANCHOR
                ):
                    raise SpecError(
                        f"{where} has no connection point for a side, so name "
                        f"one of its points with {role}_point: {end.point_ids}."
                    )
            obstacles = [
                rect for key, rect in obstacles_by_key.items() if key not in (edge.source, edge.target)
            ] + label_areas
            start_anchor, end_anchor, route = _choose_route(edge, source, target, obstacles, taken)
            if edge.route == "orthogonal":
                taken += [(p[0], p[1], q[0], q[1]) for p, q in pairwise(route.points)]
            by_index[index] = (
                edge, source, target, start_anchor, end_anchor,
                route if edge.route == "orthogonal" else None,
            )

        # Connectors leaving or reaching the same anchor share a run, as one branching line.
        _spread_channels(
            [
                (route, (source.element_id, start_anchor.id), (target.element_id, end_anchor.id))
                for _, source, target, start_anchor, end_anchor, route in (by_index[i] for i in sorted(by_index))
                if route is not None
            ]
        )

        connections: list[wire.Connection] = []
        for edge_index, edge in enumerate(edges):
            message = self.messages.get(edge_index)
            if message is not None:
                route_points = [(px, py, "straight") for px, py in message.points]
                start_attachment, end_attachment = message.start, message.end
            else:
                _, source, target, start_anchor, end_anchor, route = by_index[edge_index]
                start, end = (start_anchor.x, start_anchor.y), (end_anchor.x, end_anchor.y)
                if route is not None:
                    route_points = [(px, py, "straight") for px, py in _without_repeats(route.points)]
                elif edge.route == "curved":
                    # One interior curve point bows the line to one side of the chord.
                    length = math.hypot(end[0] - start[0], end[1] - start[1]) or 1
                    bow = min(60, length * 0.14)
                    normal = (-(end[1] - start[1]) / length, (end[0] - start[0]) / length)
                    middle = ((start[0] + end[0]) / 2 + normal[0] * bow, (start[1] + end[1]) / 2 + normal[1] * bow)
                    route_points = [(*start, "straight"), (*middle, "curve"), (*end, "straight")]
                else:
                    route_points = [(*start, "straight"), (*end, "straight")]
                start_attachment = wire.Attachment(element_id=source.element_id, connection_point_id=start_anchor.id)
                end_attachment = wire.Attachment(element_id=target.element_id, connection_point_id=end_anchor.id)
            connections.append(
                wire.connection(
                    id=self._id(f"edge:{edge_index}"),
                    points=[wire.ConnectorPoint(x=_snap(px), y=_snap(py), kind=kind) for px, py, kind in route_points],
                    start_attachment=start_attachment,
                    end_attachment=end_attachment,
                    stroke_hex=edge.stroke,
                    line_width=float(edge.line_width),
                    stroke_pattern=edge.pattern,
                    start_ending=edge.start_ending,
                    end_ending=edge.end_ending,
                    label=self._edge_label(edge.label, beside_loop=message is not None and edge.source == edge.target),
                )
            )
        for number, (key, at, label) in enumerate(self.dividers):
            fragment, node = self.placed[key], self.nodes[key]
            _, stroke, line_width = DEFAULT_STYLE["complex_shape"]
            connections.append(
                wire.connection(
                    id=self._id(f"divider:{number}"),
                    points=[
                        wire.ConnectorPoint(x=fragment.x, y=at, kind="straight"),
                        wire.ConnectorPoint(x=_snap(fragment.x + fragment.w), y=at, kind="straight"),
                    ],
                    stroke_hex=node.stroke or stroke,
                    line_width=float(node.line_width if node.line_width is not None else line_width),
                    stroke_pattern="dashed", start_ending="none", end_ending="none",
                    label=self._edge_label(label),
                )
            )
        return connections

    @staticmethod
    def _edge_label(text: str, *, beside_loop: bool = False) -> wire.ConnectorLabel | None:
        """A connector's label, centred on it; a call to its own lifeline has its label
        beside the loop instead, which is narrower than most labels. The middle of that loop
        runs down the page, and a negative offset from a line running down lies to its right."""
        if not text:
            return None
        width, _ = estimate_text_size(text, 13.0)
        return wire.ConnectorLabel(
            content=wire.text_content(text, base_style=wire.character_style(font_size=13.0)),
            position=0.5, normal_offset=-_snap(width / 2 + 6) if beside_loop else 0.0,
        )

    # -- Elements -----------------------------------------------------------------------

    def _elements(self) -> list[wire.Element]:
        """Every node's element, in the spec's order."""
        elements: list[wire.Element] = []
        for node in self.page.nodes:
            placed = self.placed[node.key]
            if node.shape in COMPLEX_KINDS:
                elements.append(self._complex_element(node, placed, len(elements)))
                continue
            look = self.looks[node.key]
            fill, stroke, line_width = DEFAULT_STYLE[look.kind]
            catalog_shape = look.catalog_shape
            elements.append(
                wire.element(
                    id=placed.element_id,
                    kind=look.kind,
                    frame=placed.rect,
                    rotation_degrees=float(node.rotation % 360),
                    flip_horizontal=node.flip_horizontal,
                    flip_vertical=node.flip_vertical,
                    z_index=len(elements),
                    text=look.text,
                    style=wire.ElementStyle(
                        fill_hex=node.fill or fill,
                        stroke_hex=node.stroke or stroke,
                        line_width=float(node.line_width if node.line_width is not None else line_width),
                    ),
                    symbol_reference=(
                        wire.SymbolReference(
                            library_id=catalog_shape.library_id,
                            item_id=catalog_shape.item_id,
                            asset_version=catalog_shape.asset_version,
                        )
                        if catalog_shape
                        else None
                    ),
                    # The anchors the library gives the shape, as the app gives a copy placed
                    # by hand; None writes the standard eight.
                    connection_points=(
                        [wire.ConnectionPointAnchor(id=i, x=x, y=y) for i, x, y in catalog_shape.connection_points]
                        if catalog_shape is not None and catalog_shape.connection_points is not None
                        else None
                    ),
                    text_layout=look.text_layout,
                )
            )
        return elements

    def _complex_element(self, node: NodeSpec, placed: _Placed, z_index: int) -> wire.Element:
        """A complex shape's element, painted as the app paints one placed from its tile."""
        if node.shape == "table":
            record = self._table(node)
        elif node.shape == "lifeline":
            record = wire.ComplexShape(
                type="lifeline",
                hand_drawn=False if node.hand_drawn is False else None,
                head_style="actor" if node.head == "actor" else None,
                ends_in_destroy_mark=True if node.ends_in_destroy_mark else None,
            )
        elif node.shape == "callout":
            record = self._callout(node)
        else:
            record = self.records[node.key]
        fill, stroke, line_width = DEFAULT_STYLE["complex_shape"]
        # A new container's title starts at its leading edge; everything else is centred.
        alignment = node.align or ("leading" if node.shape == "container" else "center")
        return wire.element(
            id=placed.element_id,
            kind="complex_shape",
            frame=placed.rect,
            flip_horizontal=node.flip_horizontal,
            flip_vertical=node.flip_vertical,
            z_index=z_index,
            text=wire.text_content(node.label, base_style=self._text_style(node), base_alignment=alignment),
            style=wire.ElementStyle(
                fill_hex=node.fill or fill,
                stroke_hex=node.stroke or stroke,
                line_width=float(node.line_width if node.line_width is not None else line_width),
            ),
            # A lifeline has one numbered point, the top of its head; messages attach along
            # its line instead. Every other complex shape has the standard eight.
            connection_points=[wire.ConnectionPointAnchor(id=2, x=0.5, y=0.0)] if node.shape == "lifeline" else None,
            complex_shape=record,
        )


# ---------------------------------------------------------------------------
# Layout checks
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """One problem found in a document, with where it is and how to fix it."""

    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning"]
    code: str
    message: str


def _segments(points: list[wire.ConnectorPoint]) -> list[tuple[float, float, float, float]]:
    return [(a.x, a.y, b.x, b.y) for a, b in pairwise(points)]


def _segment_hits_rect(segment: tuple[float, float, float, float], rect: wire.Rect, inset: float = 3) -> bool:
    """True when a segment passes through the inside of a frame (Liang-Barsky)."""
    x1, y1, x2, y2 = segment
    left, top = rect.x + inset, rect.y + inset
    right, bottom = rect.x + rect.width - inset, rect.y + rect.height - inset
    if right <= left or bottom <= top:
        return False
    dx, dy = x2 - x1, y2 - y1
    t_enter, t_exit = 0.0, 1.0
    for p, q in ((-dx, x1 - left), (dx, right - x1), (-dy, y1 - top), (dy, bottom - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t_enter = max(t_enter, t)
        else:
            t_exit = min(t_exit, t)
    return t_enter < t_exit


def _segments_cross(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """True when two segments properly cross, not merely touch at an end."""

    def orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    d1 = orient(b[0], b[1], b[2], b[3], a[0], a[1])
    d2 = orient(b[0], b[1], b[2], b[3], a[2], a[3])
    d3 = orient(a[0], a[1], a[2], a[3], b[0], b[1])
    d4 = orient(a[0], a[1], a[2], a[3], b[2], b[3])
    return (d1 * d2 < -1e-9) and (d3 * d4 < -1e-9)


def _name(element: wire.Element, keys: dict[str, str]) -> str:
    """How a finding names a shape: by its label, else by its spec node key, else (for a
    document checked without its spec) by its kind and the start of its id."""
    core = element.core
    text = core.text_content.string.replace("\n", " ").strip()
    if text:
        return f"'{text}'"
    key = keys.get(core.id.upper())
    return f"node '{key}'" if key else f"{core.kind} {core.id[:8]}"


def _collinear_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """True when two horizontal or two vertical segments run along each other."""
    for fixed, low, high in ((1, 0, 2), (0, 1, 3)):
        aligned = abs(a[fixed] - a[fixed + 2]) < 0.5 and abs(b[fixed] - b[fixed + 2]) < 0.5
        if aligned and abs(a[fixed] - b[fixed]) < 1.5:
            a_low, a_high = sorted((a[low], a[high]))
            b_low, b_high = sorted((b[low], b[high]))
            if min(a_high, b_high) - max(a_low, b_low) > 6:
                return True
    return False


def _own_end_inset(frame: wire.Rect, point: wire.ConnectorPoint) -> float:
    """How far in to test a connector against the shape it starts or ends on.

    A connection point may lie inside the frame, such as a lead end a little way in from
    the edge; the stub leaving it must not count as running back through the shape.
    """
    inside = min(
        point.x - frame.x, frame.x + frame.width - point.x,
        point.y - frame.y, frame.y + frame.height - point.y,
    )
    return max(3.0, inside + 0.5)


def _solid_part(element: wire.Element) -> wire.Rect:
    """The part of a shape a connector should not cross: its frame, or a lifeline's head,
    since the rest of a lifeline is open and its messages cross other lifelines' lines."""
    frame = element.core.frame
    shape = element.complex_shape
    if shape is None or shape.type != "lifeline":
        return frame
    head, _ = wire.lifeline_line(shape, frame)
    return wire.Rect(x=frame.x, y=frame.y, width=frame.width, height=max(head, 1e-9))


def _complex_text_findings(page_name: str, element: wire.Element, keys: dict[str, str]) -> list[Finding]:
    """Warnings for the text a container, swimlanes, table or lifeline probably cannot show
    whole: a container's title wider than its band, a lane title longer than its lane, or a
    lifeline's name wider than its head. Table cells are sized to their text by the builder."""
    shape, core = element.complex_shape, element.core
    assert shape is not None
    findings: list[Finding] = []

    def width_of(text: wire.TextContent) -> float:
        style = text.base_style
        return max(
            (estimate_text_size(line, style.font_size, style.weight == "bold")[0] for line in text.string.split("\n")),
            default=0.0,
        )

    def warn(message: str) -> None:
        findings.append(Finding(severity="warning", code="label-overflow", message=f"{page_name}: {message}"))

    name = _name(element, keys)
    if shape.type == "container" and shape.title_style is None and width_of(core.text_content) > core.frame.width - 24:
        warn(f"the title of {name} is wider than its band and will wrap out of it. Widen it or shorten the title.")
    if shape.type == "lifeline":
        head = "box" if shape.head_style is None else "actor"
        if width_of(core.text_content) > core.frame.width - (12 if head == "box" else 0):
            warn(f"the name of lifeline {name} probably does not fit its head. Give it a width or a shorter name.")
    if shape.type == "swimlanes":
        for lane, frame in zip(shape.lanes or [], wire.swimlane_frames(shape, core.frame), strict=True):
            length = frame.height if shape.direction == "horizontal" else frame.width
            if lane.title.string and width_of(lane.title) > length - 8:
                warn(
                    f"the lane title '{lane.title.string}' of {name} is longer than its "
                    f"{length:g}-point lane. Shorten it, or space the lane's rows further apart."
                )
    return findings


def lint(
    document: wire.Document, catalog: Catalog | None = None, spec: DiagramSpec | None = None
) -> list[Finding]:
    """Checks a document for things the app accepts but a reader would not.

    Errors are certain defects, such as a library shape the app will draw as a
    placeholder. Warnings are layout problems: overlaps, connectors through
    shapes or labels, crossings, connectors drawn over each other and labels
    that do not fit. Sizes of text are estimates, so label warnings are advice.
    Given the spec the document was compiled from, a finding names a shape
    without a label by its node key.
    """
    catalog = catalog or Catalog.load()
    findings: list[Finding] = []
    keys = (
        {
            _node_id(document.id, page_index, node.key): node.key
            for page_index, page in enumerate(spec.pages)
            for node in page.nodes
        }
        if spec is not None
        else {}
    )

    def warn(code: str, message: str) -> None:
        findings.append(Finding(severity="warning", code=code, message=message))

    for page in document.pages:
        page_name = page.core.name
        shapes = [element for element in page.elements if element.core.kind != "path"]
        label_areas: list[tuple[wire.Element, wire.Rect]] = []
        # Containers and swimlanes are drawn around other shapes and connectors run into
        # them, so they neither overlap nor block anything. Of a lifeline only the head does.
        holders = {
            element.core.id.upper() for element in shapes
            if element.complex_shape is not None and element.complex_shape.holds_shapes
        }
        solid = {element.core.id.upper(): _solid_part(element) for element in shapes}

        for element in page.elements:
            core = element.core
            reference = core.symbol_reference
            if reference and catalog.find_reference(
                reference.library_id, reference.item_id, reference.asset_version
            ) is None:
                findings.append(
                    Finding(
                        severity="error",
                        code="unresolved-shape",
                        message=(
                            f"{page_name}: {reference.library_id} / {reference.item_id} "
                            f"(version {reference.asset_version}) is not packaged with "
                            f"SimpleDiagrams {catalog.source_app_version}. The app would draw a "
                            "dashed placeholder. Choose a shape returned by find_shapes.py."
                        ),
                    )
                )
            text = core.text_content
            layout = element.content.text_layout
            if element.complex_shape is not None and element.complex_shape.type != "callout":
                findings.extend(_complex_text_findings(page_name, element, keys))
                continue
            if not text.string:
                continue
            style = text.base_style
            bold = style.weight == "bold"
            longest_word = max(text.string.split(), key=len, default="")
            word_width, _ = estimate_text_size(longest_word, style.font_size, bold)
            full_width, line_height = estimate_text_size(text.string.replace("\n", " "), style.font_size, bold)
            if layout is not None and layout.position in ("above", "below"):
                area = outside_label_rect(core.frame, layout, text)
                if area is not None:
                    label_areas.append((element, area))
                if word_width > max(1.0, layout.frame.width * core.frame.width):
                    warn(
                        "label-overflow",
                        f"{page_name}: the label {_name(element, keys)} is wider than its "
                        f"{core.frame.width:g}-point shape and will break mid-word. Widen the shape or "
                        "put the label in a separate text node.",
                    )
                continue
            inside = core.kind != "text"
            inner_width = max(1.0, core.frame.width - 20) if inside else core.frame.width
            inner_height = max(1.0, core.frame.height - 16) if inside else core.frame.height
            wrapped_lines = max(text.string.count("\n") + 1, math.ceil(full_width / inner_width))
            if word_width > inner_width or wrapped_lines * line_height > inner_height:
                warn(
                    "label-overflow",
                    f"{page_name}: the label {_name(element, keys)} probably does not fit its "
                    f"{core.frame.width:g} x {core.frame.height:g} shape. Widen the shape, "
                    "shorten the label, or set label_position to 'below'.",
                )

        for index, first in enumerate(shapes):
            for second in shapes[index + 1 :]:
                if "text" in (first.core.kind, second.core.kind):
                    continue
                if first.core.id.upper() in holders or second.core.id.upper() in holders:
                    continue
                a, b = first.core.frame, second.core.frame
                overlap_x = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
                overlap_y = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
                if overlap_x > 1 and overlap_y > 1:
                    warn("shapes-overlap", f"{page_name}: {_name(first, keys)} and {_name(second, keys)} overlap.")

        by_id = {element.core.id.upper(): element for element in page.elements}
        connectors: list[tuple[wire.ConnectionCore, list[tuple[float, float, float, float]], str]] = []
        for connection in page.connections:
            core = connection.content
            attachments = (core.start_attachment, core.end_attachment)
            attached = {attachment.element_id.upper() for attachment in attachments if attachment}
            segments = _segments(core.points)
            ends = " to ".join(
                _name(by_id[attachment.element_id.upper()], keys) if attachment else "a free end"
                for attachment in attachments
            )
            connectors.append((core, segments, ends))
            for element in shapes:
                if element.core.id.upper() in holders:
                    continue
                is_end = element.core.id.upper() in attached
                if is_end and element.core.rotation_degrees % 360 != 0:
                    warn(
                        "rotated-end",
                        f"{page_name}: {_name(element, keys)} is rotated and has a connector. The app "
                        "moves the attached end with the rotation, so the stored route will not "
                        "match. Leave connected shapes unrotated.",
                    )
                inset = 3.0
                body = solid[element.core.id.upper()]
                if is_end:
                    route = connection.content.points
                    for attachment, point in zip(attachments, (route[0], route[-1]), strict=True):
                        if attachment and attachment.element_id.upper() == element.core.id.upper():
                            # Both ends may be on this shape; each one's stub is its own.
                            inset = max(inset, _own_end_inset(body, point))
                if not any(_segment_hits_rect(segment, body, inset) for segment in segments):
                    continue
                if is_end:
                    warn(
                        "connector-through-shape",
                        f"{page_name}: the connector from {ends} runs back through {_name(element, keys)}, "
                        "one of its own ends. Change or remove its sides or points.",
                    )
                else:
                    warn(
                        "connector-through-shape",
                        f"{page_name}: the connector from {ends} passes through {_name(element, keys)}. "
                        "Move a node, or set source_side and target_side.",
                    )
            for element, area in label_areas:
                if any(_segment_hits_rect(segment, area, inset=1) for segment in segments):
                    warn(
                        "connector-through-label",
                        f"{page_name}: the connector from {ends} runs through the label of "
                        f"{_name(element, keys)}. Put the label on the other side of the shape, or set "
                        "source_side and target_side.",
                    )

        crossings = 0
        for index, (first_core, first_segments, first_ends) in enumerate(connectors):
            for second_core, second_segments, second_ends in connectors[index + 1 :]:
                if any(_segments_cross(a, b) for a in first_segments for b in second_segments):
                    crossings += 1
                # Connectors meeting at one point, whichever way each runs, join there and share
                # its stub; two joining the same two points are drawn on top of each other.
                second_points = (second_core.start_attachment, second_core.end_attachment)
                shared = [
                    point for point in (first_core.start_attachment, first_core.end_attachment)
                    if point is not None and point in second_points
                ]
                if len(shared) != 1 and any(
                    _collinear_overlap(a, b) for a in first_segments for b in second_segments
                ):
                    warn(
                        "connectors-overlap",
                        f"{page_name}: the connectors from {first_ends} and from {second_ends} are "
                        "drawn on top of each other. For a two-way relationship use one connector "
                        "with an ending at both ends; otherwise give them different sides.",
                    )
        if crossings:
            warn(
                "connectors-cross",
                f"{page_name}: {crossings} pair(s) of connectors cross. Reorder nodes within "
                "a row or column so connected nodes are neighbours.",
            )

    return findings
