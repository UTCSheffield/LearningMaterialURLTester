"""Streamlit reporting app for URL check results.

Run with:
    streamlit run src/learning_material_url_tester/report.py -- --db url_check_results.db

Or just:
    streamlit run src/learning_material_url_tester/report.py
and pick the database file in the sidebar.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

import streamlit as st

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

SOURCE_FILES_DELIMITER = "|"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=30)
def load_rows(db_path: str) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM url_results ORDER BY url").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Data processing
# ---------------------------------------------------------------------------

def _status(row: dict) -> str:
    if not row.get("checked"):
        return "unchecked"
    if row.get("blocked_by_senso"):
        return "blocked"
    err = row.get("error") or ""
    sc = row.get("status_code")
    if err or (sc is not None and sc >= 400):
        return "error"
    return "ok"


def _parse_path(raw: str) -> tuple[str, ...]:
    """Turn a file path string into a tuple of parts, normalising separators."""
    # Try Windows path first (handles both \\ and /)
    try:
        parts = PureWindowsPath(raw).parts
        if len(parts) > 1:
            return parts
    except Exception:
        pass
    return PurePosixPath(raw).parts


def build_tree(rows: list[dict]) -> dict:
    """
    Build a nested dict:
      tree[folder_chain][file_path] = list of row dicts
    folder_chain is a tuple of directory parts above the filename.
    """
    # file_path -> list[row]
    file_to_rows: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        raw_files = row.get("source_files") or ""
        files = [f for f in raw_files.split(SOURCE_FILES_DELIMITER) if f]
        if not files:
            files = ["(no source file)"]
        for f in files:
            file_to_rows[f].append(row)

    # Build a nested folder -> file -> rows tree
    # We use a plain dict for JSON-safe caching; leaf value = list of rows.
    tree: dict = {}
    for file_path, file_rows in file_to_rows.items():
        parts = _parse_path(file_path)
        if len(parts) <= 1:
            folders: tuple = ()
            fname = parts[0] if parts else file_path
        else:
            folders = parts[:-1]
            fname = parts[-1]

        node = tree
        for part in folders:
            node = node.setdefault(part, {})
        node.setdefault("__files__", {})[file_path] = file_rows

    return tree


def _counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[_status(row)] += 1
    return counts


def _all_rows_in_node(node: dict) -> list[dict]:
    """Recursively collect all rows under a tree node."""
    result = []
    for key, val in node.items():
        if key == "__files__":
            for file_rows in val.values():
                result.extend(file_rows)
        elif isinstance(val, dict):
            result.extend(_all_rows_in_node(val))
    return result


def _host_from_url(url: str) -> str:
    """Extract hostname from a URL, tolerating bare domains."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.hostname or ""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "unknown"


def _unique_hosts_csv(urls: list[str]) -> str:
    hosts = sorted({_host_from_url(url) for url in urls if _host_from_url(url)})
    buf = StringIO()
    writer = csv.writer(buf)
    # writer.writerow(["host"])
    for host in hosts:
        writer.writerow([host])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

STATUS_EMOJI = {"ok": "✅", "blocked": "🚫", "error": "❌", "unchecked": "⬜"}
STATUS_COLOUR = {"ok": "green", "blocked": "red", "error": "orange", "unchecked": "grey"}


def _badge(counts: dict[str, int]) -> str:
    parts = []
    for status in ("ok", "blocked", "error", "unchecked"):
        n = counts.get(status, 0)
        if n:
            colour = STATUS_COLOUR[status]
            parts.append(f":{colour}[{STATUS_EMOJI[status]} {n} {status}]")
    return "  ".join(parts)


def _render_url_row(row: dict) -> None:
    status = _status(row)
    emoji = STATUS_EMOJI[status]
    url = row["url"]
    sc = row.get("status_code")
    sc_str = f" `{sc}`" if sc else ""
    final = row.get("final_url") or ""
    redirect = f" → `{final}`" if final and final != url else ""
    st.markdown(f"{emoji} [{url}]({url}){sc_str}{redirect}")
    if status == "blocked":
        reason = row.get("block_reason") or "unknown reason"
        st.caption(f"🔒 Blocked: {reason}")
    elif status == "error":
        err = row.get("error") or ""
        st.caption(f"⚠️ {err or f'HTTP {sc}'}")


def _render_file(file_path: str, file_rows: list[dict], depth: int = 0) -> None:
    fname = Path(file_path).name
    counts = _counts(file_rows)
    label = f"📄 **{fname}**  {_badge(counts)}"
    with st.expander(label, expanded=False):
        # Deduplicate rows by URL (a URL may appear multiple times from the same file)
        seen: set[str] = set()
        for row in sorted(file_rows, key=lambda r: _status(r) + r["url"]):
            if row["url"] not in seen:
                seen.add(row["url"])
                _render_url_row(row)


def _render_tree_node(node: dict, depth: int = 0) -> None:
    """Recursively render folder nodes, then files."""
    # Render sub-folders first
    for key in sorted(k for k in node if k != "__files__"):
        child = node[key]
        if not isinstance(child, dict):
            continue
        child_rows = _all_rows_in_node(child)
        counts = _counts(child_rows)
        label = f"📁 **{key}**  {_badge(counts)}"
        with st.expander(label, expanded=depth == 0):
            _render_tree_node(child, depth + 1)

    # Then files in this node
    files = node.get("__files__", {})
    for file_path in sorted(files.keys()):
        _render_file(file_path, files[file_path], depth)


# ---------------------------------------------------------------------------
# Page: Overview
# ---------------------------------------------------------------------------

