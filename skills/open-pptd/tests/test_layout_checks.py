import json
from pathlib import Path
import sys
import pathlib
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

    def test_missing_body_leaves_a_flagged_empty_band(self):
        page = dict(pageType='content', elements=[
            dict(elementId='title', elementType='text', bounds=[48, 48, 864, 40],
                 content=dict(text='八元素与三种圆')),
            dict(elementId='lead', elementType='text', bounds=[48, 114, 400, 20],
                 content=dict(text='八个基本元素')),
            dict(elementId='foot', elementType='text', bounds=[48, 424, 864, 24],
                 content=dict(text='来源：教材')),
        ])
        issue = validate.empty_band_issue(page, 6, 'pages/06.page', 540)
        self.assertEqual(issue['code'], 'empty-body-band')
        self.assertEqual(issue['bandTop'], 134.0)
        self.assertGreater(issue['bandRatio'], 0.5)

    def test_deliberate_whitespace_around_a_body_is_not_flagged(self):
        page = dict(pageType='content', elements=[
            dict(elementId='title', elementType='text', bounds=[48, 48, 864, 40],
                 content=dict(text='留白但完整的一页')),
            dict(elementId='body', elementType='text', bounds=[48, 220, 500, 120],
                 content=dict(text='正文写在中间')),
            dict(elementId='foot', elementType='text', bounds=[48, 460, 864, 24],
                 content=dict(text='来源：示例')),
        ])
        self.assertIsNone(validate.empty_band_issue(page, 1, 'pages/01.page', 540))

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


class TextDensityAdvisoryTests(unittest.TestCase):
    def _page(self, chars, page_type='content'):
        return {'pageType': page_type, 'elements': [{'elementId': 'body', 'elementType': 'text', 'bounds': [0, 0, 800, 400],
                'content': {'text': '<p>' + ('字' * chars) + '</p>', 'fontSize': 12}}]}

    def test_dense_content_page_gets_advisory_only(self):
        adv = validate.text_density_advisory(self._page(500), 4, 'pages/04.page')
        self.assertEqual(adv['code'], 'text-density'); self.assertEqual(adv['chars'], 500)
        self.assertIsNone(validate.text_density_advisory(self._page(300), 4, 'pages/04.page'))

    def test_cover_and_custom_threshold(self):
        self.assertIsNone(validate.text_density_advisory(self._page(900, 'cover'), 1, 'pages/01.page'))
        self.assertIsNotNone(validate.text_density_advisory(self._page(300), 2, 'pages/02.page', max_chars=200))


class DuplicateImageValidityTests(unittest.TestCase):
    def test_cover_closing_pair_is_advisory_and_content_reuse_blocks(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'pages').mkdir(); (root / 'media').mkdir()
            Image.new('RGB', (1600, 900), 'white').save(root / 'media' / 'a.jpg')
            Image.new('RGB', (1600, 900), 'gray').save(root / 'media' / 'c.jpg')
            def page(name, page_type, images=(), background=None):
                data = {'pageType': page_type, 'elements': [{'elementId': f'{name}-img{i}', 'elementType': 'image', 'bounds': [40, 40, 400, 225], 'src': src} for i, src in enumerate(images)]}
                if background: data['background'] = {'type': 'image', 'src': background}
                (root / 'pages' / f'{name}.page').write_text(yaml.safe_dump(data, allow_unicode=True))
            page('01', 'cover', background='media/c.jpg'); page('02', 'content', images=['media/a.jpg']); page('03', 'content', images=['media/a.jpg']); page('04', 'final', background='media/c.jpg')
            (root / 'deck.pptd').write_text(yaml.safe_dump({'version': 'v2', 'title': 't', 'size': [960, 540], 'pages': ['pages/01.page', 'pages/02.page', 'pages/03.page', 'pages/04.page']}))
            report = validate.audit_project(root)
            self.assertEqual(report['issueCounts'].get('duplicate-image'), 1)
            self.assertEqual(report['advisoryCounts'].get('duplicate-image'), 1)
            self.assertFalse(report['valid'])


