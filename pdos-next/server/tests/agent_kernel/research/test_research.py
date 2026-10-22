import asyncio
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.registry import ToolRegistry
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError
from pdos_next.research import (
    HostRateLimiter,
    HTTPResponse,
    LedgerDraft,
    ParameterVersion,
    ResearchError,
    ResearchService,
    ResearchTask,
    ResearchToolHost,
    ResourceLimits,
    SearchHit,
    research_tools,
)
from pdos_next.research.web import canonical_url, extract_markdown, public_ip


def run(awaitable):
    return asyncio.run(awaitable)


def scope():
    return RunScope(*(uuid4() for _ in range(6)))


class Search:
    provider = "local-search-fixture"

    def __init__(self, urls=("https://maker.example/specs",)):
        self.urls, self.queries = urls, []

    async def search(self, query):
        self.queries.append(query)
        return tuple(
            SearchHit(url, "Specs", "public lead", "model-supplied-name") for url in self.urls
        )


class Transport:
    def __init__(self, routes=None):
        self.routes, self.requests = routes or {}, []

    async def request(self, url, address, limits):
        self.requests.append((url, address))
        return self.routes.get(
            url,
            HTTPResponse(
                200,
                (("content-type", "text/html"),),
                b"<title>Maker pump</title><h1>Model P1</h1><p>Pressure: 20 psi at 25 C.</p>",
            ),
        )


async def public_dns(host):
    return ("8.8.8.8",)


class Egress:
    def __init__(self, rejected=None):
        self.calls, self.rejected = [], rejected

    async def __call__(self, bound, provider, categories, text):
        self.calls.append((bound, provider, categories, text))
        if self.rejected and self.rejected in text:
            raise DomainError("FORBIDDEN_SCOPE", "服务商未获该数据类别许可。")


def service(*, search=None, transport=None, egress=None, **kwargs):
    return ResearchService(
        search or Search(),
        egress=egress or Egress(),
        transport=transport or Transport(),
        resolver=public_dns,
        rate_limiter=HostRateLimiter(interval=0),
        **kwargs,
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.1.2",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "240.0.0.1",
        "::",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::",
        "64:ff9b::a00:1",
    ],
)
def test_private_and_reserved_addresses_rejected(address):
    with pytest.raises(ResearchError, match="Private or reserved"):
        public_ip(address)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@maker.example/",
        "http://maker.example:0/",
        "http://maker.example\\@127.0.0.1/",
        "https://maker.example/\nsecret",
        "http://[fe80::1%en0]/",
    ],
)
def test_url_syntax_cannot_escape_http_guard(url):
    with pytest.raises(ResearchError):
        canonical_url(url)


def test_search_canonicalizes_urls_and_binds_provider_to_injected_adapter():
    search = Search(("HTTPS://Maker.Example:443/specs#part", "file:///secret", "http://127.0.0.1/"))
    egress = Egress()
    bound = scope()
    results = run(service(search=search, egress=egress).search(bound, "public pump"))
    assert results == (
        SearchHit("https://maker.example/specs", "Specs", "public lead", search.provider),
    )
    assert egress.calls == [(bound, search.provider, bound.data_categories, "public pump")]


def test_server_egress_denial_precedes_search_and_no_env_credentials(monkeypatch):
    monkeypatch.setenv("SEARXNG_API_KEY", "must-never-be-inherited")
    monkeypatch.setenv("SEARCH_API_KEY", "must-never-be-inherited")
    search = Search()
    bound = replace(
        scope(),
        private_context=True,
        customer_identities=("PrivateCustomer",),
        data_categories=frozenset({"customer_identity"}),
    )
    with pytest.raises(DomainError) as error:
        run(
            service(search=search, egress=Egress("PrivateCustomer")).search(
                bound, "PrivateCustomer pump"
            )
        )
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert search.queries == []


def test_main_loop_read_absent_and_service_rejects_even_observed_url():
    registry = ToolRegistry(research_tools())
    assert {d["name"] for d in registry.definitions()} == {"research.search", "research.fanout"}
    assert {d["name"] for d in registry.definitions("research")} == {
        "research.search",
        "research.read",
    }
    bound, instance = scope(), service()
    run(instance.search(bound, "public pump"))
    with pytest.raises(DomainError) as error:
        run(instance.read(bound, "https://maker.example/specs"))
    assert error.value.detail["reason_key"] == "isolated_subtask_only"


