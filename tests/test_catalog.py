"""Exercise catalogue discovery without contacting any production service.

The reader must preserve placement references, validate untrusted response
bytes, avoid repeated requests, and retain honest offline fallbacks. Temporary
cache paths and a controlled opener isolate every test from user state.
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


def _seed_cache(monkeypatch: pytest.MonkeyPatch, path: Path) -> dict[str, Any]:
    """Fetch controlled valid data before exercising revalidation or fallback."""
    document = _document()
    _transport(monkeypatch, document, ETag='"first"')
    result = catalog.load_catalogue(cache_path=path)
    assert result.source == "live"
    return document


def test_live_fetch_preserves_references_and_additive_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Public identity must never replace a packaged placement reference."""
    document = _document()
    document["future_field"] = {"untrusted": "inert"}
    document["libraries"][0]["shapes"][0]["future_field"] = "also inert"
    opener = _transport(monkeypatch, document, ETag='"first"')
    result = catalog.load_catalogue(cache_path=tmp_path / "cache.json")
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


def test_warm_cache_makes_no_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ordinary repeated searches share the one-hour request allowance."""
    path = tmp_path / "cache.json"
    _seed_cache(monkeypatch, path)
    opener = _transport(monkeypatch, error=AssertionError("network must not run"))
    result = catalog.load_catalogue(cache_path=path)
    assert result.source == "cache"
    assert opener.calls == []


def test_304_revalidates_existing_cache_and_retains_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Conditional revalidation keeps exact ordered data instead of replacing it."""
    path = tmp_path / "cache.json"
    document = _seed_cache(monkeypatch, path)
    opener = _transport(
        monkeypatch,
        error=urllib.error.HTTPError(
            catalog.CATALOGUE_URL, 304, "Not Modified", Message(), io.BytesIO()
        ),
    )
    result = catalog.load_catalogue(cache_path=path, refresh=True)
    assert result.source == "cache"
    assert result.catalogue == catalog.ShapeLibraryCatalogue.model_validate_json(json.dumps(document))
    assert opener.calls[0][0].get_header("If-none-match") == '"first"'
    assert json.loads(path.read_bytes())["etag"] == '"first"'
    assert json.loads(path.read_bytes())["failed"] is False


def test_failed_request_uses_stale_cache_and_throttles_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A network outage retains validated data and does not cause request loops."""
    path = tmp_path / "cache.json"
    _seed_cache(monkeypatch, path)
    opener = _transport(monkeypatch, error=urllib.error.URLError("unavailable"))
    first = catalog.load_catalogue(cache_path=path, refresh=True)
    second = catalog.load_catalogue(cache_path=path)
    assert first.source == second.source == "stale-cache"
    assert first.warning and second.warning
    assert first.catalogue == second.catalogue
    assert len(opener.calls) == 1


def test_expired_cache_attempts_revalidation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The hourly allowance must not leave a successful cache frozen forever."""
    path = tmp_path / "cache.json"
    monkeypatch.setattr(catalog.time, "time", lambda: 1000.0)
    _seed_cache(monkeypatch, path)
    monkeypatch.setattr(catalog.time, "time", lambda: 5000.0)
    opener = _transport(monkeypatch, ETag='"second"')
    result = catalog.load_catalogue(cache_path=path)
    assert result.source == "live"
    assert len(opener.calls) == 1


def test_offline_fallback_neither_fetches_nor_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline discovery works without creating cache or contacting the server."""
    path = tmp_path / "absent" / "cache.json"
    opener = _transport(monkeypatch, error=AssertionError("offline"))
    result = catalog.load_catalogue(cache_path=path, offline=True)
    assert result.source == "bundled"
    assert len(result.libraries) == 7
    assert all(library.built_in for library in result.libraries)
    assert all(
        shape.reference.library_id == library.readable_id
        for library in result.libraries
        for shape in library.shapes
    )
    assert opener.calls == []
    assert not path.exists()


def test_failed_first_fetch_uses_bundle_and_throttles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The first offline failure also receives the one-hour request allowance."""
    path = tmp_path / "cache.json"
    opener = _transport(monkeypatch, error=urllib.error.URLError("unavailable"))
    assert catalog.load_catalogue(cache_path=path).source == "bundled"
    assert catalog.load_catalogue(cache_path=path).source == "bundled"
    assert len(opener.calls) == 1


