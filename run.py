#!/usr/bin/env python3
"""Start Plan Marks and open it in a browser."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from elecplan.server import App, make_server  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan Marks — place electrical symbols on a floor-plan PDF. Everything stays on this computer."
    )
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args()

    app = App()
    httpd = make_server(app, args.host, args.port)
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}/"
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
    main()
