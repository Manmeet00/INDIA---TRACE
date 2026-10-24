import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import uuid4
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import jobs
from .collection import (NOT_CONFIGURED, collect_candidates, collection_run, collection_runs, default_searches, locate_places,
                         recheck_reports, targeted_searches)
from .config import get_settings
from .database import get_connection, initialize_database
from .monitoring import log_route_plan, metrics
from .regions import active_region, coverage_by_state
from .repository import add_event, create_trace, event_from_row, trace_from_row, update_trace
from .road_intelligence import load_incidents, plan_route
from .schemas import (CollectionRequest, CollectionResult, CollectionRun, DashboardSummary, EventCreate, EventOut, IncidentFlag,
                      IncidentOut, IncidentReview, JobStarted, RecheckRequest, RecheckResult, RoutePlanRequest, TraceCreate,
                      TraceDetail, TracePage, TraceStatus, TraceUpdate)

settings = get_settings()
logger = logging.getLogger("indiatrace")
# When the scheduled collection runs next (None when the schedule is off), shown by /api/health.
schedule: dict[str, str | None] = {"next_collection_at": None}


def _scheduled_collection() -> None:
    """Pilot searches, then a re-check of the reports that are due. Skipped while another run is going."""
    try:
        with jobs.exclusive(), get_connection() as connection:
            try:
                collect_candidates(connection, trigger="scheduled", recency_minutes=get_settings().collection_window_days * 1440 or None)
            finally:
                recheck_reports(connection, trigger="scheduled_recheck")
    except HTTPException as exc:
        if exc.detail != jobs.BUSY:
            raise


def _seconds_until_due(interval_minutes: int) -> float:
    """Time left until a collection is due, counted from the last finished one, so restarts do not collect again."""
    try:
        with get_connection() as connection:
            last = connection.execute("""SELECT MAX(finished_at) FROM collection_runs
                WHERE trigger IN ('scheduled', 'manual', 'targeted') AND status != 'running'""").fetchone()[0]
    except sqlite3.Error:
        return 0
    if not last:
        return 0
    due = datetime.fromisoformat(last) + timedelta(minutes=interval_minutes)
    return max(0.0, (due - datetime.now(timezone.utc)).total_seconds())


