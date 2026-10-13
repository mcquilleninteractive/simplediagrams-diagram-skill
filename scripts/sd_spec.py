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
import unicodedata
import uuid
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

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

if TYPE_CHECKING:
    from sd_catalog import ShapeLibraryCatalogue

NATIVE_KINDS = ("rectangle", "ellipse", "note", "text")
# What the app itself gives each kind when a person draws one.
DEFAULT_STYLE: dict[str, tuple[str, str, float]] = {
    "rectangle": ("#D8ECFF", "#343A40", 2),
    "ellipse": ("#DDF5E3", "#343A40", 2),
    "note": ("#FFF1A8", "#8A7636", 2),
    "text": ("#00000000", "#00000000", 0),
    "symbol": ("#FFFFFF", "#000000", 1),
}
DEFAULT_SIZE: dict[str, tuple[float, float]] = {
    "rectangle": (140, 70),
    "ellipse": (140, 70),
    "note": (140, 100),
}
# Mid-side anchors of the eight every shape carries.
SIDE_ANCHOR = {"left": 0, "right": 1, "top": 2, "bottom": 3}
SIDE_VECTOR = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}

# Rough advance of the app's standard font, as a fraction of the font size.
AVERAGE_GLYPH_WIDTH = 0.56
LINE_HEIGHT = 1.3
CHANNEL_SPACING = 16
CHANNEL_MARGIN = 10
STUB = 24
CAPTION_GAP = 4

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


