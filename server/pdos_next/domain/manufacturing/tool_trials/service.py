"""T1 tool trial with its tooling record and verification request (P95, D305).

One confirmation writes the tooling version (first trial, or a changed one), the
trial record and the verification request built from an existing preparation.
The request reuses verification.request.create's structure and checks, except
that it is authorized by the trial's duties (engineering or manufacturing) —
P95 补充确认, user 2026-11-10. Tooling acceptance in Build readiness comes from
the named disposition of the trial's test: accept → accepted, reject →
rejected, no disposition yet → unknown. Life and maintenance stay in ERP/MES.
"""

# ruff: noqa: E501 -- user-facing Chinese texts stay on one line.

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .models import ToolingCurrent, ToolingVersion, ToolTrialCurrent, ToolTrialVersion
from .schemas import OPERATION, SUBJECT

EFFECT = (
    "登记一次试模：首次试模同时登记模具，模具信息变化时续版；同一次确认按已有验证准备建立验证请求。"
    "模具是否验收看试模样件所在测试的具名处置（接受、拒绝或尚无处置）。不改变寿命、保养或 ERP/MES 记录。"
)


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@dataclass
class Validated:
    build: object
    project: object
    tooling_previous: object
    tooling_pointer: object
    tooling_body: dict | None
    trial_body: dict
    request_review: dict
    review: dict


def _imported_tooling(s, ctx, product_id, build, ref):
    from pdos_next.domain.builds.operational_facts.models import BuildOperationalFact
    from pdos_next.domain.builds.operational_facts.service import _pointer

    pointer = _pointer(s, ctx, product_id, build.id)
    require(
        pointer is not None,
        "该 Build 还没有受控导入的资源事实，模具身份未知。",
        "MISSING_REQUIRED_EVIDENCE",
    )
    fact = s.scalar(
        select(BuildOperationalFact).where(
            BuildOperationalFact.tenant_id == ctx.tenant_id,
            BuildOperationalFact.id == pointer.fact_id,
        )
    )
    found = (
        next(
            (
                row
                for row in (fact.data or {}).get("resources", [])
                if row["resource"]["id"] == str(ref.id)
            ),
            None,
        )
        if fact
        else None
    )
    require(found is not None, "该模具不在本 Build 当前的受控导入中。", "FORBIDDEN_SCOPE", 403)
    require(
        found["resource"]["kind"] == "tooling" and found["resource"]["revision"] == ref.revision,
        "导入的资源不是模具或版本已变化。",
        "VERSION_CONFLICT",
    )


