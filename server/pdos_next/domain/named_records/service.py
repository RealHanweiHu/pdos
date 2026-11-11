"""Write and read helpers shared by the D47 named-person version chains.

A loop's own service validates scope, role and evidence, then calls ``write``
with the fixed body. ``write`` appends one version, advances (or creates) the
Current and stamps the receipt binding the deferred atom checks at commit.
"""

from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.service import command_digest, digest
from pdos_next.domain.projects.work.rules import require


def current(s, ctx, product_id, record_id, versions, currents, *, lock=False, label="记录"):
    query = select(currents).where(
        currents.tenant_id == ctx.tenant_id,
        currents.product_id == product_id,
        currents.record_id == record_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    require(pointer is not None, f"{label}不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    row = s.scalar(
        select(versions).where(
            versions.tenant_id == ctx.tenant_id,
            versions.product_id == product_id,
            versions.id == pointer.version_id,
        )
    )
    require(
        row is not None and row.revision == pointer.revision and row.record_id == record_id,
        f"{label}当前指针与固定版本不一致。",
        "INTEGRITY_MISMATCH",
    )
    require(row.body_sha256 == digest(row.body), f"{label}版本摘要无法核对。", "INTEGRITY_MISMATCH")
    return pointer, row


def expect(row, revision, label="记录"):
    require(row.revision == revision, f"{label}已有新版本，请核对差异后重试。", "VERSION_CONFLICT")


def history(s, ctx, product_id, record_id, versions, limit=20):
    return list(
        s.scalars(
            select(versions)
            .where(
                versions.tenant_id == ctx.tenant_id,
                versions.product_id == product_id,
                versions.record_id == record_id,
            )
            .order_by(versions.revision.desc())
            .limit(limit)
        )
    )


def write(
    s,
    ctx,
    command,
    product,
    payload,
    *,
    versions,
    currents,
    scope,
    previous,
    pointer,
    action,
    body,
    at,
    review,
    semantic,
    sources=(),
    reads=None,
    extra=None,
    receipt_id=None,
):
    """Append one human-decided version and advance its Current in this transaction."""
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    record_id = previous.record_id if previous else UUID(body["record_id"])
    row = versions(
        id=record_id if previous is None else uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        **scope,
        **(extra or {}),
        record_id=record_id,
        revision=body["revision"],
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        action=action,
        state=body["state"],
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=command.operation,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": review,
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        sources=list(sources),
        reads=reads
        if reads is not None
        else [r.model_dump(mode="json") for r in command.source_read_set],
        body=body,
        body_sha256=digest(body),
        receipt_id=receipt_id or uuid4(),
        request_digest=command_digest(command),
        intent_digest=digest(
            {
                "operation": command.operation,
                "category": command.category_id,
                "product": command.product_id,
                "payload": envelope["payload"],
                "named_actor": ctx.requester_id,
            }
        ),
        created_at=at,
    )
    s.add(row)
    s.flush([row])
    if pointer is None:
        s.add(
            currents(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                **scope,
                record_id=row.record_id,
                version_id=row.id,
                revision=row.revision,
                state=row.state,
            )
        )
    else:
        pointer.version_id, pointer.revision, pointer.state = row.id, row.revision, row.state
    row.prepared_receipt_id = row.receipt_id
    return row


def bind(subject, receipt, label="记录"):
    require(
        subject.receipt_id == receipt.id and subject.body_sha256 == digest(subject.body),
        f"{label}缺少本事务共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )


def human_only(s, ctx):
    """T1/T2 rows are written by the named person themself, never by an AI run."""
    from pdos_next.domain.categories.preproject.access import human

    require(
        not ctx.agent_run_id and not ctx.run_id and ctx.actor_id == ctx.requester_id,
        "此操作只由具名本人办理。",
        "NAMED_DECISION_REQUIRED",
        403,
    )
    human(s, ctx)


def version_view(row):
    return {
        "id": str(row.id),
        "record_id": str(row.record_id),
        "revision": row.revision,
        "action": row.action,
        "state": row.state,
        "actor_id": str(row.actor_id),
        "recorded_at": row.created_at.isoformat(),
        "body": row.body,
    }


def require_role(s, ctx, product_id, project_id, operation, purpose, roles, at, *, write=False):
    """Named duty and qualification for this exact operation and purpose (OPERATION_ROLES)."""
    from pdos_next.domain.builds.professional_authority import service as professional
    from pdos_next.errors import DomainError

    value = professional.assess(s, ctx, product_id, project_id, operation, purpose, at, write=write)
    if "PROFESSIONAL_OPERATION_NOT_CONFIGURED" in value["reason_codes"]:
        raise DomainError("INTEGRATION_REQUIRED", "此操作的专业职责矩阵尚未接入。", 503)
    held = set(value["roles"]) & set(roles)
    require(
        value["authorized"] is True and value["qualified"] is True and bool(held),
        "当前具名专业职责或本用途资格不满足。",
        "QUALIFICATION_REQUIRED",
        403,
    )
    return sorted(held)


def project_roles(s, ctx, project_id, principal_id):
    """Active project member's role keys, or None when the person is not a member."""
    from pdos_next.domain.projects.team.models import MemberRole, ProjectMember

    member = s.scalar(
        select(ProjectMember).where(
            ProjectMember.tenant_id == ctx.tenant_id,
            ProjectMember.project_id == project_id,
            ProjectMember.principal_id == principal_id,
            ProjectMember.left_at.is_(None),
        )
    )
    if member is None:
        return None
    return set(
        s.scalars(
            select(MemberRole.role_key).where(
                MemberRole.tenant_id == ctx.tenant_id,
                MemberRole.project_id == project_id,
                MemberRole.member_id == member.id,
            )
        )
    )


def project(s, ctx, product_id, project_id):
    from pdos_next.domain.projects.models import Project

    row = s.scalar(
        select(Project).where(
            Project.tenant_id == ctx.tenant_id,
            Project.product_id == product_id,
            Project.id == project_id,
        )
    )
    require(row is not None, "项目不在当前可用范围。", "FORBIDDEN_SCOPE", 403)
    return row
