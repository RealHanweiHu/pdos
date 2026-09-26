"""Transfer a pending requirement package without rewriting its frozen ownership."""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Connection

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.definition_intake import RequirementCandidate, _inspect
from app.domain.product_definitions import _release, _row, definition_digest
from app.domain.product_workspace import ProductWorkError, _emit, digest


def source_info(c: Connection, context: AuthContext, space: UUID, row: Any) -> dict[str, Any]:
    definition = _row(c, context, space, row["definition_id"])
    release = _release(c, context, definition["product_id"])
    return {
        "title": f"{definition['title']} · 修订 {definition['revision_number']} → 需求候选",
        "source_is_current": release is not None
        and release["id"] == row["release_id"]
        and release["action"] == "publish"
        and definition_digest(definition) == row["proposal"]["definition_digest"],
    }


def transfer(
    c: Connection,
    context: AuthContext,
    space: UUID,
    row: Any,
    owner: UUID,
    request_id: UUID,
    signature: str,
) -> Any:
    # The caller holds the same space lock as original accept/apply/publication.
    if not source_info(c, context, space, row)["source_is_current"]:
        raise ProductWorkError("原定义已撤回或替代，请从当前发布版重新准备需求候选")
    definition = _row(c, context, space, row["definition_id"], write=True)
    for candidate in row["proposal"]["candidates"]:
        current = _inspect(
            c, context, definition, RequirementCandidate.model_validate(candidate["input"])
        )
        if "prior_mappings" not in candidate:
            current.pop("prior_mappings", None)
        if digest(current) != digest(candidate):
            raise ProductWorkError("需求内容或映射已有变化，请重新准备候选；原包和原责任保持不变")
    t = tables.definition_requirement_packages
    now = datetime.now(UTC)
    # Ownership is immutable in the existing package contract. Close the old
    # proposal and create an identical pending one in this transaction instead.
    closed = (
        c.execute(
            t.update()
            .where(t.c.tenant_id == context.tenant.id, t.c.id == row["id"])
            .values(state="rejected", version=row["version"] + 1, updated_at=now)
            .returning(t)
        )
        .mappings()
        .one()
    )
    successor_id = uuid5(
        NAMESPACE_URL, f"pdos:package-succession:{context.tenant.id}:{context.user.id}:{request_id}"
    )
    successor = (
        c.execute(
            t.insert()
            .values(
                id=successor_id,
                tenant_id=context.tenant.id,
                market_space_id=space,
                product_line_id=row["product_line_id"],
                definition_id=row["definition_id"],
                release_id=row["release_id"],
                owner_user_id=owner,
                proposal=row["proposal"],
                proposal_digest=row["proposal_digest"],
                request_id=successor_id,
                request_digest=signature,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    _emit(
        c,
        context,
        space,
        "definition_requirement_package",
        "closed_for_succession",
        closed,
        before=row,
    )
    _emit(c, context, space, "definition_requirement_package", "created_from_succession", successor)
    return successor


def links(
    c: Connection, tenant: UUID, space: UUID, id: UUID, kind: str = "package"
) -> list[dict[str, Any]]:
    from sqlalchemy import or_, select

    from app.domain.product_workspace import _plain

    a = tables.audit_log
    rows = c.execute(
        select(a.c.entity_id, a.c.timestamp, a.c.actor_user_id, a.c.context)
        .where(
            a.c.tenant_id == tenant,
            a.c.action == "preproject.responsibility.changed",
            a.c.context["market_space_id"].as_string() == str(space),
            a.c.context["kind"].as_string() == kind,
            a.c.context["replacement_id"].as_string().is_not(None),
            or_(a.c.entity_id == id, a.c.context["replacement_id"].as_string() == str(id)),
        )
        .order_by(a.c.id.desc())
        .limit(2)
    ).mappings()
    return [
        {
            "previous_id": str(r["entity_id"]),
            "next_id": r["context"]["replacement_id"],
            "reason": r["context"]["reason"],
            "created_at": _plain(r)["timestamp"],
            "actor_name": r["context"]["people"].get(str(r["actor_user_id"])),
            "previous_owner_name": r["context"]["people"].get(r["context"]["previous_user_id"]),
            "next_owner_name": r["context"]["people"].get(r["context"]["next_user_id"]),
        }
        for r in rows
    ]
