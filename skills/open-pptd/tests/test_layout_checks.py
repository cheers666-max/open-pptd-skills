import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_deck as validate
import audit_rendered as audit
import layout_planner as planner
import authoring_helpers
from PIL import Image, ImageDraw


class CapacityTests(unittest.TestCase):
    def test_authoring_helper_preserves_rich_quotes_and_refuses_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            value = '<p style="color: #123456">引号 " # : 文本</p>\nSecond paragraph'
            pages = [authoring_helpers.page([authoring_helpers.text('t',40,40,800,100,value)])]
            manifest = authoring_helpers.write_project(folder,'Smoke',pages)
            source = (Path(folder)/'pages/01.page').read_text()
            self.assertIn('text: |',source)
            self.assertEqual(validate.load_structured(Path(folder)/'pages/01.page')['elements'][0]['content']['text'],value)
            before = manifest.read_bytes()
            with self.assertRaises(FileExistsError):
                authoring_helpers.write_project(folder,'changed',pages)
            self.assertEqual(manifest.read_bytes(),before)

    def test_nested_gradient_schema_is_reported_before_silent_black_fill(self):
        bad = dict(type='gradient',gradient=dict(type='linear',stops=[dict(offset=0,color='#000000'),dict(offset=1,color='#FFFFFF')]))
        self.assertEqual(validate.gradient_issues(dict(elements=[dict(elementId='overlay',fill=bad)]),1,'pages/1.page')[0]['code'],'invalid-gradient')
        good = dict(type='gradient',stops=[dict(position=0,color='#000000'),dict(position=1,color='#FFFFFF')])
        self.assertEqual(validate.gradient_issues(dict(background=good),1,'pages/1.page'),[])

    def test_paragraph_boundaries_count_as_lines(self):
        r = validate.layout_text('<p>First</p><p>Second</p>', 12, 1.5, 400, 20)
        self.assertEqual(r['lineCount'], 2)
        self.assertTrue(r['heightOverflow'])

    def test_inline_large_font_counts(self):
        el = dict(elementType='text', elementId='large', bounds=[0, 0, 300, 20],
                  content=dict(fontSize=12, text='<span style="font-size:64px">大字</span>'))
        issues = validate.text_issues(el, 1, 'pages/01.page', 960, 540)
        self.assertTrue(any(i['code'] == 'text-capacity-overflow' for i in issues))

    def test_fixed_line_height_and_cjk(self):
        r = validate.layout_text('<p style="line-height:40px">中文</p>', 12, 1.5, 300, 20)
        self.assertEqual(r['estimatedHeight'], 40)
        self.assertTrue(r['heightOverflow'])
        self.assertFalse(validate.layout_text('中文', 12, 1.5, 100, 20)['overflow'])

    def test_theme_and_native_fixed_height_are_applied(self):
        el = dict(elementType='text', bounds=[0, 0, 300, 25],
                  content=dict(style='$body', text='中文', lineHeight=1))
        theme = dict(textStyles=dict(body=dict(fontSize=12, lineHeightPx=40)))
        issues = validate.text_issues(el, 1, 'pages/01.page', 960, 540, theme=theme)
        overflow = next(i for i in issues if i['code'] == 'text-capacity-overflow')
        self.assertEqual(overflow['estimatedHeight'], 40)

    def test_inline_font_width_and_native_padding_are_counted(self):
        r = validate.layout_text('<span style="font-size:64px">中文</span>', 12, 1, 100, 100, wrap=False)
        self.assertTrue(r['widthOverflow'])
        el = dict(elementType='text', bounds=[0, 0, 300, 25],
                  content=dict(fontSize=18, lineHeight=1, marginTop=10, text='中文'))
        issues = validate.text_issues(el, 1, 'pages/01.page', 960, 540)
        self.assertTrue(any(i['code'] == 'text-capacity-overflow' for i in issues))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.page=self.root/'01.page'
        self.img=self.root/'01.png'
        image=Image.new('RGB',(960,540),'white')
        ImageDraw.Draw(image).text((60,110),'Black text',fill='black')
        image.save(self.img)

    def write(self,color='#000000',background=None,overlay=None,text='Text'):
        data=dict(background=background or dict(type='solid',color='#FFFFFF'),elements=[
            dict(elementType='text',elementId='title',bounds=[40,100,600,50],content=dict(fontSize=24,color=color,text=text))])
        if overlay:data['elements'].append(overlay)
        self.page.write_text(json.dumps(data))

    def test_black_white_is_not_low_contrast(self):
        self.write()
        self.assertFalse(any(i['type']=='contrast' for i in audit.audit_page(self.img,self.page,1,1)))

    def test_pure_low_contrast_is_reported(self):
        self.write('#EEEEEE')
        issues=audit.audit_page(self.img,self.page,1,1)
        self.assertTrue(any(i['type']=='contrast' and i['ratio']<1.3 for i in issues))

    def test_complex_background_is_unknown_not_false_error(self):
        self.write(background=dict(type='image',src='media/photo.jpg'))
        issues=audit.audit_page(self.img,self.page,1,1)
        self.assertTrue(any(i.get('status')=='not_checked' for i in issues))
        self.assertFalse(any(i.get('severity')=='error' for i in issues))

    def test_transparent_overlay_is_not_occlusion(self):
        self.write(overlay=dict(elementType='shape',elementId='clear',bounds=[40,100,600,50],opacity=0,fill=dict(color='#000000')))
        self.assertFalse(any(i['type']=='occlusion' for i in audit.audit_page(self.img,self.page,1,1)))

    def test_bad_yaml_does_not_return_empty_success(self):
        self.page.write_text('elements: [ broken')
        with self.assertRaises(Exception):
            audit.audit_page(self.img,self.page,1,1)


