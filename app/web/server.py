from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.config import DEFAULT_EXCLUDE_PATTERNS, CrawlConfig, default_output_dir, output_root
from app.utils.logging import progress_callback

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = output_root()
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
ON_VERCEL = bool(os.getenv("VERCEL"))
HOSTED_MAX_PAGES = 40
HOSTED_MAX_PDFS = 20
HOSTED_MAX_DEPTH = 4
HOSTED_MAX_CONCURRENCY = 4
HOSTED_MAX_SITEMAP_URLS = 250

app = FastAPI(title="Phone Crawler", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


class CrawlRequest(BaseModel):
    start_url: str
    country: str = "US"
    max_pages: int = 500
    max_depth: int = 8
    concurrency: int = 6
    delay: float = 0.35
    timeout: float = 20.0
    render_js: Literal["off", "auto", "always"] = "auto"
    include_pdfs: bool = True
    respect_robots: bool = True
    allow_subdomains: bool = False
    discover_sitemaps: bool = True
    resume: bool = False
    output_dir: str | None = None

    @field_validator("start_url")
    @classmethod
    def _url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Start URL is required")
        return cleaned


class Job(BaseModel):
    id: str
    start_url: str
    output_dir: str
    status: Literal["queued", "running", "complete", "error"] = "queued"
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


jobs: dict[str, Job] = {}
_jobs_lock = asyncio.Lock()


def _page_vars(**kwargs: Any) -> dict[str, Any]:
    return {"on_vercel": ON_VERCEL, **kwargs}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_to_status(job: Job) -> dict[str, Any]:
    return job.model_dump()


def _safe_output(path: Path) -> Path:
    output_root = OUTPUT_ROOT.resolve()
    resolved = path.resolve()
    if output_root not in resolved.parents and resolved != output_root:
        raise HTTPException(status_code=400, detail="Invalid output path")
    return resolved


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({key: (value if value is not None else "") for key, value in row.items()})
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _summary_from_csv(output_dir: Path) -> dict[str, Any]:
    report = output_dir / "crawl_report.csv"
    rows = _read_csv(report)
    return {row.get("metric", ""): row.get("value", "") for row in rows}


def _scan_runs() -> list[dict[str, Any]]:
    try:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    runs: list[dict[str, Any]] = []
    known = {job.output_dir: job for job in jobs.values()}
    for path in sorted(OUTPUT_ROOT.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.name.startswith("."):
            continue
        live = known.get(str(path))
        inventory = path / "phone_inventory.csv"
        state = path / "crawl_state.sqlite"
        if live:
            status = live.status
            start_url = live.start_url
            summary = live.summary
        elif inventory.exists():
            status = "complete"
            summary = _summary_from_csv(path)
            start_url = str(summary.get("Start URL") or path.name)
        elif state.exists():
            status = "interrupted"
            summary = {}
            start_url = path.name
        else:
            continue
        runs.append(
            {
                "id": live.id if live else path.name,
                "name": path.name,
                "start_url": start_url,
                "status": status,
                "output_dir": str(path),
                "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "summary": summary,
            }
        )
    return runs


async def _execute_job(job_id: str, config: CrawlConfig) -> None:
    job = jobs[job_id]
    job.status = "running"
    job.started_at = _utc_now()

    def on_progress(tag: str, message: str) -> None:
        job.logs.append(f"[{tag}] {message}")
        if len(job.logs) > 4000:
            del job.logs[:-3000]

    token = progress_callback.set(on_progress)
    try:
        from app.exporters.summary import summary_rows
        from app.main import run_inventory

        result, _paths = await run_inventory(config)
        job.summary = {
            "unique_phones": len(result.unique_phones),
            "occurrences": len(result.occurrences),
            "pages": len(result.pages),
            "Domain": result.registrable_domain,
            "Start URL": result.start_url,
        }
        job.summary.update({row["metric"]: row["value"] for row in summary_rows(result)})
        job.status = "complete"
        snapshot = _job_snapshot(job, compact=True)
        (config.output_dir / "job.json").write_text(
            json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
        job.logs.append(f"[ERROR] {exc}")
    finally:
        progress_callback.reset(token)
        job.finished_at = _utc_now()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        _page_vars(runs=_scan_runs()),
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_page(request: Request, run_id: str) -> HTMLResponse:
    live = jobs.get(run_id)
    output_dir = Path(live.output_dir) if live else OUTPUT_ROOT / run_id
    if not output_dir.exists() and live is None and not ON_VERCEL:
        raise HTTPException(status_code=404, detail="Run not found")
    return TEMPLATES.TemplateResponse(
        request,
        "run.html",
        {
            "run_id": run_id,
            "output_name": output_dir.name,
            "on_vercel": ON_VERCEL,
        },
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs")
async def api_runs() -> dict[str, Any]:
    return {"runs": _scan_runs()}


def _job_tables(output_dir: Path, *, compact: bool = False) -> dict[str, list[dict[str, Any]]]:
    return {
        "inventory": _read_csv(output_dir / "phone_inventory.csv", 400 if compact else None),
        "occurrences": _read_csv(output_dir / "phone_occurrences.csv", 300 if compact else 5000),
        "coverage": _read_csv(output_dir / "url_inventory.csv", 150 if compact else 800),
        "errors": _read_csv(output_dir / "crawl_errors.csv", 100 if compact else None),
    }


def _job_snapshot(job: Job, *, compact: bool = False) -> dict[str, Any]:
    payload = _job_to_status(job)
    payload["tables"] = _job_tables(Path(job.output_dir), compact=compact)
    payload["logs"] = payload["logs"][-120:]
    return payload


def _config_from_payload(payload: CrawlRequest, output: Path) -> tuple[CrawlConfig, list[str]]:
    max_pages = payload.max_pages
    max_depth = payload.max_depth
    concurrency = payload.concurrency
    delay = payload.delay
    timeout = payload.timeout
    render_js = payload.render_js
    max_pdfs = 5_000
    notes: list[str] = []
    if ON_VERCEL:
        max_pages = min(max_pages, HOSTED_MAX_PAGES)
        max_depth = min(max_depth, HOSTED_MAX_DEPTH)
        concurrency = min(concurrency, HOSTED_MAX_CONCURRENCY)
        delay = max(delay, 0.25)
        timeout = min(timeout, 12.0)
        render_js = "off"
        max_pdfs = HOSTED_MAX_PDFS
        notes.append(
            f"Production crawl capped at {max_pages} pages, JS rendering off, {max_pdfs} PDFs."
        )
    return CrawlConfig(
        start_url=payload.start_url,
        output_dir=output,
        country=payload.country,
        max_pages=max_pages,
        max_pdfs=max_pdfs,
        max_depth=max_depth,
        concurrency=concurrency,
        delay=delay,
        timeout=timeout,
        render_js=render_js,
        include_pdfs=payload.include_pdfs,
        respect_robots=payload.respect_robots,
        allow_subdomains=payload.allow_subdomains,
        discover_sitemaps=payload.discover_sitemaps,
        resume=payload.resume,
        exclude_url_patterns=list(DEFAULT_EXCLUDE_PATTERNS),
        max_sitemap_urls=HOSTED_MAX_SITEMAP_URLS if ON_VERCEL else 100_000,
    ), notes


@app.post("/api/crawls")
async def start_crawl(payload: CrawlRequest) -> dict[str, Any]:
    output = Path(payload.output_dir) if payload.output_dir else default_output_dir(payload.start_url)
    output = _safe_output(output) if payload.output_dir else output
    output.mkdir(parents=True, exist_ok=True)
    config, notes = _config_from_payload(payload, output)
    job_id = output.name
    async with _jobs_lock:
        if any(job.status == "running" for job in jobs.values()):
            raise HTTPException(
                status_code=409,
                detail="A crawl is already running. Wait for it to finish so the target site is not overloaded.",
            )
        job = Job(
            id=job_id,
            start_url=payload.start_url,
            output_dir=str(output),
            status="queued",
            logs=[f"[QUEUE] Starting {payload.start_url}", *[f"[QUEUE] {note}" for note in notes]],
        )
        jobs[job_id] = job
    if ON_VERCEL:
        try:
            await _execute_job(job_id, config)
            return {"id": job_id, "output_dir": str(output), **_job_snapshot(jobs[job_id], compact=True)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Crawl failed: {exc}") from exc
    asyncio.create_task(_execute_job(job_id, config))
    return {"id": job_id, "output_dir": str(output)}


@app.get("/api/crawls/{run_id}")
async def crawl_status(run_id: str) -> dict[str, Any]:
    if run_id in jobs:
        job = jobs[run_id]
        if job.status == "complete":
            return _job_snapshot(job, compact=True)
        payload = _job_to_status(job)
        payload["logs"] = payload["logs"][-200:]
        return payload
    output_dir = OUTPUT_ROOT / run_id
    snapshot_path = output_dir / "job.json"
    if snapshot_path.exists():
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    summary = _summary_from_csv(output_dir)
    log_path = output_dir / "crawl.log"
    logs = []
    if log_path.exists():
        logs = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    status = "complete" if (output_dir / "phone_inventory.csv").exists() else "interrupted"
    return {
        "id": run_id,
        "start_url": summary.get("Start URL") or run_id,
        "output_dir": str(output_dir),
        "status": status,
        "logs": logs,
        "error": None,
        "summary": summary,
    }


@app.get("/api/crawls/{run_id}/inventory")
async def crawl_inventory(run_id: str) -> dict[str, Any]:
    output_dir = Path(jobs[run_id].output_dir) if run_id in jobs else OUTPUT_ROOT / run_id
    rows = _read_csv(output_dir / "phone_inventory.csv")
    return {"rows": rows}


@app.get("/api/crawls/{run_id}/occurrences")
async def crawl_occurrences(run_id: str) -> dict[str, Any]:
    output_dir = Path(jobs[run_id].output_dir) if run_id in jobs else OUTPUT_ROOT / run_id
    rows = _read_csv(output_dir / "phone_occurrences.csv")
    return {"rows": rows[:5000]}


@app.get("/api/crawls/{run_id}/coverage")
async def crawl_coverage(run_id: str) -> dict[str, Any]:
    output_dir = Path(jobs[run_id].output_dir) if run_id in jobs else OUTPUT_ROOT / run_id
    rows = _read_csv(output_dir / "url_inventory.csv")
    return {"rows": rows[:8000]}


@app.get("/api/crawls/{run_id}/errors")
async def crawl_errors(run_id: str) -> dict[str, Any]:
    output_dir = Path(jobs[run_id].output_dir) if run_id in jobs else OUTPUT_ROOT / run_id
    rows = _read_csv(output_dir / "crawl_errors.csv")
    return {"rows": rows}


@app.get("/api/crawls/{run_id}/files/{filename}")
async def crawl_file(run_id: str, filename: str) -> FileResponse:
    allowed = {
        "phone_inventory.csv",
        "phone_occurrences.csv",
        "url_inventory.csv",
        "crawl_report.csv",
        "crawl_errors.csv",
        "phone_inventory.xlsx",
        "crawl_report.md",
        "crawl.log",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="File not available")
    output_dir = Path(jobs[run_id].output_dir) if run_id in jobs else OUTPUT_ROOT / run_id
    path = output_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


def main() -> None:
    import uvicorn

    uvicorn.run("app.web.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
