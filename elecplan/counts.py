"""A plan sheet that lists how many of each symbol are placed."""

from __future__ import annotations

import math

import pymupdf


def parse_count_rows(raw) -> list[dict]:
    """Name and count pairs for a counts sheet. Empty is allowed."""
    if not isinstance(raw, list):
        raise ValueError("counts must be a list")
    if len(raw) > 400:
        raise ValueError("too many count rows")
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("bad count row")
        name = item.get("name")
        if not isinstance(name, str):
            raise ValueError("count name is missing")
        name = " ".join(name.split())
        if not name or len(name) > 80 or any(ord(ch) < 32 for ch in name):
            raise ValueError("count name is missing")
        try:
            count = int(item["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("bad count") from exc
        if count < 1 or count > 10000:
            raise ValueError("bad count")
        rows.append({"name": name, "count": count})
    return rows


def _fit(text: str, fontsize: float, max_width: float, fontname: str = "helv") -> str:
    if pymupdf.get_text_length(text, fontname=fontname, fontsize=fontsize) <= max_width:
        return text
    trimmed = text
    while trimmed and pymupdf.get_text_length(trimmed + "...", fontname=fontname, fontsize=fontsize) > max_width:
        trimmed = trimmed[:-1]
    trimmed = trimmed.rstrip() or text[:1]
    return trimmed + "..."


def build_counts_pdf(rows: list[dict], width: float, height: float, subtitle: str) -> bytes:
    """One or more pages, the same size as the plan sheet, listing the counts."""
    width = float(width)
    height = float(height)
    if width < 240 or height < 240:
        width, height = 792.0, 612.0
    subtitle = " ".join(str(subtitle or "").split())[:80] or "All sheets"

    margin = 48.0
    top = 78.0
    footer = 36.0
    row_h = 22.0
    name_size = 12.0
    gap = 20.0
    gutter = 36.0
    usable = height - top - footer
    per_col = max(1, int(usable // row_h))
    listed = list(rows) + [{"name": "Total", "count": sum(row["count"] for row in rows), "total": True}]
    available = width - margin * 2
    # Size the column to the names. A full-width column puts the number
    # on the far edge of a large plan sheet.
    natural = 0.0
    for row in listed:
        fontname = "hebo" if row.get("total") else "helv"
        name_w = pymupdf.get_text_length(row["name"], fontname=fontname, fontsize=name_size)
        count_w = pymupdf.get_text_length(str(row["count"]), fontname=fontname, fontsize=name_size)
        natural = max(natural, name_w + gap + count_w)
    col_w = min(natural + 1.0, available, 420.0)
    cols = 2 if len(listed) > per_col and available >= col_w * 2 + gutter else 1
    per_page = per_col * cols
    page_count = max(1, math.ceil(len(listed) / per_page))
    pitch = col_w + gutter
    ink = (0.1, 0.1, 0.1)
    quiet = (0.35, 0.35, 0.35)

    doc = pymupdf.open()
    try:
        for page_index in range(page_count):
            page = doc.new_page(width=width, height=height)
            page.insert_text(
                pymupdf.Point(margin, 42),
                "SYMBOL COUNTS",
                fontsize=16,
                fontname="helv",
                color=ink,
            )
            page.insert_text(
                pymupdf.Point(margin, 60),
                subtitle,
                fontsize=11,
                fontname="helv",
                color=quiet,
            )
            if page_count > 1:
                label = f"{page_index + 1} of {page_count}"
                label_w = pymupdf.get_text_length(label, fontname="helv", fontsize=10)
                page.insert_text(
                    pymupdf.Point(width - margin - label_w, 40),
                    label,
                    fontsize=10,
                    fontname="helv",
                    color=quiet,
                )
            chunk = listed[page_index * per_page : (page_index + 1) * per_page]
            for index, row in enumerate(chunk):
                col = index // per_col
                line = index % per_col
                x = margin + col * pitch
                y = top + line * row_h
                fontname = "hebo" if row.get("total") else "helv"
                count = str(row["count"])
                count_w = pymupdf.get_text_length(count, fontname=fontname, fontsize=name_size)
                name = _fit(row["name"], name_size, max(8.0, col_w - count_w - gap), fontname)
                page.insert_text(pymupdf.Point(x, y), name, fontsize=name_size, fontname=fontname, color=ink)
                page.insert_text(
                    pymupdf.Point(x + col_w - count_w, y),
                    count,
                    fontsize=name_size,
                    fontname=fontname,
                    color=ink,
                )
        return doc.tobytes()
    finally:
        doc.close()
