"""evidence.extract dispatch over actual isolated data; synthetic provider, zero real egress."""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked database fixtures

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import SkillBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.extract_adapter import ExtractReadAdapter
from pdos_next.agent_kernel.extract_graph import ExtractGraph
from pdos_next.agent_kernel.extract_service import ExtractionService
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentToolCall,
    TenantAdministrator,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE, actual_run, proposal, uploaded
from tests.preproject.test_g0 import create
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work

PROVIDER = "synthetic-extract-dispatch-no-real-egress"


def proposal_two(work, first, second):
    identity, _ = create(
        work,
        {
            "title": "Synthetic two-original proposal",
            "entry_kind": "customer_request",
            "source_refs": [
                {"type": "original", "id": str(first), "version": 1, "line": 1, "quote": QUOTE},
                {"type": "original", "id": str(second), "version": 1, "line": 1, "quote": QUOTE},
            ],
        },
    )
    return UUID(identity)


def proposal_quote(work, version_id, quote):
    identity, _ = create(
        work,
        {
            "title": "Synthetic original-bound proposal",
            "entry_kind": "customer_request",
            "source_refs": [
                {"type": "original", "id": str(version_id), "version": 1, "line": 1,
                 "quote": quote},
            ],
        },
    )
    return UUID(identity)


def fixture(
    work, security_work, *, rows_factory, extra_upload=False, skill_event=True,
    extract_arguments=None, uploader=None, mount_quote=None,
):
    owner = Bootstrap(work.engine)
    root_id, version_id = (uploader or uploaded)(work, security_work)
    second_version = None
    if extra_upload:
        _, second_version = uploaded(work, security_work, label="second synthetic original")
        proposal_id = proposal_two(work, version_id, second_version)
    elif mount_quote is not None:
        proposal_id = proposal_quote(work, version_id, mount_quote)
    else:
        proposal_id = proposal(work, version_id)
    scope, bound_sources = actual_run(work, owner, proposal_id)
    extract_args = {
        "row_schema": {"kind": "rfq_requirement", "version": "1"},
        "proposal_id": str(scope.proposal_id),
        **(extract_arguments or {}),
    }
    route = configured_route()
    with Session(work.admin) as session, session.begin():
        # Synthetic budget headroom for the full frozen main-loop tool prefix;
        # budget behaviour itself is not under test here.
        row = session.get(AgentRun, scope.run_id)
        row.token_limit = 2_000_000
    with Session(work.admin) as session, session.begin():
        if session.scalar(
            select(TenantAdministrator).where(
                TenantAdministrator.tenant_id == work.tenant,
                TenantAdministrator.principal_id == work.human,
            )
        ) is None:
            session.add(TenantAdministrator(tenant_id=work.tenant, principal_id=work.human))
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        from pdos_next.agent_kernel.models import ProviderDataAgreement

        if (
            session.scalar(
                select(ProviderDataAgreement).where(
                    ProviderDataAgreement.tenant_id == work.tenant,
                    ProviderDataAgreement.provider == PROVIDER,
                    ProviderDataAgreement.active.is_(True),
                )
            )
            is None
        ):
            register_agreement(
                session,
                work.ctx,
                AgreementInput(
                    provider=PROVIDER,
                    expected_revision=0,
                    data_categories=list(scope.data_categories),
                    decision="批准",
                    idempotency_key=str(uuid4()),
                    retention_terms="synthetic fixture only",
                    training_terms="synthetic fixture only",
                    signed_on=now() - timedelta(minutes=1),
                    expires_at=now() + timedelta(hours=1),
                ),
            )
    skill = owner.catalog._skills["rfq_extraction"]
    with Session(work.admin) as session, session.begin():
        if (
            session.scalar(
                select(TenantSkillEnablement).where(
                    TenantSkillEnablement.tenant_id == work.tenant,
                    TenantSkillEnablement.skill_key == skill.key,
                )
            )
            is None
        ):
            session.add(
                TenantSkillEnablement(
                    tenant_id=work.tenant,
                    skill_key=skill.key,
                    enabled=True,
                    pilot=True,
                    qualification_revoked=False,
                    qualified_skill_version=skill.version,
                    qualified_model_version=route.version,
                    qualified_skill_digest=skill.digest,
                    qualified_tool_digest=tool_identity(skill, owner.registry),
                    qualified_model_digest=model_identity(route),
                    reviewed_by=work.human,
                    reviewed_at=now(),
                    review_case_refs=[f"synthetic-reviewed-case-{index}" for index in range(10)],
                )
            )
        load_event_id = uuid4()
        if skill_event:
            sequence = (
                session.scalar(
                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                        AgentEvent.run_id == scope.run_id
                    )
                )
                or 0
            ) + 1
            session.add(
                AgentEvent(
                    id=load_event_id,
                    tenant_id=work.tenant,
                    run_id=scope.run_id,
                    sequence=sequence,
                    body={
                        "type": "skill_loaded",
                        "key": skill.key,
                        "version": skill.version,
                        "digest": skill.digest,
                        "isolation": "main",
                    },
                )
            )

    calls = []

    def callback(kwargs):
        tools = {tool["name"] for tool in kwargs["tools"]}
        if tools == {"evidence.artifact.read"}:
            messages = kwargs["messages"]
            task_context = json.loads(messages[0]["content"])["context"]["extraction_task"]
            artifact_id = task_context["artifact_version_id"]
            if any(message.get("role") == "tool" for message in messages):
                page = json.loads(messages[-1]["content"])
                text = page["blocks"][0]["text"].strip()
                calls.append(("child-answer", artifact_id))
                return ModelTurn(
                    structured={
                        "status": "completed",
                        "summary": "合成抽取",
                        "result": {"rows": [rows_factory(artifact_id, text)]},
                        "questions": [],
                        "unfinished": [],
                    },
                    usage=ProviderUsage(5, 3),
                )
            calls.append(("child-read", artifact_id))
            return ModelTurn(
                calls=(
                    ToolCall(
                        id="child-read-1",
                        name="evidence.artifact.read",
                        arguments={
                            "artifact_version_id": artifact_id,
                            "cursor": 0,
                            "page_size": 200,
                        },
                    ),
                ),
                usage=ProviderUsage(10, 2),
            )
        calls.append(("main", None))
        return ModelTurn(text="synthetic main turn", usage=ProviderUsage(10, 2))

    client = Client(callback)
    reads = DomainReads(owner.store, owner.commands)
    adapters = KernelAdapters(
        route_for=lambda _: route,
        project_context=owner.project_context,
        verify_result=lambda *values: values[1],
        prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None,
        provider_for=lambda *_: PROVIDER,
        provider_client=client,
        cost_required=False,
        tool_registry=owner.registry,
        read_tools=reads.handlers(),
    )
    host = BoundHost(owner.store, adapters)
    adapter = ExtractReadAdapter(
        ExtractionService(owner.store, owner.commands, owner.catalog),
        ExtractGraph(host, artifact_read=adapters.read_tools["evidence.artifact.read"]),
    )
    adapters.read_tools.update(adapter.handlers())
    adapters.read_restores.update(adapter.restores())
    calls.append(("main", None))

    def main_callback(kwargs):
        return ModelTurn(
            calls=(
                ToolCall(id="extract-1", name="evidence.extract", arguments=extract_args),
            ),
            usage=ProviderUsage(10, 2),
        )

    client.callback = main_callback
    bindings = (SkillBinding(key=skill.key, version=skill.version, digest=skill.digest,
                             load_event_id=load_event_id),) if skill_event else ()
    context = host.skill_context(scope, "Synthetic extraction", bindings=bindings)
    with registered_graph_context("xiaopai"):
        turn = host.model(
            scope,
            system="frozen synthetic main prefix",
            messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            tools=owner.registry.definitions(),
            output_schema={"type": "object"},
            loaded_skills=bindings,
        )
    client.callback = callback
    assert turn.ledger_call_id is not None
    source = ReadSource(model_call_id=turn.ledger_call_id, response_index=0)
    return owner, scope, host, client, calls, source, version_id, second_version, extract_args