class NodeSpec(SpecModel):
    """One shape on the page.

    Give either `col` and `row`, or `x` and `y`. Both name the node's centre,
    so nodes of different sizes still line up along shared centre lines.
    """

    key: Key = Field(description="Your own name for this node, unique on the page.")
    shape: str = Field(
        description=(
            "rectangle, ellipse, note or text for a plain drawn shape, or "
            "'<library>/<item>' for a library shape, for example 'basic/Cylinder'. "
            "Use a packaged selector returned by find_shapes.py; it searches the API "
            "and falls back to assets/built-in-shapes.json offline."
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
    label_position: wire.TextPosition = Field(
        default="middle",
        description=(
            "Use 'below' or 'above' for icons whose artwork would hide a label. A label wider "
            "than its shape is then written as a separate caption grouped with the shape."
        ),
    )
    fill: wire.Color | None = None
    stroke: wire.Color | None = None
    line_width: float | None = Field(default=None, ge=0, le=10_000, allow_inf_nan=False)
    text_color: wire.Color | None = None
    font_size: float = Field(default=15, ge=1, le=720, allow_inf_nan=False)
    bold: bool = False
    rotation: float = Field(default=0, ge=-360, le=360, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_position(self) -> NodeSpec:
        grid = self.col is not None and self.row is not None
        absolute = self.x is not None and self.y is not None
        partial = (self.col is None) != (self.row is None) or (self.x is None) != (self.y is None)
        if partial or grid == absolute:
            raise ValueError(f"node '{self.key}' needs either col and row, or x and y")
        return self


class EdgeSpec(SpecModel):
    """A connector between two nodes."""

    source: Key = Field(description="Key of the node the connector leaves.")
    target: Key = Field(description="Key of the node the connector arrives at.")
    label: Label = ""
    route: Literal["orthogonal", "straight", "curved"] = Field(
        default="orthogonal",
        description=(
            "orthogonal: horizontal and vertical runs only. straight: one direct line. "
            "curved: one direct line with a gentle bow."
        ),
    )
    source_side: Side | None = Field(default=None, description="Chosen automatically if omitted.")
    target_side: Side | None = Field(default=None, description="Chosen automatically if omitted.")
    start_ending: wire.Ending = "none"
    end_ending: wire.Ending = "arrow"
    pattern: wire.StrokePattern = "solid"
    stroke: wire.Color = "#495057"
    line_width: float = Field(default=2, ge=0, le=10_000, allow_inf_nan=False)


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
        known = set(keys)
        for edge in self.edges:
            for end in (edge.source, edge.target):
                if end not in known:
                    raise ValueError(f"page '{self.name}' has an edge to unknown node '{end}'")
            if edge.source == edge.target:
                raise ValueError(f"page '{self.name}' has an edge from '{edge.source}' to itself")
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
    """A discovered shape with its exact placement reference and availability."""

    model_config = ConfigDict(frozen=True)

    library_id: str
    library_short_name: str
    library_display_name: str
    asset_version: int
    item_id: str
    display_name: str
    default_width: float
    default_height: float
    built_in: bool = True
    readable_library_id: str = ""
    slug: str = ""
    description: str = ""
    keywords: tuple[str, ...] = ()
    page_url: str = ""

    @property
    def selector(self) -> str:
        """Use shipped item names for packaged shapes and slugs for discovery."""
        item = self.item_id if self.built_in else self.slug
        return f"{self.library_short_name}/{item}"


class Catalog:
    """Searchable library metadata; only packaged references are placeable today."""

    def __init__(self, shapes: list[CatalogShape], source_app_version: str) -> None:
        self.shapes = shapes
        self.source_app_version = source_app_version
        self.source = "bundled"
        self.warning: str | None = None
        self._by_reference = {(shape.library_id, shape.item_id): shape for shape in shapes}
        self._short_names: dict[str, str | None] = {}
        self._readable_ids = {shape.readable_library_id: shape.library_id for shape in shapes}
        self._library_ids = {shape.library_id for shape in shapes}
        self._by_selector = dict(self._by_reference)
        for shape in shapes:
            short = shape.library_short_name.lower()
            if short in self._short_names and self._short_names[short] != shape.library_id:
                self._short_names[short] = None
            else:
                self._short_names[short] = shape.library_id
            if not shape.built_in:
                self._by_selector[(shape.library_id, shape.slug)] = shape

    @classmethod
    def from_catalogue(
        cls, catalogue: ShapeLibraryCatalogue, *, source: str, warning: str | None = None
    ) -> Catalog:
        """Copy API references unchanged, including their asset versions."""
        shapes = [
            CatalogShape(
                library_id=shape.reference.library_id,
                library_short_name=library.readable_id.rsplit(".", 1)[-1],
                library_display_name=library.display_name,
                readable_library_id=library.readable_id,
                asset_version=shape.reference.asset_version,
                item_id=shape.reference.item_id,
                display_name=shape.display_name,
                default_width=shape.default_width,
                default_height=shape.default_height,
                built_in=library.built_in,
                slug=shape.slug,
                description=shape.description,
                keywords=tuple(shape.keywords),
                page_url=library.page_url,
            )
            for library in catalogue.libraries
            for shape in library.shapes
        ]
        result = cls(shapes, "the current catalogue")
        result.source, result.warning = source, warning
        return result

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> Catalog:
        """Read the bundled fallback without network access, useful for pure checks."""
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
                readable_library_id=library["library_id"],
                slug=item.get("slug", item["item_id"]),
                description=item.get("description", ""),
                keywords=tuple(item.get("keywords", [])),
            )
            for library in data["libraries"]
            for item in library["shapes"]
        ]
        return cls(shapes, data["source_app_version"])

    @classmethod
    def load_current(
        cls, *, cache_path: Path | None = None, offline: bool = False, refresh: bool = False
    ) -> Catalog:
        """Load one current snapshot for a complete CLI search or build."""
        from sd_catalog import load_catalogue

        result = load_catalogue(cache_path=cache_path, offline=offline, refresh=refresh)
        return cls.from_catalogue(result.catalogue, source=result.source, warning=result.warning)

    def resolve(self, library: str, item: str) -> CatalogShape | None:
        """Finds a shape by full library id or short name. Item ids are case sensitive."""
        library_id = (
            library if library in self._library_ids
            else self._readable_ids.get(library) or self._short_names.get(library.lower())
        )
        if library_id is None:
            return None
        return self._by_selector.get((library_id, item))

    def find_reference(self, library_id: str, item_id: str, asset_version: int) -> CatalogShape | None:
        shape = self._by_reference.get((library_id, item_id))
        return shape if shape and shape.built_in and shape.asset_version == asset_version else None

    def suggestions(self, library: str, item: str) -> list[str]:
        """Close names to offer when a shape is not found."""
        wanted = item.lower()
        return sorted(
            f"{shape.library_short_name}/{shape.item_id}"
            for shape in self.shapes
            if wanted in shape.item_id.lower() or shape.item_id.lower() in wanted
        )[:8]


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class SpecError(ValueError):
    """A spec that is well formed but cannot be turned into a document."""


def load_spec(path: Path) -> DiagramSpec:
    """Reads a spec file, refusing an oversized one before parsing it.

    Raises:
        SpecError: The file is missing, too large, or not a valid spec.
    """
    try:
        size = path.stat().st_size
    except OSError as failure:
        raise SpecError(f"Cannot read the spec {path}: {failure.strerror}") from failure
    if size > MAX_SPEC_BYTES:
        raise SpecError(f"The spec {path} is {size} bytes; the limit is {MAX_SPEC_BYTES}.")
    try:
        return DiagramSpec.model_validate_json(path.read_bytes())
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


def _snap(value: float) -> float:
    return float(round(value * 1000) / 1000)


class _Placed:
    """A node after sizing, with the geometry edges are routed against."""

    def __init__(self, spec: NodeSpec, element_id: str, x: float, y: float, w: float, h: float) -> None:
        self.spec = spec
        self.element_id = element_id
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def rect(self) -> wire.Rect:
        return wire.Rect(x=self.x, y=self.y, width=float(self.w), height=float(self.h))

    def anchor(self, side: str) -> tuple[float, float]:
        return {
            "left": (self.x, self.cy),
            "right": (self.x + self.w, self.cy),
            "top": (self.cx, self.y),
            "bottom": (self.cx, self.y + self.h),
        }[side]


def _node_size(node: NodeSpec, catalog_shape: CatalogShape | None) -> tuple[float, float]:
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


def _choose_route(
    edge: EdgeSpec, source: _Placed, target: _Placed, obstacles: list[wire.Rect]
) -> tuple[str, str, _Route]:
    """Picks sides, honouring any the spec fixed, that keep the route off everything else."""
    candidates = [
        (side_a, side_b)
        for side_a, side_b in _candidate_sides(source, target)
        if edge.source_side in (None, side_a) and edge.target_side in (None, side_b)
    ]
    if not candidates:
        preferred = _candidate_sides(source, target)[0]
        candidates = [(edge.source_side or preferred[0], edge.target_side or preferred[1])]
    best: tuple[int, str, str, _Route] | None = None
    for side_a, side_b in candidates:
        route = _orthogonal(source.anchor(side_a), side_a, target.anchor(side_b), side_b)
        segments = [(p[0], p[1], q[0], q[1]) for p, q in pairwise(route.points)]
        hits = sum(
            any(_segment_hits_rect(segment, obstacle) for segment in segments)
            for obstacle in [*obstacles, source.rect, target.rect]
        )
        if best is None or hits < best[0]:
            best = (hits, side_a, side_b, route)
        if hits == 0:
            break
    assert best is not None
    return best[1], best[2], best[3]


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

    Raises:
        SpecError: A node names a shape that is not built into SimpleDiagrams.
    """
    catalog = catalog or Catalog.load()
    document_id = spec.id.upper() if spec.id else str(uuid.uuid4()).upper()
    namespace = uuid.UUID(document_id)
    pages: list[wire.Page] = []

    for page_index, page in enumerate(spec.pages):
        placed: dict[str, _Placed] = {}
        elements: list[wire.Element] = []
        groups: list[wire.Group] = []
        label_areas: list[wire.Rect] = []

        for node in page.nodes:
            catalog_shape: CatalogShape | None = None
            if node.shape in NATIVE_KINDS:
                kind = node.shape
            else:
                library, separator, item = node.shape.partition("/")
                if not separator:
                    raise SpecError(
                        f"node '{node.key}': shape '{node.shape}' is not rectangle, ellipse, "
                        "note, text or '<library>/<item>'"
                    )
                catalog_shape = catalog.resolve(library, item)
                if catalog_shape is None:
                    hint = catalog.suggestions(library, item)
                    raise SpecError(
                        f"node '{node.key}': '{node.shape}' is not in the selected catalogue."
                        + (f" Did you mean: {', '.join(hint)}?" if hint else "")
                    )
                if not catalog_shape.built_in:
                    raise SpecError(
                        f"node '{node.key}': {catalog_shape.display_name} belongs to "
                        f"{catalog_shape.library_display_name}, a downloaded library. "
                        "SimpleDiagrams 5.0.16 cannot resolve its reference in a generated "
                        "document, even when installed. Place it manually in the app to embed "
                        "the artwork, or choose a packaged shape. Nothing has been written."
                    )
                kind = "symbol"

            width, height = _node_size(node, catalog_shape)
            if node.col is not None and node.row is not None:
                centre_x = page.grid.origin_x + node.col * page.grid.column_pitch
                centre_y = page.grid.origin_y + node.row * page.grid.row_pitch
            else:
                centre_x, centre_y = node.x, node.y
            element_id = _new_id(namespace, f"page:{page_index}:node:{node.key}")
            item_placed = _Placed(
                node, element_id, _snap(centre_x - width / 2), _snap(centre_y - height / 2), width, height
            )
            placed[node.key] = item_placed

            fill, stroke, line_width = DEFAULT_STYLE[kind]
            base_style = wire.character_style(
                font_size=float(node.font_size),
                weight="bold" if node.bold else "medium",
                color_hex=node.text_color or "#212529",
            )
            outside = node.label_position in ("above", "below") and bool(node.label) and kind != "text"
            label_width, label_height = estimate_text_size(node.label, node.font_size, node.bold)
            # A label outside its shape is confined to the shape's width. One
            # that would wrap becomes a separate caption grouped with the shape.
            caption = outside and label_width > width
            text_layout: wire.TextLayout | None = None
            if node.label_position != "middle" and not caption and kind != "text":
                if outside:
                    frame = wire.TextLayoutFrame(x=0.0, y=0.0, width=1.0, height=1.0)
                else:
                    # The app's own default label region: a 10 by 8 point inset.
                    inset_x, inset_y = min(10, max(0, (width - 1) / 2)), min(8, max(0, (height - 1) / 2))
                    frame = wire.TextLayoutFrame(
                        x=inset_x / width, y=inset_y / height,
                        width=max(0.001, (width - 2 * inset_x) / width),
                        height=max(0.001, (height - 2 * inset_y) / height),
                    )
                text_layout = wire.TextLayout(frame=frame, position=node.label_position)
            text = wire.text_content("" if caption else node.label, base_style=base_style)
            elements.append(
                wire.element(
                    id=element_id,
                    kind=kind,
                    frame=item_placed.rect,
                    rotation_degrees=float(node.rotation % 360),
                    z_index=len(elements),
                    text=text,
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
                    text_layout=text_layout,
                )
            )
            if caption:
                caption_width, caption_height = math.ceil(label_width + 24), math.ceil(label_height + 12)
                caption_top = (
                    item_placed.y - CAPTION_GAP - caption_height
                    if node.label_position == "above"
                    else item_placed.y + height + CAPTION_GAP
                )
                caption_frame = wire.Rect(
                    x=_snap(item_placed.cx - caption_width / 2), y=_snap(caption_top),
                    width=float(caption_width), height=float(caption_height),
                )
                caption_id = _new_id(namespace, f"page:{page_index}:caption:{node.key}")
                caption_fill, caption_stroke, caption_line = DEFAULT_STYLE["text"]
                elements.append(
                    wire.element(
                        id=caption_id, kind="text", frame=caption_frame, z_index=len(elements),
                        text=wire.text_content(node.label, base_style=base_style),
                        style=wire.ElementStyle(
                            fill_hex=caption_fill, stroke_hex=caption_stroke, line_width=float(caption_line)
                        ),
                    )
                )
                groups.append(
                    wire.Group(
                        id=_new_id(namespace, f"page:{page_index}:group:{node.key}"),
                        members=[
                            wire.GroupMember(kind="element", id=element_id),
                            wire.GroupMember(kind="element", id=caption_id),
                        ],
                        is_locked=False, rotation_degrees=0.0,
                    )
                )
                label_areas.append(caption_frame)
            elif text_layout is not None:
                area = outside_label_rect(item_placed.rect, text_layout, text)
                if area is not None:
                    label_areas.append(area)

        routed: list[tuple[EdgeSpec, _Placed, _Placed, str, str, _Route | None]] = []
        for edge in page.edges:
            source, target = placed[edge.source], placed[edge.target]
            obstacles = [
                other.rect for other in placed.values() if other is not source and other is not target
            ] + label_areas
            side_a, side_b, route = _choose_route(edge, source, target, obstacles)
            routed.append((edge, source, target, side_a, side_b, route if edge.route == "orthogonal" else None))

        _spread_channels(
            [
                (route, (source.element_id, side_a), (target.element_id, side_b))
                for _, source, target, side_a, side_b, route in routed
                if route is not None
            ]
        )

        connections: list[wire.Connection] = []
        for edge_index, (edge, source, target, side_a, side_b, route) in enumerate(routed):
            start, end = source.anchor(side_a), target.anchor(side_b)
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
            label = (
                wire.ConnectorLabel(
                    content=wire.text_content(edge.label, base_style=wire.character_style(font_size=13.0)),
                    position=0.5, normal_offset=0.0,
                )
                if edge.label
                else None
            )
            connections.append(
                wire.connection(
                    id=_new_id(namespace, f"page:{page_index}:edge:{edge_index}"),
                    points=[wire.ConnectorPoint(x=_snap(px), y=_snap(py), kind=kind) for px, py, kind in route_points],
                    start_attachment=wire.Attachment(
                        element_id=source.element_id, connection_point_id=SIDE_ANCHOR[side_a]
                    ),
                    end_attachment=wire.Attachment(
                        element_id=target.element_id, connection_point_id=SIDE_ANCHOR[side_b]
                    ),
                    stroke_hex=edge.stroke,
                    line_width=float(edge.line_width),
                    stroke_pattern=edge.pattern,
                    start_ending=edge.start_ending,
                    end_ending=edge.end_ending,
                    label=label,
                )
            )

        pages.append(
            wire.page(
                id=_new_id(namespace, f"page:{page_index}"),
                name=page.name,
                elements=elements,
                connections=connections,
                groups=groups,
                background=wire.Background(kind="solid", color_hex=page.background) if page.background else None,
            )
        )

    return wire.document(id=document_id, name=spec.name, pages=pages)


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


def _name(element: wire.Element) -> str:
    core = element.core
    text = core.text_content.string.replace("\n", " ").strip()
    return f"'{text}'" if text else f"{core.kind} {core.id[:8]}"


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


def lint(document: wire.Document, catalog: Catalog | None = None) -> list[Finding]:
    """Checks a document for things the app accepts but a reader would not.

    Errors are certain defects, such as a library shape the app will draw as a
    placeholder. Warnings are layout problems: overlaps, connectors through
    shapes or labels, crossings, connectors drawn over each other and labels
    that do not fit. Sizes of text are estimates, so label warnings are advice.
    """
    catalog = catalog or Catalog.load()
    findings: list[Finding] = []

    def warn(code: str, message: str) -> None:
        findings.append(Finding(severity="warning", code=code, message=message))

    for page in document.pages:
        page_name = page.core.name
        shapes = [element for element in page.elements if element.core.kind != "path"]
        label_areas: list[tuple[wire.Element, wire.Rect]] = []

        for element in page.elements:
            core = element.core
            reference = core.symbol_reference
            if reference and not catalog.find_reference(
                reference.library_id, reference.item_id, reference.asset_version
            ):
                findings.append(
                    Finding(
                        severity="error",
                        code="unresolved-shape",
                        message=(
                            f"{page_name}: {reference.library_id} / {reference.item_id} "
                            f"(version {reference.asset_version}) is not built into SimpleDiagrams "
                            f"{catalog.source_app_version}. The app would draw a dashed placeholder. "
                            "Choose a packaged shape returned by find_shapes.py."
                        ),
                    )
                )
            text = core.text_content
            layout = element.content.text_layout
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
                        f"{page_name}: the label {_name(element)} is wider than its "
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
                    f"{page_name}: the label {_name(element)} probably does not fit its "
                    f"{core.frame.width:g} x {core.frame.height:g} shape. Widen the shape, "
                    "shorten the label, or set label_position to 'below'.",
                )

        for index, first in enumerate(shapes):
            for second in shapes[index + 1 :]:
                if "text" in (first.core.kind, second.core.kind):
                    continue
                a, b = first.core.frame, second.core.frame
                overlap_x = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
                overlap_y = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
                if overlap_x > 1 and overlap_y > 1:
                    warn("shapes-overlap", f"{page_name}: {_name(first)} and {_name(second)} overlap.")

        by_id = {element.core.id.upper(): element for element in page.elements}
        connectors: list[tuple[wire.ConnectionCore, list[tuple[float, float, float, float]], str]] = []
        for connection in page.connections:
            core = connection.content
            attachments = (core.start_attachment, core.end_attachment)
            attached = {attachment.element_id.upper() for attachment in attachments if attachment}
            segments = _segments(core.points)
            ends = " to ".join(
                _name(by_id[attachment.element_id.upper()]) if attachment else "a free end"
                for attachment in attachments
            )
            connectors.append((core, segments, ends))
            for element in shapes:
                is_end = element.core.id.upper() in attached
                if is_end and element.core.rotation_degrees % 360 != 0:
                    warn(
                        "rotated-end",
                        f"{page_name}: {_name(element)} is rotated and has a connector. The app "
                        "moves the attached end with the rotation, so the stored route will not "
                        "match. Leave connected shapes unrotated.",
                    )
                if not any(_segment_hits_rect(segment, element.core.frame) for segment in segments):
                    continue
                if is_end:
                    warn(
                        "connector-through-shape",
                        f"{page_name}: the connector from {ends} runs back through {_name(element)}, "
                        "one of its own ends. Change or remove source_side and target_side.",
                    )
                else:
                    warn(
                        "connector-through-shape",
                        f"{page_name}: the connector from {ends} passes through {_name(element)}. "
                        "Move a node, or set source_side and target_side.",
                    )
            for element, area in label_areas:
                if any(_segment_hits_rect(segment, area, inset=1) for segment in segments):
                    warn(
                        "connector-through-label",
                        f"{page_name}: the connector from {ends} runs through the label of "
                        f"{_name(element)}. Put the label on the other side of the shape, or set "
                        "source_side and target_side.",
                    )

        crossings = 0
        for index, (first, first_segments, first_ends) in enumerate(connectors):
            for second, second_segments, second_ends in connectors[index + 1 :]:
                if any(_segments_cross(a, b) for a in first_segments for b in second_segments):
                    crossings += 1
                shares_end = (
                    first.start_attachment is not None and first.start_attachment == second.start_attachment
                ) or (first.end_attachment is not None and first.end_attachment == second.end_attachment)
                if not shares_end and any(
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
