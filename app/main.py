from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from app.config import DEFAULT_EXCLUDE_PATTERNS, CrawlConfig
from app.crawler.crawler import PhoneCrawler
from app.exporters.csv_exporter import export_csvs
from app.exporters.excel_exporter import export_excel
from app.exporters.report_exporter import export_report
from app.processing.classification import classify_inventory, classify_with_ai
from app.processing.coverage import attach_coverage
from app.processing.deduplication import build_unique_inventory
from app.utils.logging import announce, get_logger, setup_logging

load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phone-inventory",
        description=(
            "Crawl a public website like a normal visitor and inventory published phone numbers. "
            "Does not bypass authentication, CAPTCHAs, robots.txt, paywalls, or access controls."
        ),
    )
    parser.add_argument("start_url", help="Starting URL or domain, e.g. https://www.example.edu")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory (default: ./output/<hostname>_<timestamp>)",
    )
    parser.add_argument("--country", default="US", help="Default phone-number region (ISO 3166-1 alpha-2)")
    parser.add_argument("--max-pages", type=int, default=25000, help="Maximum HTML pages to schedule")
    parser.add_argument("--max-pdfs", type=int, default=5000, help="Maximum PDFs to schedule")
    parser.add_argument("--max-depth", type=int, default=10, help="Maximum crawl depth from the seed URL")
    parser.add_argument("--concurrency", type=int, default=6, help="Concurrent HTTP workers (1-32)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between requests per worker (seconds)")
    parser.add_argument(
        "--include-pdfs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Download and parse publicly linked PDFs (default: true)",
    )
    parser.add_argument(
        "--render-js",
        choices=["off", "auto", "always"],
        default="auto",
        help="Playwright rendering mode",
    )
    parser.add_argument(
        "--sitemaps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Discover and parse XML sitemaps (default: true)",
    )
    parser.add_argument(
        "--respect-robots",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Honor robots.txt (default: true)",
    )
    parser.add_argument(
        "--allow-subdomains",
        action="store_true",
        help="Also crawl hosts under the same registrable domain",
    )
    parser.add_argument(
        "--include-url",
        action="append",
        default=[],
        help="Regex; if any are set, URLs must match at least one. Repeatable.",
    )
    parser.add_argument(
        "--exclude-url",
        action="append",
        default=[],
        help="Additional URL regexes to skip. Repeatable.",
    )
    parser.add_argument("--user-agent", default=None, help="Override the crawler User-Agent")
    parser.add_argument("--max-file-size", type=int, default=50 * 1024 * 1024)
    parser.add_argument(
        "--classify-ai",
        action="store_true",
        help="Optional post-crawl LLM classification. Requires OPENAI_API_KEY. Never used while crawling.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted crawl using crawl_state.sqlite in the output directory.",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose debug logging")
    return parser


def default_output_dir(start_url: str) -> Path:
    from urllib.parse import urlparse

    from app.crawler.url_normalizer import ensure_scheme

    host = urlparse(ensure_scheme(start_url)).hostname or "site"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("output") / f"{host}_{stamp}"


def config_from_args(args: argparse.Namespace) -> CrawlConfig:
    exclude = list(DEFAULT_EXCLUDE_PATTERNS) + list(args.exclude_url or [])
    output = Path(args.output) if args.output else default_output_dir(args.start_url)
    kwargs = {
        "start_url": args.start_url,
        "output_dir": output,
        "country": args.country,
        "max_pages": args.max_pages,
        "max_pdfs": args.max_pdfs,
        "max_depth": args.max_depth,
        "concurrency": args.concurrency,
        "timeout": args.timeout,
        "delay": args.delay,
        "include_pdfs": args.include_pdfs,
        "render_js": args.render_js,
        "discover_sitemaps": args.sitemaps,
        "respect_robots": args.respect_robots,
        "allow_subdomains": args.allow_subdomains,
        "include_url_patterns": args.include_url or [],
        "exclude_url_patterns": exclude,
        "debug": args.debug,
        "max_file_size": args.max_file_size,
        "classify_ai": args.classify_ai,
        "resume": args.resume,
    }
    if args.user_agent:
        kwargs["user_agent"] = args.user_agent
    return CrawlConfig(**kwargs)


async def run_inventory(config: CrawlConfig):
    from app.models.records import CrawlResult

    config.output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(debug=config.debug, log_file=config.output_dir / "crawl.log")
    log = get_logger("app.main")
    log.info("crawl_start", start_url=config.start_url, output=str(config.output_dir))
    crawler = PhoneCrawler(config)
    result: CrawlResult = await crawler.run()
    result.unique_phones = build_unique_inventory(result.occurrences)
    result.unique_phones = classify_inventory(result.unique_phones)
    if config.classify_ai:
        result.unique_phones = await classify_with_ai(result.unique_phones, result.occurrences)
    attach_coverage(result, strip_query_params=config.strip_query_params)
    csv_paths = export_csvs(result, config.output_dir)
    excel_path = export_excel(result, config.output_dir)
    report_paths = export_report(result, config.output_dir)
    for phone in result.unique_phones[:50]:
        announce("PHONE", f"{phone.e164_phone or phone.normalized_phone} — {phone.category}")
    log.info(
        "crawl_complete",
        unique_phones=len(result.unique_phones),
        occurrences=len(result.occurrences),
        pages=len(result.pages),
        excel=str(excel_path),
        report=str(report_paths["markdown"]),
    )
    result_paths = {
        "inventory": csv_paths["inventory"],
        "occurrences": csv_paths["occurrences"],
        "url_inventory": csv_paths["url_inventory"],
        "crawl_report": csv_paths["crawl_report"],
        "crawl_errors": csv_paths["crawl_errors"],
        "excel": excel_path,
        "report": report_paths["markdown"],
    }
    return result, result_paths


def cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    try:
        result, paths = asyncio.run(run_inventory(config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    print(f"Unique phones: {len(result.unique_phones)}")
    print(f"Occurrences:   {len(result.occurrences)}")
    print(f"Pages:         {len(result.pages)}")
    print(f"Inventory CSV: {paths['inventory']}")
    print(f"Occurrences:   {paths['occurrences']}")
    print(f"URL inventory: {paths['url_inventory']}")
    print(f"Crawl report:  {paths['crawl_report']}")
    print(f"Errors CSV:    {paths['crawl_errors']}")
    print(f"Excel:         {paths['excel']}")
    print(f"Report:        {paths['report']}")
    return 0


def main() -> None:
    sys.exit(cli())


if __name__ == "__main__":
    main()
