"""Named G0 reviews and owned external receipt heads, with no business writes."""

from sqlalchemy import String, and_, case, cast, func, literal, not_, or_, select

from pdos_next import models as registered_models  # noqa: F401 -- registry before domain children
from pdos_next.domain.external_handoff.models import BINDING
from pdos_next.domain.external_handoff.models import ExternalDeliveryIntent as Intent
from pdos_next.domain.external_handoff.models import ExternalHandoffAuthorization as Handoff
from pdos_next.domain.external_handoff.models import ExternalHandoffCurrent as Current
from pdos_next.domain.external_handoff.models import ExternalReceipt as Receipt
from pdos_next.domain.preproject.models import Proposal, ProposalDecision, ProposalSubmission
from pdos_next.models import Grant
from pdos_next.personal_attention_common import columns

STAGES = ("sent", "accepted", "effective")
EXCEPTIONS = ("partial", "unknown", "rejected", "failed", "conflict")


def external_pending(receipt_count, sent, accepted, effective):
    """A saved intent alone is not delivery; only all three successful stages close it.

    SQLAlchemy also simplifies literal boundaries for pure checks, without a DB.
    Actual query inputs are Current metadata and its exact real receipt join.
    """
    return and_(
        receipt_count > 0,
        not_(and_(sent == "succeeded", accepted == "succeeded", effective == "succeeded")),
    )


def _g0(ctx):
    submission = ProposalSubmission
    current_reviewer = (
        select(Grant.id)
        .where(
            Grant.tenant_id == Proposal.tenant_id,
            Grant.category_id == Proposal.category_id,
            Grant.principal_id == submission.reviewer_id,
            Grant.can_write.is_(True),
            Grant.product_manager.is_(True),
            or_(Grant.expires_at.is_(None), Grant.expires_at > func.transaction_timestamp()),
        )
        .exists()
    )
    decided = (
        select(ProposalDecision.id)
        .where(
            ProposalDecision.tenant_id == Proposal.tenant_id,
            ProposalDecision.category_id == Proposal.category_id,
            ProposalDecision.proposal_id == Proposal.id,
            ProposalDecision.submission_id == submission.id,
        )
        .exists()
    )
    return (
        select(
            *columns(
                key=literal("g0_review:") + cast(Proposal.id, String),
                kind="g0_review",
                queue="decide",
                tenant_id=Proposal.tenant_id,
                source_id=Proposal.id,
                version_id=submission.id,
                revision=submission.revision,
                epoch=Proposal.revision,
                category_id=Proposal.category_id,
                recorded_at=submission.created_at,
                title=Proposal.title,
                reason="当前提案已具名提交给你评审，尚未形成该提交的决定。",
                state=Proposal.status,
                responsible_id=submission.reviewer_id,
                responsibility="named_reviewer",
                target="proposal",
                blocked_code=case((not_(current_reviewer), "FORBIDDEN_SCOPE"), else_=None),
                blocked_message=case(
                    (not_(current_reviewer), "当前评审人缺少品类产品管理办理权限，请核对授权。"),
                    else_=None,
                ),
                details=func.jsonb_build_object(
                    "proposal_revision",
                    Proposal.revision,
                    "submission_revision",
                    submission.revision,
                    "submission_id",
                    submission.id,
                    "owner_id",
                    Proposal.owner_id,
                ),
            )
        )
        .select_from(Proposal)
        .join(
            submission,
            and_(
                submission.tenant_id == Proposal.tenant_id,
                submission.category_id == Proposal.category_id,
                submission.proposal_id == Proposal.id,
                submission.id == Proposal.current_submission_id,
                submission.owner_id == Proposal.owner_id,
            ),
        )
        .where(
            Proposal.tenant_id == ctx.tenant_id,
            Proposal.status == "in_review",
            submission.reviewer_id == ctx.requester_id,
            Proposal.owner_id != ctx.requester_id,
            not_(decided),
        )
    )


def _same(left, right):
    return and_(*(getattr(left, name) == getattr(right, name) for name in BINDING))


