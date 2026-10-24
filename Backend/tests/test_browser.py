"""Browser end-to-end tests: the built React dashboard in Chrome, talking to the real FastAPI app.

The frontend is built with VITE_API_URL=http://india-trace.test. Playwright serves the built
files for that origin and hands every /api request to the app on a temporary database, so the
whole stack runs: React, the service layer, FastAPI, SQLite. External services (Nominatim, OSRM,
TinyFish) use the network fakes from conftest; map tiles and web fonts are blocked.

Needs Node/npm and Chrome (or `E2E_BROWSER_CHANNEL=chromium` after `playwright install chromium`).
Skipped when either is missing. Run only these with `pytest -m e2e`, or skip them with `-m "not e2e"`.
"""
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
GEOLOCATION = """Object.defineProperty(navigator, 'geolocation', { value: {
    getCurrentPosition: (ok, fail) => { %s },
    watchPosition: (ok, fail) => { %s; return 1 },
    clearWatch: () => {} } })"""


def geolocation(body):
    return GEOLOCATION % (body, body)


def plan(page, origin, destination):
    page.fill("#origin", origin)
    page.fill("#destination", destination)
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
    expect(page.locator(".summary-card.green b")).to_have_text("0")  # no route planned yet: the cards wait for one
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
    expect(page.locator(".summary-card.violet b")).to_have_text("0")
    expect(page.locator(".map-options .toggle-row", has_text="Landslides")).to_contain_text("1 on map")

    # Plan again. The form's default "cautious" priority puts the route that avoids the confirmed report first;
    # it still says verify, because the old report names NH-6 without a location.
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
    expect(page.locator(".map-status")).to_have_text("Historical snapshot")


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

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
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
    expect(page.locator(".leaflet-india-mask-pane path")).to_have_count(2)  # the mask and India's outline
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



def test_town_placed_reports_have_no_map_marker_and_live_refresh_announces_new_reports(dashboard, client, add_incident):
    add_incident("first", summary="Landslide near Shillong blocks traffic", published_at="2 hours ago")
    assert client.post("/api/places/locate").json()["found"] == 1  # Shillong, from the Nominatim fake
    page = dashboard
    page.clock.install()
    page.open()
    expect(page.locator(".selected-incident .incident-meta")).to_contain_text("Approximate · Shillong named in report")
    expect(page.locator(".leaflet-marker-icon")).to_have_count(0)  # town-placed reports are not drawn on the map
    expect(page.locator(".map-options")).not_to_contain_text("1 on map")

    add_incident("second", summary="Second slide near Shillong", published_at="1 hour ago")
    page.clock.run_for(61_000)  # the dashboard reloads every minute
    expect(page.locator(".evidence-row")).to_have_count(2)
    expect(page.locator(".collection-message")).to_contain_text("1 new report arrived at")

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
    expect(page.locator(".summary-card.green b")).to_have_text("0")

    plan(page, "Guwahati, Assam", "Shillong, Meghalaya")
    expect(page.locator(".summary-scope")).to_contain_text("Route 1: Guwahati → Shillong")
    expect(page.locator(".live-check")).to_contain_text("Live check")
    expect(page.locator(".live-check")).to_contain_text("1 new report from the route search")
    expect(page.locator(".summary-card.amber b")).to_have_text("1")   # the new landslide names NH-6, which the route uses
    expect(page.locator(".summary-card.green")).to_contain_text("Reports for this route")
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
    expect(page.locator(".map-heading h2")).to_have_text("Your location to Shillong")


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
    expect(page.locator(".map-heading h2")).to_have_text("Your location to Shillong")


def test_refused_location_leaves_the_start_for_the_person_to_type(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })"))
    page.open()
    expect(page.locator(".place-note")).to_have_text("Location permission was refused. Type a starting point instead.")
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


def test_map_stays_on_the_region_when_location_is_refused(dashboard):
    page = dashboard
    page.add_init_script(geolocation("fail({ code: 1, PERMISSION_DENIED: 1 })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Location permission was refused. Showing Northeast India.")
    expect(page.locator(".locate-button")).to_be_disabled()


def test_map_stays_on_the_region_when_you_are_outside_india(dashboard):
    page = dashboard
    page.add_init_script(geolocation("ok({ coords: { latitude: 51.5, longitude: -0.12, accuracy: 30 } })"))
    page.open()
    expect(page.locator(".map-foot")).to_contain_text("Your location is outside India. Showing Northeast India.")
    expect(page.locator(".locate-button")).to_be_disabled()
