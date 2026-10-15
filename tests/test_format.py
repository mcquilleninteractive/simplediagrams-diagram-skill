"""Tests for the exact document models in scripts/sd_format.py.

These models are the skill's statement of what SimpleDiagrams will open. The
tests pin the pinned versions, the keys the app insists on, and the mistakes a
hand-written file most often makes, so a change to the models that would let
an unreadable document through fails here first.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import fixtures
import sd_format as wire


def _dumped() -> dict:
    return wire.dump(fixtures.full_profile_document())


def _first_element(document: dict) -> dict:
    return document["pages"][0]["elements"][0]


def _core(document: dict) -> dict:
    return _first_element(document)["content"]["content"]["content"]


def _rejects(document: dict) -> str:
    with pytest.raises(ValidationError) as failure:
        wire.Document.model_validate_json(json.dumps(document))
    return str(failure.value)


def test_versions_are_the_pinned_pair() -> None:
    """The package and document counters differ by one; mixing them up is the
    commonest reason the app refuses a hand-written file."""
    assert (wire.FORMAT_VERSION, wire.SCHEMA_VERSION) == (15, 14)
    manifest = {"format": "com.simplediagrams.document", "format_version": 15, "contains_legacy_source": False}
    assert wire.dump(wire.manifest()) == manifest
    for missing in manifest:
        with pytest.raises(ValidationError):
            wire.Manifest.model_validate({key: value for key, value in manifest.items() if key != missing})
    document = _dumped()
    document["schema_version"] = 15
    assert "schema_version" in _rejects(document)


def test_full_profile_round_trips_unchanged() -> None:
    """Reading back what was written must lose nothing, or the validator would
    pass documents that differ from what the builder produced."""
    document = fixtures.full_profile_document()
    again = wire.Document.model_validate_json(json.dumps(wire.dump(document)))
    assert again == document


def test_top_level_has_exactly_the_nine_required_keys() -> None:
    """The app rejects a document with a missing or extra top-level key."""
    assert set(wire.dump(fixtures.minimal_document())) == {
        "id", "schema_version", "revision", "name", "selected_page_id", "pages",
        "quick_styles", "embedded_assets", "shape_data_definitions",
    }


def test_element_always_writes_the_null_shape_data_key() -> None:
    """The app requires shape_data_definition_id to be present even when null,
    so it must survive the dump that drops other null keys."""
    element = _first_element(_dumped())
    assert set(element) == {"content", "shape_data_definition_id", "shape_data_values"}
    assert element["shape_data_definition_id"] is None
    assert element["shape_data_values"] == []


def test_optional_keys_are_omitted_rather_than_null() -> None:
    """A page background of kind none must carry no other key."""
    page = wire.dump(fixtures.minimal_document())["pages"][0]
    assert page["content"]["background"] == {"kind": "none"}
    assert "drawableOrder" not in page["content"]


def test_inner_arrays_stay_empty() -> None:
    """Each page nests three element lists and only the outermost may be
    filled; the app rejects content in the inner ones."""
    page = _dumped()["pages"][0]
    assert page["content"]["elements"] == []
    assert page["content"]["content"]["elements"] == []
    assert page["content"]["content"]["groups"] == []
    assert page["content"]["content"]["content"]["elements"] == []
    assert page["content"]["content"]["content"]["connections"] == []
    document = _dumped()
    document["pages"][0]["content"]["elements"] = [copy.deepcopy(_first_element(document))]
    _rejects(document)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: _first_element(d).update(label="extra"),
        lambda d: _core(d).update(nickname="extra"),
        lambda d: d.update(metadata={}),
        lambda d: d["pages"][0]["content"].update(drawable_order=[]),
    ],
)
def test_unknown_keys_are_errors_everywhere(mutate) -> None:
    """The app drops unknown keys silently at some levels; an author should be
    told instead, including the snake_case misspelling of drawableOrder."""
    document = _dumped()
    mutate(document)
    assert "Extra inputs are not permitted" in _rejects(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [("fill_hex", "red"), ("fill_hex", "#FFF"), ("fill_hex", "none"), ("stroke_hex", "transparent")],
)
def test_colors_must_be_six_or_eight_digit_hex(field: str, value: str) -> None:
    """Named and short colors are refused by the app."""
    document = _dumped()
    _core(document)["style"][field] = value
    _rejects(document)


def test_identifiers_must_be_uuids_and_unique_across_the_document() -> None:
    """Every object shares one identifier space, whatever its type."""
    document = _dumped()
    _core(document)["id"] = "shape-1"
    _rejects(document)
    document = _dumped()
    _core(document)["id"] = document["pages"][0]["content"]["content"]["content"]["id"].lower()
    assert "more than once" in _rejects(document)


def test_lowercase_uuids_are_accepted() -> None:
    """The app writes upper case but opens either."""
    text = json.dumps(wire.dump(fixtures.minimal_document())).replace(
        fixtures.DOCUMENT_ID, fixtures.DOCUMENT_ID.lower()
    )
    wire.Document.model_validate_json(text)


def test_attachment_must_name_an_anchor_on_the_same_page() -> None:
    """A connector attached to a missing element or anchor stops the app
    opening the document."""
    connection = lambda d: d["pages"][0]["content"]["content"]["connections"][0]["content"]
    document = _dumped()
    connection(document)["start_attachment"]["connection_point_id"] = 99
    assert "does not have" in _rejects(document)
    document = _dumped()
    connection(document)["end_attachment"]["element_id"] = "00000000-0000-4000-8000-00000000FFFF"
    assert "not on this page" in _rejects(document)


def test_kind_specific_keys_are_enforced() -> None:
    """A symbol needs its reference, and no other kind may carry one."""
    document = _dumped()
    del _core(document)["symbol_reference"]
    _rejects(document)
    document = _dumped()
    document["pages"][0]["elements"][1]["content"]["content"]["content"]["symbol_reference"] = {
        "library_id": "x", "item_id": "y", "asset_version": 1,
    }
    _rejects(document)


def test_drawable_order_must_be_complete() -> None:
    """A partial drawing order is refused; omitting it is always safe."""
    document = _dumped()
    document["pages"][0]["content"]["drawableOrder"].pop()
    assert "drawableOrder" in _rejects(document)


def test_text_runs_are_only_allowed_over_plain_ascii() -> None:
    """The app wants run ends between whole user-perceived characters, which
    cannot be checked here for accents or emoji, so runs over such text are
    refused rather than guessed at."""
    for text in ("caf\u00e9 au lait plain", "line one\r\nline two", "\U0001F600 emoji then text"):
        document = _dumped()
        _core(document)["text_content"]["string"] = text
        assert "plain ASCII" in _rejects(document)
    document = _dumped()
    _core(document)["text_content"]["character_runs"][1]["range"] = {"location": 5, "length": 400}
    assert "runs past the text" in _rejects(document)
    document = _dumped()
    _core(document)["text_content"]["character_runs"][1]["range"] = {"location": 2, "length": 4}
    assert "must not overlap" in _rejects(document)


# Keys the app reads only when present, as (key, parent key or None for any).
OPTIONAL = {
    ("font_family", None), ("background_hex", None), ("rotation_degrees", "text_layout"),
    ("fill_texture", None), ("stroke_texture", None), ("stroke_pattern_override", None),
    ("control_point", None), ("second_control_point", None), ("text_layout", None),
    ("note_style", None), ("preserves_aspect_ratio", None), ("start_attachment", None),
    ("end_attachment", None), ("label", None), ("visible", None), ("appearance", None),
    ("color", "appearance"), ("export_frame", None), ("drawableOrder", None), ("guides", None),
}


def test_every_required_key_is_required() -> None:
    """A key the app requires must never fall back to a default when a file is
    read. Removing each key in turn, only the optional ones may still pass."""
    still_valid = []
    for path, trimmed in fixtures.documents_with_one_key_removed(_dumped()):
        try:
            wire.Document.model_validate_json(json.dumps(trimmed))
        except ValidationError:
            continue
        steps = [step for step in path.split(".") if not step.isdigit()]
        key, parent = steps[-1], (steps[-2] if len(steps) > 1 else None)
        if (key, None) not in OPTIONAL and (key, parent) not in OPTIONAL:
            still_valid.append(path)
    assert still_valid == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: _core(d).update(z_index=2**63),
        lambda d: _core(d).update(z_index=-(2**63) - 1),
        lambda d: _core(d)["symbol_reference"].update(asset_version=2**64),
        lambda d: _core(d)["connection_points"][0].update(id=2**70),
    ],
)
def test_whole_numbers_fit_in_64_bits(mutate) -> None:
    """The app stores whole numbers as 64-bit integers and refuses larger ones."""
    document = _dumped()
    mutate(document)
    _rejects(document)


@pytest.mark.parametrize("character", ["\u00ad", "\u0600", "\u200b", "\ufeff", "\x07", "\U000e0001"])
def test_control_and_format_characters_are_refused_in_names(character: str) -> None:
    """The app refuses any Unicode control or format character in a font
    family or Quick Style name, not just the common invisible ones."""
    document = _dumped()
    _core(document)["text_content"]["base_style"]["font_family"] = f"Helv{character}etica"
    _rejects(document)
    document = _dumped()
    document["quick_styles"][0]["name"] = f"Out{character}line"
    _rejects(document)


def test_groups_need_two_resolving_members_and_no_cycles() -> None:
    """Group membership must form a forest on one page."""
    groups = lambda d: d["pages"][0]["content"]["groups"]
    document = _dumped()
    groups(document)[0]["members"].append({"kind": "group", "id": groups(document)[1]["id"]})
    assert "cycle" in _rejects(document)
    document = _dumped()
    groups(document)[0]["members"] = groups(document)[0]["members"][:1]
    _rejects(document)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: _core(d)["frame"].update(width=0),
        lambda d: _core(d).update(z_index=1.5),
        lambda d: _core(d).update(z_index=True),
        lambda d: d.update(revision=-1),
        lambda d: d.update(selected_page_id="00000000-0000-4000-8000-00000000FFFF"),
        lambda d: d.update(pages=[]),
        lambda d: d.update(embedded_assets=[{"id": "a"}]),
        lambda d: d["pages"][0]["content"]["content"]["content"]["grid"].update(spacing_x=2),
        lambda d: d["pages"][0]["content"]["background"].pop("color_hex"),
        lambda d: _first_element(d).update(shape_data_definition_id="00000000-0000-4000-8000-00000000AAAA"),
    ],
)
def test_out_of_range_and_out_of_profile_values_are_rejected(mutate) -> None:
    """Bounds the app enforces, and features outside the authoring profile."""
    document = _dumped()
    mutate(document)
    _rejects(document)


def test_committed_schemas_match_the_models() -> None:
    """The JSON Schema files are generated; a stale copy would describe a
    different format from the one the scripts enforce."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "maintainers" / "export_schemas.py"), "--check"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Package 16: the libraries a document needs (desktop ADR 0039)
