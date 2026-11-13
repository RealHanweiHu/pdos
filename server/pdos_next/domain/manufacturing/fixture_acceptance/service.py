"""T2 fixture acceptance, the native acceptance owner for imported fixtures (P95, D306).

Fixture identity comes from the Build's current controlled resource import; the
named manufacturing decision is stored here as a version chain and becomes the
acceptance fact that Build readiness requires (accepted / rejected / revoked,
with validity). Equipment stays with the test-resource import.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .models import FixtureAcceptanceCurrent, FixtureAcceptanceVersion
from .schemas import OPERATION, STATE_OF, SUBJECT

LABEL = "治具验收"
EFFECT = (
    "保存制造具名的治具验收决定（接受、拒绝或撤销），作为 Build 准备度的验收事实；"
    "有效期外准备度按阻断处理。不改变治具身份、校准、设备或试产记录。"
)
ALLOWED = {
    "accepted": {"accept", "reject", "revoke"},
    "rejected": {"accept"},
    "revoked": {"accept"},
}


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


@dataclass
class Validated:
    previous: object
    pointer: object
    body: dict
    scope: dict
    review: dict


def _iso(value):
    return value.isoformat() if value else None


def _imported_fixture(s, ctx, product_id, scope):
    from pdos_next.domain.builds.operational_facts.models import BuildOperationalFact
    from pdos_next.domain.builds.operational_facts.service import _pointer
    from pdos_next.domain.builds.service import _build

    build = _build(s, ctx, product_id, scope.build_id)
    pointer = _pointer(s, ctx, product_id, build.id)
    require(
        pointer is not None,
        "该 Build 还没有受控导入的资源事实，治具身份未知。",
        "MISSING_REQUIRED_EVIDENCE",
    )
    fact = s.scalar(
        select(BuildOperationalFact).where(
            BuildOperationalFact.tenant_id == ctx.tenant_id,
            BuildOperationalFact.product_id == product_id,
            BuildOperationalFact.id == pointer.fact_id,
        )
    )
    require(
        fact is not None and fact.revision == pointer.fact_revision,
        "资源导入当前指针无法核对。",
        "INTEGRITY_MISMATCH",
    )
    resource = next(
        (
            row
            for row in fact.data.get("resources", [])
            if row["resource"]["id"] == str(scope.resource.id)
        ),
        None,
    )
    require(resource is not None, "该资源不在本 Build 当前的受控导入中。", "FORBIDDEN_SCOPE", 403)
    require(
        resource["resource"]["kind"] == "fixture",
        "本命令只办理治具验收；设备等仍走测试资源导入。",
        "VALIDATION_FAILED",
    )
    require(
        resource["resource"]["revision"] == scope.resource.revision,
        "治具导入版本已变化，请核对后重试。",
        "VERSION_CONFLICT",
    )
    require(
        scope.purpose in resource.get("purposes", [])
        and scope.operation_id in resource.get("operation_ids", []),
        "治具导入没有声明这个用途或工序。",
        "VALIDATION_FAILED",
    )
    return build, fact, resource


def validate(s, ctx, command, product, payload):
    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    at = now()
    previous = pointer = None
    if payload.acceptance is None:
        scope = payload.scope
        build, fact, resource = _imported_fixture(s, ctx, product.id, scope)
        project = records.project(s, ctx, product.id, build.project_id)
        existing = s.scalar(
            select(FixtureAcceptanceCurrent.record_id).where(
                FixtureAcceptanceCurrent.tenant_id == ctx.tenant_id,
                FixtureAcceptanceCurrent.product_id == product.id,
                FixtureAcceptanceCurrent.project_id == project.id,
                FixtureAcceptanceCurrent.resource_id == scope.resource.id,
                FixtureAcceptanceCurrent.purpose == scope.purpose,
                FixtureAcceptanceCurrent.operation_id == scope.operation_id,
            )
        )
        require(
            existing is None,
            "这个治具在该用途和工序已有验收记录，请按当前版本办理。",
            "VERSION_CONFLICT",
        )
        body = {
            "revision": 1,
            "project_id": str(project.id),
            "resource_id": str(scope.resource.id),
            "resource": dict(resource["resource"]),
            "purpose": scope.purpose,
            "operation_id": scope.operation_id,
            "identified_in": {
                "build_id": str(build.id),
                "fact_id": str(fact.id),
                "fact_revision": fact.revision,
            },
        }
        purpose, owner_id, visibility = scope.purpose, project.owner_id, project.visibility
    else:
        pointer, previous = records.current(
            s,
            ctx,
            product.id,
            payload.acceptance.id,
            FixtureAcceptanceVersion,
            FixtureAcceptanceCurrent,
            lock=True,
            label=LABEL,
        )
        records.expect(previous, payload.acceptance.revision, LABEL)
        project = records.project(s, ctx, product.id, previous.project_id)
        require(
            payload.action in ALLOWED[previous.state],
            "当前验收状态不能这样办理。",
            "VALIDATION_FAILED",
        )
        body = deepcopy(previous.body)
        body["revision"] = previous.revision + 1
        purpose, owner_id, visibility = previous.purpose, previous.owner_id, previous.visibility
        require(
            (project.owner_id, project.visibility) == (owner_id, visibility),
            "项目的可见范围已变化，验收须先按新范围重核。",
            "VERSION_CONFLICT",
        )
    held = records.require_role(
        s, ctx, product.id, project.id, OPERATION, purpose, {"manufacturing"}, at
    )
    body.update(
        state=STATE_OF[payload.action],
        action=payload.action,
        valid_from=_iso(payload.valid_from),
        valid_until=_iso(payload.valid_until),
        conditions=list(payload.conditions),
        reason=payload.reason,
    )
    if payload.valid_until is not None:
        require(payload.valid_until > at, "有效期截止已过，无法作为当前验收。", "VALIDATION_FAILED")
    review = {
        "operation": OPERATION,
        "before": previous.body if previous else None,
        "after": body,
        "roles": held,
        "effect": EFFECT,
    }
    scope = {
        "project_id": project.id,
        "resource_id": UUID(body["resource_id"]),
        "purpose": purpose,
        "operation_id": body["operation_id"],
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
        versions=FixtureAcceptanceVersion,
        currents=FixtureAcceptanceCurrent,
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
        "acceptance_id": body["record_id"],
        "state": row.state,
        "revision": row.revision,
    }
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    records.bind(subject, receipt, LABEL)


def readiness_facts(s, ctx, product_id, project_id, resource_id):
    """Native acceptance facts for one fixture, in the readiness contract's shape."""
    from pdos_next.schemas.resource_readiness.contracts import QualificationFact
    from pdos_next.schemas.verification.contracts import SourceRef

    rows = s.scalars(
        select(FixtureAcceptanceVersion)
        .join(
            FixtureAcceptanceCurrent,
            (FixtureAcceptanceCurrent.tenant_id == FixtureAcceptanceVersion.tenant_id)
            & (FixtureAcceptanceCurrent.version_id == FixtureAcceptanceVersion.id),
        )
        .where(
            FixtureAcceptanceVersion.tenant_id == ctx.tenant_id,
            FixtureAcceptanceVersion.product_id == product_id,
            FixtureAcceptanceVersion.project_id == project_id,
            FixtureAcceptanceVersion.resource_id == resource_id,
        )
        .order_by(FixtureAcceptanceVersion.purpose, FixtureAcceptanceVersion.operation_id)
    ).all()
    return [
        QualificationFact(
            kind="acceptance",
            source=SourceRef(
                id=row.record_id,
                revision=row.revision,
                kind="domain",
                position=f"fixture-acceptance:{row.id}",
            ),
            purpose=row.purpose,
            operation_id=row.operation_id,
            status=row.state,
            valid_from=row.body.get("valid_from"),
            valid_until=row.body.get("valid_until"),
            conditions=tuple(row.body.get("conditions", ())),
            named_decision_id=row.id if row.state == "accepted" else None,
            actor_id=row.actor_id if row.state == "accepted" else None,
        )
        for row in rows
    ]