class ElementSchemaTests(unittest.TestCase):
    def test_unreadable_align_blocks_and_readable_variants_are_advice(self):
        page = {'elements': [
            {'elementId': 'n', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '1', 'align': [['center', 'middle']]}},
            {'elementId': 'bare', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '2', 'align': 'right'}},
            {'elementId': 'num', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '3', 'align': [0.5, 0.5]}},
            {'elementId': 'synonym', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '4', 'align': ['left', 'center']}},
            {'elementId': 'ok', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '5', 'align': ['center', 'middle']}},
            {'elementId': 'bad-word', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '6', 'align': ['centre', 'middle']}},
            {'elementId': 'too-long', 'elementType': 'text', 'bounds': [0, 0, 36, 36], 'content': {'text': '7', 'align': ['left', 'top', 'left']}},
            {'elementId': 'arrow', 'elementType': 'line', 'bounds': [0, 0, 12, 18], 'viewBox': [12, 18], 'points': '0,0 0,100'},
            {'elementId': 'arrow-ok', 'elementType': 'line', 'bounds': [0, 0, 12, 18], 'viewBox': [12, 18], 'points': '0,0 0,18'},
        ]}
        codes = sorted((i['code'], i['elementId']) for i in validate.element_schema_issues(page, 1, 'pages/01.page'))
        self.assertEqual(codes, [
            ('invalid-align', 'bad-word'),
            ('invalid-align', 'too-long'),
            ('line-points-outside-viewbox', 'arrow'),
            ('non-canonical-align', 'bare'),
            ('non-canonical-align', 'n'),
            ('non-canonical-align', 'num'),
            ('non-canonical-align', 'synonym'),
        ])

    def test_non_canonical_align_is_advice_and_does_not_fail_a_deck(self):
        import tempfile, pathlib, json as _json
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / 'pages').mkdir()
            (root / 'deck.pptd').write_text('version: v2\ntitle: T\nsize: [960, 540]\npages:\n  - pages/01.page\n')
            (root / 'pages/01.page').write_text(
                'pageType: content\nelements:\n'
                '- elementId: t\n  elementType: text\n  bounds: [48, 48, 400, 40]\n'
                '  content:\n    text: hi\n    fontSize: 18\n    align: right\n')
            report = validate.audit_project(root)
            self.assertTrue(report['valid'])
            self.assertEqual(report['advisoryCounts'].get('non-canonical-align'), 1)


class CaptionNoiseTests(unittest.TestCase):
    def page(self, caption):
        return {'elements': [{'elementId': 'cap', 'elementType': 'text', 'bounds': [0, 0, 300, 20],
                              'content': {'text': caption}}]}

    def test_retrieval_date_licence_and_stock_captions_block(self):
        for caption in ('图：常州文旅（2026-09-09 检索）',
                        '摄影：某人（许可未知）',
                        'CQC 2024 年报道配图（资料图，不代表本单位参与）',
                        '检索日期：2026-09-09'):
            issues = validate.caption_noise_issues(self.page(caption), 1, 'pages/01.page')
            self.assertEqual([i['code'] for i in issues], ['source-caption-noise'], caption)

    def test_a_real_credit_line_passes(self):
        for caption in ('图：国家大剧院官网 · 2020',
                        '数据来源：国家统计局 2025 年年鉴',
                        '摄影：李明 / 常州市档案馆'):
            self.assertEqual(validate.caption_noise_issues(self.page(caption), 1, 'pages/01.page'), [], caption)


    def test_licence_codes_on_a_content_page_block(self):
        for caption in ('图：国家大剧院官网 · 2020 · CC BY-SA 4.0',
                        '摄影：李明（CC0）',
                        'Wikimedia Commons, Public Domain',
                        '图：商丘博物馆 · 公有领域'):
            issues = validate.caption_noise_issues(self.page(caption), 1, 'pages/01.page')
            self.assertEqual([i['code'] for i in issues], ['source-caption-noise'], caption)

    def test_the_credits_page_may_carry_reuse_terms(self):
        page = self.page('图：商丘博物馆 · 2021 · CC BY-SA 4.0')
        page['elements'].insert(0, {'elementId': 'title', 'elementType': 'text', 'bounds': [0, 0, 600, 40],
                                    'content': {'text': '图片来源'}})
        self.assertEqual(validate.caption_noise_issues(page, 9, 'pages/09.page'), [])
        typed = self.page('Wikimedia Commons · CC BY 4.0'); typed['pageType'] = 'credits'
        self.assertEqual(validate.caption_noise_issues(typed, 9, 'pages/09.page'), [])


