#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：image_search 模块

测试覆盖：
1. _fetch_with_url：成功路径、异常吞掉、字节守卫（DEFAULT_MIN_BYTES ~ MAX_BYTES）、禁用图源直接拒绝。
2. sniff_size：PNG / GIF / BMP / WebP (VP8/VP8L/VP8X) / JPEG 二进制尺寸探测。
3. canonical_url：参数过滤、bcebos 水印剥离、去重逻辑。
4. slots 行级提取与 patch_src 改写：保留 YAML 格式与注释、bounds 比例判断。
5. judge_image / VLM 解析：JSON 提取、复合分计算、硬拒逻辑。
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
    def test_request_error_gives_up(self, mock_req):
        mock_req.side_effect = Exception("HTTP 400 Bad Request")
        url = "https://example.com/photo.jpg"
        self.assertEqual(pool._fetch_with_url(url), (None, url))

    @patch("pool._req")
    def test_byte_guard_rejects_small_payload(self, mock_req):
        mock_req.return_value = b"tiny"
        url = "https://example.com/photo.jpg"
        self.assertEqual(pool._fetch_with_url(url), (None, url))

    @patch("pool._req")
    def test_blocked_source_is_never_requested(self, mock_req):
        url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg"
        self.assertEqual(pool._fetch_with_url(url), (None, url))
        mock_req.assert_not_called()


class TestQueryLanguage(unittest.TestCase):
    def test_cjk_detection(self):
        self.assertTrue(slots.is_cjk_query("电影院 观众席 背影"))
        self.assertTrue(slots.is_cjk_query("2026 年 风电场"))
        self.assertFalse(slots.is_cjk_query("dark cinema auditorium"))
        self.assertFalse(slots.is_cjk_query(""))


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



class TestAcquisitionFallback(unittest.TestCase):
    def test_auto_falls_back_after_download_failure(self):
        candidate = lambda backend: {"url": f"https://{backend}.example/image.png", "backend": backend}
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1000, 600) + b"\x00" * 100
        with patch.dict(pool.BACKENDS, {"baidu": lambda *a, **k: [candidate("baidu")],
                                       "openverse": lambda *a, **k: [candidate("openverse")]}), \
             patch.object(pool, "AUTO_ORDER", ("baidu", "openverse")), \
             patch.object(pool, "_fetch", side_effect=lambda url: None if "baidu" in url else png):
            winner, tried = pool.acquire("test", use_vlm=False)
        self.assertIsNotNone(winner, "download failure must try the next backend")
        self.assertEqual(winner["backend"], "openverse")
        self.assertTrue(any(r.get("fate") == "fetch_fail" for r in tried))

    def test_auto_falls_back_after_filter_failure(self):
        small = {"url": "https://small.example/a.png", "width": 10, "height": 10, "backend": "baidu"}
        good = {"url": "https://good.example/a.png", "backend": "openverse"}
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1000, 600) + b"\x00" * 100
        with patch.dict(pool.BACKENDS, {"baidu": lambda *a, **k: [small], "openverse": lambda *a, **k: [good]}), \
             patch.object(pool, "AUTO_ORDER", ("baidu", "openverse")), patch.object(pool, "_fetch", return_value=png):
            winner, tried = pool.acquire("test", use_vlm=False)
        self.assertIsNotNone(winner, "filter failure must try the next backend")
        self.assertTrue(any(r.get("fate") == "too_small_meta" for r in tried))

if __name__ == "__main__":
    unittest.main()
