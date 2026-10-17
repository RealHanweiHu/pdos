"""Actual original/host evidence reads; no network, qualification or business write.

Only an explicitly registered host callback can attest a verification challenge.
Reads are opaque and bound to the real caller/Engine/Session/UOW. Persisted bases
are consumed only after the host binds their immutable common atom/digest.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pydantic_core import to_jsonable_python
from sqlalchemy import select

from pdos_next import service as common
from pdos_next.contracts import SourceRead
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as originals
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.manufacturing_baseline.models import PreparationVersion
from pdos_next.domain.manufacturing_trials import native_material_owner as direct
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.domain.release import rules as release
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, OriginalSecurity, Product, UploadedOriginal
from pdos_next.request_proof import snapshot_get, snapshot_mappings, snapshot_rows
from pdos_next.safety import verify_test_target
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from . import rules
from .evidence_schemas import HandoffContract
from .schemas import AuthorizePayload, Destination, OriginalRef, ReceiptIssuer, ReceiptOriginal

_TOKEN = object()
_REGISTRY = "_pdos_handoff_evidence_issuers"
_EPOCHS = "_pdos_handoff_evidence_epochs"
_SCHEMA = "pdos-handoff-evidence-read-v1"
_OBJECT_VALUES = {
    EngineeringConfiguration: ("design_versions",),
    ProcessRevision: ("operations",),
    PartIdentity: ("external_design_refs",),
    DefinitionRevision: ("use_cases", "requirements", "constraints", "unknowns", "exclusions"),
}
_MODELS = {
    model.__tablename__: model
    for model in (
        Product,
        Project,
        Artifact,
        UploadedOriginal,
        OriginalSecurity,
        DefinitionRevision,
        EngineeringConfiguration,
        ProcessRevision,
        BomRevision,
        BomLine,
        PartIdentity,
        PreparationVersion,
    )
}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


class IssuerContext:
    __slots__ = (
        "key",
        "version",
        "tenant_id",
        "product_id",
        "project_id",
        "destination",
        "nature",
        "epoch",
        "verify",
        "current",
        "_token",
    )

    def __init__(self, token, **values):
        if token is not _TOKEN:
            raise ValueError("Evidence issuer must be configured by the actual host")
        object.__setattr__(self, "_token", token)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("Evidence issuer is immutable")


def _configure(
    engine, *, key, version, tenant_id, product_id, project_id, destination, verify, current, nature
):
    if (
        not all(isinstance(value, str) and value.strip() for value in (key, version))
        or not all(isinstance(value, UUID) for value in (tenant_id, product_id, project_id))
        or not callable(verify)
        or (current is not None and not callable(current))
    ):
        raise ValueError("Exact host scope and an actual verification callback are required")
    registry, epochs = dict(getattr(engine, _REGISTRY, {})), dict(getattr(engine, _EPOCHS, {}))
    previous = registry.get(key)
    if previous is not None and (
        previous.tenant_id,
        previous.product_id,
        previous.project_id,
        previous.nature,
    ) != (tenant_id, product_id, project_id, nature):
        raise ValueError("An issuer key cannot replace another scope or source nature")
    epoch = epochs.get(key, 0)
    if type(epoch) is not int or epoch < 0:
        raise ValueError("Issuer epoch cannot be verified")
    epochs[key] = epoch + 1
    value = IssuerContext(
        _TOKEN,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        destination=Destination.model_validate(destination),
        nature=nature,
        epoch=epochs[key],
        verify=verify,
        current=current,
    )
    registry[key] = value
    setattr(engine, _REGISTRY, registry)
    setattr(engine, _EPOCHS, epochs)
    return value


def configure_issuer(
    engine, *, key, version, tenant_id, product_id, project_id, destination, verify, current=None
):
    """Host-only provisioning after actual identity/signature validation; no grant."""
    return _configure(
        engine,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        destination=destination,
        verify=verify,
        current=current,
        nature="real",
    )


def configure_local_synthetic(
    engine,
    *,
    key,
    version,
    tenant_id,
    product_id,
    project_id,
    destination,
    verify,
    current=None,
    enabled=False,
    test_marker_verified=False,
):
    if enabled is not True or test_marker_verified is not True:
        raise ValueError("Synthetic evidence requires explicit isolated-test enablement")
    verify_test_target(engine)
    return _configure(
        engine,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        destination=destination,
        verify=verify,
        current=current,
        nature="synthetic",
    )


def revoke_issuer(engine, key):
    registry, epochs = dict(getattr(engine, _REGISTRY, {})), dict(getattr(engine, _EPOCHS, {}))
    registry.pop(key, None)
    epochs[key] = epochs.get(key, 0) + 1
    setattr(engine, _REGISTRY, registry)
    setattr(engine, _EPOCHS, epochs)


@dataclass(frozen=True, eq=False)
class ContractRead:
    contract_read: bool | None
    required_mapping_refs: tuple | None
    required_manifest_refs: tuple | None
    mappings: tuple
    files: tuple
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    source_basis: dict
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class ReceiptRead:
    original: ReceiptOriginal
    issuer: ReceiptIssuer
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    source_basis: dict
    issuer_current: bool = True
    sources_current: bool = True


class _Proof:
    __slots__ = ("__weakref__",)

    def __reduce__(self):
        raise TypeError("Actual host proof cannot leave its verification UOW")


class _Challenge:
    __slots__ = (
        "__weakref__",
        "_owner",
        "kind",
        "source",
        "source_metadata",
        "material",
        "scope",
        "category_id",
        "destination",
    )

    def __init__(self, owner, kind, source, metadata, material, scope, category):
        self._owner, self.kind, self.source = owner, kind, source
        self.source_metadata, self.material = deepcopy(metadata), material
        self.scope, self.category_id, self.destination = scope, category, material.destination

    def attest(self, watermark=None):
        """Only the configured callback calls this after its actual verification."""
        return self._owner._attest(self, watermark)

    def __reduce__(self):
        raise TypeError("Actual verification challenge cannot leave its UOW")


def _mark(row):
    value = direct._mark(row)
    value["rows"][0].update(
        to_jsonable_python(
            {name: deepcopy(getattr(row, name)) for name in _OBJECT_VALUES.get(type(row), ())}
        )
    )
    return value


def _metadata(s, ctx, pid, model, identities, key="id"):
    identities = sorted({UUID(str(value)) for value in identities}, key=str)
    rows = (
        snapshot_mappings(
            s,
            select(
                *(
                    getattr(model, name)
                    for name in (*direct._fields(model), *_OBJECT_VALUES.get(model, ()))
                )
            )
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
        "rows": sorted(
            (to_jsonable_python(dict(row)) for row in rows), key=lambda value: value["id"]
        ),
    }


class ActualHandoffEvidenceOwner:
    def __init__(self, engine):
        self.engine = engine
        self._reads, self._cache, self._challenges, self._proofs = (
            WeakKeyDictionary() for _ in range(4)
        )

    def _runtime(self, s):
        runtime = getattr(self.engine, "_pdos_external_handoff", None)
        _require(
            s.get_bind() is self.engine
            and runtime is not None
            and getattr(runtime, "evidence_owner", None) is self,
            "移交原件必须由本运行时的实际同Session owner读取。",
            "INTEGRATION_REQUIRED",
            503,
        )
        return (
            id(runtime),
            id(originals._evidence),
            id(common.source_for),
            id(getattr(self.engine, "_pdos_change_store", None)),
            tuple(
                sorted(
                    (
                        key,
                        id(value),
                        value.version,
                        value.epoch,
                        id(value.verify),
                        id(value.current),
                    )
                    for key, value in getattr(self.engine, _REGISTRY, {}).items()
                )
            ),
            tuple(sorted(getattr(self.engine, _EPOCHS, {}).items())),
        )

    def _issuer(self, ctx, pid, destination, project_id=None, *, required=True):
        matches = [
            value
            for value in getattr(self.engine, _REGISTRY, {}).values()
            if type(value) is IssuerContext
            and value._token is _TOKEN
            and (value.tenant_id, value.product_id, value.destination)
            == (ctx.tenant_id, pid, destination)
            and (project_id is None or value.project_id == project_id)
        ]
        _require(
            len(matches) <= 1,
            "同一接收范围存在多个宿主issuer，不能默选。",
            "INTEGRATION_REQUIRED",
            503,
        )
        if not matches:
            _require(not required, "尚未配置本范围真实原件验证宿主。", "INTEGRATION_REQUIRED", 503)
            return None
        issuer = matches[0]
        _require(
            getattr(self.engine, _EPOCHS, {}).get(issuer.key) == issuer.epoch,
            "宿主issuer已撤回或重配。",
        )
        return issuer

    def _scope(self, s, ctx, pid, project_id, purpose=None):
        product = common.require_access(s, ctx, pid)
        project = snapshot_get(s, Project, project_id, scope_id=pid)
        _require(
            project is not None
            and (project.tenant_id, project.category_id, project.product_id)
            == (ctx.tenant_id, ctx.category_id, pid)
            and (project.visibility != "private" or project.owner_id == ctx.requester_id)
            and (purpose is None or purpose == project.purpose),
            "原件不在本人的实际项目、品类或用途范围。",
            "FORBIDDEN_SCOPE",
            403,
        )
        return Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id), [
            _mark(product),
            _mark(project),
        ]

    def _parse(self, s, ctx, pid, source, model, *, optional=False):
        artifact = common.source_for(s, ctx, pid, source.id, source.revision)
        _require(artifact.content_hash == common.digest(artifact.content), "原文内容摘要不一致。")
        match = originals.POSITION.fullmatch(source.position)
        lines = artifact.content.splitlines()
        _require(
            match is not None and 0 < int(match[1]) <= len(lines),
            "须固定完整原文行。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
        line = lines[int(match[1]) - 1]
        _require(sha256(line.encode()).hexdigest() == match[2], "原文行摘要已变化。")
        try:
            raw = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        except json.JSONDecodeError:
            if optional:
                return None
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "回执须有完整结构化原文行。", 422
            ) from None
        except ValueError as error:
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "原文拒绝重复键及非有限数。", 422
            ) from error
        wanted = (
            "pdos-external-handoff-contract-v1"
            if model is HandoffContract
            else "pdos-external-receipt-v1"
        )
        if optional and (not isinstance(raw, dict) or raw.get("schema_version") != wanted):
            return None
        try:
            return model.model_validate(raw)
        except (ValueError, TypeError) as error:
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "原文须符合完整封闭移交/回执合同。", 422
            ) from error

    def _evidence(self, s, ctx, pid, sources, files=()):
        reads = release._canonical_reads(
            [
                *(
                    {"artifact_id": value.id, "expected_revision": value.revision}
                    for value in sources
                ),
                *(
                    {"artifact_id": value.artifact.id, "expected_revision": value.artifact.revision}
                    for value in files
                ),
            ]
        )
        # Distinct mounted Artifact rows can reference one physical original.
        # Read its bytes once; aliases still receive their own metadata proof.
        seen, groups = set(), {True: [], False: []}
        for value in reads:
            row = common.source_for(s, ctx, pid, value.artifact_id, value.expected_revision)
            io = row.original_id is None or row.original_id not in seen
            if row.original_id is not None:
                seen.add(row.original_id)
            groups[io].append(value)
        basis, private = {}, False
        for io, selected in groups.items():
            if not selected:
                continue
            ids = {value.artifact_id for value in selected}
            actual, hidden, _ = originals._evidence(
                s,
                ctx,
                pid,
                [value.model_dump(mode="json") for value in selected],
                tuple(value for value in sources if value.id in ids),
                io=io,
            )
            basis.update(actual)
            private |= hidden
        return (
            reads,
            to_jsonable_python(basis),
            private,
            direct._source_watermarks(s, ctx, pid, basis),
        )

    def _objects(self, s, ctx, pid, material):
        marks, cache = [], {}

        def row(model, identity, revision=None):
            key = model, identity
            if key not in cache:
                value = snapshot_get(s, model, identity, scope_id=pid)
                _require(
                    value is not None
                    and value.tenant_id == ctx.tenant_id
                    and value.product_id == pid
                    and getattr(value, "category_id", ctx.category_id) in (None, ctx.category_id)
                    and (
                        getattr(value, "visibility", None) != "private"
                        or value.owner_id == ctx.requester_id
                    ),
                    "映射对象不在当前真实可读范围。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                cache[key] = value
                marks.append(_mark(value))
            value = cache[key]
            _require(revision is None or value.revision == revision, "映射须固定实际对象版本。")
            return value

        config = material.subject_config
        refs = tuple(
            dict.fromkeys(
                (*material.required_mapping_refs, *(value.ref for value in material.mappings))
            )
        )
        for value in refs:
            if value.kind in {"definition", "engineering_configuration", "process_revision"}:
                field = {
                    "definition": "definition",
                    "engineering_configuration": "engineering_configuration",
                    "process_revision": "manufacturing_configuration",
                }[value.kind]
                expected = getattr(config, field)
                _require(
                    (value.id, value.revision) == (expected.id, expected.revision),
                    "映射不是本次固定定义或配置。",
                )
                row(
                    {
                        "definition": DefinitionRevision,
                        "engineering_configuration": EngineeringConfiguration,
                        "process_revision": ProcessRevision,
                    }[value.kind],
                    value.id,
                    value.revision,
                )
            elif value.kind in {"bom_revision", "part"}:
                eng = row(
                    EngineeringConfiguration,
                    config.engineering_configuration.id,
                    config.engineering_configuration.revision,
                )
                if value.kind == "bom_revision":
                    _require(
                        (value.id, value.revision) == (eng.bom_id, eng.bom_revision),
                        "BOM映射不属于本次固定工程配置。",
                    )
                    row(BomRevision, value.id, value.revision)
                else:
                    part = row(PartIdentity, value.id, value.revision)
                    lines = snapshot_rows(
                        s,
                        ("handoff-part", eng.bom_id, part.id),
                        select(BomLine).where(
                            BomLine.tenant_id == ctx.tenant_id,
                            BomLine.product_id == pid,
                            BomLine.bom_id == eng.bom_id,
                            BomLine.part_id == part.id,
                        ),
                        scope_id=pid,
                    )
                    _require(
                        bool(lines) and all(line.part_revision == part.revision for line in lines),
                        "物料映射须有本次真实BOM行关系。",
                    )
                    marks.extend(_mark(line) for line in lines)
            elif value.kind in {"work_instruction", "control_plan"}:
                document = row(PreparationVersion, value.id, value.revision)
                _require(
                    document.kind == value.kind
                    and document.project_id == material.scope.project_id
                    and (document.process_id, document.process_revision)
                    == (
                        config.manufacturing_configuration.id,
                        config.manufacturing_configuration.revision,
                    ),
                    "文档映射不属于本次实际工艺/项目。",
                )
            else:
                artifact = common.source_for(s, ctx, pid, value.id, value.revision)
                marks.append(_mark(artifact))
        return marks

    def _attest(self, challenge, watermark):
        pending = self._challenges.get(challenge)
        _require(
            pending is not None, "验证挑战不属于当前实际宿主调用。", "INTEGRATION_REQUIRED", 503
        )
        s, ctx, pid, issuer, binding = pending
        _same_uow(s, binding[0], ctx, binding[1])
        _require(
            watermark is None or (type(watermark) is dict and issuer.current is not None),
            "额外外部/资格水位须配置实际current回调。",
            "INTEGRATION_REQUIRED",
            503,
        )
        proof = _Proof()
        self._proofs[proof] = challenge, to_jsonable_python(deepcopy(watermark))
        return proof

    def _verified(self, s, ctx, pid, issuer, kind, source, metadata, material, scope):
        challenge = _Challenge(self, kind, source, metadata, material, scope, ctx.category_id)
        self._challenges[challenge] = s, ctx, pid, issuer, (_uow(s), common.digest(vars(ctx)))
        fixed = common.digest(
            to_jsonable_python(
                {
                    "kind": kind,
                    "source": source,
                    "source_metadata": metadata,
                    "material": material,
                    "scope": scope,
                    "category": ctx.category_id,
                    "destination": material.destination,
                }
            )
        )
        try:
            result = issuer.verify(s, ctx, pid, challenge)
            value = self._proofs.pop(result, None) if type(result) is _Proof else None
            _require(
                value is not None and value[0] is challenge,
                "宿主须返回本次真实验证的不可复制证明。",
                "INTEGRATION_REQUIRED",
                503,
            )
            _require(
                fixed
                == common.digest(
                    to_jsonable_python(
                        {
                            "kind": challenge.kind,
                            "source": challenge.source,
                            "source_metadata": challenge.source_metadata,
                            "material": challenge.material,
                            "scope": challenge.scope,
                            "category": challenge.category_id,
                            "destination": challenge.destination,
                        }
                    )
                ),
                "验证期间固定来源或范围被改写。",
            )
            _same_uow(s, self._challenges[challenge][4][0], ctx, self._challenges[challenge][4][1])
        finally:
            self._challenges.pop(challenge, None)
        current = self._issuer(ctx, pid, material.destination, scope.project_id)
        _require(current is issuer, "验证期间实际issuer被撤回或重配。")
        return {
            "key": issuer.key,
            "version": issuer.version,
            "epoch": issuer.epoch,
            "nature": issuer.nature,
            "destination": issuer.destination.model_dump(mode="json"),
            "scope": scope.model_dump(mode="json"),
            "category_id": str(ctx.category_id),
            "source": source.model_dump(mode="json"),
            "source_sha256": metadata["sha256"],
            "original_sha256": metadata.get("original_sha256"),
            "material_sha256": common.digest(material),
            "kind": kind,
            "watermark": value[1],
        }

    def _basis(self, scope, category, destination, sources, marks, proof, unverified_issuer=None):
        return to_jsonable_python(
            {
                "schema_version": _SCHEMA,
                "scope": scope,
                "category_id": category,
                "destination": destination,
                "artifact_sources": sources,
                "watermarks": direct._merge_marks(marks),
                "verification": proof,
                "unverified_issuer": (
                    {
                        "key": unverified_issuer.key,
                        "version": unverified_issuer.version,
                        "epoch": unverified_issuer.epoch,
                    }
                    if unverified_issuer is not None
                    else None
                ),
                "proof_sha256": common.digest(proof) if proof is not None else None,
            }
        )

    def _contract(self, s, ctx, pid, payload):
        scope, marks = self._scope(s, ctx, pid, payload.project_id, payload.purpose)
        sources = tuple(dict.fromkeys(release._sources(payload)))
        candidates = []
        for source in payload.sources:
            value = self._parse(s, ctx, pid, source, HandoffContract, optional=True)
            if value is not None:
                candidates.append((source, value))
        _require(
            len(candidates) <= 1, "移交合同原文不唯一，不能默选。", "MISSING_REQUIRED_EVIDENCE", 422
        )
        issuer = self._issuer(ctx, pid, payload.destination, scope.project_id, required=False)
        if not candidates or issuer is None:
            reads, artifacts, private, source_marks = self._evidence(s, ctx, pid, sources)
            _require(
                payload.visibility == "private" or not private,
                "私人原件不能扩大共享。",
                "FORBIDDEN_SCOPE",
                403,
            )
            return ContractRead(
                None,
                None,
                None,
                (),
                (),
                sources,
                reads,
                self._basis(
                    scope,
                    ctx.category_id,
                    payload.destination,
                    artifacts,
                    [*marks, *source_marks],
                    None,
                    unverified_issuer=issuer,
                ),
                (
                    "HANDOFF_CONTRACT_OWNER_UNCONNECTED"
                    if issuer is None
                    else "HANDOFF_CONTRACT_ORIGINAL_MISSING",
                ),
            )
        source, material = candidates[0]
        _require(
            material.scope == scope
            and material.category_id == ctx.category_id
            and material.subject_config == payload.subject_config
            and material.purpose == payload.purpose
            and material.destination == payload.destination
            and rules.scope_covers(material.release_scope, payload.release_scope),
            "合同原文须固定同项目、配置、用途、接收方与覆盖范围。",
            "FORBIDDEN_SCOPE",
            403,
        )
        sources = tuple(dict.fromkeys((*sources, *release._sources(material))))
        reads, artifacts, private, source_marks = self._evidence(
            s, ctx, pid, sources, material.files
        )
        _require(
            payload.visibility == "private" or not private,
            "私人合同或文件不能扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        marks.extend(self._objects(s, ctx, pid, material))
        for file in material.files:
            actual = artifacts[str(file.artifact.id)]
            _require(
                file.content_sha256 == actual.get("original_sha256", actual["sha256"]),
                "Manifest须核对实际Artifact/原件的内容摘要。",
            )
        proof = self._verified(
            s, ctx, pid, issuer, "contract", source, artifacts[str(source.id)], material, scope
        )
        return ContractRead(
            True,
            material.required_mapping_refs,
            material.required_manifest_refs,
            material.mappings,
            material.files,
            sources,
            reads,
            self._basis(
                scope,
                ctx.category_id,
                material.destination,
                artifacts,
                [*marks, *source_marks],
                proof,
            ),
        )

    def _receipt(self, s, ctx, pid, source, *, project_id):
        original = self._parse(s, ctx, pid, source, ReceiptOriginal)
        issuer = self._issuer(ctx, pid, original.destination, project_id)
        scope, marks = self._scope(s, ctx, pid, project_id)
        sources = (source,)
        reads, artifacts, _, source_marks = self._evidence(s, ctx, pid, sources)
        proof = self._verified(
            s, ctx, pid, issuer, "receipt", source, artifacts[str(source.id)], original, scope
        )
        return ReceiptRead(
            original,
            ReceiptIssuer(
                key=issuer.key,
                version=issuer.version,
                epoch=issuer.epoch,
                system=issuer.destination.system,
                subject_id=issuer.destination.recipient_id,
                proof_sha256=common.digest(proof),
            ),
            sources,
            reads,
            self._basis(
                scope,
                ctx.category_id,
                original.destination,
                artifacts,
                [*marks, *source_marks],
                proof,
            ),
        )

    def _snapshot(self, value):
        return common.digest(to_jsonable_python(vars(value)))

    def _binding(self, s, ctx, pid, value):
        saved = self._reads.get(value)
        _require(
            saved is not None
            and saved[0]() is s
            and saved[3] == pid
            and saved[4] == self._runtime(s)
            and saved[5] == self._snapshot(value),
            "原件读取须为当前实际owner签发的完整不变对象。",
            "FACT_CALLER_UOW_CHANGED",
        )
        _same_uow(s, saved[1], ctx, saved[2])

    def _read(self, s, ctx, pid, kind, payload, *, project_id=None):
        require_context(s, ctx)
        uow, caller, runtime = _uow(s), common.digest(vars(ctx)), self._runtime(s)
        key = common.digest(
            {
                "kind": kind,
                "payload": payload,
                "caller": caller,
                "pid": pid,
                "project_id": project_id,
            }
        )
        cache = self._cache.get(s)
        if cache is not None and cache[0] == uow and key in cache[1]:
            self._binding(s, ctx, pid, cache[1][key])
            return cache[1][key]
        value = (
            self._contract(s, ctx, pid, payload)
            if kind == "contract"
            else self._receipt(s, ctx, pid, payload, project_id=project_id)
        )
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "原件读取期间运行时变化。")
        self._reads[value] = ref(s), uow, caller, pid, runtime, self._snapshot(value)
        if cache is None or cache[0] != uow:
            self._cache[s] = uow, {}
        self._cache[s][1][key] = value
        return value

    def read_contract(self, s, ctx, pid, payload):
        return self._read(s, ctx, pid, "contract", AuthorizePayload.model_validate(payload))

    def read_receipt(self, s, ctx, pid, source, *, project_id):
        _require(
            isinstance(project_id, UUID),
            "回执读取须绑定已保存授权的实际项目。",
            "FORBIDDEN_SCOPE",
            403,
        )
        value = source.model_dump(mode="json") if isinstance(source, SourceRef) else source
        return self._read(
            s, ctx, pid, "receipt", OriginalRef.model_validate(value), project_id=project_id
        )

    def current(self, s, ctx, pid, read_or_basis):
        require_context(s, ctx)
        runtime, uow, caller = self._runtime(s), _uow(s), common.digest(vars(ctx))
        if type(read_or_basis) in {ContractRead, ReceiptRead}:
            self._binding(s, ctx, pid, read_or_basis)
            basis = read_or_basis.source_basis
        else:
            basis = read_or_basis
        _require(
            type(basis) is dict
            and basis.get("schema_version") == _SCHEMA
            and basis.get("category_id") == str(ctx.category_id),
            "缺少实际封存的原件读取水位。",
        )
        scope = Scope.model_validate(basis["scope"])
        _require(
            scope.tenant_id == ctx.tenant_id and scope.product_id == pid,
            "原件水位不在当前范围。",
            "FORBIDDEN_SCOPE",
            403,
        )
        self._scope(s, ctx, pid, scope.project_id)
        proof = basis["verification"]
        issuer = self._issuer(
            ctx,
            pid,
            Destination.model_validate(basis["destination"]),
            scope.project_id,
            required=False,
        )
        if proof is None:
            expected = basis.get("unverified_issuer")
            _require(
                (issuer is None and expected is None)
                or (
                    issuer is not None
                    and expected
                    == {"key": issuer.key, "version": issuer.version, "epoch": issuer.epoch}
                ),
                "未接宿主已有变化，请重新读取真实合同。",
            )
        else:
            _require(
                issuer is not None
                and common.digest(proof) == basis["proof_sha256"]
                and issuer.key == proof["key"]
                and issuer.version == proof["version"]
                and issuer.epoch == proof["epoch"]
                and issuer.nature == proof["nature"],
                "宿主issuer或固定验证证明已变化。",
            )
            metadata = basis["artifact_sources"].get(proof["source"]["id"])
            _require(
                proof["scope"] == basis["scope"]
                and proof["category_id"] == basis["category_id"]
                and proof["destination"] == basis["destination"]
                and metadata is not None
                and metadata["sha256"] == proof["source_sha256"]
                and metadata.get("original_sha256") == proof["original_sha256"],
                "验证证明须绑定实际完整来源及本次scope/category/destination。",
            )
            if issuer.current is None:
                _require(proof["watermark"] is None, "额外证明水位缺少实际current端口。")
            else:
                actual = issuer.current(s, ctx, pid, issuer, deepcopy(proof["watermark"]))
                _require(
                    actual is True or (type(actual) is dict and actual == proof["watermark"]),
                    "实际外部登记或资格水位已变化。",
                )
        for mark in basis["watermarks"]:
            _require(
                mark.get("table") in _MODELS and mark.get("key") in {"id", "original_id"},
                "无效的固定来源水位。",
            )
            model = _MODELS[mark["table"]]
            actual = _metadata(s, ctx, pid, model, mark["ids"], mark["key"])
            _require(
                len(actual["rows"]) == len(mark["rows"]),
                "实际来源已不可读。",
                "SOURCE_UNAVAILABLE",
                403,
            )
            for row in actual["rows"]:
                _require(
                    row.get("category_id") in (None, str(ctx.category_id))
                    and (
                        model is Product
                        or row.get("visibility") != "private"
                        or row.get("owner_id") == str(ctx.requester_id)
                    ),
                    "实际原件或对象已不在本人可读范围。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                if model is Artifact:
                    _require(row["status"] == "active", "原文已撤回。", "SOURCE_UNAVAILABLE")
                if model is OriginalSecurity:
                    _require(
                        row["source_state"] == row["disposition"] == "active",
                        "原件安全或撤回状态已变化。",
                        "SOURCE_UNAVAILABLE",
                    )
            _require(actual == mark, "实际原件、固定对象或安全摘要水位已变化。")
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "水位核对期间实际宿主已变化。")
        return True
