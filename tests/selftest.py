"""API, placement, and export checks for Plan Marks. No network beyond localhost."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf

from elecplan.export import export_pdf, parse_placements
from elecplan.legend import build_legend_block, build_legend_pdf, legend_layout
from elecplan.library import load_symbols, prepare_svg
from elecplan.sample_plan import build_sample_pdf
from elecplan.server import App, make_server

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def request(base, path, data=None, headers=None, method=None):
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
            return res.status, dict(res.headers), body
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def dark_pixels(pix, x0, y0, x1, y1):
    x0, x1 = int(max(0, min(x0, x1))), int(min(pix.width, max(x0, x1)))
    y0, y1 = int(max(0, min(y0, y1))), int(min(pix.height, max(y0, y1)))
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            px = pix.pixel(x, y)
            if px[0] < 200 or px[1] < 200 or px[2] < 200:
                count += 1
    return count


def text_dirs(page, needle):
    found = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", []))
            if needle in text:
                found.append((text, line.get("dir")))
    return found


def main():
    print("library")
    lib = load_symbols()
    ids = {item["id"] for item in lib["symbols"]}
    needed = {"duplex", "gfci", "switch", "switch3", "ceiling", "sconce", "smoke", "panel"}
    check("core symbols", needed <= ids, sorted(needed - ids))
    check("at least 12 symbols", len(lib["symbols"]) >= 12, str(len(lib["symbols"])))
    added = {
        "single",
        "usb",
        "ev",
        "outlet30",
        "outlet50",
        "coax",
        "cat6",
        "coaxcat6",
        "smurf",
        "chime",
        "meter",
    }
    check("new symbols", added <= ids, sorted(added - ids))
    gfci = next(item for item in lib["symbols"] if item["id"] == "gfci")
    check("gfi is an outlet", "<circle" in gfci["svg"] and ">GFI<" in gfci["svg"])
    dimmer = next(item for item in lib["symbols"] if item["id"] == "dimmer")
    check("dimmer is a switch marked D", ">SD<" in dimmer["svg"])
    timer = next(item for item in lib["symbols"] if item["id"] == "timer")
    ac = next(item for item in lib["symbols"] if item["id"] == "ac")
    check("timer switch is ST", ">ST<" in timer["svg"] and "<circle" not in timer["svg"])
    check("a/c is a labeled box", "<rect" in ac["svg"] and ">A/C<" in ac["svg"])
    panel = next(item for item in lib["symbols"] if item["id"] == "panel")
    check("panel is a labeled box", "<rect" in panel["svg"] and ">PANEL<" in panel["svg"])
    check("lighting additions", {"ucl", "pendant", "exhaust"} <= ids)
    ucl = next(item for item in lib["symbols"] if item["id"] == "ucl")
    pendant = next(item for item in lib["symbols"] if item["id"] == "pendant")
    exhaust = next(item for item in lib["symbols"] if item["id"] == "exhaust")
    fan = next(item for item in lib["symbols"] if item["id"] == "fan")
    check("ucl is letters", ">UCL<" in ucl["svg"] and "<circle" not in ucl["svg"])
    check("pendant hangs", "<circle" in pendant["svg"] and "<line" in pendant["svg"])
    check("bath fan is EF", ">EF<" in exhaust["svg"] and "<circle" in exhaust["svg"])
    check("bath fan is not the ceiling fan", "ellipse" in fan["svg"] and "ellipse" not in exhaust["svg"])
    layout = legend_layout(lib["symbols"])
    check(
        "drop legend lists every symbol",
        {entry["id"] for entry in layout["items"]} == ids and layout["width"] > 200,
    )
    for item in lib["symbols"]:
        check(f"svg {item['id']}", "viewBox" in item["svg"] and 'class="rot"' in item["svg"])

    rotated = prepare_svg(lib["symbols"][0]["svg"], 90, "#c4271b")
    check("rotation baked", "rotate(90.00 50 50)" in rotated)
    check("color baked", "#c4271b" in rotated and "#141414" not in rotated)
    upright = prepare_svg(next(s["svg"] for s in lib["symbols"] if s["id"] == "switch3"), 90, "#141414")
    check(
        "rotation wraps the symbol",
        'class="spin"' in upright and upright.index('class="label"') > upright.index("rotate(90.00 50 50)"),
    )

    extra = Path("/tmp/planmarks-extra-symbols")
    if extra.exists():
        for child in extra.iterdir():
            child.unlink()
    else:
        extra.mkdir()
    (extra / "catalog.json").write_text(
        json.dumps(
            {
                "categories": [{"id": "receptacles", "name": "Receptacles"}],
                "symbols": [
                    {
                        "id": "duplex",
                        "name": "Duplex outlet",
                        "category": "receptacles",
                        "file": "duplex.svg",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (extra / "duplex.svg").write_text(
        (ROOT / "symbols" / "duplex.svg").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (extra / "custom_mark.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <g class="rot" fill="none" stroke="#141414" stroke-width="4">
    <circle cx="50" cy="50" r="20"/>
  </g>
</svg>""",
        encoding="utf-8",
    )
    extra_lib = load_symbols(extra)
    check(
        "dropped-in symbol",
        any(item["id"] == "custom_mark" and item["category"] == "custom" for item in extra_lib["symbols"]),
    )

    print("sample plan")
    sample = build_sample_pdf()
    sample_doc = pymupdf.open(stream=sample, filetype="pdf")
    check("sample has 2 sheets", sample_doc.page_count == 2)
    sample_text = sample_doc[0].get_text()
    check("sample has living room", "LIVING" in sample_text, sample_text[:200])
    check("sample names the 10 ft dimension", "10'-0\"" in sample_text)
    sample_doc[0].get_pixmap(dpi=80, alpha=False).save("/tmp/planmarks-sample.png")
    sample_doc.close()

    print("stamp")
    by_id = {item["id"]: item for item in lib["symbols"]}
    # Blank page. Duplex bars run across the circle and turn with the symbol.
    # A switch is the letter only: no framing circle and no leader.
    blank = pymupdf.open()
    blank.new_page(width=300, height=300)
    blank_bytes = blank.tobytes()
    blank.close()

    def placed(symbol, rotation):
        return export_pdf(
            blank_bytes,
            [
                {
                    "symbolId": symbol,
                    "page": 0,
                    "x": 150,
                    "y": 150,
                    "size": 100,
                    "rotation": rotation,
                    "color": "#141414",
                }
            ],
            by_id,
        )

    flat_doc = pymupdf.open(stream=placed("duplex", 0), filetype="pdf")
    flat_pix = flat_doc[0].get_pixmap(dpi=72, alpha=False)
    # Upper bar is viewBox y=44, x=32..68 → page y=144, x=132..168.
    across = dark_pixels(flat_pix, 132, 141, 140, 147)
    slot = dark_pixels(flat_pix, 141, 132, 147, 140)
    below = dark_pixels(flat_pix, 144, 186, 156, 198)
    check("duplex bars run across", across > 8, f"across={across}")
    check("duplex bars are not vertical", slot < 8, f"slot={slot}")
    check("no line below the duplex", below < 8, f"below={below}")
    flat_doc.close()

    spun_doc = pymupdf.open(stream=placed("duplex", 90), filetype="pdf")
    spun_pix = spun_doc[0].get_pixmap(dpi=72, alpha=False)
    across90 = dark_pixels(spun_pix, 132, 141, 140, 147)
    slot90 = dark_pixels(spun_pix, 141, 132, 147, 140)
    below90 = dark_pixels(spun_pix, 144, 186, 156, 198)
    check("duplex bars turn vertical", slot90 > 8, f"slot={slot90}")
    check("turned bars leave the old bar", across90 < 8, f"across={across90}")
    check("no line below a turned duplex", below90 < 8, f"below={below90}")
    spun_doc.close()

    letter_doc = pymupdf.open(stream=placed("switch", 90), filetype="pdf")
    letter_pix = letter_doc[0].get_pixmap(dpi=72, alpha=False)
    # Diagonals of a framing circle (r≈30). The letter sits inside that ring.
    ring = (
        dark_pixels(letter_pix, 166, 166, 176, 176)
        + dark_pixels(letter_pix, 124, 166, 134, 176)
        + dark_pixels(letter_pix, 166, 124, 176, 134)
        + dark_pixels(letter_pix, 124, 124, 134, 134)
    )
    check("switch has no framing circle", ring < 8, f"ring={ring}")
    dirs = text_dirs(letter_doc[0], "S")
    check("switch letter turns", bool(dirs) and abs(dirs[0][1][0]) < 0.2, str(dirs))
    letter_doc.close()

    # Page stored with /Rotate 90. Symbol at the visual center must land there.
    wide = pymupdf.open()
    page = wide.new_page(width=400, height=200)
    page.insert_text((170, 100), "HELLO", fontsize=18, fontname="helv")
    wide_bytes = wide.tobytes()
    wide.close()
    rotated_src = pymupdf.open(stream=wide_bytes, filetype="pdf")
    rotated_src[0].set_rotation(90)
    rotated_bytes = rotated_src.tobytes()
    visual = rotated_src[0].rect
    rotated_src.close()
    stamped = export_pdf(
        rotated_bytes,
        [
            {
                "symbolId": "switch3",
                "page": 0,
                "x": visual.width / 2,
                "y": visual.height / 2,
                "size": 60,
                "rotation": 0,
                "color": "#c4271b",
            }
        ],
        by_id,
    )
    stamped_doc = pymupdf.open(stream=stamped, filetype="pdf")
    stamped_pix = stamped_doc[0].get_pixmap(dpi=72, alpha=False)
    cx, cy = stamped_pix.width / 2, stamped_pix.height / 2
    center_ink = dark_pixels(stamped_pix, cx - 20, cy - 20, cx + 20, cy + 20)
    corner_ink = dark_pixels(stamped_pix, 0, 0, 18, 18)
    check("rotated sheet: symbol at visual center", center_ink > 15, f"center={center_ink}")
    check("rotated sheet: corner stays blank", corner_ink == 0, f"corner={corner_ink}")
    check("original text survives stamping", "HELLO" in stamped_doc[0].get_text())
    s3_dirs = text_dirs(stamped_doc[0], "S3")
    check("S3 stays upright on a rotated sheet", bool(s3_dirs) and abs(s3_dirs[0][1][0]) > 0.9, str(s3_dirs))
    stamped_doc.close()

    # Dashed switch leg, including on a rotated sheet, plus a legend block.
    def dash_runs(pix, x0, x1, y, dark_at=180):
        runs = []
        current = None
        length = 0
        y = int(y)
        for x in range(int(x0), int(x1)):
            px = pix.pixel(x, y)
            dark = px[0] < dark_at
            if dark != current:
                if current is not None:
                    runs.append((current, length))
                current = dark
                length = 1
            else:
                length += 1
        if current is not None:
            runs.append((current, length))
        return runs

    line_doc = pymupdf.open()
    line_doc.new_page(width=320, height=180)
    line_bytes = line_doc.tobytes()
    line_doc.close()
    parsed = parse_placements(
        [
            {"kind": "line", "page": 0, "x1": 30, "y1": 40, "x2": 290, "y2": 40, "color": "#141414"},
            {"symbolId": "ucl", "page": 0, "x": 60, "y": 110, "size": 50, "rotation": 0, "color": "#141414"},
        ],
        1,
        ids,
    )
    lined = export_pdf(line_bytes, parsed, by_id)
    lined_doc = pymupdf.open(stream=lined, filetype="pdf")
    lined_pix = lined_doc[0].get_pixmap(dpi=72, alpha=False)
    runs = dash_runs(lined_pix, 50, 270, 40)
    dark_runs = [length for dark, length in runs if dark and length >= 3]
    light_runs = [length for dark, length in runs if not dark and length >= 3]
    check("dashed line has gaps", len(dark_runs) >= 2 and len(light_runs) >= 2, str(runs[:8]))
    check("dashed line stays on its path", dark_pixels(lined_pix, 40, 70, 80, 90) == 0)
    check("line page still stamps UCL", "UCL" in lined_doc[0].get_text())
    lined_doc.close()

    leg_parsed = parse_placements(
        [{"kind": "legend", "page": 0, "x": 12, "y": 12, "width": min(300, layout["width"])}],
        1,
        ids,
    )
    leg_page = pymupdf.open()
    leg_page.new_page(width=720, height=560)
    leg_bytes = leg_page.tobytes()
    leg_page.close()
    leg_pdf = export_pdf(leg_bytes, leg_parsed, by_id)
    leg_view = pymupdf.open(stream=leg_pdf, filetype="pdf")
    leg_text = leg_view[0].get_text()
    check("dropped legend title", "SYMBOL LEGEND" in leg_text)
    check("dropped legend names UCL", "Under cabinet lights" in leg_text)
    check("dropped legend names the bath fan", "Bath exhaust fan" in leg_text)
    check("dropped legend names the pendant", "Pendant" in leg_text)
    leg_view[0].get_pixmap(dpi=110, alpha=False).save("/tmp/planmarks-tools.png")
    leg_view.close()

    spun_line = export_pdf(
        rotated_bytes,
        [
            {
                "kind": "line",
                "page": 0,
                "x1": 30,
                "y1": visual.height / 2,
                "x2": visual.width - 30,
                "y2": visual.height / 2,
                "color": "#141414",
            }
        ],
        by_id,
    )
    spun_line_doc = pymupdf.open(stream=spun_line, filetype="pdf")
    spun_line_pix = spun_line_doc[0].get_pixmap(dpi=72, alpha=False)
    mid_y = int(visual.height / 2)
    spun_runs = dash_runs(spun_line_pix, 40, int(visual.width) - 40, mid_y)
    spun_dark = [length for dark, length in spun_runs if dark and length >= 3]
    spun_light = [length for dark, length in spun_runs if not dark and length >= 3]
    check("rotated sheet: dashed line follows the view", len(spun_dark) >= 2 and len(spun_light) >= 2, str(spun_runs[:8]))
    check("rotated sheet: line misses the corner", dark_pixels(spun_line_pix, 0, 0, 16, 16) == 0)
    spun_line_doc.close()

    def rejected(raw, needle):
        try:
            parse_placements(raw, 1, ids)
        except ValueError as exc:
            return needle in str(exc)
        return False

    check(
        "empty note rejected",
        rejected([{"kind": "note", "page": 0, "x": 10, "y": 10, "text": "  ", "size": 12, "color": "#141414"}], "empty"),
    )
    check(
        "short arrow rejected",
        rejected([{"kind": "arrow", "page": 0, "x1": 10, "y1": 10, "x2": 12, "y2": 10, "color": "#141414"}], "too short"),
    )

    callout = parse_placements(
        [
            {
                "kind": "note",
                "page": 0,
                "x": 36,
                "y": 24,
                "text": "ADD CIRCUIT\nIN GARAGE",
                "size": 14,
                "color": "#141414",
            },
            {"kind": "arrow", "page": 0, "x1": 30, "y1": 90, "x2": 250, "y2": 90, "color": "#141414"},
        ],
        1,
        ids,
    )
    noted = export_pdf(line_bytes, callout, by_id)
    noted_doc = pymupdf.open(stream=noted, filetype="pdf")
    noted_text = noted_doc[0].get_text()
    noted_pix = noted_doc[0].get_pixmap(dpi=72, alpha=False)
    check("note text exports", "ADD CIRCUIT" in noted_text and "IN GARAGE" in noted_text)
    check("note sits near its point", dark_pixels(noted_pix, 30, 20, 180, 70) > 20)
    check("note misses the corner", dark_pixels(noted_pix, 0, 0, 18, 18) == 0)
    arrow_runs = dash_runs(noted_pix, 40, 230, 90)
    arrow_dark = [length for dark, length in arrow_runs if dark and length >= 3]
    arrow_gaps = [length for dark, length in arrow_runs if not dark and length >= 3]
    check("arrow is a solid line", len(arrow_dark) == 1 and arrow_dark[0] > 150, str(arrow_runs[:8]))
    check("arrow is not dashed", len(arrow_gaps) == 0, str(arrow_runs[:8]))
    check("arrow head leaves the shaft", dark_pixels(noted_pix, 236, 93, 242, 96) > 0)
    check("arrow shaft stays thin", dark_pixels(noted_pix, 80, 100, 140, 112) == 0)
    noted_doc.close()

    spun_note = export_pdf(
        rotated_bytes,
        [
            {
                "kind": "note",
                "page": 0,
                "x": 24,
                "y": 40,
                "text": "PANEL",
                "size": 14,
                "color": "#141414",
            },
            {
                "kind": "arrow",
                "page": 0,
                "x1": 30,
                "y1": visual.height / 2,
                "x2": visual.width - 30,
                "y2": visual.height / 2,
                "color": "#141414",
            },
        ],
        by_id,
    )
    spun_note_doc = pymupdf.open(stream=spun_note, filetype="pdf")
    spun_note_pix = spun_note_doc[0].get_pixmap(dpi=72, alpha=False)
    spun_note_text = spun_note_doc[0].get_text()
    check("rotated sheet: note text exports", "PANEL" in spun_note_text)
    check("rotated sheet: note stays at the visual point", dark_pixels(spun_note_pix, 20, 36, 140, 80) > 15)
    check("rotated sheet: note misses the corner", dark_pixels(spun_note_pix, 0, 0, 12, 12) == 0)
    spun_arrow_runs = dash_runs(spun_note_pix, 40, int(visual.width) - 40, mid_y)
    spun_arrow_dark = [length for dark, length in spun_arrow_runs if dark and length >= 3]
    spun_arrow_gaps = [length for dark, length in spun_arrow_runs if not dark and length >= 3]
    check(
        "rotated sheet: arrow follows the view",
        len(spun_arrow_dark) == 1 and spun_arrow_dark[0] > 80,
        str(spun_arrow_runs[:8]),
    )
    check("rotated sheet: arrow is not dashed", len(spun_arrow_gaps) == 0, str(spun_arrow_runs[:8]))
    check("rotated sheet: arrow misses the corner", dark_pixels(spun_note_pix, 0, 0, 16, 16) == 0)
    spun_note_doc.close()

    # Every symbol, plus the sample plan underneath.
    placements = []
    cols = 4
    for index, item in enumerate(lib["symbols"]):
        col, row = index % cols, index // cols
        placements.append(
            {
                "symbolId": item["id"],
                "page": 0,
                "x": 120 + col * 90,
                "y": 150 + row * 100,
                "size": 70,
                "rotation": 25 if item["wall"] else 0,
                "color": item["defaultColor"],
            }
        )
    contact = export_pdf(sample, placements, by_id)
    contact_doc = pymupdf.open(stream=contact, filetype="pdf")
    check("contact keeps plan text", "LIVING" in contact_doc[0].get_text())
    check("contact draws symbol text", "S3" in contact_doc[0].get_text())
    contact_doc[0].get_pixmap(dpi=90, alpha=False).save("/tmp/planmarks-marked.png")
    # Symbol parade on a blank sheet for inspection.
    parade_doc = pymupdf.open()
    parade_rows = (len(lib["symbols"]) + cols - 1) // cols
    parade_doc.new_page(width=720, height=160 + parade_rows * 100)
    parade_bytes = parade_doc.tobytes()
    parade_doc.close()
    parade = export_pdf(parade_bytes, placements, by_id)
    parade_view = pymupdf.open(stream=parade, filetype="pdf")
    parade_view[0].get_pixmap(dpi=110, alpha=False).save("/tmp/planmarks-symbols.png")
    parade_view.close()
    contact_doc.close()

    print("server")
    app = App()
    httpd = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    base = f"http://{host}:{port}"

    status, _headers, body = request(base, "/")
    check("home page", status == 200 and b"Plan Marks" in body, str(status))
    status, _headers, body = request(base, "/static/app.js")
    check("script", status == 200 and b"function placeAt" in body)
    status, _headers, body = request(base, "/api/symbols")
    payload = json.loads(body)
    check("symbols api", status == 200 and len(payload["symbols"]) >= 12)

    status, _headers, body = request(base, "/api/open?name=sample-plan.pdf", data=sample, method="POST")
    info = json.loads(body)
    check("open pdf", status == 200 and info["pageCount"] == 2, body[:200])
    status, _headers, png = request(base, "/api/page/0.png?dpi=72")
    check("render png", status == 200 and png.startswith(b"\x89PNG"), str(status))

    status, _headers, body = request(base, "/api/open?name=bad.pdf", data=b"not a pdf", method="POST")
    check("reject junk", status == 400, body[:160])

    # Re-open the sample, then append a one-page PDF and export.
    status, _headers, _body = request(base, "/api/open?name=First%20Floor.pdf", data=sample, method="POST")
    one = pymupdf.open()
    one.new_page(width=200, height=200)
    one_bytes = one.tobytes()
    one.close()
    status, _headers, body = request(base, "/api/append", data=one_bytes, method="POST")
    added = json.loads(body)
    check("append sheet", status == 200 and added["pageCount"] == 3, body[:200])

    export_body = json.dumps(
        {
            "placements": [
                {"symbolId": "duplex", "page": 0, "x": 200, "y": 220, "size": 36, "rotation": 15, "color": "#141414"},
                {"symbolId": "gfci", "page": 0, "x": 260, "y": 220, "size": 36, "rotation": 0, "color": "#141414"},
                {"symbolId": "switch", "page": 0, "x": 320, "y": 180, "size": 32, "rotation": -20, "color": "#141414"},
                {"symbolId": "ceiling", "page": 0, "x": 220, "y": 300, "size": 40, "rotation": 0, "color": "#141414"},
                {"symbolId": "smoke", "page": 0, "x": 400, "y": 160, "size": 36, "rotation": 0, "color": "#9f1d1d"},
                {"symbolId": "panel", "page": 1, "x": 180, "y": 200, "size": 48, "rotation": 90, "color": "#141414"},
                {"kind": "line", "page": 0, "x1": 220, "y1": 300, "x2": 400, "y2": 160, "color": "#141414"},
                {"kind": "legend", "page": 1, "x": 24, "y": 24, "width": 280},
            ]
        }
    ).encode()
    status, headers, pdf = request(
        base,
        "/api/export",
        data=export_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    check("export status", status == 200 and pdf.startswith(b"%PDF"), str(status))
    check("export filename", "marked" in headers.get("Content-Disposition", "").lower())
    exported = pymupdf.open(stream=pdf, filetype="pdf")
    check("export page count", exported.page_count == 3)
    check("export keeps room name", "LIVING" in exported[0].get_text() or "KITCHEN" in exported[0].get_text())
    check("export stamps a dropped legend", "SYMBOL LEGEND" in exported[1].get_text())
    status, _headers, body = request(base, "/api/legend", method="POST")
    legend_info = json.loads(body)
    check("legend sheet", status == 200 and legend_info["pageCount"] == 4, body[:200])
    legend_pdf = build_legend_pdf(lib["symbols"], 792, 612)
    legend_doc = pymupdf.open(stream=legend_pdf, filetype="pdf")
    legend_text = legend_doc[0].get_text()
    check("legend title", "SYMBOL LEGEND" in legend_text)
    check("legend lists 30A outlet", "30A 240V outlet" in legend_text)
    check("legend lists smurf chase", "Smurf chase" in legend_text)
    check("legend lists under cabinet lights", "Under cabinet lights" in legend_text)
    block_pdf, _block_w, _block_h = build_legend_block(lib["symbols"])
    block_doc = pymupdf.open(stream=block_pdf, filetype="pdf")
    block_text = block_doc[0].get_text()
    check("legend block is one page", block_doc.page_count == 1)
    check("legend block lists the pendant", "Pendant" in block_text and "Bath exhaust fan" in block_text)
    block_doc.close()
    legend_doc[0].get_pixmap(dpi=80, alpha=False).save("/tmp/planmarks-legend.png")
    legend_doc.close()
    exported[0].get_pixmap(dpi=80, alpha=False).save("/tmp/planmarks-export.png")
    exported.close()

    bad = json.dumps({"placements": [{"symbolId": "nope", "page": 0, "x": 1, "y": 1, "size": 20}]}).encode()
    status, _headers, body = request(
        base,
        "/api/export",
        data=bad,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    check("unknown symbol rejected", status == 400, body[:160])

    status, _headers, body = request(base, "/api/sample.pdf")
    check("sample endpoint", status == 200 and body.startswith(b"%PDF"))

    httpd.shutdown()
    print()
    print(f"{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