# ---------------------------------------------------------------------------

NOTEBOOK = "79FFE4B7-EA0D-87C3-AE89-D4CD62AF5202"


def _with_libraries(libraries: list[dict]) -> dict:
    document = _dumped()
    document["schema_version"] = 15
    document["required_libraries"] = libraries
    return document


def test_required_libraries_come_only_with_schema_15_and_package_16() -> None:
    """The app refuses the list before package 16, and the skill bumps the format only for
    a document that has one, so every other document still opens in 5.0.8."""
    libraries = [{"library_id": NOTEBOOK, "display_name": "Hobby Electronics Notebook"}]
    document = wire.Document.model_validate_json(json.dumps(_with_libraries(libraries)))
    assert wire.dump(wire.manifest(document))["format_version"] == 16
    at_14 = _with_libraries(libraries)
    at_14["schema_version"] = 14
    assert "required_libraries" in _rejects(at_14)
    assert "required_libraries" in _rejects(_with_libraries([]))


def test_the_builder_picks_the_format_from_the_libraries() -> None:
    """A plain document stays at 15; one naming a library is 16, and leaves out a revision
    it does not know."""
    plain = fixtures.minimal_document()
    assert (plain.schema_version, wire.manifest(plain).format_version) == (14, 15)
    named = wire.document(
        id=plain.id, name=plain.name, pages=plain.pages,
        required_libraries=[wire.RequiredLibrary(library_id=NOTEBOOK, display_name="Notebook")],
    )
    assert (named.schema_version, wire.manifest(named).format_version) == (15, 16)
    assert wire.dump(named)["required_libraries"] == [
        {"library_id": NOTEBOOK, "display_name": "Notebook"}
    ]


