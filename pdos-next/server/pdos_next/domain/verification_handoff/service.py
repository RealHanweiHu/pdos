"""Physical handoff in the common UOW; no parallel request state machine or commits.

Actual applicability is an independent, immutable per-sample/item qualified fact.
Neither a populated planned method nor an old positive assessment proves current
actual applicability. Readiness, actual configuration, sources and original
reviewer authority are rechecked before writes and receipt replays.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.supply_execution.service import _human, _read_evidence, _sources
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification.rules import (
    accepted_coverage,
    check_coverage,
    coverage_gaps,
    document_gaps,
    pairs,
)
from pdos_next.domain.verification_execution import service as preparation
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.adapters import (
    METHOD_POSITION,
    PROFESSIONAL_PREFIX,
    authority_dto,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationRequest,
    MethodApplicability,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, OriginalSecurity, Principal, Product, now
from pdos_next.schemas.verification.contracts import (
    Coverage,
    HandoffAccept,
    HandoffOffer,
    HandoffReturn,
)
from pdos_next.service import Context, digest, require_access

from .adapters import HandoffCommands, InspectedSamples, kernel
from .models import (
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
    VerificationHandoffFact,
)
from .schemas import AcceptPayload, ActualMethodPreparePayload, OfferPayload

OPERATIONS = {
    "actual_method_prepare": "verification.actual_method.prepare",
    "handoff_offer": "verification.handoff.offer",
    "handoff_accept": "verification.handoff.accept",
    "handoff_return": "verification.handoff.return",
}
EFFECT = "记录固定实物与逐项交接范围；不承诺开测、不预约资源、不消耗样件。"
FUTURE_TIMES = ("promised_start", "actual_start", "preliminary_result", "final_result", "disposed")


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    for key in ("sources", "samples", "coverage", "returned_coverage", "assessments"):
        if key in value:
            for item in value[key]:
                if isinstance(item, dict) and "sources" in item:
                    item["sources"].sort(key=lambda ref: json.dumps(ref, sort_keys=True))
            value[key].sort(key=lambda item: json.dumps(item, sort_keys=True))
    if len(json.dumps(value, ensure_ascii=False).encode()) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "交接输入超过1MB上限。", 422)
    return value


def request_subject(payload):
    return payload.request_id


def replay_subject(*args):
    return None  # Common semantic Receipt/RequestKey replay, after validate current guards.


def event_source(reference):
    return preparation._source(reference)


def _refs(payload):
    refs = list(payload.sources)
    if isinstance(payload, ActualMethodPreparePayload):
        refs.extend(ref for item in payload.assessments for ref in item.sources)
    return [ref.model_dump(mode="json") for ref in refs]


def _merge_refs(*groups):
    values = {json.dumps(ref, sort_keys=True): ref for group in groups for ref in group}
    return [values[key] for key in sorted(values)]


def _basis(s, ctx, product_id, reads, references):
    refs, private = _sources(s, ctx, product_id, reads, references)
    fixed = []
    for key in sorted(refs):
        value = refs[key].model_dump(mode="json")
        value.pop("valid_until", None)  # Consumer Grant is a separate current ACL guard.
        fixed.append(value)
    security = []
    for read in reads:
        artifact = s.get(Artifact, UUID(read["artifact_id"]))
        if artifact.original_id:
            state = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id == product_id,
                    OriginalSecurity.original_id == artifact.original_id,
                )
            )
            security.append(
                {
                    "original_id": str(artifact.original_id),
                    "epoch": state.epoch if state else None,
                    "source_state": state.source_state if state else None,
                    "disposition": state.disposition if state else None,
                }
            )
    return {"refs": fixed, "security": sorted(security, key=lambda v: v["original_id"])}, private


def _method_pointer(s, ctx, product_id, request_id, sample_id, item_id, *, lock=False):
    query = select(ActualMethodCurrent).where(
        ActualMethodCurrent.tenant_id == ctx.tenant_id,
        ActualMethodCurrent.product_id == product_id,
        ActualMethodCurrent.request_id == request_id,
        ActualMethodCurrent.sample_id == sample_id,
        ActualMethodCurrent.item_id == item_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row = s.get(ActualMethodApplicability, pointer.assessment_id)
    if (
        row is None
        or row.revision != pointer.assessment_revision
        or (
            row.tenant_id != ctx.tenant_id
            or row.product_id != product_id
            or row.request_id != request_id
            or row.sample_id != sample_id
            or row.item_id != item_id
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "实际适用当前指针无法核对。")
    return pointer, row


def _inspect(s, ctx, product_id, request, sample, *, write=False, read_context=None):
    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.sample_handoff.service import inspect_sample

    # The authoritative inspector validates the complete immutable physical chain.
    # This local read only adds the visibility needed by the enclosing request.
    sample_row = s.scalar(
        select(SampleUnit).where(
            SampleUnit.id == sample.id,
            SampleUnit.tenant_id == ctx.tenant_id,
            SampleUnit.product_id == product_id,
        )
    )
    if sample_row is None or (
        sample_row.visibility == "private" and sample_row.owner_id != ctx.requester_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "样件不在当前可见产品范围。", 403)
    kwargs = {"at": now(), "write": write}
    if read_context is not None:
        kwargs["read_context"] = read_context
    value = inspect_sample(
        s,
        ctx,
        product_id,
        {"id": sample.id, "revision": sample.revision},
        request.purpose,
        **kwargs,
    )
    actual, current, build = value["actual_configuration"], value["sample"], value["build"]
    if (
        str(sample.id) != current["id"]
        or sample.revision != current["revision"]
        or str(sample.actual_configuration.id) != actual["id"]
        or sample.actual_configuration.revision != actual["revision"]
        or str(sample.build_id) != build["id"]
        or sample.build_id != request.build.id
        or sample.cavity != current.get("cavity")
        or str(request.scope.project_id) != build["project_id"]
    ):
        raise DomainError("SOURCE_CHANGED", "样件身份或实际配置不匹配固定范围。")
    return {**value, "visibility": sample_row.visibility}


@dataclass
class Bound:
    previous: object
    base: object
    build: object
    authority: dict
    references: list
    reads: list
    source_basis: dict
    samples: dict
    methods: dict
    visibility: str
    at: datetime
    # This object is constructed anew by each validate/preview/apply phase.
    # Only successful original-reviewer proofs may be reused inside that phase.
    proofs: dict = field(default_factory=dict, repr=False)


def _proof_stamp(s, ctx, product_id, row):
    """Fresh scalar guards; no ORM identity-map authority or cross-phase memo."""
    from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
    from pdos_next.domain.sample_handoff.service import ReadContext

    identities = {ctx.actor_id, ctx.requester_id, row.owner_id}
    rows = s.execute(
        select(
            Principal.id,
            Principal.kind,
            Principal.active,
            Principal.access_epoch,
            Grant.id,
            Grant.can_write,
            Grant.access_epoch,
            Grant.expires_at,
        )
        .join(
            Grant,
            (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.id.in_(identities),
            Grant.product_id == product_id,
        )
        .order_by(Principal.id)
    ).all()
    epoch = s.scalar(
        select(Product.lifecycle_epoch).where(
            Product.tenant_id == ctx.tenant_id, Product.id == product_id
        )
    )
    boundaries = s.execute(
        select(ProfessionalFact.id, ProfessionalFact.valid_from, ProfessionalFact.valid_until)
        .join(ProfessionalCurrent, ProfessionalCurrent.fact_id == ProfessionalFact.id)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == product_id,
            ProfessionalCurrent.project_id == row.project_id,
            ProfessionalCurrent.subject_id == row.owner_id,
        )
        .order_by(ProfessionalFact.id)
    ).all()
    # Same exact scope predicate as professional_authority.assess; its facts
    # and pointers require project_id, while only issuer configuration may be
    # product-wide. Sample time after ALL SQL, including upcoming fact boundaries.
    at = now()
    valid = {
        value[0]
        for value in rows
        if value[1] == "human" and value[2] and value[5] and value[7] > at
    }
    if not {ctx.actor_id, ctx.requester_id} <= valid:
        raise DomainError("FORBIDDEN_SCOPE", "当前本人产品权限已失效。", 403)
    if row.owner_id not in valid:
        raise DomainError("SOURCE_STALE", "原具名核对人的身份或写权限已变化。")
    # An absent transaction or pending local writes disables reuse, rather than
    # accidentally spanning a flush or a different command phase.
    transaction = s.get_transaction()
    if epoch is None or transaction is None or s.new or s.dirty or s.deleted:
        return None
    return (
        id(s),
        id(transaction),
        ctx.tenant_id,
        product_id,
        ctx.actor_id,
        ctx.requester_id,
        ctx.run_id,
        epoch,
        tuple(tuple(value) for value in rows),
        tuple((identity, begin, end, begin <= at < end) for identity, begin, end in boundaries),
        ReadContext._runtime(s),
        min(
            [value[7] for value in rows]
            + [
                boundary
                for _, begin, end in boundaries
                for boundary in (begin, end)
                if boundary > at
            ]
        ),
    )


def _proof_key(kind, row, request, sample=None, value=None):
    return (
        kind,
        digest({column.key: getattr(row, column.key) for column in row.__table__.columns}),
        digest(request.model_dump(mode="json")),
        digest(sample.model_dump(mode="json")) if sample is not None else None,
        digest(value) if value is not None else None,
    )


def _proof_deadline(row, stamp=None):
    value = row.authority_snapshot.get("valid_until")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        return (
            min(at, stamp[-1]) if at and at.tzinfo and stamp else at if at and at.tzinfo else None
        )
    except (TypeError, ValueError):
        return None


def _bound_proof(s, ctx, product_id, bound, row, key, check, sources):
    """Reuse professional traversal only while its exact successful proof is current.

    Every hit rechecks original bytes/source ACL, both signers' fresh scalar
    access, scope epoch, issuer registry and expiry. No failure is memoized.
    """
    stamp = _proof_stamp(s, ctx, product_id, row)
    saved = bound.proofs.get(key)
    if stamp is not None and saved and saved[0] == stamp and now() < saved[1]:
        sources()
        if _proof_stamp(s, ctx, product_id, row) == stamp and now() < saved[1]:
            return
    check()
    deadline = _proof_deadline(row, stamp)
    final_stamp = _proof_stamp(s, ctx, product_id, row)
    if (deadline and now() >= deadline) or (stamp is not None and final_stamp != stamp):
        raise DomainError("SOURCE_STALE", "专业核对期间资格时效或安全版本已变化，请重新核对。")
    if stamp is not None and deadline:
        bound.proofs[key] = (stamp, deadline)


def _bound_method_check(s, ctx, product_id, bound, row):
    _bound_proof(
        s,
        ctx,
        product_id,
        bound,
        row,
        _proof_key("planned", row, bound.base),
        lambda: front._method_check(s, ctx, product_id, row, bound.base),
        lambda: _sources(s, ctx, product_id, row.required_source_read_set, row.sources),
    )


def _bound_actual_check(s, ctx, product_id, bound, sample, value, row):
    _actual_binding(s, ctx, product_id, bound.base, sample, value, row)
    if row.status != "applicable":
        raise DomainError("ACTUAL_METHOD_UNKNOWN", "实际配置方法适用仍未知或不适用。")

    def sources():
        basis, _ = _basis(s, ctx, product_id, row.required_source_read_set, row.sources)
        if basis != row.source_basis:
            raise DomainError("SOURCE_STALE", "原实际适用来源安全版本已变化。")

    _bound_proof(
        s,
        ctx,
        product_id,
        bound,
        row,
        _proof_key("actual", row, bound.base, sample, value),
        lambda: _actual_check(s, ctx, product_id, bound.base, sample, value, row),
        sources,
    )


def _selected(payload, request):
    if isinstance(payload, ActualMethodPreparePayload):
        samples = {a.sample.id: a.sample for a in payload.assessments}
        coverage = tuple(
            Coverage(sample_id=a.sample.id, item_id=a.item_id) for a in payload.assessments
        )
    elif isinstance(payload, OfferPayload):
        samples, coverage = {sample.id: sample for sample in payload.samples}, payload.coverage
    else:
        selected = {
            c.sample_id for c in (*payload.coverage, *getattr(payload, "returned_coverage", ()))
        }
        samples = {sample.id: sample for sample in request.samples if sample.id in selected}
        coverage = tuple((*payload.coverage, *getattr(payload, "returned_coverage", ())))
    check_coverage(request, coverage, tuple(samples.values()))
    return samples, coverage


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "交接不在当前产品范围。", 403)
    previous = front._version(
        s, ctx, product.id, payload.request_id, payload.expected_request_revision
    )
    request = front._snapshot(previous)
    build = front._build(s, ctx, product.id, request.build.id)
    _, engineering, manufacturing, planned_reads = front._linked(s, ctx, product.id, build)
    if (
        request.build.revision != build.revision
        or str(request.build.engineering_configuration.id) != engineering["id"]
        or request.build.engineering_configuration.revision != engineering["revision"]
        or str(request.build.manufacturing_configuration.id) != manufacturing["id"]
        or request.build.manufacturing_configuration.revision != manufacturing["revision"]
    ):
        raise DomainError("SOURCE_CHANGED", "固定计划双配置已经变化。")
    authority = front._assess(
        s, ctx, product.id, build.project_id, command.operation, request.purpose, write=True
    )
    refs = _merge_refs(previous.sources, _refs(payload))
    reads = _merge_reads(
        planned_reads,
        previous.required_source_read_set,
        refs,
        authority["required_source_read_set"],
    )
    sample_refs, coverage = _selected(payload, request)
    inspected, methods = {}, {}
    for sample in sorted(sample_refs.values(), key=lambda v: str(v.id)):
        value = _inspect(s, ctx, product.id, request, sample, write=True)
        inspected[sample.id] = value
        refs = _merge_refs(refs, value["source_refs"])
        reads = _merge_reads(reads, value["required_source_read_set"], refs)
    if not isinstance(payload, ActualMethodPreparePayload):
        for cover in coverage:
            _, row = _method_pointer(s, ctx, product.id, request.id, cover.sample_id, cover.item_id)
            methods[(cover.sample_id, cover.item_id)] = row
            if row:
                refs = _merge_refs(refs, row.sources)
                reads = _merge_reads(reads, row.required_source_read_set, refs)
    source_basis, private = _basis(s, ctx, product.id, reads, refs)
    if private and previous.visibility == "product":
        raise DomainError("FORBIDDEN_SCOPE", "私有实物或引用不能加入共享请求。", 403)
    if (
        any(v["visibility"] == "private" for v in inspected.values())
        and previous.visibility == "product"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "私有实物不能扩大受众。", 403)
    if require_reads:
        supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
        if any(supplied.get(read["artifact_id"]) != read["expected_revision"] for read in reads):
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "交接须完整固定来源、实物与专业事实读集。"
            )
    return Bound(
        previous,
        request,
        build,
        authority,
        refs,
        reads,
        source_basis,
        inspected,
        methods,
        previous.visibility,
        now(),
    )


def _authorize(bound, ctx, operation):
    a = bound.authority
    if a["authorized"] is not True or a["qualified"] is not True:
        raise DomainError("QUALIFICATION_REQUIRED", "当前范围缺少本操作的具名职责或专业资格。", 403)
    expected = (
        {"engineering", "manufacturing"}
        if operation == OPERATIONS["handoff_offer"]
        else {"quality"}
    )
    if not set(a["roles"]) & expected or a["subject_id"] != str(ctx.requester_id):
        raise DomainError("FORBIDDEN_OPERATION", "本操作须当前本人对应专业职责。", 403)


def _execution(s, ctx, product_id, build, *, read_context=None):
    from pdos_next.domain.build_start import service as starts
    from pdos_next.domain.build_start.models import BuildStart

    if read_context is not None:
        from pdos_next.domain.sample_handoff.service import inspect_execution

        value = inspect_execution(s, ctx, product_id, build.id, read_context=read_context)
        if (
            not value
            or value["execution_status"] != "executing"
            or value["execution_qualification"] != "limited_current"
            or value["stop_required"]
        ):
            raise DomainError(
                "ACTUAL_SAMPLE_REQUIRED", "当前有效开工事实未满足，已观察样件不构成开工授权。"
            )
        return value

    # Consumer visibility precedes historical owner's read-only authority recheck.
    starts._build(s, ctx, product_id, build.id)
    saved = starts._start(s, ctx, product_id, build.id)
    if saved is None:
        raise DomainError("ACTUAL_SAMPLE_REQUIRED", "当前Build没有真实开工记录。")
    saved = starts._row(s, ctx, product_id, BuildStart, saved.id)
    if _read_evidence(s, ctx, product_id, saved) != "current":
        raise DomainError("SOURCE_STALE", "原开工固定来源已变化。")
    historical = Context(ctx.tenant_id, saved.owner_id, saved.owner_id)
    value = starts.execution_projection(s, historical, product_id, build.id)
    if (
        not value
        or value["execution_status"] != "executing"
        or value["execution_qualification"] != "limited_current"
        or value["stop_required"]
    ):
        raise DomainError(
            "ACTUAL_SAMPLE_REQUIRED", "当前有效开工事实未满足，已观察样件不构成开工授权。"
        )
    return value


def _actual_binding(s, ctx, product_id, request, sample, value, row, *, parent=None):
    if row is None:
        raise DomainError("ACTUAL_METHOD_UNKNOWN", "该实际样件与测试项尚无独立适用核对。")
    item = next((item for item in request.items if item.id == row.item_id), None)
    snap = row.assessment_snapshot
    if (
        row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or row.request_id != request.id
        or row.project_id != request.scope.project_id
        or row.sample_id != sample.id
        or row.sample_revision != sample.revision
        or row.actual_configuration_id != sample.actual_configuration.id
        or row.actual_configuration_revision != sample.actual_configuration.revision
        or row.build_id != request.build.id
        or item is None
        or row.method_digest != digest(item.model_dump(mode="json"))
        or row.snapshot_sha256 != digest(snap)
        or snap["sample"] != sample.model_dump(mode="json")
        or snap["fixed_item"] != item.model_dump(mode="json")
        or snap["actual_configuration"] != value["actual_configuration"]
        or row.authority_snapshot["subject_id"] != str(row.owner_id)
        or row.authority_snapshot["operation"] != OPERATIONS["actual_method_prepare"]
        or row.authority_snapshot["purpose"] != request.purpose
    ):
        raise DomainError("INTEGRITY_MISMATCH", "实际适用事实与固定配置/方法/本人无法核对。")
    if row.visibility == "private" and row.owner_id != ctx.requester_id:
        raise DomainError("SOURCE_UNAVAILABLE", "实际适用事实不在当前受众。", 403)
    parent = parent or front._row(s, ctx, product_id, row.request_version_id)
    if parent.request_id != request.id or parent.revision != row.request_revision:
        raise DomainError("INTEGRITY_MISMATCH", "实际适用事实的审阅请求版本不一致。")


def _actual_check(
    s, ctx, product_id, request, sample, value, row, *, positive=True, retained_at=None
):
    _actual_binding(s, ctx, product_id, request, sample, value, row)
    basis, _ = _basis(s, ctx, product_id, row.required_source_read_set, row.sources)
    if basis != row.source_basis:
        raise DomainError("SOURCE_STALE", "原实际适用来源安全版本已变化。")
    if not front._recheck(
        s, ctx, product_id, row.project_id, row.authority_snapshot, at=retained_at
    )["current"]:
        raise DomainError("SOURCE_STALE", "原品质核对人的专业资格已变化。")
    if positive and row.status != "applicable":
        raise DomainError("ACTUAL_METHOD_UNKNOWN", "实际配置方法适用仍未知或不适用。")


def _current_guards(s, ctx, command, product, payload, bound):
    _authorize(bound, ctx, command.operation)
    if isinstance(payload, (OfferPayload, AcceptPayload)):
        _execution(s, ctx, product.id, bound.build)
    for doc in bound.base.documents:
        if doc.id.startswith(PROFESSIONAL_PREFIX) and doc.source:
            row = s.get(MethodApplicability, doc.source.id)
            if row is None or doc.source.kind != "domain" or doc.source.position != METHOD_POSITION:
                raise DomainError("SOURCE_UNAVAILABLE", "固定专业适用记录不存在。")
            _bound_method_check(s, ctx, product.id, bound, row)
    if isinstance(payload, AcceptPayload):
        selected = pairs(payload.coverage)
        samples = {sample.id: sample for sample in bound.base.samples}
        for key in sorted(selected, key=lambda k: (str(k[0]), k[1])):
            value = bound.samples[key[0]]
            if value["availability"] != "ready":
                raise DomainError("SAMPLE_UNAVAILABLE", "未知或暂缓样件不能品质接收。")
            _bound_actual_check(
                s, ctx, product.id, bound, samples[key[0]], value, bound.methods[key]
            )
    owner = getattr(payload, "next_owner_id", None)
    if owner is not None:
        _assignee(s, ctx, product.id, bound.build.project_id, owner)
    original_model = (
        ActualMethodBatch
        if isinstance(payload, ActualMethodPreparePayload)
        else VerificationHandoffFact
    )
    intent = digest(
        {"operation": command.operation, "payload": semantic(payload), "actor": ctx.requester_id}
    )
    original = s.scalar(
        select(original_model).where(
            original_model.tenant_id == ctx.tenant_id,
            original_model.product_id == product.id,
            original_model.intent_digest == intent,
        )
    )
    if original is not None:
        original_basis, _ = _basis(
            s, ctx, product.id, original.required_source_read_set, original.sources
        )
        if (
            original_basis != original.source_basis
            or not front._recheck(
                s, ctx, product.id, original.project_id, original.authority_snapshot
            )["current"]
        ):
            raise DomainError("SOURCE_STALE", "原交接或实际适用意图的权威来源已变化。")


def validate(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _current_guards(s, ctx, command, product, payload, bound)


def _new_write(s, ctx, command, product, payload, bound):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品范围版本已变化。")
    if not isinstance(payload, ActualMethodPreparePayload):
        from pdos_next.domain.verification_launch.models import VerificationRunIdentity

        if s.scalar(
            select(VerificationRunIdentity.id).where(
                VerificationRunIdentity.tenant_id == ctx.tenant_id,
                VerificationRunIdentity.product_id == product.id,
                VerificationRunIdentity.request_id == payload.request_id,
            )
        ):
            raise DomainError(
                "REQUEST_RUN_SCOPE_FIXED",
                "此请求已固定完整Run范围，新增交接范围须进入独立后续请求。",
            )
    pointer, latest = front._current(s, ctx, product.id, payload.request_id, lock=True)
    if (
        latest is None
        or latest.id != bound.previous.id
        or latest.revision != payload.expected_request_revision
    ):
        raise DomainError("VERSION_CONFLICT", "正式请求当前版本已变化。")
    return pointer


def _assignee(s, ctx, product_id, project_id, owner):
    from pdos_next.domain.projects.service import _project

    principal = s.get(Principal, owner)
    if (
        principal is None
        or principal.tenant_id != ctx.tenant_id
        or principal.kind != "human"
        or not principal.active
    ):
        raise DomainError("INVALID_ASSIGNEE", "下一责任人须当前租户有效具名人员。", 403)
    nominated = Context(ctx.tenant_id, owner, owner)
    try:
        require_access(s, nominated, product_id, write=True)
        _project(s, nominated, product_id, project_id)
    except DomainError:
        raise DomainError("INVALID_ASSIGNEE", "下一责任人不在当前项目可办理范围。", 403) from None
    return {"id": str(principal.id), "label": principal.name}


def _child_id(command, key):
    return uuid5(NAMESPACE_URL, f"pdos-verification-handoff:{command.command_id}:{key}")


def _actual_candidates(s, ctx, command, product, payload, bound, *, lock=False):
    rows, pointers = [], []
    execution_checked = False
    accepted = pairs(accepted_coverage(bound.base))
    for item in sorted(payload.assessments, key=lambda a: (str(a.sample.id), a.item_id)):
        if (item.sample.id, item.item_id) in accepted:
            raise DomainError("ACCEPTED_SCOPE_FROZEN", "已接收样件/测试项的实际适用不可改写。")
        pointer, previous = _method_pointer(
            s, ctx, product.id, payload.request_id, item.sample.id, item.item_id, lock=lock
        )
        if (previous.revision if previous else 0) != item.expected_assessment_revision:
            raise DomainError("VERSION_CONFLICT", "实际适用当前版本已变化。")
        fixed_item = next(v for v in bound.base.items if v.id == item.item_id)
        if item.status == "applicable":
            if document_gaps(bound.base, {item.item_id}):
                raise DomainError(
                    "MISSING_REQUIRED_EVIDENCE",
                    "正适用须固定方法、图纸、判据、条件及全部所需资料完整。",
                )
            if not execution_checked:
                # The candidate loop has no effects and already holds the
                # Product gate; re-use this one invocation's Build check only.
                _execution(s, ctx, product.id, bound.build)
                execution_checked = True
        value = bound.samples[item.sample.id]
        snap = {
            "scope": bound.base.scope.model_dump(mode="json"),
            "purpose": bound.base.purpose,
            "build": bound.base.build.model_dump(mode="json"),
            "sample": item.sample.model_dump(mode="json"),
            "fixed_item": fixed_item.model_dump(mode="json"),
            "actual_configuration": value["actual_configuration"],
            "reviewer_id": str(ctx.requester_id),
            "status": item.status,
            "conditions": list(item.conditions),
            "reason": item.reason,
            "sources": [ref.model_dump(mode="json") for ref in item.sources],
        }
        row = ActualMethodApplicability(
            id=_child_id(command, f"pair:{item.sample.id}:{item.item_id}"),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=bound.build.project_id,
            request_id=payload.request_id,
            request_version_id=bound.previous.id,
            request_revision=bound.previous.revision,
            owner_id=ctx.requester_id,
            visibility=bound.visibility,
            revision=item.expected_assessment_revision + 1,
            batch_id=_child_id(command, "batch"),
            sample_id=item.sample.id,
            sample_revision=item.sample.revision,
            build_id=bound.build.id,
            actual_configuration_id=item.sample.actual_configuration.id,
            actual_configuration_revision=item.sample.actual_configuration.revision,
            item_id=item.item_id,
            previous_assessment_id=previous.id if previous else None,
            previous_revision=previous.revision if previous else None,
            status=item.status,
            method_digest=digest(fixed_item.model_dump(mode="json")),
            assessment_snapshot=snap,
            snapshot_sha256=digest(snap),
            authority_snapshot=bound.authority,
            sources=bound.references,
            required_source_read_set=bound.reads,
            source_basis=bound.source_basis,
            created_at=bound.at,
        )
        rows.append(row)
        pointers.append(pointer)
    return rows, pointers


def _actual_apply(s, ctx, command, product, payload, bound):
    rows, pointers = _actual_candidates(s, ctx, command, product, payload, bound, lock=True)
    raw = semantic(payload)
    batch = ActualMethodBatch(
        id=_child_id(command, "batch"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=bound.build.project_id,
        request_id=payload.request_id,
        request_version_id=bound.previous.id,
        request_revision=bound.previous.revision,
        owner_id=ctx.requester_id,
        visibility=bound.visibility,
        revision=1,
        status="prepared",
        input_snapshot=raw,
        assessment_ids=[str(row.id) for row in rows],
        sources=bound.references,
        required_source_read_set=bound.reads,
        source_basis=bound.source_basis,
        authority_snapshot=bound.authority,
        snapshot_sha256=digest(raw),
        intent_digest=digest(
            {"operation": command.operation, "actor": ctx.requester_id, "payload": raw}
        ),
        reason=payload.reason,
        created_at=bound.at,
    )
    s.add(batch)
    s.flush()
    for row in rows:
        s.add(row)
    s.flush()
    for row, pointer in zip(rows, pointers, strict=True):
        if pointer is None:
            s.add(
                ActualMethodCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    request_id=row.request_id,
                    sample_id=row.sample_id,
                    item_id=row.item_id,
                    assessment_id=row.id,
                    assessment_revision=row.revision,
                )
            )
        else:
            pointer.assessment_id, pointer.assessment_revision = row.id, row.revision
    s.flush()
    return batch, "verification_actual_method", bound.visibility


def _payload_kernel(payload):
    if isinstance(payload, OfferPayload):
        return HandoffOffer(samples=payload.samples, coverage=payload.coverage, at=payload.at)
    if isinstance(payload, AcceptPayload):
        return HandoffAccept(
            coverage=payload.coverage,
            returned_coverage=payload.returned_coverage,
            reason=payload.reason,
            next_owner_id=payload.next_owner_id,
            at=payload.at,
        )
    return HandoffReturn(
        coverage=payload.coverage,
        reason=payload.reason,
        next_owner_id=payload.next_owner_id,
        at=payload.at,
    )


def _kernel(s, ctx, command, product, payload, bound, save, *, accepted=False):
    refs = {
        event_source(SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])})): ref
        for ref in bound.references
    }
    selected = pairs(payload.coverage)

    def check_source(scope, source, purpose):
        if scope != bound.base.scope:
            raise DomainError("FORBIDDEN_SCOPE", "来源不在服务器固定范围。", 403)
        if source.kind == "artifact":
            if source not in refs:
                raise DomainError(
                    "MISSING_REQUIRED_EVIDENCE", "事件与方法必须引用固定精确原文位置。"
                )
            return
        if source.kind != "domain":
            raise DomainError("SOURCE_UNAVAILABLE", "未登记来源不能作为交接证据。")
        if source.position == METHOD_POSITION:
            row = s.get(MethodApplicability, source.id)
            if row is None or source.revision != 1:
                raise DomainError("SOURCE_UNAVAILABLE", "原计划专业适用证明不存在。")
            _bound_method_check(s, ctx, product.id, bound, row)
            return
        if source.position == "actual-sample":
            if source.id not in bound.samples:
                raise DomainError("SOURCE_UNAVAILABLE", "实际样件不在本次核对范围。")
            sample = next(
                (
                    sample
                    for sample in (
                        payload.samples if isinstance(payload, OfferPayload) else bound.base.samples
                    )
                    if sample.id == source.id
                ),
                None,
            )
            if sample is None or source.revision != sample.revision:
                raise DomainError("SOURCE_CHANGED", "实际样件来源版本变化。")
            return
        if source.position == "sample-readiness":
            if any(
                value.get("current_readiness")
                and value["current_readiness"].get("source_ref") == source.model_dump(mode="json")
                for value in bound.samples.values()
            ):
                return
        raise DomainError("SOURCE_UNAVAILABLE", "领域来源不是本次真实登记事实。")

    def applicable(sample):
        keys = [key for key in selected if key[0] == sample.id]
        for key in keys:
            try:
                _bound_actual_check(
                    s,
                    ctx,
                    product.id,
                    bound,
                    sample,
                    bound.samples[sample.id],
                    bound.methods.get(key),
                )
            except DomainError as error:
                if error.code in {"ACTUAL_METHOD_UNKNOWN", "SOURCE_STALE"}:
                    return False
                raise
        return bool(keys)

    dto = authority_dto(bound.authority, ctx.requester_id, bound.at)
    if command.operation == OPERATIONS["handoff_offer"] and "manufacturing" in dto.roles:
        # Only a verified manufacturing role may become kernel production.
        dto = type(dto).model_validate({**dto.model_dump(), "roles": (*dto.roles, "production")})
    commands = HandoffCommands(dto, bound.base, save, accepted_confirmation=accepted)
    availability = InspectedSamples(lambda sample: bound.samples[sample.id], applicable)
    return kernel(
        commands,
        bound.base.build,
        "executing" if isinstance(payload, (OfferPayload, AcceptPayload)) else bound.build.status,
        check_source,
        availability,
    ), commands


def _invocation(command, payload, kernel_payload):
    from pdos_next.domain.verification.handlers import semantic_digest

    return Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=payload.request_id,
        expected_revision=payload.expected_request_revision,
        semantic_digest=semantic_digest(kernel_payload),
    )


def _record(s, ctx, command, product, payload, bound, pointer, mutation):
    request = mutation.request
    if (
        mutation.run is not None
        or request is None
        or request.status not in {"offered", "accepted"}
        or any(getattr(request.timeline, name) is not None for name in FUTURE_TIMES)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "交接不能写入承诺、开测或结果状态。")
    inherited = deepcopy(bound.previous.input_snapshot)
    inherited["handoff_input"] = semantic(payload)
    row = FormalVerificationRequest(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=bound.build.project_id,
        build_id=bound.build.id,
        build_revision=bound.build.revision,
        request_id=payload.request_id,
        revision=request.revision,
        previous_request_id=bound.previous.id,
        previous_revision=bound.previous.revision,
        owner_id=bound.previous.owner_id,
        visibility=bound.visibility,
        status=request.status,
        operation=command.operation,
        preparation_id=bound.previous.preparation_id,
        preparation_revision=bound.previous.preparation_revision,
        preparation_sha256=bound.previous.preparation_sha256,
        purpose=request.purpose,
        request_snapshot=request.model_dump(mode="json"),
        input_snapshot=inherited,
        snapshot_sha256=digest(request.model_dump(mode="json")),
        sources=bound.references,
        required_source_read_set=bound.reads,
        authority_snapshot=bound.authority,
        intent_digest=digest(
            {
                "operation": command.operation,
                "payload": semantic(payload),
                "actor": ctx.requester_id,
            }
        ),
        reason=payload.reason,
        created_at=bound.at,
    )
    s.add(row)
    s.flush()
    pointer.request_version_id, pointer.request_revision = row.id, row.revision
    event = mutation.events[0].model_dump(mode="json")
    fact = VerificationHandoffFact(
        id=_child_id(command, "handoff"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=bound.build.project_id,
        request_id=payload.request_id,
        request_version_id=bound.previous.id,
        request_revision=bound.previous.revision,
        next_request_version_id=row.id,
        next_request_revision=row.revision,
        owner_id=ctx.requester_id,
        visibility=bound.visibility,
        revision=1,
        status=request.status,
        operation=command.operation,
        input_snapshot=semantic(payload),
        kernel_event=event,
        sources=bound.references,
        required_source_read_set=bound.reads,
        source_basis=bound.source_basis,
        authority_snapshot=bound.authority,
        snapshot_sha256=digest(event),
        intent_digest=row.intent_digest,
        reason=payload.reason,
        created_at=bound.at,
    )
    s.add(fact)
    s.flush()
    return row


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _current_guards(s, ctx, command, product, payload, bound)
    pointer = _new_write(s, ctx, command, product, payload, bound)
    if isinstance(payload, ActualMethodPreparePayload):
        return _actual_apply(s, ctx, command, product, payload, bound)
    recorded = []

    def save(mutation):
        row = _record(s, ctx, command, product, payload, bound, pointer, mutation)
        recorded.append(row)
        return row

    k, _ = _kernel(s, ctx, command, product, payload, bound, save, accepted=True)
    value = _payload_kernel(payload)
    k.execute(_invocation(command, payload, value), value)
    return recorded[0], "verification_request", bound.visibility


def _actual_view(
    s,
    ctx,
    product_id,
    row,
    request,
    inspected=None,
    *,
    prospective=False,
    read_cache=None,
    read_context=None,
):
    sample = row.assessment_snapshot["sample"]
    current, code = True, None
    if not prospective:
        from pdos_next.schemas.verification.contracts import SampleRef

        ref = SampleRef.model_validate(sample)
        try:
            inspected = inspected or _inspect(
                s, ctx, product_id, request, ref, read_context=read_context
            )
            if read_cache is None:
                _actual_check(s, ctx, product_id, request, ref, inspected, row, positive=False)
                _, pointer_row = _method_pointer(
                    s, ctx, product_id, request.id, ref.id, row.item_id
                )
            else:
                _read_actual_check(
                    s, ctx, product_id, request, ref, inspected, row, read_cache, positive=False
                )
                _, pointer_row = _read_method_pointer(
                    s, ctx, product_id, request.id, ref.id, row.item_id, read_cache
                )
            current = pointer_row is not None and pointer_row.id == row.id
        except DomainError as error:
            if error.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                raise
            current, code = False, error.code
    return {
        "id": None if prospective else str(row.id),
        "revision": row.revision,
        "request_id": str(row.request_id),
        "request_revision": row.request_revision,
        "sample": sample,
        "item_id": row.item_id,
        "status": row.status,
        "current": current,
        "method_digest": row.method_digest,
        "actual_configuration": row.assessment_snapshot["actual_configuration"],
        "conditions": row.assessment_snapshot["conditions"],
        "reason": row.assessment_snapshot["reason"],
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
        "authority": row.authority_snapshot,
        "source_status": "current" if current else "needs_recheck",
        "reason_codes": [code] if code else [],
        "created_at": None if prospective else row.created_at.isoformat(),
    }


def _historical_actual_view(s, ctx, product_id, row, cache):
    from pdos_next.schemas.verification.contracts import SampleRef

    parent = cache.get(
        "request_version",
        row.request_version_id,
        lambda: front._row(s, ctx, product_id, row.request_version_id),
    )
    request = front._snapshot(parent)
    sample = SampleRef.model_validate(row.assessment_snapshot["sample"])
    _actual_binding(
        s,
        ctx,
        product_id,
        request,
        sample,
        {"actual_configuration": row.assessment_snapshot["actual_configuration"]},
        row,
        parent=parent,
    )
    state = _read_evidence(s, ctx, product_id, row)
    view = _actual_view(s, ctx, product_id, row, request, prospective=True)
    view.update(
        id=str(row.id),
        created_at=row.created_at.isoformat(),
        current=False,
        source_status=state,
        current_evaluation="not_evaluated_historical",
        reason_codes=[],
    )
    return view


def _preview_receives(value, before=None):
    """New server receive clocks are assigned on commit, never on material review."""
    if isinstance(value, dict):
        previous = before if isinstance(before, dict) else {}
        return {
            key: None
            if key == "received_at" and previous.get(key) != child
            else _preview_receives(child, previous.get(key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        previous = before if isinstance(before, list) else []
        return [
            _preview_receives(child, previous[index] if index < len(previous) else None)
            for index, child in enumerate(value)
        ]
    return value


def _request_view(
    s,
    ctx,
    product_id,
    row,
    request,
    *,
    current=True,
    prospective=False,
    preparation_row=None,
):
    if preparation_row is None:
        prep, _ = preparation.get_preparation(s, ctx, product_id, row.preparation_id)
    else:
        prep = preparation_row
    raw = request.model_dump(mode="json")
    if prospective:
        previous = front._snapshot(front._row(s, ctx, product_id, row.previous_request_id))
        raw = _preview_receives(raw, previous.model_dump(mode="json"))
    return {
        "id": None if prospective else str(row.id),
        "request_id": str(row.request_id),
        "revision": row.revision,
        "previous_request_id": str(row.previous_request_id) if row.previous_request_id else None,
        "previous_revision": row.previous_revision,
        "project_id": str(row.project_id),
        "build": request.build.model_dump(mode="json"),
        "title": request.title,
        "purpose": request.purpose,
        "status": request.status,
        "items": deepcopy(prep.input_snapshot["items"]),
        "documents": deepcopy(prep.input_snapshot["documents"]),
        "request_snapshot": raw,
        "preparation_id": str(row.preparation_id),
        "preparation_revision": row.preparation_revision,
        "preparation_sha256": row.preparation_sha256,
        "samples": raw["samples"],
        "offered_coverage": raw["offered_coverage"],
        "accepted_coverage": [c.model_dump(mode="json") for c in accepted_coverage(request)],
        "acceptances": raw["acceptances"],
        "returns": raw["returns"],
        "timeline": raw["timeline"],
        "document_gaps": [g.model_dump(mode="json") for g in document_gaps(request)],
        "coverage_gaps": [
            g.model_dump(mode="json") for g in coverage_gaps(request, accepted_coverage(request))
        ],
        "first_requested_at": request.timeline.request_created.received_at.isoformat(),
        "created_at": None if prospective else row.created_at.isoformat(),
        "sha256": None if prospective else row.snapshot_sha256,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "reason": row.reason,
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
        "is_current": current,
        "zero_occupancy": request.status != "executing",
        "physical_timeline_empty": not any(
            getattr(request.timeline, k) for k in ("sample_ready", "offered", "accepted")
        ),
        "capabilities": {key: False for key in OPERATIONS},
    }


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _current_guards(s, ctx, command, product, payload, bound)
    _new_write(s, ctx, command, product, payload, bound)
    if isinstance(payload, ActualMethodPreparePayload):
        children, _ = _actual_candidates(s, ctx, command, product, payload, bound)
        before = []
        for item in payload.assessments:
            _, old = _method_pointer(
                s, ctx, product.id, payload.request_id, item.sample.id, item.item_id
            )
            before.append(_actual_view(s, ctx, product.id, old, bound.base) if old else None)
        before = {
            "request_id": str(payload.request_id),
            "request_revision": bound.previous.revision,
            "assessments": before,
        }
        after = {
            "request_id": str(payload.request_id),
            "request_revision": bound.previous.revision,
            "status": "prepared",
            "assessments": [
                _actual_view(s, ctx, product.id, row, bound.base, prospective=True)
                for row in children
            ],
            "zero_occupancy": True,
        }
    else:
        k, commands = _kernel(s, ctx, command, product, payload, bound, lambda _: None)
        value = _payload_kernel(payload)
        inv = _invocation(command, payload, value)
        preview, mutation = k._prepare(commands.authority, inv, value)
        if not preview.allowed:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "本次接收范围仍有资料或样件硬缺项。")
        before = _request_view(s, ctx, product.id, bound.previous, bound.base)
        after_row = SimpleNamespace(
            **{
                key: getattr(bound.previous, key)
                for key in (
                    "request_id",
                    "project_id",
                    "preparation_id",
                    "preparation_revision",
                    "preparation_sha256",
                    "owner_id",
                    "visibility",
                    "reason",
                    "sources",
                    "required_source_read_set",
                )
            },
            id=None,
            revision=mutation.request.revision,
            previous_request_id=bound.previous.id,
            previous_revision=bound.previous.revision,
            operation=command.operation,
        )
        after_row.reason, after_row.sources, after_row.required_source_read_set = (
            payload.reason,
            bound.references,
            bound.reads,
        )
        after = _request_view(s, ctx, product.id, after_row, mutation.request, prospective=True)
    return {
        "operation": command.operation,
        "effect": EFFECT,
        "before": before,
        "after": after,
        "authority": bound.authority,
        "required_source_read_set": bound.reads,
        "reason": payload.reason,
    }


def _sample_view(s, ctx, product_id, request, sample_row, *, read_context=None):
    from pdos_next.domain.build_execution.models import ActualConfiguration
    from pdos_next.domain.build_execution.service import sample_view
    from pdos_next.schemas.verification.contracts import ConfigurationRef, SampleRef

    revision = s.scalar(
        select(ActualConfiguration.revision).where(
            ActualConfiguration.id == sample_row.actual_configuration_id,
            ActualConfiguration.tenant_id == ctx.tenant_id,
            ActualConfiguration.product_id == product_id,
            ActualConfiguration.build_id == request.build.id,
        )
    )
    if revision is None:
        raise DomainError("SOURCE_UNAVAILABLE", "实际配置不在固定样件范围。")
    reference = SampleRef(
        id=sample_row.id,
        revision=sample_row.revision,
        build_id=sample_row.build_id,
        actual_configuration=ConfigurationRef(
            id=sample_row.actual_configuration_id, revision=revision
        ),
        cavity=sample_row.cavity,
    )
    inspected = _inspect(s, ctx, product_id, request, reference, read_context=read_context)
    # The inspector already checked the full physical chain and source audience.
    # Reuse the existing renderer, without traversing the same Lot/configuration twice.
    view = sample_view(
        s,
        ctx,
        product_id,
        sample_row,
        {
            "actual_row": SimpleNamespace(revision=inspected["actual_configuration"]["revision"]),
            "lot": SimpleNamespace(observation_nature=inspected["lot"]["nature"]),
        },
    )
    return (
        {
            **view,
            "reference": reference.model_dump(mode="json"),
            "availability": inspected["availability"],
            "current_readiness": inspected["current_readiness"],
            "actual_configuration": inspected["actual_configuration"],
            "facts_revision": inspected["facts_revision"],
            "reason_codes": inspected["reason_codes"],
            "required_source_read_set": inspected["required_source_read_set"],
            "source_refs": inspected["source_refs"],
        },
        reference,
        inspected,
    )


def inputs(s, ctx, product_id, request_id, revision, sample_refs=()):
    """Read-only complete selected sources; host can expose without client guessing epochs."""
    _human(s, ctx, product_id)
    row = front._version(s, ctx, product_id, request_id, revision)
    request = front._snapshot(row)
    authorities = {
        key: front._assess(s, ctx, product_id, row.project_id, operation, request.purpose)
        for key, operation in OPERATIONS.items()
    }
    reads = _merge_reads(
        row.required_source_read_set, *(a["required_source_read_set"] for a in authorities.values())
    )
    selected = []
    for sample in sample_refs:
        value = _inspect(s, ctx, product_id, request, sample)
        reads = _merge_reads(reads, value["required_source_read_set"])
        selected.append({"sample": sample.model_dump(mode="json"), "inspection": value})
    _sources(s, ctx, product_id, reads, row.sources)
    return {
        "request_id": str(row.request_id),
        "revision": row.revision,
        "required_source_read_set": reads,
        "authority": authorities,
        "samples": selected,
    }


class _ReadCache:
    """Invocation-local memoization only; never shared with commands or another GET."""

    def __init__(self):
        self.values = {}

    def get(self, kind, key, read):
        identity = (kind, key)
        if identity not in self.values:
            try:
                self.values[identity] = read()
            except DomainError as error:
                self.values[identity] = error
        value = self.values[identity]
        if isinstance(value, DomainError):
            raise value
        return value


def _read_method_pointer(s, ctx, product_id, request_id, sample_id, item_id, cache):
    return cache.get(
        "method_pointer",
        (request_id, sample_id, item_id),
        lambda: _method_pointer(s, ctx, product_id, request_id, sample_id, item_id),
    )


def _read_actual_check(s, ctx, product_id, request, sample, value, row, cache, *, positive=True):
    if row is None:
        raise DomainError("ACTUAL_METHOD_UNKNOWN", "该实际样件与测试项尚无独立适用核对。")
    # Positive status is a separate local condition; the complete proof is the
    # same for the pair capability and its current immutable assessment view.
    cache.get(
        "actual_proof",
        (
            row.id,
            row.snapshot_sha256,
            digest(request.model_dump(mode="json")),
            sample.id,
            sample.revision,
            digest(value),
        ),
        lambda: _actual_check(s, ctx, product_id, request, sample, value, row, positive=False),
    )
    if positive and row.status != "applicable":
        raise DomainError("ACTUAL_METHOD_UNKNOWN", "实际配置方法适用仍未知或不适用。")


def _historical_request(view, source_status):
    """Fixed history remains visible, without claiming an unperformed current review."""
    view.update(
        authority={},
        source_status=source_status,
        freshness="historical",
        current_evaluation="not_evaluated_historical",
        documents_ready=None,
        document_milestone_current=None,
        pair_capabilities=[],
        blockers=[],
        next_owner_ids=[],
    )
    return view


def list_verification_handoff(s, ctx, product_id, *, build_id=None):
    _human(s, ctx, product_id)
    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.sample_handoff.service import ReadContext

    if build_id is not None:
        build = front._build(s, ctx, product_id, build_id)
        _, _, _, reads = front._linked(s, ctx, product_id, build)
        _sources(s, ctx, product_id, reads)
        build_id = build.id  # Authoritative identity, never a client-provided scope.
    cache = _ReadCache()
    read_context = ReadContext(s, ctx, product_id)
    result = {
        "requests": [],
        "current_by_request": {},
        "actual_methods": [],
        "method_current_by_pair": [],
        "handoffs": [],
        "reference_samples": [],
        "next_owners": [],
        "capabilities": {key: False for key in OPERATIONS},
        "blockers": [{"code": "TEST_EXECUTION_UNCONNECTED", "detail": EFFECT}],
        "runs": [],
        "has_more": False,
        "unavailable_count": 0,
    }
    query = select(FormalVerificationRequest)
    if build_id is not None:
        query = query.where(FormalVerificationRequest.build_id == build_id)
    rows = s.scalars(
        query.where(
            FormalVerificationRequest.tenant_id == ctx.tenant_id,
            FormalVerificationRequest.product_id == product_id,
        )
        .order_by(FormalVerificationRequest.created_at, FormalVerificationRequest.id)
        .limit(201)
    ).all()
    result["has_more"] = len(rows) > 200
    sample_views, owners, included_requests = {}, {}, set()
    for row in rows[:200]:
        try:
            row = front._row(s, ctx, product_id, row.id)
            cache.values[("request_version", row.id)] = row
            request = front._snapshot(row)
            source_status = _read_evidence(s, ctx, product_id, row)
            _, current = cache.get(
                "request_current",
                row.request_id,
                lambda row=row: front._current(s, ctx, product_id, row.request_id),
            )
            is_current = current is not None and current.id == row.id
            prep, _ = cache.get(
                "preparation",
                row.preparation_id,
                lambda row=row: preparation.get_preparation(s, ctx, product_id, row.preparation_id),
            )
            view = _request_view(
                s,
                ctx,
                product_id,
                row,
                request,
                current=is_current,
                preparation_row=prep,
            )
            if not is_current:
                result["requests"].append(_historical_request(view, source_status))
                included_requests.add(row.request_id)
                continue
            authority = {
                key: cache.get(
                    "authority",
                    (row.project_id, request.purpose, operation),
                    lambda operation=operation, row=row, request=request: front._assess(
                        s, ctx, product_id, row.project_id, operation, request.purpose
                    ),
                )
                for key, operation in OPERATIONS.items()
            }
            view["authority"] = authority
            view["current_evaluation"] = "evaluated"
            view["source_status"] = source_status
            view["freshness"] = (
                "current"
                if is_current and source_status == "current"
                else "historical"
                if not is_current
                else "requires_recalculation"
            )
            view["required_source_read_set"] = _merge_reads(
                row.required_source_read_set,
                *(a["required_source_read_set"] for a in authority.values()),
            )
            source_current = source_status == "current"
            try:
                cache.get(
                    "planned_proofs",
                    row.snapshot_sha256,
                    lambda request=request: front._check_existing_proofs(
                        s, ctx, product_id, request
                    ),
                )
            except DomainError as error:
                if error.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                    raise
                source_current = False
            view["documents_ready"] = source_current and not document_gaps(request)
            view["document_milestone_current"] = (
                view["documents_ready"] if request.timeline.documents_complete else None
            )
            view["pair_capabilities"] = []
            view["blockers"] = []
            executing = False
            try:
                _execution(
                    s,
                    ctx,
                    product_id,
                    front._build(s, ctx, product_id, row.build_id),
                    read_context=read_context,
                )
                executing = True
            except DomainError as error:
                view["blockers"].append(
                    {"code": error.code, "detail": "当前Build执行授权须重核，既有实物不替代开工。"}
                )
            samples = cache.get(
                "sample_rows",
                row.build_id,
                lambda row=row: s.scalars(
                    select(SampleUnit)
                    .where(
                        SampleUnit.tenant_id == ctx.tenant_id,
                        SampleUnit.product_id == product_id,
                        SampleUnit.build_id == row.build_id,
                    )
                    .order_by(SampleUnit.created_at, SampleUnit.id)
                    .limit(201)
                ).all(),
            )
            result["has_more"] |= len(samples) > 200
            inspected = {}
            for sample_row in samples[:200]:
                try:
                    sample_view, ref, facts = cache.get(
                        "sample",
                        (
                            row.project_id,
                            row.build_id,
                            request.purpose,
                            sample_row.id,
                            sample_row.revision,
                        ),
                        lambda sample_row=sample_row, request=request: _sample_view(
                            s,
                            ctx,
                            product_id,
                            request,
                            sample_row,
                            read_context=read_context,
                        ),
                    )
                    sample_views[(row.request_id, ref.id)] = {
                        **sample_view,
                        "request_id": str(row.request_id),
                    }
                    inspected[ref.id] = (ref, facts)
                except DomainError:
                    result["unavailable_count"] += 1
            pending = pairs(request.offered_coverage) - pairs(accepted_coverage(request))
            for sample_id, item_id in sorted(pending, key=lambda p: (str(p[0]), p[1])):
                ready = False
                code = "SAMPLE_UNAVAILABLE"
                if sample_id in inspected:
                    ref, facts = inspected[sample_id]
                    _, method = _read_method_pointer(
                        s,
                        ctx,
                        product_id,
                        row.request_id,
                        sample_id,
                        item_id,
                        cache,
                    )
                    try:
                        _read_actual_check(s, ctx, product_id, request, ref, facts, method, cache)
                        ready = facts["availability"] == "ready" and not document_gaps(
                            request, {item_id}
                        )
                    except DomainError as error:
                        code = error.code
                view["pair_capabilities"].append(
                    {
                        "sample_id": str(sample_id),
                        "item_id": item_id,
                        "handoff_accept": bool(
                            is_current
                            and source_current
                            and executing
                            and ready
                            and authority["handoff_accept"]["authorized"]
                        ),
                        "reason_codes": [] if ready else [code],
                    }
                )
            for key, assessment in authority.items():
                allowed = (
                    assessment["authorized"] is True
                    and assessment["qualified"] is True
                    and is_current
                    and source_current
                )
                if key == "handoff_offer":
                    allowed = (
                        allowed and executing and request.status == "draft" and bool(inspected)
                    )
                elif key == "handoff_accept":
                    from pdos_next.domain.verification_launch.models import VerificationRunIdentity

                    planned = s.scalar(
                        select(VerificationRunIdentity.id).where(
                            VerificationRunIdentity.tenant_id == ctx.tenant_id,
                            VerificationRunIdentity.product_id == product_id,
                            VerificationRunIdentity.request_id == request.id,
                        )
                    )
                    view["planned_run_id"] = str(planned) if planned else None
                    allowed = (
                        allowed
                        and planned is None
                        and request.status in {"offered", "accepted"}
                        and any(p["handoff_accept"] for p in view["pair_capabilities"])
                    )
                elif key == "handoff_return":
                    allowed = (
                        allowed
                        and not view.get("planned_run_id")
                        and request.status in {"offered", "accepted"}
                        and bool(pending)
                    )
                else:
                    allowed = (
                        allowed
                        and request.status in {"draft", "offered", "accepted"}
                        and bool(inspected)
                    )
                view["capabilities"][key] = bool(allowed)
                result["capabilities"][key] |= bool(allowed)
            candidates = cache.get(
                "next_owner_candidates",
                product_id,
                lambda: s.scalars(
                    select(Principal)
                    .join(
                        Grant,
                        (Grant.tenant_id == Principal.tenant_id)
                        & (Grant.principal_id == Principal.id),
                    )
                    .where(
                        Principal.tenant_id == ctx.tenant_id,
                        Principal.kind == "human",
                        Principal.active.is_(True),
                        Grant.product_id == product_id,
                        Grant.can_write.is_(True),
                        Grant.expires_at > now(),
                    )
                    .limit(201)
                ).all(),
            )
            view["next_owner_ids"] = []
            for principal in candidates:
                try:
                    owners[principal.id] = cache.get(
                        "next_owner",
                        (row.project_id, principal.id),
                        lambda principal=principal, row=row: _assignee(
                            s,
                            ctx,
                            product_id,
                            row.project_id,
                            principal.id,
                        ),
                    )
                    view["next_owner_ids"].append(str(principal.id))
                except DomainError:
                    continue
            result["requests"].append(view)
            included_requests.add(row.request_id)
            if is_current:
                result["current_by_request"][str(row.request_id)] = {
                    "request_version_id": str(row.id),
                    "revision": row.revision,
                }
        except DomainError:
            result["unavailable_count"] += 1
    for model, key in (
        (ActualMethodApplicability, "actual_methods"),
        (VerificationHandoffFact, "handoffs"),
    ):
        query = select(model)
        if build_id is not None:
            if model is VerificationHandoffFact:
                query = query.where(
                    model.request_version_id.in_(
                        select(FormalVerificationRequest.id).where(
                            FormalVerificationRequest.tenant_id == ctx.tenant_id,
                            FormalVerificationRequest.product_id == product_id,
                            FormalVerificationRequest.build_id == build_id,
                        )
                    )
                )
            else:
                query = query.where(model.build_id == build_id)
        records = s.scalars(
            query.where(model.tenant_id == ctx.tenant_id, model.product_id == product_id)
            .order_by(model.created_at, model.id)
            .limit(201)
        ).all()
        result["has_more"] |= len(records) > 200
        for record in records[:200]:
            if record.request_id not in included_requests or (
                record.visibility == "private" and record.owner_id != ctx.requester_id
            ):
                continue
            try:
                _, parent = cache.get(
                    "request_current",
                    record.request_id,
                    lambda record=record: front._current(s, ctx, product_id, record.request_id),
                )
                request = front._snapshot(parent)
                if model is ActualMethodApplicability:
                    cached = cache.values.get(
                        (
                            "sample",
                            (
                                record.project_id,
                                record.build_id,
                                request.purpose,
                                record.sample_id,
                                record.sample_revision,
                            ),
                        )
                    )
                    inspected = (
                        cached[2] if cached and not isinstance(cached, DomainError) else None
                    )
                    _, pointed = _read_method_pointer(
                        s,
                        ctx,
                        product_id,
                        record.request_id,
                        record.sample_id,
                        record.item_id,
                        cache,
                    )
                    is_pointed = pointed is not None and pointed.id == record.id
                    if is_pointed:
                        view = _actual_view(
                            s,
                            ctx,
                            product_id,
                            record,
                            request,
                            inspected,
                            read_cache=cache,
                            read_context=read_context,
                        )
                        view["current_evaluation"] = "evaluated"
                    else:
                        # Preserve historical content and current source audience;
                        # a superseded row can never grant applicability or a CAS.
                        view = _historical_actual_view(s, ctx, product_id, record, cache)
                    result[key].append(view)
                    # Identity survives validity loss; this never grants applicability.
                    if is_pointed:
                        result["method_current_by_pair"].append(
                            {
                                "request_id": str(record.request_id),
                                "sample_id": str(record.sample_id),
                                "item_id": record.item_id,
                                "assessment_id": str(record.id),
                                "revision": record.revision,
                            }
                        )
                else:
                    status = _read_evidence(s, ctx, product_id, record)
                    result[key].append(
                        {
                            "id": str(record.id),
                            "request_id": str(record.request_id),
                            "request_revision": record.request_revision,
                            "next_request_revision": record.next_request_revision,
                            "operation": record.operation,
                            "status": record.status,
                            "input_snapshot": record.input_snapshot,
                            "kernel_event": record.kernel_event,
                            "reason": record.reason,
                            "sources": record.sources,
                            "required_source_read_set": record.required_source_read_set,
                            "source_status": status,
                            "authority": record.authority_snapshot,
                            "created_at": record.created_at.isoformat(),
                        }
                    )
            except DomainError:
                result["unavailable_count"] += 1
    result["reference_samples"] = list(sample_views.values())
    result["next_owners"] = list(owners.values())
    return result
