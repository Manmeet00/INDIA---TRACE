import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging
from uuid import uuid4
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .collection import collect_candidates, collection_runs, targeted_searches
from .config import get_settings
from .database import get_connection, initialize_database
from .repository import add_event, create_trace, event_from_row, trace_from_row, update_trace
from .road_intelligence import load_incidents, plan_route
from .schemas import (CollectionRequest, CollectionResult, CollectionRun, DashboardSummary, EventCreate, EventOut, IncidentFlag,
                      IncidentOut, IncidentReview, RoutePlanRequest, TraceCreate, TraceDetail, TracePage, TraceStatus, TraceUpdate)

settings = get_settings()
logger = logging.getLogger("indiatrace")


def _scheduled_collection() -> None:
    with get_connection() as connection:
        collect_candidates(connection, trigger="scheduled", recency_minutes=settings.collection_window_days * 1440 or None)


async def _collect_periodically(interval_minutes: int) -> None:
    while True:
        try:
            await asyncio.to_thread(_scheduled_collection)
        except Exception:  # A failed run is logged in collection_runs; keep the schedule alive.
            logger.exception("Scheduled collection failed")
        await asyncio.sleep(interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        initialize_database()
    except sqlite3.Error:
        # Start anyway so /api/health can report the problem; data endpoints answer 503 until it is fixed.
        logger.exception("Could not initialise the database at %s", settings.database_path)
    task = asyncio.create_task(_collect_periodically(settings.collection_interval_minutes)) if settings.collection_interval_minutes > 0 else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


DATABASE_UNAVAILABLE = "The INDIA-TRACE database is unavailable. Check DATABASE_PATH and free disk space, then restart the API."


@app.exception_handler(sqlite3.Error)
async def database_error(_: Request, exc: sqlite3.Error) -> JSONResponse:
    """Any database failure is a 503 with a plain explanation, never a bare 500 without CORS headers."""
    logger.error("Database error: %s", exc)
    busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
    return JSONResponse(status_code=503, content={"detail": "The database is busy. Try again in a moment." if busy else DATABASE_UNAVAILABLE})


def find_trace(connection: sqlite3.Connection, trace_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return row


@app.get("/health")
@app.get("/api/health")
def health():
    # Reading a table, not just SELECT 1, also catches a database that was never initialised.
    with get_connection() as connection:
        connection.execute("SELECT 1 FROM incidents LIMIT 1")
    return {"status": "ok", "service": settings.app_name}


@app.post("/api/routes/plan")
def post_route_plan(payload: RoutePlanRequest):
    return plan_route(payload)


@app.get("/api/incidents", response_model=list[IncidentOut])
def list_incidents(limit: int = Query(default=100, ge=1, le=500)):
    with get_connection() as connection:
        return load_incidents(connection, limit)


def find_incident(connection: sqlite3.Connection, incident_id: str) -> dict:
    """One report, annotated against the others so duplicate and conflict hints are included."""
    incident = next((item for item in load_incidents(connection) if item["id"] == incident_id), None)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident evidence not found")
    return incident


@app.get("/api/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: str):
    with get_connection() as connection:
        return find_incident(connection, incident_id)


@app.patch("/api/incidents/{incident_id}/review", response_model=IncidentOut)
def review_incident(incident_id: str, payload: IncidentReview):
    reviewed_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        row = connection.execute("SELECT id, verification FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Incident evidence not found")
        location = {field: getattr(payload, field) for field in ("location_text", "latitude", "longitude")
                    if field in payload.model_fields_set}
        values = {"verification": payload.verification, "reviewed_at": reviewed_at, "review_note": payload.review_note, **location}
        connection.execute(
            "UPDATE incidents SET " + ", ".join(f"{column} = ?" for column in values) + " WHERE id = ?",
            (*values.values(), incident_id),
        )
        # Every review is kept so status changes and their reasons are never overwritten.
        connection.execute(
            """INSERT INTO incident_reviews (id, incident_id, previous_verification, verification, review_note,
            location_changed, location_text, latitude, longitude, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"rv_{uuid4().hex}", incident_id, row["verification"], payload.verification, payload.review_note, bool(location),
             location.get("location_text"), location.get("latitude"), location.get("longitude"), reviewed_at),
        )
        # A review answers any open correction flags.
        connection.execute("UPDATE incident_flags SET resolved_at = ? WHERE incident_id = ? AND resolved_at IS NULL",
                           (reviewed_at, incident_id))
        return find_incident(connection, incident_id)


@app.post("/api/incidents/{incident_id}/flags", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def flag_incident(incident_id: str, payload: IncidentFlag):
    """User correction (report section 5): flags a record for review without changing its status."""
    with get_connection() as connection:
        if connection.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Incident evidence not found")
        connection.execute(
            "INSERT INTO incident_flags (id, incident_id, reason, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"fl_{uuid4().hex}", incident_id, payload.reason, (payload.note or "").strip() or None,
             datetime.now(timezone.utc).isoformat()),
        )
        return find_incident(connection, incident_id)


@app.post("/api/collection/run", response_model=CollectionResult)
def run_collection(payload: CollectionRequest | None = None):
    """Pilot searches by default; a road, place or event type runs a targeted search instead."""
    payload = payload or CollectionRequest()
    targeted = payload.road or payload.place or payload.event_type
    searches = targeted_searches(payload.road, payload.place, payload.event_type) if targeted else None
    with get_connection() as connection:
        return collect_candidates(connection, searches, "targeted" if targeted else "manual",
                                  payload.window_days * 1440 if payload.window_days else None)


@app.get("/api/collection/runs", response_model=list[CollectionRun])
def list_collection_runs(limit: int = Query(default=10, ge=1, le=100)):
    with get_connection() as connection:
        return collection_runs(connection, limit)


@app.get(f"{settings.api_prefix}/summary", response_model=DashboardSummary)
def summary():
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        counts = connection.execute("SELECT status, COUNT(*) AS count FROM traces GROUP BY status").fetchall()
        events = connection.execute("SELECT * FROM trace_events ORDER BY occurred_at DESC LIMIT 10").fetchall()
    return {"total_traces": total, "by_status": {row["status"]: row["count"] for row in counts},
            "recent_events": [event_from_row(row) for row in events]}


@app.get(f"{settings.api_prefix}/traces", response_model=TracePage)
def list_traces(
    status_filter: TraceStatus | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    clauses: list[str] = []
    params: list[str] = []
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter.value)
    if category:
        clauses.append("category = ?")
        params.append(category.strip())
    if q:
        clauses.append("(tracking_code LIKE ? OR title LIKE ? OR description LIKE ?)")
        term = f"%{q.strip()}%"
        params.extend([term, term, term])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM traces" + where, params).fetchone()[0]
        rows = connection.execute("SELECT * FROM traces" + where + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                                  (*params, limit, offset)).fetchall()
    return {"items": [trace_from_row(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.post(f"{settings.api_prefix}/traces", response_model=TraceDetail, status_code=status.HTTP_201_CREATED)
def post_trace(payload: TraceCreate):
    trace_id = f"tr_{uuid4().hex}"
    try:
        with get_connection() as connection:
            row = create_trace(connection, trace_id, payload)
            events = connection.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY occurred_at DESC", (trace_id,)).fetchall()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tracking code already exists") from exc
    return {**trace_from_row(row), "events": [event_from_row(event) for event in events]}


@app.get(f"{settings.api_prefix}/traces/{{trace_id}}", response_model=TraceDetail)
def get_trace(trace_id: str):
    with get_connection() as connection:
        row = find_trace(connection, trace_id)
        events = connection.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY occurred_at DESC",
                                    (trace_id,)).fetchall()
    return {**trace_from_row(row), "events": [event_from_row(event) for event in events]}


@app.patch(f"{settings.api_prefix}/traces/{{trace_id}}", response_model=TraceDetail)
def patch_trace(trace_id: str, payload: TraceUpdate):
    with get_connection() as connection:
        row = update_trace(connection, find_trace(connection, trace_id), payload)
        events = connection.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY occurred_at DESC",
                                    (trace_id,)).fetchall()
    return {**trace_from_row(row), "events": [event_from_row(event) for event in events]}


@app.delete(f"{settings.api_prefix}/traces/{{trace_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trace(trace_id: str):
    with get_connection() as connection:
        find_trace(connection, trace_id)
        connection.execute("DELETE FROM traces WHERE id = ?", (trace_id,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(f"{settings.api_prefix}/traces/{{trace_id}}/events", response_model=list[EventOut])
def list_events(trace_id: str):
    with get_connection() as connection:
        find_trace(connection, trace_id)
        rows = connection.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY occurred_at DESC",
                                  (trace_id,)).fetchall()
    return [event_from_row(row) for row in rows]


@app.post(f"{settings.api_prefix}/traces/{{trace_id}}/events", response_model=EventOut,
          status_code=status.HTTP_201_CREATED)
def post_event(trace_id: str, payload: EventCreate):
    try:
        with get_connection() as connection:
            find_trace(connection, trace_id)
            row = add_event(connection, trace_id, f"ev_{uuid4().hex}", payload)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Could not add trace event") from exc
    return event_from_row(row)
