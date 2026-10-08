"""Cost recovery, alternatives and canonical close on an assigned real PostgreSQL DB."""

import os
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from inspect import unwrap
from threading import Barrier
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.cost_alternatives import AlternativeDraft, AlternativeSave, CostAlternativeService
from app.domain.cost_gaps import CostGapService, GapDraft, GapSave
from app.domain.cost_inputs import CostInputService, InputApply, InputPreview, PriceDraft
from app.domain.cost_issue_closure import (
    CostClosureError,
    CostClosureReference,
    read_issue_cost_closure,
)
from app.domain.cost_rollups import CostRollupService, RollupDraft, RollupSave
from app.domain.issues import IssueService
from app.events.writer import EventAuditWriter
from app.main import app
from tests.test_material_issue_closure_api import headers
from tests.test_parallel_supply_postgres import seed_bom
from tests.test_supplier_replies_postgres import SupplyPostgresScope, isolated_postgres_url
from tests.test_supplier_replies_postgres import supply_postgres_scope as base_scope


@pytest.fixture
def cost_scope() -> Iterator[SupplyPostgresScope]:
    isolated_postgres_url()
    assert os.environ.get("PDOS_COST_RECOVERY_TEST_ISOLATED") == "1"
    generator = cast(Callable[[], Generator[SupplyPostgresScope, None, None]], unwrap(base_scope))()
    try:
        yield next(generator)
    finally:
        generator.close()


def price(s: SupplyPostgresScope, bom_item: UUID, amount: str, record: UUID | None = None) -> Any:
    record = record or uuid4()
    draft = PriceDraft(
        stage="estimate",
        title="原物料估算",
        subsystem="硬件",
        category="material",
        basis="unit",
        currency="CNY",
        amount=amount,
        unit="pcs",
        tax_basis="exclusive",
        freight_basis="included",
        scope_basis="原BOM材料",
        bom_item_id=bom_item,
        evidence_id=s.document,
        source_reference="material-estimate",
        source_line="line1",
        location="p1",
        as_of=s.now.date(),
        reason="合成成本凭证登记",
    )
    return save_input(s, record, draft)


def save_input(s: SupplyPostgresScope, record: UUID, draft: PriceDraft) -> Any:
    service = CostInputService(s.engine)
    prepared = service.preview(s.owner, s.project, record, InputPreview(draft=draft))
    return service.apply(
        s.owner,
        s.project,
        record,
        InputApply(
            draft=draft,
            request_id=uuid4(),
            expected_digest=prepared["digest"],
            expected_version=prepared["basis"]["previous_version"],
        ),
    )


def rollup(s: SupplyPostgresScope, bom: UUID, input_id: UUID, target: UUID) -> Any:
    service = CostRollupService(s.engine)
    draft = RollupDraft(
        bom_id=bom,
        title="合成同口径计算",
        stage="estimate",
        currency="CNY",
        as_of=s.now.date(),
        product_quantity="1",
        product_unit="台",
        tax_basis="exclusive",
        freight_basis="included",
        rate_type="budget",
        max_rate_age_days=30,
        nre_policy="separate",
        quantity_basis="一台，原BOM每台两个",
        scope_basis="原BOM材料",
        prices=[{"input_id": input_id}],
        target_ids=[target],
    )
    prepared = service.prepare(s.owner, s.project, draft)
    return service.save(
        s.owner,
        s.project,
        RollupSave(
            draft=draft,
            request_id=uuid4(),
            expected_digest=prepared["digest"],
        ),
    )


