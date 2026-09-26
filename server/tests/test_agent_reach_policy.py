"""agent-reach policy tests (vNext V2-8, D25/I8).

No test here opens a socket: the resolver and the transport are both injected,
so every refusal path can be exercised deterministically.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.ai.reach import (
    ReachDeniedError,
    ReachPolicy,
    ReachRateLimitedError,
    ReachResponse,
)

PUBLIC_IP = "93.184.216.34"


def public_resolver(hostname: str) -> Sequence[str]:
    return [PUBLIC_IP]


def policy(**overrides: object) -> ReachPolicy:
    kwargs: dict[str, object] = {"resolver": public_resolver}
    kwargs.update(overrides)
    return ReachPolicy(**kwargs)  # type: ignore[arg-type]


def test_ordinary_public_pages_are_allowed_without_approval() -> None:
    """D25 is default-allow: no first-visit approval queue."""
    reach = policy()
    for url in (
        "https://example.com/products/pump-a",
        "http://standards.example.org/gb-t-1234",
        "https://example.com/search?q=%E6%B0%94%E6%B3%B5",
    ):
        assert reach.assert_url_allowed(url) == url


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", "scheme_not_allowed"),
        ("ftp://example.com/x", "scheme_not_allowed"),
        ("gopher://example.com/x", "scheme_not_allowed"),
        ("https://user:secret@example.com/", "credentials_in_url"),
        ("https://example.com:8080/x", "port_not_allowed"),
        ("https://localhost/x", "internal_host"),
        ("https://build.internal/x", "internal_host"),
        ("https://printer.local/x", "internal_host"),
        ("https://metadata.google.internal/x", "internal_host"),
        ("https://example.com/login", "credential_surface"),
        ("https://example.com/user/oauth/authorize", "credential_surface"),
        ("https://example.com/reset-password", "credential_surface"),
        ("https://example.com/driver.exe", "executable_download"),
        ("https://example.com/install.sh", "executable_download"),
        ("https://example.com/app.apk", "executable_download"),
    ],
)
def test_the_blocklist_refuses_with_a_stated_reason(url: str, reason: str) -> None:
    with pytest.raises(ReachDeniedError) as denied:
        policy().assert_url_allowed(url)
    assert denied.value.reason == reason


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.9",
        # The cloud metadata endpoint — the single highest-value SSRF target.
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
    ],
)
def test_a_hostname_resolving_inside_the_network_is_refused(address: str) -> None:
    """The check is on the resolved address, so a public name cannot smuggle
    an internal target through."""
    reach = ReachPolicy(resolver=lambda hostname: [address])

    with pytest.raises(ReachDeniedError) as denied:
        reach.assert_url_allowed("https://totally-legitimate-research.example/")
    assert denied.value.reason == "internal_address"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/x",
        "https://10.1.2.3/x",
    ],
)
def test_ip_literals_pointing_inside_are_refused(url: str) -> None:
    with pytest.raises(ReachDeniedError) as denied:
        policy().assert_url_allowed(url)
    assert denied.value.reason == "internal_address"


def test_one_public_address_among_several_does_not_excuse_an_internal_one() -> None:
    """A split-horizon answer must fail on the internal address, not pass on the
    public one."""
    reach = ReachPolicy(resolver=lambda hostname: [PUBLIC_IP, "127.0.0.1"])

    with pytest.raises(ReachDeniedError) as denied:
        reach.assert_url_allowed("https://example.com/")
    assert denied.value.reason == "internal_address"


def test_a_host_that_does_not_resolve_is_refused_rather_than_attempted() -> None:
    reach = ReachPolicy(resolver=lambda hostname: [])

    with pytest.raises(ReachDeniedError) as denied:
        reach.assert_url_allowed("https://nowhere.example/")
    assert denied.value.reason == "unresolvable_host"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/octet-stream",
        "application/x-msdownload",
        "application/zip",
        "image/png",
        "",
    ],
)
def test_unreadable_content_types_are_refused(content_type: str) -> None:
    with pytest.raises(ReachDeniedError) as denied:
        policy().assert_response_allowed(
            ReachResponse(
                status_code=200,
                content="binary",
                content_type=content_type,
                byte_size=10,
            )
        )
    assert denied.value.reason == "content_type_not_readable"


@pytest.mark.parametrize(
    "content_type",
    ["text/html; charset=utf-8", "text/plain", "application/json", "application/xml"],
)
def test_readable_content_types_pass(content_type: str) -> None:
    policy().assert_response_allowed(
        ReachResponse(status_code=200, content="ok", content_type=content_type, byte_size=2)
    )


def test_oversized_responses_are_refused() -> None:
    reach = policy(max_content_bytes=1024)

    with pytest.raises(ReachDeniedError) as denied:
        reach.assert_response_allowed(
            ReachResponse(
                status_code=200,
                content="x",
                content_type="text/html",
                byte_size=1025,
            )
        )
    assert denied.value.reason == "content_too_large"


def test_the_per_host_budget_stops_a_crawl() -> None:
    reach = policy(per_host_budget=2)

    reach.note_read("example.com")
    reach.note_read("example.com")
    # A different host has its own budget.
    reach.note_read("other.example")

    with pytest.raises(ReachRateLimitedError):
        reach.note_read("example.com")


def test_search_without_a_provider_fails_loudly_rather_than_returning_nothing() -> None:
    """An empty result set means "nothing matched"; a missing provider must not
    be reported the same way, or absence of evidence becomes evidence of absence."""
    from app.ai.reach import ReachSearchService, ReachSearchUnavailableError

    search = ReachSearchService(policy=policy())

    assert search.is_available is False
    with pytest.raises(ReachSearchUnavailableError) as unavailable:
        search.search("锂电池气泵 噪声 标准")
    assert "not an empty result set" in str(unavailable.value)


def test_search_hits_the_policy_would_refuse_are_dropped_before_the_model_sees_them() -> None:
    from app.ai.reach import ReachSearchService, SearchHit

    class StubProvider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str, *, limit: int) -> list[SearchHit]:
            self.queries.append(query)
            return [
                SearchHit("公开规格", "https://example.com/spec", "额定气压 8 bar"),
                SearchHit("登录", "https://example.com/login", "请登录"),
                SearchHit("内网面板", "https://dashboard.internal/", "内部"),
                SearchHit("驱动下载", "https://example.com/driver.exe", "下载"),
            ]

    provider = StubProvider()
    search = ReachSearchService(provider=provider, policy=policy())

    hits = search.search("气泵规格")

    assert search.is_available is True
    assert [hit.url for hit in hits] == ["https://example.com/spec"]
    assert provider.queries == ["气泵规格"]
