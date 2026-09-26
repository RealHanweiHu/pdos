"""Event-triggered, durable retrieval of verified knowledge for a named employee."""

from contextlib import ExitStack
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, case, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from app.ai.embeddings import (
    EmbeddingError,
    EmbeddingGateway,
    EmbeddingResult,
    configured_embedding_gateway,
)
from app.db.schema import tables
from app.domain.knowledge_push import (
    ContextNotFoundError,
    KnowledgeAccessError,
    KnowledgePushService,
    KnowledgeVersionError,
    PushedMemory,
    authorize_knowledge_project,
    knowledge_scope,
)
from app.domain.memories import _record
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.settings import get_settings

TRIGGERS = frozenset(
    {
        "PROJECT_CREATED",
        "PROJECT_UPDATED",
        "SPECIFICATION_CREATED",
        "CHANGE_RECORD_CHANGED",
        "TASK_CREATED",
        "TASK_UPDATED",
    }
)


def observe(
    c: Connection,
    *,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    event_type: str,
    entity: UUID,
    payload: dict[str, Any],
    audit_id: int,
    occurred_at: datetime,
) -> None:
    kind = None
    recipient = actor
    if event_type in {"PROJECT_CREATED", "PROJECT_UPDATED"}:
        if event_type == "PROJECT_UPDATED" and not set(payload.get("changed_fields", [])) & {
            "name",
            "description",
            "owner_user_id",
        }:
            return
        kind = "project_kickoff"
        recipient = (
            c.execute(
                select(tables.projects.c.owner_user_id).where(
                    tables.projects.c.tenant_id == tenant,
                    tables.projects.c.id == project,
                )
            ).scalar_one_or_none()
            or actor
        )
    elif event_type == "SPECIFICATION_CREATED":
        kind = "part_selection"
    elif (
        event_type == "CHANGE_RECORD_CHANGED"
        and payload.get("record_type") == "ecr"
        and payload.get("action") == "created"
    ):
        kind = "change_request"
    elif event_type in {"TASK_CREATED", "TASK_UPDATED"}:
        if event_type == "TASK_UPDATED" and not set(payload.get("changed_fields", [])) & {
            "assignee_user_id",
            "title",
            "description",
            "expected_output",
        }:
            return
        task = c.execute(
            select(tables.tasks.c.assignee_user_id, tables.tasks.c.status).where(
                tables.tasks.c.tenant_id == tenant,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id == entity,
            )
        ).one_or_none()
        if task is None or task.assignee_user_id is None or task.status in {"done", "cancelled"}:
            return
        kind, recipient = "task_takeover", task.assignee_user_id
    if kind is None:
        return
    query = KnowledgePushService(c.engine)._context_query(
        tenant_id=tenant,
        project_id=project,
        context_kind=kind,
        context_entity_id=entity,
        connection=c,
    )
    if not query.strip():
        return
    c.execute(
        insert(tables.knowledge_reuse_jobs)
        .values(
            id=uuid4(),
            tenant_id=tenant,
            project_id=project,
            recipient_user_id=recipient,
            context_kind=kind,
            context_entity_id=entity,
            context_sha256=sha256(query.encode()).hexdigest(),
            query_text=query,
            source_audit_id=audit_id,
            state="pending",
            push_ids=[],
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        .on_conflict_do_nothing(constraint="uq_knowledge_reuse_context")
    )


def require_current(c: Connection, job: Any) -> None:
    unrestricted, principals = knowledge_scope(c, job["tenant_id"], job["recipient_user_id"])
    authorize_knowledge_project(c, job["tenant_id"], job["project_id"], unrestricted, principals)
    if job["context_kind"] == "task_takeover":
        task = c.execute(
            select(tables.tasks.c.assignee_user_id, tables.tasks.c.status).where(
                tables.tasks.c.tenant_id == job["tenant_id"],
                tables.tasks.c.id == job["context_entity_id"],
                tables.tasks.c.project_id == job["project_id"],
            )
        ).one_or_none()
        if (
            task is None
            or task.assignee_user_id != job["recipient_user_id"]
            or task.status in {"done", "cancelled"}
        ):
            raise KnowledgeVersionError("任务负责人或办理状态已变化")
    query = KnowledgePushService(c.engine)._context_query(
        tenant_id=job["tenant_id"],
        project_id=job["project_id"],
        context_kind=job["context_kind"],
        context_entity_id=job["context_entity_id"],
        connection=c,
    )
    if sha256(query.encode()).hexdigest() != job["context_sha256"]:
        raise KnowledgeVersionError("业务输入已变化")


class RecordedEmbedding:
    """Reuse a persisted successful response; recovering retrieval never re-calls a model."""

    def __init__(self, receipt: dict[str, Any], query: str):
        self.provider = str(receipt["provider"])
        self.model = str(receipt["model"])
        self.values = tuple(float(value) for value in receipt["values"])
        self.dimensions = len(self.values)
        self.query = query

    def embed(self, text: str) -> EmbeddingResult:
        if text != self.query[:500]:
            raise KnowledgeVersionError("检索输入与原回执不一致")
        return EmbeddingResult(provider=self.provider, model=self.model, values=self.values)


def job_summary(job: Any) -> dict[str, Any]:
    receipt = job["embedding_receipt"]
    return _plain(
        {
            "id": job["id"],
            "state": job["state"],
            "reason": job["reason"],
            "context_sha256": job["context_sha256"],
            "updated_at": job["updated_at"],
            "has_embedding_receipt": receipt is not None,
            "embedding_provider": receipt["provider"] if receipt else None,
            "embedding_model": receipt["model"] if receipt else None,
            "embedding_dimensions": len(receipt["values"]) if receipt else None,
            "result_count": len(job["push_ids"]),
        }
    )


def record_transition(
    c: Connection,
    job_id: UUID,
    *,
    actor: UUID | None = None,
    request_context: dict[str, Any] | None = None,
    **values: Any,
) -> None:
    t = tables.knowledge_reuse_jobs
    previous = c.execute(select(t).where(t.c.id == job_id).with_for_update()).mappings().one()
    before = job_summary(previous)
    after = job_summary(dict(previous) | values)
    EventAuditWriter(
        c, tenant_id=previous["tenant_id"], project_id=previous["project_id"], actor_user_id=actor
    ).record(
        EventDraft(
            event_id=f"knowledge-reuse:{uuid4()}",
            event_type="KNOWLEDGE_REUSE_STATE_CHANGED",
            source="knowledge_reuse_service",
            entity_id=job_id,
            payload={"job_id": str(job_id), "state": after["state"]},
        ),
        AuditDraft(
            action="knowledge.reuse.resume" if request_context else "knowledge.reuse.progress",
            before_snapshot=before,
            after_snapshot=after,
            context=request_context or {},
        ),
    )
    c.execute(t.update().where(t.c.id == job_id).values(**values))


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


def own_job(c: Connection, tenant: UUID, project: UUID, actor: UUID, job_id: UUID) -> Any:
    unrestricted, principals = knowledge_scope(c, tenant, actor)
    authorize_knowledge_project(c, tenant, project, unrestricted, principals)
    t = tables.knowledge_reuse_jobs
    job = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.recipient_user_id == actor,
                t.c.id == job_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if job is None:
        raise ContextNotFoundError
    return job


def resume(
    engine: Engine, tenant: UUID, project: UUID, actor: UUID, job_id: UUID, body: ResumeRequest
) -> dict[str, Any]:
    with engine.begin() as c:
        own_job(c, tenant, project, actor, job_id)
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"knowledge-resume:{tenant}:{actor}:{body.request_id}"},
        )
        a = tables.audit_log
        request_digest = digest({"job_id": str(job_id), **body.model_dump(mode="json")})
        previous = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == tenant,
                    a.c.actor_user_id == actor,
                    a.c.action == "knowledge.reuse.resume",
                    a.c.context["request_id"].as_string() == str(body.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous is not None:
            if previous["context"]["request_digest"] != request_digest:
                raise KnowledgeVersionError("原请求编号已用于不同的恢复内容")
            return {
                "request_id": str(body.request_id),
                "receipt": _plain(previous["after_snapshot"]),
            }
        acquired = c.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"knowledge-reuse:{job_id}"},
        ).scalar_one()
        if not acquired:
            raise KnowledgeVersionError("原请求仍在处理中，请刷新状态")
        t = tables.knowledge_reuse_jobs
        job = c.execute(select(t).where(t.c.id == job_id).with_for_update()).mappings().one()
        require_current(c, job)
        if digest(job_summary(job)) != body.expected_digest:
            raise KnowledgeVersionError("准备状态已变化，请刷新后继续")
        if job["state"] != "failed" or job["embedding_receipt"] is None:
            raise KnowledgeVersionError("仅已保留成功检索回执的处理失败可继续，不会重新调用模型")
        now = datetime.now(UTC)
        record_transition(
            c,
            job_id,
            actor=actor,
            request_context={
                "request_id": str(body.request_id),
                "request_digest": request_digest,
                "reason": body.reason,
            },
            state="pending",
            reason=None,
            updated_at=now,
        )
        return {
            "request_id": str(body.request_id),
            "receipt": job_summary(
                dict(job) | {"state": "pending", "reason": None, "updated_at": now}
            ),
        }


