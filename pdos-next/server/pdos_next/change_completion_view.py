"""Authenticated native completion choices; material is evaluated by real owners."""

from uuid import uuid4

from sqlalchemy import select

from pdos_next.change_completion_schemas import CompletionMaterial
from pdos_next.change_order_service import _one, inputs
from pdos_next.change_preparation_view import _current
from pdos_next.contracts import Command
from pdos_next.domain.build_execution.models import BuildLot, SampleUnit
from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_control.rules import digest, fully_effective
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import TestRun
from pdos_next.service import require_access


def _visible(row, request):
    return row.visibility != "private" or request.audience == (f"private:{row.owner_id}",)


def completion_context(s, ctx, pid, change_id):
    row, request, purpose = _current(s, ctx, pid, change_id)
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid)
    order = request.orders[-1] if request.orders else None
    items, adoptions, runs = [], [], []
    if order is not None:
        old_builds = {
            ref.id for item in order.plan.items for ref in item.intent.basis if ref.kind == "build"
        }
        builds = (
            list(
                s.scalars(
                    select(Build)
                    .where(
                        Build.tenant_id == ctx.tenant_id,
                        Build.product_id == pid,
                        Build.project_id == request.scope.project_id,
                        Build.previous_build_id.in_(old_builds),
                    )
                    .order_by(Build.created_at, Build.id)
                )
            )
            if old_builds
            else []
        )
        builds = {value.id: value for value in builds if _visible(value, request)}
        lots = (
            list(
                s.scalars(
                    select(BuildLot)
                    .where(
                        BuildLot.tenant_id == ctx.tenant_id,
                        BuildLot.product_id == pid,
                        BuildLot.project_id == request.scope.project_id,
                        BuildLot.build_id.in_(builds),
                    )
                    .order_by(BuildLot.occurred_at, BuildLot.id)
                )
            )
            if builds
            else []
        )
        for lot in lots:
            if not _visible(lot, request):
                continue
            samples = list(
                s.scalars(
                    select(SampleUnit)
                    .where(
                        SampleUnit.tenant_id == ctx.tenant_id,
                        SampleUnit.product_id == pid,
                        SampleUnit.lot_id == lot.id,
                    )
                    .order_by(SampleUnit.created_at, SampleUnit.id)
                )
            )
            adoptions.append(
                {
                    "lot": {"id": str(lot.id), "revision": lot.revision},
                    "build": {"id": str(lot.build_id), "revision": lot.build_revision},
                    "build_name": builds[lot.build_id].name,
                    "occurred_at": lot.occurred_at.isoformat(),
                    "samples": [
                        {
                            "ref": Ref(kind="sample", id=v.id, revision=v.revision).model_dump(
                                mode="json"
                            ),
                            "label": v.label,
                        }
                        for v in samples
                        if _visible(v, request)
                    ],
                }
            )
        current_runs = (
            list(
                s.scalars(
                    select(VerificationRunVersion)
                    .join(
                        VerificationRunCurrent,
                        (VerificationRunCurrent.tenant_id == VerificationRunVersion.tenant_id)
                        & (VerificationRunCurrent.product_id == VerificationRunVersion.product_id)
                        & (VerificationRunCurrent.run_version_id == VerificationRunVersion.id)
                        & (VerificationRunCurrent.run_revision == VerificationRunVersion.revision),
                    )
                    .where(
                        VerificationRunVersion.tenant_id == ctx.tenant_id,
                        VerificationRunVersion.product_id == pid,
                        VerificationRunVersion.project_id == request.scope.project_id,
                        VerificationRunVersion.build_id.in_(builds),
                    )
                    .order_by(VerificationRunVersion.created_at, VerificationRunVersion.id)
                )
            )
            if builds
            else []
        )
        for saved in current_runs:
            if not _visible(saved, request):
                continue
            run = TestRun.model_validate(saved.run_snapshot)
            if run.final_result is None or run.actual_end is None:
                continue
            item_by_id = {item.id: item for item in run.items}
            runs.append(
                {
                    "run": Ref(kind="test_run", id=run.id, revision=saved.revision).model_dump(
                        mode="json"
                    ),
                    "label": f"{builds[run.build.id].name} · Run {str(run.id)[:8]}",
                    "build": {"id": str(run.build.id), "revision": run.build.revision},
                    "mappings": [
                        {
                            "sample_id": str(pair.sample_id),
                            "test_item_id": pair.item_id,
                            "test_item_label": item_by_id[pair.item_id].feature,
                            "method": item_by_id[pair.item_id].method.model_dump(mode="json"),
                        }
                        for pair in run.coverage
                        if item_by_id[pair.item_id].method is not None
                    ],
                }
            )
        items = [
            {
                "item": item.model_dump(mode="json"),
                "requirement_sha256": digest(item.verification_requirement),
                "implemented_outputs": [
                    ref.model_dump(mode="json")
                    for fact in order.implementations
                    if fact.item_id == item.id and fact.outcome == "succeeded"
                    for ref in fact.outputs
                ],
                "effectivity_recorded": any(
                    f.item_id == item.id and f.stage == "effective" and f.outcome == "succeeded"
                    for f in order.effectivity
                ),
            }
            for item in order.plan.items
        ]
    from pdos_next.change_build_adoption import DEVELOPMENT_BUILD_ADOPTION_CONDITION

    supported_adoption = order is not None and any(
        item.selection.conditions == (DEVELOPMENT_BUILD_ADOPTION_CONDITION,)
        and any(ref.kind == "build" for ref in item.intent.basis)
        for item in order.plan.items
    )
    capabilities = {}
    for operation in ("change.effectivity.record", "change.verification.record", "change.close"):
        blockers = []
        try:
            from pdos_next import change_controlled_owner as controlled

            # Directory capability checks use the read snapshot. Keep the
            # actual write-access test, but do not take mutation locks here;
            # material/preview/submit recheck under their ordinary write UOW.
            controlled._caller(s, ctx, pid, write=False)
            require_access(s, ctx, pid, write=True, lock=False)
            controlled.authority(s, ctx, pid, request.scope, operation, purpose, write=False)
            if order is None or request.status not in {"implementing", "verifying"}:
                raise DomainError("INVALID_STATE", "请先完成批准与实际配置实施。")
            if operation == "change.effectivity.record" and not supported_adoption:
                raise DomainError(
                    "INTEGRATION_REQUIRED",
                    "当前批准计划未声明此开发 Build 采用范围，请按原计划取得对应生效证据。",
                    503,
                )
            if operation != "change.effectivity.record" and not fully_effective(order):
                raise DomainError("EFFECTIVITY_INCOMPLETE", "请先核对全部计划项的实际采用。")
            if operation == "change.verification.record" and ctx.actor_id in (
                {request.requester_id}
                | {v.actor_id for v in order.approvals}
                | {v.executor_id for v in order.implementations}
            ):
                raise DomainError("INDEPENDENT_VERIFIER_REQUIRED", "须由独立品质人员复核。", 403)
            if operation == "change.close" and (
                not order.verifications
                or order.verifications[-1].fact.result != "pass"
                or order.verifications[-1].fact.verifier_id != ctx.actor_id
            ):
                raise DomainError("CLOSURE_INCOMPLETE", "须由本次独立复核人核对通过后分别关闭。")
        except DomainError as error:
            if error.status >= 500 and error.status != 503:
                raise
            blockers.append({"code": error.code, "detail": error.message})
        capabilities[operation] = {"allowed": not blockers, "blockers": blockers}
    return {
        "change_id": str(request.id),
        "change_revision": request.revision,
        "product_revision": product.revision,
        "project_id": str(request.scope.project_id),
        "visibility": row.visibility,
        "order_id": str(order.id) if order else None,
        "content_digest": order.content_digest if order else None,
        "status": request.status,
        "items": items,
        "adoptions": adoptions,
        "runs": runs,
        "capabilities": capabilities,
        "closure": order.closure.model_dump(mode="json") if order and order.closure else None,
        "required_source_read_set": row.required_source_read_set,
    }


def completion_material(s, ctx, pid, data: CompletionMaterial):
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid)
    command = Command(
        command_id=uuid4(),
        idempotency_key=f"native-change-completion:{uuid4()}",
        operation=data.operation,
        category_id=ctx.category_id,
        product_id=pid,
        expected_revision=product.revision,
        payload=data.payload.model_dump(mode="json", exclude_none=True),
    )
    return inputs(s, ctx, pid, command)