def _view(row, history=()):
    return {
        "id": str(row.record_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "state": row.state,
        "project_id": str(row.project_id),
        "resource": row.body["resource"],
        "purpose": row.purpose,
        "operation_id": row.operation_id,
        "valid_from": row.body.get("valid_from"),
        "valid_until": row.body.get("valid_until"),
        "conditions": row.body.get("conditions", []),
        "reason": row.body.get("reason"),
        "actor_id": str(row.actor_id),
        "recorded_at": row.created_at.isoformat(),
        "history": [records.version_view(item) for item in history],
    }


def list_acceptances(s, ctx, product_id, project_id):
    records.project(s, ctx, product_id, project_id)
    rows = s.scalars(
        select(FixtureAcceptanceVersion)
        .join(
            FixtureAcceptanceCurrent,
            (FixtureAcceptanceCurrent.tenant_id == FixtureAcceptanceVersion.tenant_id)
            & (FixtureAcceptanceCurrent.version_id == FixtureAcceptanceVersion.id),
        )
        .where(
            FixtureAcceptanceVersion.tenant_id == ctx.tenant_id,
            FixtureAcceptanceVersion.product_id == product_id,
            FixtureAcceptanceVersion.project_id == project_id,
        )
        .order_by(FixtureAcceptanceVersion.created_at.desc())
        .limit(200)
    ).all()
    return {
        "project_id": str(project_id),
        "items": [
            _view(row, records.history(s, ctx, product_id, row.record_id, FixtureAcceptanceVersion))
            for row in rows
        ],
    }
