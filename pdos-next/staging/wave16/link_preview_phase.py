"""Staged, single-call preview preparation; no route, writer or shared-proof cache.

The common caller must already own its Product gate and normal principal/source
checks. A phase comes only from the actual Link loader. Its positive material is
not authorization: preview_prepared still calls the real new-write/CAS/freshness
path, and checks the caller/UOW/material again after that owner I/O.
"""

from datetime import UTC, datetime

from pdos_next.contracts import Command
from pdos_next.domain.capa_verification import commands as link
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.capa_verification.schemas import FollowupLinkPayload, ResolvedOutputs
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.quality_result_bridge import _runtime_stamp
from pdos_next.service import Context, digest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

OPERATION = "quality.capa.followup.link"


class PreviewPhase:
    """Opaque, single-use local frame, never a serialized access/proof token."""

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
        "_finished_at",
        "_spent",
    )

    def __init__(self, *args, **kwargs):
        raise TypeError("Only prepare_preview creates an in-process PreviewPhase")

    def __setattr__(self, name, value):
        raise AttributeError("PreviewPhase is opaque and immutable")

    def __reduce__(self):
        raise TypeError("PreviewPhase cannot leave its caller UOW")

    def __copy__(self):
        raise TypeError("PreviewPhase cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("PreviewPhase cannot be copied")

    def __repr__(self):
        return "<PreviewPhase: in-process preview only>"


def _fail(detail):
    raise DomainError("SOURCE_STALE", detail)


def _uow(s):
    if not isinstance(s, Session):
        raise DomainError("INTEGRATION_REQUIRED", "预览须由实际宿主Session办理。", 503)
    transaction, nested = s.get_transaction(), s.get_nested_transaction()
    if transaction is None or transaction.is_active is not True:
        raise DomainError("INTEGRATION_REQUIRED", "预览需要实际活动事务。", 503)
    if nested is not None and nested.is_active is not True:
        raise DomainError("INTEGRATION_REQUIRED", "预览子事务不可用。", 503)
    return transaction, nested, s.get_bind()


def _binding(s, ctx, command, product, payload):
    if not isinstance(ctx, Context) or ctx.run_id is not None or ctx.actor_id != ctx.requester_id:
        raise DomainError("NAMED_PERSON_REQUIRED", "回链预览须由当前具名本人办理。", 403)
    if type(command) is not Command or type(payload) is not FollowupLinkPayload:
        raise DomainError("INVALID_REQUEST", "须传入完整已验证命令与回链载荷。", 422)
    checked = Command.model_validate(command.model_dump(mode="json"))
    if (
        checked.operation != OPERATION
        or FollowupLinkPayload.model_validate(checked.payload) != payload
    ):
        raise DomainError("FORBIDDEN_SCOPE", "预览操作或完整载荷不匹配。", 403)
    if type(product) is not Product:
        raise DomainError("INTEGRATION_REQUIRED", "预览缺少实际宿主产品对象。", 503)
    state = inspect(product)
    if state.session is not s or state.persistent is not True:
        raise DomainError("INTEGRATION_REQUIRED", "产品须为本Session实际已保存对象。", 503)
    if product.tenant_id != ctx.tenant_id or checked.product_id != product.id:
        raise DomainError("FORBIDDEN_SCOPE", "预览产品或租户范围不匹配。", 403)
    return digest(
        {
            "context": vars(ctx),
            "command": checked.model_dump(mode="json"),
            "payload": payload.model_dump(mode="json"),
            "product": {c.key: getattr(product, c.key) for c in Product.__table__.columns},
            "material": link.semantic(payload),
        }
    )


def _runtime(s):
    engine = s.get_bind()
    policies = getattr(engine, "_pdos_quality_policy_issuers", {})
    return digest(
        {
            "result_runtime": _runtime_stamp(s),
            "policy_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
            "policy_issuers": {key: [id(value), value.epoch] for key, value in policies.items()},
            "proof": id(getattr(engine, "_pdos_capa_link_consumed_proof", None)),
            "callbacks": [
                id(link._load),
                id(link._new_write),
                id(link._refresh),
                id(link._review),
                id(link._deadlines),
                id(link.owners.load_exact_followup_basis),
                id(link.owners.load_followup_basis),
                id(link.owners.resolve_followup_outputs),
                id(link.owners.now),
                id(link.professional.assess),
                id(link.policy.assess),
            ],
        }
    )


def _material(bound, ctx, product, payload):
    if type(bound) is not link.Bound or type(bound.resolution) is not ResolvedOutputs:
        raise DomainError("INTEGRATION_REQUIRED", "回链预览缺少实际loader的typed结果。", 503)
    resolution = bound.resolution
    if (
        resolution.basis.scope.tenant_id != ctx.tenant_id
        or resolution.basis.scope.product_id != product.id
        or resolution.basis.issue_id != payload.issue_id
        or resolution.basis.capa_id != payload.capa_id
        or resolution.action_id != payload.action_id
        or tuple(output.ref for output in resolution.outputs) != payload.output_refs
        or resolution.owner_id != ctx.requester_id
        or bound.visibility not in {"private", "product"}
        or (resolution.visibility == "private" and bound.visibility != "private")
    ):
        _fail("回链准备结果不能改换真实范围、措施、输出或受众。")
    original = bound.original
    if original is not None and type(original) is not RemediationLinkRecord:
        raise DomainError("INTEGRATION_REQUIRED", "旧回链须是实际保存的领域对象。", 503)
    return digest(
        {
            "resolution": resolution.model_dump(mode="json"),
            "authority": bound.authority,
            "policy": bound.policy,
            "sources": [source.model_dump(mode="json") for source in bound.sources],
            "reads": bound.reads,
            "source_basis": bound.source_basis,
            "visibility": bound.visibility,
            "original": {
                c.key: getattr(original, c.key) for c in RemediationLinkRecord.__table__.columns
            }
            if original is not None
            else None,
            "proof_callback": id(bound.proof_callback),
        }
    )


def _clock():
    at = link.owners.now()
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        _fail("宿主读取时钟须含明确时区。")
    return at.astimezone(UTC)


def _after_io(s, ctx, command, product, payload, *, uow, binding, runtime, bound=None):
    current = _uow(s)
    if any(before is not after for before, after in zip(uow, current, strict=True)):
        _fail("预览读取期间Session事务、子事务或宿主连接已改变。")
    if _binding(s, ctx, command, product, payload) != binding or _runtime(s) != runtime:
        _fail("预览读取期间完整命令、身份、产品或签发入口发生变化。")
    at = _clock()
    if bound is not None:
        # The real loader/new-write path already performed fresh owner checks.
        # Recheck actual professional/policy deadlines after our final binding work.
        link._deadlines(bound.authority, bound.policy)
    return at


def prepare_preview(s, ctx, command, product, payload) -> PreviewPhase:
    """Prepare once inside common preview's already-held Product gate, no writes."""
    uow, binding, runtime = _uow(s), _binding(s, ctx, command, product, payload), _runtime(s)
    bound = link._load(s, ctx, command, product, payload)
    material = _material(bound, ctx, product, payload)
    finished = _after_io(
        s, ctx, command, product, payload, uow=uow, binding=binding, runtime=runtime, bound=bound
    )
    phase = object.__new__(PreviewPhase)
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
        ("_finished_at", finished),
        ("_spent", False),
    ):
        object.__setattr__(phase, name, value)
    return phase


