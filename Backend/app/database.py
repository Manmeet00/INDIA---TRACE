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
CREATE TABLE IF NOT EXISTS provider_cache (
    url TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    path: Path = get_settings().database_path
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
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
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(incidents)")}
        if "reviewed_at" not in columns:
            connection.execute("ALTER TABLE incidents ADD COLUMN reviewed_at TEXT")
        if "review_note" not in columns:
            connection.execute("ALTER TABLE incidents ADD COLUMN review_note TEXT")