def extract(host, scope, source, arguments):
    return host.read(
        scope,
        host.adapters.tool_registry.get("evidence.extract"),
        arguments,
        execution_key(scope.run_id, source.model_call_id, source.response_index),
        source=source,
    )


def quote_row(artifact_id, text):
    return {
        "artifact_version_id": artifact_id,
        "locator": "line:1",
        "quote": text,
        "kind": "compliance",
        "statement": "合成合规要求",
        "missing": [],
    }


def test_extract_dispatch_full_chain_and_exact_replay(work, security_work):
    owner, scope, host, client, calls, source, version_id, _, args = fixture(
        work, security_work, rows_factory=quote_row
    )
    result = extract(host, scope, source, args)
    assert result["row_schema"] == {"kind": "rfq_requirement", "version": "1"}
    assert (
        result["skill"]["key"] == "rfq_extraction"
        and result["skill"]["version"] == owner.catalog._skills["rfq_extraction"].version
    )
    assert result["proposal_id"] == str(scope.proposal_id)
    assert result["failures"] == [] and result["rejected"] == []
    assert [row["quote"] for row in result["rows"]] == [QUOTE]
    assert result["rows"][0]["artifact_id"] == str(version_id)
    assert result["rows"][0]["read_call_ids"]
    coverage = result["coverage"][0]
    assert coverage["artifact_id"] == str(version_id)
    assert coverage["parsed_text"]["read_ranges"] == [[1, 1]]
    assert coverage["parsed_text"]["fully_read"] is True
    assert [kind for kind, _ in calls] == ["main", "child-read", "child-answer"]
    with owner.store.transaction(scope) as (session, _):
        call = session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"]))
        assert call.state == "completed" and call.tool == "evidence.extract"
        assert call.execution_binding["isolation"] == "main"
        child_reads = session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id,
                AgentToolCall.tool == "evidence.artifact.read",
            )
        ).all()
        assert len(child_reads) == 1 and child_reads[0].state == "completed"
        assert child_reads[0].execution_binding["isolation"] == "extract"
    replay = extract(host, scope, source, args)
    assert replay == result
    assert [kind for kind, _ in calls] == ["main", "child-read", "child-answer"]


