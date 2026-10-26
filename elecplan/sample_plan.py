"""A small two-sheet residence drawn at 1/4 inch = 1 foot, for trying the app."""

from __future__ import annotations

import pymupdf

# 1/4" = 1'-0" → 18 points per foot.
PT = 18.0
WALL = (0.16, 0.16, 0.16)
INK = (0.12, 0.12, 0.12)
DOOR = (0.28, 0.28, 0.28)
GLASS = (0.22, 0.38, 0.58)
DIM = (0.20, 0.28, 0.55)
NOTE = (0.25, 0.25, 0.25)
TH = 0.42  # wall thickness, feet


def _p(ox, oy, x, y):
    return pymupdf.Point(ox + x * PT, oy + y * PT)


def build_sample_pdf() -> bytes:
    doc = pymupdf.open()
    _sheet(
        doc,
        "FIRST FLOOR",
        "1 OF 2",
        _first_floor,
    )
    _sheet(
        doc,
        "SECOND FLOOR",
        "2 OF 2",
        _second_floor,
    )
    doc.set_metadata(
        {
            "title": "Sample residence",
            "author": "Plan Marks",
            "creator": "Plan Marks sample plan",
        }
    )
    data = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return data


def _sheet(doc, title, sheet_no, draw_plan):
    page = doc.new_page(width=17 * 72, height=11 * 72)
    ox, oy = 64, 52
    draw_plan(page, ox, oy)
    _title_block(page, title, sheet_no)


def _hwall(page, ox, oy, x0, x1, y):
    page.draw_rect(
        pymupdf.Rect(_p(ox, oy, x0, y - TH / 2), _p(ox, oy, x1, y + TH / 2)),
        color=WALL,
        fill=WALL,
        width=0.4,
    )


def _vwall(page, ox, oy, x, y0, y1):
    page.draw_rect(
        pymupdf.Rect(_p(ox, oy, x - TH / 2, y0), _p(ox, oy, x + TH / 2, y1)),
        color=WALL,
        fill=WALL,
        width=0.4,
    )


def _label(page, ox, oy, x, y, text, size=11):
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
    pt = _p(ox, oy, x, y)
    page.insert_text(
        pymupdf.Point(pt.x - width / 2, pt.y + size * 0.35),
        text,
        fontsize=size,
        fontname="helv",
        color=NOTE,
    )


def _window_h(page, ox, oy, x0, x1, y):
    for dy, width in ((-0.12, 0.6), (0, 0.9), (0.12, 0.6)):
        page.draw_line(
            _p(ox, oy, x0, y + dy),
            _p(ox, oy, x1, y + dy),
            color=GLASS,
            width=width,
        )
    for x in (x0, x1):
        page.draw_line(
            _p(ox, oy, x, y - TH / 2),
            _p(ox, oy, x, y + TH / 2),
            color=WALL,
            width=1.1,
        )


def _window_v(page, ox, oy, x, y0, y1):
    for dx, width in ((-0.12, 0.6), (0, 0.9), (0.12, 0.6)):
        page.draw_line(
            _p(ox, oy, x + dx, y0),
            _p(ox, oy, x + dx, y1),
            color=GLASS,
            width=width,
        )
    for y in (y0, y1):
        page.draw_line(
            _p(ox, oy, x - TH / 2, y),
            _p(ox, oy, x + TH / 2, y),
            color=WALL,
            width=1.1,
        )


def _door(page, ox, oy, hx, hy, ex, ey, beta):
    """Door leaf from hinge to end, plus a swing arc of beta degrees."""
    hinge = _p(ox, oy, hx, hy)
    end = _p(ox, oy, ex, ey)
    page.draw_line(hinge, end, color=DOOR, width=1.05)
    shape = page.new_shape()
    shape.draw_sector(hinge, end, beta, fullSector=False)
    shape.finish(color=DOOR, width=0.7, closePath=False)
    shape.commit()


def _dim_h(page, ox, oy, x0, x1, y, label):
    a = _p(ox, oy, x0, y)
    b = _p(ox, oy, x1, y)
    page.draw_line(a, b, color=DIM, width=0.8)
    tick = 5
    for pt in (a, b):
        page.draw_line(
            pymupdf.Point(pt.x, pt.y - tick),
            pymupdf.Point(pt.x, pt.y + tick),
            color=DIM,
            width=0.8,
        )
    mid = pymupdf.Point((a.x + b.x) / 2 - 28, a.y - 16)
    page.insert_text(mid, label, fontsize=9, fontname="helv", color=DIM)


