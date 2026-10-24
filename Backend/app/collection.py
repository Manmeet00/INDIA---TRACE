"""TinyFish collection: Search finds candidate reports, Fetch reads their pages and re-checks them later.

Search (web and news) and Fetch are free within TinyFish's daily limits (12,000 searches,
1,000 fetched URLs). Results are stored as unverified evidence with the query and the run that
found them; nothing here decides whether a road is open.

Each run is written to collection_runs when it starts and updated as it goes, so a run started in
the background (see jobs.py) can be followed. Every check of a report's source is kept in
incident_checks.
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
from .evidence import normalize_source_url, source_category
from .monitoring import log_call
from .media import collect_preview_images
from .places import geocode_places, pending_places
from .regions import active_region
from .road_intelligence import _request_json, load_incidents

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"
FETCH_BATCH = 10  # Fetch accepts up to 10 URLs per request.
MAX_FETCH_PER_RUN = 30
SEARCH_ATTEMPTS = 2
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!\d)", re.IGNORECASE)  # "host:8080/path" is a port, not a scheme
NOT_CONFIGURED = "TinyFish is not configured. Add TINYFISH_API_KEY to Backend/.env to collect public web evidence."


def default_searches() -> list[dict[str, str]]:
    """The active region's corridor searches (app/regions.py; for the pilot see docs/PILOT.md)."""
    return [dict(search) for search in active_region().searches]


def targeted_searches(road: str | None, place: str | None, event_type: str | None) -> list[dict[str, str]]:
    """A user-initiated search for one road, place or event type, run on web and news."""
    query = " ".join(part for part in (road, place, event_type or "disruption", "road update") if part)
    return [{"query": query, "kind": "web"}, {"query": query, "kind": "news"}]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_run(connection: sqlite3.Connection, trigger: str, searches: list[dict[str, str]], recency_minutes: int | None) -> str:
    """Log a run as running before any work starts, and commit so it is visible at once."""
    run_id = f"run_{uuid4().hex}"
    started = _now()
    connection.execute(
        """INSERT INTO collection_runs (id, trigger, started_at, finished_at, searches, recency_minutes, results, stored,
        duplicates, failed_searches, fetched, fetch_failed, duration_ms, status, phase)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 'running', ?)""",
        (run_id, trigger, started, started, json.dumps(searches), recency_minutes, "searching" if searches else "reading pages"),
    )
    connection.commit()
    return run_id


