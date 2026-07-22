from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile


URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+")
TRAILING_PUNCTUATION = ".,;:!?>'\""
SUPPORTED_SUFFIXES = {".md", ".markdown", ".docx", ".docm", ".pptx", ".pptm"}


@dataclass(frozen=True)
class UrlSource:
    file_path: str
    url: str


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _trim_trailing_punctuation(url: str) -> str:
    trimmed = url.rstrip(TRAILING_PUNCTUATION)
    while trimmed.endswith(")") and trimmed.count("(") < trimmed.count(")"):
        trimmed = trimmed[:-1]
    while trimmed.endswith("]") and trimmed.count("[") < trimmed.count("]"):
        trimmed = trimmed[:-1]
    return trimmed


def _extract_urls_from_text(text: str) -> list[str]:
    cleaned_urls = [_trim_trailing_punctuation(url) for url in URL_PATTERN.findall(text)]
    return _dedupe_preserve_order(cleaned_urls)


def _extract_urls_from_ooxml(path: Path) -> list[str]:
    urls: list[str] = []
    try:
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                try:
                    content = archive.read(name).decode("utf-8", errors="ignore")
                except KeyError:
                    continue
                urls.extend(URL_PATTERN.findall(content))
    except (BadZipFile, OSError):
        return []
    return _dedupe_preserve_order(urls)


def extract_urls_from_file(path: Path) -> list[str]:
    """Extract URLs from one supported file (.md/.markdown/.docx/.docm/.pptx/.pptm)."""
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        return _extract_urls_from_text(text)
    if suffix in {".docx", ".docm", ".pptx", ".pptm"}:
        return _extract_urls_from_ooxml(path)
    return []


def discover_supported_files(root: Path) -> list[Path]:
    """Discover supported file types recursively under a root folder."""
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]


def extract_url_sources(roots: list[Path]) -> list[UrlSource]:
    """Extract URL + source-file pairs from all supported files under all roots."""
    sources: list[UrlSource] = []
    for root in roots:
        for file_path in discover_supported_files(root):
            for url in extract_urls_from_file(file_path):
                sources.append(UrlSource(file_path=str(file_path.resolve()), url=url))
    return sources
