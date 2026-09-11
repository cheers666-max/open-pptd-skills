"""The remote rasteriser, exercised against a stub so the contract is testable off the network."""

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import render_service  # noqa: E402

PNG = (b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
       + (960).to_bytes(4, 'big') + (540).to_bytes(4, 'big') + b'\x08\x02\x00\x00\x00' + b'0' * 64)


class Stub(BaseHTTPRequestHandler):
    requests = []
    errno = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Stub.requests.append(body)
        if Stub.errno:
            payload = {"errno": Stub.errno, "errmsg": "boom"}
        else:
            payload = {"errno": 0, "errmsg": "success",
                       "data": {"s3url": f"http://{self.headers['Host']}/img.png",
                                "size": [960, 540, 960, 540]}}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *_args):
        pass


class RenderServiceTests(unittest.TestCase):
    def setUp(self):
        Stub.requests = []
        Stub.errno = 0
        self.server = HTTPServer(('127.0.0.1', 0), Stub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/api/v1/convert'
        self.addCleanup(self.server.shutdown)

    def deck(self, folder, pages=3):
        html_dir = Path(folder) / 'html'
        html_dir.mkdir()
        for index in range(1, pages + 1):
            (html_dir / f'page_{index:02d}.html').write_text(
                f'<div class="slide">page {index}</div>', encoding='utf-8')
        (html_dir / 'index.html').write_text('<div class="slide">all</div>', encoding='utf-8')
        return html_dir

    def test_every_page_is_sent_with_the_capture_selector(self):
        with tempfile.TemporaryDirectory() as folder:
            html_dir = self.deck(folder)
            out = Path(folder) / 'pages'
            rendered = render_service.capture_pages(html_dir, out, endpoint=self.endpoint, workers=2)
            self.assertEqual(len(rendered), 3, 'index.html is not a page')
            self.assertEqual(sorted(p.name for p in out.glob('*.png')),
                             ['page_01.png', 'page_02.png', 'page_03.png'])
            self.assertTrue(all(r['options']['captureSelector'] == '.slide'
                                for r in Stub.requests))
            self.assertTrue(all(r['type'] == 'html2png' for r in Stub.requests))

    def test_a_service_error_is_raised_rather_than_written_as_a_png(self):
        Stub.errno = 500
        with tempfile.TemporaryDirectory() as folder:
            html_dir = self.deck(folder, pages=1)
            out = Path(folder) / 'pages'
            with self.assertRaises(render_service.RenderServiceError):
                render_service.capture_pages(html_dir, out, endpoint=self.endpoint, workers=1)
            self.assertEqual(list(out.glob('*.png')), [])

    def test_a_folder_without_pages_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder) / 'html'
            empty.mkdir()
            with self.assertRaises(render_service.RenderServiceError):
                render_service.capture_pages(empty, Path(folder) / 'out', endpoint=self.endpoint)

    def test_the_endpoint_can_come_from_the_environment(self):
        import os
        os.environ[render_service.ENDPOINT_ENV] = self.endpoint
        self.addCleanup(os.environ.pop, render_service.ENDPOINT_ENV, None)
        self.assertEqual(render_service.endpoint_from(), self.endpoint)
        with self.assertRaises(render_service.RenderServiceError):
            os.environ.pop(render_service.ENDPOINT_ENV)
            render_service.endpoint_from()


if __name__ == '__main__':
    unittest.main()
