"""Cross-report hints for reviewers: near-duplicates, mentioned roads and places, possible conflicts.

These are text heuristics. They never change a report's verification state or location;
the reviewer decides what they mean.
"""
from __future__ import annotations

from datetime import datetime
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
    "Barak Valley", "Saraighat",
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
COARSE_RELATIVE = re.compile(r"(week|month|year)s?\s+ago$", re.IGNORECASE)
STOPWORDS = {"the", "and", "for", "has", "have", "had", "was", "were", "are", "that", "this", "with", "from", "after",
             "due", "its", "into", "over", "near", "along", "amid", "been", "which", "their", "more", "than"}
TRACKING_PARAMS = {"fbclid", "gclid", "igsh", "igshid", "hl", "ref", "ref_src", "s", "si"}
DUPLICATE_SIMILARITY = 0.6
CONFLICT_WINDOW_S = 72 * 3600


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
    """Add mentions, report_signal, event_type(s), duplicate_ids, related_ids and conflict_ids to each report."""
    tokens = {}
    for item in incidents:
        text = f"{item['title']} {item['summary']}"
        highways = sorted({match.upper() for match in HIGHWAY.findall(text)}, key=lambda value: (len(value), value))
        item["mentions"] = {"highways": [f"NH-{number}" for number in highways], "places": list(dict.fromkeys(PLACE.findall(text)))}
        item["report_signal"] = _signal(text)
        item["event_types"] = [name for name, pattern in EVENT_TYPES if pattern.search(text)]
        item["event_type"] = item["event_types"][0] if item["event_types"] else "other"
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
    return incidents
