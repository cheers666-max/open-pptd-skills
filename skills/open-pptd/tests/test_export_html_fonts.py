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