def setup_cost(s: SupplyPostgresScope) -> dict[str, Any]:
    bom, item = seed_bom(s, s.project, "cost")
    target = save_input(
        s,
        uuid4(),
        PriceDraft(
            stage="target",
            title="硬件单位成本目标",
            subsystem="硬件",
            category="material",
            basis="unit",
            currency="CNY",
            amount="5",
            unit="台",
            tax_basis="exclusive",
            freight_basis="included",
            scope_basis="原BOM材料",
            evidence_id=s.document,
            source_reference="cost-target",
            source_line="target1",
            location="p2",
            as_of=s.now.date(),
            reason="合成成本目标",
        ),
    )
    original = price(s, item, "3")
    calculation = rollup(s, bom, UUID(original["id"]), UUID(target["id"]))
    service = CostGapService(s.engine)
    draft = GapDraft(
        rollup_id=UUID(calculation["id"]),
        expected_calculation_digest=calculation["calculation_digest"],
        subsystem="硬件",
        basis="unit",
        mode="create",
        title="硬件成本超标",
        owner_user_id=s.owner.user.id,
        verifier_user_id=s.peer.user.id,
        target_date=s.now.date(),
        severity="high",
        closure_criteria="同口径成本回到目标并独立验证",
        reason="实际超标一元",
    )
    prepared = service.preview(s.owner, s.project, draft)
    case = service.create(
        s.owner,
        s.project,
        GapSave(
            **draft.model_dump(),
            request_id=uuid4(),
            expected_digest=prepared["digest"],
        ),
    )
    issue = UUID(case["issue_id"])
    issues = IssueService(s.engine)
    for status in ("analysis", "action", "verification"):
        issues.transition(
            tenant_id=s.owner.tenant.id,
            actor_user_id=s.owner.user.id,
            project_id=s.project,
            issue_id=issue,
            to_status=status,
        )
    return dict(bom=bom, item=item, target=target, original=original, case=case, issue=issue)


def restored(s: SupplyPostgresScope, value: dict[str, Any]) -> CostClosureReference:
    changed = price(s, value["item"], "2", UUID(value["original"]["record_id"]))
    rollup(s, value["bom"], UUID(changed["id"]), UUID(value["target"]["id"]))
    with s.engine.connect() as c:
        current = read_issue_cost_closure(c, s.peer, s.project, value["issue"])
    assert current["ready"]
    return CostClosureReference.model_validate(current["items"][0]["closure"]["reference"])


def close(
    s: SupplyPostgresScope, value: dict[str, Any], references: list[CostClosureReference]
) -> Any:
    service = IssueService(s.engine)
    issue = service.get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
    return service.transition(
        tenant_id=s.owner.tenant.id,
        actor_user_id=s.peer.user.id,
        project_id=s.project,
        issue_id=value["issue"],
        to_status="closed",
        expected_updated_at=issue.updated_at,
        closure_evidence_ref="具名独立验证原成本与工程实施证据",
        cost_closures=references,
    )


def footprint(s: SupplyPostgresScope) -> tuple[int, ...]:
    with s.engine.connect() as c:
        return tuple(
            c.execute(
                select(func.count()).select_from(t).where(t.c.tenant_id == s.owner.tenant.id)
            ).scalar_one()
            for t in (
                tables.cost_gap_cases,
                tables.cost_gap_observations,
                tables.events,
                tables.audit_log,
            )
        )


