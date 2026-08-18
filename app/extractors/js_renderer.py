from __future__ import annotations

from dataclasses import dataclass

from app.extractors.html_extractor import PageExtraction, extract_page
from app.crawler.url_normalizer import DomainScope
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RenderResult:
    html: str
    final_url: str
    title: str | None = None


class JavascriptRenderer:
    """Lazy Playwright renderer. Started only when a page actually needs JS."""

    def __init__(self, *, timeout_ms: float = 20_000, user_agent: str | None = None) -> None:
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._available: bool | None = None
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._available is not False

    async def start(self) -> bool:
        if self._browser is not None:
            return True
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            self._available = False
            self._error = f"playwright_not_installed: {exc}"
            logger.warning("js_renderer_unavailable", error=self._error)
            return False
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._available = True
            logger.info("js_renderer_started")
            return True
        except Exception as exc:  # browsers may not be installed
            self._available = False
            self._error = str(exc)
            logger.warning("js_renderer_start_failed", error=self._error)
            return False

    async def render(self, url: str) -> RenderResult | None:
        if not await self.start() or self._browser is None:
            return None
        context = await self._browser.new_context(
            user_agent=self.user_agent,
            java_script_enabled=True,
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=self.timeout_ms)
            await page.wait_for_timeout(800)
            html = await page.content()
            title = await page.title()
            final_url = page.url
            return RenderResult(html=html, final_url=final_url, title=title)
        except Exception as exc:
            logger.warning("js_render_failed", url=url, error=str(exc))
            return None
        finally:
            await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @property
    def error(self) -> str | None:
        return self._error


def extract_rendered_page(
    html: str,
    base_url: str,
    scope: DomainScope,
    *,
    strip_query_params: list[str] | None = None,
) -> PageExtraction:
    return extract_page(html, base_url, scope, strip_query_params=strip_query_params)
