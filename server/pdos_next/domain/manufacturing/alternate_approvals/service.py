"""T2 alternate-material approval feeding only this Build's kit (P96 第 5–7 项, D308).

An engineering-role named person approves an alternate for one BOM line of one
fixed Build, citing a current test run that has a named professional review
(the quality opinion stays its own record, v1.1 §03.10). The approval is bound
to the Build's BOM and configuration digests, may expire and may be revoked;
the BOM itself never changes (permanent replacement goes through a change).
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .models import AlternateApprovalCurrent, AlternateApprovalVersion
from .schemas import OPERATION, SUBJECT

LABEL = "替代料批准"
EFFECT = (
    "只让这一轮 Build 的齐套计算把该替代料算进去；BOM、其他 Build 与库存都不变。"
    "BOM 或配置变化、批准过期或撤销后不再计入。永久替换须走变更单。"
)
ALLOWED = {"approved": {"approve", "revoke"}, "revoked": {"approve"}}


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


@dataclass
class Validated:
    previous: object
    pointer: object
    body: dict
    scope: dict
    review: dict


def _bound(s, ctx, product_id, build, at):
    from pdos_next.domain.manufacturing.supply_execution.service import _bound as load
    from pdos_next.domain.manufacturing.supply_execution.service import _rule

    return _rule(lambda: load(s, ctx, product_id, build, at))


def _evidence(s, ctx, product_id, ref):
    """A current test run version that carries a named professional review."""
    from pdos_next.domain.verification.launch.models import (
        VerificationRunCurrent,
        VerificationRunVersion,
    )

    row = s.scalar(
        select(VerificationRunVersion).where(
            VerificationRunVersion.tenant_id == ctx.tenant_id,
            VerificationRunVersion.product_id == product_id,
            VerificationRunVersion.run_id == ref.id,
            VerificationRunVersion.revision == ref.revision,
        )
    )
    require(row is not None, "测试运行不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    pointer = s.scalar(
        select(VerificationRunCurrent).where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == product_id,
            VerificationRunCurrent.run_id == ref.id,
        )
    )
    require(
        pointer is not None and pointer.run_version_id == row.id,
        "测试运行已有新版本，请引用当前版本。",
        "VERSION_CONFLICT",
    )
    conclusion = (row.run_snapshot or {}).get("professional_conclusion")
    require(
        row.status in {"reviewed", "disposed"} and conclusion,
        "替代料批准须有当前的具名测试复核（AT-21）。",
        "MISSING_REQUIRED_EVIDENCE",
    )
    return {
        "id": str(row.run_id),
        "revision": row.revision,
        "status": row.status,
        "build_id": str(row.build_id),
        "reviewer_id": conclusion.get("actor_id"),
        "conclusion": conclusion.get("text"),
    }


def _basis(bound, item_id, alternate_material_id):
    line = next((row for row in bound.demand.lines if row.item_id == item_id), None)
    require(
        line is not None and line.material_id,
        "该 BOM 行不在本轮固定需求中，或物料未知。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(
        line.material_id != alternate_material_id, "替代料不能与原物料相同。", "VALIDATION_FAILED"
    )
    return {
        "target_material_id": line.material_id,
        "target_unit": line.unit,
        "bom_sha256": bound.basis.bom.ref.sha256,
        "configuration_sha256": bound.basis.bom.engineering_configuration.sha256,
    }


def validate(s, ctx, command, product, payload):
    from pdos_next.domain.builds.service import _build

    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    at = now()
    previous = pointer = None
    if payload.approval is None:
        scope = payload.scope
        build = _build(s, ctx, product.id, scope.build_id)
        require(
            build.revision == scope.expected_build_revision,
            "Build 已有新版本，请核对后重试。",
            "VERSION_CONFLICT",
        )
        existing = s.scalar(
            select(AlternateApprovalCurrent.record_id).where(
                AlternateApprovalCurrent.tenant_id == ctx.tenant_id,
                AlternateApprovalCurrent.build_id == build.id,
                AlternateApprovalCurrent.item_id == scope.item_id,
                AlternateApprovalCurrent.alternate_material_id == scope.alternate_material_id,
            )
        )
        require(existing is None, "这一替代已有批准记录，请按当前版本办理。", "VERSION_CONFLICT")
        body = {
            "revision": 1,
            "project_id": str(build.project_id),
            "build_id": str(build.id),
            "item_id": scope.item_id,
            "alternate_material_id": scope.alternate_material_id,
            "alternate_unit": scope.alternate_unit,
            "alternate_quantity_per_target": str(scope.alternate_quantity_per_target),
        }
        owner_id, visibility = build.owner_id, build.visibility
    else:
        pointer, previous = records.current(
            s,
            ctx,
            product.id,
            payload.approval.id,
            AlternateApprovalVersion,
            AlternateApprovalCurrent,
            lock=True,
            label=LABEL,
        )
        records.expect(previous, payload.approval.revision, LABEL)
        require(
            payload.action in ALLOWED[previous.state],
            "当前批准状态不能这样办理。",
            "VALIDATION_FAILED",
        )
        build = _build(s, ctx, product.id, previous.build_id)
        owner_id, visibility = previous.owner_id, previous.visibility
        require(
            (build.owner_id, build.visibility) == (owner_id, visibility),
            "Build 的可见范围已变化，批准须先按新范围重核。",
            "VERSION_CONFLICT",
        )
        body = deepcopy(previous.body)
        body["revision"] = previous.revision + 1
    project = records.project(s, ctx, product.id, build.project_id)
    held = records.require_role(
        s, ctx, product.id, project.id, OPERATION, project.purpose, {"engineering"}, at
    )
    if payload.action == "approve":
        body.update(
            _basis(
                _bound(s, ctx, product.id, build, at),
                body["item_id"],
                body["alternate_material_id"],
            )
        )
        body["build_revision"] = build.revision
        body["evidence_run"] = _evidence(s, ctx, product.id, payload.evidence_run)
        if payload.valid_until is not None:
            require(payload.valid_until > at, "有效期截止已过。", "VALIDATION_FAILED")
        body["valid_until"] = payload.valid_until.isoformat() if payload.valid_until else None
    else:
        body["valid_until"] = None
    body.update(
        state="approved" if payload.action == "approve" else "revoked",
        action=payload.action,
        reason=payload.reason,
    )
    review = {
        "operation": OPERATION,
        "before": previous.body if previous else None,
        "after": body,
        "roles": held,
        "effect": EFFECT,
    }
    scope = {
        "project_id": build.project_id,
        "build_id": build.id,
        "item_id": body["item_id"],
        "alternate_material_id": body["alternate_material_id"],
        "owner_id": owner_id,
        "visibility": visibility,
    }
    return Validated(previous, pointer, body, scope, review)


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def apply_validated(s, ctx, command, product, payload, value):
    body = deepcopy(value.body)
    body["record_id"] = str(value.previous.record_id) if value.previous else str(uuid4())
    row = records.write(
        s,
        ctx,
        command,
        product,
        payload,
        versions=AlternateApprovalVersion,
        currents=AlternateApprovalCurrent,
        scope=value.scope,
        previous=value.previous,
        pointer=value.pointer,
        action=payload.action,
        body=body,
        at=now(),
        review=value.review,
        semantic=semantic,
    )
    row.action_result = {
        "approval_id": body["record_id"],
        "state": row.state,
        "revision": row.revision,
    }
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    records.bind(subject, receipt, LABEL)


def approved_alternates(s, ctx, product_id, bound, as_of):
    """Current, unexpired approvals that still cover this Build's fixed BOM and configuration."""
    from datetime import datetime

    from pdos_next.domain.manufacturing.supply_cost.engine.common import SnapshotRef
    from pdos_next.domain.manufacturing.supply_cost.engine.dto import AlternateQualification

    basis = bound.basis
    rows = s.scalars(
        select(AlternateApprovalVersion)
        .join(
            AlternateApprovalCurrent,
            (AlternateApprovalCurrent.tenant_id == AlternateApprovalVersion.tenant_id)
            & (AlternateApprovalCurrent.version_id == AlternateApprovalVersion.id),
        )
        .where(
            AlternateApprovalVersion.tenant_id == ctx.tenant_id,
            AlternateApprovalVersion.product_id == product_id,
            AlternateApprovalVersion.build_id == UUID(str(basis.build.build_id)),
            AlternateApprovalVersion.state == "approved",
        )
        .order_by(AlternateApprovalVersion.id)
    ).all()
    out = []
    for row in rows:
        body = row.body
        until = datetime.fromisoformat(body["valid_until"]) if body.get("valid_until") else None
        if (
            (until is not None and until <= as_of)
            or body["bom_sha256"] != basis.bom.ref.sha256
            or (body["configuration_sha256"] != basis.bom.engineering_configuration.sha256)
        ):
            continue
        out.append(
            AlternateQualification(
                qualification_id=str(row.id),
                ref=SnapshotRef(
                    source_id=f"alternate-approval:{row.record_id}",
                    version=str(row.revision),
                    sha256=row.body_sha256,
                    captured_at=row.created_at,
                    valid_until=until,
                    state="current",
                ),
                status="externally_verified",
                target_material_id=body["target_material_id"],
                alternate_material_id=body["alternate_material_id"],
                target_unit=body["target_unit"],
                alternate_unit=body["alternate_unit"],
                alternate_quantity_per_target=body["alternate_quantity_per_target"],
                build_id=str(row.build_id),
                bom_sha256=body["bom_sha256"],
                configuration_sha256=body["configuration_sha256"],
            )
        )
    return tuple(out)


