from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import TracebackType

from .checker import UrlCheckResult, _extract_block_reason, _looks_blocked_by_senso

# Default Edge user-data directory on Windows.
_DEFAULT_EDGE_PROFILE = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"

# Playwright profile copy lives next to the real one.
# Edge refuses remote debugging on the real default user-data-dir, so we copy it.
_PLAYWRIGHT_PROFILE = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Playwright Data"

# How long to wait for a page to load (milliseconds).
_PAGE_TIMEOUT_MS = 20_000

# Profile subdirectories that contain extensions and their state.
# We copy only these to keep the sync fast (skips Cache, Code Cache, etc.).
_EXTENSION_SUBDIRS = [
    "Extensions",
    "Local Extension Settings",
    "Extension State",
    "Extension Rules",
    "IndexedDB",
    "Preferences",
    "Secure Preferences",
]


def _sync_playwright_profile(source: Path, dest: Path) -> None:
    """
    Copy extension-related items from the real Edge profile to a sibling
    directory that Edge will accept for remote debugging.
    """
    default_src = source / "Default"
    default_dst = dest / "Default"
    default_dst.mkdir(parents=True, exist_ok=True)

    for name in _EXTENSION_SUBDIRS:
        src = default_src / name
        dst = default_dst / name
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    print(f"Profile synced to {dest}", flush=True)


def _clean_error(exc: Exception) -> str:
    """Return a short, readable error string from a Playwright exception.

    Playwright errors look like:
      'Page.goto: Timeout 20000ms exceeded.\nCall log:\n  - navigating to ...'
    We keep only the first line so the CSV stays readable.
    """
    first_line = str(exc).splitlines()[0].strip()
    # Strip the 'Page.goto: ' / 'Page.content: ' prefix Playwright adds.
    for prefix in ("Page.goto: ", "Page.content: ", "Page.url: "):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix):]
    return first_line


def _status_from_exception(exc: Exception) -> int | None:
    """Map well-known Playwright error strings to a pseudo status code."""
    msg = str(exc)
    if "Timeout" in msg and "exceeded" in msg:
        return 408  # Request Timeout — conventional for a navigation timeout
    return None


class BrowserChecker:
    """
    Checks URLs by driving a real Edge browser so that browser extensions
    (such as Senso) intercept requests exactly as they would for a real user.

    When keep_failed_tabs=True (set automatically when --limit is used), blocked
    and errored pages are left open as tabs in Edge after the run so you can
    review them. Press Enter in the terminal to close Edge when done.

    Usage::

        with BrowserChecker(edge_profile=..., keep_failed_tabs=True) as checker:
            result = checker.check(url)
    """

    def __init__(self, edge_profile: Path | None = None, keep_failed_tabs: bool = False) -> None:
        self._source_profile = edge_profile or _DEFAULT_EDGE_PROFILE
        self._playwright_profile = _PLAYWRIGHT_PROFILE
        self._keep_failed_tabs = keep_failed_tabs
        self._failed_pages: list = []

    def __enter__(self) -> "BrowserChecker":
        from playwright.sync_api import sync_playwright  # imported lazily

        print("Syncing profile extensions to Playwright working copy...", flush=True)
        _sync_playwright_profile(self._source_profile, self._playwright_profile)

        self._pw = sync_playwright().start()
        # launch_persistent_context lets extensions load from the real profile.
        # headless=False is required for extensions to work in Chromium/Edge.
        try:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self._playwright_profile),
                channel="msedge",
                headless=False,
                # Tell Playwright NOT to add --disable-extensions or the related
                # component-extensions flag — both prevent Senso from loading.
                ignore_default_args=[
                    "--disable-extensions",
                    "--disable-component-extensions-with-background-pages",
                ],
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    # Don't restore tabs from the previous session.
                    "--no-restore-session-state",
                    "--restore-last-session=0",
                ],
            )
        except Exception as exc:
            self._pw.stop()
            raise RuntimeError(
                f"Could not launch Edge.\n"
                "Things to try:\n"
                "  1. Close all Edge windows and wait a few seconds for background processes to exit.\n"
                "  2. Open Task Manager, check for any msedge.exe processes still running, and end them.\n"
                f"Original error: {exc}"
            ) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._failed_pages:
            n = len(self._failed_pages)
            print(
                f"\n{n} blocked/error URL(s) are open in Edge for review.\n"
                "Press Enter here when you are done to close Edge...",
                flush=True,
            )
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass

        try:
            self._context.close()
        finally:
            self._pw.stop()

    def check(self, url: str) -> UrlCheckResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        page = self._context.new_page()
        result: UrlCheckResult
        keep_open = False
        try:
            response = page.goto(url, timeout=_PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
            status = response.status if response else None
            final_url = page.url
            body = page.content()

            blocked = _looks_blocked_by_senso(body, final_url)
            reason = _extract_block_reason(body) if blocked else None
            is_error = status is not None and status >= 400
            keep_open = blocked or is_error
            result = UrlCheckResult(
                url=url,
                blocked_by_senso=blocked,
                status_code=status,
                final_url=final_url,
                error=None,
                block_reason=reason,
            )
        except Exception as exc:
            keep_open = True
            result = UrlCheckResult(
                url=url,
                blocked_by_senso=False,
                status_code=_status_from_exception(exc),
                final_url=None,
                error=_clean_error(exc),
                block_reason=None,
            )

        if keep_open and self._keep_failed_tabs:
            self._failed_pages.append(page)
        else:
            page.close()

        return result