@pytest.mark.parametrize(
    "identifier",
    [
        "", ".hidden", "trailing.", "has space", "slash/inside", "café", "a" * 257,
        "abc\n", "-a", "a-",
    ],
)
def test_required_library_identifiers_follow_the_apps_rule(identifier: str) -> None:
    """The app drops an entry it would not accept, so the skill must never write one."""
    with pytest.raises(ValidationError):
        wire.RequiredLibrary(library_id=identifier, display_name="Notebook")


@pytest.mark.parametrize(
    "name",
    [
        "", "   ", "line\nbreak", "tab\tname", "a" * 201, "evil\u202ename", "para\u2029",
        "\u200b", " \u200b\u00a0",
    ],
)
def test_required_library_names_follow_the_apps_rule(name: str) -> None:
    """A name is shown on one line inside the app's own sentence, so it may not be blank,
    break the line or reorder the text around it. The app trims with Foundation's whitespace
    set, which holds U+200B, so a name of zero-width spaces is blank to it too."""
    with pytest.raises(ValidationError):
        wire.RequiredLibrary(library_id=NOTEBOOK, display_name=name)


def test_required_library_names_may_use_joiners_and_any_script() -> None:
    """Joiners that emoji and scripts such as Persian need are ordinary text to the app."""
    for name in ("\U0001f469\u200d\U0001f4bb Library", "کتاب\u200cها"):
        assert wire.RequiredLibrary(library_id=NOTEBOOK, display_name=name).display_name == name


