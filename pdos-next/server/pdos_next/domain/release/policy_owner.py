"""Host-only release publications and direct applicability watermarks.

Only import reads the registered original line and assesses its current named
publisher. Later reads consume the immutable fact, its original metadata and
saved signature's Current watermarks; they do not reissue historical authority.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary, ref

from pydantic import ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy import select

from pdos_next import service as common
from pdos_next.change_implementation_owner import common_group
from pdos_next.contracts import Command, SourceRead
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.manufacturing_trials import native_material_owner as direct
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Receipt, RequestKey, now
from pdos_next.request_proof import snapshot_get, snapshot_mappings, snapshot_rows
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from . import policy_rules
from .policy_models import ReleasePolicyCurrent as Current
from .policy_models import ReleasePolicyFact as Fact
from .policy_schemas import PolicyImport, PolicyMaterial
from .schemas import PolicyBasis, ReleaseCheck, ReleaseScope, SubjectConfiguration

POLICY_OPERATION = "release.policy.import"
POLICY_EVENT = "release.policy_imported"
POLICY_FAMILY = "release_policy_fact"
_READ_SCHEMA = "pdos-release-policy-read-v2"
FACT_FIELDS = (
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "purpose",
    "purpose_sha256",
    "policy_version",
    "series_id",
    "revision",
    "epoch",
    "previous_id",
    "previous_revision",
    "owner_id",
    "writer_id",
    "actor_id",
    "requester_id",
    "visibility",
    "status",
    "nature",
    "operation",
    "command_id",
    "receipt_id",
    "intent_digest",
    "request_digest",
    "material",
    "material_sha256",
    "source",
    "sources",
    "required_source_read_set",
    "source_basis",
    "authority_snapshot",
    "input_snapshot",
    "valid_from",
    "valid_until",
)
_BASIS_FIELDS = {
    "schema_version",
    "scope",
    "category_id",
    "purpose",
    "pointer",
    "fact",
    "watermarks",
    "signature",
    "status",
    "valid_from",
    "valid_until",
    "time_state",
}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def fact_material(row):
    values = {key: getattr(row, key) for key in FACT_FIELDS}
    for name in ("valid_from", "valid_until"):
        value = values[name]
        values[name] = value.astimezone(UTC).isoformat() if value is not None else None
    return values


def fact_hash(row):
    return common.digest(fact_material(row))


def _original(s, ctx, pid, source):
    artifact = common.source_for(s, ctx, pid, source.id, source.revision)
    _require(
        artifact.original_id is None,
        "放行政策须由原生登记整行出版入口办理。",
        "INTEGRATION_REQUIRED",
        503,
    )
    _require(artifact.content_hash == common.digest(artifact.content), "政策原文摘要已变化。")
    evidence._native_registration(s, ctx, pid, artifact)
    match = evidence.POSITION.fullmatch(source.position)
    lines = artifact.content.splitlines()
    _require(
        match is not None and int(match[1]) <= len(lines),
        "政策须定位完整原文行。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    line = lines[int(match[1]) - 1]
    _require(sha256(line.encode()).hexdigest() == match[2], "政策固定原文行摘要不一致。")
    try:
        value = PolicyMaterial.model_validate(
            json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        )
    except (ValueError, TypeError) as error:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE",
            "放行政策须是完整封闭JSON原行，拒绝重复键、额外字段和非有限数。",
            422,
        ) from error
    return value


def _scope(s, ctx, pid, scope, purpose, *, write=False):
    _require(
        scope.tenant_id == ctx.tenant_id and scope.product_id == pid,
        "政策不在当前型号范围。",
        "FORBIDDEN_SCOPE",
        403,
    )
    product, project = professional._project(s, ctx, pid, scope.project_id, write=write)
    _require(
        product.category_id == ctx.category_id
        and project.purpose == purpose
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "政策不在当前品类、项目、用途或可读范围。",
        "FORBIDDEN_SCOPE",
        403,
    )
    return product, project


def _pointer_value(row):
    return (
        None
        if row is None
        else to_jsonable_python(
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "series_id",
                    "fact_id",
                    "revision",
                    "epoch",
                    "owner_id",
                    "visibility",
                    "purpose_sha256",
                )
            }
        )
    )


def _pointer(s, ctx, pid, scope, purpose, *, lock=False):
    query = (
        select(Current)
        .where(
            Current.tenant_id == ctx.tenant_id,
            Current.category_id == ctx.category_id,
            Current.product_id == pid,
            Current.project_id == scope.project_id,
            Current.purpose_sha256 == common.digest(purpose),
        )
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    rows = (
        list(s.scalars(query.with_for_update()))
        if lock
        else snapshot_rows(
            s, ("release-policy-current", pid, scope.project_id, purpose), query, scope_id=pid
        )
    )
    _require(len(rows) <= 1, "放行政策当前指针不唯一。", "INTEGRITY_MISMATCH", 503)
    return rows[0] if rows else None


def _fact(s, ctx, pid, scope, purpose, pointer):
    if pointer is None:
        return None
    row = snapshot_get(s, Fact, pointer.fact_id, scope_id=pid)
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id, row.project_id, row.purpose)
        == (ctx.tenant_id, ctx.category_id, pid, scope.project_id, purpose),
        "放行政策固定版本范围不一致。",
        "INTEGRITY_MISMATCH",
        503,
    )
    _require(
        (row.series_id, row.revision, row.epoch, row.owner_id, row.visibility, row.purpose_sha256)
        == (
            pointer.series_id,
            pointer.revision,
            pointer.epoch,
            pointer.owner_id,
            pointer.visibility,
            pointer.purpose_sha256,
        )
        and row.material_sha256 == common.digest(row.material)
        and row.fact_sha256 == fact_hash(row),
        "放行政策固定版本摘要或Current不一致。",
        "INTEGRITY_MISMATCH",
        503,
    )
    _require(
        row.visibility != "private" or row.owner_id == ctx.requester_id,
        "当前本人不能读取私有放行政策。",
        "FORBIDDEN_SCOPE",
        403,
    )
    value = PolicyMaterial.model_validate(row.material)
    _require(
        value.scope == scope
        and value.category_id == ctx.category_id
        and value.purpose == purpose
        and (
            value.publisher_id,
            value.owner_id,
            value.visibility,
            value.nature,
            value.status,
            value.policy_version,
            value.valid_from,
            value.valid_until,
        )
        == (
            row.actor_id,
            row.owner_id,
            row.visibility,
            row.nature,
            row.status,
            row.policy_version,
            row.valid_from,
            row.valid_until,
        )
        and row.authority_snapshot.get("subject_id") == str(row.actor_id),
        "政策原文、发布本人及固定事实绑定不一致。",
        "INTEGRITY_MISMATCH",
        503,
    )
    return row


def _common(s, ctx, pid, row):
    group = common_group(
        s, ctx, pid, row, operation=POLICY_OPERATION, event=POLICY_EVENT, actor=row.actor_id
    )
    receipt = group["receipt"]
    _require(
        receipt["id"] == row.receipt_id
        and receipt["subject_type"] == POLICY_FAMILY
        and receipt["command_id"] == row.command_id
        and receipt["request_digest"] == row.request_digest
        and receipt["intent_digest"] == row.intent_digest
        and receipt.get("run_id") is None,
        "政策缺实际共同Receipt/Audit/Outbox/请求绑定。",
        "INTEGRITY_MISMATCH",
        503,
    )
    return receipt


def _fact_value(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "sha256": row.fact_sha256,
        "material_sha256": row.material_sha256,
    }


def _time_state(row, at):
    if row.valid_from is not None and at < row.valid_from:
        return "future"
    if row.valid_until is not None and at >= row.valid_until:
        return "expired"
    return "current"


@dataclass(frozen=True, eq=False)
class PolicyRead:
    policy: PolicyBasis | None
    checks: tuple[ReleaseCheck, ...]
    source_basis: dict
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    gaps: tuple[str, ...]
    visibility: str | None = None
    owner_id: UUID | None = None


class ActualReleasePolicyOwner:
    def __init__(self, engine):
        self.engine = engine
        self._reads, self._cache = WeakKeyDictionary(), WeakKeyDictionary()

    def _runtime(self, s):
        _require(
            s.get_bind() is self.engine,
            "须使用实际放行政策owner的Session。",
            "FORBIDDEN_SCOPE",
            403,
        )
        return evidence._runtime_stamp(s), id(policy_rules.evaluate), id(signature_current)

    @staticmethod
    def _snapshot(value):
        return to_jsonable_python(
            {key: deepcopy(getattr(value, key)) for key in PolicyRead.__dataclass_fields__}
        )

    def _binding(self, s, ctx, pid, value):
        saved = self._reads.get(value) if type(value) is PolicyRead else None
        _require(saved is not None, "须使用本政策owner实际发行的读取。")
        session, uow, caller, product, runtime, snapshot = saved
        _same_uow(s, uow, ctx, caller)
        _require(
            session() is s
            and product == pid
            and runtime == self._runtime(s)
            and snapshot == self._snapshot(value),
            "政策读取的调用、事务或封存材料已变化。",
        )

    def _collect(self, s, ctx, pid, *, scope, purpose, subject_config, release_scope, facts, at):
        _scope(s, ctx, pid, scope, purpose)
        pointer = _pointer(s, ctx, pid, scope, purpose)
        row = _fact(s, ctx, pid, scope, purpose, pointer)
        basis = {
            "schema_version": _READ_SCHEMA,
            "scope": scope.model_dump(mode="json"),
            "category_id": str(ctx.category_id),
            "purpose": purpose,
            "pointer": _pointer_value(pointer),
            "fact": None,
            "watermarks": [],
            "signature": None,
            "status": None,
            "valid_from": None,
            "valid_until": None,
            "time_state": None,
        }
        if row is None:
            return PolicyRead(None, (), basis, (), (), ("RELEASE_POLICY_MISSING",))
        _common(s, ctx, pid, row)
        marks = direct._source_watermarks(s, ctx, pid, row.source_basis)
        direct._watermarks_current(s, ctx, pid, marks)
        _require(
            signature_current(s, ctx, pid, scope.project_id, row.authority_snapshot),
            "放行政策已保存签署水位需要重核。",
            "RECHECK_REQUIRED",
        )
        sources = tuple(SourceRef.model_validate(value) for value in row.sources)
        reads = tuple(SourceRead.model_validate(value) for value in row.required_source_read_set)
        basis.update(
            fact=_fact_value(row),
            watermarks=marks,
            signature=deepcopy(row.authority_snapshot),
            status=row.status,
            valid_from=row.valid_from.isoformat() if row.valid_from else None,
            valid_until=row.valid_until.isoformat() if row.valid_until else None,
            time_state=_time_state(row, at),
        )
        policy, checks = policy_rules.evaluate(
            row.material,
            scope=scope,
            category_id=ctx.category_id,
            subject_config=subject_config,
            release_scope=release_scope,
            purpose=purpose,
            facts=facts,
            sources=sources,
            at=at,
        )
        return PolicyRead(
            policy,
            checks,
            to_jsonable_python(basis),
            sources,
            reads,
            (),
            row.visibility,
            row.owner_id,
        )

    def read(self, s, ctx, pid, *, scope, purpose, subject_config, release_scope, facts, at):
        require_context(s, ctx)
        scope, subject_config, release_scope = (
            Scope.model_validate(scope),
            SubjectConfiguration.model_validate(subject_config),
            ReleaseScope.model_validate(release_scope),
        )
        _require(
            isinstance(at, datetime) and at.utcoffset() is not None,
            "政策读取须使用服务器aware时点。",
            "INVALID_EVENT_TIME",
            422,
        )
        facts = tuple(facts)
        uow, caller, runtime = _uow(s), common.digest(vars(ctx)), self._runtime(s)
        key = common.digest(
            {
                "caller": caller,
                "product": pid,
                "scope": scope,
                "purpose": purpose,
                "configuration": subject_config,
                "release_scope": release_scope,
                "facts": facts,
                "at": at,
            }
        )
        cache = self._cache.get(s)
        if cache is not None and cache[0] == uow and key in cache[1]:
            self._binding(s, ctx, pid, cache[1][key])
            return cache[1][key]
        value = self._collect(
            s,
            ctx,
            pid,
            scope=scope,
            purpose=purpose,
            subject_config=subject_config,
            release_scope=release_scope,
            facts=facts,
            at=at,
        )
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "政策读取期间实际运行时变化。")
        self._reads[value] = ref(s), uow, caller, pid, runtime, self._snapshot(value)
        if cache is None or cache[0] != uow:
            self._cache[s] = uow, {}
        self._cache[s][1][key] = value
        return value

    def current(self, s, ctx, pid, basis):
        """Compare persisted, server-sealed dependencies without original byte IO."""
        require_context(s, ctx)
        self._runtime(s)
        if type(basis) is PolicyRead:
            self._binding(s, ctx, pid, basis)
            basis = basis.source_basis
        try:
            if (
                type(basis) is not dict
                or set(basis) != _BASIS_FIELDS
                or basis["schema_version"] != _READ_SCHEMA
                or basis["category_id"] != str(ctx.category_id)
            ):
                return False
            scope = Scope.model_validate(basis["scope"])
            _scope(s, ctx, pid, scope, basis["purpose"])
            pointer = _pointer(s, ctx, pid, scope, basis["purpose"])
            if _pointer_value(pointer) != basis["pointer"]:
                return False
            if pointer is None:
                return (
                    all(
                        basis[key] is None
                        for key in (
                            "fact",
                            "signature",
                            "status",
                            "valid_from",
                            "valid_until",
                            "time_state",
                        )
                    )
                    and basis["watermarks"] == []
                )
            fields = (
                "id",
                "tenant_id",
                "category_id",
                "product_id",
                "project_id",
                "revision",
                "fact_sha256",
                "material_sha256",
                "owner_id",
                "visibility",
                "status",
                "valid_from",
                "valid_until",
            )
            rows = snapshot_mappings(
                s,
                select(*(getattr(Fact, key) for key in fields))
                .where(
                    Fact.tenant_id == ctx.tenant_id,
                    Fact.category_id == ctx.category_id,
                    Fact.product_id == pid,
                    Fact.project_id == scope.project_id,
                    Fact.id == pointer.fact_id,
                )
                .execution_options(autoflush=False),
                scope_id=pid,
            )
            if len(rows) != 1:
                return False
            row = rows[0]
            if (
                (row["visibility"] == "private" and row["owner_id"] != ctx.requester_id)
                or basis["fact"]
                != {
                    "id": str(row["id"]),
                    "revision": row["revision"],
                    "sha256": row["fact_sha256"],
                    "material_sha256": row["material_sha256"],
                }
                or basis["status"] != row["status"]
                or basis["valid_from"]
                != (row["valid_from"].isoformat() if row["valid_from"] else None)
                or basis["valid_until"]
                != (row["valid_until"].isoformat() if row["valid_until"] else None)
            ):
                return False
            at = now()
            actual_time = (
                "future"
                if row["valid_from"] is not None and at < row["valid_from"]
                else "expired"
                if row["valid_until"] is not None and at >= row["valid_until"]
                else "current"
            )
            if basis["time_state"] != actual_time:
                return False
            if not basis["watermarks"] or not basis["signature"]:
                return False
            direct._watermarks_current(s, ctx, pid, basis["watermarks"])
            return signature_current(s, ctx, pid, scope.project_id, basis["signature"])
        except (DomainError, ValidationError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def import_policy(self, s, ctx, pid, payload, *, command_id, request_key):
        """Trusted host entry: no HTTP/AI operation or second confirmation layer."""
        require_context(s, ctx)
        self._runtime(s)
        data = PolicyImport.model_validate(payload)
        _require(
            common.EVENTS.get(POLICY_OPERATION) == POLICY_EVENT,
            "政策共同发布尾尚未接线。",
            "INTEGRATION_REQUIRED",
            503,
        )
        _require(
            ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and ctx.agent_run_id is None
            and ctx.agent_call_id is None,
            "放行政策须由具名本人发布。",
            "NAMED_PERSON_REQUIRED",
            403,
        )
        uow, caller, runtime = _uow(s), common.digest(vars(ctx)), self._runtime(s)
        scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=data.project_id)
        value = _original(s, ctx, pid, data.source)
        product, project = _scope(s, ctx, pid, scope, value.purpose, write=True)
        actor = snapshot_get(s, Principal, ctx.actor_id, scope_id=pid)
        _require(
            actor is not None
            and actor.kind == "human"
            and actor.active
            and value.scope == scope
            and value.category_id == ctx.category_id
            and value.publisher_id == ctx.requester_id
            and value.owner_id == project.owner_id,
            "政策原文范围、本人或项目owner不一致。",
            "FORBIDDEN_SCOPE",
            403,
        )
        self._configurations(s, ctx, pid, value)
        auth = professional.assess(
            s, ctx, pid, data.project_id, POLICY_OPERATION, value.purpose, now(), write=True
        )
        _require(
            "PROFESSIONAL_OPERATION_NOT_CONFIGURED" not in auth["reason_codes"],
            "政策具名发布职责尚未配置。",
            "INTEGRATION_REQUIRED",
            503,
        )
        _require(
            auth["authorized"] is True
            and auth["qualified"] is True
            and bool(set(auth["roles"]) & {"engineering", "manufacturing", "quality"})
            and bool(auth["fact_refs"])
            and auth.get("subject_id") == str(ctx.requester_id)
            and value.nature == ("synthetic" if auth.get("synthetic") else "real"),
            "政策发布的当前专业职责、资格或资料性质不满足。",
            "QUALIFICATION_REQUIRED",
            403,
        )
        reads = policy_rules_reads(
            [*evidence._source_reads((data.source,)), *auth["required_source_read_set"]]
        )
        source_basis, private, verified = evidence._evidence(
            s, ctx, pid, reads, (data.source,), io=False
        )
        _require(
            evidence.digest(data.source) in verified,
            "政策原件未覆盖固定原行。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
        _require(
            not private or (value.visibility == "private" and value.owner_id == ctx.requester_id),
            "私有出处不能借政策扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        marks = direct._source_watermarks(s, ctx, pid, source_basis)
        raw = data.model_dump(mode="json")
        fingerprint = common.digest(
            {
                "operation": POLICY_OPERATION,
                "tenant": str(ctx.tenant_id),
                "product": str(pid),
                "actor": str(ctx.requester_id),
                "payload": raw,
            }
        )
        keys = list(
            s.scalars(
                select(RequestKey)
                .where(
                    RequestKey.tenant_id == ctx.tenant_id,
                    RequestKey.actor_id == ctx.actor_id,
                    RequestKey.key == request_key,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        _require(
            len(keys) <= 1 and (not keys or keys[0].digest == fingerprint),
            "请求编号对应了不同的政策发布内容。",
            "DUPLICATE_INTENT_CONFLICT",
        )
        receipts = list(
            s.scalars(
                select(Receipt)
                .where(
                    Receipt.tenant_id == ctx.tenant_id,
                    Receipt.product_id == pid,
                    Receipt.operation == POLICY_OPERATION,
                    Receipt.actor_id == ctx.actor_id,
                    Receipt.intent_digest == fingerprint,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        _require(len(receipts) <= 1, "政策发布存在重复意图回执。", "INTEGRITY_MISMATCH", 503)
        self._final(s, ctx, pid, scope, value, marks, auth, uow, caller, runtime)
        if receipts:
            receipt = receipts[0]
            saved = snapshot_get(s, Fact, receipt.subject_id, scope_id=pid)
            _require(
                saved is not None
                and saved.fact_sha256 == fact_hash(saved)
                and saved.input_snapshot.get("payload") == raw
                and saved.material == value.model_dump(mode="json")
                and saved.source_basis == source_basis
                and saved.receipt_id == receipt.id
                and (not keys or keys[0].receipt_id == receipt.id),
                "原政策发布事实或请求绑定已经变化。",
                "INTEGRITY_MISMATCH",
                503,
            )
            _common(s, ctx, pid, saved)
            _require(
                signature_current(s, ctx, pid, data.project_id, saved.authority_snapshot),
                "原政策签署水位需要重核。",
                "RECHECK_REQUIRED",
            )
            common.remember_key(s, ctx, request_key, fingerprint, receipt)
            return common.receipt_view(receipt)
        _require(not keys, "政策请求编号缺对应完整事实。", "INTEGRITY_MISMATCH", 503)
        pointer = _pointer(s, ctx, pid, scope, value.purpose, lock=True)
        prior = _fact(s, ctx, pid, scope, value.purpose, pointer)
        _require(
            (data.expected_previous is None and prior is None)
            or (
                data.expected_previous is not None
                and prior is not None
                and (data.expected_previous.id, data.expected_previous.revision)
                == (prior.id, prior.revision)
            ),
            "政策续版须明确基于当前固定版。",
            "VERSION_CONFLICT",
        )
        _require(
            prior is None
            or (prior.owner_id, prior.visibility) == (value.owner_id, value.visibility),
            "政策系列owner和共享范围不能借续版改变。",
            "FORBIDDEN_SCOPE",
            403,
        )
        cmd = Command(
            command_id=command_id,
            idempotency_key=request_key,
            operation=POLICY_OPERATION,
            category_id=ctx.category_id,
            product_id=pid,
            expected_revision=product.revision,
            source_read_set=reads,
            payload=raw,
        )
        identity, receipt_id = uuid4(), uuid4()
        row = Fact(
            id=identity,
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=pid,
            project_id=data.project_id,
            series_id=prior.series_id if prior else identity,
            revision=prior.revision + 1 if prior else 1,
            epoch=prior.epoch + 1 if prior else 1,
            previous_id=prior.id if prior else None,
            previous_revision=prior.revision if prior else None,
            purpose=value.purpose,
            purpose_sha256=common.digest(value.purpose),
            policy_version=value.policy_version,
            owner_id=value.owner_id,
            writer_id=ctx.actor_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            visibility=value.visibility,
            status=value.status,
            nature=value.nature,
            operation=POLICY_OPERATION,
            command_id=command_id,
            receipt_id=receipt_id,
            intent_digest=fingerprint,
            request_digest=fingerprint,
            material=value.model_dump(mode="json"),
            material_sha256=common.digest(value.model_dump(mode="json")),
            source=data.source.model_dump(mode="json"),
            sources=[data.source.model_dump(mode="json")],
            required_source_read_set=reads,
            source_basis=source_basis,
            authority_snapshot=auth,
            input_snapshot={
                "payload": raw,
                "original_key_sha256": sha256(request_key.encode()).hexdigest(),
            },
            valid_from=value.valid_from,
            valid_until=value.valid_until,
            created_at=now(),
        )
        row.fact_sha256 = fact_hash(row)
        row.prepared_receipt_id = receipt_id
        s.add(row)
        s.flush([row])
        if pointer is None:
            s.add(
                Current(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    product_id=pid,
                    project_id=data.project_id,
                    purpose_sha256=row.purpose_sha256,
                    series_id=row.series_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    fact_id=row.id,
                    revision=row.revision,
                    epoch=row.epoch,
                )
            )
        else:
            pointer.fact_id, pointer.revision, pointer.epoch = row.id, row.revision, row.epoch
        receipt = common.append_receipt(
            s, ctx, cmd, POLICY_FAMILY, row, fingerprint, fingerprint, row.visibility
        )
        common.remember_key(s, ctx, request_key, fingerprint, receipt)
        return common.receipt_view(receipt)

    @staticmethod
    def _configurations(s, ctx, pid, value):
        config = value.subject_config
        rows = []
        for model, wanted in (
            (DefinitionRevision, config.definition),
            (EngineeringConfiguration, config.engineering_configuration),
            (ProcessRevision, config.manufacturing_configuration),
        ):
            actual = snapshot_get(s, model, wanted.id, scope_id=pid)
            _require(
                actual is not None
                and actual.tenant_id == ctx.tenant_id
                and actual.product_id == pid
                and actual.revision == wanted.revision
                and (actual.visibility != "private" or actual.owner_id == ctx.requester_id)
                and (value.visibility == "private" or actual.visibility != "private"),
                "政策所引定义和双配置须有真实同型号、同版且可共享的固定出处。",
                "FORBIDDEN_SCOPE",
                403,
            )
            rows.append(actual)
        _, engineering, process = rows
        _require(
            (engineering.definition_id, engineering.definition_revision)
            == (config.definition.id, config.definition.revision)
            and (process.engineering_configuration_id, process.engineering_revision)
            == (config.engineering_configuration.id, config.engineering_configuration.revision),
            "政策定义、工程与制造配置绑定不一致。",
            "CONFIGURATION_MISMATCH",
        )

    def _final(self, s, ctx, pid, scope, value, marks, auth, uow, caller, runtime):
        _scope(s, ctx, pid, scope, value.purpose, write=True)
        direct._watermarks_current(s, ctx, pid, marks)
        _require(
            signature_current(s, ctx, pid, scope.project_id, auth)
            and professional.authority_time_current(auth, now()),
            "政策发布期间实际签署权限水位变化。",
            "RECHECK_REQUIRED",
        )
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "政策发布期间真实运行时变化。")


def policy_rules_reads(values):
    """Canonical exact source versions without an arbitrary source count cap."""
    unique = {}
    for value in values:
        read = SourceRead.model_validate(value)
        _require(
            read.artifact_id not in unique or unique[read.artifact_id] == read.expected_revision,
            "同一政策来源出现冲突版本。",
        )
        unique[read.artifact_id] = read.expected_revision
    return [
        {"artifact_id": str(identity), "expected_revision": unique[identity]}
        for identity in sorted(unique, key=str)
    ]
