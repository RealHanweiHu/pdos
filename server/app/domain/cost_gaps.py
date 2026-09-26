"""Actual Issue handling and deduplicated observations for a fixed cost-gap scope."""

from datetime import date
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select, true

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.cost_backtests import source_state
from app.domain.cost_freezes import row
from app.domain.cost_rollups import ALGORITHM as ROLLUP_ALGORITHM
from app.domain.issues import IssueDraft, IssueService
from app.domain.material_exceptions import _authorize
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_recovery_findings import review_context

ALGORITHM = "cost-gap.v1"


class GapDraft(Contract):
    rollup_id: UUID
    expected_calculation_digest: Digest
    subsystem: str = Field(min_length=1, max_length=128)
    basis: Literal["unit", "nre"]
    mode: Literal["create", "link"]
    issue_id: UUID | None = None
    title: str = Field(default="", max_length=512)
    owner_user_id: UUID | None = None
    verifier_user_id: UUID | None = None
    stage_id: UUID | None = None
    target_date: date | None = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    closure_criteria: str = Field(default="", max_length=2048)
    reason: Text

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.mode == "create":
            if self.issue_id or not all(
                (
                    self.title,
                    self.owner_user_id,
                    self.verifier_user_id,
                    self.target_date,
                    self.closure_criteria,
                )
            ):
                raise ValueError("创建Cost Gap问题须填写标题、负责人、验证人、日期及关闭判据")
        elif self.issue_id is None or any(
            (
                self.title,
                self.owner_user_id,
                self.verifier_user_id,
                self.stage_id,
                self.target_date,
                self.closure_criteria,
            )
        ):
            raise ValueError("关联已有问题只选择原问题并说明依据，不同时改写其责任或内容")
        return self


class GapSave(GapDraft):
    request_id: UUID
    expected_digest: Digest


class GapObservation(Contract):
    rollup_id: UUID
    expected_calculation_digest: Digest
    reason: Text


class GapObserve(GapObservation):
    request_id: UUID
    expected_digest: Digest


def metric(calculation: dict[str, Any], subsystem: str, bucket: str) -> dict[str, Any]:
    selected = next(
        (v for v in calculation["result"]["comparisons"] if v["subsystem"] == subsystem), None
    )
    comparison = selected[bucket] if selected else {"total": None, "target": None, "gap": None}
    inputs = {v["id"]: v["payload"] for v in calculation["snapshot"]["inputs"]}
    fees = []
    with localcontext() as ctx:
        ctx.prec = 38
        for line in calculation["result"]["lines"]:
            if line["basis"] != bucket or line["subsystem"] != subsystem:
                continue
            payload = inputs[line["input_id"]]
            fees.append(
                {
                    "bom_item_id": line["bom_item_id"],
                    "title": None if line["bom_item_id"] else line["title"],
                    "category": payload["category"],
                    "unit": line["unit"],
                    "quantity_per_product": str(Decimal(line["quantity_per_product"]).normalize()),
                    "scope_basis": payload["scope_basis"],
                }
            )
        command = calculation["command"]
        scope = {
            k: command[k]
            for k in (
                "bom_id",
                "stage",
                "currency",
                "tax_basis",
                "freight_basis",
                "product_unit",
                "scope_basis",
                "quantity_basis",
            )
        }
        scope.update(
            product_quantity=str(Decimal(command["product_quantity"]).normalize()),
            subsystem=subsystem,
            basis=bucket,
            target_input_id=comparison["target"]["input_id"] if comparison["target"] else None,
            fees=sorted(fees, key=digest),
        )
    return {
        "scope": scope,
        "scope_key": digest(scope),
        "comparison": comparison,
        "lines": [
            v
            for v in calculation["result"]["lines"]
            if v["subsystem"] == subsystem and v["basis"] == bucket
        ],
    }


def assess(
    case: Any, calculation: dict[str, Any], current: dict[str, Any], prior: Any = None
) -> dict[str, Any]:
    measured = metric(calculation, case["subsystem"], case["basis"])
    same = measured["scope_key"] == case["scope_key"]
    comparison = measured["comparison"]
    state = "needs_review"
    reasons = []
    prior_date = (
        prior["snapshot"]["calculation"]["command"]["as_of"]
        if prior
        else case["snapshot"]["calculation"]["command"]["as_of"]
    )
    if calculation["command"]["as_of"] < prior_date:
        reasons.append("计价时点早于已记录的同范围判断，仅作历史观察，不能据此判定当前恢复")
    if not same:
        reasons.append("原BOM/阶段、目标版本、费用构成、数量或币种税费口径已不同")
    if not current["current"]:
        reasons.append("至少一项原输入／原件已变化或尚不可核对")
    if comparison["gap"] is None:
        reasons.append("本子系统费用或目标存在缺口，不能推定恢复")
    if not reasons:
        state = "exceeded" if Decimal(comparison["gap"]) > 0 else "within_target"
    return {
        "algorithm": ALGORITHM,
        "same_scope": same,
        "metric": measured,
        "source_state": current,
        "state": state,
        "reasons": reasons,
    }


