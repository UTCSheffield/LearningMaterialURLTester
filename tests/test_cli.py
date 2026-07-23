from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_material_url_tester.checker import UrlCheckResult
from learning_material_url_tester.cli import _make_csv_row, _read_urls_from_csv, main


def _make_result(url: str, blocked: bool = False, reason: str | None = None) -> UrlCheckResult:
    return UrlCheckResult(
        url=url,
        blocked_by_senso=blocked,
        status_code=200,
        final_url=url,
        error=None,
        block_reason=reason,
    )


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
    def test_read_urls_from_csv_returns_url_to_files_map(self) -> None:
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
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/two",
                    "error": "",
                    "block_reason": "",
                    "source_files": "",
                })

            result = _read_urls_from_csv(csv_path)

        self.assertIn("https://example.com/one", result)
        self.assertIn("https://example.com/two", result)
        self.assertEqual(result["https://example.com/one"], ["/a/file.md", "/b/file.docx"])
        self.assertEqual(result["https://example.com/two"], [])

    def test_read_urls_from_csv_skips_already_ok_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/fine",
                    "blocked_by_senso": "False",
                    "status_code": "200",
                    "final_url": "https://example.com/fine",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/a/file.md",
                })
                writer.writerow({
                    "url": "https://example.com/blocked",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/blocked",
                    "error": "",
                    "block_reason": "Gaming",
                    "source_files": "",
                })

            result = _read_urls_from_csv(csv_path)

        self.assertNotIn("https://example.com/fine", result)
        self.assertIn("https://example.com/blocked", result)

    def test_read_urls_from_csv_skips_blank_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["url", "source_files"])
                writer.writeheader()
                writer.writerow({"url": "", "source_files": ""})
                writer.writerow({"url": "https://example.com/ok", "source_files": ""})

            result = _read_urls_from_csv(csv_path)

        self.assertEqual(list(result.keys()), ["https://example.com/ok"])


class MainRetestTests(unittest.TestCase):
    def test_main_from_csv_rechecks_urls(self) -> None:
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

            fake_result = _make_result("https://example.com/retest")

            with patch("learning_material_url_tester.cli.check_url", return_value=fake_result):
                with patch("sys.argv", ["prog", "--from-csv", str(csv_input), "--output", str(csv_output)]):
                    result = main()

            self.assertEqual(result, 0)
            rows = list(csv.DictReader(csv_output.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com/retest")

    def test_main_from_csv_skips_ok_and_creates_side_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_input = Path(tmp) / "previous.csv"
            csv_output = Path(tmp) / "new.csv"

            with csv_input.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"],
                )
                writer.writeheader()
                # This one was fine — should be skipped
                writer.writerow({
                    "url": "https://example.com/good",
                    "blocked_by_senso": "False",
                    "status_code": "200",
                    "final_url": "https://example.com/good",
                    "error": "",
                    "block_reason": "",
                    "source_files": "/a/lesson.md",
                })
                # This one was blocked — should be rechecked
                writer.writerow({
                    "url": "https://example.com/blocked",
                    "blocked_by_senso": "True",
                    "status_code": "200",
                    "final_url": "https://example.com/blocked",
                    "error": "",
                    "block_reason": "Gaming",
                    "source_files": "/a/lesson.md",
                })

            fake_result = _make_result("https://example.com/blocked")

            with patch("learning_material_url_tester.cli.check_url", return_value=fake_result):
                with patch("sys.argv", ["prog", "--from-csv", str(csv_input), "--output", str(csv_output)]):
                    result = main()

            self.assertEqual(result, 0)
            # Only the blocked URL is rechecked
            rows = list(csv.DictReader(csv_output.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com/blocked")
            # Side files are created
            self.assertTrue((Path(tmp) / "new_blocked.csv").exists())
            self.assertTrue((Path(tmp) / "new_errors.csv").exists())