def test_recovery_keeps_issue_open_until_named_current_close(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    assert (
        IssueService(s.engine)
        .get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
        .status
        == "verification"
    )
    before = footprint(s)
    with pytest.raises(CostClosureError):
        close(s, value, [])
    assert footprint(s) == before
    result = close(s, value, [reference])
    assert result.status == "closed"
    with s.engine.connect() as c:
        audit = (
            c.execute(
                select(tables.audit_log)
                .where(
                    tables.audit_log.c.tenant_id == s.owner.tenant.id,
                    tables.audit_log.c.entity_id == value["issue"],
                )
                .order_by(tables.audit_log.c.id.desc())
            )
            .mappings()
            .first()
        )
        assert audit is not None
        assert audit["context"]["cost_closure"]["sources"][0]["observation_id"] == str(
            reference.observation_id
        )


@pytest.mark.parametrize("change", ["cost", "document", "target"])
def test_drift_prevents_close_without_partial_writes(
    cost_scope: SupplyPostgresScope, change: str
) -> None:
    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    if change == "document":
        with s.engine.begin() as c:
            c.execute(
                update(tables.documents)
                .where(
                    tables.documents.c.tenant_id == s.owner.tenant.id,
                    tables.documents.c.id == s.document,
                )
                .values(sha256="d" * 64)
            )
    elif change == "target":
        draft = PriceDraft.model_validate(
            {**value["target"]["payload"], "amount": "8", "reason": "新目标版本"}
        )
        save_input(s, UUID(value["target"]["record_id"]), draft)
    else:
        changed = price(s, value["item"], "4", UUID(value["original"]["record_id"]))
        rollup(s, value["bom"], UUID(changed["id"]), UUID(value["target"]["id"]))
    before = footprint(s)
    with pytest.raises(CostClosureError):
        close(s, value, [reference])
    assert footprint(s) == before
    assert (
        IssueService(s.engine)
        .get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
        .status
        == "verification"
    )


def test_recovery_alternative_keeps_tradeoffs_and_replays_once(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = setup_cost(s)
    with s.engine.connect() as c:
        observation_id = c.execute(
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
                "reason": "独立登记备选估算原件，不覆盖原比较依据",
            }
        ),
    )
    proposed = rollup(s, value["bom"], UUID(proposed_price["id"]), UUID(value["target"]["id"]))
    draft = AlternativeDraft(
        case_id=UUID(value["case"]["id"]),
        observation_id=observation_id,
        title="同物料议价方案",
        scope="维持原结构与规格",
        quality_impact="仍须品质独立验证",
        schedule_impact="未取得交期承诺",
        supplier_impact="维持原供方",
        nre_impact="未登记NRE不补零",
        validation_requirements="按工程变更要求验证",
        unknowns="真实材料及执行效果待验",
        correspondence_basis="原BOM同口径",
        evidence_id=s.document,
        evidence_location="p3",
        proposal_rollup_id=UUID(proposed["id"]),
        reason="合成议价方案",
    )
    service = CostAlternativeService(s.engine)
    prepared = service.preview(s.owner, s.project, draft)
    comparison = prepared["comparison"]["values"]
    assert comparison["unit"]["baseline"]["total"] == "6.000000"
    assert comparison["unit"]["proposal"]["total"] == "4.000000"
    assert comparison["unit"]["delta"] == "-2.000000"
    assert comparison["nre"]["delta"] is None  # Unknown NRE is never zero savings.
    command = AlternativeSave(
        draft=draft, request_id=uuid4(), expected_digest=prepared["digest"], checked=True
    )
    saved = service.save(s.owner, s.project, command)
    before = footprint(s)
    assert service.save(s.owner, s.project, command)["id"] == saved["id"]
    assert footprint(s) == before
    assert saved["payload"]["draft"]["validation_requirements"] == draft.validation_requirements
    assert saved["snapshot"]["comparison"]["values"]["unit"]["delta"] == "-2.000000"
    assert IssueService(s.engine).get(
        tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"]
    ).status == "verification"