def latest(c: Connection, tenant: UUID, identity: UUID, valid_only: bool = False) -> Any:
    t = tables.cost_gap_observations
    return (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant,
                t.c.case_id == identity,
                t.c.state != "needs_review" if valid_only else true(),
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def append(
    c: Connection,
    context: AuthContext,
    case: Any,
    calculation: dict[str, Any],
    assessment: dict[str, Any],
    request: UUID,
    signature: str,
    reason: str,
    mode: str,
) -> dict[str, Any]:
    t = tables.cost_gap_observations
    old = latest(c, context.tenant.id, case["id"])
    value = {
        "algorithm": ALGORITHM,
        "calculation": calculation,
        "assessment": assessment,
        "case_scope": case["snapshot"]["metric"]["scope"],
        "reason": reason,
        "mode": mode,
        "previous_state": old["state"] if old else None,
        "state_changed": old is None or old["state"] != assessment["state"],
    }
    saved = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=case["project_id"],
                case_id=case["id"],
                rollup_id=UUID(calculation["id"]),
                version=(old["version"] if old else 0) + 1,
                state=assessment["state"],
                snapshot=value,
                created_by_user_id=context.user.id,
                request_id=request,
                request_digest=signature,
                created_at=func.clock_timestamp(),
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    NpiExecutionService._record_change(
        c,
        tenant_id=context.tenant.id,
        project_id=case["project_id"],
        actor_user_id=context.user.id,
        record_id=case["id"],
        record_type="cost_gap",
        action="observed",
        before=None,
        after={
            "observation_id": str(saved["id"]),
            "rollup_id": calculation["id"],
            "version": saved["version"],
            "state": saved["state"],
            "state_changed": value["state_changed"],
        },
    )
    return _plain(dict(saved))


def record_for_rollup(c: Connection, context: AuthContext, calculation: Any) -> None:
    """New calculations only continue explicitly registered scopes; never create/close Issues."""
    t = tables.cost_gap_cases
    cases = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == calculation["project_id"],
                t.c.bom_id == calculation["bom_id"],
                t.c.stage == calculation["command"]["stage"],
            )
        )
        .mappings()
        .all()
    )
    value = _plain(dict(calculation))
    for case in cases:
        measured = metric(value, case["subsystem"], case["basis"])
        if measured["scope_key"] != case["scope_key"]:
            continue
        current = {
            "current": all(
                v["current"] and v["source_current"] for v in value["snapshot"]["inputs"]
            ),
            "reason": "本次保存计算时的实际来源核对",
        }
        assessment = assess(case, value, current, latest(c, context.tenant.id, case["id"], True))
        o = tables.cost_gap_observations
        if c.execute(
            select(o.c.id).where(
                o.c.tenant_id == context.tenant.id,
                o.c.case_id == case["id"],
                o.c.rollup_id == calculation["id"],
            )
        ).first():
            continue
        request = uuid5(calculation["request_id"], f"cost-gap:{case['id']}")
        append(
            c,
            context,
            case,
            value,
            assessment,
            request,
            digest({"case": str(case["id"]), "rollup": value["id"]}),
            "同一已登记费用范围的新计算，沿原问题追踪；不自动关闭或重开问题",
            "calculation_saved",
        )


