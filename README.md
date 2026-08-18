# Phone Inventory Crawler

Deterministic Python crawler that visits a **public** website the way a normal browser user would, then builds an auditable inventory of every published phone number it can find.

This is **not** an agentic crawler. Discovery, fetching, extraction, normalization, and export are all rule-based. Optional LLM classification runs **after** the crawl, if you explicitly enable it.

## What it does

Given a starting domain such as `https://www.example.edu`, the application:

1. Normalizes the start URL and stays on that host (subdomains optional).
2. Reads `robots.txt` and honors it by default.
3. Discovers XML sitemaps (including indexes and gzip).
4. Crawls in-scope HTML with bounded concurrency and retries.
5. Optionally renders JavaScript-heavy pages with Playwright (`off` / `auto` / `always`).
6. Downloads publicly linked PDFs and extracts selectable text (no OCR by default).
7. Detects phone numbers from `tel:` links, schema.org / JSON-LD, and page/PDF text.
8. Normalizes and validates numbers with `phonenumbers`.
9. Captures nearby context and provenance for every occurrence.
10. Deduplicates into a unique inventory (E.164 primary key).
11. Exports CSV, Excel, and a crawl/coverage report.
12. Reconciles sitemap URLs against what was actually crawled.

## What it will not do

It behaves like a public visitor. It does **not**:

- Bypass authentication, SSO, CAPTCHAs, paywalls, or access controls
- Ignore `robots.txt` unless you pass `--no-respect-robots`
- Follow external domains into the crawl queue
- Guess credentials or defeat anti-bot controls
- Use OCR unless you later add that optional feature
- Call an LLM while crawling

Only crawl sites you are allowed to access. Respect site terms, rate limits, and privacy expectations. Institutional directories often contain personal contact details; treat the output as sensitive.

## Requirements

- Python 3.11+ (3.12 preferred)
- For JavaScript rendering: Playwright browsers (`playwright install chromium`)

## Installation

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

`playwright install chromium` is only required for `--render-js auto` or `always`.

## Basic usage

Command line:

```bash
python -m app.main https://example.edu
```

