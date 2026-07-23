from io import BytesIO
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from learning_material_url_tester.checker import check_url


class _FakeResponse:
    def __init__(self, status: int, final_url: str, body: str) -> None:
        self.status = status
        self._final_url = final_url
        self._body = body.encode("utf-8")

    def geturl(self) -> str:
        return self._final_url

    def read(self, _limit: int | None = None) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class CheckerTests(unittest.TestCase):
    def test_check_url_flags_senso_block_page(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="https://proxy.local/senso/blocked",
                body="This site is blocked by Senso policy.",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://example.com", timeout=5)

        self.assertTrue(result.blocked_by_senso)
        self.assertEqual(result.status_code, 200)

    def test_check_url_extracts_block_reason_category(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="https://proxy.local/senso/blocked",
                body="This site is blocked by Senso. Category: Social Media",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://example.com", timeout=5)

        self.assertTrue(result.blocked_by_senso)
        self.assertEqual(result.block_reason, "Social Media")

    def test_check_url_extracts_block_reason_group(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="https://proxy.local/senso/blocked",
                body="Senso blocked this. Group: Gaming\nContact your admin.",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://example.com", timeout=5)

        self.assertTrue(result.blocked_by_senso)
        self.assertEqual(result.block_reason, "Gaming")

    def test_check_url_block_reason_none_when_not_blocked(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="https://example.com",
                body="<html><body>Hello world</body></html>",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://example.com", timeout=5)

        self.assertFalse(result.blocked_by_senso)
        self.assertIsNone(result.block_reason)

    def test_check_url_prepends_https_for_bare_www_url(self) -> None:
        seen_urls: list[str] = []

        def fake_urlopen(request, timeout: int = 15):
            seen_urls.append(request.full_url)
            return _FakeResponse(
                status=200,
                final_url="https://www.example.com",
                body="<html><body>Hello</body></html>",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("www.example.com", timeout=5)

        self.assertEqual(seen_urls[0], "https://www.example.com")
        self.assertEqual(result.url, "https://www.example.com")
        self.assertFalse(result.blocked_by_senso)

    def test_check_url_handles_http_error(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            raise HTTPError(
                url="https://example.com",
                code=451,
                msg="Unavailable For Legal Reasons",
                hdrs=None,
                fp=BytesIO(b"This site is blocked by Senso."),
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://example.com")

        self.assertTrue(result.blocked_by_senso)
        self.assertEqual(result.status_code, 451)

    def test_check_url_detects_banned_phrase_without_senso_word(self) -> None:
        """Block pages that say 'Website Address is banned' but not 'senso' should still be detected."""
        def fake_urlopen(_request, timeout: int = 15):
            raise HTTPError(
                url="http://cool-timer.en.uptodown.com",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=BytesIO(
                    b"Website Address is banned\n"
                    b"This has been blocked by the following library: Software Download"
                ),
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("http://cool-timer.en.uptodown.com")

        self.assertTrue(result.blocked_by_senso)
        self.assertEqual(result.block_reason, "Software Download")

    def test_check_url_detects_this_website_has_been_banned_phrase(self) -> None:
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="http://example.com",
                body="This website has been banned by your network administrator.",
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("http://example.com", timeout=5)

        self.assertTrue(result.blocked_by_senso)

    def test_check_url_not_blocked_for_page_containing_inline_block_css(self) -> None:
        """Normal pages with 'inline-block' or 'block' in CSS/HTML must not be flagged as blocked."""
        def fake_urlopen(_request, timeout: int = 15):
            return _FakeResponse(
                status=200,
                final_url="https://www.teach-ict.com/page.htm",
                body=(
                    '<html><head><title>Teach-ICT</title></head>'
                    '<body><ins style="display:inline-block;width:728px;height:90px"></ins>'
                    '<p>Learn about computer science block diagrams.</p></body></html>'
                ),
            )

        with patch("learning_material_url_tester.checker.urlopen", fake_urlopen):
            result = check_url("https://www.teach-ict.com/page.htm", timeout=5)

        self.assertFalse(result.blocked_by_senso)
