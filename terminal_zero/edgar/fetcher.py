"""A disciplined SEC EDGAR fetcher.

Three jobs, and only these three:

  1. Rate limit    — never hammer the SEC; stay under their published ceiling.
  2. Identify      — send the required User-Agent contact header.
  3. Cache + record — write every raw response to disk with the time we
                      retrieved it, so a figure's *vintage* is captured at the
                      moment it entered the store and never silently changes.

Point (3) is the provenance foundation. Everything downstream — parsing,
rooms, derivations — trusts that the bytes on disk are exactly what the SEC
returned, and that `retrieved_at` says when. So the cache is not a performance
trick we can treat casually; it is the system of record for "what the source
said, and when we asked."
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from terminal_zero import config


@dataclass(frozen=True)
class FetchResult:
    """One fetch, plus the provenance that makes it trustworthy.

    `retrieved_at` is the moment the bytes came off the network the *first*
    time. On a cache hit we deliberately return that original timestamp, not
    "now" — the vintage of a figure is when the SEC gave it to us, not when we
    happened to re-read our own cache.
    """

    url: str
    body: bytes
    retrieved_at: str          # ISO-8601 UTC, e.g. "2026-09-01T12:00:00+00:00"
    status: int                # HTTP status from the original network fetch
    from_cache: bool           # True if served from disk, False if hit network

    def json(self):
        """Decode the body as JSON. Raises if the body isn't valid JSON."""
        return json.loads(self.body)


class RateLimiter:
    """Enforce a minimum gap between requests.

    Dead simple on purpose: record when we last returned control, and if the
    next call comes too soon, sleep the difference. One process, one throttle.
    """

    def __init__(self, requests_per_second: float):
        self._min_interval = 1.0 / requests_per_second
        self._last_call = 0.0  # monotonic seconds; 0 means "never called yet"

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if self._last_call and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


class Fetcher:
    """Fetch URLs from the SEC, caching raw bytes to disk with provenance."""

    def __init__(
        self,
        contact: str | None = None,
        cache_dir: Path | None = None,
        requests_per_second: float = config.DEFAULT_REQUESTS_PER_SECOND,
    ):
        # Resolve the contact string now so we fail fast (before any network
        # call) if it isn't configured.
        self._contact = contact or config.sec_contact()
        self._cache_dir = cache_dir or config.CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = RateLimiter(requests_per_second)

    # -- cache layout -------------------------------------------------------
    #
    # Each URL maps to two files, keyed by a hash of the URL:
    #   <hash>.body   — the raw response bytes, untouched
    #   <hash>.meta   — JSON provenance: the url, retrieved_at, status
    #
    # We keep the body byte-exact (no re-encoding) so that what's on disk is
    # provably what the SEC sent.

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    def _body_path(self, url: str) -> Path:
        return self._cache_dir / f"{self._key(url)}.body"

    def _meta_path(self, url: str) -> Path:
        return self._cache_dir / f"{self._key(url)}.meta"

    def _read_cache(self, url: str) -> FetchResult | None:
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
        )

    def _write_cache(self, url: str, body: bytes, retrieved_at: str, status: int) -> None:
        self._body_path(url).write_bytes(body)
        self._meta_path(url).write_text(
            json.dumps(
                {"url": url, "retrieved_at": retrieved_at, "status": status},
                indent=2,
            )
        )

    # -- the one public method ---------------------------------------------

    def get(self, url: str, *, refresh: bool = False) -> FetchResult:
        """Fetch `url`, returning cached bytes when we already have them.

        Pass `refresh=True` to force a new network fetch (e.g. to pick up a
        later vintage). Even then we keep the old cache overwritten by the new
        one — vintage history across restatements is handled later, in the
        store, not here.
        """
        if not refresh:
            cached = self._read_cache(url)
            if cached is not None:
                return cached

        self._limiter.wait()
        retrieved_at = datetime.now(timezone.utc).isoformat()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._contact,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = _read_maybe_gzip(response)
        except urllib.error.HTTPError as exc:
            # Surface the SEC's own error body — it usually explains why
            # (bad User-Agent, unknown CIK, throttling). Fail loudly.
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"SEC returned HTTP {exc.code} for {url}\n{detail}"
            ) from exc

        self._write_cache(url, body, retrieved_at, status)
        return FetchResult(
            url=url,
            body=body,
            retrieved_at=retrieved_at,
            status=status,
            from_cache=False,
        )


def _read_maybe_gzip(response) -> bytes:
    """Read a urllib response, transparently gunzipping if needed."""
    raw = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        import gzip

        return gzip.decompress(raw)
    return raw
