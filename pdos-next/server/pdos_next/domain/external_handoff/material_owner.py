"""Actual fixed package/decisions and bounded handoff originals in one UOW.

Historical common atoms retain their original storage-guarded proof. This owner
reads their real immutable rows, reciprocal common members and signature Current
watermarks, without reopening historical professional qualification or bytes.
Only the new handoff originals enter the new command's direct read set.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pydantic_core import to_jsonable_python
from sqlalchemy import select

from pdos_next.contracts import SourceRead
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_trials import native_material_owner as direct
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.release import rules as release_rules
from pdos_next.domain.release import service as releases
from pdos_next.domain.release.models import ReleaseDecision as Decision
from pdos_next.domain.release.models import ReleasePackage as Package
from pdos_next.domain.release.models import ReleasePackageCurrent as Current
from pdos_next.domain.release.schemas import OPERATIONS, DecisionPlan, PackagePlan, ReleaseMaterial
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Outbox, Receipt, now
from pdos_next.receipt_request_binding import readable_receipt_request_bound
from pdos_next.request_proof import snapshot_get, snapshot_mappings, snapshot_rows
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import digest, require_access

from .schemas import ActualData, ActualDecision, AuthorizePayload

_SCHEMA = "pdos-external-handoff-material-v1"
_MODELS = {
    model.__tablename__: model for model in (Package, Current, Decision, Receipt, Audit, Outbox)
}
_BASIS_FIELDS = {
    "schema_version",
    "scope",
    "category_id",
    "watermarks",
    "release_material",
    "release_basis",
    "signatures",
    "evidence_owner",
    "artifact_sources",
}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def _accessible(row, ctx, pid, project_id=None):
    return (
        row is not None
        and row.tenant_id == ctx.tenant_id
        and row.category_id == ctx.category_id
        and row.product_id == pid
        and (project_id is None or getattr(row, "project_id", project_id) == project_id)
        and (getattr(row, "visibility", None) != "private" or row.owner_id == ctx.requester_id)
    )


def _mark(s, ctx, pid, model, key, identities):
    _require(
        model.__tablename__ in _MODELS
        and key in {"id", "series_id"}
        and key in model.__table__.columns,
        "无效的移交固定水位。",
    )
    identities = sorted({UUID(str(value)) for value in identities}, key=str)
    rows = (
        snapshot_mappings(
            s,
            select(*(getattr(model, name) for name in direct._fields(model)))
            .where(model.tenant_id == ctx.tenant_id, getattr(model, key).in_(identities))
            .execution_options(autoflush=False),
            scope_id=pid,
        )
        if identities
        else []
    )
    return {
        "table": model.__tablename__,
        "key": key,
        "ids": [str(value) for value in identities],
        "rows": sorted((to_jsonable_python(dict(row)) for row in rows), key=lambda row: row["id"]),
    }


def _common(s, ctx, pid, row, *, decision=False):
    """Read exact reciprocal members; do not expose old private key/proof rows."""
    receipt = snapshot_get(s, Receipt, row.receipt_id, scope_id=pid)
    operation = row.operation
    event = OPERATIONS[operation][1]
    expected_proof = row.shared_proof_id if decision else None
    _require(
        receipt is not None
        and (
            receipt.tenant_id,
            receipt.category_id,
            receipt.product_id,
            receipt.command_id,
            receipt.confirmation_id,
            receipt.actor_id,
            receipt.requester_id,
            receipt.operation,
            receipt.subject_type,
            receipt.subject_id,
            receipt.subject_revision,
            receipt.visibility,
            receipt.request_digest,
            receipt.intent_digest,
        )
        == (
            ctx.tenant_id,
            ctx.category_id,
            pid,
            row.command_id,
            expected_proof,
            row.actor_id,
            row.requester_id,
            operation,
            "release_decision" if decision else "release_package",
            row.id,
            row.revision,
            row.visibility,
            row.request_digest,
            row.intent_digest,
        )
        and receipt.result == {"id": str(row.id), "revision": row.revision, "status": row.status}
        and receipt.created_at >= row.created_at,
        "发布材料缺实际固定共同回执绑定。",
        "STORED_ATOM_MISMATCH",
        503,
    )
    audits = snapshot_rows(
        s,
        ("handoff-release-audit", receipt.id),
        select(Audit).where(Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id),
        scope_id=pid,
    )
    outboxes = snapshot_rows(
        s,
        ("handoff-release-outbox", receipt.id),
        select(Outbox).where(Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id),
        scope_id=pid,
    )
    _require(
        len(audits) == len(outboxes) == 1
        and audits[0].category_id == ctx.category_id
        and audits[0].actor_id == receipt.actor_id
        and audits[0].operation == operation
        and (
            outboxes[0].category_id,
            outboxes[0].type,
            outboxes[0].subject_id,
            outboxes[0].subject_revision,
            outboxes[0].actor_id,
            outboxes[0].correlation_id,
            outboxes[0].schema_version,
        )
        == (
            ctx.category_id,
            event,
            row.id,
            row.revision,
            receipt.actor_id,
            receipt.agent_run_id or receipt.run_id or receipt.command_id,
            1,
        )
        and readable_receipt_request_bound(s, ctx, pid, receipt.id),
        "发布材料缺完整审计、事件或实际请求关联。",
        "STORED_ATOM_INCOMPLETE",
        503,
    )
    if decision:
        _require(
            row.writer_id == row.actor_id == row.requester_id == row.owner_id
            and receipt.run_id is None
            and receipt.agent_run_id is None
            and row.write_tier == "T2"
            and row.status == "approved"
            and row.shared_proof_id is not None
            and type(row.shared_proof_revision) is int
            and row.shared_proof_revision > 0
            and row.proof_consumed_at is not None
            and row.proof_consumed_at <= row.created_at
            and (row.proof_expires_at is None or row.created_at < row.proof_expires_at)
            and all(
                isinstance(getattr(row, key), str) and len(getattr(row, key)) == 64
                for key in ("token_sha256", "material_sha256", "read_set_sha256")
            ),
            "专业决定缺原事务固定消费证明列。",
            "STORED_ATOM_MISMATCH",
            503,
        )
    return [direct._mark(value) for value in (receipt, audits[0], outboxes[0])]


@dataclass(frozen=True, eq=False)
class HandoffMaterialRead:
    actual: ActualData
    source_basis: dict
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    checked_at: datetime


class ActualHandoffMaterialOwner:
    def __init__(self, engine):
        self.engine = engine
        self._reads, self._cache = WeakKeyDictionary(), WeakKeyDictionary()

    def _runtime(self, s):
        runtime = getattr(self.engine, "_pdos_external_handoff", None)
        _require(
            s.get_bind() is self.engine and getattr(runtime, "owner", None) is self,
            "须由实际移交runtime绑定本材料owner。",
            "INTEGRATION_REQUIRED",
            503,
        )
        return (
            id(runtime),
            id(getattr(runtime, "evidence_owner", None)),
            id(releases.get_package),
            id(signature_current),
            evidence._runtime_stamp(s),
        )

    @staticmethod
    def _snapshot(value):
        return deepcopy(
            to_jsonable_python(
                {key: getattr(value, key) for key in HandoffMaterialRead.__dataclass_fields__}
            )
        )

    def _binding(self, s, ctx, pid, value):
        saved = self._reads.get(value) if type(value) is HandoffMaterialRead else None
        _require(saved is not None, "须使用本移交owner实际发行的读取。")
        session, uow, caller, product, runtime, snapshot = saved
        _same_uow(s, uow, ctx, caller)
        _require(
            session() is s
            and product == pid
            and runtime == self._runtime(s)
            and snapshot == self._snapshot(value),
            "移交读取的实际调用、事务或封存材料已变化。",
        )

    def _collect(self, s, ctx, pid, payload):
        require_access(s, ctx, pid)
        package, viewed = releases.get_package(s, ctx, pid, payload.package.id)
        _require(
            _accessible(package, ctx, pid, payload.project_id),
            "所选发布包不在当前项目或可读范围。",
            "FORBIDDEN_SCOPE",
            403,
        )
        _require(
            package.revision == payload.package.revision,
            "须引用所选固定包的准确版本。",
            "VERSION_CONFLICT",
        )
        plan = PackagePlan.model_validate(package.body)
        scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=payload.project_id)
        _require(
            plan.scope == scope
            and plan.category_id == ctx.category_id
            and plan.model_dump(mode="json") == viewed["package"],
            "实际固定包范围或内容不一致。",
            "STORED_ATOM_MISMATCH",
            503,
        )
        marks = [direct._mark(package), *_common(s, ctx, pid, package)]
        pointer = _mark(s, ctx, pid, Current, "series_id", (package.series_id,))
        marks.append(pointer)
        package_current = (
            viewed["applicability"] == "current"
            and len(pointer["rows"]) == 1
            and pointer["rows"][0]["version_id"] == str(package.id)
            and pointer["rows"][0]["revision"] == package.revision
        )
        selected, signatures, visibility = [], [], [package.visibility]
        reading_by_id = {value["id"]: value for value in viewed["decisions"]}
        for discipline, wanted in (
            ("engineering", payload.engineering_decision),
            ("manufacturing", payload.manufacturing_decision),
        ):
            row = snapshot_get(s, Decision, wanted.id, scope_id=pid)
            marks.append(_mark(s, ctx, pid, Decision, "id", (wanted.id,)))
            if row is None:
                continue
            _require(
                _accessible(row, ctx, pid, payload.project_id),
                "所选专业决定不在当前项目或可读范围。",
                "FORBIDDEN_SCOPE",
                403,
            )
            _require(
                row.revision == wanted.revision, "须引用专业决定的准确固定版。", "VERSION_CONFLICT"
            )
            decision = DecisionPlan.model_validate(row.body)
            _require(
                row.body_sha256 == release_rules.digest(row.body)
                and (row.discipline, row.package_id, row.package_revision, row.purpose)
                == (discipline, package.id, package.revision, payload.purpose)
                and decision.discipline == discipline
                and decision.package == payload.package
                and decision.package_sha256 == plan.body_sha256
                and decision.scope == scope
                and decision.category_id == ctx.category_id
                and decision.signers == (row.actor_id,)
                and decision.subject_config == plan.declaration.subject_config
                and decision.purpose == plan.declaration.purpose
                and row.authority_snapshot.get("subject_id") == str(row.actor_id)
                and row.authority_snapshot.get("scope") == scope.model_dump(mode="json")
                and row.authority_snapshot.get("operation") == row.operation
                and row.authority_snapshot.get("purpose") == row.purpose,
                "实际专业决定内容、原具名人或包引用不一致。",
                "STORED_ATOM_MISMATCH",
                503,
            )
            matched = reading_by_id.get(str(row.id))
            _require(
                matched is not None
                and matched["decision"] == row.body
                and matched["receipt_id"] == str(row.receipt_id),
                "专业决定必须来自所选实际固定包。",
                "STORED_ATOM_MISMATCH",
                503,
            )
            marks.extend(_common(s, ctx, pid, row, decision=True))
            extra = row.source_basis.get("decision_originals")
            if extra is not None:
                marks.extend(direct._source_watermarks(s, ctx, pid, extra["basis"]))
            applicable = (
                package_current
                and matched["applicability"] == "current"
                and (decision.expiry is None or now() < decision.expiry)
            )
            selected.append(ActualDecision(ref=wanted, plan=decision, current=applicable))
            signatures.append(
                {
                    "project_id": str(row.project_id),
                    "snapshot": deepcopy(row.authority_snapshot),
                    "expiry": decision.expiry.isoformat() if decision.expiry else None,
                }
            )
            visibility.append(row.visibility)
        evidence_owner = getattr(self.engine._pdos_external_handoff, "evidence_owner", None)
        contract = None
        if evidence_owner is not None:
            from .evidence_owner import ActualHandoffEvidenceOwner

            _require(
                isinstance(evidence_owner, ActualHandoffEvidenceOwner),
                "移交直接证据须使用实际owner。",
                "INTEGRATION_REQUIRED",
                503,
            )
            contract = evidence_owner.read_contract(s, ctx, pid, payload)
        sources = (
            tuple(SourceRef.model_validate(value) for value in contract.sources) if contract else ()
        )
        reads = (
            tuple(SourceRead.model_validate(value) for value in contract.required_source_read_set)
            if contract
            else ()
        )
        artifacts = deepcopy(contract.source_basis.get("artifact_sources", {})) if contract else {}
        if any(
            value.get("visibility") == "private" or value.get("original_visibility") == "private"
            for value in artifacts.values()
        ):
            visibility.append("private")
        _require(
            payload.visibility == "private" or "private" not in visibility,
            "私有发布依据或交付原件不能借移交扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        originals_current = (
            bool(sources)
            and bool(reads)
            and bool(artifacts)
            and all(
                str(value.artifact_id) in artifacts
                and artifacts[str(value.artifact_id)]["revision"] == value.expected_revision
                for value in reads
            )
            and {str(value.artifact_id) for value in reads} == set(artifacts)
            and all(
                (value.id, value.revision)
                in {(read.artifact_id, read.expected_revision) for read in reads}
                for value in sources
                if value.kind == "artifact"
            )
        )
        if contract is not None:
            originals_current = (
                originals_current and evidence_owner.current(s, ctx, pid, contract) is True
            )
        actual = ActualData(
            scope=scope,
            category_id=ctx.category_id,
            visibility="private" if "private" in visibility else package.visibility,
            package_ref=payload.package,
            package=plan,
            package_current=package_current,
            decisions=tuple(selected),
            mappings=contract.mappings if contract else (),
            files=contract.files if contract else (),
            contract_read=contract.contract_read if contract else None,
            required_mapping_refs=contract.required_mapping_refs if contract else None,
            required_manifest_refs=contract.required_manifest_refs if contract else None,
            sources_current=originals_current if contract else None,
            sources=sources,
            required_source_read_set=reads,
        )
        basis = {
            "schema_version": _SCHEMA,
            "scope": scope.model_dump(mode="json"),
            "category_id": str(ctx.category_id),
            "watermarks": direct._merge_marks(marks),
            "release_material": deepcopy(package.material_snapshot),
            "release_basis": deepcopy(package.source_basis),
            "signatures": signatures,
            "evidence_owner": deepcopy(contract.source_basis) if contract else None,
            "artifact_sources": artifacts,
        }
        return HandoffMaterialRead(actual, to_jsonable_python(basis), sources, reads, now())

    def read(self, s, ctx, pid, payload):
        require_context(s, ctx)
        payload = AuthorizePayload.model_validate(payload)
        uow, caller, runtime = _uow(s), digest(vars(ctx)), self._runtime(s)
        key = digest(
            {
                "caller": caller,
                "product": str(pid),
                "payload": payload.model_dump(mode="json", exclude={"approval_token"}),
            }
        )
        cache = self._cache.get(s)
        if cache is not None and cache[0] == uow and key in cache[1]:
            self._binding(s, ctx, pid, cache[1][key])
            return cache[1][key]
        value = self._collect(s, ctx, pid, payload)
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "移交读取期间实际来源owner改变。")
        self._reads[value] = ref(s), uow, caller, pid, runtime, self._snapshot(value)
        if cache is None or cache[0] != uow:
            self._cache[s] = uow, {}
        self._cache[s][1][key] = value
        return value

    def current(self, s, ctx, pid, read_or_actual, source_basis=None):
        require_context(s, ctx)
        self._runtime(s)
        if type(read_or_actual) is HandoffMaterialRead:
            self._binding(s, ctx, pid, read_or_actual)
            actual, source_basis = read_or_actual.actual, read_or_actual.source_basis
        else:
            actual = ActualData.model_validate(read_or_actual)
        _require(
            type(source_basis) is dict
            and set(source_basis) == _BASIS_FIELDS
            and source_basis["schema_version"] == _SCHEMA
            and source_basis["scope"] == actual.scope.model_dump(mode="json")
            and source_basis["category_id"] == str(actual.category_id)
            and actual.scope.tenant_id == ctx.tenant_id
            and actual.scope.product_id == pid
            and actual.category_id == ctx.category_id,
            "移交材料不属于本实际品类、型号和项目。",
            "FORBIDDEN_SCOPE",
            403,
        )
        require_access(s, ctx, pid)
        known = [mark for mark in source_basis["watermarks"] if mark["table"] in direct._MODELS]
        if known:
            direct._watermarks_current(s, ctx, pid, known)
        for saved in source_basis["watermarks"]:
            if saved in known:
                continue
            _require(saved.get("table") in _MODELS, "未知的移交固定材料水位。")
            mark = _mark(s, ctx, pid, _MODELS[saved["table"]], saved["key"], saved["ids"])
            _require(mark == saved, "固定发布材料、Current或共同组水位变化。")
            for row in mark["rows"]:
                _require(
                    row.get("product_id", str(pid)) == str(pid)
                    and row.get("category_id") == str(ctx.category_id)
                    and row.get("project_id", str(actual.scope.project_id))
                    == str(actual.scope.project_id)
                    and (
                        row.get("visibility") != "private"
                        or row.get("owner_id", row.get("requester_id")) == str(ctx.requester_id)
                    ),
                    "当前不能读取所选固定材料。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
        _require(
            releases._current_material(
                s,
                ctx,
                pid,
                ReleaseMaterial.model_validate(source_basis["release_material"]),
                source_basis["release_basis"],
            )
            is True,
            "上游发布材料的直接水位需要重核。",
            "RECHECK_REQUIRED",
        )
        for signature in source_basis["signatures"]:
            _require(
                signature_current(s, ctx, pid, UUID(signature["project_id"]), signature["snapshot"])
                and (
                    signature["expiry"] is None
                    or now() < datetime.fromisoformat(signature["expiry"])
                ),
                "专业签署的直接水位或明确有效期已变化。",
                "RECHECK_REQUIRED",
            )
        contract = source_basis["evidence_owner"]
        if contract is not None:
            evidence_owner = getattr(self.engine._pdos_external_handoff, "evidence_owner", None)
            _require(
                evidence_owner is not None
                and evidence_owner.current(s, ctx, pid, contract) is True,
                "移交直接原件水位需要重核。",
                "RECHECK_REQUIRED",
            )
        return True