def _external(ctx):
    sent, accepted, effective = (Current.projection[stage]["state"].astext for stage in STAGES)
    unverified = sent != "succeeded"
    exceptional = or_(
        *(state.in_(EXCEPTIONS) for state in (sent, accepted, effective)),
        *(
            Current.projection[flag].as_boolean().is_(True)
            for flag in ("delivery_unknown", "rejected", "failed", "conflict")
        ),
    )
    return (
        select(
            *columns(
                key=literal("external_handoff:") + cast(Handoff.id, String),
                kind="external_handoff",
                queue="external",
                tenant_id=Handoff.tenant_id,
                source_id=Handoff.id,
                version_id=Receipt.id,
                revision=Receipt.revision,
                epoch=Current.epoch,
                category_id=Handoff.category_id,
                product_id=Handoff.product_id,
                project_id=Handoff.project_id,
                owner_id=Handoff.owner_id,
                visibility=Handoff.visibility,
                recorded_at=Receipt.created_at,
                title=literal("外部移交：") + Handoff.purpose,
                reason=case(
                    (unverified, "发送状态未核实，已登记的阶段回执尚未齐全。"),
                    (exceptional, "已登记发送；接收或生效阶段存在异常，须核对原回执。"),
                    else_="已登记发送成功，接收与生效回执尚未齐全。",
                ),
                state=Current.projection["status"].astext,
                responsible_id=Handoff.owner_id,
                responsibility="original_owner",
                target="project",
                blocked_code=case(
                    (unverified, "EXTERNAL_SEND_UNVERIFIED"),
                    (exceptional, "EXTERNAL_RECEIPT_EXCEPTION"),
                    else_=None,
                ),
                blocked_message=case(
                    (unverified, "不能依据授权意图或其他阶段回执认定已发送，请核对原始发送记录。"),
                    (exceptional, "部分、未知、拒绝、失败或冲突仍保留；请进入原移交核对。"),
                    else_=None,
                ),
                details=func.jsonb_build_object(
                    "sent",
                    sent,
                    "accepted",
                    accepted,
                    "effective",
                    effective,
                    "receipt_count",
                    Current.receipt_count,
                    "latest_receipt_id",
                    Receipt.id,
                    "latest_receipt_revision",
                    Receipt.revision,
                    "latest_sequence",
                    Receipt.sequence,
                    "latest_stage",
                    Receipt.stage,
                    "latest_outcome",
                    Receipt.outcome,
                    *(
                        item
                        for flag in ("delivery_unknown", "rejected", "failed", "conflict")
                        for item in (flag, Current.projection[flag].as_boolean())
                    ),
                ),
            )
        )
        .select_from(Handoff)
        .join(
            Current,
            and_(
                _same(Current, Handoff),
                Current.handoff_id == Handoff.id,
                Current.handoff_revision == Handoff.revision,
            ),
        )
        .join(
            Intent,
            and_(
                _same(Intent, Current),
                Intent.handoff_id == Current.handoff_id,
                Intent.handoff_revision == Current.handoff_revision,
                Intent.id == Current.intent_id,
                Intent.revision == Current.intent_revision,
            ),
        )
        .join(
            Receipt,
            and_(
                _same(Receipt, Current),
                Receipt.handoff_id == Current.handoff_id,
                Receipt.handoff_revision == Current.handoff_revision,
                Receipt.intent_id == Intent.id,
                Receipt.intent_revision == Intent.revision,
                Receipt.id == Current.latest_receipt_id,
                Receipt.revision == Current.latest_receipt_revision,
                Receipt.sequence == Current.receipt_count,
            ),
        )
        .where(
            Handoff.tenant_id == ctx.tenant_id,
            Handoff.owner_id == ctx.requester_id,
            Handoff.status == "authorized",
            Receipt.status == "recorded",
            external_pending(Current.receipt_count, sent, accepted, effective),
        )
    )


def queries(ctx, queue=None):
    """Construct only the selected group; scope and currentness remain in each leaf."""
    return tuple(
        factory(ctx)
        for name, factory in (("decide", _g0), ("external", _external))
        if queue is None or name == queue
    )
