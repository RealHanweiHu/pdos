"""Private append-only document and table work products from actual Runs."""

from dataclasses import replace
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pdos_next.database import require_context
from pdos_next.domain.preproject.access import human, proposal
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .models import AgentRun, AgentSession, AgentWorkProduct
from .project_scope import require_project


class FromRunInput(StrictModel):
    run_id: UUID
    kind: str = Field(pattern="^(document|table)$")
    title: str | None = Field(default=None, max_length=200)
    request_key: UUID


class RevisionInput(StrictModel):
    expected_revision: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=200000)
    request_key: UUID


def _session(session: Session, ctx, identity: UUID) -> AgentSession:
    require_context(session, ctx)
    human(session, ctx)
    conversation = session.get(AgentSession, identity)
    if conversation is None or conversation.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "会话不在当前本人范围。")
    if conversation.category_id is not None:
        require_access(session, replace(ctx, category_id=conversation.category_id), None)
    return conversation


def _run(session: Session, ctx, identity: UUID) -> tuple[AgentRun, dict]:
    run = session.get(AgentRun, identity)
    if (
        run is None
        or run.requester_id != ctx.requester_id
        or run.reverted_at is not None
        or run.state != "completed"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原运行不在当前本人范围或尚未形成可用成果。")
    _session(session, ctx, run.session_id)
    if run.proposal_id is not None:
        proposal(session, replace(ctx, category_id=run.category_id), run.proposal_id)
    if run.project_id is not None:
        require_project(
            session,
            replace(ctx, category_id=run.category_id),
            run.project_id,
            run.product_id,
        )
    from pdos_next.enterprise_search.assistant_answer import checked_sources

    return run, checked_sources(session, run)


def _view(row: AgentWorkProduct, sources=None):
    value = {
        "id": str(row.id),
        "root_id": str(row.root_id),
        "session_id": str(row.session_id),
        "run_id": str(row.run_id),
        "category_id": str(row.category_id) if row.category_id else None,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "revision": row.revision,
        "origin": row.origin,
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "created_at": row.created_at.isoformat(),
    }
    if sources and any(source.get("updated") for source in sources.values()):
        value["source_currentness"] = "updated"
    return value


def _product_sources(session, ctx, identities):
    from pdos_next.enterprise_search.assistant_answer import readable_runs

    runs = session.scalars(
        select(AgentRun).where(
            AgentRun.id.in_(identities),
            AgentRun.requester_id == ctx.requester_id,
        )
    ).all()
    return readable_runs(session, runs)


def _check_product_source(session, ctx, row):
    values = _product_sources(session, ctx, {row.run_id})
    if row.run_id not in values:
        raise DomainError("FORBIDDEN_SCOPE", "成果依赖的资料已不可读取，原内容已隐藏。", 403)
    return values[row.run_id]


def _lock(session: Session, ctx, key: UUID):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"work-product:{ctx.tenant_id}:{ctx.requester_id}:{key}"},
    )


def _prior(session: Session, ctx, request_key: UUID, request_sha256: str):
    row = session.scalar(
        select(AgentWorkProduct).where(
            AgentWorkProduct.tenant_id == ctx.tenant_id,
            AgentWorkProduct.owner_id == ctx.requester_id,
            AgentWorkProduct.request_key == request_key,
        )
    )
    if row is not None and row.request_sha256 != request_sha256:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同成果内容。")
    return row


