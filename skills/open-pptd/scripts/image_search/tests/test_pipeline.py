"""Bounded image resolution: no public network or model credentials needed."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import search_images
import pool

FAKE_WORKER = r'''
import json, pathlib, struct, sys, time
request, output = map(pathlib.Path, sys.argv[1:])
r = json.loads(request.read_text())
backend = r['backend']
if r['query'] == 'hang':
    time.sleep(30)
if r['query'] == 'exception':
    raise RuntimeError('one slot failed')
if backend == 'baidu':
    output.write_text(json.dumps({'winner': None, 'tried': [{'backend': backend, 'fate': 'fetch_fail'}]}))
else:
    data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + struct.pack('>II', 1000, 600) + b'\x00' * 100
    output.with_suffix('.bin').write_bytes(data)
    output.write_text(json.dumps({'winner': {'url': 'https://example.invalid/local-fixture', 'backend': backend,
        'w': 1000, 'h': 600, 'fmt': 'png', 'score': 1, 'license': '', 'vlm': {}}, 'tried': []}))
'''


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'pages').mkdir()
        (self.root / 'deck.pptd').write_text('title: Test\npages:\n  - pages/01.page\n')
        self.worker = self.root / 'fake_worker.py'
        self.worker.write_text(FAKE_WORKER)

    def page(self, query='test', annotation=''):
        (self.root / 'pages/01.page').write_text(
            'pageType: content\nelements:\n  - elementId: photo\n    elementType: image\n'
            f'    bounds: [0, 0, 960, 540]\n    src: "search:{query}" {annotation}\n')

    def run_pipeline(self, **kwargs):
        # These fixtures exercise pipeline mechanics; queries are ASCII sentinels, not real ones.
        kwargs.setdefault('allow_latin_query', True)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(search_images, 'WORKER', self.worker, create=True), \
             contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = search_images.run(str(self.root), **kwargs)
        report = json.loads((self.root / 'images_report.json').read_text())
        return code, report, stderr.getvalue(), stdout.getvalue()

    def test_candidate_failure_cascades_with_diagnostics(self):
        self.page()
        code, report, progress, _ = self.run_pipeline(timeout=1, budget=3)
        self.assertEqual(code, 0)
        self.assertEqual(report['slots'][0]['backend'], 'openverse')
        self.assertTrue(any(r['fate'] == 'fetch_fail' for r in report['slots'][0]['tried']))
        self.assertIn('[try]', progress)
        self.assertIn('media/', (self.root / 'pages/01.page').read_text())

    def test_backend_timeout_cascades_and_overall_budget_terminates(self):
        self.page('hang')
        start = time.monotonic()
        code, report, progress, _ = self.run_pipeline(timeout=.2, budget=.55)
        self.assertLess(time.monotonic() - start, 2.55)
        self.assertEqual(code, 2)
        self.assertEqual(report['failed'], 1)
        self.assertGreaterEqual(len(report['slots'][0]['tried']), 2)
        self.assertIn('openverse', progress)
        self.assertTrue(any(r['fate'] in ('timeout', 'budget_exhausted') for r in report['slots'][0]['tried']))

    def test_offline_only_explicit_decorative_fallback(self):
        self.page(annotation='# pptd-image: decorative fallback=gradient')
        with patch.object(pool, '_req', side_effect=AssertionError('network forbidden')), \
             patch.object(pool, 'call_vlm', side_effect=AssertionError('VLM forbidden')):
            code, report, _, _ = self.run_pipeline(offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(report['slots'][0]['status'], 'degraded')
        self.assertEqual(report['slots'][0]['backend'], 'local-gradient')
        local = self.root / report['slots'][0]['local']
        self.assertEqual(pool.sniff_size(local.read_bytes())[2], 'png')
        self.page('required product')
        code, report, _, _ = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['slots'][0]['status'], 'failed')
        self.assertIn('search:required product', (self.root / 'pages/01.page').read_text())

    def test_worker_exception_is_reported_not_lost(self):
        self.page('exception')
        code, report, _, _ = self.run_pipeline(timeout=1, budget=2)
        self.assertEqual(code, 2)
        self.assertTrue(report['slots'][0]['tried'])
        self.assertEqual(report['slots'][0]['tried'][0]['fate'], 'worker_error')

    def test_default_vlm_is_off_even_with_key(self):
        self.page(annotation='# pptd-image: decorative fallback=gradient')
        with patch.dict('os.environ', {'PPT_API_KEY': 'test-not-a-secret'}):
            code, report, _, _ = self.run_pipeline(offline=True)
        self.assertEqual(code, 0)
        self.assertFalse(report['vlm'])

    def test_progress_arrives_before_completion_and_has_heartbeat(self):
        self.page('hang')
        runner = self.root / 'runner.py'
        runner.write_text(f'import sys\nsys.path.insert(0, {str(Path(search_images.__file__).parent)!r})\n'
                          f'import search_images\nsearch_images.WORKER = {str(self.worker)!r}\n'
                          f'raise SystemExit(search_images.run({str(self.root)!r}, timeout=8, budget=5.5, allow_latin_query=True))\n')
        start = time.monotonic()
        proc = subprocess.Popen([sys.executable, '-u', str(runner)], stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            first = proc.stderr.readline()
            self.assertIn('[scan]', first)
            self.assertLess(time.monotonic() - start, 2)
            _, rest = proc.communicate(timeout=8)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('[wait]', rest)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()


if __name__ == '__main__':
    unittest.main()
