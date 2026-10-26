"""A public deployment sets ADMIN_TOKEN: reading and route planning stay open, while actions that spend TinyFish
quota or change records need the team's token. Without the setting (a laptop) everything stays open."""
import pytest

from app.config import get_settings

TOKEN = "team-secret"
PLAN = {"origin": "Guwahati", "destination": "Shillong", "vehicle_type": "car", "priority": "fastest"}
TEAM_ONLY = [("post", "/api/collection/jobs", {}), ("post", "/api/collection/run", {}), ("post", "/api/recheck/jobs", {}),
             ("post", "/api/recheck", {}), ("post", "/api/media/collect", None),
             ("patch", "/api/incidents/any/review", {"verification": "confirmed"}),
             ("post", "/api/incidents/any/flags", {"reason": "wrong_location"}), ("post", "/api/v1/traces", {}),
             ("get", "/api/admin/check", None)]


@pytest.fixture
def public(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield client
    get_settings.cache_clear()


@pytest.mark.parametrize("method,path,body", TEAM_ONLY)
def test_team_actions_need_the_token_on_a_public_site(public, method, path, body):
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN[:-1]}):
        answer = public.request(method, path, json=body, headers=headers)
        assert answer.status_code == 401 and "Sign in as a reviewer" in answer.json()["detail"]
    answer = public.request(method, path, json=body, headers={"Authorization": f"Bearer {TOKEN}"})
    assert answer.status_code != 401  # past the check (the request itself may still be invalid)


def test_reading_and_route_planning_stay_open(public, providers):
    health = public.get("/api/health").json()
    assert health["admin_required"] is True
    assert public.get("/api/incidents").status_code == 200
    assert public.get("/api/collection/runs").status_code == 200
    assert public.post("/api/routes/plan", json=PLAN).status_code == 200


def test_without_a_token_setting_nothing_is_locked(client):
    assert client.get("/api/health").json()["admin_required"] is False
    assert client.get("/api/admin/check").json() == {"ok": True}
    assert client.post("/api/collection/jobs", json={}).status_code != 401
