"""Regional configuration (report sections 5 and 6.7): the places, roads, sources and freshness rules for a region.

INDIA-TRACE runs one region at a time, chosen with REGION in Backend/.env. Expanding to a new
region or corridor means adding an entry to REGIONS: its states, places (with districts and
alternate spellings), road aliases, searches, allowed source categories and freshness windows.

Only facts we are sure of are listed. A place that exists in more than one state (Sonapur) has no
state, and a place without a district here simply has none recorded; nothing is guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

SOURCE_CATEGORIES = ("official", "news", "social", "other")


@dataclass(frozen=True)
class Place:
    name: str
    state: str | None = None
    district: str | None = None
    aliases: tuple[str, ...] = ()  # alternate spellings and older names, matched to `name`
    # "town" is a point that can be placed on the map (approximately); "area" (a district or valley) cannot.
    kind: str = "town"

    @property
    def locatable(self) -> bool:
        """A town in a known state; a name used in more than one state (Sonapur) is never placed."""
        return self.kind == "town" and self.state is not None


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    corridor: str
    states: tuple[str, ...]
    places: tuple[Place, ...]
    # Short names reports use for a state.
    state_aliases: dict[str, str]
    # Road names used in reports instead of the highway number, mapped to the national highway. Matching ignores
    # case and treats spaces, hyphens and en dashes alike, so "Guwahati–Shillong road" matches "Guwahati-Shillong Road".
    road_aliases: dict[str, str]
    searches: tuple[dict[str, str], ...]
    # How long a report stays fresh, by primary event type, in hours (report 6.5).
    freshness_window_h: dict[str, int]
    source_categories: tuple[str, ...] = SOURCE_CATEGORIES
    # The area the region's map labels cover: south, west, north, east.
    bbox: tuple[float, float, float, float] = (6.0, 68.0, 38.0, 98.0)
    # Writing systems expected in this region's sources; the original text is always kept untranslated.
    scripts: tuple[str, ...] = ("Latin",)
    place_index: dict[str, Place] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        index = {name: place for place in self.places for name in (place.name, *place.aliases)}
        object.__setattr__(self, "place_index", index)


def _places(state: str | None, *names: str, kind: str = "town") -> tuple[Place, ...]:
    return tuple(Place(name, state, kind=kind) for name in names)


NORTHEAST = Region(
    id="northeast",
    name="Northeast India",
    corridor="NH-6 / NH-306, Guwahati – Shillong – Silchar – Aizawl",
    states=("Assam", "Meghalaya", "Mizoram", "Manipur", "Nagaland", "Tripura", "Arunachal Pradesh", "Sikkim", "West Bengal"),
    places=(
        # Pilot corridor, with districts.
        Place("Guwahati", "Assam", "Kamrup Metropolitan", aliases=("Gauhati",)),
        Place("Silchar", "Assam", "Cachar"),
        Place("Haflong", "Assam", "Dima Hasao"),
        Place("Hailakandi", "Assam", "Hailakandi"),
        Place("Shillong", "Meghalaya", "East Khasi Hills"),
        Place("Sohra", "Meghalaya", "East Khasi Hills", aliases=("Cherrapunji", "Cherrapunjee")),
        Place("Nongpoh", "Meghalaya", "Ri Bhoi"),
        Place("Byrnihat", "Meghalaya", "Ri Bhoi"),
        Place("Jowai", "Meghalaya", "West Jaintia Hills"),
        Place("Khliehriat", "Meghalaya", "East Jaintia Hills"),
        Place("Lum Shnong", "Meghalaya", "East Jaintia Hills", aliases=("Lumshnong",)),
        Place("Aizawl", "Mizoram", "Aizawl"),
        Place("Kolasib", "Mizoram", "Kolasib"),
        Place("Ratacherra", "Assam"),
        Place("Jorabat", "Assam"),
        Place("Sonapur"),  # in both Assam and Meghalaya
        # Elsewhere in the region: state only.
        *_places("Assam", "Tezpur", "Jorhat", "Dibrugarh", "Tinsukia", "Nagaon", "Bongaigaon", "Dhubri", "Goalpara",
                 "Karimganj", "Lumding", "Diphu", "Dhemaji", "Lakhimpur", "Jeypore", "Saraighat", "Khanapara"),
        *_places("Assam", "Barak Valley", "Cachar", "Kamrup", kind="area"),
        *_places("Meghalaya", "Tura"),
        *_places("Meghalaya", "Ri Bhoi", "East Jaintia Hills", "East Khasi Hills", kind="area"),
        *_places("Mizoram", "Lunglei", "Champhai", "Lawngtlai", "Siaha"),
        *_places("Manipur", "Imphal", "Ukhrul", "Churachandpur", "Jiribam", "Senapati", "Mao"),
        *_places("Nagaland", "Kohima", "Dimapur", "Mokokchung", "Wokha", "Zunheboto", "Khisama"),
        *_places("Tripura", "Agartala", "Dharmanagar", "Kailashahar"),
        *_places("Arunachal Pradesh", "Itanagar", "Pasighat", "Tawang", "Bomdila", "Ziro", "Aalo", "Naharlagun", "Seppa",
                 "Deomali", "Anjaw", "Upper Subansiri", "Lohit"),
        *_places("Sikkim", "Gangtok", "Bardang"),
        *_places("West Bengal", "Siliguri", "Kalimpong"),
    ),
    state_aliases={"Arunachal": "Arunachal Pradesh"},
    # From the national-highway refs OSRM returned for these segments (docs/PILOT.md, measured 24 Oct 2026).
    road_aliases={
        "GS Road": "NH-6", "G.S. Road": "NH-6",
        "Guwahati-Shillong Road": "NH-6", "Guwahati-Shillong Highway": "NH-6",
        "Shillong-Silchar Road": "NH-6", "Shillong-Silchar Highway": "NH-6",
    },
    searches=(
        {"query": "NH-6 Guwahati Shillong road closure landslide update", "kind": "web"},
        {"query": "NH-6 Shillong Silchar Sonapur Ratacherra landslide traffic", "kind": "web"},
        {"query": "NH-306 Silchar Aizawl road blocked landslide", "kind": "web"},
        {"query": "Meghalaya Mizoram Barak Valley highway closure latest", "kind": "web"},
        # News searches return a publisher and date; narrow highway queries return nothing there, so they stay broad.
        {"query": "Meghalaya landslide highway", "kind": "news"},
        {"query": "Mizoram Barak Valley road landslide", "kind": "news"},
    ),
    freshness_window_h={"accident": 12, "weather": 24, "other": 24, "flood": 48, "closure": 48, "landslide": 72,
                        "bridge": 14 * 24, "construction": 30 * 24},
    scripts=("Latin", "Bengali-Assamese", "Devanagari", "Meetei Mayek"),
    bbox=(21.9, 88.0, 29.5, 97.5),
)

REGIONS = {region.id: region for region in (NORTHEAST,)}

# Unicode blocks for the scripts used in the region's sources. A script says how a source is written,
# not which language it is in (Bengali-Assamese script covers both languages, for example).
SCRIPTS = (
    ("Bengali-Assamese", re.compile(r"[ঀ-৿]")),
    ("Devanagari", re.compile(r"[ऀ-ॿ]")),
    ("Meetei Mayek", re.compile(r"[ꯀ-꯿]")),
    ("Latin", re.compile(r"[A-Za-z]")),
)


def alias_pattern(name: str) -> re.Pattern:
    words = [re.escape(word) for word in re.split(r"[\s\-–]+", name.strip())]
    return re.compile(r"(?<!\w)" + r"[\s\-–]+".join(words) + r"(?!\w)", re.IGNORECASE)


def coverage_by_state(region: Region, incidents: list[dict]) -> list[dict]:
    """Reports per state, so sparse coverage shows as a gap rather than as clear roads (report 5 and 11)."""
    rows = []
    for state in region.states:
        reports = [item for item in incidents if state in item["regions"] and item["verification"] not in ("dismissed", "resolved")]
        published = [item["published_estimate"] for item in reports if item["published_estimate"]]
        rows.append({"state": state, "reports": len(reports), "fresh": sum(item["freshness"] == "fresh" for item in reports),
                     "located": sum(item["latitude"] is not None for item in reports),
                     "newest_published": max(published, default=None)})
    return rows


def scripts_in(text: str) -> list[str]:
    return [name for name, pattern in SCRIPTS if pattern.search(text)]


def active_region() -> Region:
    from .config import get_settings
    region_id = get_settings().region
    if region_id not in REGIONS:
        raise ValueError(f"Unknown REGION '{region_id}'. Known regions: {', '.join(REGIONS)}")
    return REGIONS[region_id]
