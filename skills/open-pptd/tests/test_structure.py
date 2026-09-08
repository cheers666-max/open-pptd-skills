import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import authoring_helpers as helpers
import validate_deck as validate


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'pages').mkdir()
        (self.root / 'deck.pptd').write_text(json.dumps(dict(
            version='v2', title='Structure', size=[960, 540], pages=['pages/01.page'])))
        self.good = helpers.page([helpers.text('title', 40, 40, 500, 100, 'A title')])

    def audit(self, page):
        (self.root / 'pages/01.page').write_text(json.dumps(page))
        try:
            return validate.audit_project(self.root)
        except Exception as exc:
            self.fail(f'Structure errors must be reported with locations, not crash: {exc}')

    def test_nested_lists_and_integers_are_reported_instead_of_skipped(self):
        page = copy.deepcopy(self.good)
        page['elements'] += [[copy.deepcopy(page['elements'][0])], 24]
        report = self.audit(page)
        self.assertFalse(report['valid'])
        issues = [i for i in report['issues'] if i['code'] == 'invalid-element']
        self.assertEqual([i['location'] for i in issues], ['/elements/1', '/elements/2'])
        self.assertTrue(all(i['pageNumber'] == 1 and i['pageRef'] == 'pages/01.page' for i in issues))

    def test_wrong_page_and_elements_types_are_reported(self):
        for page in [[], None, {'elements': {}}, {'elements': None}, {}]:
            with self.subTest(page=page):
                self.assertFalse(self.audit(page)['valid'])

    def test_bad_fields_have_locations(self):
        mutations = [('bounds', [0, 0, 'wide', 30]), ('bounds', [0, 0, True, 30]),
                     ('bounds', [0, 0, -1, 30]), ('bounds', [0, 0, float('nan'), 30]),
                     ('bounds', [0, 0, 10 ** 400, 30]),
                     ('content', []), ('content', {'text': ['invalid']}),
                     ('opacity', 2), ('elementType', 'invented')]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                page = copy.deepcopy(self.good)
                page['elements'][0][field] = value
                report = self.audit(page)
                self.assertFalse(report['valid'])
                self.assertTrue(any(i.get('location', '').startswith('/elements/0/' + field)
                                    for i in report['issues']))

    def test_duplicate_ids_are_reported(self):
        page = copy.deepcopy(self.good)
        page['elements'].append(copy.deepcopy(page['elements'][0]))
        self.assertIn('duplicate-element-id', self.audit(page)['issueCounts'])

    def test_helper_rejects_all_pages_before_writing_any_output(self):
        destination = self.root / 'new'
        bad = copy.deepcopy(self.good)
        bad['elements'].append(24)
        with self.assertRaisesRegex(ValueError, r'pages/02.page.*elements/1'):
            helpers.write_project(destination, 'Invalid', [self.good, bad])
        self.assertFalse(destination.exists())

    def test_helper_failure_preserves_existing_project(self):
        old = (self.root / 'deck.pptd').read_bytes()
        with self.assertRaises(ValueError):
            helpers.write_project(self.root, 'Invalid', [{'elements': [24]}], overwrite=True)
        self.assertEqual((self.root / 'deck.pptd').read_bytes(), old)

    def test_valid_numeric_text_rich_text_and_zero_height_line_remain_supported(self):
        page = helpers.page([
            helpers.text('numeric', 40, 40, 400, 50, 0),
            helpers.text('boolean', 480, 40, 400, 50, True),
            helpers.text('rich', 40, 110, 400, 50, '<p><strong>中文</strong></p>'),
            helpers.line('rule', 40, 180, 400, 0, '0,0 400,0')])
        self.assertTrue(self.audit(page)['valid'])


if __name__ == '__main__':
    unittest.main()
