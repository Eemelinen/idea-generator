"""HTTP and the 24 h on-disk cache shared by the `fi` clients (pxweb, prh, eurostat).

The HTTP layer is a plain callable (`Transport`), so tests replay the IF-200 recordings and never
touch the network. Each client caches under its own `cache/<name>/` directory, keyed by method,
URL and body; a cache hit reports the original retrieval time, which is the one to cite.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ideaforge import config

TIMEOUT_S = 10
CACHE_TTL = timedelta(hours=24)

# method, url, JSON body (None for GET) → parsed JSON response
Transport = Callable[[str, str, dict[str, Any] | None], Any]


class FiDataError(Exception):
    """A request, lookup or filter that cannot be answered; the message is meant for the user."""


def requests_transport(user_agent: str) -> Transport:
    """The live transport: plain `requests` with `truststore` TLS, a UA string and a 10 s timeout."""

    def transport(method: str, url: str, body: dict[str, Any] | None) -> Any:
        import requests
        import truststore

        truststore.inject_into_ssl()
        headers = {"User-Agent": user_agent}
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=TIMEOUT_S)
            else:
                r = requests.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise FiDataError(f"{method} {url} failed: {type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise FiDataError(f"{method} {url} → HTTP {r.status_code}: {r.text.strip()[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise FiDataError(f"{method} {url} did not return JSON") from e

    return transport


@dataclass(frozen=True)
class Response:
    method: str
    url: str
    body: dict[str, Any] | None
    data: Any
    retrieved_at: datetime
    from_cache: bool


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class CachedClient:
    """Requests through the 24 h cache in cache/<cache_name>/ (keyed by method, URL and body)."""

    def __init__(self, transport: Transport, cache_name: str, now: Callable[[], datetime] = now_utc) -> None:
        self.transport = transport
        self.cache_name = cache_name
        self.now = now

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> Response:
        key = json.dumps([method, url, body], ensure_ascii=False, sort_keys=True)
        path = config.CACHE_DIR / self.cache_name / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
        now = self.now()
        if path.is_file():
            cached = read_cache_entry(path)  # None if unreadable: fetch again and overwrite it
            if cached is not None and now - cached[1] < CACHE_TTL:
                return Response(method, url, body, cached[0], cached[1], from_cache=True)
        data = self.transport(method, url, body)
        entry = {"method": method, "url": url, "body": body, "retrieved_at": now.isoformat(), "data": data}
        # Write then rename, so a killed process never leaves a truncated entry that counts as cached.
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return Response(method, url, body, data, now, from_cache=False)


def read_cache_entry(path: Path) -> tuple[Any, datetime] | None:
    """(data, retrieved_at) of a cache file, or None if it is not a JSON object with `data` and an
    aware ISO `retrieved_at` (the shape `CachedClient.request` writes)."""
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entry, dict) or "data" not in entry:
            return None
        retrieved_at = datetime.fromisoformat(entry["retrieved_at"])
    except (ValueError, KeyError, TypeError):
        return None
    return (entry["data"], retrieved_at) if retrieved_at.tzinfo is not None else None


def request_lines(resp: Response) -> list[str]:
    """The request as printed on stderr: method + URL, the body if any, the retrieval time."""
    lines = [f"request: {resp.method} {resp.url}"]
    if resp.body is not None:
        lines.append("query: " + json.dumps(resp.body, ensure_ascii=False, separators=(",", ":")))
    cached = " (from cache)" if resp.from_cache else ""
    lines.append(f"retrieved_at: {resp.retrieved_at.isoformat()}{cached}")
    return lines


def request_json(resp: Response) -> dict[str, Any]:
    return {
        "method": resp.method,
        "url": resp.url,
        "query": resp.body,
        "retrieved_at": resp.retrieved_at.isoformat(),
        "from_cache": resp.from_cache,
    }
