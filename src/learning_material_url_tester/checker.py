from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BODY_READ_BYTES = 20000

_BLOCK_REASON_PATTERNS = [
    #re.compile(r"blocked by the following library\s*[:\-]?\s*([^\n<]{2,80})", re.IGNORECASE),
    #re.compile(r"blocked\sby\sthe\sfollowing\slibrary:\s", re.IGNORECASE),
    #re.compile("This has been blocked by the following library: (Streaming \& Downloadable Video)<div>", re.IGNORECASE),
    re.compile(f"(Streaming)", re.IGNORECASE),
    re.compile(r"categor(?:y|ies)\s*[:\-]\s*([^\n<]{2,80})", re.IGNORECASE),
    re.compile(r"group\s*[:\-]\s*([^\n<]{2,80})", re.IGNORECASE),
    re.compile(r"reason\s*[:\-]\s*([^\n<]{2,80})", re.IGNORECASE),
]

# Phrases that indicate a Senso-style block page even without the word "senso".
_BLOCK_PAGE_PHRASES = (
    "website address is banned",
    "blocked by the following library",
    "this website has been banned",
)


@dataclass(frozen=True)
class UrlCheckResult:
    url: str
    blocked_by_senso: bool
    status_code: int | None
    final_url: str | None
    error: str | None
    block_reason: str | None = None


def _looks_blocked_by_senso(body: str, final_url: str | None) -> bool:
    body_l = body.lower()
    url_l = (final_url or "").lower()
    # Classic Senso detection: "senso" appears in body or redirect URL,
    # plus an explicit block signal as a standalone word (not inside "inline-block", "blockquote" etc).
    has_senso = "senso" in body_l or "senso" in url_l
    has_block_signal = bool(re.search(
        r"\b(blocked|denied|forbidden|banned)\b",
        body_l,
    ))
    if has_senso and has_block_signal:
        return True
    # Senso block pages sometimes omit the word "senso" — detect by page phrasing alone.
    return any(phrase in body_l for phrase in _BLOCK_PAGE_PHRASES)


def _extract_block_reason(body: str) -> str | None:
    """Extract the blocking category or group name from a Senso block page."""
    print("body=", body)
    for pattern in _BLOCK_REASON_PATTERNS:
        match = pattern.search(body)
        print("pattern=", pattern)
        print("match=", match)
        if match:
            return match.group(1).strip()
    return None


def check_url(url: str, timeout: int = 15) -> UrlCheckResult:
    """Fetch a URL and flag responses that look like Senso blocking pages."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    req = Request(url, headers={"User-Agent": "LearningMaterialURLTester/0.1"})
    try:
        with urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", None)
            final_url = response.geturl()
            body = response.read(MAX_BODY_READ_BYTES).decode("utf-8", errors="ignore")
            blocked = _looks_blocked_by_senso(body, final_url)
            return UrlCheckResult(
                url=url,
                blocked_by_senso=blocked,
                status_code=status,
                final_url=final_url,
                error=None,
                block_reason=_extract_block_reason(body) if blocked else None,
            )
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read(MAX_BODY_READ_BYTES).decode("utf-8", errors="ignore")
        except OSError:
            pass
        final_url = exc.geturl()
        blocked = _looks_blocked_by_senso(body, final_url)
        return UrlCheckResult(
            url=url,
            blocked_by_senso=blocked,
            status_code=exc.code,
            final_url=final_url,
            error=str(exc),
            block_reason=_extract_block_reason(body) if blocked else None,
        )
    except (URLError, ValueError, OSError) as exc:
        return UrlCheckResult(
            url=url,
            blocked_by_senso=False,
            status_code=None,
            final_url=None,
            error=str(exc),
            block_reason=None,
        )

if __name__ ==  "__main__":
    print(check_url('https://www.cbsnews.com/sanfrancisco/news/apple-watch-sales-ban-to-be-revivied-federal-appeals-court-patent-dispute/'))