def validate(s, ctx, command, product, payload):
    from pdos_next.domain.builds.service import _build
    from pdos_next.domain.verification.preparation.service import trial_request_review

    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    build = _build(s, ctx, product.id, payload.build.id)
    require(
        build.revision == payload.build.revision,
        "Build 已有新版本，请核对后重试。",
        "VERSION_CONFLICT",
    )
    project = records.project(s, ctx, product.id, build.project_id)
    # The request check is also the trial's duty check: engineering or manufacturing.
    request_review, bound = trial_request_review(
        s, ctx, command, product, payload.verification, caller=OPERATION
    )
    require(bound.build.id == build.id, "验证准备须属于本次试模的 Build。", "FORBIDDEN_SCOPE", 403)
    tooling_previous = tooling_pointer = None
    if payload.tooling_new is not None:
        fields = payload.tooling_new
        if fields.resource is not None:
            _imported_tooling(s, ctx, product.id, build, fields.resource)
        tooling_body = {
            "revision": 1,
            "state": "active",
            "project_id": str(project.id),
            "part": fields.part,
            "version": fields.version,
            "supplier_ref": fields.supplier_ref,
            "cavities": fields.cavities,
            "resource_id": str(fields.resource.id) if fields.resource else None,
        }
    else:
        tooling_pointer, tooling_previous = records.current(
            s,
            ctx,
            product.id,
            payload.tooling.id,
            ToolingVersion,
            ToolingCurrent,
            lock=True,
            label="模具",
        )
        records.expect(tooling_previous, payload.tooling.revision, "模具")
        require(
            tooling_previous.project_id == project.id, "模具不属于本项目。", "FORBIDDEN_SCOPE", 403
        )
        tooling_body = None
        if payload.tooling.changes is not None:
            tooling_body = deepcopy(tooling_previous.body)
            tooling_body.update(payload.tooling.changes.model_dump(exclude_none=True))
            tooling_body["revision"] = tooling_previous.revision + 1
            require(
                tooling_body != {**tooling_previous.body, "revision": tooling_body["revision"]},
                "模具信息没有变化。",
                "VALIDATION_FAILED",
            )
    trial_body = {
        "revision": 1,
        "state": "created",
        "build_id": str(build.id),
        "project_id": str(project.id),
        "trial": payload.trial.model_dump(mode="json"),
        "request_id": str(payload.verification.request_id),
        "preparation": request_review["preparation"],
        "reason": payload.reason,
    }
    review = {
        "operation": OPERATION,
        "build": {"id": str(build.id), "revision": build.revision},
        "tooling": {
            "action": "create"
            if payload.tooling_new
            else "revise"
            if tooling_body
            else "reference",
            "before": tooling_previous.body if tooling_previous else None,
            "after": tooling_body,
        },
        "trial": trial_body,
        "verification_request": request_review,
        "roles": request_review["roles"],
        "effect": EFFECT,
    }
    return Validated(
        build,
        project,
        tooling_previous,
        tooling_pointer,
        tooling_body,
        trial_body,
        request_review,
        review,
    )


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def apply_validated(s, ctx, command, product, payload, value):
    from pdos_next.domain.verification.preparation.service import create_trial_request

    at, receipt_id = now(), uuid4()
    project_scope = {
        "project_id": value.project.id,
        "owner_id": value.project.owner_id,
        "visibility": value.project.visibility,
    }
    tooling = value.tooling_previous
    if value.tooling_body is not None:
        body = deepcopy(value.tooling_body)
        body["record_id"] = str(tooling.record_id) if tooling else str(uuid4())
        resource = body.get("resource_id")
        tooling = records.write(
            s,
            ctx,
            command,
            product,
            payload,
            versions=ToolingVersion,
            currents=ToolingCurrent,
            scope=project_scope,
            previous=value.tooling_previous,
            pointer=value.tooling_pointer,
            action="revise" if value.tooling_previous else "create",
            body=body,
            at=at,
            review=value.review,
            semantic=semantic,
            extra={"resource_id": UUID(resource) if resource else None},
            receipt_id=receipt_id,
        )
    trial_body = deepcopy(value.trial_body)
    trial_body["record_id"] = str(uuid4())
    trial_body["tooling"] = {"id": str(tooling.record_id), "revision": tooling.revision}
    row = records.write(
        s,
        ctx,
        command,
        product,
        payload,
        versions=ToolTrialVersion,
        currents=ToolTrialCurrent,
        scope={
            "project_id": value.build.project_id,
            "build_id": value.build.id,
            "owner_id": value.build.owner_id,
            "visibility": value.build.visibility,
        },
        previous=None,
        pointer=None,
        action="create",
        body=trial_body,
        at=at,
        review=value.review,
        semantic=semantic,
        extra={
            "tooling_id": tooling.record_id,
            "tooling_revision": tooling.revision,
            "request_id": payload.verification.request_id,
        },
        receipt_id=receipt_id,
    )
    request = create_trial_request(s, ctx, command, product, payload.verification, caller=OPERATION)
    row.action_result = {
        "trial_id": str(row.record_id),
        "tooling_id": str(tooling.record_id),
        "tooling_revision": tooling.revision,
        "request_id": str(payload.verification.request_id),
        "request_version_id": str(request.id),
    }
    row._tooling_row = tooling if value.tooling_body is not None else None
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    records.bind(subject, receipt, "试模")
    tooling = getattr(subject, "_tooling_row", None)
    if tooling is not None:
        records.bind(tooling, receipt, "模具")
        del subject._tooling_row


def trial_for_request(s, ctx, product_id, request_id):
    return s.scalar(
        select(ToolTrialVersion).where(
            ToolTrialVersion.tenant_id == ctx.tenant_id,
            ToolTrialVersion.product_id == product_id,
            ToolTrialVersion.request_id == request_id,
        )
    )


def tooling_status(outcome):
    """P95 补充确认: the named disposition's result decides tooling acceptance."""
    return {"accept": "accepted", "reject": "rejected"}.get(outcome, "unknown")


