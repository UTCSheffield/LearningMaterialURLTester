import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from learning_material_url_tester.extractor import extract_urls_from_file


def _make_minimal_pdf(text: bytes) -> bytes:
    """Build a minimal but valid single-page PDF containing *text* as plain ASCII."""
    stream = b"BT /F1 12 Tf 50 700 Td (" + text + b") Tj ET"
    stream_len = len(stream)
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(stream_len).encode() + b" >>\nstream\n"
        + stream + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    )
    xref_offset = len(body)
    xref = (
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"0000000999 00000 n \n"
    )
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    )
    return body + xref + trailer


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

    def test_extract_docx_trims_unmatched_closing_bracket(self) -> None:
        """Trailing ) from docx XML (e.g. https://www.ocr.org.uk) must be stripped."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.docx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    "<w:t>See https://www.ocr.org.uk) for details</w:t>",
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://www.ocr.org.uk"])

    def test_extract_bare_www_url_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.md"
            file_path.write_text("Visit www.example.com for more info.", encoding="utf-8")

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["www.example.com"])

    def test_extract_mixed_bare_and_https_urls_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.md"
            file_path.write_text(
                "See www.example.com/docs or https://example.org/api",
                encoding="utf-8",
            )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["www.example.com/docs", "https://example.org/api"])

    def test_extract_bare_www_url_from_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.docx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    "<w:t>Visit www.example.com/page</w:t>",
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["www.example.com/page"])

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

    def test_extract_urls_from_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "spec.pdf"
            file_path.write_bytes(_make_minimal_pdf(b"Visit https://example.com/pdf and www.example.org/page"))

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/pdf", "www.example.org/page"])

    def test_extract_urls_from_pdf_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "spec.pdf"
            file_path.write_bytes(
                _make_minimal_pdf(b"https://example.com/dup https://example.com/dup https://example.com/other")
            )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/dup", "https://example.com/other"])

    def test_extract_urls_from_corrupt_pdf_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "corrupt.pdf"
            file_path.write_bytes(b"this is not a pdf")

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, [])

    def test_skips_microsoft_schema_urls_in_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.md"
            file_path.write_text(
                "Schema https://schemas.microsoft.com/office/2006/metadata and https://example.com/real",
                encoding="utf-8",
            )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/real"])

    def test_skips_microsoft_schema_urls_in_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "lesson.docx"
            with ZipFile(file_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:t>https://schemas.microsoft.com/office/word</w:t>'
                    '<w:t>https://example.com/real</w:t>',
                )

            urls = extract_urls_from_file(file_path)

            self.assertEqual(urls, ["https://example.com/real"])
