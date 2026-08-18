from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RenderMode = Literal["off", "auto", "always"]

DEFAULT_USER_AGENT = (
    "PublicPhoneInventoryBot/1.0 (+https://localhost; public contact inventory; respects robots.txt)"
)

# Skip obvious non-content / trap URLs. Patterns are matched against the full URL.
DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    r"/logout(?:/|$|\?)",
    r"/log-out(?:/|$|\?)",
    r"/sign[-_]?out(?:/|$|\?)",
    r"/login(?:/|$|\?)",
    r"/log-in(?:/|$|\?)",
    r"/sign[-_]?in(?:/|$|\?)",
    r"/sso(?:/|$|\?)",
    r"/cas/login",
    r"/shibboleth",
    r"/wp-login",
    r"/wp-admin",
    r"/cart(?:/|$|\?)",
    r"/basket(?:/|$|\?)",
    r"/checkout(?:/|$|\?)",
    r"/calendar(?:/|$|\?)",
    r"[?&](?:cid|calendar[_-]?id)=",
    r"[?&](?:day|month|year|date)=",
    r"[?&]ical=",
    r"\.ics(?:$|\?)",
    r"/search(?:/|$|\?)",
    r"[?&](?:s|q|query|search)=",
    r"/print(?:/|$|\?)",
    r"[?&](?:print|format=print)=",
    r"[?&](?:sessionid|session_id|sid|jsessionid|phpsessid)=",
    r"/cgi-bin/",
    r"/feed(?:/|$|\?)",
    r"/comment-page-",
    r"[?&]replytocom=",
    r"/cdn-cgi/",
]

DEFAULT_STRIP_QUERY_PARAMS: list[str] = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "sessionid",
    "session_id",
    "sid",
    "jsessionid",
    "phpsessid",
]


class CrawlConfig(BaseModel):
    start_url: str
    output_dir: Path
    country: str = "US"
    max_pages: int = 25_000
    max_pdfs: int = 5_000
    max_depth: int = 10
    concurrency: int = 6
    timeout: float = 20.0
    delay: float = 0.35
    include_pdfs: bool = True
    render_js: RenderMode = "auto"
    discover_sitemaps: bool = True
    respect_robots: bool = True
    allow_subdomains: bool = False
    include_url_patterns: list[str] = Field(default_factory=list)
    exclude_url_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATTERNS))
    strip_query_params: list[str] = Field(default_factory=lambda: list(DEFAULT_STRIP_QUERY_PARAMS))
    debug: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    max_file_size: int = 50 * 1024 * 1024
    classify_ai: bool = False
    retries: int = 3
    resume: bool = False

    @field_validator("output_dir", mode="before")
    @classmethod
    def _as_path(cls, value: str | Path) -> Path:
        return Path(value)

    @field_validator("country")
    @classmethod
    def _upper_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("concurrency")
    @classmethod
    def _concurrency(cls, value: int) -> int:
        if value < 1 or value > 32:
            raise ValueError("concurrency must be between 1 and 32")
        return value

    @field_validator("max_pages", "max_pdfs", "max_depth")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value