def creation_preview(
    c: Connection, context: AuthContext, project: UUID, command: GapDraft
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    calculation = row(c, context.tenant.id, project, tables.cost_rollups, command.rollup_id)
    if (
        calculation["algorithm"] != ROLLUP_ALGORITHM
        or calculation["calculation_digest"] != command.expected_calculation_digest
    ):
        raise ProductWorkError("请选择原算法下的指定计算版本")
    current = source_state(c, context.tenant.id, project, calculation)
    measured = metric(_plain(dict(calculation)), command.subsystem, command.basis)
    if (
        not current["current"]
        or measured["comparison"]["gap"] is None
        or Decimal(measured["comparison"]["gap"]) <= 0
    ):
        raise ProductWorkError("当前来源必须可核对且此项有明确正差额，才能登记超标问题")
    t = tables.cost_gap_cases
    existing = (
        c.execute(
            select(t.c.id, t.c.issue_id).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.scope_key == measured["scope_key"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        raise ProductWorkError(
            "同一目标版本和费用范围已有Cost Gap办理，请查看原问题；"
            "后续同口径重算自动沿用，避免重复建单"
        )
    issue = None
    selection = None
    if command.mode == "link":
        assert command.issue_id is not None
        issue = _plain(dict(row(c, context.tenant.id, project, tables.issues, command.issue_id)))
        if issue["status"] == "closed":
            raise ProductWorkError("原问题已关闭，请先沿原问题重新打开后关联")
    else:
        people = review_context(c, context.tenant.id, project)
        members = {v["id"]: v for v in people["members"]}
        stages = {v["id"]: v for v in people["stages"]}
        if (
            str(command.owner_user_id) not in members
            or str(command.verifier_user_id) not in members
        ):
            raise ProductWorkError("负责人和验证人须为当前实际项目成员")
        if (
            command.severity in ("high", "critical")
            and command.owner_user_id == command.verifier_user_id
        ):
            raise ProductWorkError("高／严重问题须指定不同的负责人和验证人")
        if command.stage_id and str(command.stage_id) not in stages:
            raise ProductWorkError("阶段不属于本项目")
        selection = {
            "owner": members[str(command.owner_user_id)],
            "verifier": members[str(command.verifier_user_id)],
            "stage": stages.get(str(command.stage_id)),
        }
    value = {
        "algorithm": ALGORITHM,
        "command": command.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
        "calculation": _plain(dict(calculation)),
        "metric": measured,
        "source_state": current,
        "existing_issue": issue,
        "selection": selection,
    }
    return {**value, "digest": digest(value)}


def observation_preview(
    c: Connection, context: AuthContext, project: UUID, identity: UUID, command: GapObservation
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    case = row(c, context.tenant.id, project, tables.cost_gap_cases, identity)
    calculation = row(c, context.tenant.id, project, tables.cost_rollups, command.rollup_id)
    if (
        calculation["algorithm"] != ROLLUP_ALGORITHM
        or calculation["calculation_digest"] != command.expected_calculation_digest
    ):
        raise ProductWorkError("请核对指定计算版本")
    o = tables.cost_gap_observations
    if c.execute(
        select(o.c.id).where(
            o.c.tenant_id == context.tenant.id,
            o.c.case_id == identity,
            o.c.rollup_id == command.rollup_id,
        )
    ).first():
        raise ProductWorkError(
            "此计算已有观察回执，请读取原记录；人工办理说明记录到原问题，不重复记账"
        )
    old = latest(c, context.tenant.id, identity)
    value = {
        "case_id": str(identity),
        "previous_id": str(old["id"]) if old else None,
        "calculation": _plain(dict(calculation)),
        "assessment": assess(
            case,
            _plain(dict(calculation)),
            source_state(c, context.tenant.id, project, calculation),
            latest(c, context.tenant.id, identity, True),
        ),
        "command": command.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
    }
    return {**value, "digest": digest(value)}


class CostGapService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, context: AuthContext, project: UUID, command: GapDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return creation_preview(c, context, project, command)

    def create(self, context: AuthContext, project: UUID, command: GapSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            _authorize(c, context, project, write=True)
            t = tables.cost_gap_cases
            signature = digest(command.model_dump(mode="json"))
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["project_id"] != project or old["request_digest"] != signature:
                    raise ProductWorkError("请求号已用于另一份Cost Gap")
                return _plain(dict(old))
            observed = creation_preview(c, context, project, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("计算、来源或办理对象已变化，请重新预览")
            issue = command.issue_id
            if command.mode == "create":
                comparison = observed["metric"]["comparison"]
                created = IssueService(self.engine).create(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project,
                    connection=c,
                    draft=IssueDraft(
                        stage_id=command.stage_id,
                        owner_user_id=command.owner_user_id,
                        verifier_user_id=command.verifier_user_id,
                        sample_id=None,
                        title=command.title,
                        description=(
                            f"Cost Gap：{command.subsystem} / {command.basis}\n"
                            f"计算版本：{command.rollup_id}\n"
                            f"目标：{comparison['target']['value']}；成本：{comparison['total']}；"
                            f"差额：{comparison['gap']} "
                            f"{observed['calculation']['command']['currency']}\n"
                            f"办理依据：{command.reason}\n"
                            "范围变化须重新核对，回到目标内不代替原问题验证与关闭。"
                        ),
                        issue_type="engineering",
                        severity=command.severity,
                        root_cause=None,
                        resolution=None,
                        closure_criteria=command.closure_criteria,
                        target_date=command.target_date,
                    ),
                )
                issue = created.id
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        rollup_id=command.rollup_id,
                        issue_id=issue,
                        bom_id=UUID(observed["calculation"]["bom_id"]),
                        stage=observed["calculation"]["command"]["stage"],
                        subsystem=command.subsystem,
                        basis=command.basis,
                        scope_key=observed["metric"]["scope_key"],
                        payload=command.model_dump(mode="json"),
                        snapshot=observed,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=func.clock_timestamp(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            assessment = assess(saved, observed["calculation"], observed["source_state"])
            append(
                c,
                context,
                saved,
                observed["calculation"],
                assessment,
                uuid5(command.request_id, "initial-observation"),
                signature,
                command.reason,
                "registered",
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=saved["id"],
                record_type="cost_gap",
                action="issue_linked",
                before=None,
                after={
                    "issue_id": str(issue),
                    "rollup_id": str(command.rollup_id),
                    "scope_key": saved["scope_key"],
                },
            )
            return _plain(dict(saved))

    def preview_observation(
        self, context: AuthContext, project: UUID, identity: UUID, command: GapObservation
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return observation_preview(c, context, project, identity, command)

    def observe(
        self, context: AuthContext, project: UUID, identity: UUID, command: GapObserve
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            _authorize(c, context, project, write=True)
            t = tables.cost_gap_observations
            signature = digest({"case": str(identity), "command": command.model_dump(mode="json")})
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["project_id"] != project or old["request_digest"] != signature:
                    raise ProductWorkError("请求号已用于不同观察")
                return _plain(dict(old))
            observed = observation_preview(c, context, project, identity, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("新观察或来源已变化，请重新预览")
            case = row(c, context.tenant.id, project, tables.cost_gap_cases, identity)
            return append(
                c,
                context,
                case,
                observed["calculation"],
                observed["assessment"],
                command.request_id,
                signature,
                command.reason,
                "manual_observation",
            )

    def get(
        self,
        context: AuthContext,
        project: UUID,
        identity: UUID | None = None,
        issue_id: UUID | None = None,
        before: UUID | None = None,
        observation_id: UUID | None = None,
        before_version: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            t = tables.cost_gap_cases
            o = tables.cost_gap_observations
            q = select(
                *(
                    list(t.c)
                    if identity
                    else [t.c.id, t.c.issue_id, t.c.subsystem, t.c.basis, t.c.stage, t.c.created_at]
                )
            ).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if identity:
                q = q.where(t.c.id == identity)
            if issue_id:
                q = q.where(t.c.issue_id == issue_id)
            if before:
                cursor = row(c, context.tenant.id, project, t, before)
                q = q.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            records = list(
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            values = []
            for record in records[:20]:
                value = _plain(dict(record))
                actual = row(c, context.tenant.id, project, tables.issues, record["issue_id"])
                value["issue"] = _plain(
                    {
                        k: actual[k]
                        for k in (
                            "id",
                            "title",
                            "status",
                            "severity",
                            "owner_user_id",
                            "verifier_user_id",
                            "target_date",
                            "updated_at",
                        )
                    }
                )
                last = latest(c, context.tenant.id, record["id"])
                value["latest"] = (
                    {
                        "id": str(last["id"]),
                        "version": last["version"],
                        "state": last["state"],
                        "rollup_id": str(last["rollup_id"]),
                        "created_at": last["created_at"].isoformat(),
                    }
                    if last
                    else None
                )
                if identity:
                    observations = select(
                        o.c.id, o.c.version, o.c.state, o.c.rollup_id, o.c.created_at
                    ).where(o.c.tenant_id == context.tenant.id, o.c.case_id == identity)
                    if before_version:
                        observations = observations.where(o.c.version < before_version)
                    history = list(
                        c.execute(observations.order_by(o.c.version.desc()).limit(21)).mappings()
                    )
                    value["observations"] = [_plain(dict(v)) for v in history[:20]]
                    value["next_version"] = history[19]["version"] if len(history) > 20 else None
                    selected = (
                        row(c, context.tenant.id, project, o, observation_id)
                        if observation_id
                        else last
                    )
                    if selected and selected["case_id"] != identity:
                        raise ProductWorkError("观察不属于此Cost Gap")
                    value["selected_observation"] = _plain(dict(selected)) if selected else None
                    if selected:
                        value["current_source"] = source_state(
                            c, context.tenant.id, project, selected["snapshot"]["calculation"]
                        )
                values.append(value)
            people = review_context(c, context.tenant.id, project)
            issues = select(
                tables.issues.c.id, tables.issues.c.title, tables.issues.c.status
            ).where(
                tables.issues.c.tenant_id == context.tenant.id,
                tables.issues.c.project_id == project,
                tables.issues.c.status != "closed",
            )
            if search:
                needle = (
                    "%"
                    + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    + "%"
                )
                issues = issues.where(tables.issues.c.title.ilike(needle, escape="\\"))
            candidates = list(
                c.execute(
                    issues.order_by(tables.issues.c.updated_at.desc(), tables.issues.c.id).limit(
                        201
                    )
                ).mappings()
            )
            return {
                "items": values,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
                "members": people["members"],
                "stages": people["stages"],
                "issues": [_plain(dict(v)) for v in candidates[:200]],
                "issues_more": len(candidates) > 200,
            }
