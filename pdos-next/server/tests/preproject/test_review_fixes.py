"""Review regressions on an explicit ordinary-owner PostgreSQL fixture."""
# ruff: noqa: F811 -- pytest injects the imported work fixture into named parameters

from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import AgentSession, AgentToolCall, TenantSkillEnablement
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_models import (
    ProductTargetSegment,
)
from pdos_next.domain.preproject.models import ProjectOpenItem, ProposalSource
from pdos_next.domain.preproject.provenance import prepare_candidate
from pdos_next.errors import DomainError
from pdos_next.models import Grant
from pdos_next.service import digest, execute
from tests.agent_kernel.test_execution_binding import ledger
from tests.preproject.test_g0 import (
    create,
    decide_request,
    payload,
    post,
    read,
    request,
    save,
    submit,
    work,  # noqa: F401 -- shared PG fixture
)


def agent_fixture(work, operation, arguments, proposal_id=None):
    f = ledger()
    f.scope = replace(
        f.scope,
        tenant_id=work.tenant,
        category_id=work.category,
        requester_id=work.human,
        writer_id=work.agent,
        product_id=None,
        proposal_id=UUID(proposal_id) if proposal_id else None,
    )
    for field in (
        "tenant_id",
        "category_id",
        "requester_id",
        "writer_id",
        "product_id",
        "proposal_id",
    ):
        setattr(f.run, field, getattr(f.scope, field))
    f.run.trigger, f.run.goal = "page", "Synthetic M3 review regression"
    f.run.intent_key, f.run.intent_digest = str(uuid4()), digest(str(uuid4()))
    f.arguments, f.spec = arguments, f.registry.get(operation)
    f.model.tenant_id, f.event.tenant_id, f.qualification.tenant_id = (work.tenant,) * 3
    f.qualification.reviewed_by = work.human
    f.model.call_key, f.model.input_digest = str(uuid4()), digest("synthetic response")
    f.model.result = {"calls": [{"id": "untrusted", "name": operation, "arguments": arguments}]}
    with tenant_session(
        work.admin,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as s:
        s.add(
            AgentSession(
                id=f.scope.session_id,
                tenant_id=work.tenant,
                category_id=work.category,
                owner_id=work.human,
                proposal_id=f.scope.proposal_id,
            )
        )
        s.flush()
        s.add(f.run)
        s.flush()
        qualification = s.scalar(
            select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == work.tenant,
                TenantSkillEnablement.skill_key == f.qualification.skill_key,
            )
        )
        if qualification is None:
            s.add(f.qualification)
        else:
            f.qualification = qualification
        s.add_all([f.model, f.event])
        s.flush()
        s.expunge_all()
    f.adapter = DomainCommands(
        work.engine, catalog=f.catalog, registry=f.registry, route=lambda *_: f.route
    )
    return f


def agent_session(work, f):
    return tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.agent,
        requester_id=work.human,
        category_id=work.category,
    )


def new_model_call(work, f, operation, arguments):
    row = AgentToolCall(
        id=uuid4(),
        tenant_id=work.tenant,
        run_id=f.scope.run_id,
        call_key=str(uuid4()),
        input_digest=digest(arguments),
        tool="model",
        state="completed",
        execution_binding=f.model.execution_binding,
        result={"calls": [{"name": operation, "arguments": arguments}]},
    )
    identity = row.id
    with Session(work.admin) as s, s.begin():
        s.add(row)
    return f.source.model_copy(update={"model_call_id": identity})


