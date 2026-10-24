import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_settings


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    tracking_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    description TEXT,
    origin_name TEXT,
    origin_latitude REAL,
    origin_longitude REAL,
    destination_name TEXT,
    destination_latitude REAL,
    destination_longitude REAL,
    current_location_name TEXT,
    current_latitude REAL,
    current_longitude REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);
CREATE INDEX IF NOT EXISTS idx_traces_category ON traces(category);
CREATE INDEX IF NOT EXISTS idx_traces_updated_at ON traces(updated_at DESC);
CREATE TABLE IF NOT EXISTS trace_events (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace_time
    ON trace_events(trace_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    location_text TEXT,
    verification TEXT NOT NULL DEFAULT 'unverified',
    content_hash TEXT NOT NULL,
    reviewed_at TEXT,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_collected_at ON incidents(collected_at DESC);
CREATE TABLE IF NOT EXISTS incident_reviews (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    previous_verification TEXT,
    verification TEXT NOT NULL,
    review_note TEXT NOT NULL,
    location_changed INTEGER NOT NULL DEFAULT 0,
    location_text TEXT,
    latitude REAL,
    longitude REAL,
    reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incident_reviews_incident ON incident_reviews(incident_id, reviewed_at DESC);
CREATE TABLE IF NOT EXISTS collection_runs (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    searches TEXT NOT NULL,
    recency_minutes INTEGER,
    results INTEGER NOT NULL,
    stored INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    failed_searches INTEGER NOT NULL,
    fetched INTEGER NOT NULL,
    fetch_failed INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_flags (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
-- Every time a report's source was checked: seen again in a search, its page read on collection, or re-checked.
CREATE TABLE IF NOT EXISTS incident_checks (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_incident_checks_incident ON incident_checks(incident_id, checked_at DESC);
-- Monitoring (report 8 and 13): external calls and route-plan timings. No route endpoints are stored.
CREATE TABLE IF NOT EXISTS provider_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at TEXT NOT NULL,
    service TEXT NOT NULL,
    outcome TEXT NOT NULL,
    units INTEGER NOT NULL DEFAULT 1,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_provider_calls_time ON provider_calls(called_at);
CREATE TABLE IF NOT EXISTS route_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planned_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status INTEGER NOT NULL,
    routes INTEGER
);
-- Real coordinates of places named in reports, from OpenStreetMap Nominatim. A report placed this way is
-- "approximate": the town is known, the exact spot on the road is not.
CREATE TABLE IF NOT EXISTS place_locations (
    name TEXT PRIMARY KEY,
    latitude REAL,
    longitude REAL,
    display_name TEXT,
    geocoded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_cache (
    url TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


# Columns added after the first release; existing databases gain them on startup.
ADDED_COLUMNS = {
    "incidents": dict.fromkeys(("reviewed_at", "review_note", "publisher", "search_query", "search_kind", "last_seen_at",
                                "published_source", "page_description", "page_excerpt", "page_author", "fetched_at",
                                "fetch_error", "collection_run_id", "last_checked_at", "page_hash", "page_image",
                                "page_image_checked_at"), "TEXT"),
    "collection_runs": {"searches_done": "INTEGER NOT NULL DEFAULT 0", "filtered": "INTEGER NOT NULL DEFAULT 0",
                        "phase": "TEXT", "message": "TEXT"},
}


def connect() -> sqlite3.Connection:
    path: Path = get_settings().database_path
    if str(path) != ":memory:":
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # Reported like any other database failure.
            raise sqlite3.OperationalError(f"cannot create the database folder {path.parent}: {exc}") from exc
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)
        for table, added in ADDED_COLUMNS.items():
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, kind in added.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        # Reports from before re-checks were recorded: their last check is when a search last saw them.
        connection.execute("UPDATE incidents SET last_checked_at = COALESCE(last_seen_at, collected_at) WHERE last_checked_at IS NULL")
        # A run still marked running when the API starts was cut off by a restart.
        connection.execute("UPDATE collection_runs SET status = 'interrupted', phase = NULL WHERE status = 'running'")
