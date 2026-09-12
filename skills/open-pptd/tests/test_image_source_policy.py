"""The source guard: off by default on this branch, and still correct wherever it is armed.

The restriction belongs to the 360 intranet version. These tests arm it explicitly so the
machinery — host matching, downloads, redirects, landing pages, retained caches — stays covered
and can be switched back on with confidence.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / 'image_search')]
import image_source_policy as policy
import pool
import search_images
import export_online


ARMED = ('wikimedia.org', 'wikipedia.org', 'w.wiki')


class DisarmedByDefaultTests(unittest.TestCase):
    """What this branch actually ships: nothing listed, so nothing is refused."""

    def test_the_shipped_list_is_empty(self):
        self.assertEqual(policy.BLOCKED_HOSTS, (),
                         'this branch ships the guard disarmed; arm it by listing a host')

    def test_a_formerly_blocked_source_passes(self):
        self.assertFalse(policy.blocked_source('https://upload.wikimedia.org/a.jpg'))
        self.assertFalse(policy.blocked_record(
            {'backend': 'openverse', 'landing': 'https://commons.wikimedia.org/wiki/File:P.jpg'}))


class ImageSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        armed = patch.object(policy, 'BLOCKED_HOSTS', ARMED)
        armed.start()
        self.addCleanup(armed.stop)

    def test_exact_hosts_and_subdomains_without_false_positive(self):
        for url in ['https://upload.wikimedia.org/a.jpg', 'https://COMMONS.WIKIMEDIA.ORG./a',
                    'https://en.wikipedia.org/a', 'https://w.wiki/abcd']:
            self.assertTrue(policy.blocked_source(url))
        self.assertFalse(policy.blocked_source('https://wikimedia.org.example.com/a.jpg'))
        self.assertFalse(policy.blocked_source('https://example.com/a?topic=wikimedia.org'))

    def test_direct_download_rejected_before_network(self):
        with patch('urllib.request.build_opener') as opener:
            with self.assertRaises(ValueError):
                policy.open_source('https://upload.wikimedia.org/a.jpg', timeout=1)
            opener.assert_not_called()

    def test_redirect_rejected_before_following(self):
        handler = policy.SourceRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(urllib.request.Request('https://example.com/a'), Mock(),
                                     302, 'Found', {}, 'https://upload.wikimedia.org/a.jpg')

    def test_explicit_backend_cannot_silently_fall_back(self):
        with patch.object(pool, '_req') as request:
            with self.assertRaises(ValueError):
                pool.acquire('photo', backend='wikimedia', use_vlm=False)
            request.assert_not_called()
        self.assertNotIn('wikimedia', pool.AUTO_ORDER)

    def test_openverse_landing_origin_is_filtered_before_download(self):
        candidate = {'url': 'https://cdn.example.com/photo.jpg', 'backend': 'openverse',
                     'landing': 'https://commons.wikimedia.org/wiki/File:Photo.jpg'}
        with patch.object(pool, 'search', return_value=[candidate]), patch.object(pool, '_fetch') as fetch:
            winner, tried = pool.acquire('photo', backend='openverse', use_vlm=False)
        self.assertIsNone(winner)
        self.assertEqual(tried[0]['fate'], 'blocked_source')
        fetch.assert_not_called()

    def test_known_wikimedia_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(search_images._read_cached_image(
                {'status': 'resolved', 'backend': 'wikimedia', 'local': 'media/photo.png'}, Path(temp)))

    def test_local_provenance_rejected_in_pipeline_and_online_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'pages').mkdir(); (root / 'media').mkdir()
            deck = root / 'deck.pptd'
            deck.write_text('title: Test\npages: [pages/01.page]\n')
            page = root / 'pages/01.page'
            page.write_text('pageType: content\nelements:\n  - elementType: image\n    elementId: pic\n    bounds: [0, 0, 100, 100]\n    src: media/photo.png\n')
            (root / 'media/photo.png').write_bytes(b'not read before source rejection')
            report = root / 'images_report.json'
            report.write_text(json.dumps({'slots': [{'local': 'media/photo.png', 'backend': 'remote',
                'source_url': 'https://upload.wikimedia.org/photo.png'}]}))
            before = page.read_bytes(), report.read_bytes()
            with self.assertRaises(ValueError):
                search_images.run(root, offline=True)
            with self.assertRaises(export_online.OnlineError):
                export_online.prepare_snapshot(deck, root / 'snapshot', 1)
            self.assertEqual(before, (page.read_bytes(), report.read_bytes()))
            self.assertFalse((root / 'snapshot').exists())


if __name__ == '__main__':
    unittest.main()
