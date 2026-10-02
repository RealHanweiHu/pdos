"""Real recovery bridge; the coordinator alone executes these PostgreSQL cases.

Synthetic named baseline lineage is a fixture boundary, not approval workflow
validation. Material reviews/bindings and Forecast use real services and SQL
guards. No connections at import, migrations, cleanup or source/auth doubles.
"""

# ruff: noqa: F811 -- imported guarded fixture is intentionally used by name

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.contracts.common_objects import (
    ApprovalRef,
    NodeTime,
    PlanCandidate,
    PlanNode,
    ScopeRef,
    SourceRef,
    TimeRecord,
    TimeWindow,
)
from app.db.schema import tables
from app.domain.certification_execution import CertificationExecutionService, RecertificationDraft
from app.domain.formal_schedule import current_plan
from app.domain.material_allocations import MaterialAllocationError
from app.domain.material_exceptions import MaterialExceptionService
from app.domain.material_schedule import BindingDraft, MaterialScheduleService, conditions
from app.domain.product_workspace import _plain, digest
from app.domain.schedule_forecasts import ForecastDraft, ScheduleForecastService
from app.domain.schedule_nodes import NodeDraft, ScheduleNodeService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft, WrittenEventAudit
from tests.stage_plan_fixtures import seed_formal_task
from tests.test_material_recovery_postgres import (
    capture,
    exception,
    recovery_scope,  # noqa: F401 -- explicitly reuse coordinator assignment and target guards
    review_command,
)
from tests.test_parallel_supply_postgres import (
    BuildDemand,
    allocate,
    counts,
    freeze_demand,
    publish_calendar,
)
from tests.test_supplier_replies_postgres import SupplyPostgresScope


def initial_formal(s: SupplyPostgresScope) -> tuple[UUID, UUID]:
    """Use the existing historical initial-plan fixture with its actual origin."""
    with s.engine.begin() as c:
        assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
        case = c.execute(
            select(tables.projects.c.development_case_id).where(
                tables.projects.c.tenant_id == s.owner.tenant.id,
                tables.projects.c.id == s.project,
            )
        ).scalar_one()
        EventAuditWriter(
            c, tenant_id=s.owner.tenant.id, project_id=s.project, actor_user_id=s.owner.user.id
        ).record(
            EventDraft(
                event_id=f"material-bridge-fixture:{case}:converted",
                event_type="DEVELOPMENT_CASE_STATUS_CHANGED",
                source="development_case_service",
                entity_id=case,
                payload={"from_status": "approved", "to_status": "converted"},
            ),
            AuditDraft(
                action="development_case.transition",
                before_snapshot={"status": "approved"},
                after_snapshot={"status": "converted"},
            ),
        )
        seed_formal_task(c, s.owner.tenant.id, s.project, s.owner.user.id, s.peer.user.id)
        formal = current_plan(c, s.owner.tenant.id, s.project)
        assert formal is not None
        return formal["nodes"][0]["id"], formal["baseline_id"]


def certification_node(s: SupplyPostgresScope, certificate: UUID, calendar: UUID) -> UUID:
    service = ScheduleNodeService(s.engine)
    source = next(
        row for row in service.get(s.owner, s.project)["sources"] if row["id"] == str(certificate)
    )
    saved = service.register(
        s.owner,
        s.project,
        NodeDraft(
            request_id=uuid4(),
            node_kind="certification",
            source_id=certificate,
            expected_source_digest=source["source_digest"],
            calendar_version_id=calendar,
        ),
    )
    return UUID(saved["id"])


def replacement_node(s: SupplyPostgresScope, original: UUID) -> UUID:
    with s.engine.connect() as c:
        node = (
            c.execute(
                select(tables.schedule_nodes).where(
                    tables.schedule_nodes.c.tenant_id == s.owner.tenant.id,
                    tables.schedule_nodes.c.id == original,
                )
            )
            .mappings()
            .one()
        )
        source = (
            c.execute(
                select(tables.certifications).where(
                    tables.certifications.c.tenant_id == s.owner.tenant.id,
                    tables.certifications.c.id == node["certification_id"],
                )
            )
            .mappings()
            .one()
        )
    saved = CertificationExecutionService(s.engine).recertify(
        s.owner,
        s.project,
        source["id"],
        RecertificationDraft(
            request_id=uuid4(),
            expected_digest=digest(_plain(source)),
            reason="Named supported replacement of the original certification",
        ),
    )
    assert saved["replaces_certification_id"] == str(source["id"])
    return certification_node(s, UUID(saved["id"]), node["calendar_version_id"])


