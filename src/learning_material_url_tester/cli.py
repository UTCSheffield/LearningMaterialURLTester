from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .browser_checker import BrowserChecker, _DEFAULT_EDGE_PROFILE
from .db import (
    export_to_csv,
    get_source_files,
    get_unchecked_urls,
    import_from_csv,
    mark_blocked_unchecked,
    open_db,
    upsert_result,
    upsert_source_files,
)
from .extractor import UrlSource, extract_url_sources


_SENSO_SANITY_CHECK_URL = "facebook.com"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract URLs from learning material files and check if blocked by Senso."
    )
    parser.add_argument(
        "--output",
        default="url_check_results.csv",
        help="CSV export path (default: url_check_results.csv). The database is stored alongside as a .db file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scan subcommand ---
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan learning material files for URLs and save them to the database (does not check URLs).",
    )
    scan_parser.add_argument(
        "paths",
        nargs="+",
        help="Root folder(s) containing learning materials.",
    )

    # --- check subcommand ---
    check_parser = subparsers.add_parser(
        "check",
        help="Check all unchecked URLs in the database using Edge.",
    )
    check_parser.add_argument(
        "--check-blocked",
        action="store_true",
        help="Before checking, mark all blocked URLs as unchecked so they are re-tested.",
    )
    check_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only check the first N unchecked URLs. Useful for testing. Also keeps failed tabs open in Edge.",
    )
    check_parser.add_argument(
        "--start-at",
        type=int,
        default=1,
        metavar="N",
        help="Skip the first N-1 unchecked URLs and start from position N (1-based, default: 1).",
    )
    check_parser.add_argument(
        "--edge-profile",
        metavar="DIR",
        default=str(_DEFAULT_EDGE_PROFILE),
        help=(
            r"Path to the Edge 'User Data' directory (default: %%LOCALAPPDATA%%\Microsoft\Edge\User Data). "
            "Edge must be fully closed before running."
        ),
    )

    # --- import subcommand ---
    import_parser = subparsers.add_parser(
        "import",
        help="Import a previous results CSV into the database (imported rows are marked as already checked).",
    )
    import_parser.add_argument(
        "csv",
        help="Path to the CSV file to import.",
    )

    return parser


