# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Draws a wireframe SVG of a document so its layout can be looked at.

    uv run scripts/preview_diagram.py spec.json preview.svg
Give it a diagram spec to look at a layout before the document is built.

Each shape is drawn as its frame with its label, and each connector as its
stored route. A complex shape is drawn as its parts: a container's title, lanes
and their titles, a table's cells, a callout's tail and a lifeline's head and
line. This shows spacing, alignment, crossings and label fit. It does not draw
the library artwork, fonts or hand-drawn line style; only SimpleDiagrams does
that.
"""

from __future__ import annotations

import sys

# The skill writes nothing but the output it is asked for, not even Python's bytecode.
sys.dont_write_bytecode = True

import argparse
import re
from html import escape as _escape_markup
from pathlib import Path

import sd_format as wire
from pydantic import ValidationError
from sd_spec import Catalog, SpecError, compile_spec, echo, load_spec

MARGIN = 40
# XML 1.0 cannot carry these at all, even escaped.
_NOT_XML = re.compile("[^\\x09\\x0a\\x0d\\x20-\\ud7ff\\ue000-\\ufffd\\U00010000-\\U0010ffff]")


def escape(text: str) -> str:
    """Makes text safe for SVG, dropping characters XML does not allow."""
    return _escape_markup(_NOT_XML.sub("", text))


def _page_svg(page: wire.Page) -> str:
    boxes = [element.core.frame for element in page.elements]
    xs = [box.x for box in boxes] + [box.x + box.width for box in boxes]
    ys = [box.y for box in boxes] + [box.y + box.height for box in boxes]
    for connection in page.connections:
        xs += [point.x for point in connection.content.points]
        ys += [point.y for point in connection.content.points]
    left, top = min(xs, default=0) - MARGIN, min(ys, default=0) - MARGIN
    width = max(xs, default=100) - left + MARGIN
    height = max(ys, default=100) - top + MARGIN + 24
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:g} {top:g} {width:g} {height:g}" '
            f'width="{width:g}" height="{height:g}" font-family="Helvetica, Arial, sans-serif">'
        ),
        f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="{height:g}" fill="#ffffff"/>',
        (
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs>'
        ),
    ]
    order = page.content.drawableOrder
    by_id = {element.core.id.upper(): element for element in page.elements}
    drawn = (
        [by_id[entry.id.upper()] for entry in order if entry.kind == "element"]
        if order is not None
        else sorted(page.elements, key=lambda item: item.core.z_index)
    )
    # Containers and swimlanes are drawn behind the connectors that run into them.
    for element in drawn:
        if element.complex_shape is not None and element.complex_shape.holds_shapes:
            parts.extend(_complex_svg(element))
    for connection in page.connections:
        core = connection.content
        route = " ".join(f"{point.x:g},{point.y:g}" for point in core.points)
        dash = {"solid": "", "dashed": ' stroke-dasharray="8 5"', "dotted": ' stroke-dasharray="2 4"'}[core.stroke_pattern]
        start = ' marker-start="url(#arrow)"' if core.start_ending != "none" else ""
        end = ' marker-end="url(#arrow)"' if core.end_ending != "none" else ""
        parts.append(
            f'<polyline points="{route}" fill="none" stroke="{core.stroke_hex[:7]}" '
            f'stroke-width="{max(core.line_width, 1):g}"{dash}{start}{end}/>'
        )
        if core.label:
            # Midpoint of the middle segment, moved off the line as the app moves it, is close
            # enough for a layout check.
            a, b = core.points[(len(core.points) - 1) // 2], core.points[(len(core.points) - 1) // 2 + 1]
            length = max(1e-9, ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5)
            offset = core.label.normal_offset
            x = (a.x + b.x) / 2 - (b.y - a.y) / length * offset
            y = (a.y + b.y) / 2 + (b.x - a.x) / length * offset
            parts.append(
                f'<text x="{x:g}" y="{y - 5:g}" font-size="12" '
                f'text-anchor="middle" fill="#495057">{escape(core.label.content.string)}</text>'
            )
    for element in drawn:
        core = element.core
        frame = core.frame
        if element.complex_shape is not None:
            if not element.complex_shape.holds_shapes:
                parts.extend(_complex_svg(element))
            continue
        fill = core.style.fill_hex[:7] if len(core.style.fill_hex) == 7 else "none"
        stroke = core.style.stroke_hex[:7] if core.kind != "text" else "none"
        rounding = min(frame.width, frame.height) / 2 if core.kind == "ellipse" else 3
        dash = ' stroke-dasharray="5 3"' if core.kind == "symbol" else ""
        parts.append(
            f'<rect x="{frame.x:g}" y="{frame.y:g}" width="{frame.width:g}" height="{frame.height:g}" '
            f'rx="{rounding:g}" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>'
        )
        if core.symbol_reference:
            parts.append(
                f'<text x="{frame.x + 3:g}" y="{frame.y + 9:g}" font-size="7" fill="#868e96">'
                f"{escape(core.symbol_reference.item_id)}</text>"
            )
        text = core.text_content
        if text.string:
            size = text.base_style.font_size
            lines = text.string.split("\n")
            position = element.content.text_layout.position if element.content.text_layout else "middle"
            centre_y = {
                "above": frame.y - len(lines) * size * 0.65,
                "below": frame.y + frame.height + len(lines) * size * 0.65 + 2,
                "top": frame.y + 10 + len(lines) * size * 0.6,
                "bottom": frame.y + frame.height - 10 - len(lines) * size * 0.6,
            }.get(position, frame.y + frame.height / 2)
            first = centre_y - (len(lines) - 1) * size * 0.65 + size * 0.35
            for index, line in enumerate(lines):
                parts.append(
                    f'<text x="{frame.x + frame.width / 2:g}" y="{first + index * size * 1.3:g}" '
                    f'font-size="{size:g}" text-anchor="middle" fill="{text.base_style.color_hex[:7]}">'
                    f"{escape(line)}</text>"
                )
    parts.append(
        f'<text x="{left + 8:g}" y="{top + height - 8:g}" font-size="10" fill="#868e96">'
        f"Wireframe preview of page {escape(page.core.name)}: frames and routes only, not the app's artwork.</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _text(x: float, y: float, text: str, size: float, anchor: str = "middle", extra: str = "") -> str:
    lines = text.split("\n")
    return "".join(
        f'<text x="{x:g}" y="{y + index * size * 1.3:g}" font-size="{size:g}" text-anchor="{anchor}" '
        f'fill="#212529"{extra}>{escape(line)}</text>'
        for index, line in enumerate(lines)
    )


def _complex_svg(element: wire.Element) -> list[str]:
    """A complex shape as the parts SimpleDiagrams draws for it, without its hand-drawn line."""
    core, shape = element.core, element.complex_shape
    assert shape is not None
    f = core.frame
    stroke = f'stroke="{core.style.stroke_hex[:7]}" stroke-width="1"'
    fill = core.style.fill_hex[:7] if len(core.style.fill_hex) == 7 else "none"
    size = core.text_content.base_style.font_size
    title = core.text_content.string
    parts: list[str] = []
    if shape.type == "container":
        parts.append(f'<rect x="{f.x:g}" y="{f.y:g}" width="{f.width:g}" height="{f.height:g}" rx="6" fill="{fill}" {stroke}/>')
        if shape.title_style == "corner_tag":
            width = min(f.width - 12, max(40, 12 + len(title) * size * 0.56 + 16))
            x, y = f.x + width, f.y + 28
            parts.append(f'<polyline points="{x:g},{f.y:g} {x:g},{y - 8:g} {x - 8:g},{y:g} {f.x:g},{y:g}" fill="none" {stroke}/>')
            parts.append(_text(f.x + 12, f.y + 19, title, size, "start"))
        else:
            parts.append(_text(f.x + 12, f.y + 21, title, size, "start"))
    elif shape.type == "swimlanes":
        parts.append(f'<rect x="{f.x:g}" y="{f.y:g}" width="{f.width:g}" height="{f.height:g}" fill="{fill}" {stroke}/>')
        band = shape.title_band_size or wire.SWIMLANES_STRIP
        strip = shape.title_strip_size or wire.SWIMLANES_STRIP
        parts.append(f'<line x1="{f.x:g}" y1="{f.y + band:g}" x2="{f.x + f.width:g}" y2="{f.y + band:g}" {stroke}/>')
        parts.append(_text(f.x + f.width / 2, f.y + band / 2 + size * 0.35, title, size))
        for index, (lane, lane_frame) in enumerate(zip(shape.lanes or [], wire.swimlane_frames(shape, f), strict=True)):
            if shape.direction == "horizontal":
                if index:
                    parts.append(f'<line x1="{f.x:g}" y1="{lane_frame.y:g}" x2="{f.x + f.width:g}" y2="{lane_frame.y:g}" {stroke}/>')
                cx, cy = f.x + strip / 2, lane_frame.y + lane_frame.height / 2
                parts.append(_text(cx, cy + size * 0.35, lane.title.string, size, extra=f' transform="rotate(-90 {cx:g} {cy:g})"'))
            else:
                if index:
                    parts.append(f'<line x1="{lane_frame.x:g}" y1="{lane_frame.y:g}" x2="{lane_frame.x:g}" y2="{f.y + f.height:g}" {stroke}/>')
                parts.append(_text(lane_frame.x + lane_frame.width / 2, lane_frame.y + strip / 2 + size * 0.35, lane.title.string, size))
        if shape.direction == "horizontal":
            parts.append(f'<line x1="{f.x + strip:g}" y1="{f.y + band:g}" x2="{f.x + strip:g}" y2="{f.y + f.height:g}" {stroke}/>')
        else:
            parts.append(f'<line x1="{f.x:g}" y1="{f.y + band + strip:g}" x2="{f.x + f.width:g}" y2="{f.y + band + strip:g}" {stroke}/>')
    elif shape.type == "table":
        rows, columns = shape.row_sizes or [], shape.column_sizes or []
        heights = [share / sum(rows) * f.height for share in rows]
        widths = [share / sum(columns) * f.width for share in columns]
        header = shape.header_row is None
        parts.append(f'<rect x="{f.x:g}" y="{f.y:g}" width="{f.width:g}" height="{f.height:g}" fill="none" {stroke}/>')
        y = f.y
        for row, (height, cells) in enumerate(zip(heights, shape.cells or [], strict=True)):
            if header and row == 0:
                parts.append(f'<rect x="{f.x:g}" y="{y:g}" width="{f.width:g}" height="{height:g}" fill="{fill}" {stroke}/>')
            x = f.x
            for width, cell in zip(widths, cells, strict=True):
                parts.append(f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" fill="none" {stroke}/>')
                leading = cell.base_alignment == "leading"
                weight = ' font-weight="bold"' if header and row == 0 else ""
                parts.append(_text(x + 6 if leading else x + width / 2, y + 3 + cell.base_style.font_size, cell.string,
                                   cell.base_style.font_size, "start" if leading else "middle", weight))
                x += width
            y += height
    elif shape.type == "callout":
        if shape.tail_tip is not None:
            sign_x = -1 if element.content.flip_horizontal else 1
            sign_y = -1 if element.content.flip_vertical else 1
            tip = (f.x + f.width / 2 + sign_x * shape.tail_tip.x, f.y + f.height / 2 + sign_y * shape.tail_tip.y)
            cx, cy = f.x + f.width / 2, f.y + f.height / 2
            parts.append(f'<polygon points="{cx - 10:g},{cy:g} {tip[0]:g},{tip[1]:g} {cx + 10:g},{cy:g}" fill="{fill}" {stroke}/>')
        parts.append(f'<rect x="{f.x:g}" y="{f.y:g}" width="{f.width:g}" height="{f.height:g}" rx="10" fill="{fill}" {stroke}/>')
        parts.append(_text(f.x + f.width / 2, f.y + f.height / 2 + size * 0.35, title, size))
    elif shape.type == "lifeline":
        start, end = wire.lifeline_line(shape, f)
        cx = f.x + f.width / 2
        if shape.head_style == "actor":
            parts.append(f'<circle cx="{cx:g}" cy="{f.y + 8:g}" r="7" fill="none" {stroke}/>')
            parts.append(f'<polyline points="{cx - 12:g},{f.y + 22:g} {cx + 12:g},{f.y + 22:g}" fill="none" {stroke}/>')
            parts.append(f'<polyline points="{cx:g},{f.y + 15:g} {cx:g},{f.y + 34:g} {cx - 10:g},{f.y + 48:g}" fill="none" {stroke}/>')
            parts.append(f'<line x1="{cx:g}" y1="{f.y + 34:g}" x2="{cx + 10:g}" y2="{f.y + 48:g}" {stroke}/>')
            parts.append(_text(cx, f.y + 66, title, size))
        else:
            parts.append(f'<rect x="{f.x:g}" y="{f.y:g}" width="{f.width:g}" height="{start:g}" fill="{fill}" {stroke}/>')
            parts.append(_text(cx, f.y + start / 2 + size * 0.35, title, size))
        parts.append(f'<line x1="{cx:g}" y1="{f.y + start:g}" x2="{cx:g}" y2="{f.y + end:g}" stroke-dasharray="8 5" {stroke}/>')
        if shape.ends_in_destroy_mark:
            half = wire.DESTROY_MARK_SIZE / 2
            y = f.y + end
            parts.append(f'<path d="M{cx - half:g} {y - half:g}L{cx + half:g} {y + half:g}M{cx + half:g} {y - half:g}L{cx - half:g} {y + half:g}" {stroke}/>')
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="A diagram spec (.json)")
    parser.add_argument("output", type=Path, help="New SVG to write; later pages get -2, -3 before the suffix")
    parser.add_argument("--offline", action="store_true", help="Use the packaged shapes only, without a request")
    arguments = parser.parse_args(argv)
    if arguments.source.suffix != ".json" or arguments.output.suffix != ".svg":
        echo("error   Expected a JSON spec and a new .svg output.")
        return 1
    try:
        catalog = Catalog.load_current(offline=arguments.offline)
        echo(f"Catalogue: {catalog.source}", file=sys.stderr)
        if catalog.warning:
            echo(catalog.warning, file=sys.stderr)
        document = compile_spec(load_spec(arguments.source), catalog)
    except (SpecError, ValidationError) as failure:
        for line in str(failure).splitlines():
            echo(f"error   {line}")
        return 1
    targets = [
        arguments.output if index == 0 else arguments.output.with_stem(f"{arguments.output.stem}-{index + 1}")
        for index in range(len(document.pages))
    ]
    if any(target.exists() or target.is_symlink() for target in targets):
        echo("error   A preview output already exists; choose a new name.")
        return 1
    for target, page in zip(targets, document.pages, strict=True):
        try:
            with target.open("x", encoding="utf-8") as stream:
                stream.write(_page_svg(page))
        except OSError as failure:
            echo(f"error   Could not write {target}: {failure}")
            return 1
        echo(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