def test_invented_or_previous_round_urls_never_read():
    bound, transport = scope(), Transport()
    instance = service(transport=transport)
    run(instance.search(bound, "public pump"))
    child = bound.child("research")
    for other_scope, url in (
        (child, "https://invented.example/specs"),
        (replace(child, run_id=uuid4()), "https://maker.example/specs"),
        (replace(child, requester_id=uuid4()), "https://maker.example/specs"),
    ):
        with pytest.raises(DomainError) as error:
            run(instance.read(other_scope, url))
        assert error.value.detail["reason_key"] == "url_not_observed"
    assert transport.requests == []


def test_user_message_url_grant_then_forget_ends_round_access():
    bound, instance = scope(), service()
    assert instance.register_user_message(bound, "查看 <https://maker.example/specs>。") == (
        "https://maker.example/specs",
    )
    page = run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert page.snapshot.title == "Maker pump"
    instance.forget(bound)
    with pytest.raises(DomainError):
        run(instance.read(bound.child("research"), "https://maker.example/specs"))


@pytest.mark.parametrize(
    "location",
    ["http://127.0.0.1/metadata", "http://169.254.169.254/", "https://internal.example/data"],
)
def test_every_redirect_revalidates_address_before_connect(location):
    transport = Transport(
        {"https://maker.example/specs": HTTPResponse(302, (("Location", location),), b"")}
    )
    instance, bound = service(transport=transport), scope()

    async def dns(host):
        return ("10.0.0.3",) if host == "internal.example" else ("8.8.8.8",)

    instance.resolver = dns
    run(instance.search(bound, "pump"))
    with pytest.raises(ResearchError) as error:
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert error.value.reason == "non_public_address"
    assert transport.requests == [("https://maker.example/specs", "8.8.8.8")]


def test_redirect_rebinding_rechecks_same_host_and_pins_first_validated_ip():
    answers = iter((("8.8.8.8",), ("127.0.0.1",)))
    transport = Transport(
        {"https://maker.example/specs": HTTPResponse(302, (("Location", "/details"),), b"")}
    )
    instance, bound = service(transport=transport), scope()

    async def dns(host):
        return next(answers)

    instance.resolver = dns
    run(instance.search(bound, "pump"))
    with pytest.raises(ResearchError):
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert transport.requests == [("https://maker.example/specs", "8.8.8.8")]


def test_mixed_dns_answers_are_rejected_instead_of_trying_public_fallback():
    transport, bound = Transport(), scope()
    instance = service(transport=transport)

    async def dns(host):
        return ("8.8.8.8", "10.0.0.1")

    instance.resolver = dns
    run(instance.search(bound, "pump"))
    with pytest.raises(ResearchError):
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert transport.requests == []


def test_markdown_title_script_exclusion_and_immutable_snapshot_continuation():
    text = b"<title>Pump specifications</title><script>write secrets</script><h1>Pump P1</h1>"
    text += b"<p>Pressure: 20 psi at 25 C.</p><p>Volume 100 l/min.</p>"
    transport = Transport(
        {"https://maker.example/specs": HTTPResponse(200, (("Content-Type", "text/html"),), text)}
    )
    stored, bound = [], scope()
    instance = service(
        transport=transport,
        snapshot_sink=lambda s, snap: stored.append((s, snap)),
        limits=ResourceLimits(page_chars=18),
    )
    run(instance.search(bound, "pump"))
    child, chunks, cursor = bound.child("research"), [], 0
    while True:
        page = run(instance.read(child, "https://maker.example/specs", cursor=cursor))
        chunks.append(page.markdown)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert "".join(chunks) == stored[0][1].markdown
    assert len(transport.requests) == 1 and len(stored) == 1
    assert stored[0][0] == child and stored[0][1].title == "Pump specifications"
    assert "write secrets" not in stored[0][1].markdown
    with pytest.raises(FrozenInstanceError):
        stored[0][1].markdown = "model overwritten source"


