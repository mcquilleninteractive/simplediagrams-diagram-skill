"""Exercise catalogue discovery without contacting any production service.

The reader must preserve placement references, validate untrusted response
bytes, store nothing between runs, and fall back honestly to the packaged list.
A controlled opener isolates every test from the network.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sd_catalog as catalog

LIBRARY_ID = "657227F7-7B3E-86B4-BB6F-79190E1592B3"
ITEM_ID = "43585F7D-3420-8BA8-BFF0-8962EA373A62"
SECOND_ID = "C39204AF-120A-84AF-9BEB-D93C41ED90A0"


def _document() -> dict[str, Any]:
    """Provide realistic wire fields without consulting a live API."""
    return {
        "catalog_version": 1,
        "updated_at": "2026-10-13T10:00:00Z",
        "libraries": [
            {
                "library_id": LIBRARY_ID,
                "readable_id": "com.simplediagrams.shapeLibrary.basic",
                "display_name": "Basic",
                "description": "Packaged shapes",
                "built_in": True,
                "revision": 2,
                "page_url": "https://simplediagrams.com/shape-libraries/basic/",
                "shapes": [
                    {
                        "item_id": ITEM_ID,
                        "slug": "square",
                        "display_name": "Square",
                        "description": "A square",
                        "keywords": ["box", "square"],
                        "default_width": 50,
                        "default_height": 50,
                        "connection_points": "standard",
                        "reference": {
                            "library_id": "com.simplediagrams.shapeLibrary.basic",
                            "item_id": "Square",
                            "asset_version": 1,
                        },
                    }
                ],
            }
        ],
    }


class _Response(io.BytesIO):
    """Expose the HTTP properties the reader uses, with controlled bytes."""

    def __init__(self, body: bytes, **headers: str) -> None:
        super().__init__(body)
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value

    def geturl(self) -> str:
        """Keep the fake at the single reviewed endpoint."""
        return catalog.CATALOGUE_URL


class _Opener:
    """Record one request and yield exactly the response the test supplies."""

    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[urllib.request.Request, int]] = []

    def open(self, request: urllib.request.Request, *, timeout: int) -> _Response:
        """Capture request facts and simulate transport without networking."""
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _transport(
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, Any] | None = None,
    *,
    error: Exception | None = None,
    body: bytes | None = None,
    **headers: str,
) -> _Opener:
    """Install one fake opener; calls remain available for meaningful assertions."""
    response = (
        error
        if error is not None
        else _Response(
            body if body is not None else json.dumps(document or _document()).encode(),
            **headers,
        )
    )
    opener = _Opener(response)
    monkeypatch.setattr(
        catalog.urllib.request, "build_opener", lambda *handlers: opener
    )
    return opener


def test_live_fetch_preserves_references_and_additive_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public identity must never replace a packaged placement reference."""
    document = _document()
    document["future_field"] = {"untrusted": "inert"}
    document["libraries"][0]["shapes"][0]["future_field"] = "also inert"
    opener = _transport(monkeypatch, document)
    result = catalog.load_catalogue()
    assert result.source == "live"
    assert result.warning is None
    assert (
        result.shapes[0].reference.model_dump()
        == document["libraries"][0]["shapes"][0]["reference"]
    )
    assert result.shapes[0].keywords == ("box", "square")
    request, timeout = opener.calls[0]
    assert request.full_url == catalog.CATALOGUE_URL
    assert request.get_method() == "GET"
    assert request.get_header("Accept-encoding") == "identity"
    assert request.get_header("Authorization") is None
    assert request.get_header("Cookie") is None
    assert timeout == catalog.REQUEST_TIMEOUT_SECONDS


def test_each_run_asks_once_and_stores_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The skill keeps no state outside its folder, so every command asks for itself."""
    first = _transport(monkeypatch)
    assert catalog.load_catalogue().source == "live"
    second = _transport(monkeypatch)
    assert catalog.load_catalogue().source == "live"
    assert len(first.calls) == len(second.calls) == 1


def test_offline_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline means the packaged list and nothing else, and says so."""
    opener = _transport(monkeypatch)
    result = catalog.load_catalogue(offline=True)
    assert opener.calls == []
    assert result.source == "bundled" and "packaged" in (result.warning or "")


@pytest.mark.parametrize(
    "fault",
    [
        {"error": urllib.error.URLError("unreachable")},
        {"error": urllib.error.HTTPError(catalog.CATALOGUE_URL, 304, "Not Modified", Message(), io.BytesIO())},
        {"error": urllib.error.HTTPError(catalog.CATALOGUE_URL, 500, "Server Error", Message(), io.BytesIO())},
        {"body": b"not json"},
        {"body": b'{"catalog_version":999}'},
        {"body": b"\x00"},
    ],
)
def test_a_failed_or_bad_response_falls_back_to_the_packaged_list(
    monkeypatch: pytest.MonkeyPatch, fault: dict[str, Any]
) -> None:
    """A server fault is reported and the packaged list used, never guessed data."""
    _transport(monkeypatch, **fault)
    result = catalog.load_catalogue()
    assert result.source == "bundled"
    assert "failed" in (result.warning or "")


