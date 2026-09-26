"""Six evidence-scoped health measurements under explicit published policy."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.cost_backtests import source_state as cost_state
from app.domain.cost_definition_feedback import cost_access
from app.domain.document_previews import document_row, metadata
from app.domain.portfolio_health_policy import CATALOG, HealthPolicy, evaluate, latest
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.recertification_lineage import retired_certification_ids
from app.domain.resource_reservations import _project
from app.domain.schedule_forecasts import capture_basis
from app.domain.supplier_engineering import EngineeringDraft
from app.domain.supplier_engineering import sources as supplier_sources

LIMIT = 2000


class HealthRead(Contract):
    project_ids: list[UUID] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique(self) -> "HealthRead":
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("项目不可重复")
        return self


def bounded(c: Connection, query: Any) -> list[Any]:
    rows = list(c.execute(query.limit(LIMIT + 1)).mappings())
    if len(rows) > LIMIT:
        raise ProductWorkError("本维度来源超过2000项读取范围，未截断后假定健康；请沿原记录核对")
    return rows


def measure(value: Any, records: list[Any], missing: list[str], **extra: Any) -> dict[str, Any]:
    inputs = [_plain(r) for r in records]
    return {
        "value": str(value) if value is not None and not missing else None,
        "missing": missing,
        "source_count": len(inputs),
        "source_digest": digest(inputs),
        "sources": inputs,
        **extra,
    }


def schedule(
    c: Connection, context: AuthContext, project: UUID, now: datetime, policy: HealthPolicy | None
) -> dict[str, Any]:
    r = tables.schedule_time_records
    n = tables.schedule_time_nodes
    f = tables.schedule_forecast_runs
    baseline = (
        c.execute(
            select(r)
            .where(
                r.c.tenant_id == context.tenant.id,
                r.c.project_id == project,
                r.c.time_kind == "baseline",
            )
            .order_by(r.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    forecast = (
        c.execute(
            select(f, r.c.version)
            .join(
                r,
                (r.c.tenant_id == f.c.tenant_id)
                & (r.c.project_id == f.c.project_id)
                & (r.c.id == f.c.record_id),
            )
            .where(f.c.tenant_id == context.tenant.id, f.c.project_id == project)
            .order_by(r.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if baseline is None or forecast is None:
        return measure(None, [], ["尚无获批基线或已保存预测，不能用项目目标日代替"])
    base = list(
        c.execute(
            select(n).where(
                n.c.tenant_id == context.tenant.id,
                n.c.project_id == project,
                n.c.record_id == baseline["id"],
            )
        ).mappings()
    )
    missing = []
    if not base or any(v["end"] is None for v in base):
        missing.append("基线节点完工日期不完整")
    current = capture_basis(c, context.tenant.id, project)
    if forecast["basis_digest"] != current["basis_digest"]:
        missing.append("保存预测的来源已变化，须沿原排程重算")
    if not forecast["result"]["complete"] or forecast["result"].get("project_finish") is None:
        missing.append("预测含阻塞或未知日期")
    finish = (
        datetime.fromisoformat(forecast["result"]["project_finish"])
        if forecast["result"].get("project_finish")
        else None
    )
    baseline_finish = max((v["end"] for v in base if v["end"] is not None), default=None)
    as_of = datetime.fromisoformat(forecast["result"]["as_of"])
    if policy and not now - timedelta(hours=policy.max_forecast_age_hours) <= as_of <= now:
        missing.append("保存预测超出本健康政策允许账龄")
    delay = None
    if finish and baseline_finish:
        delta = finish - baseline_finish
        delay = max(
            Decimal(0),
            Decimal(delta.days)
            + Decimal(delta.seconds) / 86400
            + Decimal(delta.microseconds) / 86400000000,
        )
    return measure(
        delay,
        [
            {
                "baseline_id": baseline["id"],
                "baseline_version": baseline["version"],
                "baseline_finish": baseline_finish,
                "forecast_id": forecast["record_id"],
                "forecast_version": forecast["version"],
                "forecast_finish": finish,
                "basis_digest": forecast["basis_digest"],
                "as_of": as_of,
            }
        ],
        missing,
        baseline_finish=baseline_finish.isoformat() if baseline_finish else None,
        forecast_finish=finish.isoformat() if finish else None,
    )


def issues(c: Connection, context: AuthContext, project: UUID, quality: bool) -> dict[str, Any]:
    if quality:
        _role(context, Action.QUALITY_VIEW)
    t = tables.issues
    rows = bounded(
        c,
        select(
            t.c.id,
            t.c.title,
            t.c.issue_type,
            t.c.severity,
            t.c.status,
            t.c.target_date,
            t.c.updated_at,
        )
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.issue_type.in_(("quality", "test_failure") if quality else ("engineering",)),
        )
        .order_by(t.c.id),
    )
    severe = [v for v in rows if v["status"] != "closed" and v["severity"] in ("high", "critical")]
    return measure(
        len(severe),
        rows,
        [] if rows else ["本范围尚无实际Issue记录，不能据此推定无风险"],
        open_count=sum(v["status"] != "closed" for v in rows),
        severe_ids=[str(v["id"]) for v in severe],
    )


def cost(
    c: Connection, context: AuthContext, project: UUID, now: datetime, policy: HealthPolicy | None
) -> dict[str, Any]:
    cost_access(c, context, project)
    t = tables.cost_gap_observations
    newer = t.alias("newer_health_gap")
    rows = bounded(
        c,
        select(t)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            ~select(newer.c.id)
            .where(
                newer.c.tenant_id == t.c.tenant_id,
                newer.c.case_id == t.c.case_id,
                newer.c.version > t.c.version,
            )
            .correlate(t)
            .exists(),
        )
        .order_by(t.c.id),
    )
    missing = []
    checked = {}
    sources = []
    if not rows:
        missing.append("尚无具名Cost Gap观察，不能将未登记差额当零")
    for v in rows:
        if v["rollup_id"] not in checked:
            r = (
                c.execute(
                    select(tables.cost_rollups).where(
                        tables.cost_rollups.c.tenant_id == context.tenant.id,
                        tables.cost_rollups.c.project_id == project,
                        tables.cost_rollups.c.id == v["rollup_id"],
                    )
                )
                .mappings()
                .one()
            )
            current = cost_state(c, context.tenant.id, project, r)["current"]
            current = current and all(
                date.fromisoformat(e["payload"]["valid_from"])
                <= now.date()
                <= date.fromisoformat(e["payload"]["valid_until"])
                for e in r["snapshot"]["inputs"]
                if e["payload"].get("stage") == "quote"
            )
            if policy:
                current = (
                    current
                    and now.date() - timedelta(days=policy.max_cost_age_days)
                    <= date.fromisoformat(r["command"]["as_of"])
                    <= now.date()
                )
            checked[v["rollup_id"]] = current
        if v["state"] == "needs_review" or not checked[v["rollup_id"]]:
            missing.append("至少一项Cost Gap须重核来源、报价有效期或计价账龄")
        sources.append(
            {
                "id": v["id"],
                "case_id": v["case_id"],
                "version": v["version"],
                "state": v["state"],
                "rollup_id": v["rollup_id"],
                "source_current": checked[v["rollup_id"]],
                "snapshot_digest": digest(v["snapshot"]),
                "created_at": v["created_at"],
            }
        )
    return measure(
        sum(v["state"] == "exceeded" for v in rows), sources, list(dict.fromkeys(missing))
    )


def supplier(c: Connection, context: AuthContext, project: UUID) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project)
    t = tables.supplier_engineering_records
    newer = t.alias("newer_health_supplier")
    rows = bounded(
        c,
        select(t)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.kind == "sample_delivery",
            t.c.status == "active",
            ~select(newer.c.id)
            .where(
                newer.c.tenant_id == t.c.tenant_id,
                newer.c.project_id == t.c.project_id,
                newer.c.record_id == t.c.record_id,
                newer.c.version > t.c.version,
            )
            .correlate(t)
            .exists(),
        )
        .order_by(t.c.id),
    )
    missing = []
    late = 0
    compared = 0
    facts = []
    if not rows:
        missing.append("尚无有效样品交付事项")
    for v in rows:
        promise = v["snapshot"].get("first_promise")
        received = v["payload"].get("received")
        valid = digest(
            supplier_sources(
                c, context.tenant.id, project, EngineeringDraft.model_validate(v["payload"])
            )
        ) == digest(v["snapshot"]["sources"])
        if promise:
            valid = (
                valid
                and metadata(
                    document_row(c, context.tenant.id, project, UUID(promise["evidence_id"]))
                )
                == promise["document"]
            )
        if not valid:
            missing.append("至少一项样品原证据或业务来源已变化")
        if not promise or not received:
            missing.append("存在未具备首次承诺或实际收样的事项，比例不可评估")
        else:
            compared += 1
            late += datetime.fromisoformat(received["at"]) > datetime.fromisoformat(promise["at"])
        facts.append(
            {
                "id": v["id"],
                "record_id": v["record_id"],
                "supplier_id": v["supplier_id"],
                "version": v["version"],
                "first_promise": promise,
                "received": received,
                "source_current": valid,
            }
        )
    value = Decimal(late) * 100 / compared if compared else None
    return measure(value, facts, list(dict.fromkeys(missing)), late=late, comparable=compared)


def certification(
    c: Connection, context: AuthContext, project: UUID, now: datetime
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project)
    t = tables.certifications
    retired = retired_certification_ids(c, context.tenant.id, project)
    rows = bounded(
        c,
        select(t)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.is_required.is_(True),
            ~t.c.id.in_(retired),
        )
        .order_by(t.c.id),
    )
    missing = []
    bad = 0
    facts = []
    if not rows:
        missing.append("尚无当前必需认证记录；不推定无需认证或合规通过")
    for v in rows:
        current = (
            v["status"] == "valid"
            and v["valid_from"] is not None
            and v["valid_until"] is not None
            and v["valid_from"] <= now.date() <= v["valid_until"]
            and bool(v["evidence_reference"])
        )
        if v["status"] == "valid" and (
            v["valid_from"] is None or v["valid_until"] is None or not v["evidence_reference"]
        ):
            missing.append("有效状态的认证仍缺有效期或原证据")
        bad += not current
        facts.append(
            {
                k: v[k]
                for k in (
                    "id",
                    "certificate_type",
                    "certificate_number",
                    "target_markets",
                    "status",
                    "valid_from",
                    "valid_until",
                    "evidence_reference",
                    "updated_at",
                )
            }
        )
    return measure(
        bad, facts, list(dict.fromkeys(missing)), retired_ids=[str(v) for v in sorted(retired)]
    )


def project_health(
    c: Connection, context: AuthContext, actual: Any, now: datetime, policy: HealthPolicy | None
) -> dict[str, Any]:
    project = actual["id"]
    metrics = {}
    for key in CATALOG:
        try:
            if key == "schedule":
                m = schedule(c, context, project, now, policy)
            elif key in ("engineering", "quality"):
                m = issues(c, context, project, key == "quality")
            elif key == "cost":
                m = cost(c, context, project, now, policy)
            elif key == "supplier":
                m = supplier(c, context, project)
            else:
                m = certification(c, context, project, now)
        except (PermissionError, ObjectPermissionDeniedError):
            m = measure(None, [], ["当前没有本维度来源读取权限"])
        except (ValueError, LookupError) as error:
            m = measure(None, [], [str(error)])
        metrics[key] = m
    result = {
        "project_id": str(project),
        "name": actual["name"],
        "code": actual["code"],
        "project_status": actual["status"],
        "target_date": actual["target_date"].isoformat() if actual["target_date"] else None,
        **evaluate(metrics, policy),
    }
    return {**result, "evaluation_digest": digest(result)}


class PortfolioHealthService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: HealthRead) -> dict[str, Any]:
        _role(context, Action.PROJECT_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = latest(c, context.tenant.id)
            policy = HealthPolicy.model_validate(saved["body"]) if saved else None
            policy_missing = None
            if (
                not policy
                or policy.status != "active"
                or not policy.valid_from <= now < policy.valid_until
            ):
                policy = None
                policy_missing = "尚无当前有效健康政策，仅展示已读取指标，不判正常或补权重"
            items = []
            for project in command.project_ids:
                actual = _project(c, context, project)
                items.append(project_health(c, context, actual, now, policy))
            items.sort(
                key=lambda v: (
                    -v["alert_dimensions"],
                    -v["unknown_dimensions"],
                    Decimal(v["score"]) if v["score"] is not None else Decimal(0),
                    v["code"],
                )
            )
            result = {
                "as_of": now.isoformat(),
                "policy": _plain(saved) if saved else None,
                "policy_missing": policy_missing,
                "items": items,
                "scope": "selected_visible_projects; registered_sources_only",
                "missing_rule": "any_unknown_dimension_keeps_total_unknown",
            }
            return {**result, "payload_digest": digest(result)}
