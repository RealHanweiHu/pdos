"""Trusted imports and current professional assessment in the caller transaction.

No connection, commit, public self-grant, AI qualification or professional signoff.
The host verifies its environment before explicitly enabling the synthetic profile.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import inspect, select

from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, OriginalSecurity, Principal, Product, now
from pdos_next.original_lifecycle.rules import digest

from .models import ProfessionalCurrent, ProfessionalFact
from .schemas import FactInput

OPERATION_ROLES = {
    "npi.work_instruction.record": frozenset({"manufacturing"}),
    "npi.control_plan.record": frozenset({"manufacturing"}),
    "npi.manufacturing_baseline.record": frozenset({"manufacturing"}),
    "build.engineering.authorize": frozenset({"engineering"}),
    "build.manufacturing.authorize": frozenset({"manufacturing"}),
    "build.start": frozenset({"manufacturing"}),
    "build.sample.readiness.record": frozenset({"manufacturing"}),
    "verification.request.create": frozenset({"engineering", "quality"}),
    "verification.method.prepare": frozenset({"quality"}),
    "verification.schedule.propose": frozenset({"quality"}),
    "verification.actual_method.prepare": frozenset({"quality"}),
    "verification.handoff.offer": frozenset({"engineering", "manufacturing"}),
    "verification.handoff.accept": frozenset({"quality"}),
    "verification.handoff.return": frozenset({"quality"}),
    "test.run.plan": frozenset({"quality"}),
    "verification.schedule.promise": frozenset({"quality"}),
    "test.run.start": frozenset({"quality"}),
    "test.results.import": frozenset({"quality", "test"}),
    "test.result.compute": frozenset({"quality", "test"}),
    "test.run.review": frozenset({"quality"}),
    "test.disposition.decide": frozenset({"quality"}),
    "quality.issue.create": frozenset({"quality", "engineering", "test"}),
    "quality.issue.merge": frozenset({"quality", "engineering", "test"}),
    "quality.issue.triage": frozenset({"quality", "engineering", "test"}),
    "quality.issue.containment.record": frozenset({"quality", "engineering", "test"}),
    "quality.capa.draft": frozenset({"quality", "engineering", "test"}),
    "quality.issue.root_cause.decide": frozenset({"quality"}),
    "quality.capa.actions.complete": frozenset({"quality", "engineering", "test"}),
    "quality.capa.followup.link": frozenset({"quality", "engineering", "test"}),
    "quality.capa.verification.candidate.record": frozenset({"quality", "engineering", "test"}),
    "quality.capa.observation.record": frozenset({"quality", "engineering", "test"}),
    "quality.capa.verification.rule.import": frozenset({"quality"}),
    "quality.capa.verification.review": frozenset({"quality"}),
    "change.order.prepare": frozenset({"engineering", "manufacturing", "quality"}),
    "change.order.approve": frozenset({"engineering", "manufacturing", "quality"}),
    "change.implementation.record": frozenset({"engineering", "manufacturing", "quality"}),
    "change.policy.import": frozenset({"quality"}),
    "change.selection.decide": frozenset({"engineering", "manufacturing", "quality"}),
    "change.request.create": frozenset({"quality", "engineering", "manufacturing"}),
    "change.impact.compute": frozenset({"quality", "engineering", "manufacturing"}),
}
MAX_FACTS = 100
MAX_PROFILES = 20
_CAPABILITY = object()


class IssuerContext:
    """Opaque server-held object; a copied DTO/string/claim cannot replace it."""

    __slots__ = (
        "key",
        "version",
        "tenant_id",
        "product_id",
        "project_id",
        "nature",
        "epoch",
        "_token",
    )

    def __init__(self, *, token, key, version, tenant_id, product_id, project_id, nature, epoch):
        if token is not _CAPABILITY:
            raise ValueError("Issuer context must be provisioned by the trusted server")
        object.__setattr__(self, "_token", token)
        for name, value in {
            "key": key,
            "version": version,
            "tenant_id": tenant_id,
            "product_id": product_id,
            "project_id": project_id,
            "nature": nature,
            "epoch": epoch,
        }.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("Trusted issuer configuration is immutable")


def _configuration(*, key, version, tenant_id, product_id, project_id, nature):
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 100
        for value in (key, version)
    ):
        raise ValueError("Stable named issuer and version are required")
    if (
        not isinstance(tenant_id, UUID)
        or not isinstance(product_id, UUID)
        or (project_id is not None and not isinstance(project_id, UUID))
    ):
        raise ValueError("Trusted issuer scope must be exact server UUIDs")
    return {
        "key": key.strip(),
        "version": version.strip(),
        "tenant_id": tenant_id,
        "product_id": product_id,
        "project_id": project_id,
        "nature": nature,
    }


def _prepare_issuer(registry, epochs, values, *, reuse=False):
    key = values["key"]
    previous = registry.get(key)
    if previous is not None:
        if (
            not isinstance(previous, IssuerContext)
            or previous._token is not _CAPABILITY
            or any(
                getattr(previous, field) != values[field]
                for field in ("tenant_id", "product_id", "project_id", "nature")
            )
        ):
            raise ValueError("An issuer key cannot replace another trusted scope or nature")
        if reuse and previous.version != values["version"]:
            raise ValueError("A profile list cannot rotate an existing issuer version")
        if reuse and previous.version == values["version"]:
            if type(epochs.get(key)) is not int or epochs[key] != previous.epoch:
                raise ValueError("The existing issuer epoch cannot be verified")
            return previous
    epoch = epochs.get(key, 0)
    if type(epoch) is not int or epoch < 0 or (previous and epoch < previous.epoch):
        raise ValueError("The existing issuer epoch cannot be verified")
    epochs[key] = epoch + 1
    issuer = IssuerContext(
        token=_CAPABILITY,
        **values,
        epoch=epochs[key],
    )
    registry[key] = issuer
    return issuer


def _configure(engine, *, key, version, tenant_id, product_id, project_id, nature):
    values = _configuration(
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        nature=nature,
    )
    registry = dict(getattr(engine, "_pdos_professional_issuers", {}))
    epochs = dict(getattr(engine, "_pdos_professional_issuer_epochs", {}))
    issuer = _prepare_issuer(registry, epochs, values)
    engine._pdos_professional_issuers = registry
    engine._pdos_professional_issuer_epochs = epochs
    return issuer


def configure_issuer(engine, *, key, version, tenant_id, product_id, project_id=None):
    """Trusted host provisioning only, with external issuer validation owned by host."""
    issuer = _configure(
        engine,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        nature="real",
    )
    engine._pdos_professional_synthetic = False
    return issuer


def configure_local_synthetic(
    engine,
    *,
    tenant_id,
    product_id,
    project_id=None,
    key="local-synthetic-authority",
    version="v1",
    enabled=False,
):
    """Not an environment attestation: host must first verify its exact test marker."""
    if enabled is not True:
        raise ValueError("Synthetic professional authority requires explicit host enablement")
    issuer = _configure(
        engine,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        nature="synthetic",
    )
    engine._pdos_professional_synthetic = True
    return issuer


def _profile_uuid(value):
    if isinstance(value, UUID):
        return value
    if type(value) is str:
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("Trusted profile scope requires an exact UUID or UUID string")


def configure_local_synthetic_profiles(engine, profiles, *, enabled=False):
    """Host-only bounded profiles; the host first verifies its test marker.

    JSON UUID strings are normalized here. The existing single-scope API remains
    valid, and an identical active profile reuses its opaque issuer and epoch.
    Other keys/scopes are retained; a failed batch makes no registry changes.
    This configures import roots, not a person's duties or qualifications.
    """
    if enabled is not True:
        raise ValueError("Synthetic professional authority requires explicit host enablement")
    if type(profiles) is not list or not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError("Trusted profiles require an explicit list of 1..20 scopes")
    required = {"tenant_id", "product_id", "key", "version"}
    configurations = []
    for profile_value in profiles:
        if (
            type(profile_value) is not dict
            or not required <= set(profile_value)
            or not set(profile_value) <= required | {"project_id"}
        ):
            raise ValueError("Trusted profile fields must be exact server configuration")
        configurations.append(
            _configuration(
                key=profile_value["key"],
                version=profile_value["version"],
                tenant_id=_profile_uuid(profile_value["tenant_id"]),
                product_id=_profile_uuid(profile_value["product_id"]),
                project_id=_profile_uuid(profile_value["project_id"])
                if profile_value.get("project_id") is not None
                else None,
                nature="synthetic",
            )
        )
    keys = {v["key"] for v in configurations}
    scopes = {(v["tenant_id"], v["product_id"], v["project_id"]) for v in configurations}
    if len(keys) != len(configurations) or len(scopes) != len(configurations):
        raise ValueError("Each listed scope needs one distinct issuer key")
    registry = dict(getattr(engine, "_pdos_professional_issuers", {}))
    epochs = dict(getattr(engine, "_pdos_professional_issuer_epochs", {}))
    issuers = tuple(_prepare_issuer(registry, epochs, v, reuse=True) for v in configurations)
    engine._pdos_professional_issuers = registry
    engine._pdos_professional_issuer_epochs = epochs
    engine._pdos_professional_synthetic = True
    return issuers


def disable_issuer(engine, key):
    registry = dict(getattr(engine, "_pdos_professional_issuers", {}))
    registry.pop(key, None)
    engine._pdos_professional_issuers = registry
    epochs = dict(getattr(engine, "_pdos_professional_issuer_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    engine._pdos_professional_issuer_epochs = epochs


def profile(engine):
    registry = getattr(engine, "_pdos_professional_issuers", {})
    return {
        "synthetic_enabled": getattr(engine, "_pdos_professional_synthetic", False) is True,
        "issuers": [
            {"key": value.key, "version": value.version, "nature": value.nature}
            for _, value in sorted(registry.items())
            if isinstance(value, IssuerContext)
        ],
    }


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("INVALID_AUTHORITY_TIME", "专业权威核对时点须含时区。", 422)
    return value.astimezone(UTC)


def _issuer(engine, issuer, tenant_id, product_id, project_id):
    registry = getattr(engine, "_pdos_professional_issuers", {})
    if (
        not isinstance(issuer, IssuerContext)
        or issuer._token is not _CAPABILITY
        or registry.get(issuer.key) is not issuer
    ):
        raise DomainError("TRUSTED_ISSUER_REQUIRED", "未配置当前可信签发入口。", 403)
    if (
        issuer.tenant_id != tenant_id
        or issuer.product_id != product_id
        or issuer.project_id not in (None, project_id)
    ):
        raise DomainError("FORBIDDEN_ISSUER_SCOPE", "签发依据不属于本范围。", 403)
    if issuer.nature == "synthetic" and not getattr(engine, "_pdos_professional_synthetic", False):
        raise DomainError("SYNTHETIC_AUTHORITY_NOT_ALLOWED", "真实模式不接受合成职责或资格。", 403)
    return issuer


def _project(s, ctx, product_id, project_id, *, write=False):
    from pdos_next.domain.projects.models import Project
    from pdos_next.service import require_access

    query = select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
    product = s.scalar(query.with_for_update() if write else query)
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "专业权威不在当前产品范围。", 403)
    require_access(s, ctx, product_id, write=True, lock=write)
    actor = s.get(Principal, ctx.requester_id)
    if (
        ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or actor is None
        or actor.kind != "human"
    ):
        raise DomainError("NAMED_PERSON_REQUIRED", "专业职责由当前具名人员承担。", 403)
    project = s.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.product_id == product_id,
            Project.tenant_id == ctx.tenant_id,
        )
    )
    if (
        project is None
        or project.status != "active"
        or (project.visibility == "private" and project.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "专业权威不在当前可读项目范围。", 403)
    return product, project


def _reads(sources):
    values = {}
    for source in sources:
        identity = str(source["artifact_id"])
        revision = source["expected_revision"]
        if identity in values and values[identity] != revision:
            raise DomainError("SOURCE_STALE", "同一来源不能绑定不同版本。")
        values[identity] = revision
    if len(values) > 20:
        raise DomainError("AUTHORITY_EVIDENCE_LIMIT", "专业权威来源超出完整读集上限。")
    return [
        {"artifact_id": key, "expected_revision": value} for key, value in sorted(values.items())
    ]


def _current_fact_rows(s, pointers):
    """One local read only; pending rows keep the original get behavior.

    Plain JSONB in-place edits need a material check before populate_existing.
    This collection is never retained outside this caller or used as authority.
    """
    identities = tuple(dict.fromkeys(pointer.fact_id for pointer in pointers))
    if not identities:
        return {}
    selected = set(identities)
    pending = any(isinstance(row, ProfessionalFact) for row in (*s.new, *s.dirty, *s.deleted))
    if not pending:
        for row in s.identity_map.values():
            if not isinstance(row, ProfessionalFact):
                continue
            state = inspect(row)
            values = state.dict
            if "id" not in values:
                pending = True
                break
            if values["id"] not in selected:
                continue
            if not {*_HASH_FIELDS, "fact_sha256"} <= values.keys():
                pending = True
                break
            try:
                unchanged = digest(_material(row)) == row.fact_sha256
            except (TypeError, ValueError, AttributeError):
                unchanged = False
            if not unchanged:
                pending = True
                break
    if pending:
        return None
    query = (
        select(ProfessionalFact)
        .where(ProfessionalFact.id.in_(identities))
        .execution_options(populate_existing=True, autoflush=False)
    )
    with s.no_autoflush:
        return {row.id: row for row in s.scalars(query)}


def _evidence(s, ctx, product_id, sources):
    from pdos_next.domain.supply_execution.service import _sources

    reads = _reads(sources)
    refs, private = _sources(s, ctx, product_id, reads, references=sources)
    epochs = []
    for read in reads:
        source = s.get(Artifact, UUID(read["artifact_id"]))
        if source.original_id is not None:
            safety = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.original_id == source.original_id,
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id == product_id,
                )
            )
            epochs.append(
                {
                    "original_id": str(source.original_id),
                    "security_epoch": safety.epoch if safety else None,
                    "source_state": safety.source_state if safety else None,
                    "disposition": safety.disposition if safety else None,
                }
            )
    return (
        reads,
        private,
        {"refs": [refs[key].model_dump(mode="json") for key in sorted(refs)], "security": epochs},
    )


_HASH_FIELDS = (
    "id",
    "tenant_id",
    "product_id",
    "project_id",
    "subject_id",
    "owner_id",
    "visibility",
    "kind",
    "role",
    "nature",
    "issuer_key",
    "issuer_version",
    "external_id",
    "operations",
    "purposes",
    "state",
    "valid_from",
    "valid_until",
    "series_id",
    "revision",
    "previous_id",
    "previous_revision",
    "sources",
    "required_source_read_set",
    "source_basis",
    "reason",
)


def _material(row):
    return {key: getattr(row, key) for key in _HASH_FIELDS}


def _fact_view(row, epoch):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "epoch": epoch,
        "kind": row.kind,
        "role": row.role,
        "nature": row.nature,
        "issuer_key": row.issuer_key,
        "issuer_version": row.issuer_version,
    }


def trusted_import(s, ctx, issuer, payload):
    """Host wraps this in its sole receipt/audit/outbox transaction, never public DTO auth."""
    value = payload if isinstance(payload, FactInput) else FactInput.model_validate(payload)
    _issuer(s.get_bind(), issuer, ctx.tenant_id, value.product_id, value.project_id)
    _, project = _project(s, ctx, value.product_id, value.project_id, write=True)
    subject = s.get(Principal, value.subject_id)
    if (
        subject is None
        or subject.tenant_id != ctx.tenant_id
        or not subject.active
        or subject.kind != "human"
    ):
        raise DomainError("NAMED_PERSON_REQUIRED", "事实须绑定当前真实人员身份。", 403)
    if value.approval.issued_at > now():
        raise DomainError("INVALID_AUTHORITY_TIME", "不能把未来签发当已发生依据。", 422)
    if any(
        operation not in OPERATION_ROLES or value.role not in OPERATION_ROLES[operation]
        for operation in value.operations
    ):
        raise DomainError("AUTHORITY_OPERATION_MISMATCH", "职责和资格须明确覆盖本专业操作。", 422)
    sources = [ref.model_dump(mode="json") for ref in value.sources]
    reads, private, evidence = _evidence(s, ctx, value.product_id, sources)
    private |= project.visibility == "private"
    query = select(ProfessionalCurrent).where(
        ProfessionalCurrent.tenant_id == ctx.tenant_id,
        ProfessionalCurrent.product_id == value.product_id,
        ProfessionalCurrent.project_id == value.project_id,
        ProfessionalCurrent.subject_id == value.subject_id,
        ProfessionalCurrent.kind == value.kind,
        ProfessionalCurrent.issuer_key == issuer.key,
        ProfessionalCurrent.external_id == value.external_id,
    )
    pointer = s.scalar(query.with_for_update())
    previous = s.get(ProfessionalFact, pointer.fact_id) if pointer else None
    intent = digest([issuer.key, issuer.version, issuer.nature, value.model_dump(mode="json")])
    if previous is not None:
        _check_pointer(
            pointer, previous, ctx.tenant_id, value.product_id, value.project_id, value.subject_id
        )
        replay = s.scalar(
            select(ProfessionalFact).where(
                ProfessionalFact.tenant_id == ctx.tenant_id,
                ProfessionalFact.product_id == value.product_id,
                ProfessionalFact.project_id == value.project_id,
                ProfessionalFact.subject_id == value.subject_id,
                ProfessionalFact.kind == value.kind,
                ProfessionalFact.issuer_key == issuer.key,
                ProfessionalFact.external_id == value.external_id,
                ProfessionalFact.series_id == previous.series_id,
                ProfessionalFact.owner_id == ctx.requester_id,
                ProfessionalFact.source_basis["import_digest"].astext == intent,
            )
        )
        if replay is not None:
            if replay.fact_sha256 != digest(_material(replay)):
                raise DomainError("AUTHORITY_INTEGRITY_UNKNOWN", "原导入事实摘要无法核对。")
            return {
                **_fact_view(replay, replay.revision),
                "required_source_read_set": replay.required_source_read_set,
                "source_basis": replay.source_basis,
            }
        if (
            previous.id != value.previous_id
            or previous.revision != value.expected_previous_revision
            or previous.owner_id != ctx.requester_id
        ):
            raise DomainError("AUTHORITY_VERSION_CONFLICT", "专业事实当前版本或导入责任已变化。")
        if (
            previous.role != value.role
            or previous.operations != value.operations
            or previous.purposes != value.purposes
            or previous.nature != issuer.nature
            or (previous.visibility == "product" and private)
        ):
            raise DomainError(
                "AUTHORITY_SERIES_MISMATCH", "续版不能更换专业、用途或扩大来源受众。", 403
            )
    elif value.previous_id is not None:
        raise DomainError("AUTHORITY_VERSION_CONFLICT", "当前范围没有可推进的专业事实。")
    identity = uuid4()
    row = ProfessionalFact(
        id=identity,
        tenant_id=ctx.tenant_id,
        product_id=value.product_id,
        project_id=value.project_id,
        subject_id=value.subject_id,
        owner_id=ctx.requester_id,
        visibility=previous.visibility if previous else "private" if private else "product",
        kind=value.kind,
        role=value.role,
        nature=issuer.nature,
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        external_id=value.external_id,
        operations=value.operations,
        purposes=value.purposes,
        state=value.state,
        valid_from=value.valid_from,
        valid_until=value.valid_until,
        series_id=previous.series_id if previous else identity,
        revision=previous.revision + 1 if previous else 1,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        sources=sources,
        required_source_read_set=reads,
        source_basis={
            "approval": value.approval.model_dump(mode="json"),
            "evidence": evidence,
            "import_digest": intent,
        },
        reason=value.reason,
    )
    row.fact_sha256 = digest(_material(row))
    s.add(row)
    s.flush()
    if pointer is None:
        pointer = ProfessionalCurrent(
            tenant_id=ctx.tenant_id,
            product_id=row.product_id,
            project_id=row.project_id,
            subject_id=row.subject_id,
            kind=row.kind,
            issuer_key=row.issuer_key,
            external_id=row.external_id,
            series_id=row.series_id,
            fact_id=row.id,
            fact_revision=1,
            epoch=1,
        )
        s.add(pointer)
    else:
        pointer.fact_id, pointer.fact_revision = row.id, row.revision
        pointer.epoch += 1
    s.flush()
    return {
        **_fact_view(row, pointer.epoch),
        "required_source_read_set": reads,
        "source_basis": row.source_basis,
    }


def _check_pointer(pointer, row, tenant_id, product_id, project_id, subject_id):
    if (
        row is None
        or (row.tenant_id, row.product_id, row.project_id, row.subject_id)
        != (tenant_id, product_id, project_id, subject_id)
        or (row.series_id, row.kind, row.issuer_key, row.external_id, row.revision)
        != (
            pointer.series_id,
            pointer.kind,
            pointer.issuer_key,
            pointer.external_id,
            pointer.fact_revision,
        )
        or pointer.epoch != pointer.fact_revision
        or row.fact_sha256 != digest(_material(row))
    ):
        raise DomainError("AUTHORITY_INTEGRITY_UNKNOWN", "专业事实固定版本和当前指针无法核对。")


def _reduce(facts, operation, purpose, at, *, synthetic_enabled):
    """Pure matrix/time reducer; caller has independently verified scope/source/issuer."""
    reasons, roles, qualifications = [], set(), []
    allowed = OPERATION_ROLES.get(operation)
    if allowed is None:
        return [], None, ["PROFESSIONAL_OPERATION_NOT_CONFIGURED"]
    for fact in facts:
        if fact.nature == "synthetic" and not synthetic_enabled:
            reasons.append("SYNTHETIC_AUTHORITY_NOT_ALLOWED")
            continue
        applicable = (
            fact.role in allowed and operation in fact.operations and purpose in fact.purposes
        )
        valid = applicable and fact.state == "active" and fact.valid_from <= at < fact.valid_until
        if fact.kind == "duty" and valid:
            roles.add(fact.role)
        if fact.kind == "qualification" and applicable:
            qualifications.append((fact.role, valid))
        if applicable and fact.state != "active":
            reasons.append("DUTY_WITHDRAWN" if fact.kind == "duty" else "QUALIFICATION_REVOKED")
        elif applicable and at < fact.valid_from:
            reasons.append("PROFESSIONAL_FACT_NOT_EFFECTIVE")
        elif applicable and at >= fact.valid_until:
            reasons.append("PROFESSIONAL_FACT_EXPIRED")
    if not roles:
        reasons.append("PROFESSIONAL_DUTY_REQUIRED")
    matching = [valid for role, valid in qualifications if role in roles]
    qualified = any(matching) if matching else False if qualifications else None
    if qualified is not True:
        reasons.append("PROFESSIONAL_QUALIFICATION_REQUIRED")
    return sorted(roles), qualified, sorted(set(reasons))


def assess(
    s, ctx, product_id, project_id, operation, purpose, at, write=False, *, retained_fact_refs=None
):
    at = _aware(at)
    retained_ids = None
    if retained_fact_refs is not None:
        if (
            write
            or at > now()
            or not isinstance(retained_fact_refs, list)
            or not retained_fact_refs
        ):
            raise DomainError("INVALID_RETAINED_AUTHORITY", "历史资格证明不得授予当前写入权。", 403)
        try:
            retained_ids = {UUID(ref["id"]) for ref in retained_fact_refs}
        except (TypeError, KeyError, ValueError):
            raise DomainError("INVALID_RETAINED_AUTHORITY", "历史资格引用集合无法核对。") from None
    if not isinstance(purpose, str) or not purpose.strip():
        raise DomainError("INVALID_AUTHORITY_PURPOSE", "专业权威须明确精确用途。", 422)
    purpose = purpose.strip()
    engine = s.get_bind()
    synthetic_enabled = getattr(engine, "_pdos_professional_synthetic", False) is True
    result = {
        "scope": {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(product_id),
            "project_id": str(project_id),
        },
        "subject_id": str(ctx.requester_id),
        "operation": operation,
        "purpose": purpose,
        "authorized": False,
        "roles": [],
        "qualified": None,
        "reason_codes": [],
        "fact_refs": [],
        "facts_revision": "",
        "valid_until": None,
        "synthetic": False,
        "required_source_read_set": [],
    }
    basis, facts, sources, deadlines = [], [], [], []
    blocked = False
    try:
        _project(s, ctx, product_id, project_id, write=write)
    except DomainError as error:
        blocked = True
        result["reason_codes"].append(error.code)

    identity = s.get(Principal, ctx.requester_id)
    grant = s.scalar(
        select(Grant).where(
            Grant.product_id == product_id,
            Grant.tenant_id == ctx.tenant_id,
            Grant.principal_id == ctx.requester_id,
        )
    )
    basis.append(
        {
            "actor_id": str(ctx.actor_id),
            "run_id": str(ctx.run_id) if ctx.run_id else None,
            "principal": [str(identity.id), identity.access_epoch, identity.active]
            if identity
            else None,
            "grant": [
                str(grant.id),
                grant.access_epoch,
                grant.can_write,
                grant.expires_at.isoformat(),
            ]
            if grant
            else None,
        }
    )
    if grant and grant.expires_at > at:
        deadlines.append(grant.expires_at)
    elif grant:
        blocked = True
        result["reason_codes"].append("PROFESSIONAL_ACCESS_EXPIRED")

    query = (
        select(ProfessionalCurrent)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == product_id,
            ProfessionalCurrent.project_id == project_id,
            ProfessionalCurrent.subject_id == ctx.requester_id,
        )
        .order_by(ProfessionalCurrent.id)
    )
    pointers = list(s.scalars((query.with_for_update() if write else query).limit(MAX_FACTS + 1)))
    if len(pointers) > MAX_FACTS:
        blocked = True
        result["reason_codes"].append("AUTHORITY_FACT_LIMIT")
    registry = getattr(engine, "_pdos_professional_issuers", {})
    if not registry:
        blocked = True
        result["reason_codes"].append("TRUSTED_ISSUER_UNAVAILABLE")

    # Build the entire bounded current epoch basis before any source/visibility failure.
    # Negative or inaccessible facts still invalidate a saved review; no facts are exposed.
    current_rows = []
    current_facts = _current_fact_rows(s, pointers)
    for pointer in pointers:
        row = (
            s.get(ProfessionalFact, pointer.fact_id)
            if current_facts is None
            else current_facts.get(pointer.fact_id)
        )
        if (
            retained_ids is not None
            and row is not None
            and row.id not in retained_ids
            and not (
                row.role in OPERATION_ROLES.get(operation, ())
                and operation in row.operations
                and purpose in row.purposes
            )
        ):
            # Only later independent, inapplicable duties may be ignored. The
            # snapshot's entire original set (including negative facts), relevant
            # additions and every original Current/issuer/source epoch still bind
            # the historical fingerprint. Missing original references cannot match.
            _check_pointer(pointer, row, ctx.tenant_id, product_id, project_id, ctx.requester_id)
            continue
        entry = {
            "pointer_id": str(pointer.id),
            "fact_id": str(pointer.fact_id),
            "revision": pointer.fact_revision,
            "epoch": pointer.epoch,
            "hash": row.fact_sha256 if row else None,
        }
        configured = registry.get(row.issuer_key) if row else None
        usable = bool(
            row
            and isinstance(configured, IssuerContext)
            and configured.version == row.issuer_version
            and configured.nature == row.nature
            and configured.tenant_id == ctx.tenant_id
            and configured.product_id == product_id
            and configured.project_id in (None, project_id)
        )
        entry["issuer_available"] = usable
        entry["issuer_epoch"] = configured.epoch if isinstance(configured, IssuerContext) else None
        basis.append(entry)
        current_rows.append((pointer, row, entry, usable))
    for pointer, row, entry, usable in current_rows:
        try:
            _check_pointer(pointer, row, ctx.tenant_id, product_id, project_id, ctx.requester_id)
            if not usable:
                blocked = True
                result["reason_codes"].append("TRUSTED_ISSUER_UNAVAILABLE")
            if row.nature == "synthetic" and not synthetic_enabled:
                blocked = True
                result["reason_codes"].append("SYNTHETIC_AUTHORITY_NOT_ALLOWED")
            result["synthetic"] |= row.nature == "synthetic"
            if row.visibility == "private" and row.owner_id != ctx.requester_id:
                raise DomainError("AUTHORITY_SOURCE_UNAVAILABLE", "专业依据不在当前可见范围。", 403)
            # Current access failure must not invoke source reads, while the complete
            # pointer basis above remains available for detecting authority changes.
            if (
                "FORBIDDEN_SCOPE" in result["reason_codes"]
                or "NAMED_PERSON_REQUIRED" in result["reason_codes"]
            ):
                continue
            reads, _, evidence = _evidence(s, ctx, product_id, row.sources)
            if reads != row.required_source_read_set:
                raise DomainError("AUTHORITY_INTEGRITY_UNKNOWN", "专业权威来源读集不完整。")
            entry["evidence"] = evidence
            sources.extend(row.sources)
            result["fact_refs"].append(_fact_view(row, pointer.epoch))
            if usable:
                facts.append(row)
        except DomainError as error:
            blocked = True
            entry["error"] = error.code
            result["reason_codes"].append(error.code)
    try:
        result["required_source_read_set"] = _reads(sources)
    except DomainError as error:
        blocked = True
        result["reason_codes"].append(error.code)
    roles, qualified, reasons = _reduce(
        facts, operation, purpose, at, synthetic_enabled=synthetic_enabled
    )
    result["roles"], result["qualified"] = roles, qualified
    result["reason_codes"].extend(reasons)
    # Only effective applicable facts delimit successful authority, while every
    # current fact (including expired/withdrawn/revoked) remains in its fingerprint.
    for fact in facts:
        if (
            fact.role in roles
            and operation in fact.operations
            and purpose in fact.purposes
            and fact.state == "active"
            and fact.valid_from <= at < fact.valid_until
        ):
            deadlines.append(fact.valid_until)
    if blocked:
        result["authorized"], result["roles"], result["qualified"] = False, [], None
        result["fact_refs"], result["required_source_read_set"] = [], []
    else:
        result["authorized"] = bool(result["roles"]) and result["qualified"] is True
    result["reason_codes"] = sorted(set(result["reason_codes"]))
    result["valid_until"] = min(deadlines).isoformat() if deadlines else None
    result["facts_revision"] = digest(
        {
            "scope": result["scope"],
            "subject": result["subject_id"],
            "operation": operation,
            "purpose": purpose,
            "synthetic_enabled": synthetic_enabled,
            "complete": len(pointers) <= MAX_FACTS,
            "facts": basis,
            "authorized": result["authorized"],
            "roles": result["roles"],
            "qualified": result["qualified"],
            "reasons": result["reason_codes"],
        }
    )
    return result


def recheck_snapshot(s, ctx, product_id, project_id, snapshot, at, write=False, *, retained=False):
    """Host may reconstruct the immutable historical reviewer context for reading only.

    Actual command authority for the current actor must be checked separately.
    """
    if retained and (
        not isinstance(snapshot, dict)
        or not isinstance(snapshot.get("fact_refs"), list)
        or not snapshot.get("fact_refs")
    ):
        return {
            "current": False,
            "assessment": None,
            "reason_codes": ["AUTHORITY_SNAPSHOT_INVALID"],
        }
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("subject_id") != str(ctx.requester_id)
        or snapshot.get("scope")
        != {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(product_id),
            "project_id": str(project_id),
        }
    ):
        return {"current": False, "assessment": None, "reason_codes": ["AUTHORITY_SCOPE_MISMATCH"]}
    if (
        not isinstance(snapshot.get("operation"), str)
        or not isinstance(snapshot.get("purpose"), str)
        or not snapshot["purpose"].strip()
    ):
        return {
            "current": False,
            "assessment": None,
            "reason_codes": ["AUTHORITY_SNAPSHOT_INVALID"],
        }
    current = assess(
        s,
        ctx,
        product_id,
        project_id,
        snapshot.get("operation"),
        snapshot.get("purpose"),
        at,
        write=write,
        retained_fact_refs=snapshot.get("fact_refs") if retained else None,
    )
    matches = (
        current["authorized"]
        and current["qualified"] is True
        and snapshot.get("authorized") is True
        and snapshot.get("qualified") is True
        and current["facts_revision"] == snapshot.get("facts_revision")
    )
    return {
        "current": bool(matches),
        "assessment": current,
        "reason_codes": [] if matches else ["PROFESSIONAL_AUTHORITY_CHANGED"],
    }
