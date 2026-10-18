"""Project activity is a read projection of domain facts and their actual common receipts."""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, literal, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased
from sqlalchemy.types import NullType

from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.database import require_context
from pdos_next.domain.work_management.owner import project as readable_project
from pdos_next.errors import DomainError
from pdos_next.models import Outbox, Principal, Receipt
from pdos_next.project_activity_catalog import OPERATION_LABELS, SOURCES
from pdos_next.service import EVENTS

VERSION = "project-activity/v1"
RUN_EVENTS = {
    "accepted": "小Pai 工作已受理",
    "needs_input": "小Pai 工作等待本人答复",
    "model_unavailable": "小Pai 模型服务暂不可用",
    "reconciliation_required": "小Pai 原调用结果待核对",
    "run_reconciled": "小Pai 原调用已核对",
    "finished": "小Pai 工作已记录结果",
    "run_state": "小Pai 工作状态已记录",
}
RUN_STATES = {"queued", "running", "waiting_input", "completed", "partial", "cancelled", "failed"}
LINK_LABELS = {
    "plan": "打开工作与计划",
    "build": "打开配置与准备",
    "start": "打开开工条件",
    "execution": "打开实际产出",
    "supply": "打开物料齐套",
    "cost": "打开成本",
    "verification": "打开验证准备",
    "professional": "打开请求与方法",
    "handoff": "打开交样与接收",
    "launch": "打开承诺与开测",
    "results": "打开结果与处置",
    "quality": "打开问题与变更",
}


def _invalid(message="请刷新项目动态后继续分页。", *, forbidden=False):
    raise DomainError(
        "FORBIDDEN_SCOPE" if forbidden else "INVALID_PAYLOAD", message, 403 if forbidden else 422
    )


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _invalid()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _invalid()
    return value.astimezone(UTC)


def _scope(ctx, product_id, project_id):
    return list(
        map(str, (ctx.tenant_id, ctx.requester_id, ctx.category_id, product_id, project_id))
    )


def _decode(cursor, scope, now):
    if cursor is None:
        return now, None
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
        _invalid()
    try:
        value = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(value, dict) or set(value) != {"v", "scope", "as_of", "before"}:
            _invalid()
        if value["v"] != VERSION or value["scope"] != scope:
            _invalid(forbidden=True)
        watermark = _aware(value["as_of"])
        before = value["before"]
        if not isinstance(before, list) or len(before) != 2:
            _invalid()
        anchor = (_aware(before[0]), UUID(before[1]))
        if watermark > now or watermark < anchor[0]:
            _invalid()
        return watermark, anchor
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
        _invalid()


def _cursor(scope, watermark, row):
    value = {
        "v": VERSION,
        "scope": scope,
        "as_of": watermark.isoformat(),
        "before": [row["recorded_at"].isoformat(), str(row["id"])],
    }
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def source_binding(source, tenant_id, category_id, product_id, project_id=None):
    """Only explicit catalog identities; indirect associations are fixed EXISTS reads."""
    model = source.model
    product = source.product_column if source.product_column is not None else model.product_id
    conditions = [
        model.tenant_id == tenant_id,
        model.category_id == category_id,
        product == product_id,
    ]
    if project_id is not None:
        if source.project_predicate is None:
            conditions.append(model.project_id == project_id)
        else:
            conditions.append(source.project_predicate(source, tenant_id, product_id, project_id))
    return conditions


def receipt_binding(source):
    model = source.model
    identity = source.subject_id if source.subject_id is not None else model.id
    revision = source.subject_revision if source.subject_revision is not None else model.revision
    conditions = [
        Receipt.tenant_id == model.tenant_id,
        Receipt.category_id == model.category_id,
        Receipt.subject_type == source.subject_kind,
        Receipt.subject_id == identity,
        Receipt.operation.in_(source.operations),
    ]
    # G0 has an actual receipt_id and a receipt-owned revision, not a Decision revision.
    if not isinstance(revision.type, NullType):
        conditions.append(Receipt.subject_revision == revision)
    if hasattr(model, "receipt_id"):
        conditions.append(Receipt.id == model.receipt_id)
    else:
        conditions.append(Receipt.product_id == model.product_id)
    if hasattr(model, "actor_id"):
        conditions.append(Receipt.actor_id == model.actor_id)
    if hasattr(model, "operation"):
        conditions.append(Receipt.operation == model.operation)
    return conditions


