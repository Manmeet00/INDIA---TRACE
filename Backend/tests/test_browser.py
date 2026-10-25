"""Browser end-to-end tests: the built React dashboard in Chrome, talking to the real FastAPI app.

The frontend is built with VITE_API_URL=http://india-trace.test. Playwright serves the built
files for that origin and hands every /api request to the app on a temporary database, so the
whole stack runs: React, the service layer, FastAPI, SQLite. External services (Nominatim, OSRM,
TinyFish) use the network fakes from conftest; map tiles and web fonts are blocked.

Needs Node/npm and Chrome (or `E2E_BROWSER_CHANNEL=chromium` after `playwright install chromium`).
Skipped when either is missing. Run only these with `pytest -m e2e`, or skip them with `-m "not e2e"`.
"""
import re
import os
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.parse import urlsplit

import pytest

from app.config import get_settings
from app.database import get_connection
from app.main import DATABASE_UNAVAILABLE
from conftest import SEARCH

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect
pytestmark = pytest.mark.e2e

ORIGIN = "http://india-trace.test"
FRONTEND = Path(__file__).resolve().parents[2] / "Frontend"


@pytest.fixture(scope="session")
def built_frontend(tmp_path_factory):
    if not shutil.which("npm") or not (FRONTEND / "node_modules").exists():
        pytest.skip("Frontend dependencies are not installed (cd Frontend && npm install)")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(out), "--emptyOutDir"], cwd=FRONTEND, check=True,
                   capture_output=True, env={**os.environ, "VITE_API_URL": ORIGIN})
    return out


@pytest.fixture(scope="session")
def browser():
    channel = os.getenv("E2E_BROWSER_CHANNEL", "chrome")
    with playwright_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(channel=None if channel == "chromium" else channel)
        except playwright_api.Error as exc:
            pytest.skip(f"No browser for end-to-end tests ({channel}): {exc.message.splitlines()[0]}")
        yield launched
        launched.close()


@pytest.fixture
def dashboard(client, providers, built_frontend, browser):
    """Opens the dashboard; returns the page. Page script errors fail the test."""
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != urlsplit(ORIGIN).netloc:
            return route.abort()  # map tiles, web fonts: the tests never depend on the internet
        if url.path.startswith("/api/"):
            headers = {"content-type": request.headers["content-type"]} if "content-type" in request.headers else {}
            response = client.request(request.method, url.path + (f"?{url.query}" if url.query else ""),
                                      content=request.post_data_buffer, headers=headers)
            return route.fulfill(status=response.status_code, body=response.content,
                                 headers={"content-type": response.headers.get("content-type", "application/json")})
        file = built_frontend / (url.path.lstrip("/") or "index.html")
        if not file.is_file():
            return route.fulfill(status=404, body="Not found")
        types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml"}
        route.fulfill(status=200, body=file.read_bytes(), headers={"content-type": types.get(file.suffix, "application/octet-stream")})

    page.route("**/*", serve)
    page.open = lambda: (page.goto(ORIGIN + "/"), expect(page.locator(".connection-label")).not_to_have_text("Connecting…"))
    yield page
    page.close()
    assert errors == [], f"Script errors in the page: {errors}"


# A device position for pages served from the plain-http test origin, where browsers refuse geolocation.
# %s is the body run with ok/fail for both one-off requests and the continuous watch the map uses.
SECURE = "Object.defineProperty(window, 'isSecureContext', { value: true });"  # the test address is plain http
GEOLOCATION = SECURE + """Object.defineProperty(navigator, 'geolocation', { value: {
    getCurrentPosition: (ok, fail) => { %s },
    watchPosition: (ok, fail) => { %s; return 1 },
    clearWatch: () => {} } })"""


def geolocation(body):
    return GEOLOCATION % (body, body)


def plan(page, origin, destination, preference=None):
    page.fill("#origin", origin)
    page.fill("#destination", destination)
    if preference:  # the form starts on Fastest
        page.locator(".chip", has_text=preference).click()
    page.click(".primary-button")


# --- No results ---------------------------------------------------------------------------

def test_empty_workspace_and_empty_collection_never_suggest_a_clear_road(dashboard, tinyfish_network):
    page = dashboard
    page.open()
    expect(page.locator(".connection-label")).to_contain_text("Live · updated")
    expect(page.locator(".offline-card")).to_contain_text("Automatic collection is off")
    expect(page.locator(".evidence-empty")).to_contain_text("No reports does not mean a road is clear.")

    page.click("text=Run collection")
    expect(page.locator(".collection-message")).to_contain_text("No reports does not mean the road is clear")
    expect(page.locator(".last-run")).to_contain_text("0 new")

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".route-card")).to_have_count(2)
    expect(page.locator(".action-banner .verdict")).to_have_text("Verify before dispatch")
    expect(page.locator(".action-banner")).to_contain_text("No reports have been collected. No reports does not mean the road is clear.")
    expect(page.locator(".coverage .milestone.gap")).to_have_count(1)  # NH-6 is a coverage gap, not a clear road
    expect(page.locator(".brief-verdict")).to_have_text("No reports foundNot proof the road is clear")


# --- The full flow: malformed and stale reports, missing coordinates, review, flags -------

def test_collect_review_locate_and_replan(dashboard, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [
        {"url": "https://example.org/sonapur", "title": "Landslide blocks NH-6 at Sonapur", "snippet": "Traffic halted on NH-6 near Sonapur.", "date": "2 hours ago"},
        {"url": "https://example.org/old", "title": "NH-6 closed for repairs", "snippet": "NH-6 closed near Shillong.", "date": "Jul 3, 2023"},
        {"url": "javascript:alert(1)", "title": "Malformed", "snippet": "Never stored."},
        {"url": "https://example.org/no-snippet", "title": "No text"},
    ]}
    page = dashboard
    page.open()
    page.click("text=Run collection")
    expect(page.locator(".collection-message")).to_contain_text("2 new reports")
    expect(page.locator(".evidence-row")).to_have_count(2)  # web and news both return them; malformed ones are dropped
    # "closed near Shillong" is placed at Shillong (approximate); the Sonapur report is not, as Sonapur is in two states.
    expect(page.locator(".brief-total")).to_have_count(0)  # no route planned yet: no counts until there is one
    expect(page.locator(".evidence-row", has_text="Sonapur")).to_contain_text("Sonapur")

    page.locator(".evidence-row", has_text="closed for repairs").click()
    expect(page.locator(".selected-incident .verification-badge")).to_have_text("Stale")

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".action-banner .verdict")).to_have_text("Verify before dispatch")
    expect(page.locator(".action-banner")).to_contain_text("Where on the road is not known")
    expect(page.locator(".impact-row")).to_have_count(2)

    # A reviewer confirms the fresh report and adds the coordinates from its source.
    page.locator(".evidence-row", has_text="Sonapur").click()
    page.locator(".verified-location summary").click()
    page.fill("[aria-label^='Latitude for']", "25.90")
    page.fill("[aria-label^='Longitude for']", "91.80")
    page.select_option("[id^=review-status-]", "confirmed")
    page.fill("[id^=review-note-]", "District advisory confirms the slide")
    page.click("text=Save review")
    expect(page.locator(".collection-message")).to_have_text("Evidence review saved.")
    expect(page.locator(".selected-incident .verification-badge")).to_have_text("Confirmed by reviewer")
    expect(page.locator(".brief-quality")).to_contain_text("0 road only")
    expect(page.locator(".map-options .toggle-row", has_text="Landslides")).to_contain_text("1 on map")

    # Plan again with Cautious, which puts the route that avoids the confirmed report first;
    # it still says verify, because the old report names NH-6 without a location.
    page.locator(".chip", has_text="Cautious").click()
    page.click(".primary-button")
    expect(page.locator(".route-card").nth(0)).to_contain_text("No located reports within 3 km")
    expect(page.locator(".action-banner .verdict")).to_have_text("Verify before dispatch")
    page.locator(".route-card").nth(1).click()
    expect(page.locator(".route-card").nth(1)).to_contain_text("1 report within 3 km (1 confirmed)")
    expect(page.locator(".route-card").nth(1).locator(".risk-pill")).to_have_text("Alternative advised")
    expect(page.locator(".action-banner .verdict")).to_have_text("Consider an alternative")
    expect(page.locator(".action-banner")).to_contain_text("Route 1 has no confirmed reports within 3 km")

    # Anyone can flag the old report; the flag never changes its status.
    page.locator(".evidence-row", has_text="closed for repairs").click()
    page.locator(".flag-form summary").click()
    page.select_option("[id^=flag-reason-]", "outdated")
    page.click("text=Send flag")
    expect(page.locator(".collection-message")).to_contain_text("Flag sent for review")
    expect(page.locator(".selected-incident .incident-top")).to_contain_text("Flagged")
    expect(page.locator(".selected-incident .verification-badge")).to_have_text("Stale")