def test_close_fault_rolls_back_issue_event_and_audit(
    cost_scope: SupplyPostgresScope, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    before = footprint(s)
    original = EventAuditWriter.record

    def fail(self: Any, *args: Any, **kwargs: Any) -> Any:
        original(self, *args, **kwargs)
        raise RuntimeError("synthetic post-write fault")

    monkeypatch.setattr(EventAuditWriter, "record", fail)
    with pytest.raises(RuntimeError, match="post-write fault"):
        close(s, value, [reference])
    assert footprint(s) == before
    assert (
        IssueService(s.engine)
        .get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
        .status
        == "verification"
    )


def test_http_current_read_close_and_stale_reference(cost_scope: SupplyPostgresScope) -> None:
    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_engine] = lambda: s.engine
    try:
        with TestClient(app) as client:
            base = f"/api/projects/{s.project}/issues/{value['issue']}"
            card = client.get(base + "/work-card", headers=headers(s.peer))
            assert card.status_code == 200, card.text
            assert card.json()["cost_closure"]["ready"]
            body = dict(
                to_status="closed",
                expected_updated_at=card.json()["item"]["updated_at"],
                closure_evidence_ref="具名独立验证",
                cost_closures=[reference.model_dump(mode="json")],
            )
            invalid = {**body, "cost_closures": []}
            before = footprint(s)
            rejected = client.post(base + "/transitions", headers=headers(s.peer), json=invalid)
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"]["code"] == "ISSUE_COST_SOURCE_CHANGED"
            assert footprint(s) == before
            owner = client.post(base + "/transitions", headers=headers(s.owner), json=body)
            assert owner.status_code == 409, owner.text
            assert owner.json()["detail"]["code"] == "ISSUE_CLOSE_REQUIRES_VERIFIER"
            response = client.post(base + "/transitions", headers=headers(s.peer), json=body)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "closed"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_cost_recovery_feedback_reaches_actual_inherited_definition(
    cost_scope: SupplyPostgresScope, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_product_manager_loop_api import command
    from tests.test_product_planning_findings_api import post, setup_candidate

    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_engine] = lambda: s.engine
    # Only the helper's token supplier changes; real JWT/auth/ACL and SQL remain active.
    monkeypatch.setattr(
        "tests.test_product_discovery_findings_api.bearer_headers", lambda client: headers(s.owner)
    )
    scope = SimpleNamespace(owner_id=s.owner.user.id, tenant_id=s.owner.tenant.id, engine=s.engine)
    try:
        with TestClient(app) as client:
            base, auth, definition, _ = setup_candidate(
                client, scope, tmp_path, monkeypatch, "product_definition", True, seed_only=True
            )
            with s.engine.connect() as c:
                requirement = c.execute(
                    select(tables.development_cases.c.requirement_id)
                    .join(
                        tables.projects,
                        tables.projects.c.development_case_id == tables.development_cases.c.id,
                    )
                    .where(tables.projects.c.id == s.project)
                ).scalar_one()
            package = post(
                client,
                base,
                auth,
                "/requirement-packages",
                {
                    "request_id": str(uuid4()),
                    "definition_id": definition["id"],
                    "candidates": [
                        {
                            "key": "pressure",
                            "item_keys": ["pressure"],
                            "mode": "reuse",
                            "requirement_id": str(requirement),
                            "acknowledge_differences": True,
                            "rationale": "合成已发布定义继承到原项目需求",
                        }
                    ],
                },
                201,
            )
            for action in ("accept", "apply"):
                package = post(
                    client,
                    base,
                    auth,
                    f"/requirement-packages/{package['id']}/actions",
                    {
                        **command(package),
                        "action": action,
                        "reviewed_proposal_digest": package["proposal_digest"],
                        "reason": "合成具名核对原需求关联",
                    },
                )
            cost_base = f"/api/projects/{s.project}/npi/cost-definition-feedback"
            draft = dict(
                source_kind="gap_observation",
                source_id=str(reference.observation_id),
                definition_id=definition["id"],
                topics=["target_cost", "scope_quality"],
                finding="同口径成本6→4，原目标5",
                proposed_response="保留原目标，实际工程验证独立办理",
                limitations="合成材料，不能宣称实际降本效果",
            )
            preview = client.post(cost_base + "/preview", headers=auth, json=draft)
            assert preview.status_code == 200, preview.text
            save = dict(
                draft=draft,
                request_id=str(uuid4()),
                expected_digest=preview.json()["digest"],
                checked=True,
            )
            result = client.post(cost_base, headers=auth, json=save)
            assert result.status_code == 200, result.text
            assert (
                client.post(cost_base, headers=auth, json=save).json()["id"] == result.json()["id"]
            )
            identity = result.json()["id"]
            decision = dict(
                action="no_change",
                reason="已核对原定义假设及验证要求",
                response_by_topic={
                    "target_cost": "原目标保留",
                    "scope_quality": "质量验证独立执行",
                },
            )
            ready = client.post(cost_base + f"/{identity}/preview", headers=auth, json=decision)
            assert ready.status_code == 200, ready.text
            saved = client.post(
                cost_base + f"/{identity}/decisions",
                headers=auth,
                json=dict(
                    draft=decision,
                    request_id=str(uuid4()),
                    expected_digest=ready.json()["digest"],
                    checked=True,
                ),
            )
            assert saved.status_code == 200, saved.text
            read = client.get(cost_base + f"?identity={identity}", headers=auth)
            assert read.status_code == 200, read.text
            assert read.json()["items"][0]["latest_decision"]["action"] == "no_change"
            assert read.json()["items"][0]["source_now"]["current"]["current"]
            assert (
                IssueService(s.engine)
                .get(tenant_id=s.owner.tenant.id, project_id=s.project, issue_id=value["issue"])
                .status
                == "verification"
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_concurrent_rollup_replay_appends_one_observation(cost_scope: SupplyPostgresScope) -> None:
    s = cost_scope
    value = setup_cost(s)
    restored(s, value)
    with s.engine.connect() as c:
        saved = (
            c.execute(
                select(tables.cost_rollups)
                .where(tables.cost_rollups.c.tenant_id == s.owner.tenant.id)
                .order_by(tables.cost_rollups.c.created_at.desc())
            )
            .mappings()
            .first()
        )
    assert saved is not None
    draft = RollupDraft.model_validate({**saved["command"], "title": "同一新请求并发重放"})
    service = CostRollupService(s.engine)
    preview = service.prepare(s.owner, s.project, draft)
    command = RollupSave(draft=draft, expected_digest=preview["digest"], request_id=uuid4())
    before = footprint(s)
    barrier = Barrier(2)

    def save() -> str:
        barrier.wait(timeout=5)
        return str(service.save(s.owner, s.project, command)["id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    assert footprint(s)[1] == before[1] + 1
    with s.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.cost_rollups)
                .where(tables.cost_rollups.c.request_id == command.request_id)
            ).scalar_one()
            == 1
        )


