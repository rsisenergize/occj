"""Integration test against the real FastAPI app (startup event, demo user
seeding, routers) rather than the isolated in-memory session used by the
other test modules -- this is what actually caught the exposure/ranking
bugs during development, so it's worth keeping as a permanent regression
test even though it's slower than the unit-level tests."""
import os

import pytest
from fastapi.testclient import TestClient

# app.db's engine is created at import time from the cached Settings, so
# overriding DATABASE_URL here would be too late if any other test module
# already imported app.db first (it always has, transitively). Instead we
# just make sure the *actual* default dev DB file is empty before this
# module's tests run -- every other test file uses its own isolated
# in-memory engine (see conftest.py's `session` fixture) and never touches
# this file, so it's otherwise untouched.
DB_FILE = os.path.join(os.path.dirname(__file__), "..", "occj.db")


@pytest.fixture(scope="module", autouse=True)
def clean_db_file():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    yield
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client, username: str) -> dict:
    r = client.post("/auth/login", data={"username": username, "password": "demo-pass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_seed_is_idempotent_and_cases_are_listable(client):
    admin = _login(client, "admin1")
    first = client.post("/demo/seed", headers=admin)
    assert first.status_code == 200
    assert first.json()["status"] == "seeded"

    second = client.post("/demo/seed", headers=admin)
    assert second.json()["status"] == "already_seeded"

    cases = client.get("/cases", headers=admin).json()
    assert len(cases) == 8
    statuses = {c["status"] for c in cases}
    assert "closed" in statuses
    assert "pending_approval" in statuses


def test_approval_queue_is_scoped_by_role(client):
    admin = _login(client, "admin1")
    supervisor = _login(client, "supervisor1")

    admin_view = client.get("/approvals", headers=admin).json()
    supervisor_view = client.get("/approvals", headers=supervisor).json()

    assert len(admin_view) >= len(supervisor_view)  # admin sees every role's queue
    assert all(a["required_role"] == "supervisor" for a in supervisor_view)


def test_approve_drives_the_case_to_the_next_stall_point(client):
    admin = _login(client, "admin1")
    finance = _login(client, "finance1")

    pending = [a for a in client.get("/approvals", headers=finance).json()]
    assert pending, "expected a finance_approver-gated approval from the seeded dataset"
    approval = pending[0]

    before = client.get(f"/cases/{approval['case_id']}", headers=admin).json()
    assert before["case"]["status"] == "pending_approval"

    r = client.post(f"/approvals/{approval['id']}/decide", json={"decision": "approved"}, headers=finance)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    after = client.get(f"/cases/{approval['case_id']}", headers=admin).json()
    assert after["case"]["status"] in ("closed", "action_in_progress")
    assert len(after["actions"]) > len(before["actions"])


def test_wrong_role_gets_403_on_decide(client):
    admin = _login(client, "admin1")
    agent = _login(client, "agent1")

    pending = client.get("/approvals", headers=admin).json()
    assert pending, "expected at least one pending approval left"
    approval = pending[0]

    r = client.post(f"/approvals/{approval['id']}/decide", json={"decision": "approved"}, headers=agent)
    assert r.status_code == 403


def test_audit_replay_reflects_case_history(client):
    admin = _login(client, "admin1")
    cases = client.get("/cases", headers=admin).json()
    closed_case = next(c for c in cases if c["status"] == "closed")

    trail = client.get(f"/cases/{closed_case['id']}/audit", headers=admin).json()
    assert len(trail) > 0

    replay_now = client.get(f"/cases/{closed_case['id']}/replay", headers=admin).json()
    assert replay_now["stage"] == "outcome_retained"

    replay_early = client.get(
        f"/cases/{closed_case['id']}/replay", headers=admin, params={"as_of": closed_case["created_at"]}
    ).json()
    assert replay_early["stage"] != "outcome_retained"
