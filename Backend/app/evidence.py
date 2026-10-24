"""Cross-report hints for reviewers: near-duplicates, mentioned roads and places, possible conflicts.

These are text heuristics. They never change a report's verification state or location;
the reviewer decides what they mean.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import math
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .regions import REGIONS, active_region, alias_pattern, scripts_in

HIGHWAY = re.compile(r"\b(?:NH|National\s+Highway|Highway\s+No\.?)[\s\-–:(]*(?:NH[\s\-]*)?0*(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
CLOSURE = re.compile(r"\b(blocked|blockade|closed|closure|snapped|cut off|suspended|collapsed?|collapses|washed (?:away|off)|standstill|stranded)\b", re.IGNORECASE)
REOPENING = re.compile(r"\b(restored|restores|reopened|re-opened|reopens|resumed|open for traffic|normalcy)\b", re.IGNORECASE)
# Checked in this order; the first match is the report's primary event_type.
EVENT_TYPES = (
    ("landslide", re.compile(r"\b(landslides?|mudslides?|rockslides?|rockfalls?|rock fall|land slip)\b", re.IGNORECASE)),
    ("flood", re.compile(r"\b(flood(?:s|ing|ed)?|waterlogg(?:ed|ing)|inundat\w*|flash floods?)\b", re.IGNORECASE)),
    ("bridge", re.compile(r"\bbridges?\b", re.IGNORECASE)),
    ("accident", re.compile(r"\b(accidents?|crash(?:ed|es)?|collisions?|overturned)\b", re.IGNORECASE)),
    ("construction", re.compile(r"\b(construction|repairs?|maintenance|road ?works?|widening)\b", re.IGNORECASE)),
    ("closure", CLOSURE),
    ("weather", re.compile(r"\b(heavy rain\w*|rainfall|downpours?|cloudbursts?|cyclone|storms?)\b", re.IGNORECASE)),
)


@lru_cache
def _region_patterns(region_id: str) -> tuple[re.Pattern, re.Pattern, list[tuple[re.Pattern, str]]]:
    """Place, state and road-alias patterns for a region. Places match case-sensitively, longest name first."""
    region = REGIONS[region_id]
    names = sorted(region.place_index, key=len, reverse=True)
    place = re.compile(r"\b(" + "|".join(re.escape(name) for name in names) + r")\b")
    states = sorted({*region.states, *region.state_aliases}, key=len, reverse=True)
    state = re.compile(r"\b(" + "|".join(re.escape(name) for name in states) + r")\b")
    aliases = [(alias_pattern(name), road) for name, road in region.road_aliases.items()]
    return place, state, aliases


# The search engine's note that a result lacks some query words ("Missing: closure | Show results with: closure").
# It is not the source's text, and its words ("closure") would otherwise set the report's event type.
SEARCH_FOOTER = re.compile(r"\s*\b(?:Missing|Must include):\s[^|]*(?:\|\s*(?:Show results with|Must include):?[^|]*)*$")
# Search hits that sell a trip or a ride rather than report on a road, judged by the title.
LISTING = re.compile(r"\b(tour packages?|taxis?|cab (?:service|booking)s?|car rentals?|hotels?|near me)\b|₹", re.IGNORECASE)


def clean_snippet(text: str) -> str:
    return SEARCH_FOOTER.sub("", text or "").strip()


COARSE_RELATIVE = re.compile(r"(week|month|year)s?\s+ago$", re.IGNORECASE)
STOPWORDS = {"the", "and", "for", "has", "have", "had", "was", "were", "are", "that", "this", "with", "from", "after",
             "due", "its", "into", "over", "near", "along", "amid", "been", "which", "their", "more", "than"}
TRACKING_PARAMS = {"fbclid", "gclid", "igsh", "igshid", "hl", "ref", "ref_src", "s", "si"}
DUPLICATE_SIMILARITY = 0.6
CONFLICT_WINDOW_S = 72 * 3600


PAGE_SCOPED_HOSTS = {"facebook.com", "m.facebook.com"}
# Reel and video URLs on these hosts do not show who posted them, so they cannot prove independence.
UNATTRIBUTABLE_HOSTS = {"instagram.com", "youtube.com", "youtu.be", "x.com", "twitter.com"}


def publisher(url: str | None) -> str | None:
    """Who published a source, as far as its URL shows; None when posters cannot be told apart."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").removeprefix("www.")
    if not host or host in UNATTRIBUTABLE_HOSTS:
        return None
    if host in PAGE_SCOPED_HOSTS:
        page = parts.path.strip("/").split("/")[0].lower()
        return f"{host}/{page}" if page else None
    return host