def test_foreign_or_duplicate_recovery_reference_is_rejected(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = setup_cost(s)
    reference = restored(s, value)
    before = footprint(s)
    for references in ([reference, reference], [reference.model_copy(update={"case_id": uuid4()})]):
        with pytest.raises(CostClosureError):
            close(s, value, references)
    assert footprint(s) == before


def test_every_cost_gap_linked_to_one_issue_requires_current_recovery(
    cost_scope: SupplyPostgresScope,
) -> None:
    s = cost_scope
    value = setup_cost(s)
    unit_reference = restored(s, value)
    nre_target = save_input(
        s,
        uuid4(),
        PriceDraft(
            stage="target",
            title="NRE预算",
            subsystem="硬件",
            category="tooling",
            basis="nre",
            currency="CNY",
            amount="10",
            unit="项",
            tax_basis="exclusive",
            freight_basis="included",
            scope_basis="合成工装",
            evidence_id=s.document,
            source_reference="nre-target",
            source_line="nre-target",
            location="p4",
            as_of=s.now.date(),
            reason="合成预算",
        ),
    )
    fee = save_input(
        s,
        uuid4(),
        PriceDraft(
            stage="estimate",
            title="NRE费用",
            subsystem="硬件",
            category="tooling",
            basis="nre",
            currency="CNY",
            amount="20",
            unit="项",
            tax_basis="exclusive",
            freight_basis="included",
            scope_basis="合成工装",
            evidence_id=s.document,
            source_reference="nre-cost",
            source_line="nre-cost",
            location="p5",
            as_of=s.now.date(),
            reason="合成工装费",
        ),
    )
    with s.engine.connect() as c:
        previous = c.execute(
            select(tables.cost_gap_observations.c.snapshot).where(
                tables.cost_gap_observations.c.id == unit_reference.observation_id
            )
        ).scalar_one()["calculation"]
    service = CostRollupService(s.engine)
    draft = RollupDraft.model_validate(
        {
            **previous["command"],
            "title": "单位成本与NRE单列",
            "prices": [*previous["command"]["prices"], {"input_id": fee["id"]}],
            "target_ids": [*previous["command"]["target_ids"], nre_target["id"]],
        }
    )
    prepared = service.prepare(s.owner, s.project, draft)
    saved = service.save(
        s.owner,
        s.project,
        RollupSave(draft=draft, expected_digest=prepared["digest"], request_id=uuid4()),
    )
    gaps = CostGapService(s.engine)
    command = GapDraft(
        rollup_id=UUID(saved["id"]),
        expected_calculation_digest=saved["calculation_digest"],
        subsystem="硬件",
        basis="nre",
        mode="link",
        issue_id=value["issue"],
        reason="同一问题的另一独立费用范围",
    )
    observed = gaps.preview(s.owner, s.project, command)
    gaps.create(
        s.owner,
        s.project,
        GapSave(**command.model_dump(), request_id=uuid4(), expected_digest=observed["digest"]),
    )
    with s.engine.connect() as c:
        context = read_issue_cost_closure(c, s.peer, s.project, value["issue"])
    assert len(context["items"]) == 2 and not context["ready"]
    current_unit = next(v for v in context["items"] if v["case_id"] == str(unit_reference.case_id))
    unit_reference = CostClosureReference.model_validate(current_unit["closure"]["reference"])
    before = footprint(s)
    with pytest.raises(CostClosureError):
        close(s, value, [unit_reference])
    assert footprint(s) == before