def activity_records(ctx, product_id, project_id):
    """Never select whole documents, command bodies, source bodies or Run conversations."""
    branches = []
    for source in SOURCES:
        actor, requester = aliased(Principal), aliased(Principal)
        columns = source.columns

        def expression(key, type_, columns=columns):
            return cast(columns[key], type_) if key in columns else cast(literal(None), type_)

        expected_event = case(*[(Receipt.operation == op, EVENTS[op]) for op in source.operations])
        branch = (
            select(
                Outbox.id.label("id"),
                Receipt.created_at.label("recorded_at"),
                Receipt.id.label("receipt_id"),
                Receipt.operation.label("operation"),
                Outbox.type.label("event_type"),
                Receipt.subject_type.label("subject_kind"),
                Receipt.subject_id.label("subject_id"),
                Receipt.subject_revision.label("subject_revision"),
                Receipt.actor_id.label("actor_id"),
                actor.name.label("actor_name"),
                actor.kind.label("actor_kind"),
                Receipt.requester_id.label("requester_id"),
                requester.name.label("requester_name"),
                Receipt.agent_run_id.label("run_id"),
                expression("title", String).label("title"),
                expression("summary", String).label("summary"),
                expression("next_steps", String).label("next_steps"),
                expression("occurred_at", String).label("occurred_at"),
                expression("original_timezone", String).label("original_timezone"),
                expression("sources", JSONB).label("sources"),
                expression("task_refs", JSONB).label("task_refs"),
                literal(source.view).label("view"),
                literal(source.label).label("link_label"),
                literal("domain_receipt").label("record_kind"),
                cast(literal(None), String).label("status"),
            )
            .select_from(source.model)
            .join(Receipt, and_(*receipt_binding(source)))
            .join(
                Outbox,
                and_(
                    Outbox.tenant_id == Receipt.tenant_id,
                    Outbox.category_id == Receipt.category_id,
                    Outbox.receipt_id == Receipt.id,
                    Outbox.subject_id == Receipt.subject_id,
                    Outbox.subject_revision == Receipt.subject_revision,
                    Outbox.actor_id == Receipt.actor_id,
                    Outbox.schema_version == 1,
                    Outbox.type == expected_event,
                    Outbox.correlation_id
                    == func.coalesce(Receipt.agent_run_id, Receipt.run_id, Receipt.command_id),
                ),
            )
            .outerjoin(
                actor, and_(actor.tenant_id == Receipt.tenant_id, actor.id == Receipt.actor_id)
            )
            .outerjoin(
                requester,
                and_(
                    requester.tenant_id == Receipt.tenant_id, requester.id == Receipt.requester_id
                ),
            )
            .where(*source_binding(source, ctx.tenant_id, ctx.category_id, product_id, project_id))
        )
        branches.append(branch)
    # Existing requester-private Run/Event RLS remains in force. An explicit
    # project link grants no new audience and never exposes goal/result/body.
    actor, requester = aliased(Principal), aliased(Principal)
    kind = AgentEvent.body["type"].astext
    actor_id = AgentRun.writer_id  # Bound execution identity, not an invented event author.
    branches.append(
        select(
            AgentEvent.id,
            AgentEvent.created_at.label("recorded_at"),
            cast(literal(None), Receipt.id.type).label("receipt_id"),
            literal("agent.run.record").label("operation"),
            (literal("agent.run.") + kind).label("event_type"),
            literal("agent_run").label("subject_kind"),
            AgentRun.id.label("subject_id"),
            AgentEvent.sequence.label("subject_revision"),
            actor_id.label("actor_id"),
            actor.name.label("actor_name"),
            actor.kind.label("actor_kind"),
            AgentRun.requester_id,
            requester.name.label("requester_name"),
            AgentRun.id.label("run_id"),
            cast(literal(None), String).label("title"),
            case(*[(kind == key, value) for key, value in RUN_EVENTS.items()]).label("summary"),
            cast(literal(None), String).label("next_steps"),
            cast(AgentEvent.created_at, String).label("occurred_at"),
            cast(literal(None), String).label("original_timezone"),
            cast(literal(None), JSONB).label("sources"),
            cast(literal(None), JSONB).label("task_refs"),
            cast(literal(None), String).label("view"),
            cast(literal(None), String).label("link_label"),
            literal("run_event").label("record_kind"),
            case(
                (
                    AgentEvent.body["status"].astext.in_(RUN_STATES),
                    AgentEvent.body["status"].astext,
                ),
                else_=None,
            ).label("status"),
        )
        .select_from(AgentEvent)
        .join(
            AgentRun,
            and_(AgentRun.tenant_id == AgentEvent.tenant_id, AgentRun.id == AgentEvent.run_id),
        )
        .outerjoin(actor, and_(actor.tenant_id == AgentRun.tenant_id, actor.id == actor_id))
        .outerjoin(
            requester,
            and_(requester.tenant_id == AgentRun.tenant_id, requester.id == AgentRun.requester_id),
        )
        .where(
            AgentRun.tenant_id == ctx.tenant_id,
            AgentRun.category_id == ctx.category_id,
            AgentRun.product_id == product_id,
            AgentRun.project_id == project_id,
            AgentRun.requester_id == ctx.requester_id,
            kind.in_(RUN_EVENTS),
        )
    )
    return union_all(*branches).subquery("project_activity")