def test_actual_owner_and_definers_are_non_superuser(work):
    with Session(work.admin) as s, s.begin():
        # The formal B8 fixture retains its administrative bootstrap connection;
        # the schema owner is NOLOGIN and is entered only by that connection.
        s.execute(text("SET LOCAL ROLE pdos_next_owner"))
        assert s.execute(
            text(
                "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        ).one() == ("pdos_next_owner", False, False)
        assert not s.scalar(text("SELECT rolcanlogin FROM pg_roles WHERE rolname=current_user"))
        assert (
            s.scalar(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' AND p.prosecdef "
                    "AND (r.rolsuper OR r.rolbypassrls OR r.rolname<>'pdos_next_owner')"
                )
            )
            == 0
        )
        assert not s.scalar(text("SELECT pg_has_role('pdos_next_app','pdos_next_owner','MEMBER')"))
        assert not s.scalar(text("SELECT has_schema_privilege('pdos_next_app','public','CREATE')"))
        assert not s.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname='m3_materialize_g0')")
        )


def test_g0_target_price_and_pinned_target_segment(work):
    registered, _ = save(
        work,
        request(
            work,
            "category.knowledge.add",
            {
                "kind": "segment",
                "content": {"segment": "车主", "jtbd": ["随车充气"], "channels": ["retail"]},
            },
        ),
    )
    identity = UUID(registered["result"]["entry_id"])
    lineage = UUID(registered["result"]["lineage_id"])
    data = payload(work)
    data["context_refs"] = [{"type": "knowledge", "id": str(identity), "version": 1}]
    data["groups"]["items"].append(
        {
            "kind": "commercial_target",
            "content": {
                "target_price": {
                    "amount": "199.50",
                    "currency": "CNY",
                    "basis": "retail",
                    "includes_tax": True,
                    "as_of": "2026-10-08",
                }
            },
        }
    )
    proposal_id, _ = create(work, data)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    with Session(work.admin) as s:
        result = s.execute(
            text(
                "SELECT target_price,target_price_currency,target_price_basis,"
                "target_price_includes_tax,target_price_as_of FROM products WHERE id=:id"
            ),
            {"id": UUID(approved["result"]["product_id"])},
        ).one()
        assert str(result.target_price).startswith("199.5")
        assert tuple(result[1:4]) == ("CNY", "retail", True)
        assert str(result.target_price_as_of) == "2026-10-08"
        target = s.scalar(
            select(ProductTargetSegment).where(
                ProductTargetSegment.product_id == UUID(approved["result"]["product_id"])
            )
        )
        assert target.segment_lineage_id == lineage and target.segment_version == 1


def test_open_item_title_note_and_later_state(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    req = decide_request(work, proposal_id)
    for disp in req["payload"]["dispositions"]:
        disp["note"] = "独立的处置说明"
    approved, _ = save(work, req, actor=work.peer)
    with Session(work.admin) as s, s.begin():
        rows = list(
            s.scalars(
                select(ProjectOpenItem).where(
                    ProjectOpenItem.project_id == UUID(approved["result"]["project_id"])
                )
            )
        )
        assert {row.title for row in rows} == {"噪声", "噪声条件待确定"}
        assert all(row.note == "独立的处置说明" for row in rows)
        for row in rows:
            row.status = "completed"
    with Session(work.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(ProjectOpenItem)
                .where(
                    ProjectOpenItem.project_id == UUID(approved["result"]["project_id"]),
                    ProjectOpenItem.status == "completed",
                )
            )
            == 2
        )


@pytest.mark.parametrize("table", ["definition_specs", "definition_sources"])
def test_sealed_definition_rejects_insert(work, table):
    data = payload(work)
    if table == "definition_sources":
        artifact = post(
            work,
            request(
                work,
                "evidence.artifact.register",
                {
                    "title": "合成来源",
                    "source_label": "合成",
                    "content": "合成要求",
                    "visibility": "private",
                },
            ),
        ).json()["subject_id"]
        data["source_refs"] = [
            {"type": "artifact", "id": artifact, "version": 1, "line": 1, "quote": "合成要求"}
        ]
    proposal_id, _ = create(work, data)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    # definition_specs now trips the narrower m3 item guard ("definition is fixed")
    # before the generic sealed guard; both are the same refusal.
    refusal = "sealed|definition is fixed"
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError, match=refusal):
        columns = list(
            s.scalars(
                text(
                    "SELECT attname FROM pg_attribute WHERE attrelid=CAST(:table AS regclass) "
                    "AND attnum>0 AND NOT attisdropped ORDER BY attnum"
                ),
                {"table": table},
            )
        )
        select_columns = [
            "gen_random_uuid()" if c == "id" else "'added'" if c == "key" else c for c in columns
        ]
        s.execute(
            text(
                f"INSERT INTO {table}({','.join(columns)}) SELECT {','.join(select_columns)} "
                f"FROM {table} WHERE definition_id=:id LIMIT 1"
            ),
            {"id": UUID(approved["result"]["definition_id"])},
        )