class ImageCaptionTests(unittest.TestCase):
    """Measured on the 20-page batch: 173 content images, 131 captioned, 37 edge-bleed decoration,
    19 inset pictures with nothing telling the audience what they are looking at. Captions sit
    0-44px under the picture (p50 8, p90 20), so a 48px band with 40% horizontal overlap finds them.
    """

    def page(self, image_bounds, caption_bounds=None):
        elements = [{'elementId': 'pic', 'elementType': 'image', 'bounds': list(image_bounds),
                     'src': 'media/a.jpg'}]
        if caption_bounds:
            elements.append({'elementId': 'cap', 'elementType': 'text', 'bounds': list(caption_bounds),
                             'content': {'text': '图：常州市档案馆 · 2015'}})
        return {'elements': elements}

    def test_an_inset_picture_without_a_caption_is_reported(self):
        issues = validate.image_caption_issues(self.page([620, 150, 284, 200]), 1, 'pages/01.page')
        self.assertEqual([i['code'] for i in issues], ['image-missing-caption'])

    def test_a_caption_under_the_picture_satisfies_it(self):
        issues = validate.image_caption_issues(
            self.page([620, 150, 284, 200], [620, 358, 284, 18]), 1, 'pages/01.page')
        self.assertEqual(issues, [])

    def test_a_far_away_text_is_not_the_caption(self):
        issues = validate.image_caption_issues(
            self.page([620, 150, 284, 200], [620, 430, 284, 18]), 1, 'pages/01.page')
        self.assertEqual([i['code'] for i in issues], ['image-missing-caption'])

    def test_a_picture_that_ends_at_the_page_edge_has_nowhere_to_put_one(self):
        # A band photo running to the bottom of the slide leaves no room under it; asking for a
        # caption there asks for one drawn off the page.
        issues = validate.image_caption_issues(self.page([0, 240, 960, 300]), 1, 'pages/01.page')
        self.assertEqual(issues, [])

    def test_full_height_edge_bleed_art_needs_no_caption(self):
        for bounds in ([540, 0, 420, 540], [0, 0, 470, 540]):
            self.assertEqual(validate.image_caption_issues(self.page(bounds), 1, 'pages/01.page'), [],
                             bounds)


class CaptionLinkTests(unittest.TestCase):
    """The caption explains the picture; the page's 来源 line carries the clickable citation."""

    def page(self, caption_text):
        return {'elements': [
            {'elementId': 'pic', 'elementType': 'image', 'bounds': [620, 150, 284, 200], 'src': 'media/a.jpg'},
            {'elementId': 'cap', 'elementType': 'text', 'bounds': [620, 358, 284, 18],
             'content': {'text': caption_text}},
            {'elementId': 'src', 'elementType': 'text', 'bounds': [48, 500, 860, 20],
             'content': {'text': '来源：<a href="https://example.org/a">河南日报</a>，2024'}},
        ]}

    def test_a_link_in_the_caption_blocks(self):
        issues = validate.caption_link_issues(self.page('商丘古城城墙 · <a href="https://x.cn/a">网易新闻</a>'), 1, 'p')
        self.assertEqual([i['code'] for i in issues], ['caption-hyperlink'])
        self.assertEqual(issues[0]['elementId'], 'cap')

    def test_a_plain_caption_passes_and_the_source_line_keeps_its_link(self):
        page = self.page('商丘古城城墙 · 网易新闻，2024')
        self.assertEqual(validate.caption_link_issues(page, 1, 'p'), [])
        self.assertEqual(validate.unlinked_source_issues(page, 1, 'p'), [])

    def test_a_source_line_under_a_picture_stays_a_source_line(self):
        # The page footnote often lands inside a picture's caption band; it keeps its link and is
        # still advised when it has none, rather than being read as that picture's caption.
        page = self.page('来源：商丘市文旅局')
        self.assertEqual(validate.caption_link_issues(page, 1, 'p'), [])
        advised = validate.unlinked_source_issues(page, 1, 'p', (960.0, 540.0))
        self.assertEqual([i['elementId'] for i in advised], ['cap'])

    def test_a_linked_footnote_in_the_caption_band_is_not_a_caption_link(self):
        page = self.page('来源：<a href="https://example.org/b">商丘日报</a>，2024')
        self.assertEqual(validate.caption_link_issues(page, 1, 'p'), [])


