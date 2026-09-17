"""Serve docs/ for local browser testing, without caching.

`python -m http.server` sends no cache headers, so browsers heuristically cache
ES modules -- you edit a file, reload, and keep testing the previous build.
That is a slow way to lose an afternoon, so this sends no-store.

    python tools/serve_docs.py [port]

The published site on Pages is a separate thing and caches normally; this is
only for driving the page locally, where `ws://` also still works (the HTTPS
site can only reach `wss://`).
"""

from __future__ import annotations

import http.server
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "docs"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter; the interesting output is the game
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8137
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), NoCacheHandler) as httpd:
        print(f"serving {ROOT} at http://127.0.0.1:{port} (no-store)")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
