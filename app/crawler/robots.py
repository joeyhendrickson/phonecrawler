from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx

from app.utils.logging import get_logger

SITEMAP_RE = re.compile(r"(?i)^sitemap:\s*(\S+)")
CRAWL_DELAY_RE = re.compile(r"(?i)^crawl-delay:\s*([\d.]+)")

logger = get_logger(__name__)


@dataclass
class RobotsRules:
    fetched: bool = False
    url: str | None = None
    sitemaps: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    parser: RobotFileParser | None = None
    error: str | None = None

    def can_fetch(self, user_agent: str, url: str, *, respect: bool = True) -> bool:
        if not respect or not self.parser:
            return True
        try:
            return bool(self.parser.can_fetch(user_agent, url))
        except Exception:
            return True


async def load_robots(
    client: httpx.AsyncClient,
    start_url: str,
    *,
    user_agent: str,
) -> RobotsRules:
    robots_url = urljoin(start_url if start_url.endswith("/") else start_url + "/", "/robots.txt")
    rules = RobotsRules(url=robots_url)
    try:
        response = await client.get(robots_url, timeout=15.0, follow_redirects=True)
        if response.status_code >= 400:
            rules.error = f"HTTP {response.status_code}"
            logger.info("robots_unavailable", url=robots_url, status=response.status_code)
            return rules
        text = response.text
        rules.fetched = True
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(text.splitlines())
        rules.parser = parser
        for line in text.splitlines():
            stripped = line.strip()
            sitemap_match = SITEMAP_RE.match(stripped)
            if sitemap_match:
                loc = sitemap_match.group(1).strip()
                rules.sitemaps.append(urljoin(robots_url, loc))
            delay_match = CRAWL_DELAY_RE.match(stripped)
            if delay_match:
                try:
                    rules.crawl_delay = float(delay_match.group(1))
                except ValueError:
                    pass
        logger.info(
            "robots_loaded",
            url=robots_url,
            sitemaps=len(rules.sitemaps),
            crawl_delay=rules.crawl_delay,
        )
    except httpx.HTTPError as exc:
        rules.error = str(exc)
        logger.warning("robots_fetch_failed", url=robots_url, error=str(exc))
    return rules
