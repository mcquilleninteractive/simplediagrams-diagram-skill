# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Draws a wireframe SVG of a document so its layout can be looked at.

    uv run scripts/preview_diagram.py spec.json preview.svg
Give it a diagram spec to look at a layout before the document is built.

Each shape is drawn as its frame with its label, and each connector as its
stored route. This shows spacing, alignment, crossings and label fit. It does
not draw the library artwork, fonts or hand-drawn line style; only
SimpleDiagrams does that.
"""

from __future__ import annotations

import argparse
import re
import sys
from html import escape as _escape_markup
from pathlib import Path

import sd_format as wire
from pydantic import ValidationError
from sd_spec import SpecError, compile_spec, load_spec

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
            # Midpoint of the middle segment is close enough for a layout check.
            a, b = core.points[(len(core.points) - 1) // 2], core.points[(len(core.points) - 1) // 2 + 1]
            parts.append(
                f'<text x="{(a.x + b.x) / 2:g}" y="{(a.y + b.y) / 2 - 5:g}" font-size="12" '
                f'text-anchor="middle" fill="#495057">{escape(core.label.content.string)}</text>'
            )
    for element in sorted(page.elements, key=lambda item: item.core.z_index):
        core = element.core
        frame = core.frame
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="A diagram spec (.json)")
    parser.add_argument("output", type=Path, help="New SVG to write; later pages get -2, -3 before the suffix")
    arguments = parser.parse_args()
    if arguments.source.suffix != ".json" or arguments.output.suffix != ".svg":
        print("error   Expected a JSON spec and a new .svg output.")
        return 1
    try:
        document = compile_spec(load_spec(arguments.source))
    except (SpecError, ValidationError) as failure:
        for line in str(failure).splitlines():
            print(f"error   {line}")
        return 1
    targets = [
        arguments.output if index == 0 else arguments.output.with_stem(f"{arguments.output.stem}-{index + 1}")
        for index in range(len(document.pages))
    ]
    if any(target.exists() or target.is_symlink() for target in targets):
        print("error   A preview output already exists; choose a new name.")
        return 1
    for target, page in zip(targets, document.pages, strict=True):
        try:
            with target.open("x", encoding="utf-8") as stream:
                stream.write(_page_svg(page))
        except OSError as failure:
            print(f"error   Could not write {target}: {failure}")
            return 1
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
