"""Real category Run + product source + T0/T1 owners; synthetic model/qualification only."""
# ruff: noqa: F811 -- explicitly imported marked PG fixture

import json
from dataclasses import replace
from types import SimpleNamespace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from lifecycle_fixture import lifecycle_work  # noqa: F401
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import TenantSkillEnablement
from pdos_next.agent_kernel.proposal_context import KEY
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.contracts import Command
from pdos_next.domain.preproject.models import ProposalItemVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Confirmation, LifecycleObject, Receipt, now
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import digest, execute
from tests.agent_kernel.test_domain_adapter_transactions import counts
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_m3_original_binding_pg import actual_run
from tests.agent_kernel.test_proposal_context_pg import agree, read
from tests.preproject.test_g0 import create, payload, post, request
from tests.preproject.test_g0 import work as work
from tests.preproject.test_m3_lifecycle_catalog import scoped as lifecycle_session
from tests.preproject.test_m3_lifecycle_catalog import uploaded as lifecycle_uploaded
from tests.products import test_definition_transactions as definitions
from tests.products.test_definition_transactions import source as product_source


def bound(work, *, human=False):
    artifact_id = product_source(work)
    data = payload(work)
    data["source_refs"] = [
        {
            "type": "artifact",
            "id": artifact_id,
            "version": 1,
            "line": 1,
            "quote": "Synthetic only",
        }
    ]
    proposal_id, _ = create(work, data)
    owner, route = Bootstrap(work.engine), configured_route()
    owner.route = owner.commands.route = lambda *_: route
    scope, sources = actual_run(work, owner, UUID(proposal_id))
    assert scope.product_id is None and sources == [
        {"artifact_id": artifact_id, "expected_revision": 1, "product_id": str(work.product)}
    ]
    with Session(work.admin) as session, session.begin():
        for key in ("public_research", "proposal_drafting"):
            skill = owner.catalog._skills[key]
            session.add(
                TenantSkillEnablement(
                    tenant_id=work.tenant,
                    skill_key=key,
                    enabled=True,
                    pilot=True,
                    qualified_skill_version=skill.version,
                    qualified_model_version=route.version,
                    qualified_skill_digest=skill.digest,
                    qualified_tool_digest=tool_identity(skill, owner.registry),
                    qualified_model_digest=model_identity(route),
                    reviewed_by=work.human,
                    reviewed_at=now(),
                    qualification_revoked=human,
                    review_case_refs=["synthetic-review-" + str(i) for i in range(10)],
                )
            )
    return SimpleNamespace(
        work=work,
        owner=owner,
        store=owner.store,
        scope=scope,
        route=route,
        registry=owner.registry,
        artifact_id=artifact_id,
        human=human,
        sources=sources,
        loaded={},
    )


def claim_args(f, identity=None):
    return {
        "source": {
            "kind": "artifact",
            "id": identity or f.artifact_id,
            "version": 1,
            "line": 1,
            "quote": "Synthetic only",
        },
        "nature": "extracted",
        "content": {"text": "Synthetic only"},
    }


def patch_args(f, identity):
    return {
        "proposal_id": str(f.scope.proposal_id),
        "ops": [
            {
                "kind": "section",
                "content": {"key": "summary", "text": "Synthetic adoption"},
                "source_refs": [{"type": "claim", "id": str(identity), "version": 1}],
            }
        ],
    }