def test_evidence_desk_shows_the_planned_routes_reports_and_why(dashboard, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [
        {"url": "https://example.org/nh6", "title": "Landslide blocks NH-6", "snippet": "Traffic halted on NH-6 after a landslide.", "date": "2 hours ago"},
        {"url": "https://example.org/corridor", "title": "Four-lane corridor will ...", "snippet": "The corridor will improve goods movement. Missing:  closure  | Show results with:", "date": "1 hour ago"},
        {"url": "https://example.org/taxi", "title": "Guwahati to Shillong Taxi | ₹2499", "snippet": "Fares on NH-6 from ₹2,499; landslide updates daily."},
    ]}
    page = dashboard
    page.open()
    page.click("text=Run collection")
    expect(page.locator(".evidence-row")).to_have_count(3)
    expect(page.locator(".evidence-scope")).to_have_count(0)  # no route yet: every report

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".evidence-scope button.on")).to_contain_text("This route1")
    expect(page.locator(".evidence-row")).to_have_count(1)  # the taxi listing names NH-6 but describes no disruption on it
    expect(page.locator(".selected-incident h3")).to_have_text("Landslide blocks NH-6")
    expect(page.locator(".route-match")).to_contain_text("Names NH-6, which this route uses. Where on NH-6 is not known")

    expect(page.locator(".report-stepper")).to_have_count(0)  # one report: nothing to step through

    page.get_by_role("button", name="All reports").click()
    expect(page.locator(".evidence-row")).to_have_count(3)
    expect(page.locator(".report-stepper")).to_contain_text("Report 1 of 3")
    first = page.locator(".selected-incident h3").inner_text()
    page.get_by_role("button", name="Next report").click()
    expect(page.locator(".report-stepper")).to_contain_text("Report 2 of 3")
    expect(page.locator(".selected-incident h3")).not_to_have_text(first)
    expect(page.get_by_role("button", name="Previous report")).to_be_enabled()
    page.locator(".evidence-row", has_text="corridor").click()
    expect(page.locator(".selected-incident .incident-summary")).to_have_text("The corridor will improve goods movement.")
    expect(page.locator(".selected-incident .incident-top")).to_contain_text("No disruption described")
    expect(page.locator(".route-match.off")).to_contain_text("Not matched to this route")


def test_route_cards_say_why_the_first_route_is_first_and_how_the_others_compare(dashboard):
    # The fake OSRM routes: route 1 is 100 km in 66 min 40 s, route 2 is 120 km in 76 min 40 s.
    page = dashboard
    page.open()
    expect(page.locator(".chip-group.preferences .chip.on")).to_have_text("Fastest")  # like a maps app
    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    cards = page.locator(".route-card")
    expect(cards.nth(0)).to_contain_text("Route 1 · Fastest")
    expect(cards.nth(0).locator(".record")).to_have_text(["Fastest", "Shortest"])
    expect(cards.nth(1)).to_contain_text("Route 2 · Alternative")
    expect(cards.nth(1).locator(".route-records em")).to_have_text("10 min slower · 20 km longer")

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya", "Shortest")
    expect(cards.nth(0)).to_contain_text("Route 1 · Shortest")


def test_the_vehicle_choice_is_car_bike_or_truck_and_says_what_the_times_mean(dashboard):
    page = dashboard
    page.open()
    expect(page.locator(".chip-group.modes .chip")).to_have_text(["Car", "Bike", "Truck"])
    expect(page.locator(".chip-group.modes .chip.on")).to_have_text("Car")
    page.locator(".chip-group.modes .chip", has_text="Bike").click()
    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".routing-note")).to_have_text("OSRM has no two-wheeler routes, so this is the car route and time; a bike may take other roads.")
    page.locator(".chip-group.modes .chip", has_text="Truck").click()
    page.click(".primary-button")
    expect(page.locator(".routing-note")).to_contain_text("trucks are usually slower")


# --- Timeouts -----------------------------------------------------------------------------

def test_routing_provider_timeout_is_explained(dashboard, providers):
    providers["router.project-osrm.org"] = TimeoutError("timed out")
    page = dashboard
    page.open()
    plan(page, "Shillong, Meghalaya", "Guwahati, Assam")
    expect(page.locator(".inline-error")).to_have_text(
        "An external routing or search service is unavailable (router.project-osrm.org did not answer within 15 s).")
    expect(page.locator(".route-card")).to_have_count(0)


def test_routing_timeout_on_the_demo_route_falls_back_to_a_labelled_snapshot(dashboard, providers):
    providers["router.project-osrm.org"] = TimeoutError("timed out")
    page = dashboard
    page.open()
    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".inline-demo-note")).to_contain_text("This historical route is not for dispatch.")
    expect(page.locator(".route-card .time-source").first).to_have_text("Historical")


def test_hung_api_request_times_out_in_the_browser(dashboard):
    page = dashboard
    page.clock.install()
    page.open()
    page.route("**/api/routes/plan", lambda route: None)  # the request never gets an answer
    plan(page, "Shillong, Meghalaya", "Guwahati, Assam")
    expect(page.locator(".primary-button")).to_have_text("Finding routes…")
    page.clock.run_for(61_000)
    expect(page.locator(".inline-error")).to_have_text("Could not plan this route. The API did not answer within 60 seconds. Refresh to see whether it finished.")
    expect(page.locator(".primary-button")).to_contain_text("Find routes")


# --- API and database failures ------------------------------------------------------------

def test_stopped_api_is_reported_as_unavailable(dashboard):
    page = dashboard
    page.route("**/api/**", lambda route: route.abort())
    page.open()
    expect(page.locator(".connection-label")).to_have_text("API unavailable")
    expect(page.locator("text=Run collection")).to_be_disabled()
    plan(page, "Shillong, Meghalaya", "Guwahati, Assam")
    expect(page.locator(".inline-error")).to_contain_text(f"The API at {ORIGIN} is not reachable. Check that the backend is running.")


