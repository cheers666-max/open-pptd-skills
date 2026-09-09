import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'image_search'))
import image_pool  # noqa: E402
import validate_deck as validate  # noqa: E402


def make_project(folder, page_bodies, outline=None):
    root = Path(folder)
    (root / 'pages').mkdir()
    refs = '\n'.join(f'  - pages/{i:02d}.page' for i in range(1, len(page_bodies) + 1))
    (root / 'deck.pptd').write_text(f'version: v2\ntitle: Pool deck\nsize: [960, 540]\npages:\n{refs}\n')
    for index, body in enumerate(page_bodies, start=1):
        (root / 'pages' / f'{index:02d}.page').write_text(body)
    if outline is not None:
        (root / 'outline.json').write_text(json.dumps(outline, ensure_ascii=False))
    return root


POOL_PAGE = '''pageType: content
elements:
- elementId: photo
  elementType: image
  bounds: [500, 100, 380, 240]
  src: "pool:p2"
'''


class IntentTests(unittest.TestCase):
    def test_only_pages_that_asked_for_a_picture_become_intents(self):
        outline = {'pages': [
            {'pageIndex': 1, 'image': True, 'actionTitle': '常州古城的来历', 'summary': 's'},
            {'pageIndex': 2, 'image': False, 'actionTitle': '没有图的一页'},
            {'pageIndex': 3, 'image': True, 'imageQuery': '风电场 航拍', 'imageOrientation': 'portrait'},
        ]}
        intents = image_pool.intents_from_outline(outline)
        self.assertEqual([i['id'] for i in intents], ['p1', 'p3'])
        self.assertEqual(intents[0]['query'], '常州古城的来历')
        self.assertEqual(intents[1]['query'], '风电场 航拍')
        self.assertEqual(intents[1]['want'], 'portrait')

    def test_a_page_without_any_wording_is_skipped(self):
        self.assertEqual(image_pool.intents_from_outline({'pages': [{'pageIndex': 1, 'image': True}]}), [])


class QueryLanguageTests(unittest.TestCase):
    def test_latin_only_query_is_refused_before_searching(self):
        intents = [{'id': 'p2', 'query': 'movie projector light beam dark room'},
                   {'id': 'p3', 'query': '电影院 观众席'}]
        with self.assertRaises(ValueError) as caught:
            image_pool.check_queries(intents)
        self.assertIn('p2', str(caught.exception))
        self.assertNotIn('p3', str(caught.exception))

    def test_chinese_queries_pass(self):
        self.assertIsNone(image_pool.check_queries([{'id': 'p1', 'query': '草原 风力发电 航拍'}]))


class ImagePlanTests(unittest.TestCase):
    def test_a_page_can_ask_for_several_pictures(self):
        outline = {'pages': [{'pageIndex': 6, 'images': [
            {'query': '云手 动作 分解', 'orientation': 'portrait'},
            {'query': '身韵课堂 教学 示范'},
            '折扇 舞蹈 道具 特写']}]}
        intents = image_pool.intents_from_outline(outline)
        self.assertEqual([i['id'] for i in intents], ['p6a', 'p6b', 'p6c'])
        self.assertEqual(intents[0]['want'], 'portrait')
        self.assertEqual(intents[2]['query'], '折扇 舞蹈 道具 特写')
        self.assertEqual({i['pageIndex'] for i in intents}, {6})

    def test_the_single_picture_form_still_works(self):
        outline = {'pages': [{'pageIndex': 3, 'image': True, 'imageQuery': '风电场 航拍'}]}
        intents = image_pool.intents_from_outline(outline)
        self.assertEqual([(i['id'], i['query']) for i in intents], [('p3', '风电场 航拍')])

    def test_a_short_query_is_left_alone_by_the_retry_trim(self):
        self.assertEqual(image_pool._trimmed('风电场 航拍'), '')
        self.assertEqual(image_pool._trimmed('电影院 观众席 背影 夜晚'), '电影院 观众席')


class ResolveTests(unittest.TestCase):
    def test_reference_is_rewritten_to_the_pooled_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = make_project(folder, [POOL_PAGE])
            (root / 'images_pool.json').write_text(json.dumps(
                {'candidates': [{'id': 'p2', 'local': 'media/pool-p2-abcdef.jpg'}]}))
            self.assertEqual(image_pool.resolve(root), 0)
            self.assertIn('media/pool-p2-abcdef.jpg', (root / 'pages/01.page').read_text())
            self.assertNotIn('pool:p2', (root / 'pages/01.page').read_text())

    def test_unknown_id_is_reported_and_never_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = make_project(folder, [POOL_PAGE])
            (root / 'images_pool.json').write_text(json.dumps(
                {'candidates': [{'id': 'p9', 'local': 'media/other.jpg'}]}))
            self.assertEqual(image_pool.resolve(root), 2)
            self.assertIn('pool:p2', (root / 'pages/01.page').read_text())


class BuildTests(unittest.TestCase):
    def test_winners_are_written_to_media_and_listed_in_the_pool(self):
        with tempfile.TemporaryDirectory() as folder:
            outline = {'pages': [{'pageIndex': 2, 'image': True, 'actionTitle': '龙门吊', 'summary': 'x'}]}
            root = make_project(folder, [POOL_PAGE], outline)

            def fake_attempts(slots, texts, brief, backend, workers, timeout, deadline, use_vlm,
                              min_dim, limit=8):
                for slot in slots:
                    slot.winner = {'bytes': b'\xff\xd8jpeg-bytes', 'sha256': 'a' * 64, 'fmt': 'jpeg',
                                   'w': 1600, 'h': 900, 'backend': 'baidu',
                                   'url': 'https://example.com/a.jpg', 'score': 0.8}
                    slot.status = 'resolved'

            with patch.object(image_pool.search_images, '_attempts', fake_attempts):
                self.assertEqual(image_pool.build(root, json_output=False), 0)
            report = json.loads((root / 'images_pool.json').read_text())
            self.assertEqual(report['collected'], 1)
            entry = report['candidates'][0]
            self.assertEqual((entry['id'], entry['pageIndex'], entry['ratio']), ('p2', 2, 1.778))
            self.assertTrue((root / entry['local']).is_file())
            self.assertEqual(image_pool.resolve(root), 0)

    def test_an_intent_with_no_winner_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            outline = {'pages': [{'pageIndex': 1, 'image': True, 'actionTitle': '找不到的图'}]}
            root = make_project(folder, [POOL_PAGE], outline)
            with patch.object(image_pool.search_images, '_attempts', lambda *a, **k: None):
                self.assertEqual(image_pool.build(root), 2)
            self.assertEqual(json.loads((root / 'images_pool.json').read_text())['failedIntents'], ['p1'])


class ValidateTests(unittest.TestCase):
    def test_leftover_pool_reference_blocks(self):
        page = {'elements': [{'elementId': 'photo', 'elementType': 'image',
                              'bounds': [0, 0, 100, 100], 'src': 'pool:p2'}]}
        codes = [i['code'] for i in validate.unresolved_src_issues(page, 1, 'pages/01.page')]
        self.assertEqual(codes, ['unresolved-pool-reference'])


if __name__ == '__main__':
    unittest.main()
