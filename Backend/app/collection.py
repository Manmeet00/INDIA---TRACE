"""TinyFish collection: Search finds candidate reports, Fetch reads their pages.

Search (web and news) and Fetch are free within TinyFish's daily limits (12,000 searches,
1,000 fetched URLs). Results are stored as unverified evidence with the query that found
them; nothing here decides whether a road is open.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
import time
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from fastapi import HTTPException

from .config import get_settings
from .evidence import normalize_source_url
from .road_intelligence import _request_json, load_incidents

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"
FETCH_BATCH = 10  # Fetch accepts up to 10 URLs per request.
MAX_FETCH_PER_RUN = 30
SEARCH_ATTEMPTS = 2
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!\d)", re.IGNORECASE)  # "host:8080/path" is a port, not a scheme

# Pilot corridor: NH-6 / NH-306, Guwahati – Shillong – Silchar – Aizawl. See docs/PILOT.md.
# News searches return a publisher and date; narrow highway queries return nothing there, so they stay broad.
PILOT_SEARCHES = [
    {"query": "NH-6 Guwahati Shillong road closure landslide update", "kind": "web"},
    {"query": "NH-6 Shillong Silchar Sonapur Ratacherra landslide traffic", "kind": "web"},
    {"query": "NH-306 Silchar Aizawl road blocked landslide", "kind": "web"},
    {"query": "Meghalaya Mizoram Barak Valley highway closure latest", "kind": "web"},
    {"query": "Meghalaya landslide highway", "kind": "news"},
    {"query": "Mizoram Barak Valley road landslide", "kind": "news"},
]


def targeted_searches(road: str | None, place: str | None, event_type: str | None) -> list[dict[str, str]]:
    """A user-initiated search for one road, place or event type, run on web and news."""
    query = " ".join(part for part in (road, place, event_type or "disruption", "road update") if part)
    return [{"query": query, "kind": "web"}, {"query": query, "kind": "news"}]


def _search(search: dict[str, str], key: str, recency_minutes: int | None) -> list[dict[str, Any]]:
    params = {"query": search["query"]}
    if search["kind"] == "news":
        params["domain_type"] = "news"
    if recency_minutes:
        params["recency_minutes"] = recency_minutes
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            response = _request_json(f"{SEARCH_URL}?{urlencode(params)}", {"X-API-Key": key}, timeout=30)
        except HTTPException:
            if attempt + 1 == SEARCH_ATTEMPTS:
                raise
            time.sleep(1)
            continue
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise HTTPException(status_code=502, detail="TinyFish Search returned an unexpected response.")
        return [item for item in response["results"] if isinstance(item, dict)]
    return []


def _text(value: Any, limit: int) -> str:
    return (value.strip() if isinstance(value, str) else "")[:limit]


def _store_result(connection: sqlite3.Connection, item: dict[str, Any], search: dict[str, str], now: str) -> str | None:
    """Insert one search hit; returns its id, "duplicate" if the URL is known, or None if unusable."""
    raw_url = _text(item.get("url"), 2000)
    if not raw_url or ("://" not in raw_url and URL_SCHEME.match(raw_url)):
        return None  # javascript:, mailto: and similar are never source links
    source_url = raw_url if "://" in raw_url else f"https://{raw_url.lstrip('/')}"
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    source_url = normalize_source_url(source_url)
    title = _text(item.get("title"), 300) or "Untitled public source"
    snippet = _text(item.get("snippet"), 3000)
    if not snippet:
        return None
    published_at = _text(item.get("published_at") or item.get("date"), 100) or None
    publisher = _text(item.get("publisher"), 200) or None
    source_name = publisher or _text(item.get("site_name"), 200) or "Public web source"
    incident_id = f"in_{uuid4().hex}"
    try:
        connection.execute(
            """INSERT INTO incidents (id, title, summary, source_name, source_url, published_at, collected_at,
            verification, content_hash, publisher, search_query, search_kind, last_seen_at, published_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, ?, ?, ?, ?)""",
            (incident_id, title, snippet, source_name, source_url, published_at, now,
             sha256((title + snippet + source_url).encode()).hexdigest(), publisher, search["query"], search["kind"],
             now, "search" if published_at else None),
        )
    except sqlite3.IntegrityError:
        # Seen again: record the re-check instead of storing a second copy.
        updated = connection.execute("UPDATE incidents SET last_seen_at = ? WHERE source_url = ?", (now, source_url))
        if updated.rowcount:
            return "duplicate"
        raise
    return incident_id


def _fetch_pages(connection: sqlite3.Connection, incident_ids: list[str], key: str) -> tuple[int, int]:
    """Read collected pages with TinyFish Fetch; keeps the page description, text excerpt, author and date."""
    fetched = failed = 0
    rows = [connection.execute("SELECT id, source_url, published_at FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            for incident_id in incident_ids[:MAX_FETCH_PER_RUN]]
    for start in range(0, len(rows), FETCH_BATCH):
        batch = rows[start:start + FETCH_BATCH]
        now = datetime.now(timezone.utc).isoformat()
        try:
            response = _request_json(FETCH_URL, {"X-API-Key": key}, {"urls": [row["source_url"] for row in batch], "format": "markdown"}, timeout=90)
        except HTTPException as exc:
            for row in batch:
                connection.execute("UPDATE incidents SET fetch_error = ?, fetched_at = ? WHERE id = ?", (str(exc.detail)[:300], now, row["id"]))
            failed += len(batch)
            continue
        by_url = {row["source_url"]: row for row in batch}
        for result in response.get("results", []) if isinstance(response, dict) else []:
            row = by_url.get(result.get("url")) or by_url.get(normalize_source_url(result.get("url") or ""))
            if row is None:
                continue
            page_date = _text(result.get("published_date"), 100) or None
            connection.execute(
                """UPDATE incidents SET page_description = ?, page_excerpt = ?, page_author = ?, fetched_at = ?, fetch_error = NULL,
                published_at = COALESCE(published_at, ?),
                published_source = CASE WHEN published_at IS NULL AND ? IS NOT NULL THEN 'page' ELSE published_source END
                WHERE id = ?""",
                (_text(result.get("description"), 1000) or None, _text(result.get("text"), 4000) or None,
                 _text(result.get("author"), 200) or None, now, page_date, page_date, row["id"]),
            )
            fetched += 1
        for error in response.get("errors", []) if isinstance(response, dict) else []:
            row = by_url.get(error.get("url"))
            if row is not None:
                connection.execute("UPDATE incidents SET fetch_error = ?, fetched_at = ? WHERE id = ?", (_text(error.get("error"), 300), now, row["id"]))
                failed += 1
    return fetched, failed


def collect_candidates(connection: sqlite3.Connection, searches: list[dict[str, str]] | None = None,
                       trigger: str = "manual", recency_minutes: int | None = None) -> dict[str, Any]:
    key = get_settings().tinyfish_api_key
    if not key:
        return {"status": "not_configured", "collected": 0, "duplicates": 0,
                "message": "TinyFish is not configured. Add TINYFISH_API_KEY to Backend/.env to collect public web evidence.", "incidents": []}
    searches = searches or PILOT_SEARCHES
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    results = duplicates = failed_searches = 0
    new_ids: list[str] = []
    for search in searches:
        try:
            items = _search(search, key, recency_minutes)
        except HTTPException:
            failed_searches += 1
            continue
        results += len(items)
        now = datetime.now(timezone.utc).isoformat()
        for item in items:
            outcome = _store_result(connection, item, search, now)
            if outcome == "duplicate":
                duplicates += 1
            elif outcome:
                new_ids.append(outcome)
    fetched, fetch_failed = _fetch_pages(connection, new_ids, key)
    status = "failed" if failed_searches == len(searches) else "partial" if failed_searches else "complete"
    connection.execute(
        """INSERT INTO collection_runs (id, trigger, started_at, finished_at, searches, recency_minutes, results, stored,
        duplicates, failed_searches, fetched, fetch_failed, duration_ms, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"run_{uuid4().hex}", trigger, started, datetime.now(timezone.utc).isoformat(), json.dumps(searches), recency_minutes,
         results, len(new_ids), duplicates, failed_searches, fetched, fetch_failed, round((time.monotonic() - clock) * 1000), status),
    )
    if status == "failed":
        connection.commit()  # Keep the failed run in the log even though the request errors.
        raise HTTPException(status_code=502, detail="TinyFish could not return search results. Try again later.")
    message = (f"{len(new_ids)} new reports from {len(searches)} searches; {fetched} pages read with TinyFish Fetch. "
               "Search results are unverified evidence candidates; location is unknown until a reviewer confirms it.")
    if failed_searches:
        message = f"{failed_searches} of {len(searches)} TinyFish searches failed. " + message
    return {"status": status, "collected": len(new_ids), "duplicates": duplicates, "message": message,
            "incidents": load_incidents(connection, 100)}


def collection_runs(connection: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(row), "searches": json.loads(row["searches"])} for row in rows]