class SourceLinkTests(unittest.TestCase):
    """56 source lines in the batch name a source and none of them is clickable."""

    def page(self, text):
        return {'elements': [{'elementId': 's', 'elementType': 'text', 'bounds': [0, 500, 900, 20],
                              'content': {'text': text}}]}

    def test_a_named_source_without_a_link_is_advised(self):
        issues = validate.unlinked_source_issues(self.page('来源：常州市档案馆《常州三杰》，2015'), 1, 'p')
        self.assertEqual([i['code'] for i in issues], ['unlinked-source'])

    def test_a_linked_source_passes(self):
        text = '来源：<a href="https://www.mfa.gov.cn/x.shtml">外交部答问</a>，2026'
        self.assertEqual(validate.unlinked_source_issues(self.page(text), 1, 'p'), [])

    def test_ordinary_body_text_is_not_a_source_line(self):
        self.assertEqual(validate.unlinked_source_issues(self.page('古典舞的来源可以追到戏曲'), 1, 'p'), [])

    def test_an_unlinked_source_advises_and_does_not_block_the_deck(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / 'pages').mkdir()
            (root / 'deck.pptd').write_text('version: v2\ntitle: T\nsize: [960, 540]\npages:\n  - pages/01.page\n')
            (root / 'pages/01.page').write_text(
                'pageType: content\nelements:\n'
                '- elementId: s\n  elementType: text\n  bounds: [48, 500, 860, 20]\n'
                '  content:\n    text: 来源：常州市档案馆《常州三杰》，2015\n    fontSize: 12\n')
            report = validate.audit_project(root)
            self.assertTrue(report['valid'], report.get('issueCounts'))
            self.assertEqual(report['advisoryCounts'].get('unlinked-source'), 1)


class ImageCropTests(unittest.TestCase):
    """Measured over 187 pictures in the 20-page batch: crop factor p50 1.13, p75 1.35, p90 2.02,
    max 3.38. 36 pictures (19%) lose more than half again their frame, and 29 of those are a
    portrait photo in a landscape box — which is what cut the head off the statue on 16/P4. Decks
    that used image_pool barely show it; the ones whose author fetched pictures directly do, since
    the pool's orientation filter is the only thing that was enforcing the match.
    """

    def project(self, folder, source_size, bounds):
        from PIL import Image
        root = pathlib.Path(folder)
        (root / 'pages').mkdir()
        (root / 'media').mkdir()
        Image.new('RGB', source_size, (128, 128, 128)).save(root / 'media' / 'a.jpg')
        (root / 'deck.pptd').write_text(
            'version: v2\ntitle: T\nsize: [960, 540]\npages:\n  - pages/01.page\n')
        (root / 'pages' / '01.page').write_text(
            'pageType: content\nelements:\n'
            f'- elementId: pic\n  elementType: image\n  bounds: {list(bounds)}\n  src: "media/a.jpg"\n'
            '- elementId: cap\n  elementType: text\n  bounds: '
            f'[{bounds[0]}, {bounds[1] + bounds[3] + 8}, {bounds[2]}, 18]\n'
            '  content:\n    text: 图：某某 · 2024\n')
        return root

    def codes(self, report):
        return {i['code'] for i in report['issues']} | {a['code'] for a in report.get('advisories', [])}

    def test_a_portrait_photo_in_a_landscape_box_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, (1164, 1490), (620, 150, 308, 232))
            self.assertIn('over-cropped-image', self.codes(validate.audit_project(root)))

    def test_a_picture_that_matches_its_frame_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, (1600, 1200), (620, 150, 308, 232))
            self.assertNotIn('over-cropped-image', self.codes(validate.audit_project(root)))


