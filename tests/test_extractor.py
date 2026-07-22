import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from learning_material_url_tester.extractor import extract_urls_from_file


class ExtractorTests(unittest.TestCase):
    def test_extract_urls_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.md"
            file_path.write_text("Read https://example.com and http://example.org/docs", encoding="utf-8")

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com", "http://example.org/docs"])

    def test_extract_urls_trims_only_unmatched_closing_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.md"
            file_path.write_text(
                "One https://example.com/path(a) and two https://example.com/path(b)).",
                encoding="utf-8",
            )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/path(a)", "https://example.com/path(b)"])

    def test_extract_urls_from_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.docx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:t>Visit https://example.com/doc</w:t><w:t>and https://example.com/doc</w:t>',
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/doc"])

    def test_extract_urls_from_docx_with_distinct_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.docx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:t>https://example.com/one?x=(a)&q=1</w:t><w:t>https://example.com/two?y=[b]&z=2</w:t>',
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(
                urls,
                ["https://example.com/one?x=(a)&q=1", "https://example.com/two?y=[b]&z=2"],
            )

    def test_extract_urls_from_pptx_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "slides.pptx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "ppt/slides/_rels/slide1.xml.rels",
                    '<Relationship Target="https://example.com/slides" />',
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/slides"])
