from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.config import CrawlConfig
from app.crawler.crawler import PhoneCrawler
from app.exporters.csv_exporter import export_csvs
from app.exporters.excel_exporter import export_excel
from app.exporters.report_exporter import export_report
from app.processing.classification import classify_inventory
from app.processing.coverage import attach_coverage
from app.processing.deduplication import build_unique_inventory

SAMPLE = (Path(__file__).parent / "fixtures" / "sample.html").read_bytes()

INDEX = b"""<!DOCTYPE html>
<html><head><title>Home</title></head>
<body>
  <h1>Example University</h1>
  <p>Call the switchboard at (614) 555-0100</p>
  <a href="/admissions/staff">Staff directory</a>
  <a href="/login">Login</a>
  <a href="https://other.edu/contact">External</a>
</body></html>
"""

ROBOTS = b"""User-agent: *
Allow: /
Disallow: /secret
Sitemap: /sitemap.xml
"""

SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>INDEX</loc></url>
  <url><loc>STAFF</loc></url>
</urlset>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        routes = {
            "/": INDEX,
            "/robots.txt": ROBOTS,
            "/admissions/staff": SAMPLE,
            "/secret": b"should not be fetched",
        }
        if self.path == "/sitemap.xml":
            host = self.headers.get("Host", "127.0.0.1")
            body = (
                SITEMAP.replace(b"INDEX", f"http://{host}/".encode())
                .replace(b"STAFF", f"http://{host}/admissions/staff".encode())
            )
            self._send(200, "application/xml", body)
            return
        body = routes.get(self.path.split("?", 1)[0])
        if body is None:
            self._send(404, "text/plain", b"missing")
            return
        content_type = "text/plain" if self.path.endswith(".txt") else "text/html; charset=utf-8"
        self._send(200, content_type, body)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_end_to_end_local_site(site_url, tmp_path):
    config = CrawlConfig(
        start_url=site_url,
        output_dir=tmp_path,
        max_pages=10,
        max_pdfs=0,
        max_depth=3,
        concurrency=2,
        delay=0,
        include_pdfs=False,
        render_js="off",
        discover_sitemaps=True,
        respect_robots=True,
        timeout=5,
    )
    result = await PhoneCrawler(config).run()
    attach_coverage(result, strip_query_params=config.strip_query_params)
    result.unique_phones = classify_inventory(build_unique_inventory(result.occurrences))
    urls = {page.requested_url for page in result.pages}
    assert any(url.rstrip("/").endswith("") or url.endswith("/") for url in urls)
    assert any("/admissions/staff" in url for url in urls)
    assert not any("/secret" in url for url in urls)
    assert not any("/login" in url for url in urls)
    e164s = {item.e164_phone for item in result.unique_phones}
    assert "+16145550100" in e164s
    assert "+16145551234" in e164s
    jane = next(item for item in result.occurrences if item.e164_phone == "+16145551234")
    assert jane.context and "Jane Smith" in jane.context
    assert result.url_inventory
    assert any(row.coverage_status.value == "SITEMAP_AND_CRAWLED" for row in result.url_inventory)

    export_csvs(result, tmp_path)
    export_excel(result, tmp_path)
    export_report(result, tmp_path)
    for name in (
        "phone_inventory.csv",
        "phone_occurrences.csv",
        "url_inventory.csv",
        "crawl_report.csv",
        "crawl_errors.csv",
        "phone_inventory.xlsx",
        "crawl_report.md",
        "crawl_state.sqlite",
    ):
        assert (tmp_path / name).exists(), name
