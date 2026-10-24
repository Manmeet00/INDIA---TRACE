from datetime import datetime, timezone
import sqlite3
from typing import Any

from .schemas import EventCreate, Place, TraceCreate, TraceUpdate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def place_values(place: Place) -> tuple[Any, Any, Any]:
    return place.name, place.latitude, place.longitude


def trace_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tracking_code": row["tracking_code"],
        "title": row["title"],
        "category": row["category"],
        "status": row["status"],
        "description": row["description"],
        "origin": {"name": row["origin_name"], "latitude": row["origin_latitude"], "longitude": row["origin_longitude"]},
        "destination": {"name": row["destination_name"], "latitude": row["destination_latitude"], "longitude": row["destination_longitude"]},
        "current_location": {"name": row["current_location_name"], "latitude": row["current_latitude"], "longitude": row["current_longitude"]},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "trace_id": row["trace_id"], "status": row["status"],
        "message": row["message"],
        "location": {"name": row["location_name"], "latitude": row["latitude"], "longitude": row["longitude"]},
        "occurred_at": row["occurred_at"], "created_at": row["created_at"],
    }


def create_trace(connection: sqlite3.Connection, trace_id: str, payload: TraceCreate) -> sqlite3.Row:
    stamp = now_iso()
    connection.execute(
        """INSERT INTO traces (
            id, tracking_code, title, category, status, description,
            origin_name, origin_latitude, origin_longitude,
            destination_name, destination_latitude, destination_longitude,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trace_id, payload.tracking_code, payload.title, payload.category, payload.status.value,
         payload.description, *place_values(payload.origin), *place_values(payload.destination), stamp, stamp),
    )
    connection.execute(
        "INSERT INTO trace_events (id, trace_id, status, message, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (f"evt_{trace_id}", trace_id, payload.status.value, "Trace created", stamp, stamp),
    )
    return connection.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()


def update_trace(connection: sqlite3.Connection, row: sqlite3.Row, payload: TraceUpdate) -> sqlite3.Row:
    data = payload.model_dump(exclude_unset=True)
    mapping = {"title": "title", "category": "category", "description": "description"}
    values: dict[str, Any] = {column: getattr(data[key], "value", data[key]) for key, column in mapping.items() if key in data}
    for key in ("origin", "destination"):
        if key in data:
            name_col = f"{key}_name"
            lat_col = f"{key}_latitude"
            lon_col = f"{key}_longitude"
            place = data[key]
            values[name_col], values[lat_col], values[lon_col] = place.name, place.latitude, place.longitude
    if values:
        values["updated_at"] = now_iso()
        connection.execute(
            "UPDATE traces SET " + ", ".join(f"{column} = ?" for column in values) + " WHERE id = ?",
            (*values.values(), row["id"]),
        )
    return connection.execute("SELECT * FROM traces WHERE id = ?", (row["id"],)).fetchone()


def add_event(connection: sqlite3.Connection, trace_id: str, event_id: str, payload: EventCreate) -> sqlite3.Row:
    stamp = now_iso()
    occurred = (payload.occurred_at or datetime.now(timezone.utc)).isoformat()
    connection.execute(
        """INSERT INTO trace_events
        (id, trace_id, status, message, location_name, latitude, longitude, occurred_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, trace_id, payload.status.value, payload.message, *place_values(payload.location), occurred, stamp),
    )
    connection.execute(
        """UPDATE traces SET status = ?, current_location_name = ?, current_latitude = ?,
        current_longitude = ?, updated_at = ? WHERE id = ?""",
        (payload.status.value, *place_values(payload.location), stamp, trace_id),
    )
    return connection.execute("SELECT * FROM trace_events WHERE id = ?", (event_id,)).fetchone()