class CropExceptionTests(unittest.TestCase):
    def test_a_page_background_may_record_that_its_crop_is_intended(self):
        """A picture filling the whole slide crops by definition; that is a judgement call.

        Shrinking the frame to the source aspect — the remedy for an inset photo — would stop the
        background covering the page, so this one is recorded and reviewed, not reshaped.
        """
        self.assertIn('over-cropped-image', validate.ACKNOWLEDGEABLE_CODES)


class ExceptionTests(unittest.TestCase):
    def project(self, folder, page_body, exceptions=None):
        import json as _json
        root = pathlib.Path(folder)
        (root / 'pages').mkdir()
        (root / 'deck.pptd').write_text('version: v2\ntitle: T\nsize: [960, 540]\npages:\n  - pages/01.page\n')
        (root / 'pages/01.page').write_text(page_body)
        if exceptions is not None:
            (root / 'validate-exceptions.json').write_text(
                _json.dumps({'exceptions': exceptions}, ensure_ascii=False))
        return root

    CARD_WALL = ('pageType: content\nelements:\n' + ''.join(
        f'- elementId: c{i}\n  elementType: shape\n  shapeName: roundRect\n'
        f'  bounds: [{48 + i * 220}, 140, 200, 150]\n  fill: {{type: solid, color: "#EEEEEE"}}\n'
        for i in range(4)))

    def test_recorded_exception_moves_the_finding_to_advice(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, self.CARD_WALL, [
                {'code': 'anti-slop-card-layout', 'pageNumber': 1,
                 'reason': '2x2 feature grid confirmed on the render; not a card wall'}])
            report = validate.audit_project(root)
            self.assertTrue(report['valid'])
            self.assertEqual(report['acknowledged'], ['anti-slop-card-layout'])
            accepted = [a for a in report['advisories'] if a['code'] == 'anti-slop-card-layout']
            self.assertIn('confirmed on the render', accepted[0]['acknowledged'])

    def test_without_the_record_it_still_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            report = validate.audit_project(self.project(folder, self.CARD_WALL))
            self.assertFalse(report['valid'])
            self.assertEqual(report['issueCounts'].get('anti-slop-card-layout'), 1)

    def test_an_exception_that_no_longer_matches_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, 'pageType: content\nelements: []\n', [
                {'code': 'orphan-last-line', 'reason': 'fixed upstream long ago'}])
            report = validate.audit_project(root)
            self.assertFalse(report['valid'])
            self.assertEqual(report['issueCounts'].get('stale-exception'), 1)

    def test_a_defect_cannot_be_acknowledged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, 'pageType: content\nelements: []\n', [
                {'code': 'empty-body-band', 'reason': 'we like holes'}])
            report = validate.audit_project(root)
            self.assertFalse(report['valid'])
            self.assertEqual(report['issueCounts'].get('invalid-exception'), 1)

    def test_an_exception_without_a_reason_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, self.CARD_WALL, [{'code': 'anti-slop-card-layout'}])
            report = validate.audit_project(root)
            self.assertFalse(report['valid'])
            self.assertEqual(report['issueCounts'].get('invalid-exception'), 1)
            self.assertEqual(report['issueCounts'].get('anti-slop-card-layout'), 1)

    def test_a_keyword_phrase_flag_can_be_acknowledged(self):
        page = ('pageType: content\nelements:\n- elementId: t\n  elementType: text\n'
                '  bounds: [48, 48, 400, 40]\n  content:\n    text: 商丘古城四面环护城河\n')
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, page, [
                {'code': 'anti-slop-phrase', 'pageNumber': 1,
                 'reason': '护城河是这座古城的真实地理要素，不是商业套话'}])
            report = validate.audit_project(root)
            self.assertTrue(report['valid'])
            self.assertEqual(report['acknowledged'], ['anti-slop-phrase'])
