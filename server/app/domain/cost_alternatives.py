"""Versioned cost alternatives, with explicit tradeoffs and original ECR routing."""

from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.cost_backtests import source_state
from app.domain.cost_freezes import row
from app.domain.cost_gaps import metric
from app.domain.document_previews import document_row, metadata
from app.domain.material_exceptions import _authorize
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest


class AlternativeDraft(Contract):
    case_id: UUID
    observation_id: UUID
    previous_id: UUID | None = None
    title: str = Field(min_length=1, max_length=256)
    status: Literal["proposed", "withdrawn"] = "proposed"
    scope: Text
    quality_impact: Text
    schedule_impact: Text
    supplier_impact: Text
    nre_impact: Text
    validation_requirements: Text
    unknowns: Text
    correspondence_basis: Text
    evidence_id: UUID
    evidence_location: Text
    proposal_rollup_id: UUID | None = None
    reason: Text


class AlternativeSave(Contract):
    request_id: UUID
    expected_digest: Digest
    draft: AlternativeDraft
    checked: bool


def latest(c: Connection, tenant: UUID, project: UUID, root: UUID) -> Any:
    t = tables.cost_alternatives
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.root_id == root)
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )


def comparison(baseline: Any, proposal: Any, subsystem: str) -> dict[str, Any]:
    gaps = []
    if proposal is None:
        gaps.append("未选择实际保存的备选估算／报价计算，预期金额未知")
    else:
        for key, label in (
            ("currency", "币种"),
            ("tax_basis", "税费"),
            ("freight_basis", "运费"),
            ("product_unit", "成品单位"),
        ):
            if baseline["command"][key] != proposal["command"][key]:
                gaps.append(f"{label}口径不同，不能直接相减")
        if Decimal(baseline["command"]["product_quantity"]) != Decimal(
            proposal["command"]["product_quantity"]
        ):
            gaps.append("产品数量不同，需先按同一数量重算")
    values = {}
    with localcontext() as ctx:
        ctx.prec = 38
        for bucket in ("unit", "nre"):
            left = metric(baseline, subsystem, bucket)["comparison"]
            right = metric(proposal, subsystem, bucket)["comparison"] if proposal else None
            missing = list(gaps)
            if left["total"] is None or right is None or right["total"] is None:
                missing.append("至少一边该类费用未完整记录，不补零")
            delta = (
                str(Decimal(right["total"]) - Decimal(left["total"]))
                if not missing and right
                else None
            )
            values[bucket] = {"baseline": left, "proposal": right, "delta": delta, "gaps": missing}
    return {
        "subsystem": subsystem,
        "currency": baseline["command"]["currency"],
        "values": values,
        "notice": (
            "差额＝备选－原计算；费用范围由具名对应依据说明，"
            "时点、汇率及构成变化均可能影响差额，不代表已实现降本。单位成本和NRE单列。"
        ),
    }


