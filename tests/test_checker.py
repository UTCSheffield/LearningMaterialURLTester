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
