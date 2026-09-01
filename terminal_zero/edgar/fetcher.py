"""A disciplined, multi-source fetcher.

Three jobs, and only these three:

  1. Rate limit    — never exceed a source's ceiling; each host gets its own
                     throttle, looked up from the source registry.
  2. Authenticate  — attach whatever a source needs (SEC contact header, an API
                     key query param, a bearer token), read from the environment
                     so credentials never touch the repo or the cache.
  3. Cache + record — write every raw response to disk with the time we
                      retrieved it, so a figure's *vintage* is captured at the
                      moment it entered the store and never silently changes.

Point (3) is the provenance foundation: downstream code trusts that the bytes
on disk are exactly what the source returned, and that `retrieved_at` says when.

One subtlety worth calling out: for key-in-URL sources (Census, NASS, BEA) we
cache and record the *canonical* URL — the one without the key — and only add
the key to the actual network request. So API keys never get written to disk,
and rotating a key doesn't invalidate the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from terminal_zero import config, sources


@dataclass(frozen=True)
class FetchResult:
    """One fetch, plus the provenance that makes it trustworthy."""

    url: str                   # canonical URL (no credentials)
    body: bytes
    retrieved_at: str          # ISO-8601 UTC — vintage, pinned at first fetch
    status: int
    from_cache: bool
    source: str                # which registry source served this
    licence_class: str         # licensing of the data, for provenance

    def json(self):
        return json.loads(self.body)


class RateLimiter:
    """Enforce a minimum gap between requests to one host."""

    def __init__(self, requests_per_second: float):
        self._min_interval = 1.0 / requests_per_second
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if self._last_call and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


class Fetcher:
    """Fetch URLs from any registered source, caching raw bytes with provenance."""

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = cache_dir or config.CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # One throttle per host, created on first use.
        self._limiters: dict[str, RateLimiter] = {}

    # -- cache layout (keyed on the canonical URL, no credentials) ----------

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    def _body_path(self, url: str) -> Path:
        return self._cache_dir / f"{self._key(url)}.body"

    def _meta_path(self, url: str) -> Path:
        return self._cache_dir / f"{self._key(url)}.meta"

    def _read_cache(self, url: str, source: sources.Source) -> FetchResult | None:
        body_path, meta_path = self._body_path(url), self._meta_path(url)
        if not (body_path.exists() and meta_path.exists()):
            return None
        meta = json.loads(meta_path.read_text())
        return FetchResult(
            url=url,
            body=body_path.read_bytes(),
            retrieved_at=meta["retrieved_at"],
            status=meta["status"],
            from_cache=True,
            source=source.key,
            licence_class=source.licence_class,
        )

    def _write_cache(self, url: str, body: bytes, retrieved_at: str, status: int) -> None:
        self._body_path(url).write_bytes(body)
        self._meta_path(url).write_text(
            json.dumps(
                {"url": url, "retrieved_at": retrieved_at, "status": status},
                indent=2,
            )
        )

    # -- rate limiting ------------------------------------------------------

    def _limiter_for(self, source: sources.Source, host: str) -> RateLimiter:
        if host not in self._limiters:
            self._limiters[host] = RateLimiter(source.requests_per_second)
        return self._limiters[host]

    # -- authentication -----------------------------------------------------

    def _authorize(self, url: str, source: sources.Source) -> tuple[str, dict[str, str]]:
        """Return (request_url, headers) with credentials applied.

        The returned request_url may carry a key (Census/NASS/BEA); the caller
        keeps using the original `url` for cache + provenance.
        """
        headers = {"Accept-Encoding": "gzip, deflate", "Accept": "application/json"}

        if source.auth == "user_agent":
            # SEC: identify the caller in the User-Agent (required).
            headers["User-Agent"] = sources.api_key(source)
        elif source.auth == "bearer":
            headers["User-Agent"] = _default_user_agent()
            headers["Authorization"] = f"Bearer {sources.api_key(source)}"
        elif source.auth == "query_param":
            headers["User-Agent"] = _default_user_agent()
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}{source.auth_param}={sources.api_key(source)}", headers
        else:  # "none"
            headers["User-Agent"] = _default_user_agent()

        return url, headers

    # -- the one public method ---------------------------------------------

    def get(self, url: str, *, refresh: bool = False) -> FetchResult:
        """Fetch `url`, returning cached bytes when we already have them."""
        source = sources.for_url(url)

        if not refresh:
            cached = self._read_cache(url, source)
            if cached is not None:
                return cached

        request_url, headers = self._authorize(url, source)
        self._limiter_for(source, urllib_host(url)).wait()
        retrieved_at = datetime.now(timezone.utc).isoformat()

        request = urllib.request.Request(request_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = _read_maybe_gzip(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"{source.key} returned HTTP {exc.code} for {url}\n{detail}"
            ) from exc

        self._write_cache(url, body, retrieved_at, status)
        return FetchResult(
            url=url,
            body=body,
            retrieved_at=retrieved_at,
            status=status,
            from_cache=False,
            source=source.key,
            licence_class=source.licence_class,
        )


def urllib_host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower()


def _default_user_agent() -> str:
    """A polite identifier for sources that don't require the SEC contact.

    Reuses the SEC contact if it's set (so you're identifiable everywhere),
    otherwise a generic string. Never raises — only the SEC path is mandatory.
    """
    return os.environ.get(config.SEC_CONTACT_ENV, "").strip() or "Terminal Zero research bot"


def _read_maybe_gzip(response) -> bytes:
    raw = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        import gzip

        return gzip.decompress(raw)
    return raw