def prepared(f, tool, args):
    key = "public_research" if tool == "evidence.claim.record" else "proposal_drafting"
    if key not in f.loaded:
        skill = f.owner.catalog._skills[key]
        identity = f.store.emit(
            f.scope,
            {
                "type": "skill_loaded",
                "key": key,
                "version": skill.version,
                "digest": skill.digest,
                "isolation": "main",
            },
        )
        f.loaded[key] = SkillBinding(
            key=key, version=skill.version, digest=skill.digest, load_event_id=identity
        )
    binding = ModelBinding(
        model_version=f.route.version,
        model_route_digest=f.route.digest,
        tool_definitions_digest=digest(f.registry.definitions()),
        prompt_digest=digest("Synthetic frozen source writeback prefix"),
        isolation="main",
        cancel_epoch=0,
        loaded_skills=tuple(f.loaded.values()),
    )
    with f.store.transaction(f.scope, lock=True) as (_, run):
        run.state = "running"
        run.versions = {
            **run.versions,
            "model_version": f.route.version,
            "model_route_digest": f.route.digest,
            "tool_definitions": {"main": binding.tool_definitions_digest},
            "prompt_prefixes": {"main": binding.prompt_digest},
        }
    call_id, _ = f.store.claim(
        f.scope,
        "synthetic-writeback:" + str(uuid4()),
        "model",
        {"synthetic": True},
        execution_binding=binding.model_dump(mode="json"),
    )
    f.store.settle(f.scope, call_id, result={"calls": [{"name": tool, "arguments": args}]})
    source = WriteSource(skill=f.loaded[key], model_call_id=call_id, response_index=0)
    intent = execution_key(f.scope.run_id, call_id, 0)
    if f.human:
        candidate = f.owner.prepare_candidate(f.scope, f.registry.get(tool), args, intent)
        checked = post(f.work, candidate["command"], preview=True)
        assert checked.status_code == 200, checked.text
        command = checked.json()["command"]

        def perform():
            response = post(f.work, command)
            assert response.status_code == 200, response.text
            return response.json()

        return perform, command
    host = BoundHost(f.store, replace(f.owner.adapters(), route_for=lambda _: f.route))
    return lambda: host.write(f.scope, f.registry.get(tool), args, intent, source=source), None


def current(f):
    with f.store.transaction(f.scope) as (_, run):
        return digest(run.versions), run.read_sources, run.data_categories


@pytest.mark.parametrize("human", [False, True])
def test_category_run_records_adopts_reads_and_replays_product_source(work, human):
    f = bound(work, human=human)
    original = current(f)
    record, _ = prepared(f, "evidence.claim.record", claim_args(f))
    receipt = record()
    assert record()["id"] == receipt["id"]
    adopt, _ = prepared(f, "proposal.item.patch", patch_args(f, receipt["subject_id"]))
    adopted = adopt()
    before = current(f), counts(work)
    assert adopt()["id"] == adopted["id"] and (current(f), counts(work)) == before
    assert current(f)[1:] == original[1:]
    document = read(f.owner, f.scope, "proposal.items.read")
    assert any(item["content"].get("text") == "Synthetic adoption" for item in document["items"])
    assert f.owner.project_context(f.scope, "Synthetic continue")["proposal"]["id"] == str(
        f.scope.proposal_id
    )
    with Session(work.admin) as session:
        claim = session.get(Claim, UUID(receipt["subject_id"]))
        item = session.scalar(
            select(ProposalItemVersion).where(
                ProposalItemVersion.proposal_id == f.scope.proposal_id,
                ProposalItemVersion.run_id == f.scope.run_id,
            )
        )
        for row in (claim, item):
            assert row.writer_id == work.agent and row.run_id == f.scope.run_id
            assert row.confirmed_by == (work.human if human else None)
        assert claim.product_id is None and claim.artifact_id == UUID(f.artifact_id)
        assert claim.privacy == "private" and claim.proposal_id == f.scope.proposal_id
    # A real new Claim cannot be represented by the predecessor guard.
    if not human:
        from migrations.schema_s0_0762 import DOWNGRADE_SQL, SCHEMA_SQL

        with pytest.raises(DBAPIError, match="history requires s0_0762"):
            with work.admin.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE pdos_next_owner")
                for statement in DOWNGRADE_SQL:
                    connection.exec_driver_sql(statement)
        with work.admin.connect() as connection:
            for table in ("claims", "artifact_versions"):
                assert connection.scalar(
                    text("SELECT relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"),
                    {"name": table},
                )
            assert (
                connection.scalar(
                    text(
                        "SELECT pg_get_functiondef('direct_source_set_visible"
                        "(uuid,uuid,uuid,jsonb)'"
                        "::regprocedure)"
                    )
                )
                == SCHEMA_SQL[0]
            )


