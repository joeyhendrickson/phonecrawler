from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse, urlencode

import tldextract

from app.config import DEFAULT_EXCLUDE_PATTERNS, DEFAULT_STRIP_QUERY_PARAMS

_SCHEME_RE = re.compile(r"^https?://", re.I)
_MULTI_SLASH = re.compile(r"/{2,}")
_TLD = tldextract.TLDExtract(cache_dir="/tmp/tldextract")


@dataclass(frozen=True)
class DomainScope:
    start_url: str
    scheme: str
    hostname: str
    registrable_domain: str
    allow_subdomains: bool
    port: int | None = None

    @property
    def origin(self) -> str:
        if self.port and not (
            (self.scheme == "http" and self.port == 80)
            or (self.scheme == "https" and self.port == 443)
        ):
            return f"{self.scheme}://{self.hostname}:{self.port}"
        return f"{self.scheme}://{self.hostname}"

    def allows(self, hostname: str) -> bool:
        host = hostname.lower().rstrip(".")
        if host == self.hostname:
            return True
        if self.allow_subdomains and self.registrable_domain:
            return host == self.registrable_domain or host.endswith("." + self.registrable_domain)
        return False


def parse_scope(start_url: str, *, allow_subdomains: bool = False) -> DomainScope:
    normalized = ensure_scheme(start_url)
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError(f"Could not determine hostname from {start_url!r}")
    extracted = _TLD(hostname)
    registrable = ".".join(p for p in (extracted.domain, extracted.suffix) if p)
    scheme = parsed.scheme.lower() or "https"
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
        port = None
    path = parsed.path or "/"
    canonical_start = urlunparse((scheme, netloc, path, "", parsed.query, ""))
    return DomainScope(
        start_url=canonical_start,
        scheme=scheme,
        hostname=hostname,
        registrable_domain=registrable,
        allow_subdomains=allow_subdomains,
        port=port,
    )


def ensure_scheme(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("URL is empty")
    if url.startswith("//"):
        return "https:" + url
    if not _SCHEME_RE.match(url):
        return "https://" + url
    return url


def normalize_url(
    url: str,
    base: str | None = None,
    *,
    strip_query_params: list[str] | None = None,
    keep_fragment: bool = False,
) -> str | None:
    """Normalize a URL for crawl deduplication.

    Fragments are dropped, hostnames are lowercased, default ports removed,
    tracking/session query params stripped, and trailing slashes collapsed
    except for the origin root.
    """
    if not url or url.startswith(("mailto:", "javascript:", "data:", "tel:")):
        return None
    raw = url.strip()
    if base:
        raw = urljoin(base, raw)
    raw = ensure_scheme(raw)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return None
    port = parsed.port
    if (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443):
        netloc = hostname
    elif port:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path or "/"
    path = _MULTI_SLASH.sub("/", path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    drop = {p.lower() for p in (strip_query_params or DEFAULT_STRIP_QUERY_PARAMS)}
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in drop
    ]
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)
    fragment = parsed.fragment if keep_fragment else ""
    return urlunparse((parsed.scheme, netloc, path, "", query, fragment))


def is_internal(url: str, scope: DomainScope) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return bool(host) and scope.allows(host)


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.I))
        except re.error:
            compiled.append(re.compile(re.escape(pattern), re.I))
    return compiled


def matches_any(url: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(url) for p in patterns)


def should_skip_url(
    url: str,
    *,
    exclude_patterns: list[re.Pattern[str]] | None = None,
    include_patterns: list[re.Pattern[str]] | None = None,
) -> tuple[bool, str | None]:
    exclude_patterns = exclude_patterns or compile_patterns(DEFAULT_EXCLUDE_PATTERNS)
    if matches_any(url, exclude_patterns):
        return True, "exclude_pattern"
    if include_patterns and not matches_any(url, include_patterns):
        return True, "include_pattern"
    return False, None
