"""Immutable organization template revisions and explicit release/rollback receipts."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.process_template_approval_routes import ApprovalRehearsal, rehearse_approvals
from app.domain.process_template_configuration import (
    Input,
    RehearsalCase,
    TemplateConfiguration,
    configuration_difference,
    configure,
    rehearse,
)
from app.domain.process_template_field_rehearsal import (
    FieldRehearsal,
    field_examples,
    rehearse_fields,
)
from app.domain.process_template_gates import baseline
from app.domain.process_template_named_signers import SignerCase
from app.domain.process_template_named_signers import rehearse as rehearse_signers
from app.domain.process_template_reminder_rehearsal import (
    ReminderRehearsal,
    rehearse_reminders,
    reminder_examples,
)
from app.domain.process_template_reminders import ReminderPolicy
from app.domain.process_template_risk_field_rehearsal import (
    RiskFieldRehearsal,
    rehearse_risk_fields,
    risk_field_examples,
)
from app.domain.process_template_route_rehearsal import RouteRehearsal, rehearse_routes
from app.domain.process_template_task_field_rehearsal import (
    TaskFieldRehearsal,
    rehearse_task_fields,
    task_field_examples,
)
from app.domain.product_workspace import ProductWorkAccessError, _plain, digest
from app.domain.project_templates import ProjectTemplateError, catalog
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class TemplateRevisionInput(Input):
    request_id: UUID
    template_id: str = Field(pattern=r"^org-[a-z0-9][a-z0-9-]{0,119}$")
    base_template_id: str = Field(min_length=1, max_length=128)
    base_version: int = Field(gt=0)
    base_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_release_id: UUID | None = None
    source_brief_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=5000)
    configuration: TemplateConfiguration


class TemplatePreviewInput(Input):
    risk_field_cases: list[RiskFieldRehearsal] = Field(default_factory=list, max_length=100)
    signer_cases: list[SignerCase] = Field(default_factory=list, max_length=400)
    task_field_cases: list[TaskFieldRehearsal] = Field(default_factory=list, max_length=100)
    field_cases: list[FieldRehearsal] = Field(default_factory=list, max_length=100)
    approval_cases: list[ApprovalRehearsal] = Field(default_factory=list, max_length=100)
    routing_cases: list[RouteRehearsal] = Field(default_factory=list, max_length=20)
    reminder_cases: list[ReminderRehearsal] = Field(default_factory=list, max_length=20)
    cases: list[RehearsalCase] = Field(min_length=1, max_length=20)


class TemplateReleaseInput(TemplatePreviewInput):
    request_id: UUID
    expected_release_id: UUID | None = None
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["publish", "rollback"] = "publish"
    reason: str = Field(min_length=1, max_length=5000)
    confirmed: Literal[True]


def head(c: Connection, tenant: UUID, template: str) -> Any:
    t = tables.process_template_releases
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.template_id == template)
            .order_by(t.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def released_catalog(c: Connection, tenant: UUID) -> list[dict[str, Any]]:
    r, v = tables.process_template_releases, tables.process_template_revisions
    latest = (
        select(r.c.template_id, func.max(r.c.sequence).label("sequence"))
        .where(r.c.tenant_id == tenant)
        .group_by(r.c.template_id)
        .subquery()
    )
    return [
        dict(row)
        for row in c.execute(
            select(v.c.snapshot)
            .join(r, (r.c.tenant_id == v.c.tenant_id) & (r.c.revision_id == v.c.id))
            .join(
                latest,
                (latest.c.template_id == r.c.template_id) & (latest.c.sequence == r.c.sequence),
            )
            .where(v.c.tenant_id == tenant)
            .order_by(v.c.template_id)
        ).scalars()
    ]


def authorize(c: Connection, ctx: AuthContext) -> None:
    u, t = tables.users, tables.tenants
    role = c.execute(
        select(u.c.role)
        .join(t, t.c.id == u.c.tenant_id)
        .where(
            u.c.tenant_id == ctx.tenant.id,
            u.c.id == ctx.user.id,
            u.c.is_active.is_(True),
            t.c.status == "active",
        )
    ).scalar_one_or_none()
    if role is None or not is_allowed(Role(role), Action.USER_MANAGE):
        raise ProductWorkAccessError("仅组织治理负责人可管理和发布组织模板")


def lock(c: Connection, ctx: AuthContext, template: str) -> None:
    c.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"process-template:{ctx.tenant.id}:{template}"},
    )
    authorize(c, ctx)


def event(c: Connection, ctx: AuthContext, row: Any, action: str) -> None:
    revision_id = row["revision_id"] if "revision_id" in row else row["id"]
    EventAuditWriter(c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id).record(
        EventDraft(
            event_id=f"process-template:{row['id']}:{action}",
            event_type="PROCESS_TEMPLATE_CHANGED",
            source="process_template_service",
            entity_id=revision_id,
            payload={
                "template_id": row["template_id"],
                "revision_id": str(revision_id),
                "action": action,
            },
        ),
        AuditDraft(
            action=f"process_template.{action}",
            after_snapshot={
                "receipt_id": str(row["id"]),
                "revision_id": str(revision_id),
                "reason": row["reason"],
            },
        ),
    )


class ProcessTemplateService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def row(c: Connection, ctx: AuthContext, identity: UUID) -> Any:
        authorize(c, ctx)
        t = tables.process_template_revisions
        row = (
            c.execute(select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.id == identity))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProjectTemplateError("组织模板候选不存在")
        return row

    def overview(self, ctx: AuthContext) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx)
            t = tables.process_template_revisions
            revisions = c.execute(
                select(
                    t.c.id,
                    t.c.template_id,
                    t.c.version,
                    t.c.reason,
                    t.c.created_at,
                    t.c.created_by_user_id,
                )
                .where(t.c.tenant_id == ctx.tenant.id)
                .order_by(t.c.created_at.desc(), t.c.id.desc())
                .limit(100)
            ).mappings()
            return {
                "reminder_defaults": ReminderPolicy().model_dump(mode="json"),
                "catalog": [
                    item
                    | {
                        "source_digest": digest(item),
                        "gate_baseline": baseline(item),
                        "release_id": str(head(c, ctx.tenant.id, item["id"])["id"])
                        if item["id"].startswith("org-")
                        else None,
                    }
                    for item in catalog(connection=c, tenant_id=ctx.tenant.id)
                ],
                "revisions": [_plain(row) for row in revisions],
                "scope": "发布影响后续模板选择；在途项目、任务、测试计划和正式基线保留原版本。",
            }

    def get(self, ctx: AuthContext, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = self.row(c, ctx, identity)
            h = head(c, ctx.tenant.id, row["template_id"])
            r = tables.process_template_releases
            source_brief = None
            if row["source_brief_id"] is not None:
                from app.domain.process_template_briefs import brief

                source_brief = _plain(brief(c, ctx, row["source_brief_id"]))
            accepted_rehearsal = None
            if row["source_finding_id"] is not None:
                finding = tables.findings
                accepted = c.execute(
                    select(finding.c.accepted_payload).where(
                        finding.c.tenant_id == ctx.tenant.id,
                        finding.c.id == row["source_finding_id"],
                        finding.c.scope_kind == "tenant",
                        finding.c.finding_type == "process_template_configuration",
                        finding.c.applied_entity_id == row["id"],
                    )
                ).scalar_one_or_none()
                if accepted is not None:
                    assessment = accepted["assessment"]
                    accepted_rehearsal = {
                        key: assessment[key]
                        for key in (
                            "cases",
                            "routing_cases",
                            "reminder_cases",
                            "approval_cases",
                            "field_cases",
                            "task_field_cases",
                            "risk_field_cases",
                            "signer_cases",
                        )
                        if key in assessment
                    }
            return {
                "revision": _plain(row),
                "accepted_rehearsal": accepted_rehearsal,
                "gate_baseline": baseline(row["snapshot"]),
                "reminder_examples": reminder_examples(row["snapshot"]),
                "field_examples": field_examples(row["snapshot"]),
                "risk_field_examples": risk_field_examples(row["snapshot"]),
                "task_field_examples": task_field_examples(row["snapshot"]),
                "source_brief": source_brief,
                "current_release": _plain(h) if h else None,
                "releases": [
                    _plain(item)
                    for item in c.execute(
                        select(r)
                        .where(
                            r.c.tenant_id == ctx.tenant.id, r.c.template_id == row["template_id"]
                        )
                        .order_by(r.c.sequence.desc())
                        .limit(50)
                    ).mappings()
                ],
            }

    def create(
        self,
        ctx: AuthContext,
        body: TemplateRevisionInput,
        *,
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
    ) -> dict[str, Any]:
        omitted = {
            key
            for key in (
                "approval_routes",
                "issue_fields",
                "task_fields",
                "named_gate_slots",
                "risk_fields",
            )
            if getattr(body.configuration, key) is None
        }
        signature = digest(body.model_dump(mode="json", exclude={"configuration": omitted}))

        with nullcontext(connection) if connection is not None else self.engine.begin() as c:
            lock(c, ctx, body.template_id)
            v = tables.process_template_revisions
            prior = (
                c.execute(
                    select(v).where(
                        v.c.tenant_id == ctx.tenant.id, v.c.request_id == body.request_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if (
                    prior["request_digest"] != signature
                    or prior["source_finding_id"] != source_finding_id
                ):
                    raise ProjectTemplateError("此保存请求已对应另一份配置")
                return _plain(prior)
            h = head(c, ctx.tenant.id, body.template_id)
            if body.expected_release_id != (h["id"] if h else None):
                raise ProjectTemplateError("组织模板已发布新版本，请读取当前版本后继续")
            base = next(
                (
                    item
                    for item in catalog(connection=c, tenant_id=ctx.tenant.id)
                    if item["id"] == body.base_template_id and item["version"] == body.base_version
                ),
                None,
            )
            if base is None or digest(base) != body.base_digest:
                raise ProjectTemplateError("配置依据已变化，请重新读取模板")
            if h and body.base_template_id != body.template_id:
                raise ProjectTemplateError("修订须基于此组织模板当前发布版")
            if body.source_brief_id is not None:
                from app.domain.process_template_briefs import require_revision_source

                require_revision_source(
                    c,
                    ctx,
                    body.source_brief_id,
                    template_id=body.template_id,
                    base_template_id=body.base_template_id,
                    base_version=body.base_version,
                    base_digest=body.base_digest,
                    base_release_id=body.expected_release_id,
                )
            version = (
                c.execute(
                    select(func.coalesce(func.max(v.c.version), 0)).where(
                        v.c.tenant_id == ctx.tenant.id, v.c.template_id == body.template_id
                    )
                ).scalar_one()
                + 1
            )
            snapshot = configure(base, body.configuration, body.template_id, version)
            row = (
                c.execute(
                    v.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        template_id=body.template_id,
                        version=version,
                        request_id=body.request_id,
                        request_digest=signature,
                        base_template_id=body.base_template_id,
                        base_version=body.base_version,
                        base_digest=body.base_digest,
                        base_release_id=body.expected_release_id,
                        base_snapshot=base,
                        snapshot=snapshot,
                        digest=digest(snapshot),
                        configuration=body.configuration.model_dump(
                            mode="json",
                            exclude={
                                key
                                for key in ("task_fields", "named_gate_slots", "risk_fields")
                                if getattr(body.configuration, key) is None
                            },
                        ),
                        difference=configuration_difference(base, snapshot),
                        reason=body.reason,
                        source_brief_id=body.source_brief_id,
                        source_finding_id=source_finding_id,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(v)
                )
                .mappings()
                .one()
            )
            event(c, ctx, row, "prepared")
            return _plain(row)

    def preview(
        self,
        ctx: AuthContext,
        identity: UUID,
        cases: list[RehearsalCase],
        routing_cases: list[RouteRehearsal] | None = None,
        reminder_cases: list[ReminderRehearsal] | None = None,
        approval_cases: list[ApprovalRehearsal] | None = None,
        field_cases: list[FieldRehearsal] | None = None,
        task_field_cases: list[TaskFieldRehearsal] | None = None,
        signer_cases: list[SignerCase] | None = None,
        risk_field_cases: list[RiskFieldRehearsal] | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            return self._preview(
                c,
                ctx,
                self.row(c, ctx, identity),
                cases,
                routing_cases or [],
                reminder_cases or [],
                approval_cases or [],
                field_cases or [],
                task_field_cases or [],
                signer_cases or [],
                risk_field_cases or [],
            )

    @staticmethod
    def _preview(
        c: Connection,
        ctx: AuthContext,
        row: Any,
        cases: list[RehearsalCase],
        routing_cases: list[RouteRehearsal],
        reminder_cases: list[ReminderRehearsal],
        approval_cases: list[ApprovalRehearsal],
        field_cases: list[FieldRehearsal],
        task_field_cases: list[TaskFieldRehearsal],
        signer_cases: list[SignerCase],
        risk_field_cases: list[RiskFieldRehearsal],
    ) -> dict[str, Any]:
        h = head(c, ctx.tenant.id, row["template_id"])
        before = row["base_snapshot"]
        if h:
            before = c.execute(
                select(tables.process_template_revisions.c.snapshot).where(
                    tables.process_template_revisions.c.id == h["revision_id"],
                    tables.process_template_revisions.c.tenant_id == ctx.tenant.id,
                )
            ).scalar_one()
        v, p = tables.project_template_versions, tables.projects
        query = (
            select(
                p.c.id,
                p.c.code,
                p.c.name,
                p.c.status,
                v.c.revision,
                v.c.template_id,
                v.c.template_version,
                v.c.digest,
            )
            .join(v, (v.c.tenant_id == p.c.tenant_id) & (v.c.project_id == p.c.id))
            .where(
                p.c.tenant_id == ctx.tenant.id,
                v.c.status == "active",
                v.c.template_id.in_((row["template_id"], row["base_template_id"])),
            )
        )
        count = c.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        examples = [
            _plain(item)
            for item in c.execute(query.order_by(p.c.code, p.c.id).limit(50)).mappings()
        ]
        r = tables.process_template_releases
        released_before = (
            c.execute(
                select(r.c.id).where(r.c.tenant_id == ctx.tenant.id, r.c.revision_id == row["id"])
            ).first()
            is not None
        )
        source = next(
            (
                item
                for item in catalog(connection=c, tenant_id=ctx.tenant.id)
                if item["id"] == row["base_template_id"] and item["version"] == row["base_version"]
            ),
            None,
        )
        source_current = source is not None and digest(source) == row["base_digest"]
        rehearsal = rehearse(row["snapshot"], cases)
        routing_rehearsal = rehearse_routes(row["snapshot"], routing_cases)
        reminder_rehearsal = rehearse_reminders(row["snapshot"], reminder_cases)
        approval_rehearsal = rehearse_approvals(row["snapshot"], approval_cases)
        field_rehearsal = rehearse_fields(row["snapshot"], field_cases)
        task_field_rehearsal = rehearse_task_fields(row["snapshot"], task_field_cases)
        signer_rehearsal = rehearse_signers(row["snapshot"], signer_cases)
        risk_field_rehearsal = rehearse_risk_fields(row["snapshot"], risk_field_cases)
        extensions = row["configuration"].get("extension_requests", [])
        preview = {
            "revision_id": str(row["id"]),
            "revision_digest": row["digest"],
            "current_release_id": str(h["id"]) if h else None,
            "base_current": source_current,
            "released_before": released_before,
            "can_publish": source_current
            and not extensions
            and rehearsal["passed"]
            and field_rehearsal["passed"]
            and task_field_rehearsal["passed"]
            and signer_rehearsal["passed"]
            and risk_field_rehearsal["passed"]
            and approval_rehearsal["passed"]
            and reminder_rehearsal["passed"]
            and routing_rehearsal["passed"]
            and row["base_release_id"] == (h["id"] if h else None),
            "can_rollback": released_before
            and h is not None
            and h["revision_id"] != row["id"]
            and not extensions
            and rehearsal["passed"]
            and field_rehearsal["passed"]
            and task_field_rehearsal["passed"]
            and signer_rehearsal["passed"]
            and risk_field_rehearsal["passed"]
            and approval_rehearsal["passed"]
            and reminder_rehearsal["passed"]
            and routing_rehearsal["passed"],
            "pending_extensions": extensions,
            "rehearsal": rehearsal,
            "field_rehearsal": field_rehearsal,
            "field_cases": [case.model_dump(mode="json") for case in field_cases],
            "approval_rehearsal": approval_rehearsal,
            "approval_cases": [case.model_dump(mode="json") for case in approval_cases],
            "reminder_rehearsal": reminder_rehearsal,
            "reminder_cases": [case.model_dump(mode="json") for case in reminder_cases],
            "routing_rehearsal": routing_rehearsal,
            "routing_cases": [case.model_dump(mode="json") for case in routing_cases],
            "cases": [case.model_dump(mode="json") for case in cases],
            "project_count": count,
            "projects": examples,
            "projects_truncated": count > 50,
            "migration_policy": (
                "零自动迁移。上述项目仅展示当前采用情况；"
                "已有阶段/Gate签核要求/提醒规则/任务/测试计划/基线与原模板快照不改写，"
                "项目如需采用另行提出差异。"
            ),
            "difference": configuration_difference(before, row["snapshot"]),
        }
        if row["snapshot"].get("task_fields") or task_field_cases:
            preview["task_field_rehearsal"] = task_field_rehearsal
            preview["task_field_cases"] = [
                case.model_dump(mode="json") for case in task_field_cases
            ]
        if row["snapshot"].get("named_gate_slots") or signer_cases:
            preview["signer_rehearsal"] = signer_rehearsal
            preview["signer_cases"] = [case.model_dump(mode="json") for case in signer_cases]
        if row["snapshot"].get("risk_fields") or risk_field_cases:
            preview["risk_field_rehearsal"] = risk_field_rehearsal
            preview["risk_field_cases"] = [
                case.model_dump(mode="json") for case in risk_field_cases
            ]
        return preview | {"preview_digest": digest(preview)}

    def release(
        self, ctx: AuthContext, identity: UUID, body: TemplateReleaseInput
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = self.row(c, ctx, identity)
            lock(c, ctx, row["template_id"])
            t = tables.process_template_releases
            signature = digest(
                {
                    "revision": str(identity),
                    "body": body.model_dump(
                        mode="json",
                        exclude={
                            key
                            for key in (
                                "routing_cases",
                                "reminder_cases",
                                "approval_cases",
                                "field_cases",
                                "task_field_cases",
                                "signer_cases",
                                "risk_field_cases",
                            )
                            if not getattr(body, key)
                        },
                    ),
                }
            )
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id, t.c.request_id == body.request_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProjectTemplateError("此发布请求已对应另一份内容")
                return _plain(prior)
            h = head(c, ctx.tenant.id, row["template_id"])
            if body.expected_release_id != (h["id"] if h else None):
                raise ProjectTemplateError("发布版已变化，请重新预览后决定")
            preview = self._preview(
                c,
                ctx,
                row,
                body.cases,
                body.routing_cases,
                body.reminder_cases,
                body.approval_cases,
                body.field_cases,
                body.task_field_cases,
                body.signer_cases,
                body.risk_field_cases,
            )
            if preview["preview_digest"] != body.preview_digest:
                raise ProjectTemplateError("演练或影响范围已变化，请重新预览后决定")
            if not preview["can_publish" if body.action == "publish" else "can_rollback"]:
                raise ProjectTemplateError(
                    "候选依据、待决扩展或正反例演练尚不满足本次发布/回退条件"
                )
            release = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        template_id=row["template_id"],
                        revision_id=identity,
                        sequence=h["sequence"] + 1 if h else 1,
                        previous_release_id=body.expected_release_id,
                        request_id=body.request_id,
                        request_digest=signature,
                        action=body.action,
                        reason=body.reason,
                        preview=preview,
                        preview_digest=body.preview_digest,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, ctx, release, body.action)
            return _plain(release)