def test_sources_incremental_no_unchanged_quote_revalidation(work, monkeypatch):
    from pdos_next.domain.preproject import service

    source = post(
        work,
        request(
            work,
            "evidence.artifact.register",
            {
                "title": "合成原件",
                "source_label": "合成",
                "content": "共享引用测试",
                "visibility": "private",
            },
        ),
    ).json()["subject_id"]
    ref = {"type": "artifact", "id": source, "version": 1, "line": 1, "quote": "共享引用"}
    data = payload(work)
    for item in data["groups"]["items"][:2]:
        item["source_refs"] = [ref]
    proposal_id, _ = create(work, data)
    before = read(work, proposal_id).json()
    calls = []
    original = service.source_for

    def tracked(*args, **kwargs):
        calls.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "source_for", tracked)
    for index in (0, 1):
        item = before["items"][index]
        patch = request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": proposal_id,
                "ops": [
                    {
                        "op": "upsert",
                        "item_id": item["item_id"],
                        "base_version": item["version"],
                        "kind": item["kind"],
                        "content": item["content"],
                        "source_refs": [],
                    }
                ],
            },
        )
        assert post(work, patch).status_code == 200
        with Session(work.admin) as s:
            link = s.scalar(
                select(ProposalSource).where(ProposalSource.proposal_id == UUID(proposal_id))
            )
            assert (link.ref_count if link else 0) == 1 - index
        assert read(work, proposal_id).json()["private_source_count"] == 1 - index
    assert calls == []


