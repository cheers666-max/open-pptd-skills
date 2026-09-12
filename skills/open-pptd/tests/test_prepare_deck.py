import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import prepare_deck as prepare
except ImportError:
    prepare = None


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(prepare, 'The stable check/export entry point is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'pages').mkdir()
        (self.root / 'media').mkdir()
        Image.new('RGB', (960, 540), 'red').save(self.root / 'media/a.png')
        self.manifest = dict(version='v2', title='Incremental', size=[960, 540],
                             pages=['pages/01.page', 'pages/02.page'])
        self.page = dict(elements=[dict(elementType='text', elementId='title',
                          bounds=[40, 40, 500, 60], content=dict(text='Current title', fontSize=24))])
        self.save(self.root / 'deck.pptd', self.manifest)
        self.save(self.root / 'pages/01.page', self.page)
        self.save(self.root / 'pages/02.page', self.page)
        self.calls = []

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value))

    def render(self, deck, output, scale, virtual_time_ms, timeout, force, workers, page_spec=None,
               endpoint=None):
        indices = [int(v) for v in page_spec.split(',')]
        self.calls.append(indices)
        (output / 'pages').mkdir(parents=True, exist_ok=True)
        for i in indices:
            Image.new('RGB', (960, 540), (30 + i, 100, 120)).save(output / f'pages/page_{i:02d}.png')
        return {'renderHealth': [dict(ok=True, pageNumber=i, errors=[]) for i in indices]}

    def run_check(self, **kwargs):
        with patch.object(prepare, 'export_images', side_effect=self.render), \
                patch.object(prepare, 'audit_page', return_value=[]):
            return prepare.run(str(self.root), **kwargs)

    def test_second_check_reuses_unchanged_pages_and_still_returns_full_overview(self):
        first = self.run_check()
        second = self.run_check()
        self.assertTrue(first['ok'])
        self.assertEqual(self.calls, [[1, 2]])
        self.assertEqual(second['renderedPages'], [])
        self.assertEqual(second['reusedPages'], [1, 2])
        self.assertEqual(len(second['images']), 2)
        self.assertTrue(Path(second['overview']).is_file())
        self.assertEqual(second['visualReview'], 'required')
        self.assertNotIn('scores', second)

    def test_content_change_rerenders_only_affected_page(self):
        self.run_check()
        changed = copy.deepcopy(self.page)
        changed['elements'][0]['content']['text'] = 'Changed title'
        self.save(self.root / 'pages/02.page', changed)
        report = self.run_check()
        self.assertEqual(report['renderedPages'], [2])
        self.assertEqual(report['reusedPages'], [1])

    def test_image_bytes_change_invalidates_its_page(self):
        page = copy.deepcopy(self.page)
        page['background'] = dict(type='image', src='media/a.png')
        self.save(self.root / 'pages/01.page', page)
        self.run_check()
        Image.new('RGB', (960, 540), 'blue').save(self.root / 'media/a.png')
        self.assertEqual(self.run_check()['renderedPages'], [1])

    def test_theme_and_scale_changes_invalidate_all_pages(self):
        self.run_check()
        self.manifest['theme'] = dict(colors=dict(primary='#123456'))
        self.save(self.root / 'deck.pptd', self.manifest)
        self.assertEqual(self.run_check()['renderedPages'], [1, 2])
        self.assertEqual(self.run_check(scale=1)['renderedPages'], [1, 2])

    def test_corrupt_or_missing_cached_png_is_not_reused(self):
        self.run_check()
        qa = self.root / '.qa-images/pages'
        (qa / 'page_01.png').write_bytes(b'not a valid screenshot')
        (qa / 'page_02.png').unlink()
        self.assertEqual(self.run_check()['renderedPages'], [1, 2])

    def test_structural_failure_does_not_render_or_export(self):
        self.save(self.root / 'pages/02.page', dict(elements=[24]))
        with patch.object(prepare, 'subprocess') as process:
            report = self.run_check(export_formats=['html', 'pptx'])
        self.assertFalse(report['ok'])
        self.assertEqual(self.calls, [])
        process.run.assert_not_called()
        self.assertEqual(report['validation']['issues'][0]['code'], 'invalid-element')
        saved = json.loads((self.root / '.qa-images/prepare-report.json').read_text())
        self.assertFalse(saved['ok'])

    def test_remote_theme_image_never_reuses_cached_pixels(self):
        self.manifest['theme'] = dict(tableStyles=dict(default=dict(
            fill=dict(type='image', src='https://example.invalid/photo.jpg'))))
        self.save(self.root / 'deck.pptd', self.manifest)
        with self.assertRaisesRegex(ValueError, 'local'):
            self.run_check()
        self.assertEqual(self.calls, [])

    def test_output_cannot_replace_source_media(self):
        image = self.root / 'media/overview.jpg'
        Image.new('RGB', (960, 540), 'red').save(image)
        before = image.read_bytes()
        page = copy.deepcopy(self.page)
        page['background'] = dict(type='image', src='media/overview.jpg')
        self.save(self.root / 'pages/01.page', page)
        with self.assertRaisesRegex(ValueError, 'source'):
            self.run_check(output=self.root / 'media')
        self.assertEqual(image.read_bytes(), before)

    def test_failure_report_cannot_replace_a_malformed_source_page(self):
        source = self.root / 'draft/prepare-report.json'
        source.parent.mkdir()
        self.save(source, {'elements': [24]})
        self.manifest['pages'] = ['draft/prepare-report.json']
        self.save(self.root / 'deck.pptd', self.manifest)
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source'):
            self.run_check(output=source.parent)
        self.assertEqual(source.read_bytes(), before)

    def test_source_changed_during_render_cannot_commit_a_stale_snapshot(self):
        first = self.run_check()
        before = Path(first['overview']).read_bytes()
        def concurrent_edit(*args, **kwargs):
            result = self.render(*args, **kwargs)
            self.manifest['title'] = 'Changed while rendering'
            self.save(self.root / 'deck.pptd', self.manifest)
            return result
        with patch.object(prepare, 'export_images', side_effect=concurrent_edit):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                prepare.run(str(self.root), force=True)
        self.assertEqual(Path(first['overview']).read_bytes(), before)

    def test_export_timeout_writes_failure_instead_of_leaving_a_success_report(self):
        import subprocess
        with patch.object(prepare.subprocess, 'run', side_effect=subprocess.TimeoutExpired('export', 1)):
            report = self.run_check(export_formats=['html'])
        self.assertFalse(report['ok'])
        self.assertFalse(json.loads((self.root / '.qa-images/prepare-report.json').read_text())['ok'])

    def test_explicit_exports_keep_the_full_pptx_warning_report(self):
        import subprocess
        completed = subprocess.CompletedProcess('export', 0, '{"ok":true}', '')
        with patch.object(prepare.subprocess, 'run', return_value=completed) as process:
            report = self.run_check(export_formats=['html', 'pptx'])
        self.assertTrue(report['ok'])
        self.assertEqual(set(report['exports']), {'html', 'pptx'})
        command = process.call_args_list[1].args[0]
        self.assertIn('--report', command)
        self.assertEqual(Path(command[command.index('--report') + 1]).resolve(),
                         (self.root / '.qa-images/pptx-report.json').resolve())

    def test_render_failure_preserves_previous_successful_images(self):
        first = self.run_check()
        overview = Path(first['overview']).read_bytes()
        with patch.object(prepare, 'export_images', side_effect=RuntimeError('render failed')):
            with self.assertRaisesRegex(RuntimeError, 'render failed'):
                prepare.run(str(self.root), force=True)
        self.assertEqual(Path(first['overview']).read_bytes(), overview)

    def test_page_reorder_invalidates_indices_and_append_reuses_previous_pages(self):
        self.run_check()
        self.manifest['pages'].reverse()
        self.save(self.root / 'deck.pptd', self.manifest)
        self.assertEqual(self.run_check()['renderedPages'], [1, 2])
        self.manifest['pages'].append('pages/03.page')
        self.save(self.root / 'pages/03.page', self.page)
        self.save(self.root / 'deck.pptd', self.manifest)
        self.assertEqual(self.run_check()['renderedPages'], [3])


if __name__ == '__main__':
    unittest.main()
