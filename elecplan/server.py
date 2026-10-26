"""Local HTTP server. PDFs stay in this process; nothing is uploaded."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import pymupdf

from elecplan.export import export_pdf, parse_placements
from elecplan.legend import build_legend_pdf, legend_layout
from elecplan.library import load_symbols
from elecplan.sample_plan import build_sample_pdf

STATIC = Path(__file__).resolve().parent / "static"
MAX_PDF_BYTES = 80 * 1024 * 1024
_PAGE_PATH = re.compile(r"/api/page/(\d+)\.png")
_FITZ = threading.Lock()

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


def _clamp_dpi(page, dpi: float) -> int:
    # PyMuPDF 2 requires an integer resolution.
    dpi = min(max(float(dpi), 36), 160)
    long_pt = max(page.rect.width, page.rect.height)
    if long_pt * dpi / 72 > 5000:
        dpi = 5000 * 72 / long_pt
    return int(round(dpi))


def _safe_name(name: str) -> str:
    name = (name or "plan.pdf").replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "").strip() or "plan.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


def _marked_name(filename: str) -> str:
    base = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return f"{base}-marked.pdf"


def _content_disposition(filename: str) -> str:
    ascii_name = "".join(ch if 32 < ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class Session:
    def __init__(self):
        self.data: bytes | None = None
        self.doc: pymupdf.Document | None = None
        self.filename = ""
        self.doc_id = ""
        self.cache: OrderedDict = OrderedDict()

    def info(self) -> dict:
        if self.doc is None:
            raise ValueError("No PDF is open")
        pages = []
        with _FITZ:
            for index, page in enumerate(self.doc):
                rect = page.rect
                label = (page.get_label() or "").strip() or str(index + 1)
                pages.append(
                    {
                        "index": index,
                        "width": rect.width,
                        "height": rect.height,
                        "rotation": int(page.rotation),
                        "label": label,
                    }
                )
        return {
            "id": self.doc_id,
            "filename": self.filename,
            "pageCount": len(pages),
            "pages": pages,
        }

    def _remember(self, doc: pymupdf.Document, data: bytes, filename: str) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = doc
        self.data = data
        self.filename = filename
        self.doc_id = hashlib.sha256(data).hexdigest()[:16]
        self.cache.clear()

    def open_pdf(self, data: bytes, filename: str) -> dict:
        if not data:
            raise ValueError("That file is empty")
        if len(data) > MAX_PDF_BYTES:
            raise ValueError("That PDF is larger than 80 MB")
        with _FITZ:
            try:
                doc = pymupdf.open(stream=data, filetype="pdf")
            except Exception as exc:
                raise ValueError("Could not open that file as a PDF") from exc
            if doc.needs_pass and not doc.authenticate(""):
                doc.close()
                raise ValueError("This PDF is password-protected. Remove the password and try again.")
            if doc.page_count < 1:
                doc.close()
                raise ValueError("This PDF has no pages")
            self._remember(doc, data, _safe_name(filename))
        return self.info()

    def append_pdf(self, data: bytes) -> dict:
        if self.doc is None or self.data is None:
            raise ValueError("Open a PDF before adding sheets")
        if not data:
            raise ValueError("That file is empty")
        if len(data) > MAX_PDF_BYTES:
            raise ValueError("That PDF is larger than 80 MB")
        with _FITZ:
            try:
                other = pymupdf.open(stream=data, filetype="pdf")
            except Exception as exc:
                raise ValueError("Could not open that file as a PDF") from exc
            try:
                if other.needs_pass and not other.authenticate(""):
                    raise ValueError("That PDF is password-protected. Remove the password and try again.")
                if other.page_count < 1:
                    raise ValueError("That PDF has no pages")
                added = other.page_count
                self.doc.insert_pdf(other)
                self.data = self.doc.tobytes(deflate=True, garbage=3)
                self.doc_id = hashlib.sha256(self.data).hexdigest()[:16]
                self.cache.clear()
            finally:
                other.close()
        payload = self.info()
        payload["added"] = added
        return payload

    def append_legend(self, symbols) -> dict:
        if self.doc is None or self.data is None:
            raise ValueError("Open a PDF before adding a legend")
        with _FITZ:
            rect = self.doc[0].rect
            legend = build_legend_pdf(symbols, rect.width, rect.height)
            other = pymupdf.open(stream=legend, filetype="pdf")
            try:
                added = other.page_count
                self.doc.insert_pdf(other)
                self.data = self.doc.tobytes(deflate=True, garbage=3)
                self.doc_id = hashlib.sha256(self.data).hexdigest()[:16]
                self.cache.clear()
            finally:
                other.close()
        payload = self.info()
        payload["added"] = added
        return payload

    def render_page(self, index: int, dpi: float) -> bytes:
        with _FITZ:
            if self.doc is None:
                raise ValueError("No PDF is open")
            if index < 0 or index >= self.doc.page_count:
                raise ValueError("Page out of range")
            page = self.doc[index]
            dpi = _clamp_dpi(page, dpi)
            key = (self.doc_id, index, dpi)
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                return cached
            pix = page.get_pixmap(dpi=dpi, alpha=False, annots=True)
            data = pix.tobytes("png")
            self.cache[key] = data
            self.cache.move_to_end(key)
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
            return data

    def export(self, placements, symbols_by_id) -> tuple[bytes, str]:
        if self.data is None or self.doc is None:
            raise ValueError("No PDF is open")
        parsed = parse_placements(placements, self.doc.page_count, set(symbols_by_id))
        with _FITZ:
            pdf = export_pdf(self.data, parsed, symbols_by_id)
        return pdf, _marked_name(self.filename)


class App:
    def __init__(self):
        self.session = Session()
        library = load_symbols()
        self.library = library
        self.symbols_by_id = {item["id"]: item for item in library["symbols"]}
        self.legend = legend_layout(library["symbols"])
        self.sample_pdf: bytes | None = None

    def public_symbols(self) -> dict:
        categories = self.library["categories"]
        symbols = []
        for item in self.library["symbols"]:
            symbols.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "category": item["category"],
                    "wall": item["wall"],
                    "keywords": item["keywords"],
                    "hint": item["hint"],
                    "defaultColor": item["defaultColor"],
                    "svg": item["svg"],
                }
            )
        return {"categories": categories, "symbols": symbols, "legend": self.legend}

    def sample(self) -> bytes:
        if self.sample_pdf is None:
            with _FITZ:
                self.sample_pdf = build_sample_pdf()
        return self.sample_pdf


def _make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            try:
                code = int(args[1])
            except (IndexError, TypeError, ValueError):
                code = 0
            if code >= 400:
                super().log_message(fmt, *args)

        def do_GET(self):
            try:
                self._get()
            except Exception as exc:
                traceback.print_exc()
                self._json(500, {"error": str(exc) or "Something went wrong"})

        def do_POST(self):
            try:
                self._post()
            except Exception as exc:
                traceback.print_exc()
                self._json(500, {"error": str(exc) or "Something went wrong"})

        def _get(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == "/":
                self._file(STATIC / "index.html")
                return
            if path == "/api/symbols":
                self._json(200, app.public_symbols())
                return
            if path == "/api/document":
                try:
                    self._json(200, app.session.info())
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path == "/api/sample.pdf":
                data = app.sample()
                self._bytes(200, data, "application/pdf", _content_disposition("sample-plan.pdf"))
                return
            match = _PAGE_PATH.fullmatch(path)
            if match:
                try:
                    dpi = float(query.get("dpi", ["110"])[0])
                except ValueError:
                    dpi = 110
                try:
                    png = app.session.render_page(int(match.group(1)), dpi)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._bytes(200, png, "image/png")
                return
            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                if not rel or ".." in rel.split("/"):
                    self._json(404, {"error": "Not found"})
                    return
                self._file(STATIC / rel)
                return
            self._json(404, {"error": "Not found"})

        def _post(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length < 0 or length > MAX_PDF_BYTES + 2_000_000:
                self._json(413, {"error": "Upload is too large"})
                return
            body = self.rfile.read(length) if length else b""
            if path == "/api/open":
                name = query.get("name", ["plan.pdf"])[0]
                try:
                    info = app.session.open_pdf(body, name)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                print(f"opened {info['filename']} ({info['pageCount']} sheets)")
                self._json(200, info)
                return
            if path == "/api/append":
                try:
                    info = app.session.append_pdf(body)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                print(f"appended {info.get('added', 0)} sheets")
                self._json(200, info)
                return
            if path == "/api/legend":
                try:
                    info = app.session.append_legend(app.library["symbols"])
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                print(f"added legend ({info.get('added', 0)} sheets)")
                self._json(200, info)
                return
            if path == "/api/export":
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    pdf, name = app.session.export(payload.get("placements", []), app.symbols_by_id)
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                count = len(payload.get("placements") or [])
                print(f"exported {name} with {count} symbols")
                self._bytes(200, pdf, "application/pdf", _content_disposition(name))
                return
            self._json(404, {"error": "Not found"})

        def _json(self, status: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self._bytes(status, data, "application/json; charset=utf-8")

        def _file(self, path: Path):
            root = STATIC.resolve()
            try:
                full = path.resolve()
            except OSError:
                self._json(404, {"error": "Not found"})
                return
            if full != root and root not in full.parents:
                self._json(404, {"error": "Not found"})
                return
            if not full.is_file():
                self._json(404, {"error": "Not found"})
                return
            data = full.read_bytes()
            kind = _TYPES.get(full.suffix.lower(), "application/octet-stream")
            self._bytes(200, data, kind)

        def _bytes(self, status: int, data: bytes, content_type: str, disposition: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if disposition:
                self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(data)

    return Handler


def make_server(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = _make_handler(app)
    ThreadingHTTPServer.allow_reuse_address = True
    last_error = None
    for candidate in range(port, port + 10):
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f"No free port from {port} to {port + 9}") from last_error
