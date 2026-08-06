"""SQLite backend for URL check results.

Results are upserted one at a time so progress is never lost if the run is
interrupted. CSV files are exported from the DB at the end of a run.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .checker import UrlCheckResult

SOURCE_FILES_DELIMITER = "|"

CSV_FIELDNAMES = ["url", "blocked_by_senso", "status_code", "final_url", "error", "block_reason", "source_files"]
BLOCKED_FIELDNAMES = ["url", "block_reason", "source_files"]
ERRORS_FIELDNAMES = ["url", "status_code", "error", "source_files"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure the schema exists."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # WAL mode keeps the DB consistent even if the process is killed mid-write.
    conn.execute("PRAGMA journal_mode=WAL")
    # Ensure WAL is checkpointed to the main DB file when the connection closes.
    conn.execute("PRAGMA wal_autocheckpoint=100")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS url_results (
            url              TEXT PRIMARY KEY,
            blocked_by_senso INTEGER,  -- NULL = never checked, 0 = ok, 1 = blocked
            status_code      INTEGER,
            final_url        TEXT,
            error            TEXT,
            block_reason     TEXT,
            source_files     TEXT NOT NULL DEFAULT '',
            checked          INTEGER NOT NULL DEFAULT 0,  -- 0 = needs checking, 1 = done
            checked_at       TEXT,  -- ISO-8601; NULL = never checked
            scan_seen_at     TEXT   -- ISO-8601; NULL = imported, not from a scan
        )
    """)
    # Migration: add 'checked' to databases created before this column existed.
    try:
        conn.execute("ALTER TABLE url_results ADD COLUMN checked INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    return conn


def upsert_source_files(conn: sqlite3.Connection, url: str, source_files: list[str]) -> None:
    """Record that a URL was found in a file scan without touching check results.

    New rows are inserted with checked=0 (needs checking).
    Existing rows keep their current checked value — a re-scan never resets progress.
    """
    files_str = SOURCE_FILES_DELIMITER.join(sorted(set(source_files)))
    conn.execute(
        """
        INSERT INTO url_results (url, source_files, scan_seen_at, checked)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(url) DO UPDATE SET
            source_files = excluded.source_files,
            scan_seen_at = excluded.scan_seen_at
        """,
        (url, files_str, _now_iso()),
    )


def upsert_result(conn: sqlite3.Connection, result: UrlCheckResult, source_files: list[str]) -> None:
    """Upsert a check result immediately — called after every single URL check.

    Always sets checked=1 so the URL is not picked up again on the next run.
    """
    files_str = SOURCE_FILES_DELIMITER.join(sorted(set(source_files)))
    conn.execute(
        """
        INSERT INTO url_results
            (url, blocked_by_senso, status_code, final_url, error, block_reason, source_files, checked, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(url) DO UPDATE SET
            blocked_by_senso = excluded.blocked_by_senso,
            status_code      = excluded.status_code,
            final_url        = excluded.final_url,
            error            = excluded.error,
            block_reason     = excluded.block_reason,
            source_files     = excluded.source_files,
            checked          = 1,
            checked_at       = excluded.checked_at
        """,
        (
            result.url,
            1 if result.blocked_by_senso else 0,
            result.status_code,
            result.final_url,
            result.error,
            result.block_reason,
            files_str,
            _now_iso(),
        ),
    )
    conn.commit()


def get_unchecked_urls(conn: sqlite3.Connection) -> list[str]:
    """Return all URLs that have not yet been checked (checked=0), ordered by URL."""
    rows = conn.execute(
        "SELECT url FROM url_results WHERE checked = 0 ORDER BY url"
    ).fetchall()
    return [row["url"] for row in rows]


def mark_blocked_unchecked(conn: sqlite3.Connection) -> int:
    """Reset checked=0 for all blocked URLs so they will be rechecked.

    Returns the number of rows updated.
    """
    cursor = conn.execute(
        "UPDATE url_results SET checked = 0 WHERE blocked_by_senso = 1"
    )
    conn.commit()
    return cursor.rowcount


def get_blocked_urls(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT url FROM url_results WHERE blocked_by_senso = 1 ORDER BY url"
    ).fetchall()
    return [row["url"] for row in rows]


def get_all_urls(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT url FROM url_results ORDER BY url").fetchall()
    return [row["url"] for row in rows]


def get_source_files(conn: sqlite3.Connection, url: str) -> list[str]:
    row = conn.execute(
        "SELECT source_files FROM url_results WHERE url = ?", (url,)
    ).fetchone()
    if row and row["source_files"]:
        return row["source_files"].split(SOURCE_FILES_DELIMITER)
    return []


def import_from_csv(conn: sqlite3.Connection, csv_path: Path) -> int:
    """Import rows from a CSV into the DB.

    Uses INSERT OR IGNORE so any URL already in the DB (with fresher results
    from a previous run) is left untouched.  Returns the number of new rows
    inserted.
    """
    csv.field_size_limit(10_000_000)
    count = 0
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("url", "").strip()
            if not url:
                continue
            blocked = row.get("blocked_by_senso", "").strip().lower() == "true"
            status_raw = row.get("status_code", "").strip()
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO url_results
                    (url, blocked_by_senso, status_code, final_url, error, block_reason, source_files, checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    url,
                    1 if blocked else 0,
                    int(status_raw) if status_raw.isdigit() else None,
                    row.get("final_url", "").strip() or None,
                    row.get("error", "").strip() or None,
                    row.get("block_reason", "").strip() or None,
                    row.get("source_files", "").strip(),
                ),
            )
            count += cursor.rowcount
    conn.commit()
    return count


def export_to_csv(
    conn: sqlite3.Connection,
    output_path: Path,
    blocked_path: Path,
    errors_path: Path,
) -> tuple[int, int, int]:
    """Write all DB rows to CSV files. Returns (total, blocked, errors)."""
    rows = conn.execute("SELECT * FROM url_results ORDER BY url").fetchall()
    total = len(rows)
    blocked_count = 0
    error_count = 0

    with (
        output_path.open("w", encoding="utf-8", newline="") as csv_file,
        blocked_path.open("w", encoding="utf-8", newline="") as blocked_file,
        errors_path.open("w", encoding="utf-8", newline="") as errors_file,
    ):
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
        blocked_writer = csv.DictWriter(blocked_file, fieldnames=BLOCKED_FIELDNAMES)
        errors_writer = csv.DictWriter(errors_file, fieldnames=ERRORS_FIELDNAMES)
        for w in (writer, blocked_writer, errors_writer):
            w.writeheader()

        for row in rows:
            is_blocked = bool(row["blocked_by_senso"])
            status = row["status_code"]
            error = row["error"] or ""
            source_files = row["source_files"] or ""

            writer.writerow({
                "url": row["url"],
                "blocked_by_senso": is_blocked,
                "status_code": status if status is not None else "",
                "final_url": row["final_url"] or "",
                "error": error,
                "block_reason": row["block_reason"] or "",
                "source_files": source_files,
            })

            if is_blocked:
                blocked_count += 1
                blocked_writer.writerow({
                    "url": row["url"],
                    "block_reason": row["block_reason"] or "",
                    "source_files": source_files,
                })
            elif error or (status is not None and status >= 400):
                error_count += 1
                errors_writer.writerow({
                    "url": row["url"],
                    "status_code": status if status is not None else "",
                    "error": error,
                    "source_files": source_files,
                })

    return total, blocked_count, error_count
