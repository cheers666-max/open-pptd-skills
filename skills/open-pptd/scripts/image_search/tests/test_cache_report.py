"""Incremental acquisition keeps provenance only for current, unambiguous slots."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import search_images


class CacheReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'pages').mkdir()
        (self.root / 'deck.pptd').write_text('title: Cache test\npages: [pages/01.page]\n')
        self.page_path = self.root / 'pages/01.page'
        self.page('search:alpha', 'search:beta')
        self.original_page = self.page_path.read_text()

    def page(self, first, second=None, *, first_id='a', bounds='[0, 0, 960, 540]'):
        text = 'pageType: content\nelements:\n'
        for element_id, src in [(first_id, first), ('b', second)]:
            if src is not None:
                text += (f'  - elementId: {element_id}\n    elementType: image\n'
                         f'    bounds: {bounds}\n    src: "{src}" # keep comment\n')
        self.page_path.write_text(text)

    @staticmethod
    def resolve(slots, *_args):
        for slot in slots:
            slot.winner = search_images._gradient(slot)
            slot.winner.update(url=f'https://example.invalid/{slot.query}.png', backend='fixture',
                               license='CC BY 4.0', landing='https://example.invalid/source',
                               vlm={'relevance': 2, 'reason': 'fixture provenance'}, score=26)
            slot.status = 'resolved'
            slot.tried = [{'backend': 'fixture', 'fate': 'accepted'}]

    def run_pipeline(self, *, offline=False, resolver=None):
        output = io.StringIO()
        with patch.object(search_images, '_attempts', side_effect=resolver or self.resolve), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = search_images.run(self.root, offline=offline, json_output=True,
                                     allow_latin_query=True)
        report = json.loads((self.root / 'images_report.json').read_text())
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertEqual(report['total_slots'], len(report['slots']))
        self.assertEqual(report['resolved'] + report['failed'], report['total_slots'])
        return code, report

    def test_partial_research_preserves_untouched_provenance(self):
        _, before = self.run_pipeline()
        original = copy.deepcopy(before['slots'][0])
        self.page(original['local'], 'search:new beta')
        _, report = self.run_pipeline()
        self.assertEqual(report['total_slots'], 2)
        self.assertEqual(report['slots'][0], original)
        self.assertEqual(report['slots'][1]['query'], 'new beta')

    def test_rebuild_same_slots_reuses_images_and_full_provenance(self):
        _, before = self.run_pipeline()
        self.page_path.write_text('\n# rebuilt with shifted lines\n' + self.original_page)
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(report['slots'], before['slots'])
        self.assertNotIn('search:', self.page_path.read_text())
        self.assertIn('# keep comment', self.page_path.read_text())

    def test_no_placeholder_rerun_returns_and_writes_live_records(self):
        _, before = self.run_pipeline()
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(report['slots'], before['slots'])

    def test_failed_partial_research_keeps_success_and_failure_counts(self):
        _, before = self.run_pipeline()
        self.page(before['slots'][0]['local'], 'search:unavailable')
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual((report['total_slots'], report['resolved'], report['failed']), (2, 1, 1))
        self.assertEqual(report['slots'][0], before['slots'][0])
        self.assertEqual(report['slots'][1]['query'], 'unavailable')

    def test_removed_or_manually_replaced_slots_do_not_keep_old_records(self):
        self.run_pipeline()
        (self.root / 'media/manual.png').write_bytes(b'manual asset')
        self.page('media/manual.png')
        _, report = self.run_pipeline(offline=True)
        self.assertEqual(report['slots'], [])

    def test_deleted_slot_cache_is_not_reused_for_new_element(self):
        self.run_pipeline()
        self.page('search:alpha', first_id='new-element')
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['slots'][0]['status'], 'failed')

    def test_changed_query_and_orientation_require_new_acquisition(self):
        self.run_pipeline()
        self.page('search:changed', 'search:beta', bounds='[0, 0, 300, 900]')
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['failed'], 2)

    def test_missing_cached_file_does_not_claim_live_success(self):
        _, report = self.run_pipeline()
        (self.root / report['slots'][0]['local']).unlink()
        _, report = self.run_pipeline(offline=True)
        self.assertEqual([record['elementId'] for record in report['slots']], ['b'])

    def test_new_records_include_the_full_content_digest(self):
        _, report = self.run_pipeline()
        for record in report['slots']:
            digest = hashlib.sha256((self.root / record['local']).read_bytes()).hexdigest()
            self.assertEqual(record.get('sha256'), digest)

    def test_replaced_local_bytes_do_not_inherit_old_provenance(self):
        _, before = self.run_pipeline()
        first, second = before['slots']
        (self.root / first['local']).write_bytes((self.root / second['local']).read_bytes())
        _, report = self.run_pipeline(offline=True)
        self.assertEqual(report['slots'], [second])

    def test_rebuild_rejects_replaced_bytes_for_new_and_legacy_records(self):
        _, before = self.run_pipeline()
        first, second = before['slots']
        (self.root / first['local']).write_bytes((self.root / second['local']).read_bytes())
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                records = copy.deepcopy(before)
                if legacy:
                    for record in records['slots']:
                        record.pop('sha256', None)
                (self.root / 'images_report.json').write_text(json.dumps(records))
                self.page_path.write_text(self.original_page)
                code, report = self.run_pipeline(offline=True)
                self.assertEqual(code, 2)
                self.assertEqual(report['slots'][0]['status'], 'failed')
                self.assertNotIn('source_url', report['slots'][0])
                self.assertEqual(report['slots'][1]['status'], 'resolved')

    def test_legacy_filename_digest_allows_restore_and_upgrades_record(self):
        _, before = self.run_pipeline()
        legacy = copy.deepcopy(before)
        for record in legacy['slots']:
            record.pop('sha256', None)
        (self.root / 'images_report.json').write_text(json.dumps(legacy))
        self.page_path.write_text(self.original_page)
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 0)
        for record, original in zip(report['slots'], before['slots']):
            self.assertEqual(record['source_url'], original['source_url'])
            self.assertEqual(record['vlm'], original['vlm'])
            digest = hashlib.sha256((self.root / record['local']).read_bytes()).hexdigest()
            self.assertEqual(record.get('sha256'), digest)

    def test_legacy_without_verifiable_digest_is_not_reused(self):
        _, before = self.run_pipeline()
        first = before['slots'][0]
        (self.root / first['local']).rename(self.root / 'media/no-digest.png')
        first.update(local='media/no-digest.png')
        first.pop('sha256', None)
        (self.root / 'images_report.json').write_text(json.dumps(before))
        self.page_path.write_text(self.original_page)
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['slots'][0]['status'], 'failed')

    def test_full_digest_mismatch_cannot_fall_back_to_filename_prefix(self):
        _, before = self.run_pipeline()
        first = before['slots'][0]
        digest = hashlib.sha256((self.root / first['local']).read_bytes()).hexdigest()
        first['sha256'] = digest[:10] + '0' * 54
        (self.root / 'images_report.json').write_text(json.dumps(before))
        self.page_path.write_text(self.original_page)
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['slots'][0]['status'], 'failed')

    def test_anonymous_duplicate_slots_are_not_reused_ambiguously(self):
        anonymous = ('  - elementType: shape\n    fill:\n'
                     '      type: image\n      src: "search:alpha"\n')
        self.page_path.write_text('elements:\n' + anonymous)
        self.run_pipeline()
        self.page_path.write_text('elements:\n' + anonymous * 2)
        code, report = self.run_pipeline(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(report['failed'], 2)


if __name__ == '__main__':
    unittest.main()