def preview(
    c: Connection, context: AuthContext, project: UUID, draft: AlternativeDraft
) -> dict[str, Any]:
    case = row(c, context.tenant.id, project, tables.cost_gap_cases, draft.case_id)
    observation = row(
        c, context.tenant.id, project, tables.cost_gap_observations, draft.observation_id
    )
    if observation["case_id"] != draft.case_id or observation["state"] == "needs_review":
        raise ProductWorkError("请选择此Cost Gap中范围有效的原观察作为方案依据")
    previous = None
    if draft.previous_id:
        previous = row(c, context.tenant.id, project, tables.cost_alternatives, draft.previous_id)
        if (
            previous["case_id"] != draft.case_id
            or latest(c, context.tenant.id, project, previous["root_id"])["id"] != previous["id"]
        ):
            raise ProductWorkError("方案已有新版或不属于此Cost Gap，请读取最新版本后修订")
    elif draft.status == "withdrawn":
        raise ProductWorkError("新方案不能直接撤回，请选择要撤回的原方案")
    proposal = None
    current = None
    if draft.proposal_rollup_id:
        proposal = _plain(
            dict(row(c, context.tenant.id, project, tables.cost_rollups, draft.proposal_rollup_id))
        )
        if proposal["command"]["stage"] not in {"estimate", "quote"}:
            raise ProductWorkError("备选预期费用请选择估算／报价计算；实际成本保留回测用途")
        current = source_state(c, context.tenant.id, project, proposal)
    baseline = observation["snapshot"]["calculation"]
    evidence = metadata(document_row(c, context.tenant.id, project, draft.evidence_id))
    issue = _plain(dict(row(c, context.tenant.id, project, tables.issues, case["issue_id"])))
    result = {
        "sources": [
            {"kind": "document", "id": str(draft.evidence_id), "expected_digest": digest(evidence)},
            {"kind": "issue", "id": str(case["issue_id"]), "expected_digest": digest(issue)},
        ],
        "issue_at_revision": issue,
        "algorithm": "cost-alternative.v1",
        "command": draft.model_dump(mode="json"),
        "title": draft.title,
        "scope": draft.scope,
        "case": _plain(dict(case)),
        "observation": _plain(dict(observation)),
        "baseline_calculation": baseline,
        "baseline_source": source_state(c, context.tenant.id, project, baseline),
        "proposal_calculation": proposal,
        "proposal_source": current,
        "evidence": evidence,
        "previous_id": str(previous["id"]) if previous else None,
        "revision_number": previous["revision_number"] + 1 if previous else 1,
        "comparison": comparison(baseline, proposal, case["subsystem"]),
    }
    return {**result, "digest": digest(result)}


def source_for_change(c: Connection, tenant: UUID, project: UUID, identity: UUID) -> dict[str, Any]:
    saved = row(c, tenant, project, tables.cost_alternatives, identity)
    newest = latest(c, tenant, project, saved["root_id"])
    snap = saved["snapshot"]
    try:
        evidence = metadata(document_row(c, tenant, project, saved["evidence_id"]))
    except (ValueError, LookupError, PermissionError):
        evidence = None
    references = [
        {
            "kind": "document",
            "id": str(saved["evidence_id"]),
            "current": evidence,
            "changed": evidence != snap["evidence"],
        }
    ]
    proposal = snap["proposal_calculation"]
    if proposal:
        state = source_state(c, tenant, project, proposal)
        references.append(
            {
                "kind": "cost_rollup",
                "id": proposal["id"],
                "current": state,
                "changed": not state["current"],
            }
        )
    return _plain(
        {
            "kind": "cost_alternative",
            "source": dict(saved),
            "root_id": saved["root_id"],
            "latest_id": newest["id"],
            "references": references,
            "ready": newest["id"] == identity
            and saved["status"] == "proposed"
            and not any(r["changed"] for r in references),
        }
    )


class CostAlternativeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self, context: AuthContext, project: UUID, draft: AlternativeDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project, write=True)
            return preview(c, context, project, draft)

    def save(self, context: AuthContext, project: UUID, command: AlternativeSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            return self.save_in_connection(c, context, project, command)

    @staticmethod
    def save_in_connection(
        c: Connection, context: AuthContext, project: UUID, command: AlternativeSave
    ) -> dict[str, Any]:
        NpiExecutionService._project(c, tenant_id=context.tenant.id, project_id=project, lock=True)
        _authorize(c, context, project, write=True)
        t = tables.cost_alternatives
        signature = digest(command.model_dump(mode="json"))
        prior = (
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
        if prior:
            if prior["project_id"] != project or prior["request_digest"] != signature:
                raise ProductWorkError("此请求已保存其他方案内容，请刷新原回执")
            return _plain(dict(prior))
        if not command.checked:
            raise ProductWorkError("请核对原费用范围、预期差额与质量／时间／供方代价")
        observed = preview(c, context, project, command.draft)
        if observed["digest"] != command.expected_digest:
            raise ProductWorkError("来源或方案版本已变化，请重新预览")
        d = command.draft
        identity = uuid4()
        previous = row(c, context.tenant.id, project, t, d.previous_id) if d.previous_id else None
        saved = (
            c.execute(
                t.insert()
                .values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    root_id=previous["root_id"] if previous else identity,
                    previous_id=d.previous_id,
                    case_id=d.case_id,
                    observation_id=d.observation_id,
                    proposal_rollup_id=d.proposal_rollup_id,
                    evidence_id=d.evidence_id,
                    revision_number=observed["revision_number"],
                    title=d.title,
                    status=d.status,
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
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project,
            actor_user_id=context.user.id,
            record_id=saved["id"],
            record_type="cost_alternative",
            action="revised" if previous else "recorded",
            before=None,
            after={
                "id": str(saved["id"]),
                "case_id": str(d.case_id),
                "title": d.title,
                "revision_number": saved["revision_number"],
                "status": d.status,
            },
        )
        return _plain(dict(saved))

    def get(
        self,
        context: AuthContext,
        project: UUID,
        case_id: UUID,
        identity: UUID | None = None,
        root_id: UUID | None = None,
        before: UUID | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            row(c, context.tenant.id, project, tables.cost_gap_cases, case_id)
            t = tables.cost_alternatives
            columns = (
                list(t.c)
                if identity
                else [
                    t.c.id,
                    t.c.root_id,
                    t.c.previous_id,
                    t.c.title,
                    t.c.status,
                    t.c.revision_number,
                    t.c.created_at,
                    t.c.snapshot["comparison"].label("comparison"),
                ]
            )
            q = select(*columns).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.case_id == case_id,
            )
            if identity:
                q = q.where(t.c.id == identity)
            elif root_id:
                q = q.where(t.c.root_id == root_id)
            else:
                newer = t.alias("newer")
                q = q.where(
                    ~select(newer.c.id)
                    .where(
                        newer.c.tenant_id == t.c.tenant_id,
                        newer.c.root_id == t.c.root_id,
                        newer.c.revision_number > t.c.revision_number,
                    )
                    .exists()
                )
            if before:
                cursor = row(c, context.tenant.id, project, t, before)
                if cursor["case_id"] != case_id or root_id and cursor["root_id"] != root_id:
                    raise ProductWorkError("翻页位置不属于此方案列表")
                q = q.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            records = list(
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            values = []
            for item in records[:20]:
                value = _plain(dict(item))
                if identity:
                    value["current_source"] = source_for_change(
                        c, context.tenant.id, project, item["id"]
                    )
                    application, origin_item = (
                        tables.cost_reduction_applications,
                        tables.cost_reduction_items,
                    )
                    origin = (
                        c.execute(
                            select(
                                application.c.finding_id,
                                application.c.id.label("application_id"),
                                origin_item.c.proposal_key,
                            )
                            .join(
                                origin_item,
                                (origin_item.c.tenant_id == application.c.tenant_id)
                                & (origin_item.c.project_id == application.c.project_id)
                                & (origin_item.c.application_id == application.c.id),
                            )
                            .where(
                                origin_item.c.tenant_id == context.tenant.id,
                                origin_item.c.project_id == project,
                                origin_item.c.alternative_id == item["root_id"],
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    value["suggestion_origin"] = _plain(dict(origin)) if origin else None
                    value["baseline_source_now"] = source_state(
                        c, context.tenant.id, project, item["snapshot"]["baseline_calculation"]
                    )
                values.append(value)
            doc = tables.documents
            dq = select(doc.c.id, doc.c.filename).where(
                doc.c.tenant_id == context.tenant.id, doc.c.project_id == project
            )
            if search:
                dq = dq.where(doc.c.filename.icontains(search, autoescape=True))
            docs = list(
                c.execute(
                    dq.order_by(doc.c.created_at.desc(), doc.c.id.desc()).limit(201)
                ).mappings()
            )
            return {
                "items": values,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
                "documents": [_plain(dict(d)) for d in docs[:200]],
                "documents_more": len(docs) > 200,
            }
