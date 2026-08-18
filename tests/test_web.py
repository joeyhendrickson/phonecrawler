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
