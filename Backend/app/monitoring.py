"""Monitoring and evaluation metrics (report sections 8, 11 and 13).

External calls and route-plan timings are logged as they happen, and the metrics below are computed
from those logs and from stored reports. Nothing is estimated: a metric with no data is reported as
not measured (None), and every rate comes with the count it was computed from.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import statistics
import time
from typing import Any

# TinyFish's free daily allowances for Search and Fetch (see docs/PILOT.md).
TINYFISH_DAILY_LIMITS = {"tinyfish_search": 12000, "tinyfish_fetch": 1000}


def log_call(connection: sqlite3.Connection, service: str, outcome: str, started: float | None = None, units: int = 1) -> None:
    """Record one call to an external service: outcome is ok, cache, stale_cache or failed."""
    duration = round((time.monotonic() - started) * 1000) if started is not None else None
    connection.execute("INSERT INTO provider_calls (called_at, service, outcome, units, duration_ms) VALUES (?, ?, ?, ?, ?)",
                       (datetime.now(timezone.utc).isoformat(), service, outcome, units, duration))


def log_route_plan(connection: sqlite3.Connection, duration_ms: int, status: int, routes: int | None) -> None:
    connection.execute("INSERT INTO route_plans (planned_at, duration_ms, status, routes) VALUES (?, ?, ?, ?)",
                       (datetime.now(timezone.utc).isoformat(), duration_ms, status, routes))


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def metrics(connection: sqlite3.Connection, incidents: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    active = [item for item in incidents if item["verification"] not in ("dismissed", "resolved")]

    # Freshness lag: from an exact source publication time to when INDIA-TRACE collected the report.
    exact = [(datetime.fromisoformat(item["collected_at"]), item["published_estimate"]) for item in incidents
             if item["published_estimate"] and not item["published_approximate"]]
    lags = [(collected - published).total_seconds() / 3600 for collected, published in exact if collected >= published]
    # Reviewer decisions stand in for a manual check of extraction: dismissed means "not a relevant road report".
    reviewed = [item for item in incidents if item["review_history"]]
    kept = [item for item in reviewed if item["verification"] != "dismissed"]
    grouped = {item["id"] for item in incidents if item["duplicate_ids"]}

    evidence = {
        "total": len(incidents),
        "active": len(active),
        "by_status": _count(item["evidence_status"] for item in incidents),
        "by_lifecycle": _count(item["lifecycle"] for item in incidents),
        "by_source_category": _count(item["source_category"] for item in incidents),
        "stale_share": _rate(sum(item["freshness"] == "stale" for item in active), len(active)),
        "unknown_time_share": _rate(sum(item["freshness"] == "unknown" for item in active), len(active)),
        "located_share": _rate(sum(item["latitude"] is not None for item in active), len(active)),
        "in_duplicate_groups_share": _rate(len(grouped), len(incidents)),
        "freshness_lag_hours": {"n": len(lags), "median": _round(statistics.median(lags)) if lags else None,
                                "p90": _round(_percentile(lags, 0.9))},
        "reviewer_kept_share": {"n": len(reviewed), "value": _rate(len(kept), len(reviewed))},
    }

    since = (now - timedelta(days=30)).isoformat()
    runs = connection.execute("SELECT * FROM collection_runs WHERE started_at >= ? AND status != 'running'", (since,)).fetchall()
    fetch_attempts = sum(run["fetched"] + run["fetch_failed"] for run in runs)
    collection = {
        "runs_30d": len(runs),
        "by_status": _count(run["status"] for run in runs),
        "median_duration_s": _round(statistics.median(run["duration_ms"] for run in runs) / 1000) if runs else None,
        "search_failure_share": _rate(sum(run["failed_searches"] for run in runs), sum(len(_searches(run)) for run in runs)),
        "fetch_failure_share": _rate(sum(run["fetch_failed"] for run in runs), fetch_attempts),
        "last_finished_at": max((run["finished_at"] for run in runs), default=None),
    }

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    providers = {}
    for row in connection.execute(
            """SELECT service, outcome, COUNT(*) AS calls, SUM(units) AS units FROM provider_calls
            WHERE called_at >= ? GROUP BY service, outcome""", (day_start,)):
        entry = providers.setdefault(row["service"], {"calls": 0, "units": 0, "by_outcome": {}})
        entry["calls"] += row["calls"]
        entry["units"] += row["units"]
        entry["by_outcome"][row["outcome"]] = row["calls"]
    for service, limit in TINYFISH_DAILY_LIMITS.items():
        entry = providers.setdefault(service, {"calls": 0, "units": 0, "by_outcome": {}})
        used = entry["units"] - entry["by_outcome"].get("cache", 0)
        entry["free_daily_limit"] = limit
        entry["free_limit_used_share"] = _rate(used, limit)

    plans = connection.execute("SELECT duration_ms, status FROM route_plans WHERE planned_at >= ?",
                               ((now - timedelta(days=7)).isoformat(),)).fetchall()
    ok = [row["duration_ms"] / 1000 for row in plans if row["status"] == 200]
    routing = {"plans_7d": len(plans), "failed_7d": sum(row["status"] != 200 for row in plans),
               "p50_s": _round(_percentile(ok, 0.5)), "p95_s": _round(_percentile(ok, 0.95))}

    return {"generated_at": now, "evidence": evidence, "collection": collection,
            "providers_today": providers, "providers_day_start": day_start, "routing": routing}


def _searches(run: sqlite3.Row) -> list:
    return json.loads(run["searches"])


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
