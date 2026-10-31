"""Fixed, authority-bound recovery batches; only derived indexes are changed."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest, require_access

from .indexing import project, record_failure
from .schemas import SOURCE_TYPES
from .sources import prepare_read, select_sources

BATCH_SIZE = 20


def _context(value):
    try:
        return Context(
            **{
                key: UUID(value[key]) if value.get(key) is not None else None
                for key in ("tenant_id", "actor_id", "requester_id", "category_id")
            }
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError("INVALID_PAYLOAD", "重建批次缺少实际调用范围。", 422) from None


def context_reference(ctx):
    return {
        key: str(getattr(ctx, key)) if getattr(ctx, key) is not None else None
        for key in ("tenant_id", "actor_id", "requester_id", "category_id")
    }


def plan_rebuild(engine, ctx):
    """One RR inventory of every implemented readable source, including fixed history."""
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
        read_snapshot=True,
    ) as session:
        prepare_read(session, SOURCE_TYPES)
        sources = session.execute(select_sources()).mappings().all()
        as_of = session.scalar(select(func.transaction_timestamp())).isoformat()
    targets = [
        {
            "source_type": source["source_type"],
            "source_id": str(source["source_id"]),
            "category_id": str(source["category_id"]),
            "source_revision": source["source_revision"],
            "content_hash": source["content_hash"],
        }
        for source in sources
    ]
    targets.sort(key=lambda row: (row["source_type"], row["source_id"]))
    value = {
        "version": 1,
        "context": context_reference(ctx),
        "source_as_of": as_of,
        "targets": targets,
    }
    return {**value, "manifest_digest": digest(value)}


def validate_plan(plan):
    """A digest detects accidental payload changes; current authority still owns access."""
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise DomainError("INVALID_PAYLOAD", "重建批次结构无效。", 422)
    frozen = {key: value for key, value in plan.items() if key != "manifest_digest"}
    if digest(frozen) != plan.get("manifest_digest"):
        raise DomainError("SOURCE_STALE", "重建批次清单已变化。")
    try:
        ctx = _context(plan["context"])
        targets = plan["targets"]
        if not isinstance(targets, list) or not isinstance(plan["source_as_of"], str):
            raise ValueError
        if ctx.tenant_id is None or ctx.actor_id is None or ctx.requester_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "重建批次须绑定实际身份。")
        seen = set()
        for target in targets:
            key = (target["source_type"], UUID(target["source_id"]))
            category = UUID(target["category_id"])
            content_hash = target["content_hash"]
            if (
                type(target["source_revision"]) is not int
                or target["source_revision"] < 1
                or not isinstance(content_hash, str)
                or len(content_hash) != 64
                or any(character not in "abcdef0123456789" for character in content_hash)
            ):
                raise ValueError
            if (
                key in seen
                or key[0] not in SOURCE_TYPES
                or ctx.category_id is not None
                and category != ctx.category_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "重建批次来源不属于固定调用范围。")
            seen.add(key)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError("INVALID_PAYLOAD", "重建批次结构无效。", 422) from None
    return ctx


def rebuild_batch(engine, plan, cursor=0):
    """Retry the same fixed target slice; a source change never advances it as ready."""
    ctx = validate_plan(plan)
    targets = plan["targets"]
    if type(cursor) is not int or not 0 <= cursor <= len(targets):
        raise DomainError("INVALID_PAYLOAD", "重建批次游标无效。", 422)
    selected = targets[cursor : cursor + BATCH_SIZE]
    rows, changed = [], 0
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as session:
        for target in selected:
            source_ctx = replace(ctx, category_id=UUID(target["category_id"]))
            code = None
            try:
                with session.begin_nested():
                    require_access(session, source_ctx, None, lock=True)
                    value = project(
                        session,
                        source_ctx,
                        target["source_type"],
                        UUID(target["source_id"]),
                        expected_source=(target["source_revision"], target["content_hash"]),
                        force=True,
                        repair_derived=True,
                    )
                changed += bool(value["changed"])
            except (DomainError, SQLAlchemyError) as error:
                code = error.reason if isinstance(error, DomainError) else "INDEX_WRITE_FAILED"
                # A revoked category cannot authorize even a derived failure row.
                if not isinstance(error, DomainError) or error.code != "FORBIDDEN_SCOPE":
                    try:
                        with session.begin_nested():
                            record_failure(
                                session,
                                source_ctx,
                                target["source_type"],
                                UUID(target["source_id"]),
                                source_ctx.category_id,
                                target["source_revision"],
                                error,
                            )
                    except SQLAlchemyError:
                        # A corrupt hidden state row can also prevent recording
                        # its replacement. The durable batch still retains the
                        # failure; do not erase unreadable rows or abort peers.
                        pass
            rows.append(
                {
                    "source_type": target["source_type"],
                    "source_id": target["source_id"],
                    "source_revision": target["source_revision"],
                    "code": code,
                }
            )
        # One repair at batch end counts this tenant's complete derived metadata,
        # preserving unreadable other-category chunks. It avoids both corrupt
        # pre-existing deltas and an aggregate scan for every individual source.
        session.execute(text("SELECT public.enterprise_index_statistics_repair()"))
        indexed_as_of = session.scalar(select(func.transaction_timestamp())).isoformat()
    stop = cursor + len(selected)
    failed = sum(row["code"] is not None for row in rows)
    return {
        "processed": len(rows),
        "changed": changed,
        "failed": failed,
        "rows": rows,
        "next_cursor": stop if stop < len(targets) else None,
        "source_as_of": plan["source_as_of"],
        "indexed_as_of": indexed_as_of,
        "manifest_digest": plan["manifest_digest"],
        "total": len(targets),
        "status": "partial" if failed else "current",
    }