def test_database_failure_is_shown_and_recovers(dashboard, monkeypatch, tmp_path, add_incident):
    add_incident("kept", summary="Landslide on NH-6")
    page = dashboard
    page.open()
    expect(page.locator(".evidence-row")).to_have_count(1)

    good = get_settings().database_path
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))  # a folder: SQLite cannot open it
    get_settings.cache_clear()
    page.click("[aria-label='Refresh evidence and API status']")
    expect(page.locator(".connection-label")).to_have_text("API error")
    expect(page.locator(".offline-card")).to_contain_text("Running, but data is unavailable")
    expect(page.locator(".collection-message")).to_have_text(DATABASE_UNAVAILABLE)
    expect(page.locator("text=Run collection")).to_be_disabled()
    expect(page.locator(".evidence-row")).to_have_count(1)  # the last loaded evidence stays visible

    monkeypatch.setenv("DATABASE_PATH", str(good))
    get_settings.cache_clear()
    page.click("[aria-label='Refresh evidence and API status']")
    expect(page.locator(".connection-label")).to_contain_text("Live · updated")
    expect(page.locator(".collection-message")).to_have_text("Evidence and service status are up to date.")


# --- Report features: background runs, source categories, timeline, re-checks, coverage, monitoring ---

def test_background_run_source_choice_timeline_recheck_coverage_and_monitoring(dashboard, tinyfish_network):
    release = threading.Event()

    def search(request):
        release.wait(10)
        return {"results": [
            {"url": "https://eastjaintiahills.gov.in/order-12", "title": "Order: NH-6 closed near Sonapur",
             "snippet": "Traffic on NH-6 near Sonapur in Meghalaya is suspended after a landslide.", "date": "3 hours ago"},
            {"url": "https://www.facebook.com/somepage/posts/1", "title": "NH-6 jam", "snippet": "Long queue on NH-6, says a post."},
        ]}
    tinyfish_network[SEARCH] = search
    page = dashboard
    page.open()

    page.get_by_label("Social post").uncheck()
    page.click("text=Run collection")
    expect(page.locator(".list-heading .text-button")).to_contain_text("Searching 1 of 6")  # the run is followed live
    release.set()
    expect(page.locator(".collection-message")).to_contain_text("1 new reports from 6 searches")
    expect(page.locator(".collection-message")).to_contain_text("outside the allowed categories (official, news, other) were skipped")
    expect(page.locator(".evidence-row")).to_have_count(1)

    desk = page.locator(".selected-incident")
    expect(desk.locator(".source-badge")).to_have_text("Official source")
    expect(desk.locator(".verification-badge")).to_have_text("Corroborated")
    expect(desk.locator(".timeline")).to_contain_text("Collected by TinyFish web search")
    expect(desk.locator(".timeline")).to_contain_text("Page read with TinyFish Fetch")

    desk.locator("text=Re-check source").click()
    expect(page.locator(".collection-message")).to_have_text("Re-checked: page read, no change since the last read")
    expect(desk.locator(".timeline li").first).to_contain_text("no change since the last read")

    coverage = page.locator(".region-panel")
    expect(coverage.locator("li", has_text="Meghalaya")).to_contain_text("1 report · 1 recent")
    expect(coverage.locator("li.gap", has_text="Mizoram")).to_contain_text("none recent")

    monitoring = page.locator("#monitoring")
    expect(monitoring.locator(".figure", has_text="TinyFish searches")).to_contain_text("6 / 12,000")
    expect(monitoring.locator(".figure", has_text="Kept after review")).to_contain_text("not measured")


# --- Mappls base map ----------------------------------------------------------------------
# The real SDK needs a Mappls key and the internet, so these tests serve a stand-in at sdk.mappls.com that
# follows the documented v3 API (mappls.Map, Polyline, Marker, remove, addListener) and records each call.

FAKE_MAPPLS_SDK = """
window.__mappls = { maps: [], polylines: [], markers: [], geojson: [] };
class Listening { constructor() { this.listeners = {}; } addListener(name, fn) { (this.listeners[name] ||= []).push(fn); } fire(name) { (this.listeners[name] || []).forEach((fn) => fn()); } }
window.mappls = {
  ControlPosition: { RIGHT_BOTTOM: 'bottom-right' },
  Map: class extends Listening {
    constructor(id, options) { super(); this.id = id; this.options = options; this.removed = false;
      document.getElementById(id).dataset.mappls = 'ready'; window.__mappls.maps.push(this); setTimeout(() => this.fire('load'), 0); }
    setCenter(center) { this.center = center; } setZoom(zoom) { this.zoom = zoom; } remove() { this.removed = true; }
  },
  Polyline: class { constructor(options) { this.options = options; this.removed = false; window.__mappls.polylines.push(this); } },
  Marker: class extends Listening { constructor(options) { super(); this.options = options; this.removed = false; window.__mappls.markers.push(this); } },
  addGeoJson(options) { const layer = { options, removed: false }; window.__mappls.geojson.push(layer); return layer; },
  remove({ layer }) { layer.removed = true; },
};
"""


def live(page, kind):
    return page.evaluate(f"window.__mappls.{kind}.filter((item) => !item.removed).map((item) => item.options)")


@pytest.fixture
def mappls_key(monkeypatch):
    monkeypatch.setenv("MAPPLS_STATIC_KEY", "browser-key")
    get_settings.cache_clear()
    return "browser-key"


def test_mappls_draws_routes_markers_and_selects_evidence(dashboard, mappls_key, add_incident):
    add_incident("slide", "confirmed", 25.90, 91.80, summary="Landslide on NH-6", published_at="2 hours ago")
    page = dashboard
    sdk_urls = []
    page.route("https://sdk.mappls.com/**", lambda route: (sdk_urls.append(route.request.url),
               route.fulfill(status=200, body=FAKE_MAPPLS_SDK, headers={"content-type": "text/javascript"})))
    page.open()
    expect(page.locator(".mappls-canvas[data-mappls=ready]")).to_have_count(1)
    assert sdk_urls == ["https://sdk.mappls.com/map/sdk/web?v=3.0&access_token=browser-key"]
    expect(page.locator(".map-foot")).to_contain_text("Map © Mappls (MapmyIndia)")
    expect(page.locator(".leaflet-container")).to_have_count(0)
    assert [marker["position"] for marker in live(page, "markers")] == [{"lat": 25.9, "lng": 91.8}]  # located evidence only
    page.wait_for_function("window.__mappls.geojson.length === 1")
    mask = live(page, "geojson")[0]
    rings = mask["data"]["features"][0]["geometry"]["coordinates"]
    assert mask["cType"] == 1 and rings[0][0] == [-180, -89] and len(rings) == 59  # the world, with India's 58 land parts cut out

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya", "Cautious")
    expect(page.locator(".route-card")).to_have_count(2)
    page.wait_for_function("window.__mappls.polylines.filter((item) => !item.removed).length === 2")
    lines = live(page, "polylines")
    assert [line["fitbounds"] for line in lines] == [False, True]  # the selected route is drawn last and fitted
    assert lines[1]["strokeColor"] == "#0878e8" and lines[1]["path"][0] == {"lat": 26.18, "lng": 91.75}
    assert len(live(page, "markers")) == 3  # origin, destination, the located report

    page.locator(".route-card").nth(1).click()  # choosing the other route redraws with it on top
    page.wait_for_function("window.__mappls.polylines.filter((item) => !item.removed).slice(-1)[0].options.path[1].lng === 91.8")

    page.fill(".global-search input", "nothing matches this")  # select through the map, not the list
    page.evaluate("window.__mappls.markers.filter((item) => !item.removed && item.options.position.lat === 25.9)[0].fire('click')")
    expect(page.locator(".selected-incident h3")).to_have_text("Report slide")
    assert page.evaluate("window.__mappls.maps.length") == 1  # one map for the whole session


