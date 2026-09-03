#!/usr/bin/env python3
"""Shared localhost HTTP server for serving viewer.html + PPTD deck files.

Both export_html.py and export_images.py need to serve the viewer and the
deck from a single HTTP origin — ``file://`` protocol blocks the viewer's
subresource fetches for decks with many pages or media.

Usage (as a library):

    from deck_server import start_deck_server

    server, port = start_deck_server(viewer_path, deck_dir)
    try:
        url = f"http://127.0.0.1:{port}/viewer?deck=http://127.0.0.1:{port}/deck/{deck_name}"
        ...
    finally:
        server.shutdown()
        server.server_close()
"""

from __future__ import annotations

import http.server
import mimetypes
import threading
from pathlib import Path
from typing import Tuple


class _DeckHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves /viewer → viewer.html, /deck/<path> → deck project files."""

    viewer_path: Path = Path()  # set by start_deck_server
    deck_dir: Path = Path()     # set by start_deck_server

    def do_GET(self) -> None:  # noqa: N802
        url_path = self.path.split("?")[0].split("#")[0]
        if url_path in ("/viewer", "/viewer.html", "/"):
            self._send_file(self.viewer_path, "text/html; charset=utf-8")
        elif url_path.startswith("/deck/"):
            rel = url_path[len("/deck/"):]
            # Prevent directory traversal
            resolved = (self.deck_dir / rel).resolve()
            if not str(resolved).startswith(str(self.deck_dir.resolve())):
                self.send_error(403)
                return
            self._send_file(resolved)
        else:
            self.send_error(404)

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB — 防止大文件耗尽内存

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        if size > self.MAX_FILE_SIZE:
            self.send_error(413)
            return
        if content_type is None:
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # silent


def start_deck_server(viewer: Path, deck_dir: Path) -> Tuple[http.server.HTTPServer, int]:
    """Start a localhost HTTP server. Returns (server, port).

    The caller must call ``server.shutdown()`` + ``server.server_close()``
    when done.
    """
    handler_cls = type(
        "DeckHandler",
        (_DeckHTTPHandler,),
        {"viewer_path": viewer, "deck_dir": deck_dir},
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port