def history(
    engine: Engine, tenant: UUID, project: UUID, actor: UUID, job_id: UUID, before_id: int | None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        own_job(c, tenant, project, actor, job_id)
        a, u = tables.audit_log, tables.users
        q = (
            select(
                a.c.id,
                a.c.timestamp,
                a.c.action,
                a.c.before_snapshot,
                a.c.after_snapshot,
                a.c.context,
                u.c.display_name.label("actor_name"),
            )
            .select_from(
                a.outerjoin(u, (u.c.tenant_id == a.c.tenant_id) & (u.c.id == a.c.actor_user_id))
            )
            .where(
                a.c.tenant_id == tenant,
                a.c.project_id == project,
                a.c.entity_id == job_id,
                a.c.action.in_(["knowledge.reuse.progress", "knowledge.reuse.resume"]),
            )
        )
        if before_id is not None:
            q = q.where(a.c.id < before_id)
        entries = c.execute(q.order_by(a.c.id.desc()).limit(21)).mappings().all()
        return {
            "items": [_plain(entry) for entry in entries[:20]],
            "next_before_id": entries[19]["id"] if len(entries) > 20 else None,
        }


class KnowledgeReuseWorker:
    def __init__(self, engine: Engine):
        self.engine = engine

    def run_once(self, gateway: EmbeddingGateway | None = None) -> dict[str, Any]:
        if not get_settings().knowledge_reuse_enabled:
            return {"state": "disabled"}
        t = tables.knowledge_reuse_jobs
        # The session lock survives commits while a real embedding call is in flight.
        # A free lock on a running job proves no worker still owns that attempt.
        with self.engine.connect() as owner:
            candidates = (
                owner.execute(
                    select(t.c.id)
                    .where(t.c.state.in_(["pending", "running"]))
                    .order_by(t.c.created_at, t.c.id)
                    .limit(20)
                )
                .scalars()
                .all()
            )
            owner.commit()
            for job_id in candidates:
                lock = {"key": f"knowledge-reuse:{job_id}"}
                acquired = owner.execute(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), lock
                ).scalar_one()
                owner.commit()
                if not acquired:
                    continue
                try:
                    return self._process(job_id, gateway)
                finally:
                    owner.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), lock)
                    owner.commit()
        return {"state": "idle"}

    def _process(self, job_id: UUID, gateway: EmbeddingGateway | None) -> dict[str, Any]:
        t = tables.knowledge_reuse_jobs
        with self.engine.begin() as c:
            job = dict(
                c.execute(select(t).where(t.c.id == job_id).with_for_update()).mappings().one()
            )
            if job["state"] not in {"pending", "running"}:
                return {"state": "idle"}
            if job["state"] == "running" and job["embedding_receipt"] is None:
                record_transition(
                    c,
                    job_id,
                    state="uncertain",
                    reason="embedding_outcome_unknown",
                    updated_at=datetime.now(UTC),
                )
                return {"state": "uncertain", "id": str(job_id)}
            try:
                require_current(c, job)
            except (KnowledgeAccessError, KnowledgeVersionError, ContextNotFoundError):
                record_transition(
                    c,
                    job_id,
                    state="stale",
                    reason="context_or_access_changed",
                    updated_at=datetime.now(UTC),
                )
                return {"state": "stale", "id": str(job_id)}
            record_transition(c, job_id, state="running", updated_at=datetime.now(UTC))
        receipt = job["embedding_receipt"]
        if receipt is None:
            try:
                from app.domain.memories import MemoryService

                with ExitStack() as stack:
                    selected = gateway or stack.enter_context(configured_embedding_gateway())
                    result = selected.embed(job["query_text"][:500])
                    MemoryService._validate_embedding_route(selected, result)
                receipt = {
                    "provider": result.provider,
                    "model": result.model,
                    "values": list(result.values),
                }
                with self.engine.begin() as c:
                    record_transition(
                        c, job_id, embedding_receipt=receipt, updated_at=datetime.now(UTC)
                    )
            except Exception as error:
                state = (
                    "failed"
                    if isinstance(error, EmbeddingError)
                    and error.code == "EMBEDDING_NOT_CONFIGURED"
                    else "uncertain"
                )
                # Do not automatically repeat an external call whose receipt is absent.
                with self.engine.begin() as c:
                    record_transition(
                        c,
                        job_id,
                        state=state,
                        reason="embedding_not_configured"
                        if state == "failed"
                        else "embedding_receipt_unavailable",
                        updated_at=datetime.now(UTC),
                    )
                return {"state": state, "id": str(job_id)}
        try:
            pushed = KnowledgePushService(self.engine).push_for_context(
                tenant_id=job["tenant_id"],
                project_id=job["project_id"],
                actor_user_id=job["recipient_user_id"],
                context_kind=job["context_kind"],
                context_entity_id=job["context_entity_id"],
                expected_context_sha256=job["context_sha256"],
                gateway=RecordedEmbedding(receipt, job["query_text"]),
                member_scoped=True,
            )
            with self.engine.begin() as c:
                require_current(c, job)
                state = "ready" if pushed else "empty"
                record_transition(
                    c,
                    job_id,
                    state=state,
                    push_ids=[str(item.push_id) for item in pushed],
                    reason=None,
                    updated_at=datetime.now(UTC),
                )
            return {"state": state, "id": str(job_id)}
        except (KnowledgeAccessError, KnowledgeVersionError, ContextNotFoundError):
            state, reason = "stale", "context_or_access_changed"
        except Exception:
            state, reason = "failed", "retrieval_failed"
        with self.engine.begin() as c:
            record_transition(c, job_id, state=state, reason=reason, updated_at=datetime.now(UTC))
        return {"state": state, "id": str(job_id)}