@pytest.mark.parametrize("human", [False, True])
def test_product_source_write_tail_failure_is_atomic_and_same_request_recovers(work, human):
    f = bound(work, human=human)
    perform, command = prepared(f, "evidence.claim.record", claim_args(f))
    before = current(f), counts(work)

    def fail(_c, _cursor, statement, *_args):
        if statement.startswith("UPDATE agent_runs SET versions"):
            raise RuntimeError("Synthetic product-source writeback tail failure")

    event.listen(work.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="writeback tail failure"):
            perform()
    finally:
        event.remove(work.engine, "before_cursor_execute", fail)
    assert (current(f), counts(work)) == before
    if human:
        with Session(work.admin) as session:
            assert not session.scalar(
                select(Confirmation).where(
                    Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
                )
            ).consumed
    result = perform()
    assert perform()["id"] == result["id"]


@pytest.mark.parametrize("tool", ["evidence.claim.record", "proposal.item.patch"])
def test_readable_but_unbound_product_artifact_cannot_expand_run_on_write(work, tool):
    f = bound(work)
    response = definitions.post(
        work,
        definitions.command(
            work,
            "evidence.artifact.register",
            {
                "title": "Synthetic unbound product source",
                "source_label": "Synthetic fixture only",
                "content": "Synthetic only\nDifferent unbound source",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    other = response.json()["subject_id"]
    assert other != f.artifact_id
    args = claim_args(f, other) if tool == "evidence.claim.record" else patch_args(f, uuid4())
    if tool == "proposal.item.patch":
        args["ops"][0]["source_refs"] = [{"type": "artifact", "id": other, "version": 1}]
    perform, _ = prepared(f, tool, args)
    before = current(f), counts(work)
    with pytest.raises(DomainError) as caught:
        perform()
    assert caught.value.code == "MISSING_REQUIRED_EVIDENCE"
    assert (current(f), counts(work)) == before


def test_withdrawn_product_source_stops_new_write_and_preserves_original_receipt(work):
    f = bound(work)
    record, _ = prepared(f, "evidence.claim.record", claim_args(f))
    receipt = record()
    adopt, _ = prepared(f, "proposal.item.patch", patch_args(f, receipt["subject_id"]))
    with Session(work.admin) as session, session.begin():
        session.get(Artifact, UUID(f.artifact_id)).status = "withdrawn"
    before = counts(work)
    with pytest.raises(DomainError):
        adopt()
    assert counts(work) == before
    with Session(work.admin) as session:
        assert session.get(Receipt, UUID(receipt["id"])).agent_run_id == f.scope.run_id


@pytest.mark.parametrize("consumer", ["claim", "proposal"])
def test_pending_product_original_blocks_category_reference_without_committing_fake_state(
    work,
    lifecycle_work,
    consumer,
    monkeypatch,
):
    f = bound(work)
    original_id, artifact_id = lifecycle_uploaded(lifecycle_work, True)
    # The rollback-only fixture Session uses the test admin Engine to insert
    # metadata. Keep the actual scanner configuration used for these bytes.
    monkeypatch.setattr(
        work.admin, "_pdos_security_runtime", work.engine._pdos_security_runtime, raising=False
    )
    # This intentionally rolls back synthetic lifecycle metadata after exercising
    # the ordinary app trigger; it is not a physical retention decision.
    reason = (
        "Pending or isolated original" if consumer == "claim" else "Pending original prohibits M3"
    )
    with pytest.raises(DBAPIError, match=reason):
        with lifecycle_session(work, admin=True) as session:
            session.add(
                LifecycleObject(
                    id=original_id,
                    tenant_id=work.tenant,
                    category_id=work.category,
                    product_id=work.product,
                    owner_id=work.human,
                    reference={},
                    state={"value": {"pending_intent_id": str(uuid4()), "disposition": "active"}},
                )
            )
            session.flush()
            session.execute(text("SET LOCAL ROLE pdos_next_app"))
            if consumer == "claim":
                command = request(
                    work,
                    "evidence.claim.record",
                    {
                        "proposal_id": str(f.scope.proposal_id),
                        "nature": "extracted",
                        "content": {"text": "Synthetic exact M3 lifecycle source"},
                        "source": {
                            "kind": "artifact",
                            "id": str(artifact_id),
                            "version": 1,
                            "line": 1,
                            "quote": "Synthetic exact M3 lifecycle source",
                        },
                    },
                )
                command["source_read_set"] = [
                    {
                        "artifact_id": str(artifact_id),
                        "expected_revision": 1,
                    }
                ]
                execute(session, work.ctx, Command.model_validate(command))
                return
            session.execute(
                text(
                    "UPDATE proposals SET source_refs=CAST(:refs AS jsonb),revision=revision+1 "
                    "WHERE id=:id"
                ),
                {
                    "refs": json.dumps(
                        [
                            {
                                "type": "artifact",
                                "id": str(artifact_id),
                                "version": 1,
                                "line": 1,
                                "quote": "Synthetic exact M3 lifecycle source",
                            }
                        ]
                    ),
                    "id": f.scope.proposal_id,
                },
            )


def test_registered_graph_records_product_source_adopts_reads_and_completes(work):
    f = bound(work)
    with f.store.transaction(f.scope, lock=True) as (_, run):
        run.token_limit = 1_000_000  # Synthetic byte reservation, no real provider metering.
    agree(work, f.scope, f.scope.data_categories)
    claim_id = None

    def answer(kwargs):
        nonlocal claim_id
        step = client.calls
        if step == 1:
            tool, args = "evidence.claim.record", claim_args(f)
        elif step == 2:
            receipt = json.loads(kwargs["messages"][-1]["content"])
            assert "error" not in receipt, receipt
            claim_id = receipt["subject_id"]
            tool, args = "proposal.item.patch", patch_args(f, claim_id)
        elif step == 3:
            assert "error" not in json.loads(kwargs["messages"][-1]["content"])
            tool, args = "proposal.items.read", {"proposal_id": str(f.scope.proposal_id)}
        else:
            value = json.loads(kwargs["messages"][-1]["content"])
            assert any(
                item["content"].get("text") == "Synthetic adoption" for item in value["items"]
            ), value
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "Synthetic product source adopted",
                    "result": {"claim_id": claim_id},
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(2, 1),
            )
        return ModelTurn(
            calls=(ToolCall(id="synthetic-" + str(step), name=tool, arguments=args),),
            usage=ProviderUsage(2, 1),
        )

    client = Client(answer)
    host = BoundHost(
        f.store,
        replace(
            f.owner.adapters(),
            route_for=lambda _: f.route,
            provider_for=lambda *_: "synthetic-provider",
            provider_client=client,
            cost_required=False,
        ),
    )
    result = AgentKernel(host, f.registry).execute(
        f.scope,
        goal="Synthetic product source writeback",
        preload=("public_research", "proposal_drafting"),
    )
    assert result["output"]["status"] == "completed" and client.calls == 4, result["output"]
    with f.store.transaction(f.scope) as (_, run):
        assert run.state == "completed" and run.read_sources == f.sources
        assert any(ref["id"] == claim_id for ref in run.versions[KEY]["references"])
    print(
        json.dumps(
            {
                "registered_graph_run_id": str(f.scope.run_id),
                "synthetic_turns": client.calls,
                "real_provider_calls": 0,
                "outcome": result["output"]["status"],
            }
        )
    )
