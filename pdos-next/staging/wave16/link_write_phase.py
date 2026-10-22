"""Staged new-write material frame; never consumes a shared proof or commits.

Common must run its current-guarded key/semantic/replay paths first. It compares
the returned server review to the real Confirmation, consumes once and records
the actual False->True marker. Only then may this local frame construct one Link.
"""

from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

import link_preview_phase as preview
from pdos_next import quality_followup_host as host
from pdos_next.domain.capa_verification import commands as link
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import digest, material_digest
from sqlalchemy import inspect, select


class WritePhase:
    """Distinct, opaque single-write frame; a PreviewPhase cannot authorize it."""

    __slots__ = (
        "_session",
        "_transaction",
        "_nested",
        "_engine",
        "_product",
        "_binding",
        "_runtime",
        "_bound",
        "_material",
        "_review_sha256",
        "_finished_at",
        "_spent",
    )

    def __init__(self, *args, **kwargs):
        raise TypeError("Only prepare_write_review creates a WritePhase")

    def __setattr__(self, name, value):
        raise AttributeError("WritePhase is opaque and immutable")

    def __reduce__(self):
        raise TypeError("WritePhase cannot leave its caller UOW")

    def __copy__(self):
        raise TypeError("WritePhase cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("WritePhase cannot be copied")

    def __repr__(self):
        return "<WritePhase: same-call new Link only>"


def _runtime(s):
    return digest(
        {
            "preview_runtime": preview._runtime(s),
            "actual_consumed_guard": id(host.require_consumed_proof),
        }
    )


def _assert_binding(s, ctx, command, product, payload, *, uow, binding, runtime, bound, material):
    current = preview._uow(s)
    if any(before is not after for before, after in zip(uow, current, strict=True)):
        preview._fail("实际回链不能跨主事务、子事务或宿主连接。")
    # UOW precedes any ORM attributes: rollback cannot reload an old frame.
    if preview._material(bound, ctx, product, payload) != material:
        preview._fail("实际回链Bound的完整材料已改变。")
    if preview._binding(s, ctx, command, product, payload) != binding or _runtime(s) != runtime:
        preview._fail("实际回链的原命令、身份、产品或可信入口已改变。")
    link._deadlines(bound.authority, bound.policy)
    return preview._clock()


def _assert_phase(s, ctx, command, product, payload, phase):
    if phase._session is not s or phase._product is not product:
        preview._fail("实际回链不能跨Session或改换Product对象。")
    at = _assert_binding(
        s,
        ctx,
        command,
        product,
        payload,
        uow=(phase._transaction, phase._nested, phase._engine),
        binding=phase._binding,
        runtime=phase._runtime,
        bound=phase._bound,
        material=phase._material,
    )
    if at < phase._finished_at:
        preview._fail("保存时钟不能倒退后复用实际回链准备。")
    return at


def prepare_write_review(s, ctx, command, product, payload) -> tuple[WritePhase, dict]:
    """Return exact old review once, inside common's NEW-write material phase."""
    uow = preview._uow(s)
    binding, runtime = preview._binding(s, ctx, command, product, payload), _runtime(s)
    if not payload.confirmation_token:
        raise DomainError("CONFIRMATION_REQUIRED", "实际回链须持原共同确认载荷。")
    bound = link._load(s, ctx, command, product, payload)
    if bound.original is not None:
        raise DomainError("REPLAY_REQUIRED", "已有固定回链，请由共同重放核对原回执。")
    material = preview._material(bound, ctx, product, payload)
    args = dict(uow=uow, binding=binding, runtime=runtime, bound=bound, material=material)
    _assert_binding(s, ctx, command, product, payload, **args)
    link._new_write(s, ctx, command, product, payload, bound)
    _assert_binding(s, ctx, command, product, payload, **args)
    review = deepcopy(link._review(command, payload, bound))
    finished = _assert_binding(s, ctx, command, product, payload, **args)
    phase = object.__new__(WritePhase)
    for name, value in (
        ("_session", s),
        ("_transaction", uow[0]),
        ("_nested", uow[1]),
        ("_engine", uow[2]),
        ("_product", product),
        ("_binding", binding),
        ("_runtime", runtime),
        ("_bound", bound),
        ("_material", material),
        ("_review_sha256", digest(review)),
        ("_finished_at", finished),
        ("_spent", False),
    ):
        object.__setattr__(phase, name, value)
    return phase, review


def _proof(s, ctx, command, product, payload, phase):
    actual = phase._bound.proof_callback(s, ctx, command, product, payload)
    if not isinstance(actual, UUID):
        raise DomainError("INTEGRATION_REQUIRED", "共同实际证明必须返回真实已消费UUID。", 503)
    # A random UUID returned by a callback cannot establish the actual common
    # consumer's same-transaction marker or its locked, current Confirmation.
    marker_id = host.require_consumed_proof(s, ctx, command, payload, tier="T1")
    if not isinstance(marker_id, UUID) or actual != marker_id:
        raise DomainError("NAMED_APPROVAL_REQUIRED", "回链证明须等于本事务实际共同消费证明。")
    proof = s.scalar(
        select(Confirmation)
        .where(
            Confirmation.id == actual,
            Confirmation.tenant_id == ctx.tenant_id,
            Confirmation.product_id == product.id,
            Confirmation.subject_id == product.id,
            Confirmation.actor_id == ctx.actor_id,
            Confirmation.operation == link.OPERATION,
            Confirmation.revision == product.revision,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not isinstance(proof, Confirmation):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "当前已消费回链证明缺失。")
    state = inspect(proof)
    if (
        state.session is not s
        or state.persistent is not True
        or proof.consumed is not True
        or proof.token_hash != digest(payload.confirmation_token)
        or proof.payload_digest != material_digest(ctx, command, payload, link)
        or digest(proof.snapshot) != phase._review_sha256
    ):
        raise DomainError(
            "CONFIRMATION_SCOPE_CHANGED", "实际已消费证明与准备的完整实质预览不一致。"
        )
    return proof


def _proof_deadline(proof, at):
    expiry = proof.expires_at
    if (
        not isinstance(expiry, datetime)
        or expiry.tzinfo is None
        or expiry.utcoffset() is None
        or expiry <= at
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "最终实际回链共同证明已经到期。")


def apply_prepared_write(s, ctx, command, product, payload, phase: WritePhase):
    """Refresh owners, capture actual save clock, assert consumed proof, return row."""
    if type(phase) is not WritePhase:
        raise DomainError("INTEGRATION_REQUIRED", "没有本次实际新写准备对象。", 503)
    if phase._spent:
        preview._fail("实际回链准备仅限一次尝试，失败后也不能重用。")
    object.__setattr__(phase, "_spent", True)
    _assert_phase(s, ctx, command, product, payload, phase)
    bound = phase._bound
    link._refresh(s, ctx, command, product, payload, bound)
    _assert_phase(s, ctx, command, product, payload, phase)
    saved_at = preview._clock()  # after ALL owner/bytes I/O, not prepare/Confirmation time
    if saved_at < phase._finished_at:
        preview._fail("实际保存钟早于本次真实准备完成。")
    proof = _proof(s, ctx, command, product, payload, phase)
    final_at = _assert_phase(s, ctx, command, product, payload, phase)
    if final_at < saved_at:
        preview._fail("共同证明核对后实际时钟不能早于捕获的保存钟。")
    _proof_deadline(proof, final_at)
    basis = bound.resolution.basis
    row = RemediationLinkRecord(
        id=uuid4(),
        created_at=saved_at,
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=basis.scope.project_id,
        issue_id=basis.issue_id,
        issue_version_id=basis.issue_version_id,
        issue_revision=basis.issue_revision,
        capa_id=basis.capa_id,
        action_id=payload.action_id,
        owner_id=ctx.requester_id,
        writer_id=ctx.actor_id,
        visibility=bound.visibility,
        purpose=basis.purpose,
        nature=basis.nature,
        revision=1,
        basis_snapshot=basis.model_dump(mode="json"),
        basis_sha256=basis.basis_sha256,
        input_snapshot={
            **link.semantic(payload),
            "shared_proof": {"id": str(proof.id), "tier": "T1"},
        },
        output_snapshot=bound.resolution.model_dump(mode="json"),
        resolution_sha256=bound.resolution.resolution_sha256,
        authority_snapshot=deepcopy(bound.authority),
        policy_snapshot=deepcopy(bound.policy),
        sources=[source.model_dump(mode="json") for source in bound.sources],
        required_source_read_set=deepcopy(bound.reads),
        source_basis=deepcopy(bound.source_basis),
        intent_digest=link._intent(ctx, command, payload),
        reason=payload.reason,
    )
    final_at = _assert_phase(s, ctx, command, product, payload, phase)
    if final_at < saved_at:
        preview._fail("构造回链后实际时钟不能早于捕获的保存钟。")
    _proof_deadline(proof, final_at)
    return row, "capa_remediation_link", row.visibility
