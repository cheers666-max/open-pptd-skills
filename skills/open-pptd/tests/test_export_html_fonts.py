import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import export_html


class EmbedFontsTests(unittest.TestCase):
    def setUp(self):
        self.regular = export_html.FONTS_DIR / 'NotoSansSC-Regular.ttf'
        if not self.regular.is_file():
            self.skipTest('bundled Noto font not downloaded (fonts/ is gitignored)')

    def _page(self, text):
        return ('<!doctype html><html><head><meta charset="utf-8"><style>.slide{font-family:MiSans,sans-serif}</style></head>'
                f'<body><div class="el el-text" style="font-family: &quot;Noto Sans SC&quot;; font-weight: bold;"><p>{text}</p></div></body></html>')

    def test_subset_faces_are_injected_once_and_are_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); (out / 'page_01.html').write_text(self._page('受理 1 检测 2'), encoding='utf-8')
            (out / 'other.txt').write_text('ignored')
            summary = export_html.embed_fonts(out)
            html = (out / 'page_01.html').read_text(encoding='utf-8')
            self.assertGreaterEqual(html.count('@font-face'), 1)
            self.assertIn('font-family:"Noto Sans SC";font-weight:400', html)
            self.assertIn('data:font/', html)
            total = sum(f['bytes'] for f in summary['embedded'])
            self.assertLess(total, 400_000, 'subset should be far smaller than the 16 MB source font')
            self.assertTrue(all(f['file'] == 'page_01.html' for f in summary['embedded']))
            # idempotent: a second pass must not duplicate faces
            before = html.count('@font-face'); export_html.embed_fonts(out)
            self.assertEqual((out / 'page_01.html').read_text(encoding='utf-8').count('@font-face'), before)

    def test_disabled_and_unrelated_families_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); (out / 'page_01.html').write_text('<html><head></head><body style="font-family: Arial">x</body></html>')
            self.assertTrue(export_html.embed_fonts(out, enabled=False)['skipped'])
            export_html.embed_fonts(out)
            self.assertNotIn('@font-face', (out / 'page_01.html').read_text())


class SubsetCacheTests(unittest.TestCase):
    """Subsetting is the slowest part of an export; the cache exists so a rerun skips it."""

    def setUp(self):
        if not (export_html.FONTS_DIR / 'NotoSansSC-Regular.ttf').is_file():
            self.skipTest('bundled Noto font not downloaded (fonts/ is gitignored)')

    def _pages(self, folder, count=2):
        out = Path(folder) / 'html'
        out.mkdir(parents=True, exist_ok=True)
        page = ('<!doctype html><html><head></head><body>'
                '<div class="el el-text" style="font-family: &quot;Noto Sans SC&quot;;"><p>商丘文化元素</p></div>'
                '</body></html>')
        for index in range(1, count + 1):
            (out / f'page_{index:02d}.html').write_text(page, encoding='utf-8')
        return out

    def test_a_rerun_reads_the_cache_and_writes_the_same_bytes(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            first = self._pages(folder)
            self.assertTrue(export_html.embed_fonts(first)['embedded'])
            cache = Path(folder) / '.font-cache'
            self.assertTrue(any(cache.iterdir()), 'nothing was cached')
            expected = (first / 'page_01.html').read_text(encoding='utf-8')

            second = self._pages(str(Path(folder) / 'again'))
            os.environ[export_html.FONT_CACHE_ENV] = str(cache)
            self.addCleanup(os.environ.pop, export_html.FONT_CACHE_ENV, None)
            export_html.embed_fonts(second)
            self.assertEqual((second / 'page_01.html').read_text(encoding='utf-8'), expected)

    def test_a_cache_it_cannot_write_is_not_a_failed_export(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            out = self._pages(folder, count=1)
            os.environ[export_html.FONT_CACHE_ENV] = '/dev/null/cache'
            self.addCleanup(os.environ.pop, export_html.FONT_CACHE_ENV, None)
            self.assertTrue(export_html.embed_fonts(out)['embedded'])
            self.assertIn('@font-face', (out / 'page_01.html').read_text(encoding='utf-8'))

    def test_two_exports_of_one_page_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = self._pages(folder, 1), self._pages(str(Path(folder) / 'b'), 1)
            export_html.embed_fonts(a)
            export_html.embed_fonts(b)
            self.assertEqual((a / 'page_01.html').read_text(encoding='utf-8'),
                             (b / 'page_01.html').read_text(encoding='utf-8'))