@pytest.mark.parametrize("cached", [b"not json", b"{}"])
def test_corrupt_cache_is_replaced_by_valid_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cached: bytes
) -> None:
    """Local cache corruption must not become trusted discovery data."""
    path = tmp_path / "cache.json"
    path.write_bytes(cached)
    _transport(monkeypatch)
    result = catalog.load_catalogue(cache_path=path)
    assert result.source == "live"
    assert catalog._read_cache(path).catalogue == result.catalogue


@pytest.mark.parametrize("body", [b"not json", b'{"catalog_version":999}', b"\x00"])
def test_bad_response_does_not_replace_valid_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes
) -> None:
    """Server faults must not overwrite the last valid catalogue."""
    path = tmp_path / "cache.json"
    _seed_cache(monkeypatch, path)
    _transport(monkeypatch, body=body)
    result = catalog.load_catalogue(cache_path=path, refresh=True)
    assert result.source == "stale-cache"
    assert result.shapes[0].reference.item_id == "Square"


def test_response_byte_limit_is_checked_before_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even unparseable oversized data must stop at the transport ceiling."""
    # A valid cached catalogue avoids reading the larger bundled fallback.
    path = tmp_path / "cache.json"
    _seed_cache(monkeypatch, path)
    monkeypatch.setattr(catalog, "MAX_CATALOGUE_BYTES", 1024)
    _transport(monkeypatch, body=b"x" * 1025)
    assert catalog.load_catalogue(cache_path=path, refresh=True).source == "stale-cache"


def test_declared_large_body_and_unexpected_gzip_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A server cannot bypass the byte limit with length or encoding headers."""
    path = tmp_path / "cache.json"
    _seed_cache(monkeypatch, path)
    _transport(monkeypatch, Content_Length=str(catalog.MAX_CATALOGUE_BYTES + 1))
    assert catalog.load_catalogue(cache_path=path, refresh=True).source == "stale-cache"
    _transport(monkeypatch, Content_Encoding="gzip")
    assert catalog.load_catalogue(cache_path=path, refresh=True).source == "stale-cache"


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


def test_cache_write_failure_keeps_valid_live_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Read-only cache storage should not discard useful validated response data."""
    _transport(monkeypatch)
    monkeypatch.setattr(
        catalog,
        "_write_cache",
        lambda *args: (_ for _ in ()).throw(OSError("read only")),
    )
    result = catalog.load_catalogue(cache_path=tmp_path / "cache.json")
    assert result.source == "live"
    assert "could not be saved" in result.warning


def test_unsolicited_304_has_no_data_to_trust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A server's conditional response cannot fabricate a missing cache."""
    _transport(
        monkeypatch,
        error=urllib.error.HTTPError(
            catalog.CATALOGUE_URL, 304, "Not Modified", Message(), io.BytesIO()
        ),
    )
    assert (
        catalog.load_catalogue(cache_path=tmp_path / "cache.json").source == "bundled"
    )


def test_304_requires_a_conditional_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A server cannot revalidate a cached response lacking an ETag."""
    path = tmp_path / "cache.json"
    _transport(monkeypatch)
    assert catalog.load_catalogue(cache_path=path).source == "live"
    _transport(
        monkeypatch,
        error=urllib.error.HTTPError(
            catalog.CATALOGUE_URL, 304, "Not Modified", Message(), io.BytesIO()
        ),
    )
    assert catalog.load_catalogue(cache_path=path, refresh=True).source == "stale-cache"


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
