from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .checker import UrlCheckResult, check_url
from .extractor import UrlSource, extract_url_sources

SOURCE_FILES_DELIMITER = "|"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract URLs from learning material files and check if blocked by Senso."
    )
    parser.add_argument("paths", nargs="+", help="Root folder(s) containing learning materials.")
    parser.add_argument(
        "--output",
        default="url_check_results.csv",
        help="CSV output path (default: url_check_results.csv)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="URL request timeout in seconds (default: 15)",
    )
    return parser


def _group_sources_by_url(sources: list[UrlSource]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for source in sources:
        grouped.setdefault(source.url, []).append(source.file_path)
    return grouped


def _write_csv(
    results: list[UrlCheckResult], url_to_files: dict[str, list[str]], output_path: Path
) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["url", "blocked_by_senso", "status_code", "final_url", "error", "source_files"],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "url": result.url,
                    "blocked_by_senso": result.blocked_by_senso,
                    "status_code": result.status_code,
                    "final_url": result.final_url,
                    "error": result.error,
                    "source_files": SOURCE_FILES_DELIMITER.join(
                        sorted(set(url_to_files.get(result.url, [])))
                    ),
                }
            )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    roots = [Path(p).resolve() for p in args.paths]

    sources = extract_url_sources(roots)
    if not sources:
        print("No supported files or URLs found.")
        return 0

    url_to_files = _group_sources_by_url(sources)
    unique_urls = sorted(url_to_files.keys())
    results = [check_url(url, timeout=args.timeout) for url in unique_urls]
    _write_csv(results, url_to_files, Path(args.output))

    blocked_count = sum(1 for result in results if result.blocked_by_senso)
    print(
        f"Checked {len(results)} unique URLs from {len(sources)} extracted URLs. "
        f"Blocked by Senso: {blocked_count}. Results written to {args.output}."
    )
    return 0