def readiness_facts(s, ctx, product_id, project_id, resource, purposes, operation_ids):
    """Native tooling acceptance from the latest trial's named disposition."""
    from pdos_next.domain.verification.results.models import TestResultActionFact
    from pdos_next.schemas.resource_readiness.contracts import QualificationFact
    from pdos_next.schemas.verification.contracts import SourceRef

    tooling = s.scalars(
        select(ToolingVersion)
        .join(
            ToolingCurrent,
            (ToolingCurrent.tenant_id == ToolingVersion.tenant_id)
            & (ToolingCurrent.version_id == ToolingVersion.id),
        )
        .where(
            ToolingVersion.tenant_id == ctx.tenant_id,
            ToolingVersion.product_id == product_id,
            ToolingVersion.project_id == project_id,
            ToolingVersion.resource_id == resource.id,
        )
    ).all()
    if not tooling:
        return []
    trial = s.scalar(
        select(ToolTrialVersion)
        .where(
            ToolTrialVersion.tenant_id == ctx.tenant_id,
            ToolTrialVersion.product_id == product_id,
            ToolTrialVersion.tooling_id.in_([row.record_id for row in tooling]),
        )
        .order_by(ToolTrialVersion.created_at.desc())
        .limit(1)
    )
    if trial is None:
        return []
    action = s.scalar(
        select(TestResultActionFact)
        .where(
            TestResultActionFact.tenant_id == ctx.tenant_id,
            TestResultActionFact.product_id == product_id,
            TestResultActionFact.request_id == trial.request_id,
            TestResultActionFact.operation == "test.disposition.decide",
        )
        .order_by(TestResultActionFact.created_at.desc())
        .limit(1)
    )
    status = tooling_status((action.input_snapshot or {}).get("outcome") if action else None)
    source = SourceRef(
        id=trial.record_id,
        revision=trial.revision,
        kind="domain",
        position=f"tool-trial:{trial.id}",
    )
    return [
        QualificationFact(
            kind="acceptance",
            source=source,
            purpose=purpose,
            operation_id=operation,
            status=status,
            named_decision_id=action.id if status == "accepted" else None,
            actor_id=action.actor_id if status == "accepted" else None,
        )
        for purpose in purposes
        for operation in operation_ids
    ]


def list_trials(s, ctx, product_id, build_id):
    from pdos_next.domain.builds.service import _build

    build = _build(s, ctx, product_id, build_id)
    rows = s.scalars(
        select(ToolTrialVersion)
        .where(
            ToolTrialVersion.tenant_id == ctx.tenant_id,
            ToolTrialVersion.product_id == product_id,
            ToolTrialVersion.build_id == build.id,
        )
        .order_by(ToolTrialVersion.created_at.desc())
    ).all()
    tooling = {
        row.record_id: row
        for row in s.scalars(
            select(ToolingVersion)
            .join(
                ToolingCurrent,
                (ToolingCurrent.tenant_id == ToolingVersion.tenant_id)
                & (ToolingCurrent.version_id == ToolingVersion.id),
            )
            .where(
                ToolingVersion.tenant_id == ctx.tenant_id,
                ToolingVersion.product_id == product_id,
                ToolingVersion.project_id == build.project_id,
            )
        )
    }
    # Each round shows the tooling version it used, not the tooling's current one.
    used = (
        {
            (row.record_id, row.revision): row.body
            for row in s.scalars(
                select(ToolingVersion).where(
                    ToolingVersion.tenant_id == ctx.tenant_id,
                    ToolingVersion.product_id == product_id,
                    ToolingVersion.record_id.in_({row.tooling_id for row in rows}),
                )
            )
        }
        if rows
        else {}
    )
    return {
        "build_id": str(build.id),
        "tooling": [
            {
                "id": str(row.record_id),
                "revision": row.revision,
                **{
                    k: row.body.get(k)
                    for k in ("part", "version", "supplier_ref", "cavities", "resource_id")
                },
            }
            for row in tooling.values()
        ],
        "items": [
            {
                "id": str(row.record_id),
                "trial": row.body["trial"],
                "tooling": {
                    **row.body["tooling"],
                    **{
                        k: used.get((row.tooling_id, row.tooling_revision), {}).get(k)
                        for k in ("part", "version")
                    },
                },
                "request_id": str(row.request_id),
                "actor_id": str(row.actor_id),
                "recorded_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }
