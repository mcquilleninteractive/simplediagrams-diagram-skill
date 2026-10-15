"""Read the public shape catalogue with a bounded, anonymous HTTP request.

The API is the authority after a successful fetch. Each command makes at most one
request and stores nothing; the bundled packaged-library snapshot keeps discovery
usable without the network.
Nothing here downloads artwork or executes catalogue content. Placement code
must copy a shape's ``reference`` unchanged and check desktop support itself.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.message import Message
from http.client import HTTPException
from pathlib import Path
from typing import IO, Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

CATALOGUE_URL = "https://simplediagrams.com/shape-libraries/catalog.json"
BUNDLED_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "built-in-shapes.json"
)
MAX_CATALOGUE_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 10
_MAX_NUMBER = 2_147_483_647


def _plain_text(value: str) -> str:
    """Keep catalogue text inert and suitable for terminals and document text."""
    if any(
        (unicodedata.category(character) in {"Cc", "Cs"} and character not in "\t\n\r")
        or character in "\ufffe\uffff"
        for character in value
    ):
        raise ValueError("text contains an unsupported control character")
    if len(value.encode("utf-8")) > 40_000:
        raise ValueError("text exceeds the byte limit")
    return value


Identifier = Annotated[
    str, Field(min_length=1, max_length=256), AfterValidator(_plain_text)
]
Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_plain_text)]
Description = Annotated[str, Field(max_length=10_000), AfterValidator(_plain_text)]
PublishedUUID = Annotated[
    str,
    Field(pattern=r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"),
]
PositiveNumber = Annotated[float, Field(gt=0, le=1_000_000, allow_inf_nan=False)]
Revision = Annotated[int, Field(ge=1, le=_MAX_NUMBER)]


class CatalogueModel(BaseModel):
    """Validate known v1 fields strictly while allowing additive API fields."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, strict=True, allow_inf_nan=False
    )


class CatalogueShapeReference(CatalogueModel):
    """The exact received identifier triple to copy into ``symbol_reference``."""

    library_id: Identifier
    item_id: Identifier
    asset_version: Revision


class CatalogueConnectionPoint(CatalogueModel):
    """One explicit numbered anchor, with coordinates relative to the frame."""

    id: int = Field(ge=0, le=_MAX_NUMBER)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CatalogueTextRegion(CatalogueModel):
    """Where a shape's label is laid out, as fractions of its frame, inside it."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_the_frame(self) -> CatalogueTextRegion:
        """The app refuses a label region that leaves its shape."""
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("the text region extends beyond the shape")
        return self


class CatalogueShape(CatalogueModel):
    """Search and placement facts for one shape, excluding its artwork."""

    item_id: PublishedUUID
    slug: Annotated[
        str, Field(min_length=1, max_length=200), AfterValidator(_plain_text)
    ]
    display_name: Name
    description: Description
    keywords: tuple[
        Annotated[
            str, Field(min_length=1, max_length=128), AfterValidator(_plain_text)
        ],
        ...,
    ] = Field(max_length=128)
    default_width: PositiveNumber
    default_height: PositiveNumber
    connection_points: (
        Literal["standard"]
        | Annotated[tuple[CatalogueConnectionPoint, ...], Field(max_length=128)]
    )
    reference: CatalogueShapeReference
    # Where the library puts the label (desktop ADR 0042). Absent means the app's own inset
    # and the middle. The bundled list carries them for packaged shapes; the website
    # catalogue may add them later, and is read the same way when it does.
    text_region: CatalogueTextRegion | None = None
    text_position: Literal["above", "top", "middle", "bottom", "below"] | None = None

    @model_validator(mode="after")
    def unique_connection_points(self) -> CatalogueShape:
        """Repeated anchor numbers cannot truthfully describe an attachment."""
        if self.connection_points != "standard":
            ids = [point.id for point in self.connection_points]
            if len(ids) != len(set(ids)):
                raise ValueError("connection point ids must be unique")
        return self


class CatalogueLibrary(CatalogueModel):
    """A complete ordered public library and its authoritative placement facts."""

    library_id: PublishedUUID
    readable_id: Identifier
    display_name: Name
    description: Description
    built_in: bool
    revision: Revision
    page_url: Annotated[
        str, Field(min_length=1, max_length=2048), AfterValidator(_plain_text)
    ]
    shapes: tuple[CatalogueShape, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def consistent_shapes(self) -> CatalogueLibrary:
        """Prevent ambiguous search entries and references to a different library."""
        slugs = [shape.slug for shape in self.shapes]
        references = [shape.reference.item_id for shape in self.shapes]
        if len(slugs) != len(set(slugs)) or len(references) != len(set(references)):
            raise ValueError(
                "shape slugs and placement identifiers must be unique within a library"
            )
        expected_library = self.readable_id if self.built_in else self.library_id
        for shape in self.shapes:
            if shape.reference.library_id != expected_library:
                raise ValueError("shape reference names a different library")
            if not self.built_in and shape.reference.item_id != shape.item_id:
                raise ValueError(
                    "downloadable shape reference differs from its published identifier"
                )
        return self


class ShapeLibraryCatalogue(CatalogueModel):
    """The complete version 1 response, bounded before and after JSON parsing."""

    catalog_version: Literal[1]
    updated_at: AwareDatetime
    libraries: tuple[CatalogueLibrary, ...] = Field(max_length=1000)

    @field_validator("catalog_version", mode="before")
    @classmethod
    def actual_version_number(cls, value: object) -> object:
        """A boolean must not masquerade as the version number one."""
        if type(value) is not int:
            raise ValueError("catalog_version must be an integer")
        return value

    @field_validator("updated_at")
    @classmethod
    def whole_utc_second(cls, value: datetime) -> datetime:
        """Match the API's exact UTC timestamp contract."""
        if value.utcoffset() != timedelta(0) or value.microsecond:
            raise ValueError("updated_at must be a whole second in UTC")
        return value

    @model_validator(mode="after")
    def unique_identities(self) -> ShapeLibraryCatalogue:
        """Never allow one identifier to resolve to several shapes or libraries."""
        library_ids = [library.library_id for library in self.libraries]
        readable_ids = [library.readable_id.casefold() for library in self.libraries]
        item_ids = [
            shape.item_id for library in self.libraries for shape in library.shapes
        ]
        if len(item_ids) > 50_000:
            raise ValueError("catalogue has too many shapes")
        if (
            len(library_ids) != len(set(library_ids))
            or len(readable_ids) != len(set(readable_ids))
            or len(item_ids) != len(set(item_ids))
        ):
            raise ValueError("catalogue identifiers must be unique")
        return self


