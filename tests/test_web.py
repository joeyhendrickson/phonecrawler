from fastapi.testclient import TestClient

from app.web.server import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_renders_tailwind_shell():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Phone Crawler" in html
    assert "cdn.tailwindcss.com" in html
    assert "Start a crawl" in html
    assert "Respect robots.txt" in html


def test_start_url_is_required():
    response = client.post("/api/crawls", json={"start_url": ""})
    assert response.status_code == 422


def test_vercel_production_allows_crawls(monkeypatch):
    import app.web.server as web

    async def fake_execute(job_id: str, config) -> None:
        web.jobs[job_id].status = "complete"
        web.jobs[job_id].summary = {"Unique phone numbers": "0"}

    monkeypatch.setattr(web, "ON_VERCEL", True)
    monkeypatch.setattr(web, "_execute_job", fake_execute)
    response = client.post("/api/crawls", json={"start_url": "https://www.example.edu", "max_pages": 500})
    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["status"] == "complete"