def _update_run(connection: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    connection.execute("UPDATE collection_runs SET " + ", ".join(f"{key} = ?" for key in fields) + " WHERE id = ?",
                       (*fields.values(), run_id))
    connection.commit()  # progress is read by other requests while the run continues


def _finish_run(connection: sqlite3.Connection, run_id: str, status: str, message: str, **fields: Any) -> None:
    started = connection.execute("SELECT started_at FROM collection_runs WHERE id = ?", (run_id,)).fetchone()["started_at"]
    duration = round((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds() * 1000)
    _update_run(connection, run_id, status=status, message=message, phase=None, finished_at=_now(), duration_ms=duration, **fields)


def _check(connection: sqlite3.Connection, incident_id: str, kind: str, outcome: str, run_id: str | None,
           detail: str | None = None, when: str | None = None) -> None:
    connection.execute(
        "INSERT INTO incident_checks (id, incident_id, checked_at, kind, outcome, detail, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (f"ck_{uuid4().hex}", incident_id, when or _now(), kind, outcome, detail, run_id))


def _search(connection: sqlite3.Connection, search: dict[str, str], key: str, recency_minutes: int | None) -> list[dict[str, Any]]:
    params = {"query": search["query"]}
    if search["kind"] == "news":
        params["domain_type"] = "news"
    if recency_minutes:
        params["recency_minutes"] = recency_minutes
    for attempt in range(SEARCH_ATTEMPTS):
        started = time.monotonic()
        try:
            response = _request_json(f"{SEARCH_URL}?{urlencode(params)}", {"X-API-Key": key}, timeout=30)
        except HTTPException:
            log_call(connection, "tinyfish_search", "failed", started)
            if attempt + 1 == SEARCH_ATTEMPTS:
                raise
            time.sleep(1)
            continue
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            log_call(connection, "tinyfish_search", "failed", started)
            raise HTTPException(status_code=502, detail="TinyFish Search returned an unexpected response.")
        log_call(connection, "tinyfish_search", "ok", started)
        return [item for item in response["results"] if isinstance(item, dict)]
    return []


def _text(value: Any, limit: int) -> str:
    return (value.strip() if isinstance(value, str) else "")[:limit]


def _dicts(response: Any, key: str) -> list[dict[str, Any]]:
    """The objects under response[key]; anything malformed in a provider response is skipped."""
    items = response.get(key) if isinstance(response, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _store_result(connection: sqlite3.Connection, item: dict[str, Any], search: dict[str, str], now: str,
                  run_id: str, allowed: tuple[str, ...]) -> str | None:
    """Insert one search hit; returns its id, "duplicate" if the URL is known, "filtered" if its source
    category is not allowed, or None if unusable."""
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
    if source_category(source_url, search["kind"]) not in allowed:
        return "filtered"
    published_at = _text(item.get("published_at") or item.get("date"), 100) or None
    publisher = _text(item.get("publisher"), 200) or None
    source_name = publisher or _text(item.get("site_name"), 200) or "Public web source"
    incident_id = f"in_{uuid4().hex}"
    try:
        connection.execute(
            """INSERT INTO incidents (id, title, summary, source_name, source_url, published_at, collected_at,
            verification, content_hash, publisher, search_query, search_kind, last_seen_at, published_source,
            collection_run_id, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (incident_id, title, snippet, source_name, source_url, published_at, now,
             sha256((title + snippet + source_url).encode()).hexdigest(), publisher, search["query"], search["kind"],
             now, "search" if published_at else None, run_id, now),
        )
    except sqlite3.IntegrityError:
        # Seen again: record the check instead of storing a second copy.
        row = connection.execute("SELECT id, collection_run_id FROM incidents WHERE source_url = ?", (source_url,)).fetchone()
        if row is None:
            raise
        # Several searches in one run often return the same page; that is one sighting, not several checks.
        seen_this_run = row["collection_run_id"] == run_id or connection.execute(
            "SELECT 1 FROM incident_checks WHERE incident_id = ? AND run_id = ? AND outcome = 'seen_again'", (row["id"], run_id)).fetchone()
        if not seen_this_run:
            connection.execute("UPDATE incidents SET last_seen_at = ?, last_checked_at = ? WHERE id = ?", (now, now, row["id"]))
            _check(connection, row["id"], "search", "seen_again", run_id, when=now)
        return "duplicate"
    return incident_id


def _fetch_pages(connection: sqlite3.Connection, incident_ids: list[str], key: str, run_id: str, kind: str = "fetch") -> tuple[int, int]:
    """Read report pages with TinyFish Fetch; keeps the page description, text excerpt, author and date.

    kind "fetch" is the first read after collection; "recheck" compares the page with the last read.
    A page that cannot be read is recorded as such; it never changes a report's status.
    """
    fetched = failed = 0
    rows = [connection.execute("SELECT id, source_url, page_hash FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            for incident_id in incident_ids[:MAX_FETCH_PER_RUN]]
    for start in range(0, len(rows), FETCH_BATCH):
        batch = rows[start:start + FETCH_BATCH]
        now = _now()
        started = time.monotonic()
        try:
            response = _request_json(FETCH_URL, {"X-API-Key": key}, {"urls": [row["source_url"] for row in batch], "format": "markdown"}, timeout=90)
        except HTTPException as exc:
            log_call(connection, "tinyfish_fetch", "failed", started, units=len(batch))
            for row in batch:
                connection.execute("UPDATE incidents SET fetch_error = ?, fetched_at = ? WHERE id = ?", (str(exc.detail)[:300], now, row["id"]))
                _check(connection, row["id"], kind, "page_unreadable", run_id, str(exc.detail)[:300], now)
            failed += len(batch)
            continue
        log_call(connection, "tinyfish_fetch", "ok", started, units=len(batch))
        by_url = {row["source_url"]: row for row in batch}
        for result in _dicts(response, "results"):
            url = _text(result.get("url"), 2000)
            row = by_url.get(url) or (by_url.get(normalize_source_url(url)) if url else None)
            if row is None:
                continue
            description, text = _text(result.get("description"), 1000) or None, _text(result.get("text"), 4000) or None
            page_hash = sha256(f"{description or ''}\n{text or ''}".encode()).hexdigest()
            page_date = _text(result.get("published_date"), 100) or None
            connection.execute(
                """UPDATE incidents SET page_description = ?, page_excerpt = ?, page_author = ?, fetched_at = ?, fetch_error = NULL,
                page_hash = ?, last_checked_at = ?,
                published_at = COALESCE(published_at, ?),
                published_source = CASE WHEN published_at IS NULL AND ? IS NOT NULL THEN 'page' ELSE published_source END
                WHERE id = ?""",
                (description, text, _text(result.get("author"), 200) or None, now, page_hash, now, page_date, page_date, row["id"]),
            )
            outcome = "page_read" if kind == "fetch" or not row["page_hash"] else \
                "page_changed" if row["page_hash"] != page_hash else "page_unchanged"
            _check(connection, row["id"], kind, outcome, run_id, when=now)
            fetched += 1
        for error in _dicts(response, "errors"):
            row = by_url.get(_text(error.get("url"), 2000))
            if row is not None:
                detail = _text(error.get("error"), 300)
                connection.execute("UPDATE incidents SET fetch_error = ?, fetched_at = ? WHERE id = ?", (detail, now, row["id"]))
                _check(connection, row["id"], kind, "page_unreadable", run_id, detail, now)
                failed += 1
    return fetched, failed


def collect_candidates(connection: sqlite3.Connection, searches: list[dict[str, str]] | None = None,
                       trigger: str = "manual", recency_minutes: int | None = None,
                       source_categories: list[str] | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Run searches, store new results as unverified evidence, then read their pages.

    source_categories narrows the region's allowed categories (official, news, social, other) for this run.
    Pass run_id when the run was already logged with start_run (background jobs).
    """
    key = get_settings().tinyfish_api_key
    if not key:
        return {"status": "not_configured", "collected": 0, "duplicates": 0, "message": NOT_CONFIGURED, "incidents": []}
    searches = searches or default_searches()
    region_allowed = active_region().source_categories
    allowed = tuple(category for category in region_allowed if not source_categories or category in source_categories)
    run_id = run_id or start_run(connection, trigger, searches, recency_minutes)
    results = duplicates = failed_searches = filtered = 0
    new_ids: list[str] = []
    for done, search in enumerate(searches, start=1):
        try:
            items = _search(connection, search, key, recency_minutes)
        except HTTPException:
            failed_searches += 1
            items = []
        results += len(items)
        now = _now()
        for item in items:
            outcome = _store_result(connection, item, search, now, run_id, allowed)
            if outcome == "duplicate":
                duplicates += 1
            elif outcome == "filtered":
                filtered += 1
            elif outcome:
                new_ids.append(outcome)
        _update_run(connection, run_id, searches_done=done, results=results, stored=len(new_ids), duplicates=duplicates,
                    filtered=filtered, failed_searches=failed_searches, phase="searching" if done < len(searches) else "reading pages")
    fetched, fetch_failed = _fetch_pages(connection, new_ids, key, run_id)
    located = locate_places(connection, run_id)
    if new_ids:
        _update_run(connection, run_id, phase="reading preview images")
        collect_preview_images(connection, new_ids)
    status = "failed" if failed_searches == len(searches) else "partial" if failed_searches else "complete"
    if status == "failed":
        message = "TinyFish could not return search results. Try again later."
    elif results == 0:
        message = (f"TinyFish found no reports for {len(searches)} searches. "
                   "No reports does not mean the road is clear; check official advisories.")
    else:
        message = (f"{len(new_ids)} new reports from {len(searches)} searches; {fetched} pages read with TinyFish Fetch. "
                   "Search results are unverified evidence candidates; the exact spot is unknown until a reviewer confirms it.")
    if located["found"]:
        message += f" {located['found']} newly named towns placed on the map (approximate)."
    if filtered:
        message += f" {filtered} results from sources outside the allowed categories ({', '.join(allowed)}) were skipped."
    if failed_searches and status != "failed":
        message = f"{failed_searches} of {len(searches)} TinyFish searches failed. " + message
    _finish_run(connection, run_id, status, message, fetched=fetched, fetch_failed=fetch_failed)
    if status == "failed":
        raise HTTPException(status_code=502, detail=message)  # the failed run stays in the log
    return {"status": status, "collected": len(new_ids), "duplicates": duplicates, "message": message, "run_id": run_id,
            "incidents": load_incidents(connection, 100)}


def locate_places(connection: sqlite3.Connection, run_id: str | None = None) -> dict[str, Any]:
    """Look up the real coordinates of towns named in reports that have not been placed yet."""
    names = pending_places(connection, load_incidents(connection))
    if not names:
        return {"looked_up": 0, "found": 0, "not_found": 0, "failed": 0}
    if run_id:
        _update_run(connection, run_id, phase="locating places")
    return geocode_places(connection, names)


def due_for_recheck(incidents: list[dict[str, Any]]) -> list[str]:
    """Reports whose lifecycle says their source should be checked again, newest first."""
    due = [item for item in incidents if item["lifecycle"] == "needs_recheck"]
    due.sort(key=lambda item: item["published_estimate"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [item["id"] for item in due[:MAX_FETCH_PER_RUN]]


def recheck_reports(connection: sqlite3.Connection, incident_ids: list[str] | None = None, trigger: str = "recheck",
                    run_id: str | None = None) -> dict[str, Any]:
    """Read report pages again with TinyFish Fetch (report 6.5 and 7.9). Without ids, rechecks the reports due.

    A changed page is flagged for the reviewer; an unreadable page is recorded but never taken to mean
    the road has reopened. Statuses are not changed here.
    """
    key = get_settings().tinyfish_api_key
    if not key:
        return {"status": "not_configured", "checked": 0, "fetched": 0, "failed": 0, "changed": 0, "message": NOT_CONFIGURED}
    ids = due_for_recheck(load_incidents(connection)) if incident_ids is None else incident_ids[:MAX_FETCH_PER_RUN]
    run_id = run_id or start_run(connection, trigger, [], None)
    fetched, failed = _fetch_pages(connection, ids, key, run_id, kind="recheck")
    changed = connection.execute("SELECT COUNT(*) FROM incident_checks WHERE run_id = ? AND outcome = 'page_changed'", (run_id,)).fetchone()[0]
    if not ids:
        status, message = "complete", "No reports are due for a re-check."
    else:
        status = "failed" if fetched == 0 else "partial" if failed else "complete"
        message = (f"Re-checked {len(ids)} source{'s' if len(ids) != 1 else ''}: {fetched} read ({changed} changed since the last read), "
                   f"{failed} could not be read. An unreadable page does not mean the road has reopened.")
    _finish_run(connection, run_id, status, message, fetched=fetched, fetch_failed=failed)
    return {"status": status, "checked": len(ids), "fetched": fetched, "failed": failed, "changed": changed,
            "message": message, "run_id": run_id}


def collection_runs(connection: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(row), "searches": json.loads(row["searches"])} for row in rows]


def collection_run(connection: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM collection_runs WHERE id = ?", (run_id,)).fetchone()
    return {**dict(row), "searches": json.loads(row["searches"])} if row else None