# Source categories (report 7: allowed source categories; 9: an authoritative source can corroborate).
OFFICIAL_SUFFIXES = (".gov.in", ".nic.in")
SOCIAL_HOSTS = {"facebook.com", "m.facebook.com", "instagram.com", "youtube.com", "youtu.be", "x.com", "twitter.com",
                "reddit.com", "threads.net", "t.me"}
# News sites seen in pilot collections; any result from TinyFish news search also counts as news.
NEWS_HOSTS = {"timesofindia.indiatimes.com", "indiatodayne.in", "barakbulletin.com", "morungexpress.com", "sentinelassam.com",
              "assamtribune.com", "hindustantimes.com", "ndtv.com", "eastmojo.com", "nenow.in", "thehindu.com",
              "indianexpress.com", "theshillongtimes.com", "highlandpost.com", "nagalandpost.com", "imphalfreepress.com"}


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


def source_category(url: str | None, search_kind: str | None = None) -> str:
    """official (government domains), news, social or other; decided from the URL and how it was found."""
    host = _host(url)
    if host.endswith(OFFICIAL_SUFFIXES) or host in {"gov.in", "nic.in"}:
        return "official"
    if host in SOCIAL_HOSTS:
        return "social"
    if search_kind == "news" or host in NEWS_HOSTS:
        return "news"
    return "other"


def evidence_status(item: dict[str, Any]) -> str:
    """One label in the project's evidence vocabulary. Stale outranks confirmed so old reports never read as current."""
    verification = item.get("verification", "unverified")
    if verification in ("dismissed", "resolved"):
        return verification
    if verification == "conflicting" or item["conflict_ids"]:
        return "conflicting"
    if item.get("freshness") == "stale":
        return "stale"
    if verification == "confirmed":
        return "confirmed"
    if item["corroborating_ids"] or item.get("source_category") == "official":
        return "corroborated"
    return "unknown" if verification == "unknown" else "unverified"


LIFECYCLE_DEFAULT_RECHECK_S = 24 * 3600


def lifecycle(item: dict[str, Any], now: datetime | None = None) -> str:
    """Where a report is in its life (report 6.5): new, needs_recheck, stale, resolved or dismissed.

    A fresh report needs a re-check once half its freshness window has passed since it was published
    or last checked; a report without a source time needs one a day after its last check.
    Nothing here marks a report resolved: only a reviewer, with an authoritative update, does that.
    """
    if item.get("verification") in ("dismissed", "resolved"):
        return item["verification"]
    if item["freshness"] == "stale":
        return "stale"
    now = now or datetime.now(timezone.utc)
    checked = item.get("last_checked_at")
    checked_age = (now - checked).total_seconds() if checked else math.inf
    if item["freshness"] == "unknown":
        return "needs_recheck" if checked_age > LIFECYCLE_DEFAULT_RECHECK_S else "new"
    half_window = item["freshness_window_h"] * 3600 / 2
    published_age = (now - item["published_estimate"]).total_seconds()
    return "needs_recheck" if min(published_age, checked_age) > half_window else "new"