def test_t1_prepared_create_preserves_ai_origin_and_confirming_person(work):
    data = payload(work)
    data["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
    f = agent_fixture(work, "proposal.create", data)
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.create",
            data,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    approved, _ = save(work, request(work, "proposal.create", prepared))
    proposal_id = approved["subject_id"]
    rows = read(work, proposal_id).json()["items"]
    assert all(
        row["origin"] == "ai_draft"
        and row["writer_id"] == str(work.agent)
        and row["run_id"] == str(f.scope.run_id)
        and row["confirmed_by"] == str(work.human)
        and row["human_value"]
        for row in rows
    )


@pytest.mark.parametrize(
    ("availability", "item_status", "requires_disposition"),
    [
        ("unknown", "ai_draft", True),
        ("conflicted", "ai_draft", True),
        ("not_applicable", "ai_draft", False),
        ("not_applicable", "unknown", False),
        ("not_applicable", "expert_pending", True),
    ],
)
def test_at52_ai_spec_availability_requires_disposition_only_for_approval(
    work, availability, item_status, requires_disposition
):
    data = payload(work)
    data["groups"]["questions"] = []
    for item in data["groups"]["items"]:
        if item["kind"] == "spec":
            item["content"]["item_status"] = "ai_draft"
    data["groups"]["items"][3]["content"].update(
        availability=availability,
        item_status=item_status,
        reason="此配置不采用该噪声要求" if availability == "not_applicable" else None,
    )
    f = agent_fixture(work, "proposal.create", data)
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.create",
            data,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    created, _ = save(work, request(work, "proposal.create", prepared))
    proposal_id = created["subject_id"]
    # Unknown AI values may enter G0; the new rule applies only to approval.
    submit(work, proposal_id)
    fixed = read(work, proposal_id, work.peer).json()
    spec = next(
        item
        for item in fixed["submission"]["frozen_document"]["items"]
        if item["kind"] == "spec" and item["content"]["key"] == "noise"
    )
    assert spec["origin"] == "ai_draft" and spec["run_id"] == str(f.scope.run_id)
    assert spec["content"]["availability"] == availability
    expected = {spec["item_id"]} if requires_disposition else set()
    assert {entry["subject_id"] for entry in fixed["maturity"]["required_dispositions"]} == expected
    req = decide_request(work, proposal_id)
    preview = post(work, req, actor=work.peer, preview=True)
    assert preview.status_code == 200, preview.text
    assert {
        entry["subject_id"] for entry in preview.json()["review"]["required_dispositions"]
    } == expected
    if requires_disposition:
        missing = deepcopy(req)
        missing["payload"]["dispositions"] = []
        for is_preview in (True, False):
            rejected = post(work, missing, actor=work.peer, preview=is_preview)
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["code"] == "VALIDATION_FAILED"
            assert rejected.json()["detail"]["reason"] == "unknown_without_disposition"
        assert read(work, proposal_id).json()["status"] == "in_review"
        assert (
            post(
                work,
                decide_request(work, proposal_id, "returned"),
                actor=work.peer,
                preview=True,
            ).status_code
            == 200
        )
    approved = post(work, preview.json()["command"], actor=work.peer)
    assert approved.status_code == 200, approved.text
    with Session(work.admin) as s:
        pending = list(
            s.scalars(
                select(ProjectOpenItem).where(
                    ProjectOpenItem.project_id == UUID(approved.json()["result"]["project_id"]),
                )
            )
        )
        assert len(pending) == int(requires_disposition)
        if pending:
            assert pending[0].kind == "risk" and pending[0].owner_id == work.expert
            assert pending[0].due_date.isoformat() == "2026-10-25"


def test_batch_validation_keeps_each_candidate_identity_and_source_privacy(work, monkeypatch):
    from pdos_next.domain.preproject import service
    from pdos_next.domain.preproject.schemas import ProposalCreate
    from pdos_next.models import Category

    sources = []
    for visibility in ("private", "category"):
        result = post(
            work,
            request(
                work,
                "evidence.artifact.register",
                {
                    "title": visibility,
                    "source_label": "合成",
                    "content": "批量候选引用",
                    "visibility": visibility,
                },
            ),
        )
        assert result.status_code == 200, result.text
        sources.append(
            {
                "type": "original",
                "id": result.json()["subject_id"],
                "version": 1,
                "line": 1,
                "quote": "批量候选引用",
            }
        )
    prepared_commands, runs = [], []
    for index in range(3):
        data = payload(work)
        data["title"] = f"批量候选 {index}"
        data["source_refs"] = [sources[index % 2]]
        if index < 2:
            data["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
            f = agent_fixture(work, "proposal.create", data)
            with agent_session(work, f) as s:
                data = prepare_candidate(
                    s,
                    f.scope,
                    "proposal.create",
                    data,
                    f.source,
                    catalog=f.catalog,
                    registry=f.registry,
                    route=f.route,
                )
            runs.append(f.scope.run_id)
        else:
            runs.append(None)
        preview = post(work, request(work, "proposal.create", data), preview=True)
        assert preview.status_code == 200, preview.text
        prepared_commands.append(Command.model_validate(preview.json()["command"]))

    results = []
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        category_id=work.category,
    ) as s:
        scope = s.get(Category, work.category)
        validated = {
            cmd.command_id: service.validate(
                s,
                work.ctx,
                cmd,
                scope,
                ProposalCreate.model_validate(cmd.payload),
            )
            for cmd in prepared_commands
        }
        assert "m3_provenance" not in s.info and "m3_reference_privacy" not in s.info
        for index, cmd in enumerate(prepared_commands):
            body = ProposalCreate.model_validate(cmd.payload)
            assert validated[cmd.command_id].reference_privacy == {
                digest(body.source_refs[0].model_dump(mode="json")): "private"
                if index % 2 == 0
                else "shared",
                digest(body.groups.items[4].source_refs[0].model_dump(mode="json")): "shared",
            }
        # Simulate validating every candidate before the common command writer
        # consumes any of them. All confirmation/receipt/atomic guards still run.
        monkeypatch.setattr(
            service, "validate", lambda _s, _ctx, cmd, *_: validated[cmd.command_id]
        )
        for cmd in prepared_commands:
            results.append(execute(s, work.ctx, cmd))
        assert "m3_provenance" not in s.info and "m3_reference_privacy" not in s.info
    for index, result in enumerate(results):
        row = read(work, result["subject_id"]).json()
        assert row["private_source_count"] == int(index % 2 == 0)
        assert all(
            item["origin"] == ("ai_draft" if runs[index] else "human")
            and item["run_id"] == (str(runs[index]) if runs[index] else None)
            and item["writer_id"] == str(work.agent if runs[index] else work.human)
            and item["confirmed_by"] == (str(work.human) if runs[index] else None)
            for item in row["items"]
        )


def test_audience_lookup_returns_only_scoped_membership(work):
    proposal_id, _ = create(work)
    sql = text("SELECT m3_audience_member(:t,:c,:p,:person)")
    params = {"t": work.tenant, "c": work.category, "p": UUID(proposal_id)}
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        category_id=work.category,
    ) as s:
        assert s.scalar(sql, {**params, "person": work.human}) is True
        assert s.scalar(sql, {**params, "person": work.expert}) is False
        assert s.scalar(sql, {**params, "person": work.other_human}) is False
        assert s.scalar(sql, {**params, "person": work.human, "t": work.other_tenant}) is False
        assert (
            s.scalar(text("SELECT to_regprocedure('m3_effective_audience(uuid,uuid,uuid)')"))
            is None
        )
    # A category member who cannot read this private proposal learns no members.
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        category_id=work.category,
    ) as s:
        assert s.scalar(sql, {**params, "person": work.human}) is False
    submit(work, proposal_id)
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        category_id=work.category,
    ) as s:
        assert s.scalar(sql, {**params, "person": work.human}) is True
        assert s.scalar(sql, {**params, "person": work.peer}) is True
        assert s.scalar(sql, {**params, "person": work.expert}) is False