def test_extract_fans_out_over_all_mounted_originals(work, security_work):
    owner, scope, host, client, calls, source, version_id, second, args = fixture(
        work, security_work, rows_factory=quote_row, extra_upload=True
    )
    assert second is not None
    result = extract(host, scope, source, args)
    assert result["failures"] == []
    assert {row["artifact_id"] for row in result["rows"]} == {str(version_id), str(second)}
    assert {entry["artifact_id"] for entry in result["coverage"]} == {str(version_id), str(second)}
    assert all(entry["parsed_text"]["fully_read"] for entry in result["coverage"])
    assert sorted(kind for kind, _ in calls) == [
        "child-answer",
        "child-answer",
        "child-read",
        "child-read",
        "main",
    ]
    subset_args = {**args, "artifact_version_ids": [str(version_id)]}
    owner, scope, host, client, calls, source, _, _, subset_args = fixture(
        work, security_work, rows_factory=quote_row, extra_upload=True,
        extract_arguments={"artifact_version_ids": [str(version_id)]},
    )
    subset = extract(host, scope, source, subset_args)
    assert {row["artifact_id"] for row in subset["rows"]} == {str(version_id)}
    assert {entry["artifact_id"] for entry in subset["coverage"]} == {str(version_id)}


def test_extract_requires_declared_loaded_skill_and_bound_sources(work, security_work):
    owner, scope, host, client, calls, source, version_id, _, args = fixture(
        work, security_work, rows_factory=quote_row, skill_event=False
    )
    with pytest.raises(DomainError) as missing:
        extract(host, scope, source, args)
    assert missing.value.code == "FORBIDDEN_SCOPE"
    assert missing.value.detail["reason_key"] == "row_schema_not_declared"
    assert [kind for kind, _ in calls] == ["main"]

    owner, scope, host, client, calls, source, version_id, _, voice_args = fixture(
        work, security_work, rows_factory=quote_row,
        extract_arguments={"row_schema": {"kind": "user_voice", "version": "1"}},
    )
    with pytest.raises(DomainError) as undeclared:
        extract(host, scope, source, voice_args)
    assert undeclared.value.code == "FORBIDDEN_SCOPE"
    assert [kind for kind, _ in calls] == ["main"]

    owner, scope, host, client, calls, source, version_id, _, unbound_args = fixture(
        work, security_work, rows_factory=quote_row,
        extract_arguments={"artifact_version_ids": [str(uuid4())]},
    )
    with pytest.raises(DomainError) as unbound:
        extract(host, scope, source, unbound_args)
    assert unbound.value.code == "FORBIDDEN_SCOPE"
    assert [kind for kind, _ in calls] == ["main"]


def test_extract_rows_require_actual_reads(work, security_work):
    def no_read_row(artifact_id, _text):
        return {
            "artifact_version_id": artifact_id,
            "locator": "line:1",
            "quote": QUOTE,
            "kind": "compliance",
            "statement": "未读原件的编造行",
            "missing": [],
        }

    owner, scope, host, client, calls, source, version_id, _, args = fixture(
        work, security_work, rows_factory=no_read_row
    )

    def skipping(kwargs):
        tools = {tool["name"] for tool in kwargs["tools"]}
        if tools == {"evidence.artifact.read"}:
            calls.append(("child-skip", None))
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "跳过读取",
                    "result": {"rows": [no_read_row(str(version_id), "")]},
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(5, 3),
            )
        calls.append(("main-child-orphan", None))
        return ModelTurn(text="synthetic main turn", usage=ProviderUsage(10, 2))

    client.callback = skipping
    result = extract(host, scope, source, args)
    assert result["rows"] == []
    assert result["rejected"][0]["code"] == "source_location_not_read"
    assert result["coverage"][0]["parsed_text"]["read_ranges"] == []


def test_extract_replay_refused_after_run_cancellation(work, security_work):
    owner, scope, host, client, calls, source, version_id, _, args = fixture(
        work, security_work, rows_factory=quote_row
    )
    result = extract(host, scope, source, args)
    assert result["rows"]
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        cancel_run(session, work.ctx, scope.run_id)
    with pytest.raises(DomainError) as cancelled:
        extract(host, scope, source, args)
    assert cancelled.value.code == "CANCELLED_RUN"
    assert [kind for kind, _ in calls] == ["main", "child-read", "child-answer"]
