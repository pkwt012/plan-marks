"""Load electrical symbols and bake rotation and ink color into SVG."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

INK = "#141414"


def project_root() -> Path:
    """Folder that contains elecplan/ and symbols/.

    A Windows build unpacks those beside the program. Running from source
    uses the repository folder.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


ROOT = project_root()
SYMBOL_DIR = ROOT / "symbols"

_UNSAFE = ("<script", "<foreignobject", "javascript:", "<iframe", "<embed", "onload=", "onclick=")
_VIEWBOX = re.compile(r"""viewBox\s*=\s*["']0 0 100 100["']""")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SVG_OPEN = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)


def prepare_svg(svg: str, rotation: float, color: str) -> str:
    """Return SVG with the whole symbol turned and ink recolored.

    Rotation is around the viewBox center, so letters turn with the drawing.
    Ink is the literal color #141414 in the source files; white knockout
    shapes are left alone.
    """
    if not _HEX.fullmatch(color or ""):
        raise ValueError(f"bad color {color!r}")
    color = color.lower()
    out = svg.replace(INK, color)
    rot = float(rotation) % 360
    if rot < 0.05 or rot > 359.95:
        return out
    opened = _SVG_OPEN.search(out)
    close = out.rfind("</svg>")
    if not opened or close < opened.end():
        return out
    inner = out[opened.end():close]
    wrapped = f'<g class="spin" transform="rotate({rot:.2f} 50 50)">{inner}</g>'
    return out[: opened.end()] + wrapped + out[close:]


def _check_svg(svg: str, name: str) -> None:
    lowered = svg.lower()
    for bad in _UNSAFE:
        if bad in lowered:
            raise ValueError(f"{name} contains disallowed SVG content ({bad})")
    if not _VIEWBOX.search(svg):
        raise ValueError(f'{name} must use viewBox="0 0 100 100"')


def load_symbols(folder: Path | None = None) -> dict:
    """Read catalog.json plus any extra *.svg files dropped in the folder.

    An extra file is appended under Custom using its filename as the name.
    """
    folder = (folder or SYMBOL_DIR).resolve()
    catalog_path = folder / "catalog.json"
    if not catalog_path.is_file():
        raise FileNotFoundError(f"missing symbol catalog: {catalog_path}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    categories = list(catalog.get("categories") or [])
    entries = list(catalog.get("symbols") or [])
    known_files = set()
    by_id: dict[str, dict] = {}

    def adopt(entry: dict) -> None:
        sid = str(entry["id"]).strip()
        filename = str(entry["file"])
        if sid in by_id:
            raise ValueError(f"duplicate symbol id {sid}")
        if "/" in filename or "\\" in filename or not filename.endswith(".svg"):
            raise ValueError(f"bad symbol file name: {filename}")
        path = (folder / filename).resolve()
        if path.parent != folder:
            raise ValueError(f"symbol file escapes the library: {filename}")
        if not path.is_file():
            raise ValueError(f"missing symbol file: {filename}")
        svg = path.read_text(encoding="utf-8")
        _check_svg(svg, filename)
        color = entry.get("defaultColor") or INK
        if not _HEX.fullmatch(color):
            raise ValueError(f"{sid} has a bad defaultColor")
        known_files.add(filename)
        by_id[sid] = {
            "id": sid,
            "name": entry.get("name") or sid,
            "category": entry.get("category") or "custom",
            "file": filename,
            "wall": bool(entry.get("wall", False)),
            "keywords": entry.get("keywords") or "",
            "hint": entry.get("hint") or "",
            "defaultColor": color.lower(),
            "svg": svg,
        }

    for entry in entries:
        adopt(entry)

    extras = []
    for path in sorted(folder.glob("*.svg")):
        if path.name in known_files:
            continue
        sid = re.sub(r"[^a-z0-9_-]+", "-", path.stem.lower()).strip("-") or "symbol"
        base = sid
        n = 2
        while sid in by_id:
            sid = f"{base}-{n}"
            n += 1
        extras.append(
            {
                "id": sid,
                "name": path.stem.replace("_", " ").replace("-", " ").title(),
                "category": "custom",
                "file": path.name,
                "wall": False,
                "keywords": "",
                "hint": "Custom symbol.",
                "defaultColor": INK,
            }
        )
    if extras:
        if not any(c.get("id") == "custom" for c in categories):
            categories.append({"id": "custom", "name": "Custom"})
        for entry in extras:
            adopt(entry)

    symbols = list(by_id.values())
    return {"categories": categories, "symbols": symbols}