def test_t0_qualified_patch_real_receipt_and_protection(work):
    proposal_id, _ = create(work)
    args = {
        "proposal_id": proposal_id,
        "ops": [{"kind": "section", "content": {"key": "summary", "text": "AI 草稿"}}],
    }
    f = agent_fixture(work, "proposal.item.patch", args, proposal_id)
    key = execution_key(f.scope.run_id, f.source.model_call_id, f.source.response_index)
    result = f.adapter.execute(f.scope, "proposal.item.patch", args, key, source=f.source)
    added = read(work, proposal_id).json()["items"][-1]
    assert (
        added["origin"] == "ai_draft"
        and added["run_id"] == str(f.scope.run_id)
        and not added["human_value"]
    )
    assert result["agent_call_id"]
    replay = f.adapter.execute(f.scope, "proposal.item.patch", args, key, source=f.source)
    assert replay["id"] == result["id"]
    # A new real model ledger response still cannot replace a human version.
    human_item = read(work, proposal_id).json()["items"][0]
    protected = {
        "proposal_id": proposal_id,
        "ops": [
            {
                "item_id": human_item["item_id"],
                "base_version": 1,
                "kind": "section",
                "content": {"key": "worth_it", "text": "AI 替换人工"},
            }
        ],
    }
    source = new_model_call(work, f, "proposal.item.patch", protected)
    with pytest.raises(DomainError) as error:
        f.adapter.execute(
            f.scope,
            "proposal.item.patch",
            protected,
            execution_key(f.scope.run_id, source.model_call_id, 0),
            source=source,
        )
    assert error.value.code == "CONFIRMATION_REQUIRED"
    assert error.value.detail["reason"] == "human_value_protected"


