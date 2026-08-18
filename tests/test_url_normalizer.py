from __future__ import annotations

from app.crawler.url_normalizer import (
    compile_patterns,
    is_internal,
    normalize_url,
    parse_scope,
    should_skip_url,
)


def test_normalize_strips_fragment_and_lowercase_host():
    assert (
        normalize_url("HTTPS://WWW.Example.EDU/Admissions/#staff")
        == "https://www.example.edu/Admissions"
    )


def test_normalize_trailing_slash_and_relative():
    base = "https://www.example.edu/admissions/"
    assert normalize_url("../contact/", base) == "https://www.example.edu/contact"
    assert normalize_url("https://www.example.edu/", base) == "https://www.example.edu/"


def test_normalize_strips_tracking_and_session_params():
    url = "https://www.example.edu/page?utm_source=x&id=12&sessionid=abc&b=1"
    normalized = normalize_url(url)
    assert normalized is not None
    assert "utm_source" not in normalized
    assert "sessionid" not in normalized
    assert "id=12" in normalized
    assert "b=1" in normalized


def test_scope_stays_on_host_by_default():
    scope = parse_scope("https://www.example.edu")
    assert scope.hostname == "www.example.edu"
    assert scope.registrable_domain == "example.edu"
    assert is_internal("https://www.example.edu/admissions", scope)
    assert not is_internal("https://admissions.example.edu/", scope)
    assert not is_internal("https://other.edu/", scope)


def test_scope_preserves_non_default_port():
    scope = parse_scope("http://127.0.0.1:8765/path")
    assert scope.origin == "http://127.0.0.1:8765"
    assert scope.start_url.startswith("http://127.0.0.1:8765/")
    assert is_internal("http://127.0.0.1:8765/other", scope)


def test_scope_can_allow_subdomains():
    scope = parse_scope("https://www.example.edu", allow_subdomains=True)
    assert is_internal("https://admissions.example.edu/staff", scope)
    assert not is_internal("https://example.com/", scope)


def test_skip_login_cart_calendar_and_search():
    patterns = compile_patterns(
        [
            r"/login(?:/|$|\?)",
            r"/cart(?:/|$|\?)",
            r"/calendar(?:/|$|\?)",
            r"/search(?:/|$|\?)",
            r"[?&](?:sessionid|sid)=",
            r"/print(?:/|$|\?)",
        ]
    )
    skipped = [
        "https://www.example.edu/login",
        "https://www.example.edu/cart",
        "https://www.example.edu/calendar?month=4",
        "https://www.example.edu/search?q=admissions",
        "https://www.example.edu/page?sessionid=1",
        "https://www.example.edu/print/handbook",
    ]
    for url in skipped:
        skip, _ = should_skip_url(url, exclude_patterns=patterns)
        assert skip, url