def test_mappls_unreachable_falls_back_to_openstreetmap(dashboard, mappls_key):
    page = dashboard  # the fixture blocks every outside host, so the Mappls script cannot load
    page.open()
    expect(page.locator(".map-fallback")).to_have_text("The Mappls map could not load: check MAPPLS_STATIC_KEY and the internet connection. Showing OpenStreetMap instead.")
    expect(page.locator(".leaflet-container")).to_have_count(1)
    expect(page.locator(".map-foot")).to_contain_text("OpenStreetMap contributors")


def test_rejected_mappls_key_falls_back_to_openstreetmap(dashboard, mappls_key):
    page = dashboard
    rejecting = FAKE_MAPPLS_SDK.replace("setTimeout(() => this.fire('load'), 0);", "setTimeout(() => options.token_callback(), 0);")
    page.route("https://sdk.mappls.com/**", lambda route: route.fulfill(status=200, body=rejecting, headers={"content-type": "text/javascript"}))
    page.open()
    expect(page.locator(".map-fallback")).to_have_text("Mappls rejected the map key. Showing OpenStreetMap instead.")
    expect(page.locator(".leaflet-container")).to_have_count(1)


def test_without_a_mappls_key_the_map_is_openstreetmap_showing_only_india(dashboard):
    page = dashboard
    page.open()
    expect(page.locator(".leaflet-container")).to_have_count(1)
    expect(page.locator(".leaflet-india-mask-pane canvas")).to_have_count(1)  # the mask and India's outline, drawn on a canvas
    expect(page.locator(".map-foot")).to_contain_text("India boundary: Survey of India")
    expect(page.locator(".map-fallback")).to_have_count(0)


def test_sidebar_can_be_hidden_and_the_choice_is_remembered(dashboard):
    page = dashboard
    page.open()
    toggle = page.locator(".sidebar-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(toggle).to_have_attribute("aria-label", "Show sidebar")
    expect(page.locator("#sidebar")).to_be_hidden()
    expect(page.locator(".topbar-brand")).to_be_visible()
    page.reload()
    expect(page.locator(".sidebar-toggle")).to_have_attribute("aria-expanded", "false")
    page.locator(".sidebar-toggle").click()
    expect(page.locator("#sidebar")).to_be_visible()



def test_town_placed_reports_show_one_approximate_symbol_and_live_refresh_announces_new_reports(dashboard, client, add_incident):
    add_incident("first", summary="Landslide near Shillong blocks traffic", published_at="2 hours ago")
    assert client.post("/api/places/locate").json()["found"] == 1  # Shillong, from the Nominatim fake
    page = dashboard
    page.clock.install()
    page.open()
    expect(page.locator(".selected-incident .incident-meta")).to_contain_text("Approximate · Shillong named in report")
    symbol = page.locator(".leaflet-marker-pane .incident-icon")
    expect(symbol).to_have_count(1)  # a Google-style symbol at the town, marked approximate
    expect(symbol).to_have_class(re.compile(r"\bapprox\b"))
    expect(page.locator(".map-options .toggle-row", has_text="Landslides")).to_contain_text("1 on map")
    symbol.hover()
    expect(page.locator(".leaflet-tooltip")).to_contain_text("Landslide: 1 report placed at Shillong · exact spot unknown")

    add_incident("second", summary="Second landslide near Shillong", published_at="1 hour ago")
    page.clock.run_for(61_000)  # the dashboard reloads every minute
    expect(page.locator(".evidence-row")).to_have_count(2)
    expect(page.locator(".collection-message")).to_contain_text("1 new report arrived at")
    client.post("/api/places/locate")
    page.clock.run_for(61_000)
    expect(page.locator(".leaflet-marker-pane .incident-icon")).to_have_count(1)  # same town, same type: one symbol, no count

def test_planning_a_route_scopes_the_cards_and_runs_a_live_check_for_it(dashboard, tinyfish_network):
    searched = []

    def search(request):
        searched.append(request.full_url)
        return {"results": [{"url": "https://example.org/live-nh6", "title": "Landslide blocks NH-6",
                             "snippet": "A landslide blocked NH-6 this morning; traffic is held.", "date": "1 hour ago"}]}
    tinyfish_network[SEARCH] = search
    page = dashboard
    page.open()
    expect(page.locator(".summary-scope")).to_contain_text("No route planned yet")
    expect(page.locator(".brief-total")).to_have_count(0)

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".summary-scope .brief-route")).to_have_text("Route 1")
    expect(page.locator(".summary-scope b")).to_contain_text("Guwahati → Shillong")
    expect(page.locator(".live-check")).to_contain_text("Live check")
    expect(page.locator(".live-check")).to_contain_text("1 new report from the route search")
    expect(page.locator(".brief-type.landslide b")).to_have_text("1")   # the new landslide names NH-6, which the route uses
    expect(page.locator(".brief-total")).to_contain_text("for this route")
    expect(page.locator(".brief-verdict")).to_contain_text("None confirmed")  # one unverified landslide
    expect(page.locator(".action-banner")).to_contain_text("NH-6")    # the advice was recalculated with it
    assert all("query=NH-6+Guwahati+Shillong" in url and "recency_minutes=4320" in url for url in searched)



def test_route_form_suggests_places_and_uses_your_location(dashboard, providers):
    providers["photon.komoot.io"] = {"features": [
        {"properties": {"name": "Jowai Bypass", "county": "West Jaintia Hills", "state": "Meghalaya", "countrycode": "IN"}},
        {"properties": {"name": "Jowa", "state": "Vaud", "countrycode": "CH"}},  # outside India: never suggested
    ]}
    page = dashboard
    # The test origin is plain http, where browsers refuse geolocation, so the device position is supplied directly.
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.18, longitude: 91.75, accuracy: 50 } })"))
    page.open()
    page.fill("#destination", "Jow")
    options = page.locator("#destination ~ .place-suggestions li")
    expect(options).to_have_count(2)
    expect(options.nth(0)).to_contain_text("JowaiWest Jaintia Hills, Meghalaya")  # the region's own town first
    expect(options.nth(1)).to_contain_text("Jowai Bypass")
    expect(page.locator("#destination")).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator("#destination")).to_have_value("Jowai, Meghalaya")

    page.fill("#origin", "")
    page.locator("#origin ~ .place-suggestions li.location").click()
    expect(page.locator("#origin")).to_have_value("Your location")
    page.fill("#destination", "Shillong, Meghalaya")
    page.keyboard.press("Escape")
    page.locator(".chip", has_text="Fastest").click()
    page.click(".primary-button")
    expect(page.locator(".route-card")).to_have_count(2)
    expect(page.locator(".summary-scope b")).to_contain_text("Your location → Shillong")