def page_overview(rows: list[dict]) -> None:
    st.header("Overview")

    total = len(rows)
    counts = _counts(rows)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total URLs", total)
    col2.metric("✅ OK", counts.get("ok", 0))
    col3.metric("🚫 Blocked", counts.get("blocked", 0))
    col4.metric("❌ Errors", counts.get("error", 0))

    cola1, cola2, cola3, cola4 = st.columns(4)
    tested = counts.get("ok", 0) + counts.get("blocked", 0) + counts.get("error", 0)
    tested_pct = round(100 * tested / total) if total else 0
    ok_pct = round(100 * counts.get("ok", 0) / tested) if tested else 0
    blocked_pct = round(100 * counts.get("blocked", 0) / tested) if tested else 0
    error_pct = round(100 * counts.get("error", 0) / tested) if tested else 0
    cola1.metric("Tested URLs", tested)
    cola2.metric("✅ OK", f"{ok_pct}%")
    cola3.metric("🚫 Blocked", f"{blocked_pct}%")
    cola4.metric("❌ Errors", f"{error_pct}%")
    if counts.get("unchecked", 0):
        st.info(f"⬜ {counts['unchecked']} URL(s) not yet checked. {tested_pct}% checked")
    
    st.divider()

    # Block reasons breakdown
    blocked_rows = [r for r in rows if _status(r) == "blocked"]
    if not blocked_rows:
        st.success("No URLs are currently blocked by Senso.")
        return

    st.subheader("🚫 Block reasons")
    reason_counts: dict[str, int] = defaultdict(int)
    for row in blocked_rows:
        reason = (row.get("block_reason") or "Unknown").strip()
        reason_counts[reason] += 1

    sorted_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])

    # Bar chart data
    import pandas as pd
    df = pd.DataFrame(sorted_reasons, columns=["Reason", "Count"])
    st.bar_chart(df.set_index("Reason"))

    

    st.subheader("Detail")
    for reason, count in sorted_reasons:
        reason_rows = [
            row
            for row in blocked_rows
            if (row.get("block_reason") or "Unknown").strip() == reason
        ]
        urls_for_reason = [row["url"] for row in reason_rows]
        csv_data = _unique_hosts_csv(urls_for_reason)
        with st.expander(f"**{reason}** — {count} URL(s)"):
            st.download_button(
                label="Download unique hosts CSV",
                data=csv_data,
                file_name=f"blocked_hosts_{_slugify(reason)}.csv",
                mime="text/csv",
                key=f"download_hosts_{_slugify(reason)}",
            )
            for row in sorted(reason_rows, key=lambda r: r["url"]):
                st.markdown(f"- [{row['url']}]({row['url']})")
                files = [f for f in (row.get("source_files") or "").split(SOURCE_FILES_DELIMITER) if f]
                if files:
                    for f in files:
                        st.caption(f"  📄 {f}")


# ---------------------------------------------------------------------------
# Page: By folder / file
# ---------------------------------------------------------------------------

def page_by_file(rows: list[dict]) -> None:
    st.header("Results by folder and file")

    # Filter controls
    col1, col2 = st.columns(2)
    with col1:
        show_ok = st.checkbox("Show OK ✅", value=True)
        show_blocked = st.checkbox("Show blocked 🚫", value=True)
    with col2:
        show_errors = st.checkbox("Show errors ❌", value=True)
        show_unchecked = st.checkbox("Show unchecked ⬜", value=False)

    allowed = set()
    if show_ok:
        allowed.add("ok")
    if show_blocked:
        allowed.add("blocked")
    if show_errors:
        allowed.add("error")
    if show_unchecked:
        allowed.add("unchecked")

    filtered = [r for r in rows if _status(r) in allowed]
    if not filtered:
        st.info("No results match the current filters.")
        return

    tree = build_tree(filtered)
    _render_tree_node(tree, depth=0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="URL Check Results",
        page_icon="🔗",
        layout="wide",
    )

    st.title("🔗 URL Check Results")

    # Resolve DB path from CLI arg or sidebar picker
    db_path: str | None = None

    # Check for --db argument passed after `--` to streamlit
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            break

    with st.sidebar:
        st.header("Database")
        if db_path:
            st.info(f"Using: `{db_path}`")
        else:
            uploaded = st.text_input(
                "Path to .db file",
                value="url_check_results.db",
                help="Absolute or relative path to the SQLite database.",
            )
            db_path = uploaded.strip() if uploaded.strip() else None

        if db_path and st.button("🔄 Refresh data"):
            load_rows.clear()

        st.divider()
        st.markdown(
            "**Legend**\n"
            "- ✅ OK — loaded fine\n"
            "- 🚫 Blocked — Senso block page\n"
            "- ❌ Error — HTTP error or timeout\n"
            "- ⬜ Unchecked — not yet tested\n"
        )

    if not db_path:
        st.info("Enter the path to a `url_check_results.db` file in the sidebar.")
        return

    db_file = Path(db_path)
    if not db_file.exists():
        st.error(f"Database file not found: `{db_file.resolve()}`")
        return

    try:
        rows = load_rows(str(db_file.resolve()))
    except Exception as exc:
        st.error(f"Could not read database: {exc}")
        return

    if not rows:
        st.warning("The database is empty. Run `scan` and `check` first.")
        return

    tab1, tab2 = st.tabs(["📊 Overview", "📁 By folder & file"])
    with tab1:
        page_overview(rows)
    with tab2:
        page_by_file(rows)


if __name__ == "__main__":
    main()