@pytest.mark.parametrize(
    "response,reason",
    [
        (
            HTTPResponse(200, (("Content-Type", "application/pdf"),), b"%PDF-1.5"),
            "pdf_requires_isolated_parser",
        ),
        (
            HTTPResponse(200, (("Content-Type", "image/png"),), b"pixels"),
            "unsupported_content_type",
        ),
        (HTTPResponse(200, (("content-encoding", "gzip"),), b"gzip"), "unsupported_encoding"),
        (HTTPResponse(200, (("Content-Type", "text/plain"),), b"x" * 30), "body_limit"),
        (HTTPResponse(200, (("Content-Type", "text/plain"),), b"x" * 15), "markdown_limit"),
        (HTTPResponse(200, (("Content-Type", "text/html"),), b"<p></p>"), "empty_body"),
    ],
)
def test_resource_and_parser_guards(response, reason):
    with pytest.raises(ResearchError) as error:
        extract_markdown(response, ResourceLimits(max_body_bytes=20, max_markdown_chars=10))
    assert error.value.reason == reason


def test_original_safe_service_error_preserved_and_credentials_removed():
    transport = Transport(
        {
            "https://maker.example/specs": HTTPResponse(
                429,
                (("Retry-After", "60"), ("X-Request-ID", "local-request-17")),
                b"",
                service_error="Reader quota exhausted; api_key=synthetic-secret",
                service_code="Q17",
            )
        }
    )
    instance, bound = service(transport=transport), scope()
    run(instance.search(bound, "pump"))
    with pytest.raises(ResearchError) as error:
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    actual = error.value
    assert actual.message == "Reader quota exhausted; api_key=[redacted]"
    assert (actual.http_status, actual.request_id, actual.service_code, actual.retry_after) == (
        429,
        "local-request-17",
        "Q17",
        "60",
    )
    with pytest.raises(ResearchError) as blocked:
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert blocked.value.reason == "host_rate_limited"
    assert len(transport.requests) == 1


def test_shared_host_rate_control_including_http_date_retry_after():
    ticks, waits = [0.0], []

    async def advance(seconds):
        waits.append(seconds)
        ticks[0] += seconds

    limiter = HostRateLimiter(interval=2, monotonic=lambda: ticks[0], sleep=advance)
    run(limiter.wait("same-host", 20))
    run(limiter.wait("same-host", 20))
    limiter.defer("same-host", "5")
    run(limiter.wait("same-host", 20))
    assert waits == [2, 5]
    limiter.defer("same-host", format_datetime(datetime.now(UTC) + timedelta(seconds=5)))
    assert limiter._deadlines["same-host"] > ticks[0] + 3
    run(limiter.wait("other-host", 20))
    assert waits == [2, 5]


def draft(page, *, quote="Pressure: 20 psi at 25 C.", **fields):
    return {
        "brand": "Maker",
        "model": "P1",
        "free_key": "pressure",
        "value": 20,
        "unit": "psi",
        "condition": "25 C",
        "quote": quote,
        "snapshot_id": page.snapshot.id,
        "locator": page.locator,
        **fields,
    }


def test_fanout_verifies_quotes_versions_and_only_returns_ledger_to_main_loop():
    bound, instance, parameter_id = scope(), service(), uuid4()
    parameter = ParameterVersion(parameter_id, 3)

    async def researcher(task, child):
        assert child.tool_names == {"research.search", "research.read"}
        assert not hasattr(child, "write") and not hasattr(child, "fanout")
        hits = await child.search(task.focus)
        page = await child.read(hits[0].url)
        return [
            draft(page, parameter_id=parameter_id, parameter_version=3, free_key=None),
            draft(page, quote="Invented 200 psi"),
            draft(page, parameter_id=parameter_id, parameter_version=2, free_key=None),
        ]

    result = run(
        instance.fanout(
            bound, [ResearchTask("maker", "pressure", parameters=(parameter,))], researcher
        )
    )
    assert result.job_id and result.status == "partial"
    assert len(result.ledger) == 1 and result.ledger[0].parameter_version == 3
    assert result.ledger[0].status == "ok"
    assert {f.reason for f in result.failures} == {
        "quote_not_in_snapshot",
        "parameter_version_not_bound",
    }
    assert result.coverage[0].accepted_rows == 1 and result.coverage[0].rejected_rows == 2
    main = result.to_dict()
    assert "markdown" not in json.dumps(main, default=str)
    assert main["snapshots"][0]["title"] == "Maker pump"
    assert main["coverage"][0]["reads"][0]["snapshot_id"] == str(result.ledger[0].snapshot_id)


