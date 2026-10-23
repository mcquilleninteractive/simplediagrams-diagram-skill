"""Documents shared by format tests and private compatibility checks.

`full_profile_document` uses every optional feature of plain shapes and connectors
the authoring profile allows, and `complex_profile_document` every key complex shapes,
connector ends along a lifeline and label regions starting outside their shape add.
They exist so these documents can be shown to SimpleDiagrams' own reader
whenever the format or the models change; see VERSIONS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sd_format as wire

DOCUMENT_ID = "0F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F1"


def _uuid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012X}"


def _element(number: int, kind: str, x: float, y: float, **extra: Any) -> wire.Element:
    extra.setdefault("style", wire.ElementStyle(fill_hex="#FFFFFF", stroke_hex="#000000", line_width=1.0))
    return wire.element(
        id=_uuid(number), kind=kind, frame=wire.Rect(x=x, y=y, width=120.0, height=70.0),
        z_index=number, is_locked=bool(number % 2), **extra,
    )


def full_profile_document() -> wire.Document:
    """One document exercising every optional key in the authoring profile."""
    rich = wire.text_content(
        "Bold then plain",
        base_style=wire.character_style(font_family="Helvetica", font_size=18.0, is_italic=True),
        character_runs=[
            wire.CharacterRun(
                range=wire.TextRange(location=0, length=4),
                style=wire.character_style(weight="bold", is_underlined=True, color_hex="#C92A2AFF"),
            ),
            wire.CharacterRun(
                range=wire.TextRange(location=5, length=4), style=wire.character_style(font_size=24.0)
            ),
        ],
        base_alignment="leading",
        paragraph_runs=[wire.ParagraphRun(range=wire.TextRange(location=0, length=4), alignment="trailing")],
        background_hex="#FFF3BF",
    )
    layout = wire.TextLayout(
        frame=wire.TextLayoutFrame(x=0.1, y=0.1, width=1.5, height=0.8),
        position="below",
        rotation_degrees=15.0,
    )
    elements = [
        _element(
            1, "symbol", 100.0, 100.0, text=rich, text_layout=layout, flip_horizontal=True,
            preserves_aspect_ratio=True,
            symbol_reference=wire.SymbolReference(
                library_id="com.simplediagrams.shapeLibrary.basic", item_id="Square", asset_version=1
            ),
            style=wire.ElementStyle(
                fill_hex="#D8ECFF", stroke_hex="#343A40", line_width=2.0,
                fill_texture="PencilThinHoriztonalHatch", stroke_texture="Grain",
                stroke_pattern_override="dashed",
            ),
        ),
        _element(2, "rectangle", 400.0, 100.0, rotation_degrees=30.0),
        _element(3, "ellipse", 700.0, 100.0, flip_vertical=True),
        _element(4, "note", 100.0, 300.0, note_style="indexCard"),
        _element(5, "text", 400.0, 300.0, text=wire.text_content("Unicode stays plain: café \U0001F600")),
        _element(
            6, "path", 700.0, 300.0,
            # Path nodes are relative to the frame's top left corner.
            path=wire.Path(
                nodes=[
                    wire.PathNode(point=wire.Point(x=0.0, y=0.0), kind="straight"),
                    wire.PathNode(
                        point=wire.Point(x=60.0, y=70.0), kind="curve",
                        control_point=wire.Point(x=20.0, y=60.0),
                        second_control_point=wire.Point(x=50.0, y=10.0),
                    ),
                    wire.PathNode(point=wire.Point(x=120.0, y=0.0), kind="straight"),
                ],
                is_closed=True, is_smoothed=False, stroke_pattern="dotted",
                start_ending="none", end_ending="none",
            ),
            style=wire.ElementStyle(fill_hex="#00000000", stroke_hex="#343A40", line_width=2.0),
            connection_points=[wire.ConnectionPointAnchor(id=9, x=0.25, y=0.75)],
        ),
    ]
    connections = [
        wire.connection(
            id=_uuid(20),
            points=[
                wire.ConnectorPoint(x=220.0, y=135.0, kind="straight"),
                wire.ConnectorPoint(x=310.0, y=90.0, kind="curve"),
                wire.ConnectorPoint(x=400.0, y=135.0, kind="straight"),
            ],
            start_attachment=wire.Attachment(element_id=_uuid(1), connection_point_id=1),
            end_attachment=wire.Attachment(element_id=_uuid(2), connection_point_id=0),
            stroke_hex="#1971C2", line_width=3.0, stroke_pattern="dashed",
            start_ending="zeroOrMany", end_ending="oneAndOnlyOne", stroke_texture="PencilFill",
            label=wire.ConnectorLabel(content=wire.text_content("has"), position=0.25, normal_offset=-12.0),
            is_locked=True,
        ),
        wire.connection(
            id=_uuid(21),
            points=[
                wire.ConnectorPoint(x=520.0, y=400.0, kind="straight"),
                wire.ConnectorPoint(x=730.0, y=352.5, kind="straight"),
            ],
            end_attachment=wire.Attachment(element_id=_uuid(6), connection_point_id=9),
        ),
    ]
    page_one = wire.page(
        id=_uuid(100), name="Everything", width=1600.0, height=900.0,
        grid=wire.Grid(
            spacing_x=10.0, spacing_y=25.0, origin=wire.Point(x=5.0, y=5.0), visible=False,
            appearance=wire.GridAppearance(
                minor_line="dotted", major_line="solid", major_interval=4,
                marker="cross", marker_placement="every", color="#4263EB", strength=0.4,
            ),
        ),
        export_frame=wire.Rect(x=50.0, y=50.0, width=900.0, height=500.0),
        elements=elements,
        connections=connections,
        background=wire.Background(kind="solid", color_hex="#FFF9DB"),
        groups=[
            wire.Group(
                id=_uuid(200),
                members=[
                    wire.GroupMember(kind="element", id=_uuid(2)),
                    wire.GroupMember(kind="element", id=_uuid(3)),
                ],
                is_locked=False, rotation_degrees=0.0,
            ),
            wire.Group(
                id=_uuid(201),
                members=[
                    wire.GroupMember(kind="group", id=_uuid(200)),
                    wire.GroupMember(kind="connection", id=_uuid(21)),
                ],
                is_locked=True, rotation_degrees=45.0,
            ),
        ],
        drawable_order=[
            wire.DrawableReference(kind="connection", id=_uuid(20)),
            *(wire.DrawableReference(kind="element", id=_uuid(number)) for number in range(1, 7)),
            wire.DrawableReference(kind="connection", id=_uuid(21)),
        ],
        guides=[
            wire.Guide(id=_uuid(300), axis="horizontal", position=250.0),
            wire.Guide(id=_uuid(301), axis="vertical", position=-40.0),
        ],
    )
    return wire.document(
        id=DOCUMENT_ID, name="Full profile", revision=7, selected_page_id=_uuid(101),
        pages=[page_one, wire.page(id=_uuid(101), name="Empty")],
    )


def _complex(
    number: int, x: float, y: float, width: float, height: float, shape: wire.ComplexShape, text: str = "",
    flip_horizontal: bool = False,
) -> wire.Element:
    points = [wire.ConnectionPointAnchor(id=2, x=0.5, y=0.0)] if shape.type == "lifeline" else None
    return wire.element(
        id=_uuid(number), kind="complex_shape", frame=wire.Rect(x=x, y=y, width=width, height=height),
        z_index=number, text=wire.text_content(text, base_alignment="leading" if shape.type == "container" else "center"),
        style=wire.ElementStyle(fill_hex="#FFFFFF", stroke_hex="#000000", line_width=1.0),
        connection_points=points, complex_shape=shape, flip_horizontal=flip_horizontal,
    )


def complex_profile_document() -> wire.Document:
    """One document using every key complex shapes, connector ends along a lifeline and
    label regions starting outside their shape add."""
    element = lambda number: wire.HolderMember(kind="element", id=_uuid(number))
    cell = wire.text_content
    elements = [
        _element(1, "rectangle", 120.0, 140.0),
        _element(2, "rectangle", 120.0, 240.0),
        _element(3, "text", 120.0, 320.0, text=wire.text_content("Caption")),
        _complex(4, 300.0, 120.0, 200.0, 200.0, wire.ComplexShape(type="container", members=[element(5)]), "Inner"),
        _element(5, "rectangle", 340.0, 180.0),
        _complex(
            30, 100.0, 80.0, 440.0, 300.0,
            wire.ComplexShape(
                type="container", hand_drawn=False, title_style="corner_tag",
                members=[element(1), wire.HolderMember(kind="group", id=_uuid(200)), element(4)],
            ),
            "sd Everything",
        ),
        _complex(
            6, 600.0, 80.0, 400.0, 300.0,
            wire.ComplexShape(
                type="swimlanes", direction="vertical", title_strip_size=40.0, title_band_size=36.0,
                lanes=[
                    wire.Lane(id=_uuid(400), title=cell("Left"), size=1.0, members=[element(7)]),
                    wire.Lane(id=_uuid(401), title=cell("Right"), size=2.5, members=[]),
                ],
            ),
            "Pool",
        ),
        _element(7, "note", 620.0, 200.0),
        _complex(
            8, 100.0, 450.0, 200.0, 80.0,
            wire.ComplexShape(
                type="table", hand_drawn=False, row_sizes=[1.0, 2.0], column_sizes=[30.0, 70.0],
                cells=[[cell("a"), cell("b")], [cell("c", base_alignment="leading"), cell("")]], header_row=False,
            ),
        ),
        _complex(
            10, 350.0, 450.0, 180.0, 80.0,
            wire.ComplexShape(
                type="callout", tail_tip=wire.Point(x=140.0, y=-40.0),
                tail_attachment=wire.Attachment(element_id=_uuid(8), connection_point_id=6),
            ),
            "Locked tail", flip_horizontal=True,
        ),
        _complex(11, 600.0, 450.0, 180.0, 80.0, wire.ComplexShape(type="callout", tail_tip=wire.Point(x=-40.0, y=70.0)), "Free tail"),
        _complex(12, 820.0, 450.0, 180.0, 80.0, wire.ComplexShape(type="callout"), "No tail"),
        _complex(13, 100.0, 600.0, 120.0, 200.0, wire.ComplexShape(type="lifeline"), "Box"),
        _complex(
            14, 300.0, 600.0, 100.0, 200.0,
            wire.ComplexShape(type="lifeline", head_style="actor", ends_in_destroy_mark=True),
            "Actor",
        ),
        _element(
            15, "symbol", 500.0, 600.0,
            symbol_reference=wire.SymbolReference(
                library_id="com.simplediagrams.shapeLibrary.bpmn", item_id="start-event", asset_version=1
            ),
            text=wire.text_content("Start"),
            text_layout=wire.TextLayout(
                frame=wire.TextLayoutFrame(x=-0.977, y=0.0, width=2.954, height=1.0), position="below"
            ),
        ),
    ]
    line = lambda number, distance: wire.Attachment(
        element_id=_uuid(number), attach_line_id=wire.LIFELINE_ATTACH_LINE, distance=distance
    )
    connections = [
        wire.connection(
            id=_uuid(20),
            points=[wire.ConnectorPoint(x=160.0, y=672.0, kind="straight"), wire.ConnectorPoint(x=350.0, y=672.0, kind="straight")],
            start_attachment=line(13, 32.0), end_attachment=line(14, 0.0), end_ending="filledArrow",
        ),
        wire.connection(
            id=_uuid(21),
            points=[
                wire.ConnectorPoint(x=160.0, y=700.0, kind="straight"), wire.ConnectorPoint(x=190.0, y=700.0, kind="straight"),
                wire.ConnectorPoint(x=190.0, y=720.0, kind="straight"), wire.ConnectorPoint(x=160.0, y=720.0, kind="straight"),
            ],
            start_attachment=line(13, 60.0), end_attachment=line(13, 80.0), end_ending="filledArrow",
        ),
        wire.connection(
            id=_uuid(22),
            points=[wire.ConnectorPoint(x=300.0, y=490.0, kind="straight"), wire.ConnectorPoint(x=160.0, y=600.0, kind="straight")],
            start_attachment=wire.Attachment(element_id=_uuid(8), connection_point_id=1),
            end_attachment=wire.Attachment(element_id=_uuid(13), connection_point_id=2),
        ),
    ]
    page = wire.page(
        id=_uuid(100), name="Complex", elements=elements, connections=connections,
        groups=[
            wire.Group(
                id=_uuid(200),
                members=[wire.GroupMember(kind="element", id=_uuid(2)), wire.GroupMember(kind="element", id=_uuid(3))],
                is_locked=False, rotation_degrees=0.0,
            )
        ],
    )
    return wire.document(id=DOCUMENT_ID, name="Complex profile", pages=[page])


def minimal_document() -> wire.Document:
    """The smallest valid document: one empty page and no quick styles."""
    return wire.document(
        id=DOCUMENT_ID, name="Minimal", quick_styles=[], pages=[wire.page(id=_uuid(100), name="Page 1")]
    )


def documents_with_one_key_removed(document: dict) -> list[tuple[str, dict]]:
    """Every copy of a dumped document that lacks exactly one key.

    Used to show that no key the app requires can go missing unnoticed: each
    copy the models still accept must also open in the app.
    """
    import copy

    results: list[tuple[str, dict]] = []

    def walk(node: object, path: tuple) -> None:
        if isinstance(node, dict):
            for key in node:
                trimmed = copy.deepcopy(document)
                target = trimmed
                for step in path:
                    target = target[step]
                del target[key]
                results.append((".".join(str(step) for step in (*path, key)), trimmed))
                walk(node[key], (*path, key))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, (*path, index))

    walk(document, ())
    return results
