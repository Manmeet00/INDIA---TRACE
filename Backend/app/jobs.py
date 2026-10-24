"""Collection and re-checks as background jobs (report 11: collection must not hold up the user).

A job is logged in collection_runs before it starts, so the caller gets a run id at once and
follows progress with GET /api/collection/runs/{id}. Only one collection or re-check runs at a
time, whether started by a person, a background job or the schedule.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import sqlite3
import threading
from typing import Callable, Iterator

from fastapi import HTTPException

from .collection import _finish_run, start_run
from .database import get_connection

logger = logging.getLogger("indiatrace")
_running = threading.Lock()
BUSY = "A collection or re-check is already running. Wait for it to finish, then try again."


@contextmanager
def exclusive() -> Iterator[None]:
    """Hold the collection lock for a run in the current thread; 409 if another run holds it."""
    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=BUSY)
    try:
        yield
    finally:
        _running.release()


def start(trigger: str, searches: list[dict[str, str]], recency_minutes: int | None,
          work: Callable[[sqlite3.Connection, str], object]) -> str:
    """Log a run, then call work(connection, run_id) on a background thread. Returns the run id."""
    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=BUSY)
    try:
        with get_connection() as connection:
            run_id = start_run(connection, trigger, searches, recency_minutes)
    except BaseException:
        _running.release()
        raise

    def run() -> None:
        try:
            with get_connection() as connection:
                work(connection, run_id)
        except HTTPException:
            pass  # a failed collection is already recorded on its run
        except Exception as exc:  # recorded on the run so the person following it sees why it stopped
            logger.exception("Background run %s failed", run_id)
            try:
                with get_connection() as connection:
                    _finish_run(connection, run_id, "failed", f"The run stopped because of an internal error ({type(exc).__name__}). Check the API log.")
            except sqlite3.Error:
                logger.exception("Could not record the failure of run %s", run_id)
        finally:
            _running.release()

    threading.Thread(target=run, name=f"india-trace-{run_id}", daemon=True).start()
    return run_id
