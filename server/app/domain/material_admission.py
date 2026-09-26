"""Versioned material admission, independent scoped waivers and actual operation receipts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_allocations import MaterialAllocationError, read_material_state
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest

TargetKind = Literal["build", "gate"]


class PolicyDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    mode: Literal["enforce", "disabled"]
    build_ids: list[UUID] = Field(min_length=1, max_length=50)
    criterion: Literal["all", "critical"]
    allow_documented_issued: bool = False
    require_closed_exceptions: bool = False
    allow_waivers: bool = False
    waiver_max_hours: int = Field(default=24, ge=1, le=720)
    reason: Text

    @model_validator(mode="after")
    def unique_builds(self) -> Self:
        if len(set(self.build_ids)) != len(self.build_ids):
            raise ValueError("准入批次不能重复")
        return self


class WaiverDraft(Contract):
    request_id: UUID
    expected_digest: Digest
    approver_user_id: UUID
    expires_at: AwareDatetime
    evidence_ids: list[UUID] = Field(min_length=1, max_length=20)
    mitigations: Text
    reason: Text


class WaiverDecision(Contract):
    request_id: UUID
    outcome: Literal["approved", "rejected"]
    reason: Text


class MaterialAdmissionBlocked(MaterialAllocationError):
    def __init__(self, check: dict[str, Any]):
        self.check = check
        super().__init__("本次物料准入未满足，请核对当前规则、供给或具名例外")


def authorize(c: Connection, context: AuthContext, project_id: UUID, action: Action) -> None:
    for needed in {Action.PRODUCT_ENGINEERING_VIEW, action}:
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project_id, needed
        )


def allowed(c: Connection, context: AuthContext, project_id: UUID, action: Action) -> bool:
    try:
        authorize(c, context, project_id, action)
        return True
    except KnowledgeAccessError:
        return False


def target(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: TargetKind, identity: UUID
) -> dict[str, Any]:
    t = tables.build_batches if kind == "build" else tables.gates
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MaterialAllocationError("当前项目中没有所选准入对象")
    scope = {"kind": kind, "id": str(identity), "status": row["status"], "code": row["code"]}
    if kind == "gate":
        r = tables.gate_signoff_rounds
        round_id = c.execute(
            select(r.c.id).where(
                r.c.tenant_id == tenant_id,
                r.c.project_id == project_id,
                r.c.gate_id == identity,
                r.c.status == "open",
            )
        ).scalar_one_or_none()
        scope["round_id"] = str(round_id) if round_id else None
    return scope


def policy(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: TargetKind, identity: UUID
) -> dict[str, Any] | None:
    t = tables.material_admission_policies
    row = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.target_kind == kind,
                t.c.target_id == identity,
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return _plain(dict(row)) if row else None


def _evidence(
    c: Connection, tenant_id: UUID, project_id: UUID, ids: list[UUID]
) -> list[dict[str, Any]]:
    return [
        metadata(document_row(c, tenant_id, project_id, identity)) for identity in sorted(set(ids))
    ]


def _evidence_current(
    c: Connection, tenant_id: UUID, project_id: UUID, original: list[dict[str, Any]]
) -> bool:
    # Use exact immutable original identity/hash, not mutable extraction progress.
    d = tables.documents
    for item in original:
        row = (
            c.execute(
                select(d.c.sha256, d.c.size_bytes).where(
                    d.c.tenant_id == tenant_id,
                    d.c.project_id == project_id,
                    d.c.id == UUID(item["id"]),
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["sha256"] != item["sha256"]
            or row["size_bytes"] != item["size_bytes"]
        ):
            return False
    return True


def check_admission(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    kind: TargetKind,
    identity: UUID,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    current_policy = policy(c, tenant_id, project_id, kind, identity)
    if current_policy is None:
        return {
            "policy": None,
            "allowed": True,
            "source_digest": None,
            "blockers": [],
            "waiver": None,
            "builds": [],
            "scope": target(c, tenant_id, project_id, kind, identity),
        }
    config = current_policy["configuration"]
    build_ids = [UUID(value) for value in config["build_ids"]]
    if lock:
        keys = {
            tuple(pool["pool_key"])
            for build_id in build_ids
            for pool in read_material_state(c, tenant_id, project_id, build_id)["pools"]
        }
        lock_pools(c, tenant_id, keys)
    observed_at = datetime.now(UTC)
    builds, blockers = [], []
    with localcontext() as arithmetic:
        arithmetic.prec = 2048
        for build_id in build_ids:
            state = read_material_state(c, tenant_id, project_id, build_id)
            lines = [
                row for row in state["lines"] if config["criterion"] == "all" or row["critical"]
            ]
            if state["revision"] is None or not lines:
                blockers.append(
                    {
                        "key": f"material:{build_id}:demand",
                        "kind": "material",
                        "label": "所选批次尚无固定需求或规则所要求的关键件标记",
                    }
                )
            for line in lines:
                if Decimal(line["qualified_allocated"]) + (
                    Decimal(line.get("qualified_issued", "0"))
                    if config.get("allow_documented_issued", False)
                    else Decimal(0)
                ) < Decimal(line["required_quantity"]):
                    blockers.append(
                        {
                            "key": f"material:{build_id}:{line['bom_item_id']}",
                            "kind": "material",
                            "label": "所选批次存在未被本规则允许的合格现货或有据净领料覆盖的需求",
                        }
                    )
            builds.append(
                {
                    "build": state["build"],
                    "revision": state["revision"],
                    "lines": lines,
                    "allocations": state["allocations"],
                    "pools": state["pools"],
                }
            )
    open_issues = []
    if config["require_closed_exceptions"]:
        e, i = tables.material_exceptions, tables.issues
        open_issues = [
            _plain(dict(row))
            for row in c.execute(
                select(
                    e.c.id.label("exception_id"), e.c.build_id, i.c.id, i.c.status, i.c.updated_at
                )
                .join(i, (i.c.tenant_id == e.c.tenant_id) & (i.c.id == e.c.issue_id))
                .where(
                    e.c.tenant_id == tenant_id,
                    e.c.project_id == project_id,
                    e.c.build_id.in_(build_ids),
                    i.c.status != "closed",
                )
                .order_by(e.c.id)
            ).mappings()
        ]
        blockers.extend(
            {
                "key": f"material:issue:{row['id']}",
                "kind": "material",
                "label": "规则要求所选批次的物料异常问题完成关闭",
            }
            for row in open_issues
        )
    if config["mode"] == "disabled":
        blockers = []
    scope = target(c, tenant_id, project_id, kind, identity)
    basis = {
        "policy_id": current_policy["id"],
        "policy_version": current_policy["version"],
        "configuration": config,
        "scope": scope,
        "builds": builds,
        "open_issues": open_issues,
        "blockers": blockers,
    }
    source_digest = digest(basis)
    waiver = None
    if blockers and config["allow_waivers"]:
        w, d = tables.material_admission_waivers, tables.material_admission_decisions
        rows = c.execute(
            select(
                w, d.c.id.label("decision_id"), d.c.created_by_user_id.label("approved_by_user_id")
            )
            .join(d, (d.c.tenant_id == w.c.tenant_id) & (d.c.waiver_id == w.c.id))
            .where(
                w.c.tenant_id == tenant_id,
                w.c.project_id == project_id,
                w.c.policy_id == UUID(current_policy["id"]),
                w.c.source_digest == source_digest,
                w.c.expires_at > observed_at,
                d.c.outcome == "approved",
            )
            .order_by(d.c.created_at.desc(), d.c.id.desc())
        ).mappings()
        for candidate in rows:
            if _evidence_current(c, tenant_id, project_id, candidate["evidence"]):
                waiver = _plain(dict(candidate))
                break
    return {
        "policy": current_policy,
        "scope": scope,
        "source_digest": source_digest,
        "basis": basis,
        "blockers": blockers,
        "builds": builds,
        "waiver": waiver,
        "allowed": not blockers or waiver is not None,
        "as_of": observed_at.isoformat(),
    }


def enforce(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    kind: TargetKind,
    identity: UUID,
) -> dict[str, Any] | None:
    check = check_admission(c, tenant_id, project_id, kind, identity, lock=True)
    if not check["allowed"]:
        raise MaterialAdmissionBlocked(check)
    if check["policy"] is None:
        return None
    operation = identity if kind == "build" else UUID(check["scope"]["round_id"])
    t = tables.material_admission_receipts
    saved = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                created_by_user_id=actor_id,
                policy_id=UUID(check["policy"]["id"]),
                target_kind=kind,
                target_id=identity,
                operation_key=operation,
                source_digest=check["source_digest"],
                decision_id=UUID(check["waiver"]["decision_id"]) if check["waiver"] else None,
                snapshot=check,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    NpiExecutionService._record_change(
        c,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_user_id=actor_id,
        record_id=identity,
        record_type="material_admission",
        action="used",
        before=None,
        after=_plain(dict(saved)),
    )
    return _plain(dict(saved))


class MaterialAdmissionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project_id: UUID, kind: TargetKind, identity: UUID
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
            check = check_admission(c, context.tenant.id, project_id, kind, identity)
            p, w, d = (
                tables.material_admission_policies,
                tables.material_admission_waivers,
                tables.material_admission_decisions,
            )
            policies = [
                _plain(dict(row))
                for row in c.execute(
                    select(p)
                    .where(
                        p.c.tenant_id == context.tenant.id,
                        p.c.project_id == project_id,
                        p.c.target_kind == kind,
                        p.c.target_id == identity,
                    )
                    .order_by(p.c.version.desc())
                    .limit(20)
                ).mappings()
            ]
            waivers = [
                _plain(dict(row))
                for row in c.execute(
                    select(
                        w,
                        d.c.outcome,
                        d.c.reason.label("decision_reason"),
                        d.c.created_by_user_id.label("decided_by_user_id"),
                    )
                    .join(p, (p.c.tenant_id == w.c.tenant_id) & (p.c.id == w.c.policy_id))
                    .outerjoin(d, (d.c.tenant_id == w.c.tenant_id) & (d.c.waiver_id == w.c.id))
                    .where(
                        w.c.tenant_id == context.tenant.id,
                        w.c.project_id == project_id,
                        p.c.target_kind == kind,
                        p.c.target_id == identity,
                    )
                    .order_by(w.c.created_at.desc())
                    .limit(50)
                ).mappings()
            ]
            b, u, docs = tables.build_batches, tables.users, tables.documents
            builds = [
                _plain(dict(row))
                for row in c.execute(
                    select(b.c.id, b.c.code, b.c.phase, b.c.status)
                    .where(b.c.tenant_id == context.tenant.id, b.c.project_id == project_id)
                    .order_by(b.c.created_at.desc())
                    .limit(200)
                ).mappings()
            ]
            members = select(tables.project_members.c.user_id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
            )
            people = [
                _plain(dict(row))
                for row in c.execute(
                    select(u.c.id, u.c.display_name)
                    .where(
                        u.c.tenant_id == context.tenant.id,
                        u.c.is_active.is_(True),
                        u.c.role.in_(("owner", "admin", "project_manager")),
                        or_(u.c.role.in_(("owner", "admin")), u.c.id.in_(members)),
                    )
                    .order_by(u.c.display_name)
                ).mappings()
            ]
            documents = [
                _plain(dict(row))
                for row in c.execute(
                    select(docs.c.id, docs.c.filename)
                    .where(docs.c.tenant_id == context.tenant.id, docs.c.project_id == project_id)
                    .order_by(docs.c.created_at.desc())
                    .limit(200)
                ).mappings()
            ]
            r = tables.material_admission_receipts
            receipts = [
                _plain(dict(row))
                for row in c.execute(
                    select(r)
                    .where(
                        r.c.tenant_id == context.tenant.id,
                        r.c.project_id == project_id,
                        r.c.target_kind == kind,
                        r.c.target_id == identity,
                    )
                    .order_by(r.c.created_at.desc())
                    .limit(20)
                ).mappings()
            ]
            scope = check["scope"]
            editable = (
                scope["status"] == "planned"
                if kind == "build"
                else not scope["round_id"] and scope["status"] not in {"approved", "conditional"}
            )
            return {
                "check": check,
                "policies": policies,
                "waivers": waivers,
                "receipts": receipts,
                "builds": builds,
                "people": people,
                "documents": documents,
                "actor_id": str(context.user.id),
                "can_manage": allowed(c, context, project_id, Action.GATE_MANAGE),
                "can_request": allowed(c, context, project_id, Action.PRODUCT_ENGINEERING_EDIT),
                "policy_editable": editable,
            }

    def configure(
        self,
        context: AuthContext,
        project_id: UUID,
        kind: TargetKind,
        identity: UUID,
        command: PolicyDraft,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "kind": kind,
                "id": str(identity),
                "project": str(project_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            authorize(c, context, project_id, Action.GATE_MANAGE)
            t = tables.material_admission_policies
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
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("原请求已用于其他准入规则")
                return _plain(dict(prior))
            current = policy(c, context.tenant.id, project_id, kind, identity)
            if command.expected_version != (current["version"] if current else 0):
                raise MaterialAllocationError("准入规则已有新版，请刷新")
            scope = target(c, context.tenant.id, project_id, kind, identity)
            if kind == "build" and (
                scope["status"] != "planned" or command.build_ids != [identity]
            ):
                raise MaterialAllocationError("批次开始前只能为本批次配置准入规则")
            if kind == "gate" and (
                scope["round_id"] or scope["status"] in {"approved", "conditional"}
            ):
                raise MaterialAllocationError(
                    "当前签核轮次或历史裁决的物料规则已固定；新规则须在下一轮开始前配置"
                )
            for build_id in command.build_ids:
                target(c, context.tenant.id, project_id, "build", build_id)
            config = command.model_dump(
                mode="json", exclude={"request_id", "expected_version", "reason"}
            )
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        created_by_user_id=context.user.id,
                        target_kind=kind,
                        target_id=identity,
                        version=command.expected_version + 1,
                        configuration=config,
                        request_id=command.request_id,
                        request_digest=signature,
                        reason=command.reason,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=identity,
                record_type="material_admission_policy",
                action="configured",
                before=current,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))

    def request_waiver(
        self,
        context: AuthContext,
        project_id: UUID,
        kind: TargetKind,
        identity: UUID,
        command: WaiverDraft,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "kind": kind,
                "id": str(identity),
                "project": str(project_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            authorize(c, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
            t = tables.material_admission_waivers
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
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("原例外请求已用于不同内容")
                return _plain(dict(prior))
            check = check_admission(c, context.tenant.id, project_id, kind, identity, lock=True)
            if (
                check["policy"] is None
                or not check["policy"]["configuration"]["allow_waivers"]
                or not check["blockers"]
                or check["source_digest"] != command.expected_digest
            ):
                raise MaterialAllocationError("当前规则不允许例外、缺项已变化或无需例外，请刷新")
            if kind == "gate" and not check["scope"]["round_id"]:
                raise MaterialAllocationError("请先开启本次签核轮次，再申请绑定本轮的例外")
            if kind == "build" and check["scope"]["status"] != "planned":
                raise MaterialAllocationError("批次已经开始，原准入不能补写例外")
            now = datetime.now(UTC)
            if (
                not now
                < command.expires_at
                <= now + timedelta(hours=check["policy"]["configuration"]["waiver_max_hours"])
            ):
                raise MaterialAllocationError("例外有效期须在当前规则允许的时限内")
            if command.approver_user_id == context.user.id:
                raise MaterialAllocationError("例外须由另一位具名审批人独立确认")
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, command.approver_user_id, project_id, Action.GATE_MANAGE
            )
            evidence = _evidence(c, context.tenant.id, project_id, command.evidence_ids)
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        created_by_user_id=context.user.id,
                        policy_id=UUID(check["policy"]["id"]),
                        source_digest=check["source_digest"],
                        snapshot=check,
                        approver_user_id=command.approver_user_id,
                        expires_at=command.expires_at,
                        mitigations=command.mitigations,
                        evidence=evidence,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=saved["id"],
                record_type="material_waiver",
                action="requested",
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))

    def decide(
        self,
        context: AuthContext,
        project_id: UUID,
        kind: TargetKind,
        identity: UUID,
        waiver_id: UUID,
        command: WaiverDecision,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project_id),
                "kind": kind,
                "target": str(identity),
                "waiver": str(waiver_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            authorize(c, context, project_id, Action.GATE_MANAGE)
            w, d, p = (
                tables.material_admission_waivers,
                tables.material_admission_decisions,
                tables.material_admission_policies,
            )
            waiver = (
                c.execute(
                    select(w)
                    .join(p, (p.c.tenant_id == w.c.tenant_id) & (p.c.id == w.c.policy_id))
                    .where(
                        w.c.tenant_id == context.tenant.id,
                        w.c.project_id == project_id,
                        w.c.id == waiver_id,
                        p.c.target_kind == kind,
                        p.c.target_id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                waiver is None
                or waiver["approver_user_id"] != context.user.id
                or waiver["created_by_user_id"] == context.user.id
            ):
                raise MaterialAllocationError("只有原指定的另一位审批人可以办理本例外")
            prior = (
                c.execute(
                    select(d).where(d.c.tenant_id == context.tenant.id, d.c.waiver_id == waiver_id)
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("本例外已经独立裁决，不能改写原结论")
                return _plain(dict(prior))
            check = check_admission(c, context.tenant.id, project_id, kind, identity, lock=True)
            if command.outcome == "approved" and (
                waiver["expires_at"] <= datetime.now(UTC)
                or check["source_digest"] != waiver["source_digest"]
                or not _evidence_current(c, context.tenant.id, project_id, waiver["evidence"])
            ):
                raise MaterialAllocationError(
                    "原例外的规则、范围、供给或证据已变化，或有效期已过，不能批准旧申请"
                )
            saved = (
                c.execute(
                    d.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        created_by_user_id=context.user.id,
                        waiver_id=waiver_id,
                        outcome=command.outcome,
                        snapshot={"waiver": _plain(dict(waiver)), "check": check},
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(d)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=waiver_id,
                record_type="material_waiver",
                action=command.outcome,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