def freshness(published: datetime | None, approximate: bool, window_s: float = 24 * 3600) -> str:
    if published is None:
        return "unknown"
    age_seconds = (datetime.now(timezone.utc) - published).total_seconds()
    if age_seconds < 0:
        # A date-only value can be up to a day ahead of UTC (for example a date in IST).
        if not approximate or age_seconds < -86400:
            return "unknown"
        age_seconds = 0
    return "fresh" if age_seconds <= window_s else "stale"


def location_confidence(item: dict[str, Any]) -> str:
    """precise: reviewer-entered coordinates; approximate: placed at the one town the report names;
    road/place: only named in text; none: no location at all."""
    if item.get("latitude") is not None and item.get("longitude") is not None:
        return "precise"
    if item.get("approximate_location"):
        return "approximate"
    if item["mentions"]["highways"]:
        return "road_mentioned"
    return "place_mentioned" if item["mentions"]["places"] else "none"


def normalize_source_url(url: str) -> str:
    """Drop fragments, tracking parameters and trailing slashes so reposted links deduplicate."""
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")]
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2 and word not in STOPWORDS}


def _signal(text: str) -> str | None:
    closure, reopening = bool(CLOSURE.search(text)), bool(REOPENING.search(text))
    return "mixed" if closure and reopening else "closure" if closure else "reopening" if reopening else None