def _has_markdown_table(body: str) -> bool:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        if not (lines[index].startswith("|") and lines[index].endswith("|")):
            continue
        separator = lines[index + 1]
        if (
            separator.startswith("|")
            and "-" in separator
            and not set(
                separator.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
            )
        ):
            return True
    return False


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/personal/work-products")
    def list_work_products(session_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            conversation = _session(session, ctx, session_id)
            rows = session.scalars(
                select(AgentWorkProduct)
                .where(
                    AgentWorkProduct.tenant_id == ctx.tenant_id,
                    AgentWorkProduct.owner_id == ctx.requester_id,
                    AgentWorkProduct.session_id == conversation.id,
                )
                .order_by(AgentWorkProduct.created_at, AgentWorkProduct.id)
            ).all()
            sources = _product_sources(session, ctx, {row.run_id for row in rows})
            return {
                "version": "agent-work-products/v1",
                "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
                "items": [_view(row, sources[row.run_id]) for row in rows if row.run_id in sources],
                "next_cursor": None,
            }

    @result.get("/v1/personal/work-products/{identity}")
    def read_work_product(identity: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            row = session.get(AgentWorkProduct, identity)
            if row is None or row.owner_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "成果不在当前本人范围。")
            _session(session, ctx, row.session_id)
            return _view(row, _check_product_source(session, ctx, row))

    @result.post("/v1/personal/work-products/from-run", status_code=201)
    def create_from_run(data: FromRunInput, ctx=context_dependency):
        with transaction(ctx) as session:
            run, sources = _run(session, ctx, data.run_id)
            body = (run.result or {}).get("summary")
            if not isinstance(body, str) or not body.strip():
                raise DomainError("VALIDATION_FAILED", "这次运行没有可保存为成果的正文。", 422)
            body = body.strip()
            comparison = (run.result or {}).get("result", {}).get("assistant", {}).get("comparison")
            if isinstance(comparison, dict):
                from pdos_next.enterprise_search.comparison_result import markdown

                body += "\n\n" + markdown(comparison)
            task_result = (
                (run.result or {}).get("result", {}).get("assistant", {}).get("task_result")
            )
            if isinstance(task_result, dict):
                from pdos_next.enterprise_search.task_result import markdown as task_markdown

                body += "\n\n" + task_markdown(task_result)
            if data.kind == "table" and not _has_markdown_table(body):
                raise DomainError(
                    "VALIDATION_FAILED", "这段回复没有可核对的表格，请作为文档打开。", 422
                )
            title = data.title.strip() if data.title else run.goal.split("\n", 1)[0].strip()[:200]
            if not title:
                title = "小Pai成果"
            request_sha256 = digest(
                {"run_id": str(run.id), "kind": data.kind, "title": title, "body": body}
            )
            _lock(session, ctx, data.request_key)
            prior = _prior(session, ctx, data.request_key, request_sha256)
            if prior is not None:
                return _view(prior, sources)
            identity = uuid4()
            row = AgentWorkProduct(
                id=identity,
                tenant_id=ctx.tenant_id,
                session_id=run.session_id,
                run_id=run.id,
                root_id=identity,
                supersedes_id=None,
                owner_id=ctx.requester_id,
                category_id=run.category_id,
                kind=data.kind,
                title=title,
                body=body,
                revision=1,
                origin="ai_draft",
                request_key=data.request_key,
                request_sha256=request_sha256,
            )
            session.add(row)
            session.flush()
            return _view(row, sources)

    @result.post("/v1/personal/work-products/{identity}/revisions", status_code=201)
    def revise(identity: UUID, data: RevisionInput, ctx=context_dependency):
        with transaction(ctx) as session:
            current = session.get(AgentWorkProduct, identity)
            if current is None or current.owner_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "成果不在当前本人范围。")
            conversation = _session(session, ctx, current.session_id)
            sources = _check_product_source(session, ctx, current)
            title = data.title.strip()
            body = data.body.strip()
            if not title or not body:
                raise DomainError("VALIDATION_FAILED", "成果标题和正文不能为空。", 422)
            request_sha256 = digest(
                {
                    "root_id": str(current.root_id),
                    "expected_revision": data.expected_revision,
                    "title": title,
                    "body": body,
                }
            )
            _lock(session, ctx, data.request_key)
            prior = _prior(session, ctx, data.request_key, request_sha256)
            if prior is not None:
                return _view(prior, sources)
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"work-product-revision:{ctx.tenant_id}:{current.root_id}"},
            )
            latest = session.scalar(
                select(AgentWorkProduct)
                .where(
                    AgentWorkProduct.tenant_id == ctx.tenant_id,
                    AgentWorkProduct.root_id == current.root_id,
                )
                .order_by(AgentWorkProduct.revision.desc())
            )
            if (
                latest is None
                or latest.id != current.id
                or latest.revision != data.expected_revision
            ):
                raise DomainError("VERSION_CONFLICT", "成果已有新版本，请先读取后再编辑。")
            identity = uuid4()
            row = AgentWorkProduct(
                id=identity,
                tenant_id=ctx.tenant_id,
                session_id=conversation.id,
                run_id=current.run_id,
                root_id=current.root_id,
                supersedes_id=current.id,
                owner_id=ctx.requester_id,
                category_id=current.category_id,
                kind=current.kind,
                title=title,
                body=body,
                revision=current.revision + 1,
                origin="human",
                request_key=data.request_key,
                request_sha256=request_sha256,
            )
            session.add(row)
            session.flush()
            return _view(row, sources)

    return result