def test_response_byte_limits_are_checked_before_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server cannot bypass the byte limit with its body, its length header or gzip."""
    _transport(monkeypatch, Content_Length=str(catalog.MAX_CATALOGUE_BYTES + 1))
    with pytest.raises(catalog.CatalogueError):
        catalog._fetch()
    _transport(monkeypatch, Content_Encoding="gzip")
    with pytest.raises(catalog.CatalogueError):
        catalog._fetch()
    monkeypatch.setattr(catalog, "MAX_CATALOGUE_BYTES", 1024)
    _transport(monkeypatch, body=b"x" * 1025)
    with pytest.raises(catalog.CatalogueError):
        catalog._fetch()


@pytest.mark.parametrize(
    "value", [0, -1, float("nan"), float("inf"), True, "50", 1_000_001]
)
def test_invalid_dimensions_are_not_coerced(value: object) -> None:
    """Invalid natural sizes must not reach layout or reference placement."""
    document = _document()
    document["libraries"][0]["shapes"][0]["default_width"] = value
    with pytest.raises(ValidationError):
        catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    ("region", "accepted"),
    [
        ({"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6}, True),
        # Centred and wider, as a shipped library gives the UML Actor's name.
        ({"x": -1.569, "y": 0, "width": 4.138, "height": 1}, True),
        ({"x": -0.5, "y": 0, "width": 1.5, "height": 1}, False),
        ({"x": 0.5, "y": 0, "width": 0.8, "height": 1}, False),
        ({"x": 0, "y": 0.5, "width": 1, "height": 0.8}, False),
        ({"x": -4, "y": 0, "width": 9, "height": 1}, False),
        # The widest centred region the app allows, and one that runs below the shape.
        ({"x": -3.5, "y": 0, "width": 8, "height": 1}, True),
        ({"x": -1, "y": 0.5, "width": 3, "height": 0.8}, False),
    ],
)
def test_label_regions_take_the_apps_two_forms(region: dict[str, float], accepted: bool) -> None:
    """The app accepts a label region inside its shape, or one centred on it and wider for
    a name below a narrow shape. Refusing that second form would
    reject the whole catalogue once the website lists the 5.1.0 libraries, and accepting any
    other form would let a region through that the app refuses."""
    document = _document()
    document["libraries"][0]["shapes"][0] |= {"text_region": region, "text_position": "below"}
    payload = json.dumps(document)
    if accepted:
        catalog.ShapeLibraryCatalogue.model_validate_json(payload)
    else:
        with pytest.raises(ValidationError):
            catalog.ShapeLibraryCatalogue.model_validate_json(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "library_uuid",
        "readable_id",
        "shape_uuid",
        "shape_slug",
        "shape_reference",
        "connection_id",
    ],
)
def test_duplicate_identities_are_rejected(mutation: str) -> None:
    """Catalogue lookups must be unambiguous at every identity boundary."""
    document = _document()
    library = document["libraries"][0]
    if mutation in {"library_uuid", "readable_id"}:
        duplicate = copy.deepcopy(library)
        if mutation == "library_uuid":
            duplicate["readable_id"] += ".second"
            duplicate["shapes"][0]["reference"]["library_id"] = duplicate["readable_id"]
        else:
            duplicate["library_id"] = SECOND_ID
        document["libraries"].append(duplicate)
    elif mutation == "connection_id":
        library["shapes"][0]["connection_points"] = [
            {"id": 0, "x": 0, "y": 0},
            {"id": 0, "x": 1, "y": 1},
        ]
    else:
        duplicate = copy.deepcopy(library["shapes"][0])
        if mutation != "shape_uuid":
            duplicate["item_id"] = SECOND_ID
        if mutation != "shape_slug":
            duplicate["slug"] = "second"
        if mutation != "shape_reference":
            duplicate["reference"]["item_id"] = "Second"
        library["shapes"].append(duplicate)
    with pytest.raises(ValidationError):
        catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))


def test_shapes_keep_published_order_and_custom_anchors() -> None:
    """Search order and explicit connection-point lists belong to the API."""
    document = _document()
    shape = copy.deepcopy(document["libraries"][0]["shapes"][0])
    shape.update(item_id=SECOND_ID, slug="first-in-display", display_name="Second")
    shape["reference"]["item_id"] = "Second"
    shape["connection_points"] = [{"id": 9, "x": 0.25, "y": 0.75}]
    document["libraries"][0]["shapes"].insert(0, shape)
    parsed = catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))
    assert [entry.reference.item_id for entry in parsed.libraries[0].shapes] == [
        "Second",
        "Square",
    ]
    assert parsed.libraries[0].shapes[0].connection_points[0].id == 9


def test_downloadable_reference_is_preserved_and_validated() -> None:
    """Published UUID references are never converted into invented built-in names."""
    document = _document()
    library = document["libraries"][0]
    library["built_in"] = False
    shape = library["shapes"][0]
    shape["reference"] = {
        "library_id": LIBRARY_ID,
        "item_id": ITEM_ID,
        "asset_version": 3,
    }
    parsed = catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))
    assert parsed.libraries[0].shapes[0].reference.model_dump() == shape["reference"]
    shape["reference"]["item_id"] = SECOND_ID
    with pytest.raises(ValidationError):
        catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))


def test_redirect_handler_never_follows_another_address() -> None:
    """A fixed anonymous request must not turn into requests chosen by a server."""
    assert (
        catalog._NoRedirect().redirect_request(
            None, None, 302, "Found", Message(), "https://example.com/"
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "too_many_points",
        "too_many_keywords",
        "control_text",
        "boolean_version",
        "different_library",
    ],
)
def test_bounds_and_cross_field_contract_are_enforced(mutation: str) -> None:
    """Response fields must remain bounded, typed and internally consistent."""
    document = _document()
    shape = document["libraries"][0]["shapes"][0]
    if mutation == "too_many_points":
        shape["connection_points"] = [
            {"id": number, "x": 0, "y": 0} for number in range(129)
        ]
    elif mutation == "too_many_keywords":
        shape["keywords"] = ["keyword"] * 129
    elif mutation == "control_text":
        shape["description"] = "description\x1b[0m"
    elif mutation == "boolean_version":
        document["catalog_version"] = True
    else:
        shape["reference"]["library_id"] = "different.library"
    with pytest.raises(ValidationError):
        catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))
