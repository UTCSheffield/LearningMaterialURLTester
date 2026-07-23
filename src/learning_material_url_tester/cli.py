from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .checker import UrlCheckResult, check_url
from .extractor import UrlSource, _should_skip_url, extract_url_sources

SOURCE_FILES_DELIMITER = "|"
CSV_FIELDNAMES = ["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"]
BLOCKED_FIELDNAMES = ["url", "block_reason", "source_files"]
ERRORS_FIELDNAMES = ["url", "status_code", "error", "source_files"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract URLs from learning material files and check if blocked by Senso."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Root folder(s) containing learning materials. Not required when --from-csv is used.",
    )
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
    parser.add_argument(
        "--from-csv",
        metavar="CSV",
        help="Retest URLs from a previous results CSV instead of scanning folders.",
    )
    return parser


def _group_sources_by_url(sources: list[UrlSource]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for source in sources:
        grouped.setdefault(source.url, []).append(source.file_path)
    return grouped


def _read_urls_from_csv(csv_path: Path) -> dict[str, list[str]]:
    """Read url→source_files mapping from a previous results CSV, skipping already-OK rows."""
    url_to_files: dict[str, list[str]] = {}
    skipped_ok = 0
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("url", "").strip()
            if not url or _should_skip_url(url):
                continue
            if row.get("blocked_by_senso", "").strip().lower() == "false":
                skipped_ok += 1
                continue
            raw_files = row.get("source_files", "")
            files = [f for f in raw_files.split(SOURCE_FILES_DELIMITER) if f] if raw_files else []
            url_to_files[url] = files
    if skipped_ok:
        print(f"Skipped {skipped_ok} already-OK URL(s) from CSV.", flush=True)
    return url_to_files


def _make_csv_row(result: UrlCheckResult, url_to_files: dict[str, list[str]]) -> dict:
    return {
        "url": result.url,
        "blocked_by_senso": result.blocked_by_senso,
        "status_code": result.status_code,
        "final_url": result.final_url,
        "error": result.error,
        "block_reason": result.block_reason,
        "source_files": SOURCE_FILES_DELIMITER.join(
            sorted(set(url_to_files.get(result.url, [])))
        ),
    }


def _side_output_path(main_path: Path, suffix: str) -> Path:
    """Return e.g. url_check_results_blocked.csv from url_check_results.csv."""
    return main_path.with_stem(main_path.stem + suffix)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.from_csv:
        csv_path = Path(args.from_csv)
        if not csv_path.is_file():
            print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
            return 1
        url_to_files = _read_urls_from_csv(csv_path)
        if not url_to_files:
            print("No URLs found in the provided CSV.")
            return 0
    elif args.paths:
        roots = [Path(p).resolve() for p in args.paths]
        print("Scanning for files...", flush=True)
        sources = extract_url_sources(roots)
        if not sources:
            print("No supported files or URLs found.")
            return 0
        url_to_files = _group_sources_by_url(sources)
        print(f"Found {len(sources)} URLs across {len(set(s.file_path for s in sources))} file(s). Checking...", flush=True)
    else:
        print("Error: provide folder path(s) or --from-csv.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 1

    unique_urls = sorted(url_to_files.keys())
    total = len(unique_urls)
    output_path = Path(args.output)
    blocked_path = _side_output_path(output_path, "_blocked")
    errors_path = _side_output_path(output_path, "_errors")
    blocked_count = 0
    error_count = 0

    source_files_for = lambda url: SOURCE_FILES_DELIMITER.join(
        sorted(set(url_to_files.get(url, [])))
    )

    with (
        output_path.open("w", encoding="utf-8", newline="") as csv_file,
        blocked_path.open("w", encoding="utf-8", newline="") as blocked_file,
        errors_path.open("w", encoding="utf-8", newline="") as errors_file,
    ):
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
        blocked_writer = csv.DictWriter(blocked_file, fieldnames=BLOCKED_FIELDNAMES)
        errors_writer = csv.DictWriter(errors_file, fieldnames=ERRORS_FIELDNAMES)
        writer.writeheader()
        blocked_writer.writeheader()
        errors_writer.writeheader()
        csv_file.flush()
        blocked_file.flush()
        errors_file.flush()

        for i, url in enumerate(unique_urls, 1):
            print(f"[{i}/{total}] {url}", flush=True)
            result = check_url(url, timeout=args.timeout)
            writer.writerow(_make_csv_row(result, url_to_files))
            csv_file.flush()

            if result.blocked_by_senso:
                blocked_count += 1
                reason = f" ({result.block_reason})" if result.block_reason else ""
                print(f"  *** BLOCKED{reason}: {result.url}", flush=True)
                blocked_writer.writerow({
                    "url": result.url,
                    "block_reason": result.block_reason or "",
                    "source_files": source_files_for(result.url),
                })
                blocked_file.flush()
            elif result.error or (result.status_code is not None and result.status_code >= 400):
                error_count += 1
                errors_writer.writerow({
                    "url": result.url,
                    "status_code": result.status_code or "",
                    "error": result.error or "",
                    "source_files": source_files_for(result.url),
                })
                errors_file.flush()

    print(
        f"\nChecked {total} unique URLs. "
        f"Blocked by Senso: {blocked_count}. Errors: {error_count}.\n"
        f"  All results  → {output_path}\n"
        f"  Blocked URLs → {blocked_path}\n"
        f"  Error URLs   → {errors_path}"
    )
    return 0