def replaced_formal(
    s: SupplyPostgresScope, root: UUID, node: UUID, previous_node: UUID | None = None
) -> UUID:
    """Append one complete named baseline fixture without deleting old history."""
    current, scenario, check, policy, change, decision, application = (uuid4() for _ in range(7))
    now = datetime.now(UTC) - timedelta(hours=1)
    with s.engine.begin() as c:
        formal = current_plan(c, s.owner.tenant.id, s.project)
        assert formal is not None and formal["baseline_id"] == root
        previous_version = formal["baseline_version"]
        keys = {row["id"]: row["node_key"] for row in formal["nodes"]}
        retained = [row for row in formal["nodes"] if row["id"] != previous_node]
        previous_plan = PlanCandidate.model_validate(formal["plan"])
        calendar = c.execute(
            select(tables.schedule_nodes.c.calendar_version_id).where(
                tables.schedule_nodes.c.tenant_id == s.owner.tenant.id,
                tables.schedule_nodes.c.id == node,
            )
        ).scalar_one()
        plan = PlanCandidate(
            id=scenario,
            tenant_id=s.owner.tenant.id,
            scope=ScopeRef(kind="project", ref_id=s.project),
            version=1,
            owner_user_id=s.owner.user.id,
            template_version="pg.material-bridge.fixture.v1",
            nodes=(
                *(
                    old
                    for old in previous_plan.nodes
                    if previous_node is None or old.node_key != keys[previous_node]
                ),
                PlanNode(
                    node_key="RECOVERY-TARGET",
                    title="Recovery target",
                    discipline="ME",
                    owner_user_id=s.peer.user.id,
                    receiver_user_id=s.owner.user.id,
                    expected_output="Synthetic execution evidence",
                    completion_criteria="Named evidence checked",
                    effort_hours=Decimal(1),
                    waiting_days=0,
                    estimate_basis="Named fixture estimate",
                ),
            ),
        )
        identities = {row["node_key"]: row["id"] for row in retained} | {"RECOVERY-TARGET": node}
        allocations = {
            key: {
                "calendar_key": formal["allocations"][key]["calendar_version_id"],
                "parallel_units": formal["allocations"][key]["parallel_units"],
                "allocation_basis": formal["allocations"][key]["allocation_basis"],
                "not_before": now.isoformat(),
            }
            for key in identities
            if key != "RECOVERY-TARGET"
        } | {
            "RECOVERY-TARGET": {
                "calendar_key": str(calendar),
                "parallel_units": "1",
                "allocation_basis": "Named fixture allocation",
                "not_before": now.isoformat(),
            }
        }
        replacements = (
            [{"previous_node_id": str(previous_node), "replacement_node_id": str(node)}]
            if previous_node
            else []
        )
        capacity = {
            "request_id": str(uuid4()),
            "demands": {},
            "no_resource_reasons": {key: "Synthetic no-resource fixture" for key in identities},
        }
        result = {
            "complete": True,
            "capacity_status": "not_checked",
            "applied": False,
            "nodes": [
                {
                    "node_key": key,
                    "node_id": str(identity),
                    "start": now.isoformat(),
                    "finish": (now + timedelta(hours=1)).isoformat(),
                    "allocation": allocations[key],
                }
                for key, identity in identities.items()
            ],
            "changes": {"certification_replacements": replacements},
        }
        capacity_result = {
            "status": "capacity_clear",
            "project_scenario_id": str(scenario),
            "baseline_changed": False,
            "profiles": [],
        }
        snapshot = {
            "baseline": {"id": str(root)},
            "plan": plan.model_dump(mode="json"),
            "capacity_inputs": capacity,
            "result": result,
            "policy": {"id": str(policy)},
            "capacity": capacity_result,
            "blockers": [],
        }
        payload = digest(snapshot)
        common = {"tenant_id": s.owner.tenant.id, "project_id": s.project}
        policy_version = (
            c.execute(
                select(tables.baseline_change_policies.c.version)
                .where(
                    tables.baseline_change_policies.c.tenant_id == s.owner.tenant.id,
                    tables.baseline_change_policies.c.project_id == s.project,
                )
                .order_by(tables.baseline_change_policies.c.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        ) + 1

        def insert(table: Any, **values: Any) -> None:
            c.execute(
                table.insert().values(
                    **common, request_id=uuid4(), request_digest=payload, **values
                )
            )

        insert(
            tables.project_schedule_scenarios,
            id=scenario,
            baseline_id=root,
            title="Named replacement fixture",
            reason="Synthetic boundary",
            inputs={"certification_replacements": replacements, "dependencies": []},
            snapshot=snapshot,
            basis_digest=payload,
            plan=snapshot["plan"],
            result=result,
            result_digest=payload,
            actor_user_id=s.owner.user.id,
        )
        for key, identity in identities.items():
            c.execute(
                tables.project_schedule_scenario_nodes.insert().values(
                    **common, scenario_id=scenario, node_id=identity, node_key=key
                )
            )
        insert(
            tables.project_scenario_capacity_checks,
            id=check,
            scenario_id=scenario,
            inputs=capacity,
            result=capacity_result,
            result_digest=payload,
            scenario_basis_digest=payload,
            created_by_user_id=s.owner.user.id,
        )
        insert(
            tables.baseline_change_policies,
            id=policy,
            version=policy_version,
            approver_user_id=s.peer.user.id,
            authority_basis="Named synthetic approval boundary",
            four_eyes=True,
            created_by_user_id=s.owner.user.id,
        )
        insert(
            tables.baseline_change_requests,
            id=change,
            scenario_id=scenario,
            capacity_check_id=check,
            policy_id=policy,
            base_baseline_id=root,
            reason="Named fixture replacement",
            snapshot=snapshot,
            payload_digest=payload,
            created_by_user_id=s.owner.user.id,
        )
        insert(
            tables.baseline_change_decisions,
            id=decision,
            change_id=change,
            action="approve",
            reason="Named fixture decision",
            actor_user_id=s.peer.user.id,
            approved_payload_digest=payload,
            created_at=now,
        )
        approval = ApprovalRef(
            approval_id=decision,
            payload_digest=payload,
            policy_version=f"baseline-policy:{policy}:{policy_version}",
            approved_by_user_id=s.peer.user.id,
            approved_at=now,
        )
        record = TimeRecord(
            id=current,
            tenant_id=s.owner.tenant.id,
            scope=plan.scope,
            version=previous_version + 1,
            owner_user_id=s.owner.user.id,
            time_kind="baseline",
            fact_kind="derived",
            approval=approval,
            algorithm_version="pg.material-bridge.fixture.v1",
            as_of=now,
            sources=(
                SourceRef(
                    tenant_id=s.owner.tenant.id,
                    project_id=s.project,
                    kind="project_schedule_scenario",
                    ref_id=scenario,
                    version=1,
                ),
            ),
            node_times=(
                *(
                    NodeTime(
                        node_id=identity,
                        window=TimeWindow(start=now, end=now + timedelta(hours=1)),
                    )
                    for identity in identities.values()
                ),
            ),
        )
        c.execute(
            tables.schedule_time_records.insert().values(
                **common,
                id=current,
                time_kind="baseline",
                version=previous_version + 1,
                contract=record.model_dump(mode="json"),
            )
        )
        for identity in identities.values():
            c.execute(
                tables.schedule_time_nodes.insert().values(
                    **common,
                    record_id=current,
                    node_id=identity,
                    start=now,
                    end=now + timedelta(hours=1),
                )
            )
        insert(
            tables.baseline_change_applications,
            id=application,
            change_id=change,
            decision_id=decision,
            baseline_id=current,
            previous_baseline_id=root,
            scenario_id=scenario,
            actor_user_id=s.owner.user.id,
            receipt={
                "id": str(application),
                "status": "applied",
                "baseline_id": str(current),
                "baseline_version": previous_version + 1,
                "previous_baseline_id": str(root),
                "change_id": str(change),
                "decision_id": str(decision),
                "actor_user_id": str(s.owner.user.id),
                "payload_digest": payload,
                "node_ids": [str(identity) for identity in identities.values()],
            },
        )
    return current


@dataclass
class BridgeCase:
    scope: SupplyPostgresScope
    demand: BuildDemand
    exception_id: UUID
    original_node: UUID
    root_baseline: UUID
    binding: dict[str, Any]

    def command(self, action: str, node: UUID) -> BindingDraft:
        detail = MaterialScheduleService(self.scope.engine).get(
            self.scope.owner, self.scope.project, self.exception_id
        )
        return BindingDraft(
            request_id=uuid4(),
            expected_version=detail["history"][0]["version"],
            review_id=UUID(detail["current"]["latest_review"]["id"]),
            source_digest=detail["current"]["source_digest"],
            mode="released" if action == "release" else "waiting",
            target_point="start",
            node_ids=[] if action == "release" else [node],
            reason="Named explicit recovery of original impact scope",
        )


def prepared(s: SupplyPostgresScope) -> BridgeCase:
    retained_task, initial_baseline = initial_formal(s)
    with s.engine.connect() as c:
        calendar = c.execute(
            select(tables.schedule_nodes.c.calendar_version_id).where(
                tables.schedule_nodes.c.tenant_id == s.owner.tenant.id,
                tables.schedule_nodes.c.id == retained_task,
            )
        ).scalar_one()
    certificate = s.insert(
        tables.certifications,
        project_id=s.project,
        owner_user_id=s.owner.user.id,
        created_by_user_id=s.owner.user.id,
        certificate_type="product_safety",
        certificate_number="SYNTHETIC-BRIDGE-CERT",
        status="valid",
        target_markets=["synthetic"],
        is_required=False,
        valid_from=(s.now - timedelta(days=30)).date(),
        valid_until=(s.now + timedelta(days=30)).date(),
    )
    original = certification_node(s, certificate, calendar)
    baseline = replaced_formal(s, initial_baseline, original)
    demand = freeze_demand(s, s.project, publish_calendar(s))
    source = capture(s, 4, 1)
    allocate(s, s.owner, demand, source, 4)
    identity, _ = exception(s, demand)
    service = MaterialScheduleService(s.engine)
    detail = service.get(s.owner, s.project, identity)
    binding = service.apply(
        s.owner,
        s.project,
        identity,
        BindingDraft(
            request_id=uuid4(),
            expected_version=0,
            review_id=UUID(detail["current"]["latest_review"]["id"]),
            source_digest=detail["current"]["source_digest"],
            mode="waiting",
            target_point="start",
            node_ids=[original],
            reason="Original shortage affects this explicit formal node",
        ),
    )
    restored = capture(s, 8, 2)
    allocate(s, s.owner, demand, restored, 4)
    MaterialExceptionService(s.engine).review(
        s.owner, s.project, identity, review_command(s, demand, identity, "supply_ready")
    )
    with s.engine.connect() as c:
        assert conditions(c, s.owner.tenant.id, s.project)[original][0]["status"] == "ready"
    return BridgeCase(s, demand, identity, original, baseline, binding)


def forecast(case: BridgeCase) -> dict[str, Any]:
    s = case.scope
    service = ScheduleForecastService(s.engine)
    detail = service.get(s.owner, s.project)
    return service.recalculate(
        s.owner,
        s.project,
        ForecastDraft(
            request_id=uuid4(),
            expected_basis_digest=detail["basis_digest"],
            reason="Check material recovery bridge with real Forecast",
        ),
    )


@pytest.mark.parametrize("action", ["rebind", "release"])
def test_ready_supply_cannot_erase_removed_node_before_explicit_current_action(
    recovery_scope: SupplyPostgresScope, action: str
) -> None:
    s = recovery_scope
    case = prepared(s)
    old_forecast = forecast(case)
    replacement = replacement_node(s, case.original_node)
    current_baseline = replaced_formal(s, case.root_baseline, replacement, case.original_node)
    with s.engine.connect() as c:
        values = conditions(c, s.owner.tenant.id, s.project)
    assert set(values) == {case.original_node} and replacement not in values
    condition = values[case.original_node][0]
    assert condition["status"] == "rebind_required"
    assert condition["bound_baseline_id"] == str(case.root_baseline)
    assert condition["current_baseline_id"] == str(current_baseline)
    detail = MaterialScheduleService(s.engine).get(s.owner, s.project, case.exception_id)
    assert detail["scope"]["missing_node_ids"] == [str(case.original_node)]
    assert detail["scope"]["reasons"] and detail["current"]["supply_ready"]
    history = ScheduleForecastService(s.engine).get(s.owner, s.project)
    old = next(v for v in history["items"] if v["record_id"] == old_forecast["record_id"])
    assert not old["basis_is_current"]
    blocked = forecast(case)
    assert not blocked["result"]["complete"]
    assert blocked["inputs"]["basis"]["unmapped_material_conditions"][0]["node_id"] == str(
        case.original_node
    )
    command = case.command(action, replacement)
    service = MaterialScheduleService(s.engine)
    saved = service.apply(s.owner, s.project, case.exception_id, command)
    before_replay = counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log)
    assert service.apply(s.owner, s.project, case.exception_id, command) == saved
    assert (
        counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log)
        == before_replay
    )
    with s.engine.connect() as c:
        values = conditions(c, s.owner.tenant.id, s.project)
    assert case.original_node not in values
    if action == "rebind":
        assert set(values) == {replacement} and values[replacement][0]["status"] == "ready"
    else:
        assert values == {}
    assert forecast(case)["result"]["complete"]
    detail = service.get(s.owner, s.project, case.exception_id)
    assert {item["id"] for item in detail["history"]} >= {case.binding["id"], saved["id"]}


