"""All install-time PWA resources must exist and return successful local HTTP."""
import json
from pathlib import Path
import re
import unittest
import urllib.request

from tests import test_app as support

ROOT = Path(__file__).resolve().parents[1]


class PwaShellResourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.LocalAPITest.setUpClass()
        cls.addClassCleanup(support.LocalAPITest.tearDownClass)
        cls.base = support.LocalAPITest.base

    def test_all_shell_manifest_and_favicon_urls_respond_200(self):
        sw = (ROOT / 'static/sw.js').read_text(encoding='utf-8')
        match = re.search(r'const SHELL = (\[[^;]+\]);', sw)
        self.assertIsNotNone(match)
        shell = json.loads(match.group(1))
        manifest = json.loads((ROOT / 'static/manifest.webmanifest').read_text(encoding='utf-8'))
        index = (ROOT / 'static/index.html').read_text(encoding='utf-8')
        favicon = re.search(r'<link rel="icon" href="([^"]+)" type="image/png">', index)
        self.assertIsNotNone(favicon)
        icons = [item['src'] for item in manifest['icons']]
        self.assertEqual(set(icons), {'/static/icon-192.png', '/static/icon-512.png'})
        self.assertIn(favicon.group(1), icons)
        self.assertIn('/static/app.js', shell)
        self.assertIn('/static/styles.css', shell)
        self.assertIn('/static/manifest.webmanifest', shell)
        self.assertTrue(set(icons).issubset(shell))
        for path in sorted(set(shell + icons + [favicon.group(1), manifest['start_url']])):
            with self.subTest(path=path):
                self.assertTrue(path.startswith('/'))
                with urllib.request.urlopen(self.base + path, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    body = response.read()
                    self.assertTrue(body)
                    if path.endswith('.png'):
                        self.assertEqual(response.headers.get_content_type(), 'image/png')
                        self.assertTrue(body.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertNotIn('/static/icon.svg', sw + index + json.dumps(manifest))


if __name__ == '__main__':
    unittest.main()