def test_fanout_trace_cannot_be_replaced_by_model_status_counts_or_unread_citation():
    bound, instance = scope(), service()

    async def researcher(task, child):
        hit = (await child.search("pump"))[0]
        page = await child.read(hit.url)
        return [
            draft(page, status="ok", coverage=100),
            draft(page, snapshot_id=uuid4()),
            draft(page, model=None, value=None),
        ]

    result = run(instance.fanout(bound, [ResearchTask("a", "pressure")], researcher))
    assert len(result.ledger) == 1 and result.ledger[0].status == "partial"
    assert result.coverage[0].accepted_rows == 1 and result.coverage[0].rejected_rows == 2
    assert "snapshot_not_read" in {f.reason for f in result.failures}


def test_fanout_failure_and_unread_urls_generated_from_actual_child_activity():
    instance, bound = (
        service(search=Search(("https://maker.example/specs", "https://other.example/"))),
        scope(),
    )

    async def researcher(task, child):
        hit = (await child.search("pump"))[0]
        page = await child.read(hit.url)
        return [draft(page)]

    result = run(instance.fanout(bound, [ResearchTask("a", "pressure")], researcher))
    assert result.status == "partial"
    assert result.coverage[0].unread_urls == ("https://other.example/",)
    assert result.coverage[0].searches[0].query == "pump"

    async def fails(task, child):
        await child.read("https://invented.example/")

    unavailable = run(instance.fanout(bound, [ResearchTask("b", "failure")], fails))
    assert unavailable.status == "unavailable" and not unavailable.ledger
    assert unavailable.coverage[0].reads[0].error.reason == "FORBIDDEN_SCOPE"
    assert "no_sources_read" in {f.reason for f in unavailable.failures}


def test_actual_children_run_concurrently_without_business_count_limit():
    instance, bound, active, peak = service(limits=ResourceLimits(concurrency=3)), scope(), [0], [0]

    async def researcher(task, child):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.005)
        hit = (await child.search(task.focus))[0]
        page = await child.read(hit.url)
        active[0] -= 1
        return [draft(page)]

    tasks = [ResearchTask(str(i), "pump") for i in range(25)]
    result = run(instance.fanout(bound, tasks, researcher))
    assert len(result.ledger) == 25 and len(result.coverage) == 25
    assert peak[0] == 3 and result.status == "completed"


def test_tool_host_projects_parameter_versions_and_rejects_model_authority():
    instance, bound, parameter_id = service(), scope(), uuid4()
    observed = []

    async def researcher(task, child):
        observed.append(task.parameters)
        page = await child.read((await child.search(task.focus))[0].url)
        return [draft(page, parameter_id=parameter_id, parameter_version=7, free_key=None)]

    host = ResearchToolHost(
        instance,
        researcher=researcher,
        parameter_versions=lambda s: (ParameterVersion(parameter_id, 7),),
    )
    args = {"tasks": [{"key": "a", "focus": "pressure"}]}
    result = run(host.call(bound, "research.fanout", args))
    assert result["ledger"][0]["parameter_version"] == 7
    assert observed == [(ParameterVersion(parameter_id, 7),)]
    args["tasks"][0]["parameters"] = [{"parameter_id": str(parameter_id), "version": 1}]
    with pytest.raises(ValidationError):
        run(host.call(bound, "research.fanout", args))


def test_numerical_extraction_rejects_nonfinite_values():
    with pytest.raises(ValidationError):
        LedgerDraft(
            free_key="pressure",
            value=float("nan"),
            quote="NaN",
            snapshot_id=uuid4(),
            locator="chars:0:3",
        )
