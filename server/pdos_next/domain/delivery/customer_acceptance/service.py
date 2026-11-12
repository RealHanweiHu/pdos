"""T2 customer acceptance from a signed sample sheet (P97 第 5–8 项, C11, D309).

An internal named member registers the customer's signed sheet (an uploaded
original) scope by scope. The record shows what the acceptance covers and what
it does not; it never stands in for engineering release, manufacturing release
or a stage decision, and stage reviews only list it. AI cannot act as the
customer's signature (v1.1 §08.8) and never holds this T2 record.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from pdos_next.core.models import Artifact, now
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .models import CustomerAcceptanceCurrent, CustomerAcceptanceVersion
from .schemas import OPERATION, SCOPES, SUBJECT

LABEL = "客户承认"
EFFECT = (
    "按客户签样单逐类登记承认范围：承认、条件承认、未承认或不涉及。承认只覆盖登记的范围，"
    "不代表工程发布、制造放行或阶段通过；阶段评审只列出它作为依据，不自动阻断。"
)
SCOPE_NAMES = {
    "appearance": "外观",
    "dimensions": "尺寸",
    "performance": "性能",
    "packaging_labeling": "包装标识",
    "certification_docs": "认证资料",
}


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


@dataclass
class Validated:
    previous: object
    pointer: object
    body: dict
    scope: dict
    sources: list
    review: dict


def overall(scopes):
    states = {item["state"] for item in scopes}
    if "not_accepted" in states:
        return "not_accepted"
    if "conditionally_accepted" in states:
        return "conditional"
    return "accepted"


def validate(s, ctx, command, product, payload):
    from pdos_next.core.source_current import direct_source_basis
    from pdos_next.domain.builds.service import _build

    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    at = now()
    previous = pointer = None
    if payload.acceptance is None:
        build = _build(s, ctx, product.id, payload.build_id)
        require(
            build.revision == payload.expected_build_revision,
            "Build 已有新版本，请核对后重试。",
            "VERSION_CONFLICT",
        )
        owner_id, visibility = build.owner_id, build.visibility
        body = {"revision": 1, "build_id": str(build.id), "project_id": str(build.project_id)}
    else:
        pointer, previous = records.current(
            s,
            ctx,
            product.id,
            payload.acceptance.id,
            CustomerAcceptanceVersion,
            CustomerAcceptanceCurrent,
            lock=True,
            label=LABEL,
        )
        records.expect(previous, payload.acceptance.revision, LABEL)
        build = _build(s, ctx, product.id, previous.build_id)
        owner_id, visibility = previous.owner_id, previous.visibility
        require(
            (build.owner_id, build.visibility) == (owner_id, visibility),
            "Build 的可见范围已变化，承认须先按新范围重核。",
            "VERSION_CONFLICT",
        )
        body = deepcopy(previous.body)
        body["revision"] = previous.revision + 1
    require(
        payload.send_ref is None,
        "客户样品外发尚未接入，暂不能关联外发记录；线下交付的样品不填外发。",
        "INTEGRATION_REQUIRED",
        503,
    )
    sheet = s.get(Artifact, payload.signed_sheet.id)
    require(
        sheet is not None and sheet.original_id is not None,
        "签样单须是上传的原件（扫描件或照片），不能是手写登记的文字。",
        "VALIDATION_FAILED",
    )
    basis, private = direct_source_basis(
        s, ctx, product, [payload.signed_sheet], command.source_read_set
    )
    require(
        not private or visibility == "private",
        "私有签样单不能扩大到共享的 Build。",
        "FORBIDDEN_SCOPE",
        403,
    )
    scopes = sorted(
        (item.model_dump(mode="json") for item in payload.scopes),
        key=lambda item: SCOPES.index(item["scope"]),
    )
    for item in payload.scopes:
        if item.expires_at is not None:
            require(
                item.expires_at > at,
                f"{SCOPE_NAMES[item.scope]}的到期日已过。",
                "VALIDATION_FAILED",
            )
    body.update(
        state=overall(scopes),
        customer=payload.customer.model_dump(mode="json"),
        scopes=scopes,
        signed_sheet=payload.signed_sheet.model_dump(mode="json"),
        source_basis=basis,
        send_ref=None,
        reason=payload.reason,
        action="create" if previous is None else "revise",
    )
    review = {
        "operation": OPERATION,
        "before": previous.body if previous else None,
        "after": body,
        "covered": [
            SCOPE_NAMES[i["scope"]]
            for i in scopes
            if i["state"] in {"accepted", "conditionally_accepted"}
        ],
        "not_covered": [
            SCOPE_NAMES[i["scope"]]
            for i in scopes
            if i["state"] in {"not_accepted", "not_applicable"}
        ],
        "effect": EFFECT,
    }
    scope = {
        "project_id": build.project_id,
        "build_id": build.id,
        "owner_id": owner_id,
        "visibility": visibility,
    }
    return Validated(
        previous, pointer, body, scope, [payload.signed_sheet.model_dump(mode="json")], review
    )


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
        versions=CustomerAcceptanceVersion,
        currents=CustomerAcceptanceCurrent,
        scope=value.scope,
        previous=value.previous,
        pointer=value.pointer,
        action=body["action"],
        body=body,
        at=now(),
        review=value.review,
        semantic=semantic,
        sources=value.sources,
    )
    row.action_result = {
        "acceptance_id": body["record_id"],
        "state": row.state,
        "revision": row.revision,
    }
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    records.bind(subject, receipt, LABEL)


def _view(row, history=()):
    return {
        "id": str(row.record_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "state": row.state,
        "build_id": str(row.build_id),
        "customer": row.body["customer"],
        "scopes": row.body["scopes"],
        "signed_sheet": row.body["signed_sheet"],
        "reason": row.body.get("reason"),
        "actor_id": str(row.actor_id),
        "recorded_at": row.created_at.isoformat(),
        "history": [records.version_view(item) for item in history],
    }


def _current_rows(s, ctx, product_id, **where):
    return s.scalars(
        select(CustomerAcceptanceVersion)
        .join(
            CustomerAcceptanceCurrent,
            (CustomerAcceptanceCurrent.tenant_id == CustomerAcceptanceVersion.tenant_id)
            & (CustomerAcceptanceCurrent.version_id == CustomerAcceptanceVersion.id),
        )
        .where(
            CustomerAcceptanceVersion.tenant_id == ctx.tenant_id,
            CustomerAcceptanceVersion.product_id == product_id,
            *(getattr(CustomerAcceptanceVersion, key) == value for key, value in where.items()),
        )
        .order_by(CustomerAcceptanceVersion.created_at.desc())
        .limit(200)
    ).all()


def list_acceptances(s, ctx, product_id, build_id):
    from pdos_next.domain.builds.service import _build

    build = _build(s, ctx, product_id, build_id)
    return {
        "build_id": str(build.id),
        "items": [
            _view(
                row, records.history(s, ctx, product_id, row.record_id, CustomerAcceptanceVersion)
            )
            for row in _current_rows(s, ctx, product_id, build_id=build.id)
        ],
    }


def project_listing(s, ctx, product_id, project_id):
    """Stage review basis only (P97 第 8 项): listed, never a gate check."""
    return [
        {
            "id": str(row.record_id),
            "revision": row.revision,
            "state": row.state,
            "build_id": str(row.build_id),
            "customer": row.body["customer"]["label"],
            "covered": [
                SCOPE_NAMES[i["scope"]]
                for i in row.body["scopes"]
                if i["state"] in {"accepted", "conditionally_accepted"}
            ],
            "not_covered": [
                SCOPE_NAMES[i["scope"]]
                for i in row.body["scopes"]
                if i["state"] in {"not_accepted", "not_applicable"}
            ],
        }
        for row in _current_rows(s, ctx, product_id, project_id=project_id)
    ]
