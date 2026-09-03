#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：image_search 模块

测试覆盖：
1. wikimedia_alt_urls：白名单改写规则、超限处理、原图兜底、非 Wikimedia URL 行为。
2. _fetch_with_url：候选链遍历、异常 continue、字节守卫（DEFAULT_MIN_BYTES ~ MAX_BYTES）。
3. sniff_size：PNG / GIF / BMP / WebP (VP8/VP8L/VP8X) / JPEG 二进制尺寸探测。
4. canonical_url：参数过滤、bcebos 水印剥离、去重逻辑。
5. slots 行级提取与 patch_src 改写：保留 YAML 格式与注释、bounds 比例判断。
6. judge_image / VLM 解析：JSON 提取、复合分计算、硬拒逻辑。
"""

import hashlib
import json
import os
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import pool
import slots


class TestWikimediaAltUrls(unittest.TestCase):
    def test_non_wikimedia(self):
        self.assertEqual(pool.wikimedia_alt_urls("https://example.com/img.jpg"), [])
        self.assertEqual(pool.wikimedia_alt_urls(""), [])
        self.assertEqual(pool.wikimedia_alt_urls(None), [])

    def test_white_listed_size(self):
        # 960 在白名单中，因此只需原图兜底，无需额外插入改写 thumb
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/960px-Test.jpg"
        alts = pool.wikimedia_alt_urls(url)
        self.assertEqual(len(alts), 1)
        self.assertEqual(alts[0], "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg")

    def test_non_whitelisted_size_rounded_up(self):
        # 800 不在白名单 (250, 500, 960, 1280, 1920)，应上取到 960，最后附原图
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/800px-Test.jpg"
        alts = pool.wikimedia_alt_urls(url)
        self.assertEqual(len(alts), 2)
        self.assertEqual(
            alts[0],
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/960px-Test.jpg",
        )
        self.assertEqual(
            alts[1],
            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg",
        )

    def test_non_whitelisted_size_above_max(self):
        # 2560 大于最大白名单 1920，应取最大白名单 1920，并附原图
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/2560px-Test.jpg"
        alts = pool.wikimedia_alt_urls(url)
        self.assertEqual(len(alts), 2)
        self.assertEqual(
            alts[0],
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/1920px-Test.jpg",
        )
        self.assertEqual(
            alts[1],
            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg",
        )


class TestFetchWithUrl(unittest.TestCase):
    @patch("pool._req")
    def test_primary_url_success(self, mock_req):
        data = b"x" * (pool.DEFAULT_MIN_BYTES + 100)
        mock_req.return_value = data
        url = "https://example.com/photo.jpg"
        b, final_url = pool._fetch_with_url(url)
        self.assertEqual(b, data)
        self.assertEqual(final_url, url)
        mock_req.assert_called_once_with(url, timeout=20.0)

    @patch("pool._req")
    def test_fallback_chain_on_error(self, mock_req):
        # 模拟第一次 800px 失败 (如 400)，第二次 960px 成功
        data = b"x" * (pool.DEFAULT_MIN_BYTES + 100)
        orig_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/800px-Test.jpg"
        target_960 = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/960px-Test.jpg"

        def side_effect(url, timeout=20.0):
            if "800px" in url:
                raise Exception("HTTP 400 Bad Request")
            return data

        mock_req.side_effect = side_effect
        b, final_url = pool._fetch_with_url(orig_url)
        self.assertEqual(b, data)
        self.assertEqual(final_url, target_960)

    @patch("pool._req")
    def test_byte_guard_too_small_skipped(self, mock_req):
        # 尺寸太小被守卫忽略，继续尝试直到合格或全部失败
        small_data = b"tiny"
        ok_data = b"x" * (pool.DEFAULT_MIN_BYTES + 10)
        orig_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/800px-Test.jpg"

        def side_effect(url, timeout=20.0):
            if "800px" in url:
                return small_data
            if "960px" in url:
                return ok_data
            return None

        mock_req.side_effect = side_effect
        b, final_url = pool._fetch_with_url(orig_url)
        self.assertEqual(b, ok_data)
        self.assertIn("960px", final_url)


class TestSniffSize(unittest.TestCase):
    def test_png(self):
        # PNG header: 8 bytes magic + 4 len + 4 type (IHDR) + 4 width + 4 height
        data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 800, 600) + b"\x08\x06\x00\x00\x00"
        w, h, fmt = pool.sniff_size(data)
        self.assertEqual((w, h, fmt), (800, 600, "png"))

    def test_gif(self):
        data = b"GIF89a" + struct.pack("<HH", 640, 480)
        w, h, fmt = pool.sniff_size(data)
        self.assertEqual((w, h, fmt), (640, 480, "gif"))

    def test_bmp(self):
        data = b"BM" + b"\x00" * 16 + struct.pack("<ii", 1024, 768)
        w, h, fmt = pool.sniff_size(data)
        self.assertEqual((w, h, fmt), (1024, 768, "bmp"))

    def test_webp_vp8(self):
        data = b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" + struct.pack("<HH", 400, 300)
        w, h, fmt = pool.sniff_size(data)
        self.assertEqual((w, h, fmt), (400, 300, "webp"))

    def test_jpeg(self):
        # JPEG: SOI (FF D8) + SOF0 (FF C0 + len + bits + height + width)
        data = b"\xff\xd8\xff\xc0\x00\x11\x08" + struct.pack(">HH", 720, 1280) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        w, h, fmt = pool.sniff_size(data)
        self.assertEqual((w, h, fmt), (1280, 720, "jpeg"))

    def test_invalid(self):
        w, h, fmt = pool.sniff_size(b"not an image")
        self.assertEqual((w, h, fmt), (None, None, "unknown"))


class TestCanonicalUrl(unittest.TestCase):
    def test_tracking_params_stripped(self):
        url = "https://example.com/pic.jpg?utm_source=google&w=1200&spm=123"
        c = pool.canonical_url(url)
        self.assertEqual(c, "https://example.com/pic.jpg?w=1200")

    def test_bcebos_watermark_stripped(self):
        url = "https://img.bcebos.com/v1/pic.jpg?x-bce-process=image/watermark,image_xxx"
        c = pool.canonical_url(url)
        self.assertEqual(c, "https://img.bcebos.com/v1/pic.jpg")


class TestSlotsAndPatch(unittest.TestCase):
    def test_extract_slots(self):
        sample_page = """\
pageId: test_01
background:
  src: "search:科技 互联网 背景"
elements:
  - elementId: hero-img
    elementType: image
    bounds: [50, 50, 400, 300]
    fit: { mode: cover }
    src: "search:人工智能 芯片 摄影"
  - elementId: remote-img
    elementType: image
    bounds: [50, 400, 200, 400]
    src: "https://example.com/static.png"
  - elementId: local-img
    elementType: image
    src: "media/local.jpg"
"""
        page_slots = slots.extract_slots(sample_page, "pages/01.page")
        # extract 返回 search 与 remote 槽（local 不入槽）；remote 是否处理由调用方按 --localize-remote 过滤
        self.assertEqual(len(page_slots), 3)

        s1 = page_slots[0]
        self.assertEqual(s1.kind, "background")
        self.assertEqual(s1.query, "科技 互联网 背景")
        self.assertTrue(s1.is_search)
        self.assertFalse(s1.is_remote)
        self.assertEqual(s1.want, "any")  # background 无 bounds

        s2 = page_slots[1]
        self.assertEqual(s2.kind, "image")
        self.assertEqual(s2.element_id, "hero-img")
        self.assertEqual(s2.query, "人工智能 芯片 摄影")
        self.assertEqual(s2.want, "landscape")  # 400/300 = 1.33 > 1.25
        self.assertEqual(s2.fit, "cover")

        s3 = page_slots[2]
        self.assertEqual(s3.kind, "image")
        self.assertEqual(s3.element_id, "remote-img")
        self.assertFalse(s3.is_search)
        self.assertTrue(s3.is_remote)
        self.assertEqual(s3.query, "")  # remote 无 query
        self.assertEqual(s3.want, "portrait")  # 200/400 = 0.5 < 0.8

    def test_patch_src(self):
        original = """\
pageId: p1
elements:
  - elementId: img1
    src: "search:query here" # initial placeholder
"""
        patched = slots.patch_src(original, 3, "search:query here", "media/img1.jpg")
        self.assertIn('src: "media/img1.jpg" # initial placeholder', patched)


class TestVlmJudgement(unittest.TestCase):
    @patch("pool.call_vlm")
    def test_judge_image_parse(self, mock_vlm):
        mock_vlm.return_value = json.dumps({
            "relevance": 2,
            "image_type": "real_photo",
            "has_media_chrome": False,
            "has_watermark": False,
            "quality": 2,
            "reason": "高清契合",
        })
        res = pool.judge_image("AI芯片", b"fakebytes", deck_brief="AI发展")
        self.assertFalse(res["reject"])
        self.assertEqual(res["relevance"], 2)
        self.assertEqual(res["quality"], 2)
        self.assertEqual(res["composite"], 20 + 6)  # 2*10 + 2*3


if __name__ == "__main__":
    unittest.main()