def read_prepared(
    engine: Engine,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    kind: str,
    entity: UUID,
    selected_job_id: UUID | None = None,
) -> tuple[dict[str, Any], tuple[PushedMemory, ...]]:
    t = tables.knowledge_reuse_jobs
    service = KnowledgePushService(engine)
    with engine.begin() as c:
        unrestricted, principals = knowledge_scope(c, tenant, actor)
        authorize_knowledge_project(c, tenant, project, unrestricted, principals)
        current_digest = current_input_digest(c, tenant, project, kind, entity)
        query = select(t).where(
            t.c.tenant_id == tenant,
            t.c.project_id == project,
            t.c.recipient_user_id == actor,
            t.c.context_kind == kind,
            t.c.context_entity_id == entity,
        )
        if selected_job_id is not None:
            query = query.where(t.c.id == selected_job_id)
        # A return to previously used business input can reuse its deduplicated request.
        # A newer, different input must not obscure that matching request.
        job = (
            c.execute(
                query.order_by(
                    case((t.c.context_sha256 == current_digest, 0), else_=1),
                    t.c.created_at.desc(),
                    t.c.id.desc(),
                ).limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            if selected_job_id is not None:
                raise ContextNotFoundError
            return {"state": "not_requested", "enabled": get_settings().knowledge_reuse_enabled}, ()
        status = {
            "id": str(job["id"]),
            "state": job["state"],
            "recorded_state": job["state"],
            "input_matches_current": job["context_sha256"] == current_digest,
            "selection": "history" if selected_job_id is not None else "current",
            "created_at": job["created_at"],
            "source_audit_id": job["source_audit_id"],
            "enabled": get_settings().knowledge_reuse_enabled,
        }
        a, u = tables.audit_log, tables.users
        origin = (
            c.execute(
                select(a.c.action, a.c.timestamp, u.c.display_name.label("actor_name"))
                .select_from(
                    a.outerjoin(u, (u.c.tenant_id == a.c.tenant_id) & (u.c.id == a.c.actor_user_id))
                )
                .where(a.c.tenant_id == tenant, a.c.id == job["source_audit_id"])
            )
            .mappings()
            .one()
        )
        status.update(
            {
                "origin": _plain(origin),
                "basis": job_summary(job),
                "resume_digest": digest(job_summary(job)),
                "can_resume": job["state"] == "failed" and job["embedding_receipt"] is not None,
            }
        )
        try:
            require_current(c, job)
        except (KnowledgeAccessError, KnowledgeVersionError, ContextNotFoundError):
            return {**status, "state": "stale", "can_resume": False}, ()
        items = []
        unavailable = 0
        for push_id in job["push_ids"]:
            try:
                push, memory = service._authorized_push(c, tenant, actor, UUID(push_id))
            except (KnowledgeAccessError, KnowledgeVersionError, ContextNotFoundError):
                unavailable += 1
                continue
            feedback = (
                c.execute(
                    select(tables.knowledge_push_feedback).where(
                        tables.knowledge_push_feedback.c.tenant_id == tenant,
                        tables.knowledge_push_feedback.c.push_id == UUID(push_id),
                        tables.knowledge_push_feedback.c.actor_user_id == actor,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if feedback and feedback["action"] == "not_useful":
                continue
            items.append(
                PushedMemory(
                    push_id=UUID(push_id),
                    memory=_record(memory),
                    similarity=push["similarity_basis_points"] / 10000,
                    rank=push["rank"],
                    source_project_id=memory["project_id"],
                    already_seen=True,
                    feedback=_plain(feedback) if feedback else None,
                )
            )
        return {**status, "unavailable_count": unavailable}, tuple(items)


def resume_receipt(
    engine: Engine, tenant: UUID, project: UUID, actor: UUID, job_id: UUID, request_id: UUID
) -> dict[str, Any]:
    with engine.connect() as c:
        own_job(c, tenant, project, actor, job_id)
        a = tables.audit_log
        found = c.execute(
            select(a.c.after_snapshot).where(
                a.c.tenant_id == tenant,
                a.c.project_id == project,
                a.c.entity_id == job_id,
                a.c.actor_user_id == actor,
                a.c.action == "knowledge.reuse.resume",
                a.c.context["request_id"].as_string() == str(request_id),
            )
        ).scalar_one_or_none()
        if found is None:
            raise ContextNotFoundError
        return {"request_id": str(request_id), "receipt": _plain(found)}


def current_input_digest(
    c: Connection, tenant: UUID, project: UUID, kind: str, entity: UUID
) -> str | None:
    try:
        query = KnowledgePushService(c.engine)._context_query(
            tenant_id=tenant,
            project_id=project,
            context_kind=kind,
            context_entity_id=entity,
            connection=c,
        )
    except ContextNotFoundError:
        return None
    return sha256(query.encode()).hexdigest()


def request_history(
    engine: Engine,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    kind: str,
    entity: UUID,
    before_created_at: datetime | None,
    before_id: UUID | None,
) -> dict[str, Any]:
    if (before_created_at is None) != (before_id is None):
        raise KnowledgeVersionError("历史分页须包含完整的位置")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        unrestricted, principals = knowledge_scope(c, tenant, actor)
        authorize_knowledge_project(c, tenant, project, unrestricted, principals)
        current_digest = current_input_digest(c, tenant, project, kind, entity)
        t, a, u = tables.knowledge_reuse_jobs, tables.audit_log, tables.users
        query = (
            select(
                t.c.id,
                t.c.state,
                t.c.created_at,
                t.c.updated_at,
                t.c.context_sha256,
                t.c.reason,
                a.c.action.label("source_action"),
                u.c.display_name.label("source_actor_name"),
            )
            .select_from(
                t.join(
                    a, (a.c.tenant_id == t.c.tenant_id) & (a.c.id == t.c.source_audit_id)
                ).outerjoin(u, (u.c.tenant_id == a.c.tenant_id) & (u.c.id == a.c.actor_user_id))
            )
            .where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.recipient_user_id == actor,
                t.c.context_kind == kind,
                t.c.context_entity_id == entity,
            )
        )
        if before_created_at is not None:
            query = query.where(
                or_(
                    t.c.created_at < before_created_at,
                    (t.c.created_at == before_created_at) & (t.c.id < before_id),
                )
            )
        entries = (
            c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
            .mappings()
            .all()
        )
        return {
            "items": [
                _plain(
                    dict(entry)
                    | {"input_matches_current": entry["context_sha256"] == current_digest}
                )
                for entry in entries[:20]
            ],
            "next": {
                "before_created_at": entries[19]["created_at"].isoformat(),
                "before_id": str(entries[19]["id"]),
            }
            if len(entries) > 20
            else None,
        }