def _refs(value, *, tasks=False):
    """Expose only fixed reference metadata, even if a historical JSON contains more."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DomainError("INTEGRITY_MISMATCH", "项目动态的固定引用无法核对。")
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        identity, revision = item.get("id"), item.get("revision")
        try:
            identity = str(UUID(identity))
        except (ValueError, TypeError, AttributeError):
            continue
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            continue
        ref = {"id": identity, "revision": revision}
        if not tasks:
            if not isinstance(item.get("kind"), str):
                continue
            ref["kind"] = item["kind"]
            if isinstance(item.get("position"), str):
                ref["position"] = item["position"]
        if ref not in result:
            result.append(ref)
    return result


def activity_item(row):
    actual = row["occurred_at"]
    return {
        "id": str(row["id"]),
        "record_kind": row["record_kind"],
        "status": row["status"],
        "operation": row["operation"],
        "event_type": row["event_type"],
        "recorded_at": _aware(row["recorded_at"]).isoformat(),
        "occurred_at": _aware(actual).isoformat() if actual else None,
        "original_timezone": row["original_timezone"],
        "subject": {
            "kind": row["subject_kind"],
            "id": str(row["subject_id"]),
            "revision": row["subject_revision"],
            "title": row["title"],
        },
        "actor": {
            "id": str(row["actor_id"]),
            "name": row["actor_name"],
            "kind": {"human": "human", "agent": "ai"}.get(row["actor_kind"]),
        },
        "requester": {"id": str(row["requester_id"]), "name": row["requester_name"]},
        "summary": row["summary"] or OPERATION_LABELS[row["operation"]],
        "next_steps": row["next_steps"],
        "receipt_id": str(row["receipt_id"]) if row["receipt_id"] else None,
        "run_id": str(row["run_id"]) if row["run_id"] else None,
        "sources": _refs(row["sources"]),
        "task_refs": _refs(row["task_refs"], tasks=True),
        "link": {"view": row["view"], "label": LINK_LABELS[row["view"]]} if row["view"] else None,
    }


def project_activity(session, ctx, product_id, project_id, *, page_size=20, cursor=None):
    require_context(session, ctx)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        _invalid("每页请选择 1–100 条实际活动。")
    project = readable_project(session, ctx, product_id, project_id)
    scope = _scope(ctx, product_id, project_id)
    watermark, anchor = _decode(
        cursor, scope, _aware(session.scalar(select(func.transaction_timestamp())))
    )
    records = activity_records(ctx, product_id, project_id)
    query = select(records).where(records.c.recorded_at <= watermark)
    if anchor:
        if (
            session.execute(
                query.where(records.c.id == anchor[1], records.c.recorded_at == anchor[0])
            ).first()
            is None
        ):
            _invalid(forbidden=True)
        query = query.where(tuple_(records.c.recorded_at, records.c.id) < anchor)
    rows = (
        session.execute(
            query.order_by(records.c.recorded_at.desc(), records.c.id.desc()).limit(page_size + 1)
        )
        .mappings()
        .all()
    )
    page = rows[:page_size]
    receipt_ids = [row["receipt_id"] for row in rows if row["receipt_id"] is not None]
    if len(set(receipt_ids)) != len(receipt_ids):
        raise DomainError("INTEGRITY_MISMATCH", "项目动态的业务回执重复，请核对原记录。")
    return {
        "version": VERSION,
        "category_id": str(ctx.category_id),
        "product_id": str(product_id),
        "principal_id": str(ctx.requester_id),
        "project": {"id": str(project.id), "revision": project.revision, "name": project.name},
        "as_of": watermark.isoformat(),
        "items": [activity_item(row) for row in page],
        "next_cursor": _cursor(scope, watermark, page[-1]) if len(rows) > page_size else None,
    }