def _dated_closely(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """True when both reports have publication times precise enough to be about the same moment."""
    times: list[datetime] = []
    for item in (first, second):
        if item["published_estimate"] is None or COARSE_RELATIVE.search(item["published_at"] or ""):
            return False
        times.append(item["published_estimate"])
    return abs((times[0] - times[1]).total_seconds()) <= CONFLICT_WINDOW_S


SAME_PLACE_M = 1000
PREPOSITION = r"\b(?:at|near|in|from|between)\s+(?:the\s+)?"


def report_place(text: str, places: list[Any]) -> Any | None:
    """The town a report is about: the only locatable town it names, or the first one it puts after
    "at", "near", "in", "from" or "between". Several towns without that cue are ambiguous: None."""
    towns = [place for place in places if place.locatable]
    if len(towns) == 1:
        return towns[0]
    for place in towns:
        names = "|".join(re.escape(name) for name in (place.name, *place.aliases))
        if re.search(PREPOSITION + r"(?:" + names + r")\b", text):
            return place
    return None



def _same_place_and_time(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Reviewer-located reports of the same event type within 1 km, published close together (report 6.4)."""
    if None in (first.get("latitude"), first.get("longitude"), second.get("latitude"), second.get("longitude")):
        return False
    lat = math.radians((first["latitude"] + second["latitude"]) / 2)
    dx = math.radians(second["longitude"] - first["longitude"]) * math.cos(lat) * 6_371_000
    dy = math.radians(second["latitude"] - first["latitude"]) * 6_371_000
    return (math.hypot(dx, dy) <= SAME_PLACE_M and first["event_type"] == second["event_type"]
            and _dated_closely(first, second))


def annotate(incidents: list[dict[str, Any]], place_points: dict[str, tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    """Add mentions, regions, districts, scripts, source category, event type, freshness (per-type window),
    approximate location (from place_points, the looked-up coordinates of named towns), location confidence,
    duplicate/related/conflict/corroborating ids, evidence_status and lifecycle to each report."""
    region = active_region()
    place_pattern, state_pattern, road_aliases = _region_patterns(region.id)
    windows = region.freshness_window_h
    tokens = {}
    for item in incidents:
        # The fetched page description is the article's own summary; full page text is not used because
        # navigation and related-story links would add unrelated roads and places.
        item["summary"] = clean_snippet(item["summary"])
        text = f"{item['title']} {item['summary']} {item.get('page_description') or ''}"
        numbers = {match.upper() for match in HIGHWAY.findall(text)}
        numbers |= {road.removeprefix("NH-") for pattern, road in road_aliases if pattern.search(text)}
        highways = sorted(numbers, key=lambda value: (len(value), value))
        places = [region.place_index[name] for name in dict.fromkeys(place_pattern.findall(text))]
        item["mentions"] = {"highways": [f"NH-{number}" for number in highways],
                            "places": list(dict.fromkeys(place.name for place in places))}
        item["report_signal"] = _signal(text)
        item["event_types"] = [name for name, pattern in EVENT_TYPES if pattern.search(text)]
        item["event_type"] = item["event_types"][0] if item["event_types"] else "other"
        # Describes a disruption or a reopening, and is not a trip or ride listing. Only these are matched to routes.
        item["road_report"] = bool(item["event_types"] or item["report_signal"]) and not LISTING.search(item["title"])
        item["freshness_window_h"] = windows.get(item["event_type"], windows["other"])
        item["freshness"] = freshness(item.get("published_estimate"), item.get("published_approximate", False),
                                      item["freshness_window_h"] * 3600)
        named = {region.state_aliases.get(name, name) for name in state_pattern.findall(text)}
        named |= {place.state for place in places if place.state}
        item["regions"] = [state for state in region.states if state in named]
        item["districts"] = list(dict.fromkeys(place.district for place in places if place.district))
        item["scripts"] = scripts_in(f"{item['title']} {item['summary']}")
        item["source_category"] = source_category(item.get("source_url"), item.get("search_kind"))
        town = report_place(text, places)
        point = (place_points or {}).get(town.name) if town else None
        item["approximate_location"] = {"place": town.name, "latitude": point[0], "longitude": point[1]} if point else None
        item["location_confidence"] = location_confidence(item)
        tokens[item["id"]] = _tokens(text)

    # Near-duplicate groups, compared on title and snippet together: search titles are often
    # truncated to the same generic words for unrelated stories.
    parent = {item["id"]: item["id"] for item in incidents}

    def root(incident_id: str) -> str:
        while parent[incident_id] != incident_id:
            parent[incident_id] = parent[parent[incident_id]]
            incident_id = parent[incident_id]
        return incident_id

    for index, first in enumerate(incidents):
        for second in incidents[index + 1:]:
            a, b = tokens[first["id"]], tokens[second["id"]]
            similar_text = len(a) >= 8 and len(b) >= 8 and len(a & b) / len(a | b) >= DUPLICATE_SIMILARITY
            if similar_text or _same_place_and_time(first, second):
                parent[root(second["id"])] = root(first["id"])
    groups: dict[str, list[str]] = {}
    for item in incidents:
        groups.setdefault(root(item["id"]), []).append(item["id"])

    # Same-highway links (and the conflicts and corroboration found among them) only join road reports.
    by_highway: dict[str, list[dict[str, Any]]] = {}
    for item in incidents:
        for highway in item["mentions"]["highways"] if item["road_report"] else ():
            by_highway.setdefault(highway, []).append(item)

    for item in incidents:
        item["duplicate_ids"] = [other for other in groups[root(item["id"])] if other != item["id"]]
        related = {other["id"]: other for highway in item["mentions"]["highways"] for other in by_highway.get(highway, ())
                   if other["id"] != item["id"]}
        item["related_ids"] = list(related)
        opposite = {"closure": "reopening", "reopening": "closure"}.get(item["report_signal"] or "")
        item["conflict_ids"] = [other["id"] for other in related.values()
                                if opposite and other["report_signal"] == opposite and _dated_closely(item, other)]
        # Corroboration needs a different, identifiable publisher saying the same thing at about the
        # same time. Duplicates are excluded so syndicated copies never count as confirmation.
        own_publisher = publisher(item.get("source_url"))
        item["corroborating_ids"] = [
            other["id"] for other in related.values()
            if other["id"] not in item["duplicate_ids"] and item["report_signal"] in ("closure", "reopening")
            and other["report_signal"] == item["report_signal"] and own_publisher
            and publisher(other.get("source_url")) not in (None, own_publisher) and _dated_closely(item, other)
        ]
    for item in incidents:
        item["evidence_status"] = evidence_status(item)
        item["lifecycle"] = lifecycle(item)
    return incidents