def _assert_phase(s, ctx, command, product, payload, phase):
    if phase._session is not s or phase._product is not product:
        _fail("预览不能跨Session或改换宿主产品对象。")
    # Check before ORM attribute access: rollback may expire objects, and must
    # never cause a stale phase to re-load material in a different transaction.
    current = _uow(s)
    expected = (phase._transaction, phase._nested, phase._engine)
    if any(before is not after for before, after in zip(expected, current, strict=True)):
        _fail("预览不能跨主事务、子事务或宿主连接复用。")
    if _material(phase._bound, ctx, product, payload) != phase._material:
        _fail("已核对回链Bound的完整材料已改变。")
    at = _after_io(
        s,
        ctx,
        command,
        product,
        payload,
        uow=(phase._transaction, phase._nested, phase._engine),
        binding=phase._binding,
        runtime=phase._runtime,
        bound=phase._bound,
    )
    if at < phase._finished_at:
        _fail("宿主时钟不能倒退后复用预览准备。")


def preview_prepared(s, ctx, command, product, payload, phase: PreviewPhase) -> dict:
    """Render once, retaining the real Current CAS and fresh owner recheck."""
    if type(phase) is not PreviewPhase:
        raise DomainError("INTEGRATION_REQUIRED", "没有本次实际预览准备对象。", 503)
    if phase._spent:
        _fail("预览准备只能在一次调用内使用，失败后也须重新准备。")
    object.__setattr__(phase, "_spent", True)
    _assert_phase(s, ctx, command, product, payload, phase)
    # This still loads the current CAPA basis and calls real _refresh after owner I/O.
    link._new_write(s, ctx, command, product, payload, phase._bound)
    _assert_phase(s, ctx, command, product, payload, phase)
    review = link._review(command, payload, phase._bound)
    _assert_phase(s, ctx, command, product, payload, phase)
    return review