class PlannerTests(unittest.TestCase):
    def test_fixed_count_and_all_fields_preserved(self):
        pages=[dict(index=i+1,type='content',title='Same title',custom={'keep':i}) for i in range(14)]
        self.assertEqual(planner.plan_rhythm(pages),pages)

    def test_continuous_teaching_group_has_no_forced_change(self):
        pages=[dict(index=i+1,type='content',title='Derive',layoutIntent='derivation',continuityGroup='lesson') for i in range(4)]
        self.assertEqual(planner.plan_rhythm(pages),pages)
        self.assertEqual(planner.validate_rhythm(pages),[])


if __name__=='__main__':
    unittest.main()


class InternalTokenAndDuplicateImageTests(unittest.TestCase):
    def _page(self, texts=(), images=(), background=None):
        page = {'elements': []}
        if background:
            page['background'] = {'type': 'image', 'src': background}
        for i, txt in enumerate(texts):
            page['elements'].append({'elementId': f't{i}', 'elementType': 'text', 'bounds': [0, 0, 400, 40],
                                     'content': {'text': txt, 'fontSize': 12}})
        for i, src in enumerate(images):
            page['elements'].append({'elementId': f'i{i}', 'elementType': 'image', 'bounds': [0, 0, 200, 100], 'src': src})
        return page

    def test_internal_tokens_in_visible_text_are_reported(self):
        page = self._page(texts=['资料图：山间徒步（开放授权，来源见 images_report.json）', '依据：材料包（儿童教法）', '正常图注：Wikimedia Commons，CC BY 2.0'])
        issues = validate.internal_token_leak_issues(page, 3, 'pages/03.page')
        self.assertEqual([i['elementId'] for i in issues], ['t0', 't1'])
        self.assertTrue(all(i['code'] == 'internal-token-leak' for i in issues))

    def test_speaker_notes_are_not_scanned(self):
        page = self._page(texts=['正文']); page['notes'] = '内部：出处见 images_report.json'
        self.assertEqual(validate.internal_token_leak_issues(page, 1, 'pages/01.page'), [])

    def test_duplicate_image_across_content_pages_is_asset_replacement(self):
        pages = [(1, 'pages/01.page', self._page(background='media/cover.jpg')),
                 (2, 'pages/02.page', self._page(images=['media/a.jpg'])),
                 (3, 'pages/03.page', self._page(images=['media/a.jpg', 'media/b.jpg'])),
                 (4, 'pages/04.page', self._page(background='media/cover.jpg'))]
        issues = validate.duplicate_image_issues(pages)
        by_src = {i['src']: i for i in issues}
        self.assertEqual(set(by_src), {'media/a.jpg', 'media/cover.jpg'})
        self.assertEqual(by_src['media/a.jpg']['repairability'], 'asset-replacement')
        self.assertEqual(by_src['media/a.jpg']['pages'], [2, 3])
        self.assertEqual(by_src['media/cover.jpg']['repairability'], 'style')

    def test_unique_images_and_search_placeholders_are_silent(self):
        pages = [(1, 'pages/01.page', self._page(images=['search: mountain'])),
                 (2, 'pages/02.page', self._page(images=['search: mountain', 'media/x.jpg']))]
        self.assertEqual(validate.duplicate_image_issues(pages), [])
