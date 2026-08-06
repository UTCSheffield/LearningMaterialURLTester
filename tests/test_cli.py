from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from learning_material_url_tester.checker import UrlCheckResult
from learning_material_url_tester.cli import _make_csv_row, _read_all_rows_from_csv, main


def _make_result(url: str, blocked: bool = False, reason: str | None = None) -> UrlCheckResult:
    return UrlCheckResult(
        url=url,
        blocked_by_senso=blocked,
        status_code=200,
        final_url=url,
        error=None,
        block_reason=reason,
    )


def _mock_browser(check_result: UrlCheckResult) -> MagicMock:
    """Return a mock BrowserChecker whose .check() returns check_result."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=None)
    ctx.check = MagicMock(return_value=check_result)
    return ctx


class CsvRowTests(unittest.TestCase):
    def test_make_csv_row_includes_block_reason(self) -> None:
        result = _make_result("https://example.com/a", blocked=True, reason="Social Media")
        url_to_files = {"https://example.com/a": ["/path/lesson.md"]}

        row = _make_csv_row(result, url_to_files)

        self.assertEqual(row["block_reason"], "Social Media")

    def test_make_csv_row_empty_block_reason_when_not_blocked(self) -> None:
        result = _make_result("https://example.com/b")
        url_to_files: dict = {}

        row = _make_csv_row(result, url_to_files)

        self.assertIsNone(row["block_reason"])

    def test_make_csv_row_joins_source_files(self) -> None:
        result = _make_result("https://example.com/x")
        url_to_files = {"https://example.com/x": ["/a/file.md", "/b/file.docx"]}

        row = _make_csv_row(result, url_to_files)

        self.assertIn("/a/file.md", row["source_files"])
        self.assertIn("/b/file.docx", row["source_files"])


class ReadCsvTests(unittest.TestCase):
    def test_read_all_rows_returns_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/one",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/one",
                    "error": "",
                    "block_reason": "Gaming",
                    "source_files": "/a/file.md|/b/file.docx",
                })
                writer.writerow({
                    "url": "https://example.com/two",
                    "blocked_by_senso": "False",
                    "status_code": "404",
                    "final_url": "",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/c/file.docx",
                })

            rows = _read_all_rows_from_csv(csv_path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://example.com/one")
        self.assertEqual(rows[1]["url"], "https://example.com/two")
        self.assertEqual(rows[1]["status_code"], "404")

    def test_read_urls_from_csv_skips_blank_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["url", "source_files"])
                writer.writeheader()
                writer.writerow({"url": "", "source_files": ""})
                writer.writerow({"url": "https://example.com/ok", "source_files": ""})

            rows = _read_all_rows_from_csv(csv_path)

        # Blank url row is still in the raw output; filtering happens in _recheck_from_csv
        self.assertEqual(len(rows), 2)


class MainRetestTests(unittest.TestCase):
    def test_main_from_csv_rechecks_blocked_url(self) -> None:
        """Blocked URL is rechecked; output contains the fresh result."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_input = Path(tmp) / "previous.csv"
            csv_output = Path(tmp) / "new.csv"

            with csv_input.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/retest",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/retest",
                    "error": "",
                    "block_reason": "Social Media",
                    "source_files": "/a/lesson.md",
                })

            # Simulate the block being lifted
            fake_result = _make_result("https://example.com/retest", blocked=False)
            mock_ctx = _mock_browser(fake_result)

            with patch("learning_material_url_tester.cli.BrowserChecker", return_value=mock_ctx):
                with patch("sys.argv", ["prog", "--from-csv", str(csv_input), "--output", str(csv_output)]):
                    result = main()

            self.assertEqual(result, 0)
            rows = list(csv.DictReader(csv_output.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com/retest")
            self.assertEqual(rows[0]["blocked_by_senso"], "False")

    def test_main_from_csv_preserves_non_blocked_rows(self) -> None:
        """OK and error rows are preserved unchanged; only blocked rows are rechecked."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_input = Path(tmp) / "previous.csv"
            csv_output = Path(tmp) / "new.csv"

            with csv_input.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                # Fine URL — must be preserved as-is
                writer.writerow({
                    "url": "https://example.com/good",
                    "blocked_by_senso": "False",
                    "status_code": "200",
                    "final_url": "https://example.com/good",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/a/lesson.md",
                })
                # 404 URL — must be preserved as-is
                writer.writerow({
                    "url": "https://example.com/missing",
                    "blocked_by_senso": "False",
                    "status_code": "404",
                    "final_url": "",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/a/lesson.md",
                })
                # Blocked URL — must be rechecked
                writer.writerow({
                    "url": "https://example.com/blocked",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/blocked",
                    "error": "",
                    "block_reason": "Gaming",
                    "source_files": "/a/lesson.md",
                })

            fake_result = _make_result("https://example.com/blocked", blocked=False)
            mock_ctx = _mock_browser(fake_result)

            with patch("learning_material_url_tester.cli.BrowserChecker", return_value=mock_ctx):
                with patch("sys.argv", ["prog", "--from-csv", str(csv_input), "--output", str(csv_output)]):
                    result = main()

            self.assertEqual(result, 0)
            rows = list(csv.DictReader(csv_output.open(encoding="utf-8")))
            # All 3 rows preserved
            self.assertEqual(len(rows), 3)
            urls = [r["url"] for r in rows]
            self.assertIn("https://example.com/good", urls)
            self.assertIn("https://example.com/missing", urls)
            self.assertIn("https://example.com/blocked", urls)
            # 404 row unchanged
            missing_row = next(r for r in rows if r["url"] == "https://example.com/missing")
            self.assertEqual(missing_row["status_code"], "404")
            # Blocked row updated
            blocked_row = next(r for r in rows if r["url"] == "https://example.com/blocked")
            self.assertEqual(blocked_row["blocked_by_senso"], "False")
            # Side files created
            self.assertTrue((Path(tmp) / "new_blocked.csv").exists())
            self.assertTrue((Path(tmp) / "new_errors.csv").exists())

    def test_main_from_csv_recheck_all_retests_every_url(self) -> None:
        """--recheck-all rechecks every row, not just blocked ones."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_input = Path(tmp) / "previous.csv"
            csv_output = Path(tmp) / "new.csv"

            with csv_input.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/good",
                    "blocked_by_senso": "False",
                    "status_code": "200",
                    "final_url": "https://example.com/good",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/a/lesson.md",
                })
                writer.writerow({
                    "url": "https://example.com/blocked",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/blocked",
                    "error": "",
                    "block_reason": "Gaming",
                    "source_files": "/a/lesson.md",
                })

            checked_urls: list[str] = []

            def fake_check(url: str) -> UrlCheckResult:
                checked_urls.append(url)
                return _make_result(url, blocked=False)

            mock_ctx = _mock_browser(_make_result("x"))
            mock_ctx.check = fake_check

            with patch("learning_material_url_tester.cli.BrowserChecker", return_value=mock_ctx):
                with patch("sys.argv", ["prog", "--from-csv", str(csv_input), "--output", str(csv_output), "--recheck-all"]):
                    result = main()

            self.assertEqual(result, 0)
            # Both URLs were checked
            self.assertIn("https://example.com/good", checked_urls)
            self.assertIn("https://example.com/blocked", checked_urls)
            self.assertEqual(len(checked_urls), 2)