def test_evidence_desk_shows_the_sources_own_video_and_hides_a_picture_that_will_not_load(dashboard, add_incident):
    add_incident("video", summary="Video of the NH-6 landslide", source_url="https://www.youtube.com/watch?v=bh1TVzezZWs")
    add_incident("photo", summary="Landslide photo on NH-6", source_url="https://news.example.org/nh6")
    with get_connection() as connection:  # a picture whose host the test blocks, as a publisher might
        connection.execute("UPDATE incidents SET page_image = 'https://img.example.org/slide.jpg' WHERE id = 'photo'")
    page = dashboard
    frames = []
    page.route("https://www.youtube-nocookie.com/**", lambda route: (frames.append(route.request.url), route.fulfill(status=200, body="<p>player</p>", headers={"content-type": "text/html"})))
    page.open()
    expect(page.locator(".evidence-row", has_text="Report video")).to_contain_text("· video")
    expect(page.locator(".evidence-row", has_text="Report photo")).to_contain_text("· photo")

    page.locator(".evidence-row", has_text="Report video").click()
    expect(page.locator(".embed-load")).to_contain_text("Show the YouTube video")
    expect(page.locator(".evidence-media figcaption")).to_have_text("Nothing loads from YouTube until you choose to.")
    assert frames == []  # nothing from YouTube before the click
    page.locator(".embed-load").click()
    expect(page.locator(".evidence-media iframe")).to_have_attribute("src", "https://www.youtube-nocookie.com/embed/bh1TVzezZWs")
    expect(page.locator(".evidence-media")).to_have_count(1)

    page.locator(".evidence-row", has_text="Report photo").click()
    expect(page.locator(".selected-incident h3")).to_have_text("Report photo")
    expect(page.locator(".evidence-media")).to_have_count(0)  # the picture failed to load, so it is left out




def test_a_facebook_video_that_refuses_embedding_can_be_opened_on_facebook_or_hidden(dashboard, add_incident):
    url = "https://www.facebook.com/61570749780277/videos/1093339910158314"
    add_incident("fbvideo", summary="HMVs halted at Lakhanpur on NH44", source_url=url)
    page = dashboard
    page.route("https://www.facebook.com/plugins/**", lambda route: route.fulfill(status=200, body="<p>Unavailable</p>", headers={"content-type": "text/html"}))
    page.open()
    page.locator(".evidence-row", has_text="Report fbvideo").click()
    expect(page.locator(".embed-load")).to_contain_text("Show the Facebook video")
    page.locator(".embed-load").click()
    frame = page.locator(".evidence-media iframe")
    expect(frame).to_have_attribute("src", re.compile(r"plugins/video\.php.*show_text=false"))
    box = frame.bounding_box()
    assert abs(box["height"] - box["width"] * 9 / 16) < 2  # video-shaped: no blank space under a refusal
    expect(page.locator(".embed-caption")).to_contain_text("If it says Unavailable, the owner does not allow it to be shown here")
    expect(page.locator(".embed-actions a")).to_have_attribute("href", url)
    page.locator(".embed-actions button", has_text="Hide").click()
    expect(page.locator(".evidence-media iframe")).to_have_count(0)
    expect(page.locator(".embed-load")).to_be_visible()


def test_start_is_your_location_and_destination_is_chosen(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.18, longitude: 91.75 } })"))
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    expect(page.locator("#origin")).to_have_class("is-location")
    expect(page.locator("#destination")).to_have_value("")
    expect(page.locator("#destination")).to_have_attribute("placeholder", "Choose destination")
    page.fill("#destination", "Shillong")
    page.keyboard.press("Escape")
    page.click(".primary-button")
    expect(page.locator(".summary-scope b")).to_contain_text("Your location → Shillong")


def test_map_search_bar_plans_a_route_to_the_place_chosen(dashboard, providers):
    providers["photon.komoot.io"] = {"features": []}
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.18, longitude: 91.75, accuracy: 50 } })"))
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    search = page.locator(".map-search input")
    expect(search).to_have_attribute("placeholder", "Search destination")
    search.click()
    expect(page.locator(".map-search .place-suggestions")).to_have_count(0)  # no "Your location" offered here
    page.evaluate("document.querySelector('.leaflet-container').dataset.first = 'yes'")
    search.fill("Shillo")
    page.locator(".map-search .place-suggestions li", has_text="Shillong").first.click()
    expect(page.locator("#destination")).to_have_value("Shillong, Meghalaya")
    expect(page.locator(".summary-scope b")).to_contain_text("Your location → Shillong")
    expect(page.locator(".route-card")).to_have_count(2)
    # The same map moved to the route: nothing already loaded is thrown away and fetched again.
    expect(page.locator(".leaflet-container[data-first='yes']")).to_have_count(1)


def test_map_search_bar_fills_the_destination_when_the_start_is_unknown(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })"))
    page.open()
    page.locator(".map-search input").fill("Shillong")
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")
    expect(page.locator("#destination")).to_have_value("Shillong")
    expect(page.locator(".summary-scope b")).to_have_text("No route planned yet")  # nothing planned without a start
    expect(page.locator(".map-search-status")).to_have_text("Destination set. Choose a starting point in the route planner.")


def test_map_search_bar_shows_progress_and_errors_under_the_bar(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.18, longitude: 91.75, accuracy: 50 } })"))
    replies = []

    def plan(route):  # the routing service fails, slowly enough to see the progress note
        replies.append(route.request.url)
        page.wait_for_timeout(500)
        route.fulfill(status=502, json={"detail": "Routing service unavailable (router.project-osrm.org)."})
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    page.route("**/api/routes/plan", plan)
    page.locator(".fullscreen-button").click()  # the route planner is out of sight
    page.locator(".map-search input").fill("Shillong")
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")
    expect(page.locator(".map-search-status")).to_have_text("Finding routes…")
    expect(page.locator(".map-search-status.error")).to_have_text("Routing service unavailable (router.project-osrm.org).")
    assert len(replies) == 1


DRIVING = SECURE + """(() => {
  let position = { coords: { latitude: 26.18, longitude: 91.75, accuracy: 20 }, timestamp: Date.now() }
  const watchers = []
  window.driveTo = (latitude, longitude) => {
    position = { coords: { latitude, longitude, accuracy: 20 }, timestamp: Date.now() }
    watchers.forEach((ok) => ok(position))
  }
  Object.defineProperty(navigator, 'geolocation', { value: {
    getCurrentPosition: (ok) => ok(position),
    watchPosition: (ok) => { watchers.push(ok); ok(position); return watchers.length },
    clearWatch: () => {} } })
})()"""


def osrm_with_steps(request):
    from conftest import osrm
    answer = osrm(request)
    for route, turn in zip(answer["routes"], ([91.80, 25.90], [92.10, 25.90])):
        route["legs"] = [{"steps": [
            {"name": "", "distance": 50000, "duration": 2000, "maneuver": {"type": "depart", "modifier": "right", "bearing_after": 170, "location": [91.75, 26.18]}},
            {"name": "GS Road", "ref": "NH6", "distance": route["distance"] - 50000, "duration": 2000, "maneuver": {"type": "turn", "modifier": "left", "location": turn}},
            {"name": "", "distance": 0, "duration": 0, "maneuver": {"type": "arrive", "location": [91.88, 25.58]}},
        ]}]
    return answer


SPEECH = """window.said = []
Object.defineProperty(window, 'speechSynthesis', { value: { speak: (utterance) => window.said.push(utterance.text), cancel: () => {} } })"""