def _first_floor(page, ox, oy):
    # Outer shell, 36 ft x 22 ft. Gaps are doors and windows.
    _hwall(page, ox, oy, 0, 10, 0)
    _window_h(page, ox, oy, 10, 15, 0)
    _hwall(page, ox, oy, 15, 36, 0)

    _hwall(page, ox, oy, 0, 5.2, 22)
    _hwall(page, ox, oy, 8.2, 36, 22)

    _vwall(page, ox, oy, 0, 0, 7)
    _window_v(page, ox, oy, 0, 7, 11)
    _vwall(page, ox, oy, 0, 11, 22)

    _vwall(page, ox, oy, 36, 0, 14)
    _window_v(page, ox, oy, 36, 14, 18.5)
    _vwall(page, ox, oy, 36, 18.5, 22)

    # Living | right wing.
    _vwall(page, ox, oy, 16, 0, 8.2)
    _vwall(page, ox, oy, 16, 11.2, 22)
    # Bed / bath split and bath / closet.
    _vwall(page, ox, oy, 26, 0, 4.3)
    _vwall(page, ox, oy, 26, 7.2, 12)
    _hwall(page, ox, oy, 16, 23.2, 12)
    _hwall(page, ox, oy, 26.2, 36, 12)
    _hwall(page, ox, oy, 26, 36, 7)

    # Front door, swinging into the living room.
    _door(page, ox, oy, 5.2, 22, 5.2, 19.4, 90)
    # Bed to hall.
    _door(page, ox, oy, 16, 8.2, 18.4, 8.2, -90)
    # Hall to kitchen.
    _door(page, ox, oy, 23.2, 12, 23.2, 14.4, 90)
    # Bath.
    _door(page, ox, oy, 26, 4.3, 28.2, 4.3, 80)

    _label(page, ox, oy, 8, 6, "BEDROOM")
    _label(page, ox, oy, 8, 15.6, "LIVING")
    _label(page, ox, oy, 21, 6, "HALL")
    _label(page, ox, oy, 31, 3.6, "BATH", 10)
    _label(page, ox, oy, 31, 9.4, "CLOSET", 9)
    _label(page, ox, oy, 26, 17.2, "KITCHEN")

    # Exactly 10 feet, for the calibrate tool. 10 * 18 pt = 180 pt.
    _dim_h(page, ox, oy, 3, 13, 19.2, "10'-0\"")
    page.insert_text(
        _p(ox, oy, 0, 25.8),
        "The 10 ft line inside the living room is for Calibrate.",
        fontsize=8,
        fontname="helv",
        color=DIM,
    )
    _dim_h(page, ox, oy, 0, 36, 24.3, "36'-0\"")
    page.insert_text(
        _p(ox, oy, 0, -1.35),
        "SCALE 1/4\" = 1'-0\"",
        fontsize=9,
        fontname="helv",
        color=NOTE,
    )


def _second_floor(page, ox, oy):
    _hwall(page, ox, oy, 0, 36, 0)
    _hwall(page, ox, oy, 0, 36, 22)
    _vwall(page, ox, oy, 0, 0, 22)
    _vwall(page, ox, oy, 36, 0, 22)
    _vwall(page, ox, oy, 18, 0, 8)
    _vwall(page, ox, oy, 18, 11, 22)
    _hwall(page, ox, oy, 0, 8, 12)
    _hwall(page, ox, oy, 11, 25, 12)
    _hwall(page, ox, oy, 28, 36, 12)
    _window_h(page, ox, oy, 4, 9, 0)
    _window_h(page, ox, oy, 22, 28, 0)
    _window_h(page, ox, oy, 6, 12, 22)

    _door(page, ox, oy, 8, 12, 8, 14.5, 90)
    _door(page, ox, oy, 25, 12, 25, 9.6, -80)

    _label(page, ox, oy, 9, 6, "BEDROOM 2")
    _label(page, ox, oy, 27, 6, "BEDROOM 3")
    _label(page, ox, oy, 9, 16.6, "HALL")
    _label(page, ox, oy, 27, 17, "SITTING")
    _dim_h(page, ox, oy, 0, 10, 19.2, "10'-0\"")
    page.insert_text(
        _p(ox, oy, 0, -1.35),
        "SCALE 1/4\" = 1'-0\"",
        fontsize=9,
        fontname="helv",
        color=NOTE,
    )


def _title_block(page, title, sheet_no):
    rect = pymupdf.Rect(page.rect.width - 250, page.rect.height - 118, page.rect.width - 36, page.rect.height - 36)
    page.draw_rect(rect, color=INK, width=1.2)
    page.insert_text(
        pymupdf.Point(rect.x0 + 12, rect.y0 + 22),
        "SAMPLE RESIDENCE",
        fontsize=11,
        fontname="helv",
        color=INK,
    )
    page.insert_text(
        pymupdf.Point(rect.x0 + 12, rect.y0 + 42),
        title,
        fontsize=13,
        fontname="helv",
        color=INK,
    )
    page.insert_text(
        pymupdf.Point(rect.x0 + 12, rect.y0 + 62),
        'SCALE  1/4" = 1\'-0"',
        fontsize=9,
        fontname="helv",
        color=NOTE,
    )
    page.insert_text(
        pymupdf.Point(rect.x0 + 12, rect.y0 + 76),
        f"SHEET  {sheet_no}",
        fontsize=9,
        fontname="helv",
        color=NOTE,
    )
