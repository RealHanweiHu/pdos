"""Integrity, offline tokenization, and native counting without model qualification."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

import httpx2
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from app.ai.egress import ProviderEgressPolicy
from app.ai.input_metering import (
    AnthropicInputMeter,
    LocalTemplateMeter,
    MeteringError,
    load_published_meters,
)
from app.ai.model_budget import QualifiedModelMeter
from app.ai.model_catalog import AgentTier, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import AnthropicNativeAdapter, ChatMessage
from tests.test_model_budget_controller import evidence
from tests.test_model_gateway import catalog, qualification


class PublicationDocument(TypedDict):
    schema_version: int
    golden_suite_version: str
    golden_suite_digest: str
    models: list[dict[str, object]]


def route() -> ResolvedModelRoute:
    return catalog().resolve_route(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        agent_tier=AgentTier.DEFAULT,
        qualifications=[qualification()],
    )


def asset(root: Path, name: str, body: bytes) -> dict[str, str]:
    (root / name).write_bytes(body)
    return dict(path=name, sha256=sha256(body).hexdigest())


def save(path: Path, document: object) -> str:
    path.write_text(json.dumps(document, ensure_ascii=False))
    return sha256(path.read_bytes()).hexdigest()


def publication(
    root: Path, *, native: bool = False, qualified_input_limit: int = 200, window_tokens: int = 8192
) -> tuple[Path, PublicationDocument, str]:
    tokenizer = Tokenizer(
        WordLevel({"[UNK]": 0, "hello": 1, "system": 2, "user": 3}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.enable_truncation(max_length=2)
    tokenizer.enable_padding(length=8)
    blob = tokenizer.to_str().encode()
    template = (
        b"{% for m in messages %}{{m.role}} {{m.content}} {% endfor %}"
        b"{% if add_generation_prompt %}assistant {% endif %}"
    )
    local = LocalTemplateMeter(blob, template, b"{}")
    now = datetime.now(UTC)
    cases: list[dict[str, object]] = []
    for key, body in [
        ("short_text", "hello"),
        ("unicode", "你好 😊 café"),
        ("structured_schema", 'Return {"risk":"low"}'),
        ("near_input_limit", "hello " * (qualified_input_limit * 4 // 5)),
    ]:
        messages = [ChatMessage(role="user", content=body)]
        count = local.count(route(), messages)
        cases.append(
            dict(
                key=key,
                category=key,
                messages=[m.model_dump() for m in messages],
                counted_input_tokens=count,
                observed_input_tokens=count,
                provider_request_id=f"synthetic-{key}",
                observed_at=(now - timedelta(minutes=1)).isoformat(),
            )
        )
    evidence = dict(schema_version=1, qualification_key="synthetic-meter-v1", cases=cases)
    entry: dict[str, object] = dict(
        key="synthetic-meter-v1",
        provider="minimax",
        model="MiniMax-M2.7",
        protocol="openai-compatible",
        base_url=route().base_url,
        implementation="hf_text_template.v1",
        window_tokens=window_tokens,
        output_token_limit=64,
        max_qualified_input_tokens=qualified_input_limit,
        output_parameter="max_completion_tokens",
        input_margin_tokens=4,
        input_margin_percent=5,
        source_ref="synthetic-source",
        reviewed_by="synthetic-reviewer",
        valid_from=(now - timedelta(seconds=30)).isoformat(),
        valid_until=(now + timedelta(hours=1)).isoformat(),
        tokenizer=asset(root, "tokenizer.json", blob),
        chat_template=asset(root, "chat.jinja", template),
        tokenizer_config=asset(root, "config.json", b"{}"),
        evidence=asset(root, "evidence.json", json.dumps(evidence).encode()),
    )
    if native:
        entry.update(
            provider="anthropic",
            model="claude-test",
            protocol="anthropic-native",
            base_url="https://anthropic.test",
            implementation="anthropic_count_tokens.v1",
            output_parameter="max_tokens",
            tokenizer=None,
            chat_template=None,
            tokenizer_config=None,
        )
    doc: PublicationDocument = dict(
        schema_version=1,
        golden_suite_version="s2-v1",
        golden_suite_digest="sha256:trusted-suite",
        models=[entry],
    )
    path = root / "publication.json"
    return path, doc, save(path, doc)


def load(
    path: Path,
    digest: str,
    client: httpx2.Client,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[tuple[ProviderName, str], QualifiedModelMeter]:
    return load_published_meters(
        path,
        expected_sha256=digest,
        qualifications=[qualification()],
        client=client,
        egress_policy=ProviderEgressPolicy.from_catalog(catalog()),
        clock=clock,
    )


def test_local_counter_counts_full_input_without_padding_or_truncation(tmp_path: Path) -> None:
    path, _, digest = publication(tmp_path)
    with httpx2.Client(
        transport=httpx2.MockTransport(lambda _: pytest.fail("unexpected HTTP"))
    ) as client:
        meter = load(path, digest, client)[(ProviderName.MINIMAX, "MiniMax-M2.7")]
        assert meter.meter.count(route(), [ChatMessage(role="user", content="hello " * 100)]) == 112
        assert meter.qualification_ref == f"meter-publication:sha256:{digest}:synthetic-meter-v1"


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "model",
        "protocol",
        "base_url",
        "expired",
        "not_effective",
        "source",
        "coverage",
        "near_limit",
        "undercount",
        "future_evidence",
        "evidence_key",
        "duplicate_receipt",
        "duplicate",
        "unknown_implementation",
    ],
)
def test_invalid_publication_never_qualifies(tmp_path: Path, change: str) -> None:
    path, doc, digest = publication(tmp_path)
    p = doc["models"][0]
    if change == "digest":
        digest = "0" * 64
    elif change in {"model", "protocol", "base_url", "source", "unknown_implementation"}:
        field = {"source": "source_ref", "unknown_implementation": "implementation"}.get(
            change, change
        )
        p[field] = {
            "model": "other-model",
            "protocol": "anthropic-native",
            "base_url": "https://user:pass@meter.test",
            "source": " ",
            "unknown_implementation": "execute_remote_python",
        }[change]
    elif change == "expired":
        p["valid_until"] = p["valid_from"]
    elif change == "not_effective":
        p["valid_from"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    elif change == "duplicate":
        doc["models"].append(dict(p))
    else:
        evidence = json.loads((tmp_path / "evidence.json").read_text())
        if change == "coverage":
            evidence["cases"].pop()
        if change == "near_limit":
            p["max_qualified_input_tokens"] = 500
        if change == "undercount":
            evidence["cases"][0]["observed_input_tokens"] = 100
        if change == "future_evidence":
            evidence["cases"][0]["observed_at"] = p["valid_until"]
        if change == "evidence_key":
            evidence["qualification_key"] = "different"
        if change == "duplicate_receipt":
            evidence["cases"][1]["provider_request_id"] = evidence["cases"][0][
                "provider_request_id"
            ]
        p["evidence"] = asset(tmp_path, "evidence.json", json.dumps(evidence).encode())
    if change != "digest":
        digest = save(path, doc)
    with httpx2.Client() as client, pytest.raises(MeteringError):
        load(path, digest, client)


@pytest.mark.parametrize("field", ["tokenizer", "chat_template", "tokenizer_config", "evidence"])
def test_asset_integrity_and_path_escape(tmp_path: Path, field: str) -> None:
    path, doc, digest = publication(tmp_path)
    asset_ref = doc["models"][0][field]
    assert isinstance(asset_ref, dict)
    asset_path = asset_ref["path"]
    assert isinstance(asset_path, str)
    (tmp_path / asset_path).write_bytes(b"changed")
    with httpx2.Client() as client, pytest.raises(MeteringError):
        load(path, digest, client)
    asset_ref["path"] = "../outside"
    with httpx2.Client() as client, pytest.raises(MeteringError):
        load(path, save(path, doc), client)


def test_each_count_checks_document_expiry_route_and_coverage(tmp_path: Path) -> None:
    path, _, digest = publication(tmp_path)
    current = datetime.now(UTC)
    with httpx2.Client() as client:
        meter = load(path, digest, client, clock=lambda: current)[
            (ProviderName.MINIMAX, "MiniMax-M2.7")
        ].meter
        messages = [ChatMessage(role="user", content="hello")]
        for changed in [
            replace(route(), base_url="https://other.test"),
            replace(route(), model="wrong"),
            replace(route(), provider=ProviderName.OPENAI),
        ]:
            with pytest.raises(MeteringError):
                meter.count(changed, messages)
        with pytest.raises(MeteringError):
            meter.count(route(), [ChatMessage(role="user", content="hello " * 300)])
        current += timedelta(days=1)
        with pytest.raises(MeteringError):
            meter.count(route(), messages)
        current -= timedelta(days=1)
        path.write_text("{}")
        with pytest.raises(MeteringError):
            meter.count(route(), messages)


def test_local_samples_must_be_reproducible(tmp_path: Path) -> None:
    path, doc, _ = publication(tmp_path)
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    evidence["cases"][0]["counted_input_tokens"] += 1
    doc["models"][0]["evidence"] = asset(tmp_path, "evidence.json", json.dumps(evidence).encode())
    with httpx2.Client() as client, pytest.raises(MeteringError):
        load(path, save(path, doc), client)


def native_route() -> ResolvedModelRoute:
    return replace(
        route(),
        provider=ProviderName.ANTHROPIC,
        protocol=ProtocolKind.ANTHROPIC_NATIVE,
        base_url="https://anthropic.test",
        model="claude-test",
    )


def test_native_counter_and_generation_share_exact_input() -> None:
    native = native_route()
    requests: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(
            (request.url.path, evidence(json.loads(request.content)), dict(request.headers))
        )
        return httpx2.Response(
            200,
            json={"input_tokens": 12}
            if "count_tokens" in request.url.path
            else {
                "id": "synthetic",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 12, "output_tokens": 1},
            },
        )

    messages = [
        ChatMessage(role="system", content="first"),
        ChatMessage(role="system", content="second"),
        ChatMessage(role="user", content="你好"),
    ]
    policy = ProviderEgressPolicy.from_routes([native])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        assert AnthropicInputMeter(client, policy).count(native, messages) == 12
        AnthropicNativeAdapter(client, policy).complete(native, messages)
    assert requests[0][0] == "/v1/messages/count_tokens"
    assert requests[0][1] == {
        k: v for k, v in requests[1][1].items() if k not in {"max_tokens", "temperature"}
    }
    assert requests[0][1]["system"] == "first\n\nsecond"
    assert requests[0][2]["anthropic-version"] == "2023-06-01"


@pytest.mark.parametrize(
    "answer",
    [
        True,
        -1,
        "12",
        None,
        {},
        httpx2.Response(302, headers={"location": "https://evil.test"}),
        httpx2.Response(429),
        httpx2.ReadTimeout("synthetic"),
    ],
)
def test_native_errors_never_retry_or_follow_redirect(answer: object) -> None:
    native = native_route()
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if isinstance(answer, Exception):
            raise answer
        return (
            answer
            if isinstance(answer, httpx2.Response)
            else httpx2.Response(200, json={"input_tokens": answer})
        )

    with (
        httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(MeteringError),
    ):
        AnthropicInputMeter(client, ProviderEgressPolicy.from_routes([native])).count(
            native, [ChatMessage(role="user", content="test")]
        )
    assert len(calls) == 1


def test_native_publication_load_is_offline_and_requires_golden_pass(tmp_path: Path) -> None:
    path, _, digest = publication(tmp_path, native=True)
    q = qualification().model_copy(
        update={"provider": ProviderName.ANTHROPIC, "model": "claude-test"}
    )
    with httpx2.Client(
        transport=httpx2.MockTransport(lambda _: pytest.fail("load sent HTTP"))
    ) as client:
        assert (
            len(
                load_published_meters(
                    path,
                    expected_sha256=digest,
                    qualifications=[q],
                    client=client,
                    egress_policy=ProviderEgressPolicy.from_routes([native_route()]),
                )
            )
            == 1
        )
        with pytest.raises(MeteringError):
            load_published_meters(
                path,
                expected_sha256=digest,
                qualifications=[q.model_copy(update={"status": "failed"})],
                client=client,
                egress_policy=ProviderEgressPolicy.from_routes([native_route()]),
            )


def test_pinned_template_cannot_access_python_internals(tmp_path: Path) -> None:
    path, doc, _ = publication(tmp_path)
    doc["models"][0]["chat_template"] = asset(
        tmp_path, "chat.jinja", b"{{ messages[0].__class__.__mro__ }}"
    )
    with httpx2.Client() as client, pytest.raises(MeteringError):
        load(path, save(path, doc), client)


def test_counter_rechecks_qualification_after_native_count(tmp_path: Path) -> None:
    path, doc, digest = publication(tmp_path, native=True)
    q = qualification().model_copy(
        update={"provider": ProviderName.ANTHROPIC, "model": "claude-test"}
    )

    def handler(_: httpx2.Request) -> httpx2.Response:
        path.write_text("{}")
        return httpx2.Response(200, json={"input_tokens": 12})

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        meters = load_published_meters(
            path,
            expected_sha256=digest,
            qualifications=[q],
            client=client,
            egress_policy=ProviderEgressPolicy.from_routes([native_route()]),
        )
        with pytest.raises(MeteringError):
            meters[(ProviderName.ANTHROPIC, "claude-test")].meter.count(
                native_route(), [ChatMessage(role="user", content="Synthetic text")]
            )
