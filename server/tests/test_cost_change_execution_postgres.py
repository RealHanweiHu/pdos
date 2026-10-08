"""Cost alternative → named ECR → actual execution and independent confirmation.

Only the explicitly assigned exclusive temporary pdos_test is used. Synthetic
source documents and tenant records remain available for receipt inspection.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.auth.errors import ObjectPermissionDeniedError
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import change_execution_overview as overview
from app.domain import change_execution_results as results
from app.domain import change_execution_tasks as tasks
from app.domain import change_impact_scope as scope
from app.domain import professional_change_routes as professional
from app.domain.change_governance import ChangeGovernanceService
from app.domain.cost_alternatives import AlternativeDraft, AlternativeSave, CostAlternativeService
from app.domain.cost_inputs import PriceDraft
from app.domain.issues import IssueService
from app.domain.product_workspace import ProductWorkError, digest
from app.main import app
from tests.test_cost_recovery_postgres import cost_scope as cost_scope
from tests.test_cost_recovery_postgres import rollup, save_input, setup_cost
from tests.test_material_issue_closure_api import headers
from tests.test_supplier_replies_postgres import SupplyPostgresScope


def alternative(s: SupplyPostgresScope) -> dict[str, Any]:
    value = setup_cost(s)
    with s.engine.connect() as c:
        observation = c.execute(
            select(tables.cost_gap_observations.c.id).where(
                tables.cost_gap_observations.c.case_id == UUID(value["case"]["id"])
            )
        ).scalar_one()
    proposed_price = save_input(
        s,
        uuid4(),
        PriceDraft.model_validate(
            {
                **value["original"]["payload"],
                "amount": "2",
                "source_reference": "negotiated-estimate",
                "reason": "独立备选费用原件",
            }
        ),
    )
    proposal = rollup(s, value["bom"], UUID(proposed_price["id"]), UUID(value["target"]["id"]))
    draft = AlternativeDraft(
        case_id=UUID(value["case"]["id"]),
        observation_id=observation,
        title="同物料议价方案",
        scope="维持原BOM与规格，核对报价适用范围",
        quality_impact="仍须独立验证品质",
        schedule_impact="原交付时间待核对",
        supplier_impact="原供方条件待核对",
        nre_impact="NRE未知，不补零",
        validation_requirements="获批范围要求实际证据与独立确认",
        unknowns="真实业务效果未验证",
        correspondence_basis="原BOM每台两个，同口径CNY",
        evidence_id=s.document,
        evidence_location="p3",
        proposal_rollup_id=UUID(proposal["id"]),
        reason="合成议价方案",
    )
    service = CostAlternativeService(s.engine)
    prepared = service.preview(s.owner, s.project, draft)
    saved = service.save(
        s.owner,
        s.project,
        AlternativeSave(
            draft=draft,
            request_id=uuid4(),
            expected_digest=prepared["digest"],
            checked=True,
        ),
    )
    return {**value, "alternative": saved, "draft": draft, "proposal_price": proposed_price}


def approved(s: SupplyPostgresScope) -> dict[str, Any]:
    value = alternative(s)
    source_id = UUID(value["alternative"]["id"])
    options = professional.options(
        s.engine,
        context=s.owner,
        project_id=s.project,
        kind="cost_alternative",
        source_id=source_id,
    )
    route = professional.route(
        s.engine,
        context=s.owner,
        project_id=s.project,
        kind="cost_alternative",
        source_id=source_id,
        draft=professional.RouteDraft(
            request_id=uuid4(),
            expected_digest=options["digest"],
            reason="合成具名变更：核对报价范围及实施条件",
            code="ECR-COST-1",
            title="议价实施与证据确认",
        ),
    )
    ecr = UUID(route["ecr_id"])
    governance = ChangeGovernanceService(s.engine)
    context = dict(tenant_id=s.owner.tenant.id, project_id=s.project, ecr_id=ecr)
    governance.start_impact(**context, actor_user_id=s.owner.user.id)
    key = uuid4()
    with s.engine.connect() as c:
        document = scope.source(c, s.owner.tenant.id, s.project, "document", s.document)
    version = scope.save(
        s.engine,
        context=s.owner,
        project_id=s.project,
        ecr_id=ecr,
        draft=scope.ScopeDraft(
            request_id=uuid4(),
            reason="核对合同及实施说明",
            coverage="仅本议价方案的文件协同实施范围",
            exclusions="实际产品品质、复测、认证、ERP生效与真实成本效益另验",
            items=[
                scope.ScopeItem(
                    key=key,
                    kind="document",
                    id=s.document,
                    expected_digest=digest(document),
                    conclusion="affected",
                    basis="原报价及实施范围须有实际回应文件",
                    action="coordination",
                    next_action="实际实施文件回写并由独立确认人核对",
                )
            ],
        ),
    )
    with s.engine.connect() as c:
        professional_basis = professional.impact_basis(c, s.owner.tenant.id, s.project, ecr)
        scope_basis = scope.current_basis(c, s.owner.tenant.id, s.project, ecr)
    assert professional_basis and scope_basis
    analysis = dict(
        summary="具名核对九类影响；此合成范围仅要求文件协同",
        professional=dict(
            expected_basis_digest=digest(professional_basis),
            source_responses={route["id"]: "按报价文件范围实施，真实收益另验"},
            assessments={
                axis: dict(
                    conclusion="affected" if axis == "cost" else "unaffected",
                    basis="合成逐项核对结论",
                    next_action="实际文件回写独立确认",
                )
                for axis in professional.AXES
            },
        ),
        impact_scope=dict(version_id=version["id"], expected_digest=digest(scope_basis)),
    )
    governance.submit_impact(
        **context, actor_user_id=s.owner.user.id, impact_analysis=analysis, affected_bom_ids=[]
    )
    governance.decide_ecr(
        **context, actor_user_id=s.peer.user.id, outcome="approved", note="具名独立批准本次明确范围"
    )
    return {**value, "ecr": ecr, "item_key": key, "scope": version, "route": route}


def assignment(s: SupplyPostgresScope, value: dict[str, Any]) -> tasks.BatchDraft:
    state = tasks.read(s.engine, context=s.owner, project_id=s.project, ecr_id=value["ecr"])
    stage = UUID(state["stages"][0]["id"])
    return tasks.BatchDraft.model_validate(
        dict(
            request_id=uuid4(),
            scope_version_id=value["scope"]["id"],
            expected_digest=state["digest"],
            reason="具名承接已获批协同范围",
            assignments=[
                dict(
                    item_key=value["item_key"],
                    completion_criteria="提交实际实施文件并独立核对",
                    new_task=dict(
                        title="议价实施文件核对",
                        stage_id=stage,
                        assignee_user_id=s.engineer.user.id,
                        due_date=s.now.date(),
                        expected_output="实际实施文件及明确覆盖范围",
                        description="仅执行已批准范围，真实效益另验",
                    ),
                )
            ],
        )
    )


def assigned(s: SupplyPostgresScope, value: dict[str, Any]) -> dict[str, Any]:
    command = assignment(s, value)
    receipt = tasks.save(
        s.engine, context=s.owner, project_id=s.project, ecr_id=value["ecr"], draft=command
    )
    assert (
        tasks.save(
            s.engine, context=s.owner, project_id=s.project, ecr_id=value["ecr"], draft=command
        )["batch"]["id"]
        == receipt["batch"]["id"]
    )
    return {**value, "binding": UUID(receipt["bindings"][0]["id"])}


def pending(s: SupplyPostgresScope, value: dict[str, Any]) -> dict[str, Any]:
    document = s.document_for(s.project, "实际议价实施回应.pdf")
    with s.engine.connect() as c:
        actual = scope.source(c, s.owner.tenant.id, s.project, "document", document)
    state = results.read(
        s.engine, context=s.engineer, project_id=s.project, binding_id=value["binding"]
    )
    command = results.ResultDraft.model_validate(
        dict(
            request_id=uuid4(),
            expected_digest=state["digest"],
            outcome="ready_for_confirmation",
            reviewer_user_id=s.peer.user.id,
            completed_scope="实际文件协同范围已回应",
            excluded_scope="品质复测、认证、ERP生效及真实降本未覆盖",
            criteria_response="文件与获批报价范围对应",
            follow_up="后续按原流程核对品质、ERP与实际成本",
            reason="合成实施文件回写",
            references=[
                dict(
                    kind="document",
                    id=document,
                    expected_digest=digest(actual),
                    role="verification",
                    correspondence="实际回应文件对应本报价协同实施范围",
                )
            ],
        )
    )
    saved = results.save(
        s.engine,
        context=s.engineer,
        project_id=s.project,
        binding_id=value["binding"],
        draft=command,
    )
    assert (
        results.save(
            s.engine,
            context=s.engineer,
            project_id=s.project,
            binding_id=value["binding"],
            draft=command,
        )["id"]
        == saved["id"]
    )
    return {**value, "result": UUID(saved["id"]), "result_draft": command}


def confirmation(s: SupplyPostgresScope, value: dict[str, Any]) -> results.ConfirmDraft:
    state = results.read(
        s.engine, context=s.peer, project_id=s.project, binding_id=value["binding"]
    )
    return results.ConfirmDraft(
        request_id=uuid4(),
        expected_digest=state["history"][0]["review_digest"],
        outcome="verified",
        note="独立核对实际文件、明确覆盖与排除范围",
    )


def confirm(s: SupplyPostgresScope, value: dict[str, Any], command: results.ConfirmDraft) -> Any:
    return results.confirm(
        s.engine,
        context=s.peer,
        project_id=s.project,
        binding_id=value["binding"],
        result_id=value["result"],
        draft=command,
    )


def read(s: SupplyPostgresScope, value: dict[str, Any]) -> dict[str, Any]:
    return overview.read(s.engine, context=s.owner, project_id=s.project, ecr_id=value["ecr"])


def mutate(s: SupplyPostgresScope, value: dict[str, Any], change: str) -> None:
    if change in {"revision", "withdrawn"}:
        draft = value["draft"].model_copy(
            update=dict(
                previous_id=UUID(value["alternative"]["id"]),
                reason="来源变更须重新核对",
                status="withdrawn" if change == "withdrawn" else "proposed",
                scope="已修订报价适用范围",
            )
        )
        service = CostAlternativeService(s.engine)
        prepared = service.preview(s.owner, s.project, draft)
        service.save(
            s.owner,
            s.project,
            AlternativeSave(
                draft=draft,
                request_id=uuid4(),
                expected_digest=prepared["digest"],
                checked=True,
            ),
        )
    elif change == "proposal_price":
        save_input(
            s,
            UUID(value["proposal_price"]["record_id"]),
            PriceDraft.model_validate({**value["proposal_price"]["payload"], "amount": "4"}),
        )
    elif change == "proposal_document":
        with s.engine.begin() as c:
            c.execute(
                update(tables.documents)
                .where(tables.documents.c.id == s.document)
                .values(sha256="a" * 64)
            )
    else:
        raise AssertionError(change)


def counts(s: SupplyPostgresScope) -> tuple[int, ...]:
    with s.engine.connect() as c:
        return tuple(
            c.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == s.owner.tenant.id)
            ).scalar_one()
            for table in (
                tables.tasks,
                tables.change_execution_batches,
                tables.change_execution_results,
                tables.change_execution_confirmations,
                tables.events,
                tables.audit_log,
            )
        )


def test_named_cost_route_execution_and_independent_confirmation(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = approved(s)
    assert not read(s, value)["all_required_verified"]
    value = assigned(s, value)
    assert read(s, value)["items"][0]["status"] == "no_result"
    value = pending(s, value)
    assert read(s, value)["items"][0]["status"] == "awaiting_confirmation"
    before = counts(s)
    with pytest.raises(ObjectPermissionDeniedError):
        results.confirm(
            s.engine,
            context=s.engineer,
            project_id=s.project,
            binding_id=value["binding"],
            result_id=value["result"],
            draft=confirmation(s, value),
        )
    assert counts(s) == before
    command = confirmation(s, value)
    receipt = confirm(s, value, command)
    after = counts(s)
    assert confirm(s, value, command)["id"] == receipt["id"]
    assert counts(s) == after
    current = read(s, value)
    assert current["all_required_verified"] and not current["scope_gaps"]
    assert current["items"][0]["status"] == "verified"
    assert current["items"][0]["result_scope"]["excluded_scope"]
    assert value["alternative"]["snapshot"]["comparison"]["values"]["unit"]["delta"] == "-2.000000"
    assert value["alternative"]["snapshot"]["comparison"]["values"]["nre"]["delta"] is None
    assert (
        IssueService(s.engine)
        .get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
        .status
        == "verification"
    )


@pytest.mark.parametrize("change", ["revision", "withdrawn", "proposal_price", "proposal_document"])
def test_cost_source_changes_block_new_assignments(
    cost_scope: SupplyPostgresScope, change: str
) -> None:
    s = cost_scope
    value = approved(s)
    old = assignment(s, value)
    mutate(s, value, change)
    before = counts(s)
    assert any(
        item["blocking"] and item["kind"] == "cost_alternative"
        for item in read(s, value)["source_changes"]
    )
    for command in (old, assignment(s, value)):
        with pytest.raises(ProductWorkError, match="来源仍有效"):
            tasks.save(
                s.engine, context=s.owner, project_id=s.project, ecr_id=value["ecr"], draft=command
            )
    assert counts(s) == before


@pytest.mark.parametrize("change", ["revision", "withdrawn", "proposal_price"])
def test_cost_source_changes_revoke_current_verification(
    cost_scope: SupplyPostgresScope, change: str
) -> None:
    s = cost_scope
    value = pending(s, assigned(s, approved(s)))
    receipt = confirm(s, value, confirmation(s, value))
    assert read(s, value)["all_required_verified"]
    mutate(s, value, change)
    before = counts(s)
    state = read(s, value)
    assert not state["all_required_verified"] and state["scope_gaps"]
    assert state["items"][0]["status"] == "evidence_gaps"
    assert (
        state["items"][0]["confirmation"]["outcome"] == "verified"
    )  # Preserve actual historical receipt.
    current = results.read(
        s.engine, context=s.peer, project_id=s.project, binding_id=value["binding"]
    )
    assert not current["history"][0]["effective_verified"]
    assert current["history"][0]["confirmation"]["id"] == receipt["id"]
    command = value["result_draft"].model_copy(
        update=dict(request_id=uuid4(), expected_digest=current["digest"])
    )
    with pytest.raises(ProductWorkError, match="获批专业来源"):
        results.save(
            s.engine,
            context=s.engineer,
            project_id=s.project,
            binding_id=value["binding"],
            draft=command,
        )
    assert counts(s) == before


def test_pending_cost_confirmation_rejects_source_change_and_http_is_scoped(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = pending(s, assigned(s, approved(s)))
    stale = confirmation(s, value)
    mutate(s, value, "revision")
    before = counts(s)
    with pytest.raises(ProductWorkError, match="已有变化"):
        confirm(s, value, stale)
    with pytest.raises(ProductWorkError, match="获批专业来源"):
        confirm(s, value, confirmation(s, value))
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_engine] = lambda: s.engine
    try:
        with TestClient(app) as client:
            path = f"/api/projects/{s.project}/changes/ecrs/{value['ecr']}/execution-overview"
            response = client.get(path, headers=headers(s.owner))
            assert response.status_code == 200, response.text
            assert "no-store" in response.headers["cache-control"]
            assert not response.json()["all_required_verified"]
            assert client.get(path, headers=headers(s.foreign)).status_code in {403, 404}
            assert client.get(
                path.replace(str(s.project), str(s.other_project)), headers=headers(s.owner)
            ).status_code in {404, 409}
            assert client.get(path).status_code == 401
            result_path = (
                f"/api/projects/{s.project}/changes/execution-items/{value['binding']}/results"
            )
            result = client.get(result_path, headers=headers(s.peer))
            assert result.status_code == 200, result.text
            assert "no-store" in result.headers["cache-control"]
            body = confirmation(s, value).model_dump(mode="json")
            rejection = client.post(
                result_path + f"/{value['result']}/confirm", headers=headers(s.peer), json=body
            )
            assert rejection.status_code == 409, rejection.text
            assert "获批专业来源" in rejection.json()["detail"]["message"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
    assert counts(s) == before


def test_historical_baseline_changes_do_not_invalidate_current_proposal(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = pending(s, assigned(s, approved(s)))
    confirm(s, value, confirmation(s, value))
    save_input(
        s,
        UUID(value["original"]["record_id"]),
        PriceDraft.model_validate({**value["original"]["payload"], "amount": "4"}),
    )
    current = read(s, value)
    assert current["all_required_verified"]
    assert not current["source_changes"]
    assert value["alternative"]["snapshot"]["comparison"]["values"]["unit"]["delta"] == "-2.000000"
