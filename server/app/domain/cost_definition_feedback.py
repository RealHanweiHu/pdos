"""Cost observations returned to actual inherited definitions with named dispositions."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.ai.project_discussion_sources import linked_definitions
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.cost_alternatives import source_for_change
from app.domain.cost_backtests import source_state
from app.domain.cost_freezes import row
from app.domain.document_previews import document_row, metadata
from app.domain.material_exceptions import _authorize
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_definitions import _row as definition_row
from app.domain.product_definitions import definition_digest
from app.domain.product_strategies import _manager
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)

SourceKind = Literal["gap_observation", "cost_alternative", "cost_backtest"]
Topic = Literal[
    "target_cost", "scope_quality", "launch_window", "supplier", "nre", "price_position"
]


class FeedbackDraft(Contract):
    source_kind: SourceKind
    source_id: UUID
    definition_id: UUID
    topics: list[Topic] = Field(min_length=1, max_length=6)
    finding: Text
    proposed_response: Text
    limitations: Text

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len(set(self.topics)) != len(self.topics):
            raise ValueError("反馈主题不能重复")
        return self


class FeedbackSave(Contract):
    request_id: UUID
    expected_digest: Digest
    draft: FeedbackDraft
    checked: bool


class DispositionDraft(Contract):
    expected_decision_id: UUID | None = None
    action: Literal["needs_information", "no_change", "link_revision"]
    reason: Text
    revision_id: UUID | None = None
    response_by_topic: dict[Topic, Text]

    @model_validator(mode="after")
    def revision(self) -> Self:
        if (self.action == "link_revision") != (self.revision_id is not None):
            raise ValueError("关联定义修订须选择实际版本，其他处置不能同时关联版本")
        return self


class DispositionSave(Contract):
    request_id: UUID
    expected_digest: Digest
    draft: DispositionDraft
    checked: bool


def cost_access(c: Connection, context: AuthContext, project: UUID, write: bool = False) -> None:
    try:
        _authorize(c, context, project, write=write)
    except (ObjectPermissionDeniedError, PermissionError) as error:
        raise ProductWorkAccessError("需同时有权读取原项目成本和目标产品定义") from error


def definition(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> Any:
    _role(context, Action.PRODUCT_WORK_VIEW)
    return definition_row(c, context, space, identity)


def source(
    c: Connection, context: AuthContext, project: UUID, kind: SourceKind, identity: UUID
) -> dict[str, Any]:
    tenant = context.tenant.id
    if kind == "gap_observation":
        observed = row(c, tenant, project, tables.cost_gap_observations, identity)
        case = row(c, tenant, project, tables.cost_gap_cases, observed["case_id"])
        return {
            "kind": kind,
            "id": str(identity),
            "record": _plain(dict(observed)),
            "case": _plain(dict(case)),
            "title": "Cost Gap · " + case["subsystem"],
            "current": source_state(c, tenant, project, observed["snapshot"]["calculation"]),
        }
    if kind == "cost_alternative":
        basis = source_for_change(c, tenant, project, identity)
        return {
            "kind": kind,
            "id": str(identity),
            "record": basis["source"],
            "title": basis["source"]["title"],
            "current": {"current": basis["ready"]},
            "latest_id": basis["latest_id"],
            "references": basis["references"],
        }
    saved = row(c, tenant, project, tables.cost_backtests, identity)
    current = source_state(c, tenant, project, saved["snapshot"]["actual_calculation"])
    try:
        evidence_current = (
            metadata(document_row(c, tenant, project, saved["evidence_id"]))
            == saved["snapshot"]["evidence"]
        )
    except (ValueError, LookupError, PermissionError):
        evidence_current = False
    current = {
        **current,
        "evidence_current": evidence_current,
        "current": current["current"] and evidence_current,
    }
    return {
        "kind": kind,
        "id": str(identity),
        "record": _plain(dict(saved)),
        "title": saved["title"],
        "current": current,
    }


def last_decision(c: Connection, tenant: UUID, identity: UUID) -> Any:
    t = tables.cost_definition_dispositions
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.feedback_id == identity)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def feedback_preview(
    c: Connection, context: AuthContext, project: UUID, draft: FeedbackDraft
) -> dict[str, Any]:
    cost_access(c, context, project, write=True)
    candidates = linked_definitions(c, context, project, [draft.definition_id])
    if not candidates:
        raise ProductWorkAccessError("目标须为本项目实际需求继承且当前有权读取的已发布定义")
    target = candidates[0]
    original = source(c, context, project, draft.source_kind, draft.source_id)
    t = tables.cost_definition_feedback
    if c.execute(
        select(t.c.id).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.definition_id == draft.definition_id,
            t.c.source_kind == draft.source_kind,
            t.c.source_id == draft.source_id,
        )
    ).first():
        raise ProductWorkError("此来源版本已反馈给该定义，请沿原记录查看处置")
    result = {
        "command": draft.model_dump(mode="json"),
        "source": original,
        "definition": _plain(dict(target)),
        "definition_digest": definition_digest(target),
    }
    return {**result, "digest": digest(result)}


def disposition_preview(
    c: Connection, context: AuthContext, project: UUID, identity: UUID, draft: DispositionDraft
) -> dict[str, Any]:
    cost_access(c, context, project)
    feedback = row(c, context.tenant.id, project, tables.cost_definition_feedback, identity)
    target = definition(c, context, feedback["market_space_id"], feedback["definition_id"])
    if not _manager(c, context, target["market_space_id"], target["product_line_id"]):
        raise ProductWorkAccessError("请由此产品线当前有管理权限的产品经理处理定义反馈")
    previous = last_decision(c, context.tenant.id, identity)
    if (previous["id"] if previous else None) != draft.expected_decision_id:
        raise ProductWorkError("反馈已有新的处置，请刷新后继续")
    if set(draft.response_by_topic) != set(feedback["payload"]["draft"]["topics"]):
        raise ProductWorkError("请逐项回应本反馈的全部主题")
    revision = None
    if draft.revision_id:
        candidate = definition(c, context, target["market_space_id"], draft.revision_id)
        if (
            candidate["series_id"] != target["series_id"]
            or candidate["revision_number"] <= target["revision_number"]
        ):
            raise ProductWorkError("请选择同一定义系列的实际后续修订，不能以其他产品或原版代替")
        revision = _plain(dict(candidate))
    current = source(c, context, project, feedback["source_kind"], feedback["source_id"])
    result = {
        "command": draft.model_dump(mode="json"),
        "feedback_id": str(identity),
        "source_now": current,
        "target": _plain(dict(target)),
        "revision": revision,
        "original_feedback": feedback["snapshot"],
        "version": previous["version"] + 1 if previous else 1,
    }
    return {**result, "digest": digest(result)}


class CostDefinitionFeedbackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, context: AuthContext, project: UUID, draft: FeedbackDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return feedback_preview(c, context, project, draft)

    def save(self, context: AuthContext, project: UUID, command: FeedbackSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            cost_access(c, context, project, write=True)
            t = tables.cost_definition_feedback
            prior = self.replay(c, context, project, t, command)
            if prior:
                definition(c, context, UUID(prior["market_space_id"]), UUID(prior["definition_id"]))
                return prior
            if not command.checked:
                raise ProductWorkError("请核对成本原值、目标定义假设及本次反馈")
            observed = feedback_preview(c, context, project, command.draft)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("反馈来源或目标版本已变化，请重新预览")
            target = observed["definition"]
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        market_space_id=UUID(target["market_space_id"]),
                        definition_id=command.draft.definition_id,
                        source_kind=command.draft.source_kind,
                        source_id=command.draft.source_id,
                        payload=command.model_dump(mode="json"),
                        snapshot=observed,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=digest(command.model_dump(mode="json")),
                        created_at=func.clock_timestamp(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            self.record(c, context, project, saved, "cost_definition_feedback")
            return _plain(dict(saved))

    def preview_disposition(
        self, context: AuthContext, project: UUID, identity: UUID, draft: DispositionDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return disposition_preview(c, context, project, identity, draft)

    def decide(
        self, context: AuthContext, project: UUID, identity: UUID, command: DispositionSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            cost_access(c, context, project)
            feedback = row(c, context.tenant.id, project, tables.cost_definition_feedback, identity)
            target = definition(c, context, feedback["market_space_id"], feedback["definition_id"])
            if not _manager(c, context, target["market_space_id"], target["product_line_id"]):
                raise ProductWorkAccessError("当前没有目标产品线反馈处置权限")
            t = tables.cost_definition_dispositions
            prior = self.replay(c, context, project, t, command)
            if prior:
                if prior["feedback_id"] != str(identity):
                    raise ProductWorkError("请求已用于另一份反馈")
                return prior
            if not command.checked:
                raise ProductWorkError("请核对原反馈、当前来源及逐主题处置")
            observed = disposition_preview(c, context, project, identity, command.draft)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("来源、处置或修订正文已变化，请重新预览")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        feedback_id=identity,
                        market_space_id=feedback["market_space_id"],
                        revision_id=command.draft.revision_id,
                        action=command.draft.action,
                        version=observed["version"],
                        payload=command.model_dump(mode="json"),
                        snapshot=observed,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=digest(command.model_dump(mode="json")),
                        created_at=func.clock_timestamp(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            self.record(c, context, project, saved, "cost_definition_disposition")
            return _plain(dict(saved))

    @staticmethod
    def replay(
        c: Connection,
        context: AuthContext,
        project: UUID,
        t: Any,
        command: FeedbackSave | DispositionSave,
    ) -> dict[str, Any] | None:
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
            if prior["project_id"] != project or prior["request_digest"] != digest(
                command.model_dump(mode="json")
            ):
                raise ProductWorkError("同一请求已保存其他内容，请读取原回执")
            return _plain(dict(prior))
        return None

    @staticmethod
    def record(c: Connection, context: AuthContext, project: UUID, saved: Any, kind: str) -> None:
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project,
            actor_user_id=context.user.id,
            record_id=saved["id"],
            record_type=kind,
            action="recorded",
            before=None,
            after={"id": str(saved["id"]), "market_space_id": str(saved["market_space_id"])},
        )

    def get(
        self,
        context: AuthContext,
        *,
        project: UUID | None = None,
        space: UUID | None = None,
        definition_id: UUID | None = None,
        identity: UUID | None = None,
        source_kind: SourceKind | None = None,
        source_id: UUID | None = None,
        before: UUID | None = None,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            target = None
            if project:
                cost_access(c, context, project)
            elif space and definition_id:
                target = definition(c, context, space, definition_id)
            else:
                raise ProductWorkAccessError("请选择实际项目或产品定义范围")
            t = tables.cost_definition_feedback
            columns = (
                list(t.c)
                if identity
                else [
                    t.c.id,
                    t.c.project_id,
                    t.c.market_space_id,
                    t.c.definition_id,
                    t.c.source_kind,
                    t.c.source_id,
                    t.c.created_at,
                    t.c.payload["draft"]["finding"].as_string().label("finding"),
                ]
            )
            q = select(*columns).where(t.c.tenant_id == context.tenant.id)
            if project:
                q = q.where(t.c.project_id == project)
            if target is not None:
                d = tables.product_definitions
                q = q.where(
                    t.c.market_space_id == space,
                    t.c.definition_id.in_(
                        select(d.c.id).where(
                            d.c.tenant_id == context.tenant.id,
                            d.c.market_space_id == space,
                            d.c.series_id == target["series_id"],
                        )
                    ),
                )
            if identity:
                q = q.where(t.c.id == identity)
            if source_kind:
                q = q.where(t.c.source_kind == source_kind)
            if source_id:
                q = q.where(t.c.source_id == source_id)
            if before:
                cursor = c.execute(q.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("翻页位置不属于此反馈范围")
                q = q.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            records = list(
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            values = []
            for entry in records[:20]:
                try:
                    cost_access(c, context, entry["project_id"])
                    d = definition(c, context, entry["market_space_id"], entry["definition_id"])
                except ProductWorkAccessError:
                    if identity:
                        raise
                    continue
                value = _plain(dict(entry))
                last = last_decision(c, context.tenant.id, entry["id"])
                value["latest_decision"] = (
                    _plain(dict(last))
                    if last and identity
                    else (
                        {
                            "id": str(last["id"]),
                            "action": last["action"],
                            "version": last["version"],
                        }
                        if last
                        else None
                    )
                )
                value["definition_title"] = d["title"]
                if identity:
                    value["source_now"] = source(
                        c, context, entry["project_id"], entry["source_kind"], entry["source_id"]
                    )
                    value["can_decide"] = _manager(
                        c, context, d["market_space_id"], d["product_line_id"]
                    )
                    r = tables.product_definitions
                    revisions = (
                        c.execute(
                            select(r.c.id, r.c.title, r.c.revision_number, r.c.state, r.c.version)
                            .where(
                                r.c.tenant_id == context.tenant.id,
                                r.c.market_space_id == d["market_space_id"],
                                r.c.series_id == d["series_id"],
                                r.c.revision_number > d["revision_number"],
                            )
                            .order_by(r.c.revision_number.desc())
                            .limit(101)
                        )
                        .mappings()
                        .all()
                    )
                    value["revisions"] = [_plain(dict(v)) for v in revisions[:100]]
                    value["revisions_more"] = len(revisions) > 100
                    h = tables.cost_definition_dispositions
                    history = select(h).where(
                        h.c.tenant_id == context.tenant.id, h.c.feedback_id == entry["id"]
                    )
                    if before_version:
                        history = history.where(h.c.version < before_version)
                    decisions = list(
                        c.execute(history.order_by(h.c.version.desc()).limit(21)).mappings()
                    )
                    value["decisions"] = [_plain(dict(v)) for v in decisions[:20]]
                    value["next_version"] = (
                        decisions[19]["version"] if len(decisions) > 20 else None
                    )
                    if last and last["revision_id"]:
                        current_revision = definition(
                            c, context, entry["market_space_id"], last["revision_id"]
                        )
                        value["linked_revision_now"] = {
                            **_plain(dict(current_revision)),
                            "changed": definition_digest(current_revision)
                            != definition_digest(last["snapshot"]["revision"]),
                        }
                values.append(value)
            choices = linked_definitions(c, context, project) if project and not identity else []
            return {
                "items": values,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
                "definitions": [
                    {
                        "id": str(d["id"]),
                        "title": d["title"],
                        "revision_number": d["revision_number"],
                    }
                    for d in choices[:100]
                ],
                "definitions_more": len(choices) > 100,
            }