@pytest.mark.parametrize("action", ["rebind", "release"])
def test_stale_recovery_review_cannot_rebind_or_release_and_new_review_recovers(
    recovery_scope: SupplyPostgresScope, action: str
) -> None:
    s = recovery_scope
    case = prepared(s)
    replacement = replacement_node(s, case.original_node)
    replaced_formal(s, case.root_baseline, replacement, case.original_node)
    old = case.command(action, replacement)
    capture(s, 8, 3, quality="frozen")
    before = counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log)
    service = MaterialScheduleService(s.engine)
    with pytest.raises(MaterialAllocationError, match="尚未具名核对或已变化"):
        service.apply(s.owner, s.project, case.exception_id, old)
    assert counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log) == before
    MaterialExceptionService(s.engine).review(
        s.owner,
        s.project,
        case.exception_id,
        review_command(s, case.demand, case.exception_id, "follow_up"),
    )
    saved = service.apply(s.owner, s.project, case.exception_id, case.command(action, replacement))
    assert saved["version"] == case.binding["version"] + 1
    with s.engine.connect() as c:
        values = conditions(c, s.owner.tenant.id, s.project)
    if action == "rebind":
        assert values[replacement][0]["status"] == "waiting"
    else:
        assert values == {}


def test_binding_audit_failure_preserves_original_scope_then_same_request_recovers(
    recovery_scope: SupplyPostgresScope, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = recovery_scope
    case = prepared(s)
    replacement = replacement_node(s, case.original_node)
    replaced_formal(s, case.root_baseline, replacement, case.original_node)
    command = case.command("rebind", replacement)
    before = counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log)
    original = EventAuditWriter.record

    def fail_after_real_audit(
        writer: EventAuditWriter, event: EventDraft, audit: AuditDraft
    ) -> WrittenEventAudit:
        result = original(writer, event, audit)
        if audit.action == "npi.material_schedule.revised":
            raise RuntimeError("Synthetic audit failure after actual SQL")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(EventAuditWriter, "record", fail_after_real_audit)
        with pytest.raises(RuntimeError, match="after actual SQL"):
            MaterialScheduleService(s.engine).apply(s.owner, s.project, case.exception_id, command)
    assert counts(s, tables.material_schedule_bindings, tables.events, tables.audit_log) == before
    with s.engine.connect() as c:
        assert (
            conditions(c, s.owner.tenant.id, s.project)[case.original_node][0]["status"]
            == "rebind_required"
        )
    saved = MaterialScheduleService(s.engine).apply(s.owner, s.project, case.exception_id, command)
    assert saved["version"] == case.binding["version"] + 1
