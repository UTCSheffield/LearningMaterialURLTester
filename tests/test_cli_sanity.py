from __future__ import annotations

import unittest

from learning_material_url_tester.checker import UrlCheckResult
from learning_material_url_tester.cli import _run_senso_startup_sanity_check


class _FakeBrowserChecker:
    def __init__(self, result: UrlCheckResult) -> None:
        self._result = result
        self.checked_urls: list[str] = []

    def check(self, url: str) -> UrlCheckResult:
        self.checked_urls.append(url)
        return self._result


class SensoStartupSanityCheckTests(unittest.TestCase):
    def test_sanity_check_passes_when_facebook_is_blocked(self) -> None:
        browser = _FakeBrowserChecker(
            UrlCheckResult(
                url="https://facebook.com",
                blocked_by_senso=True,
                status_code=200,
                final_url="https://proxy.local/senso/blocked",
                error=None,
                block_reason="Social Media",
            )
        )

        ok = _run_senso_startup_sanity_check(browser)

        self.assertTrue(ok)
        self.assertEqual(browser.checked_urls, ["facebook.com"])

    def test_sanity_check_fails_when_facebook_is_not_blocked(self) -> None:
        browser = _FakeBrowserChecker(
            UrlCheckResult(
                url="https://facebook.com",
                blocked_by_senso=False,
                status_code=200,
                final_url="https://facebook.com",
                error=None,
                block_reason=None,
            )
        )

        ok = _run_senso_startup_sanity_check(browser)

        self.assertFalse(ok)
        self.assertEqual(browser.checked_urls, ["facebook.com"])