def list_approvals(s, ctx, product_id, build_id):
    from pdos_next.domain.builds.service import _build

    build = _build(s, ctx, product_id, build_id)
    rows = s.scalars(
        select(AlternateApprovalVersion)
        .join(
            AlternateApprovalCurrent,
            (AlternateApprovalCurrent.tenant_id == AlternateApprovalVersion.tenant_id)
            & (AlternateApprovalCurrent.version_id == AlternateApprovalVersion.id),
        )
        .where(
            AlternateApprovalVersion.tenant_id == ctx.tenant_id,
            AlternateApprovalVersion.product_id == product_id,
            AlternateApprovalVersion.build_id == build.id,
        )
        .order_by(AlternateApprovalVersion.created_at.desc())
    ).all()
    return {
        "build_id": str(build.id),
        "items": [
            {
                "id": str(row.record_id),
                "version_id": str(row.id),
                "revision": row.revision,
                "state": row.state,
                **{
                    key: row.body.get(key)
                    for key in (
                        "item_id",
                        "target_material_id",
                        "alternate_material_id",
                        "alternate_unit",
                        "alternate_quantity_per_target",
                        "valid_until",
                        "evidence_run",
                        "reason",
                    )
                },
                "actor_id": str(row.actor_id),
                "recorded_at": row.created_at.isoformat(),
                "history": [
                    records.version_view(item)
                    for item in records.history(
                        s, ctx, product_id, row.record_id, AlternateApprovalVersion
                    )
                ],
            }
            for row in rows
        ],
    }