def start_navigation(page):
    page.add_init_script(DRIVING)
    page.add_init_script(SPEECH)
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    page.fill("#destination", "Shillong")
    page.keyboard.press("Escape")
    page.click(".primary-button")
    expect(page.locator(".route-card")).to_have_count(2)
    page.locator(".start-button").click()


def test_start_follows_the_route_turn_by_turn_until_arrival(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    start_navigation(page)
    banner = page.locator(".nav-banner")
    # Laid out like Google Maps: the turn and its distance, the action above the road name.
    expect(banner.locator(".nav-turn")).to_have_text("50 km")
    expect(banner.locator(".nav-road span")).to_have_text("Turn left")
    expect(banner.locator(".nav-road b")).to_have_text("GS Road (NH6)")
    expect(page.locator(".map-wrap.fullscreen")).to_have_count(1)  # navigation fills the screen
    expect(page.locator(".map-search")).to_have_count(0)
    expect(page.locator(".nav-sheet .nav-eta")).to_contain_text("min")
    expect(page.locator(".nav-sheet .nav-eta")).to_contain_text("km")
    expect(page.locator(".leaflet-marker-pane .nav-arrow")).to_have_count(1)  # an arrow, not the dot
    expect(page.locator(".locate-button")).to_be_hidden()  # the dashboard's own controls step aside
    page.wait_for_function("window.said.length > 0")
    assert page.evaluate("window.said[0]") == "In 50 kilometres, turn left onto GS Road (NH 6)"

    page.evaluate("driveTo(26.05, 92.45)")  # well away from both routes
    expect(page.locator(".nav-off-route")).to_contain_text("You are off the route")
    page.locator(".nav-off-route button").click()
    expect(banner.locator(".nav-road b")).to_have_text("GS Road (NH6)")  # a new route from here, still navigating
    plans = [request for host, request in providers["calls"] if host == "router.project-osrm.org"]
    assert "92.45,26.05" in plans[-1].full_url

    page.evaluate("driveTo(25.58, 91.88)")
    expect(banner).to_contain_text("You have arrived")
    expect(banner).to_contain_text("Shillong")
    page.wait_for_function("window.said.includes('You have arrived at Shillong')")
    page.get_by_role("button", name="Done").click()
    expect(page.locator(".navigation")).to_have_count(0)
    expect(page.locator(".map-wrap.fullscreen")).to_have_count(0)  # the dashboard is back
    expect(page.locator(".map-start")).to_be_visible()  # the route can be started again from the map


def test_navigation_recentres_shows_the_overview_mutes_and_reroutes_on_its_own(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    start_navigation(page)
    expect(page.locator(".nav-banner .nav-road b")).to_have_text("GS Road (NH6)")

    box = page.locator(".map-canvas").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 150, box["y"] + box["height"] / 2 + 80, steps=8)
    page.mouse.up()
    recentre = page.locator(".nav-recentre")
    expect(recentre).to_be_visible()  # looking around stops the map following
    recentre.click()
    expect(recentre).to_have_count(0)

    overview = page.get_by_role("button", name="Route overview")
    overview.click()
    expect(overview).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".nav-recentre")).to_be_visible()
    overview.click()
    expect(overview).to_have_attribute("aria-pressed", "false")

    mute = page.get_by_role("button", name="Mute voice directions")
    mute.click()
    expect(page.get_by_role("button", name="Turn on voice directions")).to_have_attribute("aria-pressed", "false")
    assert page.evaluate("localStorage.getItem('india-trace.voice')") == "off"

    before = sum(host == "router.project-osrm.org" for host, _ in providers["calls"])
    page.evaluate("driveTo(26.05, 92.45)")
    expect(page.locator(".nav-off-route")).to_be_visible()  # one position off the route: only a warning
    assert sum(host == "router.project-osrm.org" for host, _ in providers["calls"]) == before
    page.evaluate("driveTo(26.051, 92.451)")  # still off the route at the next position: a new route on its own
    for _ in range(50):  # the new route is requested without pressing anything
        if sum(host == "router.project-osrm.org" for host, _ in providers["calls"]) > before:
            break
        page.wait_for_timeout(100)
    plans = [request for host, request in providers["calls"] if host == "router.project-osrm.org"]
    assert len(plans) == before + 1 and "92.451,26.051" in plans[-1].full_url
    expect(page.locator(".nav-banner .nav-road b")).to_have_text("GS Road (NH6)")