async def _collect_periodically(interval_minutes: int, first_delay_s: float) -> None:
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            await asyncio.to_thread(_scheduled_collection)
        except Exception:  # A failed run is logged in collection_runs; keep the schedule alive.
            logger.exception("Scheduled collection failed")
        schedule["next_collection_at"] = (datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat()
        await asyncio.sleep(interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        initialize_database()
    except sqlite3.Error:
        # Start anyway so /api/health can report the problem; data endpoints answer 503 until it is fixed.
        logger.exception("Could not initialise the database at %s", settings.database_path)
    task = None
    interval = get_settings().collection_interval_minutes  # read at startup, not import, so tests and restarts see .env changes
    if interval > 0:
        delay = _seconds_until_due(interval)
        schedule["next_collection_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        task = asyncio.create_task(_collect_periodically(interval, delay))
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
    interval = get_settings().collection_interval_minutes
    return {"status": "ok", "service": settings.app_name, "collection_interval_minutes": interval,
            "next_collection_at": schedule["next_collection_at"] if interval > 0 else None}


@app.post("/api/routes/plan")
def post_route_plan(payload: RoutePlanRequest):
    started = time.monotonic()
    status_code, routes = 200, None
    try:
        plan = plan_route(payload)
        routes = len(plan["routes"])
        return plan
    except HTTPException as exc:
        status_code = exc.status_code
        raise
    finally:
        with get_connection() as connection:
            log_route_plan(connection, round((time.monotonic() - started) * 1000), status_code, routes)


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
        # A review is a check by a person, so it also counts as the report's latest check.
        values = {"verification": payload.verification, "reviewed_at": reviewed_at, "last_checked_at": reviewed_at,
                  "review_note": payload.review_note, **location}
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


def _collection_plan(payload: CollectionRequest | None) -> tuple[list[dict[str, str]], str, int | None, list[str] | None]:
    """Searches, trigger, recency and source categories for a request: region searches unless it names a target."""
    payload = payload or CollectionRequest()
    targeted = payload.road or payload.place or payload.event_type
    searches = targeted_searches(payload.road, payload.place, payload.event_type) if targeted else default_searches()
    return searches, "targeted" if targeted else "manual", payload.window_days * 1440 if payload.window_days else None, payload.source_categories


@app.post("/api/collection/run", response_model=CollectionResult)
def run_collection(payload: CollectionRequest | None = None):
    """Runs the collection and answers when it has finished. The dashboard uses /api/collection/jobs instead."""
    searches, trigger, recency, categories = _collection_plan(payload)
    with jobs.exclusive(), get_connection() as connection:
        return collect_candidates(connection, searches, trigger, recency, categories)


@app.post("/api/collection/jobs", response_model=JobStarted, status_code=status.HTTP_202_ACCEPTED)
def start_collection_job(response: Response, payload: CollectionRequest | None = None):
    """Starts a collection in the background; follow it with GET /api/collection/runs/{run_id}."""
    if not get_settings().tinyfish_api_key:
        response.status_code = status.HTTP_200_OK
        return {"status": "not_configured", "message": NOT_CONFIGURED}
    searches, trigger, recency, categories = _collection_plan(payload)
    run_id = jobs.start(trigger, searches, recency,
                        lambda connection, run_id: collect_candidates(connection, searches, trigger, recency, categories, run_id))
    return {"status": "running", "run_id": run_id, "message": f"Collection started: {len(searches)} searches."}


@app.post("/api/recheck", response_model=RecheckResult)
def recheck(payload: RecheckRequest | None = None):
    """Reads report pages again now. Without ids, re-checks the reports whose lifecycle says they are due."""
    with jobs.exclusive(), get_connection() as connection:
        return recheck_reports(connection, payload.incident_ids if payload else None)


@app.post("/api/recheck/jobs", response_model=JobStarted, status_code=status.HTTP_202_ACCEPTED)
def start_recheck_job(response: Response, payload: RecheckRequest | None = None):
    if not get_settings().tinyfish_api_key:
        response.status_code = status.HTTP_200_OK
        return {"status": "not_configured", "message": NOT_CONFIGURED}
    ids = payload.incident_ids if payload else None
    run_id = jobs.start("recheck", [], None, lambda connection, run_id: recheck_reports(connection, ids, run_id=run_id))
    return {"status": "running", "run_id": run_id, "message": "Re-check started."}


@app.post("/api/incidents/{incident_id}/recheck", response_model=IncidentOut)
def recheck_incident(incident_id: str):
    """Reads one report's page again and returns the report with the outcome in its timeline."""
    with get_connection() as connection:
        if connection.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Incident evidence not found")
    if not get_settings().tinyfish_api_key:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    with jobs.exclusive(), get_connection() as connection:
        recheck_reports(connection, [incident_id], trigger="recheck")
        return find_incident(connection, incident_id)


@app.get("/api/collection/runs", response_model=list[CollectionRun])
def list_collection_runs(limit: int = Query(default=10, ge=1, le=100)):
    with get_connection() as connection:
        return collection_runs(connection, limit)


@app.get("/api/collection/runs/{run_id}", response_model=CollectionRun)
def get_collection_run(run_id: str):
    with get_connection() as connection:
        run = collection_run(connection, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Collection run not found")
    return run


@app.get("/api/region")
def region_overview():
    """The active region's configuration (report 6.7) and its coverage by state."""
    region = active_region()
    with get_connection() as connection:
        incidents = load_incidents(connection)
    return {
        "id": region.id, "name": region.name, "corridor": region.corridor, "states": region.states,
        "places": [{"name": place.name, "state": place.state, "district": place.district, "aliases": place.aliases}
                   for place in region.places if place.district],
        "road_aliases": region.road_aliases, "searches": region.searches, "source_categories": region.source_categories,
        "freshness_window_h": region.freshness_window_h, "scripts": region.scripts,
        "coverage": coverage_by_state(region, incidents),
        "coverage_note": "A state with no recent reports is a coverage gap, not evidence that its roads are clear.",
    }


@app.post("/api/places/locate")
def locate_named_places():
    """Looks up the real coordinates of towns named in stored reports (OpenStreetMap Nominatim, one request
    a second). Collection does this for new reports; this fills in reports collected before."""
    with jobs.exclusive(), get_connection() as connection:
        return locate_places(connection)


@app.get("/api/map-config")
def map_config():
    """Which base map the dashboard draws. Mappls needs its static key in the browser; the key should be
    restricted to the dashboard's domains in the Mappls console. Without a key the dashboard uses OpenStreetMap."""
    key = get_settings().mappls_static_key
    return {"provider": "mappls", "mappls_key": key} if key else {"provider": "osm", "mappls_key": None}


@app.get("/api/metrics")
def get_metrics():
    """Monitoring and evaluation figures computed from logs and stored reports; unmeasured values are null."""
    with get_connection() as connection:
        return metrics(connection, load_incidents(connection))


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