CatalogueSource = Literal["live", "bundled"]


class CatalogueResult(BaseModel):
    """A validated catalogue and an explicit account of where it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    catalogue: ShapeLibraryCatalogue
    source: CatalogueSource
    warning: str | None = None

    @property
    def libraries(self) -> tuple[CatalogueLibrary, ...]:
        """Return public libraries without a second mutable representation."""
        return self.catalogue.libraries

    @property
    def shapes(self) -> tuple[CatalogueShape, ...]:
        """Return shapes in library order for simple discovery clients."""
        return tuple(shape for library in self.libraries for shape in library.shapes)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the anonymous request at its fixed, reviewed HTTPS endpoint."""

    def redirect_request(
        self,
        req: urllib.request.Request | None,
        fp: IO[bytes] | None,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        """Refuse every redirect instead of contacting another address."""
        return


class CatalogueError(ValueError):
    """Report response bytes that cannot safely become a catalogue."""


def _fetch() -> ShapeLibraryCatalogue:
    """Make the one anonymous request and validate the whole answer before using it."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "SimpleDiagrams-Diagram-Skill/1",
    }
    request = urllib.request.Request(CATALOGUE_URL, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        error.close()
        raise
    with response:
        if response.status != 200 or response.geturl() != CATALOGUE_URL:
            raise CatalogueError("unexpected catalogue response")
        if response.headers.get_content_type() != "application/json":
            raise CatalogueError("catalogue response is not JSON")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise CatalogueError("unexpected catalogue content encoding")
        content_length = response.headers.get("Content-Length")
        if content_length is not None and (
            not content_length.isdecimal() or int(content_length) > MAX_CATALOGUE_BYTES
        ):
            raise CatalogueError("catalogue exceeds the byte limit")
        payload = response.read(MAX_CATALOGUE_BYTES + 1)
        if len(payload) > MAX_CATALOGUE_BYTES:
            raise CatalogueError("catalogue exceeds the byte limit")
        return ShapeLibraryCatalogue.model_validate_json(payload)


def _bundled_catalogue() -> ShapeLibraryCatalogue:
    """Adapt the shipped packaged snapshot, using only its recorded identifiers."""
    with BUNDLED_PATH.open("rb") as source:
        payload = source.read(MAX_CATALOGUE_BYTES + 1)
    if len(payload) > MAX_CATALOGUE_BYTES:
        raise CatalogueError("bundled catalogue exceeds the byte limit")
    bundled = json.loads(payload)
    if (
        bundled.get("catalog") != "com.simplediagrams.skill.built-in-shapes"
        or bundled.get("catalog_version") != 1
    ):
        raise CatalogueError("unsupported bundled catalogue")
    libraries = []
    for library in bundled["libraries"]:
        shapes = []
        for shape in library["shapes"]:
            shapes.append(
                {
                    "item_id": shape["published_item_id"],
                    "slug": shape.get("slug", shape["item_id"]),
                    "display_name": shape["display_name"],
                    "description": shape.get("description", ""),
                    "keywords": shape.get("keywords", []),
                    "default_width": shape["default_width"],
                    "default_height": shape["default_height"],
                    "connection_points": shape.get("connection_points", "standard"),
                    **{
                        key: shape[key]
                        for key in ("text_region", "text_position")
                        if shape.get(key) is not None
                    },
                    "reference": {
                        "library_id": library["library_id"],
                        "item_id": shape["item_id"],
                        "asset_version": library["asset_version"],
                    },
                }
            )
        libraries.append(
            {
                "library_id": library["published_library_id"],
                "readable_id": library["library_id"],
                "display_name": library["display_name"],
                "description": library.get("description", ""),
                "built_in": True,
                "revision": library.get("revision", 1),
                "page_url": library.get("page_url", CATALOGUE_URL),
                "shapes": shapes,
            }
        )
    return ShapeLibraryCatalogue.model_validate_json(
        json.dumps(
            {
                "catalog_version": 1,
                "updated_at": bundled.get("updated_at", "1970-01-01T00:00:00Z"),
                "libraries": libraries,
            }
        )
    )


def load_catalogue(*, offline: bool = False) -> CatalogueResult:
    """The current catalogue from one request, or the packaged list.

    Nothing is stored between runs, so each command asks once. `offline` makes no
    request. A failed request is reported and the packaged list used, never guessed data.
    """
    if offline:
        return CatalogueResult(
            catalogue=_bundled_catalogue(),
            source="bundled",
            warning="Offline: only packaged shapes are available.",
        )
    try:
        return CatalogueResult(catalogue=_fetch(), source="live")
    except (OSError, HTTPException, ValueError, RecursionError):
        return CatalogueResult(
            catalogue=_bundled_catalogue(),
            source="bundled",
            warning="The catalogue request failed; using packaged shapes only.",
        )