def test_required_libraries_name_each_library_once_and_at_most_64() -> None:
    """The app keeps one entry per library, ignoring case, and at most 64."""
    twice = [
        {"library_id": NOTEBOOK, "display_name": "Notebook"},
        {"library_id": NOTEBOOK.lower(), "display_name": "Notebook again"},
    ]
    assert "twice" in _rejects(_with_libraries(twice))
    many = [
        {"library_id": f"00000000-0000-4000-8000-{index:012d}", "display_name": "Library"}
        for index in range(wire.MAX_REQUIRED_LIBRARIES + 1)
    ]
    assert "required_libraries" in _rejects(_with_libraries(many))


def test_minimum_revision_is_bounded_when_given() -> None:
    """The app reads a revision from 1 to 1,000,000 and leaves out anything else."""
    assert wire.RequiredLibrary(library_id=NOTEBOOK, display_name="N", minimum_revision=1)
    for revision in (0, wire.MAX_LIBRARY_REVISION + 1):
        with pytest.raises(ValidationError):
            wire.RequiredLibrary(library_id=NOTEBOOK, display_name="N", minimum_revision=revision)


def test_the_largest_entries_the_app_keeps_are_accepted() -> None:
    """Every limit is the app's own, so its largest entries must still be written: 200
    astral emoji (400 UTF-16 units, which a UTF-16 count would refuse), a 256-byte
    reverse-DNS identifier with every allowed mark, and 64 entries."""
    reverse_dns = "com.example.shape-library_"
    reverse_dns += "x" * (wire.MAX_IDENTIFIER_BYTES - len(reverse_dns))
    emoji = "\U0001f469" * wire.MAX_REQUIRED_LIBRARY_NAME_SCALARS
    widest = wire.RequiredLibrary(library_id=reverse_dns, display_name=emoji)
    assert (len(widest.library_id.encode()), len(widest.display_name)) == (256, 200)
    with pytest.raises(ValidationError):
        wire.RequiredLibrary(library_id=reverse_dns + "x", display_name="N")
    with pytest.raises(ValidationError):
        wire.RequiredLibrary(library_id=NOTEBOOK, display_name=emoji + "\U0001f469")
    most = [
        {"library_id": f"00000000-0000-4000-8000-{index:012d}", "display_name": "Library"}
        for index in range(wire.MAX_REQUIRED_LIBRARIES)
    ]
    document = wire.Document.model_validate_json(json.dumps(_with_libraries(most)))
    assert len(document.required_libraries or []) == wire.MAX_REQUIRED_LIBRARIES


def test_a_library_list_written_as_null_is_refused() -> None:
    """The app takes a key that is present, even as null, to need schema 15, and would
    refuse the whole file; a document without libraries leaves the key out."""
    document = _dumped()
    document["required_libraries"] = None
    assert "never written as null" in _rejects(document)
    assert "required_libraries" not in wire.dump(fixtures.minimal_document())
