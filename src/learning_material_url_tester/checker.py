from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BODY_READ_BYTES = 20000


@dataclass(frozen=True)
class UrlCheckResult:
    url: str
    blocked_by_senso: bool
    status_code: int | None
    final_url: str | None
    error: str | None


def _looks_blocked_by_senso(body: str, final_url: str | None) -> bool:
    body_l = body.lower()
    url_l = (final_url or "").lower()
    has_senso = "senso" in body_l or "senso" in url_l
    has_block_signal = any(term in body_l for term in ("block", "blocked", "deny", "denied", "forbidden"))
    return has_senso and has_block_signal


def check_url(url: str, timeout: int = 15) -> UrlCheckResult:
    """Fetch a URL and flag responses that look like Senso blocking pages."""
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
        )
    except (URLError, ValueError, OSError) as exc:
        return UrlCheckResult(
            url=url,
            blocked_by_senso=False,
            status_code=None,
            final_url=None,
            error=str(exc),
        )
