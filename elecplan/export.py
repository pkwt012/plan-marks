"""Stamp symbol placements onto a copy of a floor-plan PDF."""

from __future__ import annotations

import math
import re

import pymupdf

from elecplan.library import prepare_svg

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _page_index(item: dict, page_count: int) -> int:
    page = int(item["page"])
    if page < 0 or page >= page_count:
        raise ValueError("page out of range")
    return page


def _color(item: dict) -> str:
    color = item.get("color") or "#141414"
    if not _HEX.fullmatch(str(color)):
        raise ValueError("bad color")
    return str(color).lower()


def _finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("non-numeric coordinate")


def parse_placements(raw, page_count: int, symbol_ids: set[str]) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("placements must be a list")
    if len(raw) > 5000:
        raise ValueError("too many symbols (limit 5000)")
    out = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"placement {index} is not an object")
        kind = item.get("kind") or ("symbol" if "symbolId" in item else "")
        try:
            if kind == "line":
                page = _page_index(item, page_count)
                x1, y1 = float(item["x1"]), float(item["y1"])
                x2, y2 = float(item["x2"]), float(item["y2"])
                color = _color(item)
                _finite(x1, y1, x2, y2)
                out.append(
                    {
                        "kind": "line",
                        "page": page,
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "color": color,
                    }
                )
                continue
            if kind == "legend":
                page = _page_index(item, page_count)
                x, y = float(item["x"]), float(item["y"])
                width = float(item["width"])
                _finite(x, y, width)
                if not 40 <= width <= 2000:
                    raise ValueError("legend width must be between 40 and 2000 points")
                out.append({"kind": "legend", "page": page, "x": x, "y": y, "width": width})
                continue
            if kind != "symbol":
                raise ValueError(f"unknown kind {kind!r}")
            sid = item["symbolId"]
            if sid not in symbol_ids:
                raise ValueError(f"unknown symbol {sid}")
            page = _page_index(item, page_count)
            x = float(item["x"])
            y = float(item["y"])
            size = float(item["size"])
            rotation = float(item.get("rotation") or 0)
            color = _color(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"placement {index}: {exc}") from exc
        _finite(x, y, size, rotation)
        if not 2 <= size <= 500:
            raise ValueError(f"placement {index} size must be between 2 and 500 points")
        out.append(
            {
                "kind": "symbol",
                "symbolId": sid,
                "page": page,
                "x": x,
                "y": y,
                "size": size,
                "rotation": rotation,
                "color": color,
            }
        )
    return out


def _svg_to_pdf(svg: str) -> pymupdf.Document:
    src = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
    try:
        pdf_bytes = src.convert_to_pdf()
    finally:
        src.close()
    return pymupdf.open(stream=pdf_bytes, filetype="pdf")


def _rgb(color: str) -> tuple[float, float, float]:
    return (
        int(color[1:3], 16) / 255,
        int(color[3:5], 16) / 255,
        int(color[5:7], 16) / 255,
    )


def _draw_line(page, item: dict) -> None:
    """Dashed switch leg. Endpoints are visual; drawing uses unrotated space."""
    matrix = page.derotation_matrix
    start = pymupdf.Point(item["x1"], item["y1"]) * matrix
    end = pymupdf.Point(item["x2"], item["y2"]) * matrix
    page.draw_line(
        start,
        end,
        color=_rgb(item["color"]),
        width=1.35,
        dashes="[8 6] 0",
        lineCap=0,
        overlay=True,
    )


def _stamp_legend(page, item: dict, src: pymupdf.Document, nat_w: float, nat_h: float) -> None:
    width = float(item["width"])
    height = nat_h * width / nat_w
    rect = pymupdf.Rect(item["x"], item["y"], item["x"] + width, item["y"] + height)
    rect = rect * page.derotation_matrix
    page.show_pdf_page(rect, src, 0, overlay=True, keep_proportion=True)


def export_pdf(pdf_bytes: bytes, placements: list[dict], symbols_by_id: dict) -> bytes:
    """Return a new PDF with each placement drawn on top of the original page.

    Coordinates are visual: origin at the top-left of the page as shown,
    y downward, units in PDF points. Page rotation (/Rotate) is honored.
    A placement is a symbol unless kind is "line" or "legend".
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    cache: dict[tuple, pymupdf.Document] = {}
    legend_doc: pymupdf.Document | None = None
    legend_size: tuple[float, float] | None = None
    try:
        for item in placements:
            page = doc[item["page"]]
            kind = item.get("kind") or "symbol"
            if kind == "line":
                _draw_line(page, item)
                continue
            if kind == "legend":
                if legend_doc is None:
                    from elecplan.legend import build_legend_block

                    raw, nat_w, nat_h = build_legend_block(list(symbols_by_id.values()))
                    legend_doc = pymupdf.open(stream=raw, filetype="pdf")
                    legend_size = (nat_w, nat_h)
                assert legend_size is not None
                _stamp_legend(page, item, legend_doc, legend_size[0], legend_size[1])
                continue
            key = (item["symbolId"], round(float(item["rotation"]), 1), item["color"])
            src = cache.get(key)
            if src is None:
                svg = prepare_svg(
                    symbols_by_id[item["symbolId"]]["svg"],
                    item["rotation"],
                    item["color"],
                )
                src = _svg_to_pdf(svg)
                cache[key] = src
            size = item["size"]
            x = item["x"]
            y = item["y"]
            rect = pymupdf.Rect(x - size / 2, y - size / 2, x + size / 2, y + size / 2)
            # show_pdf_page uses the unrotated page space. derotation_matrix
            # maps a rectangle in the on-screen (rotated) view back to that space.
            rect = rect * page.derotation_matrix
            page.show_pdf_page(rect, src, 0, overlay=True, keep_proportion=True)
        return doc.tobytes(deflate=True, garbage=3)
    finally:
        for src in cache.values():
            src.close()
        if legend_doc is not None:
            legend_doc.close()
        doc.close()
