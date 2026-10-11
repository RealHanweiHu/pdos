"""Human T1 all-or-none rollback; original execution and receipts remain history."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Principal
from pdos_next.request_proof import command_inputs_once
from pdos_next.service import reversible_claim

# A retained run may contain product-scoped EvidenceLinks. Match their
# Category → Product fence before inspecting or reverting those rows.
category_lifecycle_fence = True


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@dataclass(frozen=True)
class RevertPlan:
    target: object
    receipts: tuple
    subjects: tuple
    epoch: int | None
    item_plan: object | None = None


@command_inputs_once
def prepared(s, ctx, command, scope, payload):
    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "撤回须由当前授权本人确认。", 403)
    if payload.receipt_id:
        receipt, claim = reversible_claim(s, ctx, payload.receipt_id, scope.id)
        if command.expected_revision != claim.revision:
            raise DomainError("VERSION_CONFLICT", "待撤回记录已变化。")
        return RevertPlan(claim, (receipt,), (claim,), None)
    from pdos_next.agent_kernel.persistence import prepare_run_revert
    from pdos_next.domain.preproject.evidence_models import EvidenceLink

    run, receipts = prepare_run_revert(s, ctx, payload.run_id, lock=True)
    if (
        run.product_id != scope.id
        or run.reverted_at
        or command.expected_revision != run.cancel_epoch + 1
    ):
        raise DomainError("VERSION_CONFLICT", "运行范围或撤回状态已变化，请重新核对。")
    from pdos_next.domain.products import definition_items

    item_plan = (
        definition_items.prepare_revert(s, ctx, run, receipts)
        if any(r.operation == "product.definition.item.patch" for r in receipts)
        else None
    )
    subjects = []
    # Lock the complete target set in a stable order before applying any effect.
    for receipt in sorted(receipts, key=lambda r: (r.subject_type, str(r.subject_id))):
        if receipt.operation == "product.definition.item.patch":
            continue
        if receipt.operation == "evidence.claim.record":
            _, subject = reversible_claim(s, ctx, receipt.id, receipt.product_id)
        elif receipt.operation == "evidence.artifact.register":
            subject = s.scalar(
                select(Artifact).where(Artifact.id == receipt.subject_id).with_for_update()
            )
            if (
                not subject
                or subject.status != "active"
                or subject.revision != receipt.subject_revision
                or subject.owner_id != ctx.requester_id
                or subject.original_id is not None
            ):
                raise DomainError(
                    "UNDO_BLOCKED_BY_DEPENDENCY", "资料已改变或不是本次运行的独立草稿。"
                )
        elif receipt.operation == "evidence.link.create":
            subject = s.scalar(
                select(EvidenceLink).where(EvidenceLink.id == receipt.subject_id).with_for_update()
            )
            if (
                not subject
                or subject.reverted_by_receipt_id
                or subject.run_id != run.id
                or subject.origin != "ai_draft"
                or subject.writer_id != run.writer_id
            ):
                raise DomainError("UNDO_BLOCKED_BY_DEPENDENCY", "关联已变化或不属于本次运行。")
            if subject.target_type == "proposal_item":
                from pdos_next.domain.preproject.access import proposal
                from pdos_next.domain.preproject.models import ProposalItem

                item = s.get(ProposalItem, subject.target_id)
                owner = proposal(s, ctx, item.proposal_id, lock=True) if item else None
                if (
                    not owner
                    or owner.owner_id != ctx.requester_id
                    or owner.status not in {"draft", "returned"}
                    or item.removed
                    or item.current_version != subject.target_version
                ):
                    raise DomainError(
                        "UNDO_BLOCKED_BY_DEPENDENCY", "关联条目已有人工修改或已提交。"
                    )
            elif subject.target_type == "definition_spec":
                from pdos_next.domain.products.models import (
                    DefinitionRevision,
                    DefinitionSpecCurrent,
                    DefinitionSpecRow,
                )

                spec = s.get(DefinitionSpecRow, subject.target_id)
                definition = s.get(DefinitionRevision, spec.definition_id) if spec else None
                pointer = (
                    s.scalar(
                        select(DefinitionSpecCurrent).where(
                            DefinitionSpecCurrent.tenant_id == ctx.tenant_id,
                            DefinitionSpecCurrent.item_id == spec.item_id,
                        )
                    )
                    if spec
                    else None
                )
                if (
                    not definition
                    or definition.sealed
                    or definition.status != "draft"
                    or not pointer
                    or pointer.current_row_id != spec.id
                    or pointer.removed
                ):
                    raise DomainError("UNDO_BLOCKED_BY_DEPENDENCY", "关联定义已固定或不可读。")
        else:
            raise DomainError(
                "UNDO_BLOCKED_BY_DEPENDENCY",
                "运行含已发布、具名决定或尚不支持撤回的结果，不能部分撤回。",
            )
        if subject.category_id != ctx.category_id or (
            getattr(subject, "product_id", receipt.product_id) != receipt.product_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "待撤回对象与回执范围不一致。", 403)
        subjects.append(subject)
    if item_plan:
        subjects.extend(item_plan.original_rows)
    import json

    from pdos_next.domain.products.models import DefinitionSpecRow

    if s.scalar(
        text(
            "SELECT revert_subjects_consumed(:tenant,:category,"
            "CAST(:targets AS jsonb),CAST(:receipts AS uuid[]))"
        ),
        {
            "tenant": ctx.tenant_id,
            "category": ctx.category_id,
            "targets": json.dumps(
                [
                    {
                        "type": "claim"
                        if isinstance(row, Claim)
                        else (
                            "definition_spec"
                            if isinstance(row, DefinitionSpecRow)
                            else "evidence_link"
                            if isinstance(row, EvidenceLink)
                            else "artifact"
                        ),
                        "id": str(row.id),
                    }
                    for row in subjects
                ]
            ),
            "receipts": [row.id for row in receipts],
        },
    ):
        raise DomainError("UNDO_BLOCKED_BY_DEPENDENCY", "运行结果已有后续消费，不能部分撤回。")
    return RevertPlan(run, tuple(receipts), tuple(subjects), run.cancel_epoch, item_plan)


def validate(s, ctx, command, scope, payload):
    prepared(s, ctx, command, scope, payload)


def confirmation_subject(s, ctx, command, scope, payload):
    plan = prepared(s, ctx, command, scope, payload)
    return ("agent_run" if payload.run_id else "claim"), plan.target


def preview_view(s, ctx, command, scope, payload):
    plan = prepared(s, ctx, command, scope, payload)
    return {
        "payload": semantic(payload),
        "run_id": str(payload.run_id) if payload.run_id else None,
        "receipts": [
            {
                "id": str(r.id),
                "operation": r.operation,
                "subject_id": str(r.subject_id),
                "revision": r.subject_revision,
            }
            for r in plan.receipts
        ],
        "effect": "撤回全部尚未被后续工作消费的草稿，原文、运行结果与历史回执保留。",
    }


def apply(s, ctx, command, scope, payload):
    plan = prepared(s, ctx, command, scope, payload)
    from pdos_next.domain.preproject.evidence_models import EvidenceLink

    receipt_id = uuid4()
    from pdos_next.domain.products import definition_items
    from pdos_next.domain.products.models import DefinitionSpecRow

    changed_rows = (
        definition_items.apply_revert(s, ctx, plan.item_plan, receipt_id) if plan.item_plan else []
    )
    for subject in plan.subjects:
        if isinstance(subject, DefinitionSpecRow):
            continue
        if isinstance(subject, EvidenceLink):
            subject.reverted_by_receipt_id = receipt_id
            continue
        subject.status = "reverted" if isinstance(subject, Claim) else "withdrawn"
        subject.revision += 1
    if payload.run_id:
        # The technical owner is stamped only after this Human receipt is flushed.
        subject = SimpleNamespace(
            id=plan.target.id,
            revision=plan.epoch + 1,
            status="reverted",
            prepared_receipt_id=receipt_id,
            action_result={
                "receipt_ids": [str(r.id) for r in plan.receipts],
                "execution_state": plan.target.state,
                "definition_item_changes": [definition_items._change(row) for row in changed_rows],
                "retained_items": list(plan.item_plan.retained) if plan.item_plan else [],
            },
        )
        return subject, "agent_run", "private"
    return plan.target, "claim", plan.target.visibility


def finalize_receipt(s, ctx, command, scope, payload, subject, receipt):
    if not payload.run_id:
        return
    from pdos_next.agent_kernel.persistence import finish_run_revert

    finish_run_revert(
        s,
        ctx,
        payload.run_id,
        revert_receipt_id=receipt.id,
        expected_cancel_epoch=command.expected_revision - 1,
    )
