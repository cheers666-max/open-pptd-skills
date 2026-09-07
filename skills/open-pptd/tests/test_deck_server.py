from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deck_server import start_deck_server


class DeckServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deck = self.root/'deck'
        self.deck.mkdir()
        self.viewer = self.root/'scripts/viewer.html'
        self.viewer.parent.mkdir()
        self.viewer.write_text('viewer')
        self.server, port = start_deck_server(self.viewer,self.deck)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{port}'

    def test_unicode_media_name_is_decoded_once(self):
        name = 'media/中国古典舞 空格%23.png'
        file = self.deck/name
        file.parent.mkdir()
        file.write_bytes(b'local fixture image bytes')
        with urlopen(self.base+'/deck/'+quote(name),timeout=2) as response:
            self.assertEqual(response.read(),file.read_bytes())

    def test_encoded_sibling_prefix_cannot_escape_deck(self):
        neighbor = self.root/'deck-private'
        neighbor.mkdir()
        (neighbor/'secret.txt').write_text('must stay outside')
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base+'/deck/%2e%2e/deck-private/secret.txt',timeout=2)
        self.assertEqual(caught.exception.code,403)
        caught.exception.close()

    def test_symlink_cannot_escape_scripts(self):
        outside = self.root/'private.txt'
        outside.write_text('must stay outside')
        (self.viewer.parent/'link.txt').symlink_to(outside)
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base+'/scripts/link.txt',timeout=2)
        self.assertEqual(caught.exception.code,403)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()
