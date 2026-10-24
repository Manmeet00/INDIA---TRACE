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


class ReviewEntry(BaseModel):
    previous_verification: str | None
    verification: str
    review_note: str
    location_changed: bool
    location_text: str | None
    latitude: float | None
    longitude: float | None
    reviewed_at: datetime


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
    # Text heuristics for the reviewer; see app/evidence.py.
    mentions: dict[str, list[str]] = Field(default_factory=dict)
    report_signal: str | None = None
    event_type: str = "other"
    event_types: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    corroborating_ids: list[str] = Field(default_factory=list)
    evidence_status: str = "unverified"
    review_history: list[ReviewEntry] = Field(default_factory=list)


class CollectionResult(BaseModel):
    status: str
    collected: int
    duplicates: int
    message: str
    incidents: list[IncidentOut]


class IncidentReview(BaseModel):
    """Location fields left out of the request are kept; fields sent as null are cleared."""
    verification: str = Field(pattern=r"^(confirmed|conflicting|unknown|unverified|dismissed)$")
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