def test_a_failed_reroute_keeps_the_route_and_reroutes_start_no_live_check(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    jobs = []
    page.on("request", lambda request: jobs.append(request.url) if "/api/collection/jobs" in request.url else None)
    start_navigation(page)
    expect(page.locator(".nav-banner .nav-road b")).to_have_text("GS Road (NH6)")
    checks = len(jobs)  # the live check for the planned route

    providers["router.project-osrm.org"] = TimeoutError("timed out")  # no signal in the hills
    page.evaluate("driveTo(26.05, 92.45)")
    expect(page.locator(".nav-off-route")).to_be_visible()
    page.evaluate("driveTo(26.051, 92.451)")
    expect(page.locator(".nav-banner.problem")).to_contain_text("No new route")
    expect(page.locator(".nav-retry")).to_be_visible()
    expect(page.locator(".nav-eta b")).to_have_text(re.compile(r"\d+ (min|h)"))  # still guided: time left on the route

    providers["router.project-osrm.org"] = osrm_with_steps
    page.locator(".nav-retry").click()
    expect(page.locator(".nav-banner.problem")).to_have_count(0)
    page.wait_for_timeout(500)
    assert len(jobs) == checks  # a re-route, failed or not, never starts a collection


def test_far_past_the_destination_is_off_the_route_not_arrived(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    start_navigation(page)
    expect(page.locator(".nav-banner .nav-road b")).to_have_text("GS Road (NH6)")
    page.evaluate("driveTo(25.45, 91.88)")  # about 14 km beyond Shillong, where the route ends
    expect(page.locator(".nav-off-route")).to_be_visible()
    expect(page.locator(".navigation")).not_to_contain_text("You have arrived")


def test_a_route_away_from_you_is_previewed_turn_by_turn(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    page.add_init_script(DRIVING)
    page.add_init_script(SPEECH)
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    page.evaluate("driveTo(25.0, 93.0)")  # far from Guwahati, where the route starts
    plan(page, "Guwahati", "Shillong")
    expect(page.locator(".route-card")).to_have_count(2)
    button = page.locator(".start-button")
    expect(button).to_have_text("Preview")
    expect(button).to_be_enabled()
    expect(page.locator(".start-note")).to_have_text("Preview steps through the turns. Live guidance starts when you are at Guwahati.")
    expect(page.locator(".map-start")).to_have_text("Preview")

    button.click()
    banner = page.locator(".nav-banner")
    expect(banner.locator(".nav-road b")).to_have_text("Head south")
    expect(banner.locator(".nav-turn")).to_have_text("Start")
    sheet = page.locator(".nav-sheet")
    expect(sheet).to_contain_text("Turn 1 of 3")
    expect(page.get_by_role("button", name="Previous turn")).to_be_disabled()
    page.get_by_role("button", name="Next turn").click()
    expect(banner.locator(".nav-road span")).to_have_text("Turn left")
    expect(banner.locator(".nav-road b")).to_have_text("GS Road (NH6)")
    expect(banner.locator(".nav-turn")).to_have_text("50 km")  # how far this turn is from the one before
    expect(sheet).to_contain_text("Turn 2 of 3")
    page.get_by_role("button", name="Next turn").click()
    expect(banner).to_contain_text("Arrive at your destination")
    expect(page.get_by_role("button", name="Next turn")).to_be_disabled()
    expect(page.locator(".nav-off-route")).to_have_count(0)  # a preview never says you are off the route
    expect(page.locator(".leaflet-marker-pane .nav-arrow")).to_have_count(1)
    assert page.evaluate("window.said") == []  # and never speaks
    page.get_by_role("button", name="Close preview").click()
    expect(page.locator(".navigation")).to_have_count(0)


def test_a_typed_start_where_you_are_is_guided_live(dashboard, providers):
    providers["router.project-osrm.org"] = osrm_with_steps
    page = dashboard
    page.add_init_script(DRIVING)  # the device is at Guwahati
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    plan(page, "Guwahati", "Shillong")
    expect(page.locator(".start-button")).to_have_text("Start")
    expect(page.locator(".start-note")).to_have_count(0)
    page.locator(".start-button").click()
    expect(page.locator(".nav-banner .nav-road b")).to_have_text("GS Road (NH6)")
    expect(page.locator(".nav-sheet")).to_contain_text("min")

def test_route_cards_list_toll_plazas_on_the_route_without_inventing_prices(dashboard, providers):
    import os
    from pathlib import Path
    from test_live_locations import TOLL_LIST
    page = dashboard
    page.add_init_script(DRIVING)
    page.open()
    plan(page, "Guwahati", "Shillong")
    expect(page.locator(".route-card").first).to_contain_text("Tolls unknown")  # no list loaded: unknown, not "no tolls"
    expect(page.locator(".route-tolls")).to_contain_text("tolls on this route are unknown")

    Path(os.environ["TOLL_PLAZAS_PATH"]).write_text(TOLL_LIST, encoding="utf-8")
    plan(page, "Guwahati", "Shillong")
    expect(page.locator(".route-card", has_text="2 toll plazas")).to_have_count(1)
    page.locator(".route-card", has_text="2 toll plazas").click()
    rows = page.locator(".toll-list li")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Jorabat")
    expect(rows.nth(1)).to_contain_text("Umiam")
    expect(rows.nth(0)).to_contain_text("Price not available")
    expect(page.locator(".route-tolls")).to_contain_text("as of 03-08-2026")
    expect(page.locator(".route-tolls")).not_to_contain_text("₹")  # no price is ever shown
    expect(page.locator(".leaflet-marker-pane .toll-marker")).to_have_count(2)


def test_refused_location_leaves_the_start_for_the_person_to_type(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })"))
    page.open()
    expect(page.locator(".place-note")).to_have_text("Location is blocked for this site: allow it from the icon beside the address bar. Or type a starting point.")
    expect(page.locator("#origin")).to_have_value("")
    expect(page.locator("#origin")).to_have_attribute("placeholder", "Choose starting point")


def test_a_start_typed_before_the_location_arrives_is_kept(dashboard):
    page = dashboard
    page.add_init_script(geolocation("setTimeout(() => ok({ coords: { latitude: 26.18, longitude: 91.75 } }), 1500)"))
    page.open()
    page.fill("#origin", "Silchar")
    page.wait_for_timeout(2000)
    expect(page.locator("#origin")).to_have_value("Silchar")



def test_map_opens_on_your_location_and_the_button_returns_to_it(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.14, longitude: 91.74, accuracy: 120 } })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Your location · accurate to about 120 m")
    expect(page.locator(".locate-button")).to_be_enabled()
    expect(page.locator(".map-legend")).to_contain_text("You")
    page.locator(".locate-button").click()  # recentres without errors


def test_full_screen_button_fills_the_screen_with_the_map(dashboard):
    page = dashboard
    page.open()
    button = page.locator(".fullscreen-button")
    expect(button).to_have_attribute("aria-pressed", "false")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("document.fullscreenElement?.classList.contains('map-wrap')")
    box = page.locator(".map-wrap").bounding_box()
    assert box["height"] == page.evaluate("window.innerHeight")
    expect(page.locator(".map-wrap .map-legend")).to_be_visible()  # legend and credits come along
    search = page.locator(".map-search").bounding_box()
    assert abs(search["x"] + search["width"] / 2 - page.evaluate("window.innerWidth") / 2) <= 1  # search bar centred
    expect(page.locator(".map-credit small")).to_be_hidden()  # credits fold behind an "i"
    page.locator(".map-credit summary").click()
    expect(page.locator(".map-credit small")).to_contain_text("© OpenStreetMap")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".map-credit")).to_have_count(0)


def test_full_screen_falls_back_to_the_window_without_browser_support(dashboard):
    page = dashboard
    page.add_init_script("Object.defineProperty(Document.prototype, 'fullscreenEnabled', { get: () => false })")  # like iPhone Safari
    page.open()
    page.locator(".fullscreen-button").click()
    expect(page.locator(".map-wrap.fullscreen")).to_have_count(1)
    assert page.locator(".map-wrap").bounding_box()["height"] == page.evaluate("window.innerHeight")
    page.keyboard.press("Escape")
    expect(page.locator(".map-wrap.fullscreen")).to_have_count(0)


def test_map_stays_on_the_region_when_location_is_refused(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Location is blocked for this site: allow it from the icon beside the address bar. Showing Northeast India.")
    expect(page.locator(".locate-button")).to_be_enabled()  # pressing it asks again, once the person allows it


def test_location_button_asks_again_after_a_refusal(dashboard):
    page = dashboard
    # The first request is refused (a dismissed prompt); the person then allows location and presses the button.
    page.add_init_script(SECURE + """Object.defineProperty(navigator, 'geolocation', { value: {
        getCurrentPosition: (ok, fail) => fail({ code: 1, PERMISSION_DENIED: 1 }),
        watchPosition: (ok, fail) => { window.watches = (window.watches || 0) + 1;
          if (window.watches === 1) fail({ code: 1, PERMISSION_DENIED: 1 });
          else ok({ coords: { latitude: 26.14, longitude: 91.74, accuracy: 50 } }); return window.watches },
        clearWatch: () => {} } })""")
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Location is blocked for this site")
    page.locator(".locate-button").click()
    expect(page.locator(".map-foot")).to_contain_text("Your location · accurate to about 50 m")


def test_location_explains_that_it_needs_https_or_localhost(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })").replace(SECURE, ""))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Location only works on https or localhost")


def test_location_explains_a_device_without_a_position(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 2, PERMISSION_DENIED: 1 })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("This device could not find its position: check that Location Services is on for your browser.")


def test_map_stays_on_the_region_when_you_are_outside_india(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 51.5, longitude: -0.12, accuracy: 30 } })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Your location is outside India. Showing Northeast India.")
    expect(page.locator(".locate-button")).to_be_disabled()


