"""Cross-report hints for reviewers: near-duplicates, mentioned roads and places, possible conflicts.

These are text heuristics. They never change a report's verification state or location;
the reviewer decides what they mean.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HIGHWAY = re.compile(r"\b(?:NH|National\s+Highway|Highway\s+No\.?)[\s\-–:(]*(?:NH[\s\-]*)?0*(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
# Northeast India towns, districts and road points that appear in disruption reports. Matched case-sensitively.
PLACES = (
    "Guwahati", "Shillong", "Silchar", "Imphal", "Aizawl", "Kohima", "Dimapur", "Agartala", "Itanagar", "Gangtok",
    "Tezpur", "Jorhat", "Dibrugarh", "Tinsukia", "Nagaon", "Bongaigaon", "Dhubri", "Goalpara", "Nongpoh", "Jowai",
    "Tura", "Sohra", "Cherrapunji", "Haflong", "Karimganj", "Hailakandi", "Lumding", "Diphu", "Dhemaji", "Lakhimpur",
    "Pasighat", "Tawang", "Bomdila", "Ziro", "Aalo", "Naharlagun", "Seppa", "Lunglei", "Kolasib", "Champhai",
    "Lawngtlai", "Siaha", "Mokokchung", "Wokha", "Zunheboto", "Ukhrul", "Churachandpur", "Jiribam", "Senapati",
    "Mao", "Khisama", "Dharmanagar", "Kailashahar", "Khliehriat", "Byrnihat", "Jorabat", "Sonapur", "Lum Shnong",
    "Ratacherra", "Bardang", "Jeypore", "Deomali", "Anjaw", "Upper Subansiri", "Lohit", "Siliguri", "Kalimpong",
    "Barak Valley", "Saraighat", "Khanapara", "Cachar", "Kamrup", "Ri Bhoi", "East Jaintia Hills", "East Khasi Hills",
)
PLACE = re.compile(r"\b(" + "|".join(re.escape(place) for place in PLACES) + r")\b")
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
# How long a report stays "fresh", by primary event type (report 6.5: fast-changing events
# get short windows, longer-lasting damage and roadworks longer ones). Hours.
FRESHNESS_WINDOW_H = {"accident": 12, "weather": 24, "other": 24, "flood": 48, "closure": 48, "landslide": 72,
                      "bridge": 14 * 24, "construction": 30 * 24}
STATES = ("Assam", "Meghalaya", "Mizoram", "Manipur", "Nagaland", "Tripura", "Arunachal Pradesh", "Sikkim", "West Bengal")
STATE = re.compile(r"\b(Assam|Meghalaya|Mizoram|Manipur|Nagaland|Tripura|Arunachal(?: Pradesh)?|Sikkim|West Bengal)\b")
# State for each listed place; places that exist in more than one state (e.g. Sonapur) are left out.
PLACE_STATE = {
    **dict.fromkeys(("Guwahati", "Silchar", "Tezpur", "Jorhat", "Dibrugarh", "Tinsukia", "Nagaon", "Bongaigaon", "Dhubri",
                     "Goalpara", "Haflong", "Karimganj", "Hailakandi", "Lumding", "Diphu", "Dhemaji", "Lakhimpur",
                     "Jorabat", "Ratacherra", "Jeypore", "Barak Valley", "Saraighat", "Khanapara", "Cachar", "Kamrup"), "Assam"),
    **dict.fromkeys(("Shillong", "Nongpoh", "Jowai", "Tura", "Sohra", "Cherrapunji", "Khliehriat", "Byrnihat", "Lum Shnong",
                     "Ri Bhoi", "East Jaintia Hills", "East Khasi Hills"), "Meghalaya"),
    **dict.fromkeys(("Aizawl", "Lunglei", "Kolasib", "Champhai", "Lawngtlai", "Siaha"), "Mizoram"),
    **dict.fromkeys(("Imphal", "Ukhrul", "Churachandpur", "Jiribam", "Senapati", "Mao"), "Manipur"),
    **dict.fromkeys(("Kohima", "Dimapur", "Mokokchung", "Wokha", "Zunheboto", "Khisama"), "Nagaland"),
    **dict.fromkeys(("Agartala", "Dharmanagar", "Kailashahar"), "Tripura"),
    **dict.fromkeys(("Itanagar", "Pasighat", "Tawang", "Bomdila", "Ziro", "Aalo", "Naharlagun", "Seppa", "Deomali", "Anjaw",
                     "Upper Subansiri", "Lohit"), "Arunachal Pradesh"),
    **dict.fromkeys(("Gangtok", "Bardang"), "Sikkim"),
    **dict.fromkeys(("Siliguri", "Kalimpong"), "West Bengal"),
}
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
    if item["corroborating_ids"]:
        return "corroborated"
    return "unknown" if verification == "unknown" else "unverified"


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
    """precise: reviewer-entered coordinates; road/place: only named in text; none: no location at all."""
    if item.get("latitude") is not None and item.get("longitude") is not None:
        return "precise"
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


def annotate(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add mentions, regions, event type, freshness (per-type window), location confidence,
    duplicate/related/conflict/corroborating ids and evidence_status to each report."""
    tokens = {}
    for item in incidents:
        # The fetched page description is the article's own summary; full page text is not used because
        # navigation and related-story links would add unrelated roads and places.
        text = f"{item['title']} {item['summary']} {item.get('page_description') or ''}"
        highways = sorted({match.upper() for match in HIGHWAY.findall(text)}, key=lambda value: (len(value), value))
        item["mentions"] = {"highways": [f"NH-{number}" for number in highways], "places": list(dict.fromkeys(PLACE.findall(text)))}
        item["report_signal"] = _signal(text)
        item["event_types"] = [name for name, pattern in EVENT_TYPES if pattern.search(text)]
        item["event_type"] = item["event_types"][0] if item["event_types"] else "other"
        item["freshness_window_h"] = FRESHNESS_WINDOW_H.get(item["event_type"], FRESHNESS_WINDOW_H["other"])
        item["freshness"] = freshness(item.get("published_estimate"), item.get("published_approximate", False),
                                      item["freshness_window_h"] * 3600)
        states = {"Arunachal Pradesh" if name == "Arunachal" else name for name in STATE.findall(text)}
        states |= {PLACE_STATE[place] for place in item["mentions"]["places"] if place in PLACE_STATE}
        item["regions"] = [state for state in STATES if state in states]
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
            if len(a) >= 8 and len(b) >= 8 and len(a & b) / len(a | b) >= DUPLICATE_SIMILARITY:
                parent[root(second["id"])] = root(first["id"])
    groups: dict[str, list[str]] = {}
    for item in incidents:
        groups.setdefault(root(item["id"]), []).append(item["id"])

    by_highway: dict[str, list[dict[str, Any]]] = {}
    for item in incidents:
        for highway in item["mentions"]["highways"]:
            by_highway.setdefault(highway, []).append(item)

    for item in incidents:
        item["duplicate_ids"] = [other for other in groups[root(item["id"])] if other != item["id"]]
        related = {other["id"]: other for highway in item["mentions"]["highways"] for other in by_highway[highway] if other["id"] != item["id"]}
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
    return incidents
