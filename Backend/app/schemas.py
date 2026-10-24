from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TraceStatus(StrEnum):
    created = "created"
    in_transit = "in_transit"
    delayed = "delayed"
    delivered = "delivered"
    cancelled = "cancelled"


class Coordinates(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class Place(Coordinates):
    name: str | None = Field(default=None, max_length=200)


class TraceCreate(BaseModel):
    tracking_code: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    origin: Place = Field(default_factory=Place)
    destination: Place = Field(default_factory=Place)
    status: TraceStatus = TraceStatus.created

    @field_validator("tracking_code", "category", mode="before")
    @classmethod
    def trim_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class TraceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    origin: Place | None = None
    destination: Place | None = None

    @field_validator("title", "category", "origin", "destination", mode="before")
    @classmethod
    def reject_null_required_patch_values(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value.strip() if info.field_name in {"title", "category"} and isinstance(value, str) else value


class EventCreate(BaseModel):
    status: TraceStatus
    message: str = Field(min_length=1, max_length=1000)
    occurred_at: datetime | None = None
    location: Place = Field(default_factory=Place)

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    trace_id: str
    status: TraceStatus
    message: str
    location: Place
    occurred_at: datetime
    created_at: datetime


class TraceOut(BaseModel):
    id: str
    tracking_code: str
    title: str
    category: str
    status: TraceStatus
    description: str | None
    origin: Place
    destination: Place
    current_location: Place
    created_at: datetime
    updated_at: datetime


class TraceDetail(TraceOut):
    events: list[EventOut]


class TracePage(BaseModel):
    items: list[TraceOut]
    total: int
    limit: int
    offset: int


class DashboardSummary(BaseModel):
    total_traces: int
    by_status: dict[str, int]
    recent_events: list[EventOut]


class RoutePlanRequest(BaseModel):
    origin: str = Field(min_length=2, max_length=200)
    destination: str = Field(min_length=2, max_length=200)
    vehicle_type: str = Field(default="truck", pattern=r"^(truck|van|ambulance)$")
    priority: str = Field(default="balanced", pattern=r"^(balanced|fastest|shortest|cautious)$")


class IncidentFlag(BaseModel):
    reason: str = Field(pattern=r"^(wrong_location|outdated|duplicate|not_relevant|other)$")
    note: str | None = Field(default=None, max_length=500)


class FlagEntry(IncidentFlag):
    created_at: datetime


class ReviewEntry(BaseModel):
    previous_verification: str | None
    verification: str
    review_note: str
    location_changed: bool
    location_text: str | None
    latitude: float | None
    longitude: float | None
    reviewed_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    kind: str
    text: str
    approximate: bool = False


class IncidentOut(BaseModel):
    id: str
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: str | None
    published_estimate: datetime | None = None
    published_approximate: bool = False
    collected_at: datetime
    latitude: float | None
    longitude: float | None
    location_text: str | None
    verification: str
    freshness: str
    reviewed_at: datetime | None = None
    review_note: str | None = None
    publisher: str | None = None
    search_query: str | None = None
    search_kind: str | None = None
    last_seen_at: datetime | None = None
    published_source: str | None = None
    page_description: str | None = None
    page_excerpt: str | None = None
    page_author: str | None = None
    fetched_at: datetime | None = None
    fetch_error: str | None = None
    # Text heuristics for the reviewer; see app/evidence.py.
    mentions: dict[str, list[str]] = Field(default_factory=dict)
    report_signal: str | None = None
    event_type: str = "other"
    freshness_window_h: int = 24
    regions: list[str] = Field(default_factory=list)
    location_confidence: str = "none"
    # The town a report names, at its real coordinates; approximate, never the exact spot (app/places.py).
    approximate_location: dict[str, str | float] | None = None
    # The source's own video, post or preview picture (app/media.py): kind is youtube, instagram, facebook or image.
    media: dict[str, str] | None = None
    event_types: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    corroborating_ids: list[str] = Field(default_factory=list)
    evidence_status: str = "unverified"
    review_history: list[ReviewEntry] = Field(default_factory=list)
    open_flags: list[FlagEntry] = Field(default_factory=list)
    # Region, source and lifecycle (report 5, 6.5, 6.7, 7).
    districts: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    source_category: str = "other"
    lifecycle: str = "new"
    last_checked_at: datetime | None = None
    collection_run_id: str | None = None
    timeline: list[TimelineEntry] = Field(default_factory=list)


class CollectionRequest(BaseModel):
    """Optional targeted search (PPT: 'user-initiated search: district, road or event type')."""
    road: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9 .\-]+$")
    place: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z .\-']+$")
    event_type: str | None = Field(default=None, pattern=r"^(landslide|flood|closure|bridge|accident|construction|weather)$")
    window_days: int | None = Field(default=None, ge=1, le=3650)
    # Narrows the region's allowed source categories for this run.
    source_categories: list[str] | None = Field(default=None, min_length=1)

    @field_validator("source_categories")
    @classmethod
    def known_categories(cls, value):
        unknown = set(value or []) - {"official", "news", "social", "other"}
        if unknown:
            raise ValueError(f"unknown source categories: {', '.join(sorted(unknown))}")
        return value

    @field_validator("road", "place", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class CollectionRun(BaseModel):
    id: str
    trigger: str
    started_at: datetime
    finished_at: datetime
    searches: list[dict[str, str]]
    recency_minutes: int | None
    results: int
    stored: int
    duplicates: int
    failed_searches: int
    fetched: int
    fetch_failed: int
    duration_ms: int
    status: str
    searches_done: int = 0
    filtered: int = 0
    phase: str | None = None
    message: str | None = None


class CollectionResult(BaseModel):
    status: str
    collected: int
    duplicates: int
    message: str
    run_id: str | None = None
    incidents: list[IncidentOut]


class JobStarted(BaseModel):
    status: str
    run_id: str | None = None
    message: str


class RecheckRequest(BaseModel):
    """Which reports to re-check; without ids, the reports whose lifecycle says they are due."""
    incident_ids: list[str] | None = Field(default=None, min_length=1, max_length=30)


class RecheckResult(BaseModel):
    status: str
    checked: int
    fetched: int
    failed: int
    changed: int
    message: str
    run_id: str | None = None


class IncidentReview(BaseModel):
    """Location fields left out of the request are kept; fields sent as null are cleared."""
    verification: str = Field(pattern=r"^(confirmed|conflicting|unknown|unverified|dismissed|resolved)$")
    review_note: str = Field(min_length=3, max_length=1000)
    location_text: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("review_note", "location_text", mode="before")
    @classmethod
    def trim_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        sent_together = ("latitude" in self.model_fields_set) == ("longitude" in self.model_fields_set)
        if not sent_together or (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self
