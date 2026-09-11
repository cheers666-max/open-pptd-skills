import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import outline_contract as contract


def write_project(folder, pages):
    root = Path(folder)
    (root / 'pages').mkdir()
    refs = '\n'.join(f'  - pages/{i:02d}.page' for i in range(1, len(pages) + 1))
    (root / 'deck.pptd').write_text(f'version: v2\ntitle: T\nsize: [960, 540]\npages:\n{refs}\n')
    for index, body in enumerate(pages, start=1):
        (root / 'pages' / f'{index:02d}.page').write_text(body)
    return root


TEXT_PAGE = 'pageType: content\nelements:\n- elementId: t\n  elementType: text\n  bounds: [48, 48, 400, 40]\n  content:\n    text: hi\n'
IMAGE_PAGE = (TEXT_PAGE + '- elementId: pic\n  elementType: image\n  bounds: [500, 100, 300, 200]\n  src: media/a.jpg\n')
BACKGROUND_PAGE = 'pageType: cover\nbackground:\n  type: image\n  src: media/bg.jpg\nelements:\n- elementId: t\n  elementType: text\n  bounds: [48, 48, 400, 40]\n  content:\n    text: hi\n'


def outline(pages, **top):
    body = {'title': 'T', 'pages': pages}
    body.update(top)
    return body


def page(index, **fields):
    base = {'pageIndex': index, 'pageType': 'content', 'actionTitle': f'第 {index} 页结论',
            'summary': '一句话', 'slots': ['a', 'b'], 'image': True, 'imageQuery': '示例 配图'}
    base.update(fields)
    return base


class PlanTests(unittest.TestCase):
    def test_page_count_must_match_what_was_agreed(self):
        issues = contract.plan_issues(outline([page(1), page(2)], requestedPages=7))
        self.assertEqual([i['code'] for i in issues], ['outline-page-count'])

    def test_a_page_needs_a_point_a_summary_and_enough_slots(self):
        thin = page(1, actionTitle='', summary='', slots=['only'])
        codes = sorted(i['code'] for i in contract.plan_issues(outline([thin])))
        self.assertEqual(codes, ['outline-missing-summary', 'outline-missing-title', 'outline-thin-page'])

    def test_a_complete_plan_passes(self):
        self.assertEqual(contract.plan_issues(outline([page(1), page(2)], requestedPages=2)), [])


class IllustrationTests(unittest.TestCase):
    def test_a_text_only_deck_is_reported(self):
        pages = [page(i, image=False) for i in range(1, 6)]
        codes = [i['code'] for i in contract.plan_issues(outline(pages, requestedPages=5))]
        self.assertIn('outline-thin-illustration', codes)

    def test_meeting_the_target_passes(self):
        pages = [page(i) for i in range(1, 5)] + [page(5, image=False)]
        self.assertEqual(contract.plan_issues(outline(pages, requestedPages=5)), [])

    def test_a_page_may_plan_several_pictures(self):
        rich = page(1, image=None, images=[{'query': '云手 分解'}, {'query': '课堂 示范'}])
        self.assertEqual(contract.planned_image_count(rich), 2)
        self.assertEqual(contract.planned_image_count(page(2, image=False)), 0)


class DeckTests(unittest.TestCase):
    def test_promised_picture_missing_from_the_built_page(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_project(folder, [IMAGE_PAGE, TEXT_PAGE])
            plan = outline([page(1, image=True), page(2, image=True)], requestedPages=2)
            issues = contract.deck_issues(root, plan)
            self.assertEqual([(i['code'], i['pageIndex']) for i in issues], [('outline-missing-image', 2)])

    def test_background_image_counts_as_the_promised_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_project(folder, [BACKGROUND_PAGE])
            plan = outline([page(1, pageType='cover', image=True)], requestedPages=1)
            self.assertEqual(contract.deck_issues(root, plan), [])

    def test_a_page_that_placed_fewer_pictures_than_planned(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_project(folder, [IMAGE_PAGE])
            plan = outline([page(1, image=None, images=[{'query': 'a'}, {'query': 'b'}])], requestedPages=1)
            issues = contract.deck_issues(root, plan)
            self.assertEqual([(i['code'], i['planned'], i['placed']) for i in issues],
                             [('outline-fewer-images', 2, 1)])

    def test_short_deck_and_drifted_page_type_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_project(folder, [BACKGROUND_PAGE])
            plan = outline([page(1, pageType='content'), page(2)], requestedPages=2)
            codes = sorted(i['code'] for i in contract.deck_issues(root, plan))
            self.assertEqual(codes, ['outline-deck-count', 'outline-page-type'])


class ReportTests(unittest.TestCase):
    def test_audit_and_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_project(folder, [IMAGE_PAGE])
            path = root / 'outline.json'
            path.write_text(json.dumps(outline([page(1, image=True)], requestedPages=1,
                                               audience='教师', purpose='培训'), ensure_ascii=False))
            report = contract.audit(path, root)
            self.assertTrue(report['valid'])
            self.assertEqual(report['pageCount'], 1)
            table = contract.to_markdown(json.loads(path.read_text()))
            self.assertIn('受众：教师', table)
            self.assertIn('| 1 | content |', table)


if __name__ == '__main__':
    unittest.main()


class ImageSlotDeclarationTests(unittest.TestCase):
    """29 of 187 pictures in the 20-page batch were a portrait photo in a landscape frame.

    The pool already filters by orientation and scores by ratio, but the outline never declared
    either, so every slot defaulted to landscape and the filter silently passed anything. One
    declaration per slot drives the search, the score and the fit mode.
    """

    def outline(self, image_entry):
        return {"pages": [{"pageIndex": 1, "pageType": "content", "actionTitle": "T",
                           "summary": "S", "slots": ["title"], "images": [image_entry]}]}

    def codes(self, outline):
        return {i["code"] for i in contract.plan_issues(outline)}

    def test_a_slot_without_a_target_ratio_is_reported(self):
        self.assertIn("outline-image-slot-undeclared",
                      self.codes(self.outline({"query": "庄子像 商丘民权"})))

    def test_a_slot_without_a_subject_is_reported(self):
        self.assertIn("outline-image-slot-undeclared",
                      self.codes(self.outline({"query": "庄子像", "ratio": 1.33})))

    def test_a_fully_declared_slot_passes(self):
        self.assertNotIn("outline-image-slot-undeclared",
                         self.codes(self.outline({"query": "庄子像", "ratio": 1.33,
                                                  "subject": "artifact"})))

    def test_an_unknown_subject_is_reported(self):
        self.assertIn("outline-image-slot-subject",
                      self.codes(self.outline({"query": "庄子像", "ratio": 1.33,
                                               "subject": "statue"})))

    def test_a_nonsense_ratio_is_reported(self):
        self.assertIn("outline-image-slot-ratio",
                      self.codes(self.outline({"query": "庄子像", "ratio": 0,
                                               "subject": "scene"})))