def test_agent_context_without_controlled_call_cannot_write(work):
    from pdos_next.service import Context

    proposal_id, _ = create(work)
    ctx = Context(
        work.tenant, work.agent, work.human, category_id=work.category, agent_run_id=uuid4()
    )
    with (
        tenant_session(
            work.engine,
            work.tenant,
            actor_id=work.agent,
            requester_id=work.human,
            category_id=work.category,
        ) as s,
        pytest.raises(DomainError) as error,
    ):
        execute(
            s,
            ctx,
            Command.model_validate(
                request(
                    work,
                    "proposal.item.patch",
                    {
                        "proposal_id": proposal_id,
                        "ops": [{"kind": "section", "content": {"key": "summary", "text": "伪造"}}],
                    },
                )
            ),
        )
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_t1_candidate_tampering_rejected(work):
    data = payload(work)
    data["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
    f = agent_fixture(work, "proposal.create", data)
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.create",
            data,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    changed = deepcopy(prepared)
    changed["groups"]["items"][0]["content"]["text"] = "伪造候选"
    response = post(work, request(work, "proposal.create", changed), preview=True)
    assert (
        response.status_code == 403
        and response.json()["detail"]["reason"] == "candidate_binding_invalid"
    )


def test_t1_patch_requires_confirmation_without_t0_qualification(work):
    from pdos_next.agent_kernel.models import TenantSkillEnablement

    proposal_id, _ = create(work)
    item = read(work, proposal_id).json()["items"][0]
    args = {
        "proposal_id": proposal_id,
        "ops": [
            {
                "item_id": item["item_id"],
                "base_version": item["version"],
                "kind": "section",
                "content": {"key": "worth_it", "text": "AI 建议，人确认"},
            }
        ],
    }
    f = agent_fixture(work, "proposal.item.patch", args, proposal_id)
    with Session(work.admin) as s, s.begin():
        s.get(TenantSkillEnablement, f.qualification.id).qualification_revoked = True
    with pytest.raises(DomainError) as denied:
        f.adapter.execute(
            f.scope,
            "proposal.item.patch",
            args,
            execution_key(f.scope.run_id, f.source.model_call_id, 0),
            source=f.source,
        )
    assert denied.value.code == "QUALIFICATION_REQUIRED"
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.item.patch",
            args,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    assert post(work, request(work, "proposal.item.patch", prepared)).status_code == 409
    save(work, request(work, "proposal.item.patch", prepared))
    saved = read(work, proposal_id).json()["items"][0]
    assert saved["version"] == 2 and saved["content"]["text"] == "AI 建议，人确认"
    assert saved["origin"] == "ai_draft" and saved["run_id"] == str(f.scope.run_id)
    assert saved["confirmed_by"] == str(work.human) and saved["human_value"]


def test_t1_run_cancelled_after_preview_cannot_be_consumed(work):
    from pdos_next.agent_kernel.models import AgentRun

    data = payload(work)
    data["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
    f = agent_fixture(work, "proposal.create", data)
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.create",
            data,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    preview = post(work, request(work, "proposal.create", prepared), preview=True)
    assert preview.status_code == 200
    with Session(work.admin) as s, s.begin():
        run = s.get(AgentRun, f.scope.run_id)
        run.cancel_epoch += 1
        run.state = "cancelled"
    result = post(work, preview.json()["command"])
    assert (
        result.status_code == 403
        and result.json()["detail"]["reason"] == "candidate_binding_invalid"
    )


@pytest.mark.parametrize("visibility", ["category", "audience"])
def test_g0_uses_effective_proposal_audience(work, visibility):
    from tests.preproject.test_evidence_commands_pg import share_request

    proposal_id, _ = create(work)
    save(
        work,
        share_request(
            work,
            proposal_id,
            visibility=visibility,
            audience_ids=[work.expert] if visibility == "audience" else [],
        ),
    )
    submit(work, proposal_id)
    result, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    assert all(not d["audience_added"] for d in result["result"]["dispositions"])
    assert not result["result"]["project_owner_audience_added"]


def test_old_round_reviewer_remains_in_effective_audience(work):
    from pdos_next.domain.preproject.models import Proposal
    from pdos_next.domain.preproject.schemas import G0Decide
    from pdos_next.domain.preproject.service import _audience_changes

    proposal_id, _ = create(work)
    submit(work, proposal_id)
    save(work, decide_request(work, proposal_id, "returned"), actor=work.peer)
    with Session(work.admin) as s, s.begin():
        grant = s.scalar(select(Grant).where(Grant.principal_id == work.expert))
        grant.product_manager = True
    row = read(work, proposal_id).json()
    save(
        work,
        request(
            work,
            "proposal.g0.submit",
            {
                "proposal_id": proposal_id,
                "expected_revision": row["revision"],
                "reviewer_id": str(work.expert),
            },
            revision=row["revision"],
        ),
    )
    current = read(work, proposal_id).json()
    params = G0Decide(
        proposal_id=UUID(proposal_id),
        submission_id=UUID(current["submission"]["id"]),
        expected_revision=current["revision"],
        outcome="approved",
        rationale="合成旧轮受众核对",
        project={"name": "旧轮评审人负责", "owner_id": work.peer},
        dispositions=[
            {
                "subject_type": "question",
                "subject_id": uuid4(),
                "kind": "task",
                "owner_id": work.peer,
                "due_date": "2026-10-25",
                "note": "合成受众核对",
            }
        ],
    )
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as s:
        dispositions, _owner, added = _audience_changes(
            s, s.get(Proposal, UUID(proposal_id)), params
        )
        assert not dispositions[0]["audience_added"] and not added


def test_commercial_nested_source_is_validated_and_canonical(work):
    data = payload(work)
    item = {
        "kind": "commercial_target",
        "content": {
            "target_price": {
                "amount": "199",
                "source": {
                    "type": "original",
                    "id": str(uuid4()),
                    "version": 1,
                    "line": 1,
                    "quote": "不存在的价格证据",
                },
            }
        },
    }
    data["groups"]["items"].append(item)
    result = post(work, request(work, "proposal.create", data), preview=True)
    assert result.status_code == 403


def test_ai_question_origin_survives_g0_carry(work):
    data = payload(work)
    data["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
    f = agent_fixture(work, "proposal.create", data)
    with agent_session(work, f) as s:
        prepared = prepare_candidate(
            s,
            f.scope,
            "proposal.create",
            data,
            f.source,
            catalog=f.catalog,
            registry=f.registry,
            route=f.route,
        )
    created, _ = save(work, request(work, "proposal.create", prepared))
    proposal_id = created["subject_id"]
    submit(work, proposal_id)
    save(work, decide_request(work, proposal_id), actor=work.peer)
    question = next(i for i in read(work, proposal_id).json()["items"] if i["kind"] == "question")
    assert question["content"]["status"] == "carried" and question["origin"] == "ai_draft"
    assert question["run_id"] == str(f.scope.run_id) and question["writer_id"] == str(work.agent)
    assert question["confirmed_by"] == str(work.peer)


def test_source_type_database_constraint_rejects_noncanonical_value(work):
    proposal_id, _ = create(work)
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError) as error:
        s.add(
            ProposalSource(
                tenant_id=work.tenant,
                category_id=work.category,
                proposal_id=UUID(proposal_id),
                source_type="artifact",
                source_id=uuid4(),
                source_version=1,
                privacy="shared",
                ref_count=1,
            )
        )
        s.flush()
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize(
    "operation", ["proposal.create", "proposal.item.patch", "proposal.question.create"]
)
def test_registered_host_preparation_preserves_model_source(work, operation):
    from pdos_next.agent_kernel.bootstrap import Bootstrap

    proposal_id = None
    if operation == "proposal.create":
        arguments = payload(work)
        arguments["groups"]["items"][4]["content"]["item_status"] = "ai_draft"
    else:
        proposal_id, _ = create(work)
        arguments = {
            "proposal_id": proposal_id,
            "ops": [{"kind": "section", "content": {"key": "summary", "text": "准备候选"}}],
        }
        if operation == "proposal.question.create":
            assert post(work, request(work, "proposal.item.patch", arguments)).status_code == 200
            arguments = {
                "proposal_id": proposal_id,
                "expected_revision": 2,
                "question": "登记宿主的问题",
                "owner_id": str(work.human),
                "due_date": "2026-10-25",
            }
    f = agent_fixture(work, operation, arguments, proposal_id)
    host = Bootstrap(work.engine)
    host.catalog, host.registry, host.route = f.catalog, f.registry, lambda *_: f.route
    key = execution_key(f.scope.run_id, f.source.model_call_id, 0)
    candidate = host.prepare_candidate(f.scope, f.spec, arguments, key)
    assert candidate["requires_human"] and candidate["write_tier"] == "T1"
    body = candidate["command"]["payload"]
    assert body["prepared_by_run_id"] == str(f.scope.run_id) and len(body["candidate_digest"]) == 64
    if operation == "proposal.question.create":
        assert candidate["command"]["expected_revision"] == 2
    saved, _ = save(work, candidate["command"])
    items = read(work, proposal_id or saved["subject_id"]).json()["items"]
    row = items[0] if operation == "proposal.create" else items[-1]
    if operation == "proposal.question.create":
        row = next(i for i in items if i["content"].get("question") == arguments["question"])
    assert row["origin"] == "ai_draft" and row["run_id"] == str(f.scope.run_id)
    assert row["confirmed_by"] == str(work.human)


def test_registered_graph_protected_t0_becomes_t1_candidate():
    from pdos_next.agent_kernel.graph import AgentKernel
    from pdos_next.agent_kernel.tools import default_registry
    from pdos_next.agent_kernel.types import ModelTurn, ToolCall
    from pdos_next.domain.preproject.access import fail
    from tests.agent_kernel.test_graph import Host, final, scope

    host = Host(
        [
            ModelTurn(
                calls=(
                    ToolCall(
                        id="protected", name="proposal.item.patch", arguments={"text": "建议"}
                    ),
                ),
                ledger_call_id=uuid4(),
            ),
            final(),
        ]
    )
    host.qualified = lambda *_: True

    def protected(*args, **kwargs):
        fail("CONFIRMATION_REQUIRED", "human_value_protected", "合成人工值受保护")

    host.write = protected
    result = AgentKernel(host, default_registry()).execute(
        scope(), goal="Synthetic protected value", preload=["proposal_drafting"]
    )
    assert len(host.prepared) == 1
    assert result["tool_results"][0]["value"]["requires_human"]


def test_invalid_stored_model_candidate_returns_safe_field_feedback_without_writes(work):
    from pdos_next.domain.preproject.models import PreparedCandidate

    proposal_id, _ = create(work)
    arguments = {
        "proposal_id": proposal_id,
        "ops": [{"op": "upsert", "item_id": "", "kind": "section",
                 "content": {"key": "summary", "text": "PRIVATE_SYNTHETIC_CANDIDATE"}}],
    }
    f = agent_fixture(work, "proposal.item.patch", arguments, proposal_id=proposal_id)
    with pytest.raises(DomainError) as caught, agent_session(work, f) as s:
        prepare_candidate(s, f.scope, f.spec.name, arguments, f.source,
                          catalog=f.catalog, registry=f.registry, route=f.route)
    assert caught.value.code == "VALIDATION_FAILED"
    assert caught.value.detail["fields"] == [{"path": ["ops", 0, "item_id"],
                                              "type": "uuid_parsing"}]
    assert "PRIVATE_SYNTHETIC_CANDIDATE" not in str(caught.value.payload())
    with Session(work.admin) as s:
        assert s.scalar(select(func.count()).select_from(PreparedCandidate).where(
            PreparedCandidate.run_id == f.scope.run_id,
        )) == 0
    assert all(row["content"].get("key") != "summary"
               for row in read(work, proposal_id).json()["items"])