Web UI (Tailwind dashboard on http://127.0.0.1:8000):

```bash
python -m app.web
```

The UI can start a crawl, stream tagged progress, and browse unique numbers, occurrences, coverage, and errors. Exports remain CSV/Excel in `output/`.

Production dashboard: `https://phonecrawler.vercel.app`. Hosted crawls cap at 100 pages, skip Playwright, and finish inside the function time limit. For a full-site crawl with JavaScript rendering, run locally:

```bash
python -m app.web
```

## Advanced usage

```bash
python -m app.main https://www.example.edu \
  --output ./output/example \
  --country US \
  --max-pages 25000 \
  --max-depth 10 \
  --concurrency 8 \
  --timeout 20 \
  --delay 0.35 \
  --render-js auto \
  --include-pdfs \
  --respect-robots \
  --allow-subdomains \
  --include-url '/admissions|/directory' \
  --exclude-url '/alumni' \
  --debug
```

Resume an interrupted job (same `--output` directory):

```bash
python -m app.main https://www.example.edu \
  --output ./output/example \
  --resume
```

Optional post-crawl LLM labels (never used while crawling):

```bash
python -m app.main https://www.example.edu --output ./output/example --classify-ai
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--output` | `output/<host>_<timestamp>` | Export directory |
| `--country` | `US` | Default region for parsing numbers |
| `--max-pages` | `25000` | HTML URL scheduling cap |
| `--max-pdfs` | `5000` | PDF scheduling cap |
| `--max-depth` | `10` | Link-follow depth |
| `--concurrency` | `6` | Concurrent workers (max 32) |
| `--timeout` | `20` | Per-request timeout (seconds) |
| `--delay` | `0.35s` | Per-worker pause; raised if robots `Crawl-delay` is larger |
| `--render-js` | `auto` | `off`, `auto`, or `always` |
| `--include-pdfs` / `--no-include-pdfs` | include | PDF discovery |
| `--sitemaps` / `--no-sitemaps` | on | Sitemap discovery |
| `--respect-robots` / `--no-respect-robots` | on | robots.txt |
| `--allow-subdomains` | off | Crawl `*.registrable_domain` |
| `--include-url` / `--exclude-url` | configurable defaults | Extra URL regex filters |
| `--resume` | off | Reload `crawl_state.sqlite` from the output directory |
| `--classify-ai` | off | Optional post-crawl LLM labels |
| `--user-agent` | `PublicPhoneInventoryBot/1.0` | Identifiable crawler UA |
| `--debug` | off | Verbose logs |

`--classify-ai` requires `OPENAI_API_KEY` (see `.env.example`). It labels already-extracted numbers only. It does not decide what to crawl.

## Output

Each run writes:

| File | Contents |
| --- | --- |
| `phone_inventory.xlsx` | Workbook: Summary, Phone Inventory, Phone Occurrences, URL Inventory, Crawl Coverage, Errors |
| `phone_inventory.csv` | Unique numbers, occurrence counts, source URLs, context, category |
| `phone_occurrences.csv` | One row per sighting, with full provenance |
| `url_inventory.csv` | Every discovered URL and coverage classification |
| `crawl_report.csv` | Summary dashboard metrics |
| `crawl_errors.csv` | Failed fetches and PDFs with no extractable text |
| `crawl_report.md` / `.json` | Human/machine coverage report |
| `crawl_state.sqlite` | Visited URLs, pending queue, and results for `--resume` |
| `audit.jsonl` | Append-only page log |
| `crawl.log` | Tagged progress lines plus structured logs |

Excel formatting includes frozen header rows, filters, bold headings, text-formatted phone columns, and hyperlinks on source URLs.

Coverage classifications:

- `SITEMAP_AND_CRAWLED`
- `SITEMAP_NOT_CRAWLED`
- `CRAWLED_NOT_IN_SITEMAP`
- `DISCOVERED_BUT_FAILED`
- `EXCLUDED`
- `REDIRECTED`

### Occurrence fields

`occurrence_id`, `raw_phone`, `normalized_phone`, `e164_phone`, `extension`, `validation_status`, `source_url`, `final_url`, `source_type`, `page_title`, `page_h1`, `context`, `nearest_heading`, `pdf_page_number`, `referring_url`, `crawl_timestamp`, `http_status`, `extraction_method`

`source_type` values: `HTML`, `HTML_TEL_LINK`, `HTML_SCHEMA`, `JAVASCRIPT_RENDERED`, `PDF`

`validation_status` values: `VALID`, `POSSIBLE`, `INVALID` — uncertain candidates are retained, not dropped.

Console progress looks like:

```
[DISCOVER] https://example.edu/sitemap.xml — 3,842 URLs
[CRAWL] 142/3842 https://example.edu/admissions
[PHONE] +16145551234 — Admissions Staff Directory
[PDF] https://example.edu/files/directory.pdf — 14 numbers
[JS] Rendering https://example.edu/directory
[ERROR] 500 https://example.edu/page
```

## Architecture

```
app/
  main.py                 CLI
  web/                    FastAPI + Tailwind dashboard
  config.py               Pydantic crawl settings
  crawler/                URL scope, robots, sitemaps, queue, fetch loop, SQLite state
  extractors/             HTML, Playwright, PDF, phones, context
  processing/             normalize, dedupe, classify, reconcile static vs JS, coverage
  exporters/              CSV, Excel, coverage report
  models/                 occurrence / inventory / page records
```

JavaScript rendering in `auto` mode runs only when static HTML looks thin, SPA-like, or framework-heavy. PDFs with no extractable text are recorded as `PDF_TEXT_UNAVAILABLE` so they can be reviewed (OCR can be added later without changing the pipeline).

Rule-based classification assigns categories such as Admissions, Financial Aid, Registrar, IT Support, Faculty, Staff, Department, Campus Safety, Emergency, Human Resources, General Information, Student Services, Library, Athletics, or Unknown. Extraction does not depend on classification.

## Tests

```bash
pytest
```

## Ethics and crawl etiquette

Use this tool on public pages you are authorized to inventory. Do not point it at authenticated portals. Keep robots.txt honored for production use. The default user agent is `PublicPhoneInventoryBot/1.0`. Concurrency defaults to 6 workers with a request delay; do not raise those aggressively.

Backup repository: [github.com/joeyhendrickson/phonecrawler](https://github.com/joeyhendrickson/phonecrawler).