def _group_sources_by_url(sources: list[UrlSource]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for source in sources:
        grouped.setdefault(source.url, []).append(source.file_path)
    return grouped


def _side_output_path(main_path: Path, suffix: str) -> Path:
    return main_path.with_stem(main_path.stem + suffix)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    output_path = Path(args.output)
    blocked_path = _side_output_path(output_path, "_blocked")
    errors_path = _side_output_path(output_path, "_errors")
    db_path = output_path.with_suffix(".db").resolve()

    conn = open_db(db_path)
    print(f"Database: {db_path}", flush=True)

    try:
        if args.command == "scan":
            return _cmd_scan(args, conn)

        if args.command == "import":
            return _cmd_import(args, conn)

        if args.command == "check":
            return _cmd_check(args, conn, output_path, blocked_path, errors_path)

        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def _cmd_scan(args, conn) -> int:
    roots = [Path(p).resolve() for p in args.paths]
    print("Scanning for files...", flush=True)
    sources = extract_url_sources(roots)
    if not sources:
        print("No supported files or URLs found.")
        return 0

    url_to_files = _group_sources_by_url(sources)
    print(
        f"Found {len(sources)} URL references across "
        f"{len(set(s.file_path for s in sources))} file(s). "
        "Saving to database...",
        flush=True,
    )

    for url, files in url_to_files.items():
        upsert_source_files(conn, url, files)
    conn.commit()

    unchecked = conn.execute(
        "SELECT COUNT(*) FROM url_results WHERE checked = 0"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM url_results").fetchone()[0]
    print(
        f"Done. Database holds {total} URL(s), {unchecked} unchecked.\n"
        "Run `check` to test them."
    )
    return 0


def _cmd_import(args, conn) -> int:
    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"Error: CSV file not found: {csv_path.resolve()}", file=sys.stderr)
        return 1

    print(f"Importing {csv_path}...", flush=True)
    imported = import_from_csv(conn, csv_path)
    total = conn.execute("SELECT COUNT(*) FROM url_results").fetchone()[0]
    print(
        f"  {imported} new row(s) added (existing rows preserved).\n"
        f"  Database now holds {total} URL(s).\n"
        "Use `check --check-blocked` to retest blocked URLs."
    )
    return 0


def _cmd_check(args, conn, output_path: Path, blocked_path: Path, errors_path: Path) -> int:
    if args.check_blocked:
        reset = mark_blocked_unchecked(conn)
        print(f"Marked {reset} blocked URL(s) as unchecked.", flush=True)

    urls = get_unchecked_urls(conn)
    if not urls:
        print("No unchecked URLs in the database. Run `scan` first, or use --check-blocked to retest blocked URLs.")
        return 0

    start_at = max(1, args.start_at)
    urls = urls[start_at - 1:]
    if args.limit:
        urls = urls[:args.limit]

    if start_at > 1 or args.limit:
        print(f"(start-at {start_at}, limit {args.limit or 'none'}: checking {len(urls)} URLs)", flush=True)

    edge_profile = Path(args.edge_profile)
    keep_failed_tabs = bool(args.limit)
    print(f"Using Edge profile at {edge_profile}", flush=True)
    print("(Edge must be fully closed before this will work.)", flush=True)
    try:
        browser_ctx = BrowserChecker(edge_profile=edge_profile, keep_failed_tabs=keep_failed_tabs)
        browser_ctx.__enter__()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        if not _run_senso_startup_sanity_check(browser_ctx):
            return 1
        url_to_files = {url: get_source_files(conn, url) for url in urls}
        return _check_urls(urls, url_to_files, output_path, blocked_path, errors_path, browser_ctx, conn)
    finally:
        browser_ctx.__exit__(None, None, None)


def _run_senso_startup_sanity_check(browser_ctx: BrowserChecker) -> bool:
    """Verify Senso is active by checking that facebook.com is blocked."""
    print(f"Running startup sanity check: {_SENSO_SANITY_CHECK_URL} should be blocked...", flush=True)
    result = browser_ctx.check(_SENSO_SANITY_CHECK_URL)
    if result.blocked_by_senso:
        reason = f" ({result.block_reason})" if result.block_reason else ""
        print(f"Startup sanity check passed: {_SENSO_SANITY_CHECK_URL} is blocked{reason}.", flush=True)
        return True

    status = result.status_code if result.status_code is not None else "n/a"
    final_url = result.final_url or "n/a"
    error = result.error or "none"
    print(
        "Error: startup sanity check failed. "
        f"{_SENSO_SANITY_CHECK_URL} was not detected as blocked.\n"
        "This usually means Senso is not active in the Edge profile used for checking.\n"
        f"Observed status={status}, final_url={final_url}, error={error}.",
        file=sys.stderr,
        flush=True,
    )
    return False


def _check_urls(
    urls: list[str],
    url_to_files: dict[str, list[str]],
    output_path: Path,
    blocked_path: Path,
    errors_path: Path,
    browser_ctx: BrowserChecker,
    conn,
) -> int:
    total = len(urls)
    blocked_count = 0
    error_count = 0

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{total}] {url}", flush=True)
        result = browser_ctx.check(url)
        upsert_result(conn, result, url_to_files.get(url, []))

        if result.blocked_by_senso:
            blocked_count += 1
            reason = f" ({result.block_reason})" if result.block_reason else ""
            print(f"  *** BLOCKED{reason}: {result.url}", flush=True)
        elif result.error or (result.status_code is not None and result.status_code >= 400):
            error_count += 1
            print(f"  ✗ Error (HTTP {result.status_code or result.error}): {result.url}", flush=True)

    total_db, blocked_db, errors_db = export_to_csv(conn, output_path, blocked_path, errors_path)
    print(
        f"\nChecked {total} URL(s) this run "
        f"(database holds {total_db} total). "
        f"Blocked by Senso: {blocked_db}. Errors: {errors_db}.\n"
        f"  Database     → {output_path.with_suffix('.db')}\n"
        f"  All results  → {output_path}\n"
        f"  Blocked URLs → {blocked_path}\n"
        f"  Error URLs   → {errors_path}"
    )
    return 0
