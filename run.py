#!/usr/bin/env python3
"""Start Plan Marks and open it in a browser.

On Windows, the packaged program opens a small window. Leave that window
open while you work, and close it to quit. From a terminal, this stays a
normal local server you stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import multiprocessing
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

from elecplan.server import App, make_server  # noqa: E402


class _Silent:
    """Windowed builds have no console, and the server logs every request."""

    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = _Silent()
    if sys.stderr is None:
        sys.stderr = _Silent()


def _self_check() -> None:
    """Prove the packaged program can see its files and open a PDF."""
    import pymupdf

    from elecplan.library import load_symbols, project_root

    symbols = load_symbols()
    ids = {item["id"] for item in symbols["symbols"]}
    if "duplex" not in ids or "panel" not in ids:
        raise RuntimeError("symbol catalog did not load")
    page = project_root() / "elecplan" / "static" / "index.html"
    if not page.is_file():
        raise RuntimeError(f"missing {page}")
    doc = pymupdf.open()
    doc.new_page(width=100, height=100)
    if doc.page_count != 1:
        raise RuntimeError("pymupdf could not build a page")
    print("planmarks-ok")


def _windows_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return


def _report_startup_error(exc: BaseException) -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Plan Marks", f"Plan Marks could not start.\n\n{exc}")
        root.destroy()
    except Exception:
        return


def run_desktop(httpd, url: str, open_browser: bool) -> None:
    """Small window so the program can be quit without a terminal."""
    import tkinter as tk

    _windows_dpi()
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="planmarks-http", daemon=True)
    thread.start()

    root = tk.Tk()
    root.title("Plan Marks")
    root.configure(bg="#181b21")
    root.resizable(False, False)
    width, height = 440, 230
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")

    title = tk.Label(
        root,
        text="Plan Marks",
        bg="#181b21",
        fg="#e8eaef",
        font=("Segoe UI", 18, "bold"),
    )
    title.pack(pady=(22, 4))
    detail = tk.Label(
        root,
        text="Running on this computer. Your plans stay here.",
        bg="#181b21",
        fg="#a3aab6",
        font=("Segoe UI", 10),
    )
    detail.pack()
    address = tk.Label(
        root,
        text=url,
        bg="#181b21",
        fg="#e2a23a",
        font=("Segoe UI", 10),
    )
    address.pack(pady=(8, 14))

    buttons = tk.Frame(root, bg="#181b21")
    buttons.pack()
    tk.Button(
        buttons,
        text="Open Plan Marks",
        command=lambda: webbrowser.open(url),
        bg="#e2a23a",
        fg="#2a1c06",
        activebackground="#efb14e",
        activeforeground="#2a1c06",
        relief="flat",
        padx=14,
        pady=6,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    ).pack(side="left", padx=6)
    closing = {"done": False}

    def quit_app() -> None:
        if closing["done"]:
            return
        closing["done"] = True
        httpd.shutdown()
        root.destroy()

    tk.Button(
        buttons,
        text="Quit",
        command=quit_app,
        bg="#22262f",
        fg="#e8eaef",
        activebackground="#313743",
        activeforeground="#e8eaef",
        relief="flat",
        padx=14,
        pady=6,
        font=("Segoe UI", 10),
        cursor="hand2",
    ).pack(side="left", padx=6)
    hint = tk.Label(
        root,
        text="Leave this window open while you work.",
        bg="#181b21",
        fg="#767e8c",
        font=("Segoe UI", 9),
    )
    hint.pack(pady=(16, 0))
    root.protocol("WM_DELETE_WINDOW", quit_app)
    if open_browser:
        root.after(400, lambda: webbrowser.open(url))
    root.mainloop()
    if not closing["done"]:
        httpd.shutdown()
    thread.join(timeout=3)
    httpd.server_close()


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(
        description="Plan Marks — place electrical symbols on a floor-plan PDF. Everything stays on this computer."
    )
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return

    app = App()
    httpd = make_server(app, args.host, args.port)
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}/"
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        run_desktop(httpd, url, open_browser=not args.no_browser)
        return

    print("Plan Marks")
    print(f"  {url}")
    print("  Local only. PDFs stay on this computer.")
    print("  Press Ctrl+C to stop.")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("  This host is reachable from other machines on the network.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    _ensure_stdio()
    try:
        main()
    except Exception as exc:
        if "--self-check" in sys.argv:
            print(exc, file=sys.stderr)
            sys.exit(1)
        if getattr(sys, "frozen", False):
            _report_startup_error(exc)
            sys.exit(1)
        raise