def test_map_layers_change_the_map_and_are_remembered(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 26.14, longitude: 91.74, accuracy: 120 } })"))
    page.open()
    page.click(".layers-button")
    expect(page.locator(".layers-panel")).to_be_visible()
    expect(page.locator(".layer-tile", has_text="Traffic")).to_be_disabled()  # live traffic needs the Mappls map
    expect(page.locator(".layer-tile", has_text="Traffic")).to_contain_text("Needs the Mappls map")

    page.locator(".layer-tile", has_text="Satellite").click()
    page.locator(".layer-tile", has_text="Wildfires").click()
    page.locator(".layer-tile", has_text="Air quality").click()
    page.keyboard.press("Escape")
    expect(page.locator(".layers-panel")).to_have_count(0)
    expect(page.locator(".leaflet-tile-pane img[src*='World_Imagery']").first).to_be_attached()
    expect(page.locator(".leaflet-tile-pane img[src*='gibs.earthdata.nasa.gov']").first).to_be_attached()
    expect(page.locator(".leaflet-tile-pane img[src*='VIIRS_NOAA20_Thermal_Anomalies']").first).to_be_attached()
    expect(page.locator(".aqi-pill")).to_have_text("AQI 97")
    expect(page.locator(".map-foot")).to_contain_text("Imagery © Esri")
    expect(page.locator(".map-foot")).to_contain_text("Fires: NASA VIIRS")

    page.reload()
    expect(page.locator(".map-foot")).to_contain_text("Imagery © Esri")  # remembered in this browser
    page.click(".layers-button")
    expect(page.locator(".layer-tile", has_text="Satellite")).to_have_attribute("aria-checked", "true")
    expect(page.locator(".layer-tile", has_text="Wildfires")).to_have_attribute("aria-pressed", "true")


def _varint(value):
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number, wire, payload):
    return _varint(number << 3 | wire) + (_varint(len(payload)) + payload if wire == 2 else payload)


def _mvt_layer(name, features, z, x, y):
    """One vector-tile layer: [(properties, [(latitude, longitude), ...])]; one point is a point, more a line."""
    import math
    extent = 4096
    zig = lambda n: (n << 1) ^ (n >> 31)

    def pixel(latitude, longitude):
        py = (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * 2 ** z - y
        return round(((longitude + 180) / 360 * 2 ** z - x) * extent), round(py * extent)

    keys = list(dict.fromkeys(key for properties, _ in features for key in properties))
    values = list(dict.fromkeys(value for properties, _ in features for value in properties.values()))
    body = b""
    for properties, coordinates in features:
        points = [pixel(*point) for point in coordinates]
        commands, cx, cy = [1 | 1 << 3], 0, 0
        for index, (px, py) in enumerate(points):
            if index == 1:
                commands.append(2 | (len(points) - 1) << 3)
            commands += [zig(px - cx), zig(py - cy)]
            cx, cy = px, py
        geometry = b"".join(_varint(value) for value in commands)
        tags = b"".join(_varint(value) for key, item in properties.items() for value in (keys.index(key), values.index(item)))
        kind = 1 if len(points) == 1 else 2
        body += _field(2, 2, _field(2, 2, tags) + _field(3, 0, _varint(kind)) + _field(4, 2, geometry))
    layer = (_field(15, 0, _varint(2)) + _field(1, 2, name.encode()) + body
             + b"".join(_field(3, 2, key.encode()) for key in keys)
             + b"".join(_field(4, 2, _field(1, 2, value.encode())) for value in values) + _field(5, 0, _varint(extent)))
    return _field(3, 2, layer)


def place_tile(places, z, x, y, roads=()):
    """A minimal Mapbox vector tile: a "place" layer of points [(name, class, latitude, longitude)] and,
    optionally, roads [(class, [(latitude, longitude), ...])] in "transportation"."""
    tile = _mvt_layer("place", [({"name": name, "class": kind}, [(latitude, longitude)]) for name, kind, latitude, longitude in places], z, x, y)
    if roads:
        tile += _mvt_layer("transportation", [({"class": kind}, line) for kind, line in roads], z, x, y)
    return tile


def test_satellite_view_names_places_inside_india_only_and_draws_roads(dashboard):
    places = [("Guwahati", "city", 26.18, 91.75), ("Shillong", "city", 25.57, 91.88),
              ("Sylhet", "city", 24.90, 91.87)]  # Bangladesh: never named on the map
    roads = [("trunk", [(26.18, 91.0), (25.57, 91.88), (25.0, 93.5)])]  # a highway across the region
    page = dashboard
    esri_roads = []
    page.route("**/World_Transportation/**", lambda route: (esri_roads.append(route.request.url), route.abort()))

    def tile(route):
        z, x, y = (int(part.split(".")[0]) for part in route.request.url.rsplit("/", 3)[1:])
        route.fulfill(status=200, body=place_tile(places, z, x, y, roads), headers={"content-type": "application/x-protobuf"})
    page.route("https://tiles.openfreemap.org/planet", lambda route: route.fulfill(
        status=200, body='{"tiles": ["https://tiles.openfreemap.org/planet/test/{z}/{x}/{y}.pbf"]}', headers={"content-type": "application/json"}))
    page.route("https://tiles.openfreemap.org/planet/test/**", tile)
    page.add_init_script("localStorage.setItem('india-trace.map-layers', JSON.stringify({ base: 'satellite', overlays: [] }))")
    page.open()
    expect(page.locator(".map-label", has_text="Guwahati")).to_have_count(1)
    expect(page.locator(".map-label", has_text="Shillong")).to_have_count(1)
    expect(page.locator(".map-label", has_text="Sylhet")).to_have_count(0)
    # Roads are drawn in Google's highway yellow on canvas tiles over the imagery.
    expect(page.locator(".hybrid-roads canvas").first).to_be_attached()
    page.wait_for_function("""() => [...document.querySelectorAll('.hybrid-roads canvas')].some((canvas) => {
        const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
        for (let index = 0; index < pixels.length; index += 4) {
          if (pixels[index + 3] > 200 && pixels[index] > 230 && pixels[index + 1] > 190 && pixels[index + 2] < 140) return true
        }
        return false
    })""")
    assert esri_roads == []
    expect(page.locator(".map-foot")).to_contain_text("Roads and place names © OpenStreetMap contributors via OpenFreeMap")


def test_map_has_no_corner_thumbnail_switch(dashboard):
    page = dashboard
    page.open()
    expect(page.locator(".leaflet-control-scale")).to_have_count(1)
    expect(page.locator(".base-switch")).to_have_count(0)  # map type is chosen from the Layers panel


def test_route_times_say_where_they_come_from_and_google_turns_are_worded_by_google(dashboard, providers, monkeypatch):
    from test_google_routes import GOOGLE, google_answer
    page = dashboard
    page.add_init_script(DRIVING)
    page.add_init_script(SPEECH)
    page.open()
    expect(page.locator("#origin")).to_have_value("Your location")
    page.fill("#destination", "Shillong")
    page.keyboard.press("Escape")
    page.click(".primary-button")
    expect(page.locator(".route-card").first.locator(".time-source")).to_have_text("OSRM · no traffic")
    expect(page.locator(".results-provider")).to_have_text("OSRM estimates · no traffic")

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-google-key")
    get_settings.cache_clear()
    providers[GOOGLE] = google_answer
    page.click(".primary-button")
    expect(page.locator(".route-card")).to_have_count(1)
    expect(page.locator(".route-card .time-source")).to_have_text("Google · live traffic")
    expect(page.locator(".route-card .route-facts")).to_contain_text("3 h")
    expect(page.locator(".routing-note")).to_have_count(0)

    page.locator(".start-button").click()
    expect(page.locator(".nav-road")).to_contain_text("Turn right")
    expect(page.locator(".nav-road b")).to_have_text("Mawlai Bypass")
