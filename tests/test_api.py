"""HTTP API in local mode (memory store, background-thread dispatch, demo agents)."""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DAILY_RUN_LIMIT", "2")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    from usecase_forge import web

    web.get_service.cache_clear()
    web._hits.clear()
    monkeypatch.setattr("usecase_forge.demo.demo_dependencies.__defaults__", (None, 0))
    yield TestClient(web.app)
    web.get_service.cache_clear()


def wait_for(client, run_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_status_reports_quota(client):
    body = client.get("/api/status").json()
    assert body["shared_key"] and body["own_key_supported"]
    assert body["runs_left_today"] == 2


def test_run_end_to_end_and_report_download(client):
    res = client.post("/api/runs", json={"url": "byjus.com"})
    assert res.status_code == 202
    run = wait_for(client, res.json()["id"])
    assert run["status"] == "succeeded" and run["scores"] == [5, 8]
    assert res.headers["cache-control"] == "no-store"

    report = client.get(f"/api/runs/{run['id']}/report.md")
    assert report.status_code == 200
    assert "attachment" in report.headers["content-disposition"]
    assert report.text.startswith("# GenAI & ML Use Cases")


def test_validation_errors_are_400(client):
    res = client.post("/api/runs", json={"url": "http://127.0.0.1"})
    assert res.status_code == 400
    assert "public websites" in res.json()["detail"]


def test_quota_exhaustion_is_429(client):
    for _ in range(2):
        assert client.post("/api/runs", json={"url": "a.com"}).status_code == 202
    res = client.post("/api/runs", json={"url": "a.com"})
    assert res.status_code == 429
    assert "own free Gemini key" in res.json()["detail"]


def test_rate_limit(client):
    payload = {"url": "a.com", "api_key": "AIza" + "x" * 35}
    codes = [client.post("/api/runs", json=payload).status_code for _ in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/" + "0" * 32).status_code == 404
    assert client.get("/api/runs/0/report.md").status_code == 404


def test_frontend_is_served_locally(client):
    page = client.get("/")
    assert page.status_code == 200 and "UseCaseForge" in page.text
