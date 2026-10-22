"""Trusted imports and current professional assessment in the caller transaction.

No connection, commit, public self-grant, AI qualification or professional signoff.
The host verifies its environment before explicitly enabling the synthetic profile.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import inspect, select, true
from sqlalchemy.orm import Session, aliased

from pdos_next.database import category_for_product
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, Principal, Product, now
from pdos_next.original_lifecycle.rules import digest

from .models import ProfessionalCurrent, ProfessionalFact
from .schemas import FactInput

OPERATION_ROLES = {
    "knowledge.rule.publish": frozenset({"knowledge"}),
    "integration.handoff.authorize": frozenset({"engineering", "manufacturing", "quality"}),
    "release.exception.decide": frozenset({"engineering", "manufacturing", "quality"}),
    "release.exception.withdraw": frozenset({"engineering", "manufacturing", "quality"}),
    "release.policy.import": frozenset({"engineering", "manufacturing", "quality"}),
    "npi.work_instruction.record": frozenset({"manufacturing"}),
    "npi.control_plan.record": frozenset({"manufacturing"}),
    "npi.manufacturing_baseline.record": frozenset({"manufacturing"}),
    "npi.manufacturing_baseline.publish": frozenset({"manufacturing"}),
    "release.engineering.approve": frozenset({"engineering"}),
    "release.manufacturing.approve": frozenset({"manufacturing"}),
    "npi.pilot.create": frozenset({"manufacturing"}),
    "npi.pilot.result.record": frozenset({"manufacturing"}),
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
    "change.effectivity.record": frozenset({"engineering", "manufacturing", "quality"}),
    "change.verification.record": frozenset({"quality"}),
    "change.close": frozenset({"quality"}),
    "change.order.prepare": frozenset({"engineering", "manufacturing", "quality"}),
    "change.order.approve": frozenset({"engineering", "manufacturing", "quality"}),
    "change.implementation.record": frozenset({"engineering", "manufacturing", "quality"}),
    "change.policy.import": frozenset({"quality"}),
    "change.selection.decide": frozenset({"engineering", "manufacturing", "quality"}),
    "change.request.create": frozenset({"quality", "engineering", "manufacturing"}),
    "change.impact.compute": frozenset({"quality", "engineering", "manufacturing"}),
}
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
    if type(profiles) is not list or not profiles:
        raise ValueError("Trusted profiles require a nonempty explicit scope list")
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
    from pdos_next.request_proof import scoped_rows, snapshot_get
    from pdos_next.service import require_access

    query = select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
    snapshot = s.info.get("read_snapshot") and not write
    if snapshot:
        product = snapshot_get(s, Product, product_id, scope_id=product_id)
    else:
        products = scoped_rows(s, (Product, product_id), query, lock=write)
        product = products[0] if products else None
    if product is None or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "专业权威不在当前型号范围。", 403)
    require_access(s, ctx, product_id, write=write, lock=write)
    actor = s.get(Principal, ctx.requester_id)
    if write and (
        ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or actor is None
        or actor.kind != "human"
    ):
        raise DomainError("NAMED_PERSON_REQUIRED", "专业职责由当前具名人员承担。", 403)
    if snapshot:
        project = snapshot_get(s, Project, project_id, scope_id=product_id)
    else:
        projects = scoped_rows(
            s,
            (Project, project_id),
            select(Project).where(
                Project.id == project_id,
                Project.product_id == product_id,
                Project.tenant_id == ctx.tenant_id,
            ),
            lock=write,
        )
        project = projects[0] if projects else None
    if (
        project is None
        or project.status != "active"
        or project.tenant_id != ctx.tenant_id
        or project.product_id != product_id
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
    return [
        {"artifact_id": key, "expected_revision": value} for key, value in sorted(values.items())
    ]


def _current_fact_refresh_safe(s, selected=None):
    if any(isinstance(row, ProfessionalFact) for row in (*s.new, *s.dirty, *s.deleted)):
        return False
    for row in s.identity_map.values():
        if not isinstance(row, ProfessionalFact):
            continue
        values = inspect(row).dict
        if "id" not in values:
            return False
        if selected is not None and values["id"] not in selected:
            continue
        if not {*_HASH_FIELDS, "fact_sha256"} <= values.keys():
            return False
        try:
            unchanged = digest(_material(row)) == row.fact_sha256
        except (TypeError, ValueError, AttributeError):
            unchanged = False
        if not unchanged:
            return False
    return True


def _current_fact_writer_owner(s, ctx, product_id):
    """Pure provenance of the existing Product gate, with no connection enlistment."""
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import SessionTransaction

    from pdos_next.database import require_context
    from pdos_next.request_proof import request_proof

    if (
        not isinstance(s, Session)
        or s.is_active is not True
        or not s.in_transaction()
        or s.info.get("read_snapshot")
        or s.new
        or s.dirty
        or s.deleted
    ):
        return None
    require_context(s, ctx)
    scope = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    if s.info.get("scope") != scope:
        return None
    proof = request_proof(s)
    if product_id not in proof.scope_locks or s.get_transaction() is not proof.transaction:
        return None
    chain, seen = [], set()
    node = s._transaction
    while node is not None:
        if (
            not isinstance(node, SessionTransaction)
            or node.session is not s
            or node.is_active is not True
            or id(node) in seen
            or len(chain) >= 128
        ):
            return None
        seen.add(id(node))
        chain.append(node)
        node = node.parent
    if not chain or chain[-1] is not proof.transaction:
        return None
    if s.get_nested_transaction() is not next((node for node in chain if node.nested), None):
        return None
    try:
        bind = s.get_bind()
        if (
            not isinstance(bind, (Engine, Connection))
            or bind.dialect.name != "postgresql"
            or any(
                s.get_bind(mapper=model) is not bind
                for model in (Product, ProfessionalCurrent, ProfessionalFact)
            )
        ):
            return None
    except Exception:
        # Unknown/routed bindings keep the original ordered domain reader.
        return None
    # Only inspect the Connection already enlisted by the Product FOR UPDATE.
    # s.connection() here could enlist a new bind while keeping the old marker.
    enlisted = getattr(proof.transaction, "_connections", None)
    if not isinstance(enlisted, dict) or bind not in enlisted:
        return None
    entry = enlisted[bind]
    if not isinstance(entry, tuple) or len(entry) != 4:
        return None
    connection, transaction = entry[:2]
    if (
        not isinstance(connection, Connection)
        or connection.closed
        or connection.invalidated
        or getattr(transaction, "is_active", False) is not True
        or not connection.in_transaction()
        or connection.get_transaction() is not transaction
        or set(enlisted) != {connection, connection.engine}
        or any(
            not isinstance(value, tuple)
            or len(value) != 4
            or value[0] is not connection
            or value[1] is not transaction
            for value in enlisted.values()
        )
        or (isinstance(bind, Engine) and connection.engine is not bind)
        or (isinstance(bind, Connection) and connection is not bind)
    ):
        return None
    return (
        tuple(sorted(vars(ctx).items())),
        scope,
        tuple(chain),
        proof.transaction,
        proof.mutation_epoch,
        bind,
        connection,
        transaction,
    )


def _joined_current_fact_rows(s, ctx, product_id, project_id, subject_id, query, *, write):
    """Collapse an uncached writer's adjacent raw reads; never cache an assessment.

    The canonical application schema grants SELECT on both referenced tables.
    LATERAL/OFFSET prevents runtime Fact evaluation without an outer Current;
    SQL privilege checks still precede rows and are not conditional on Current.
    """
    if not write:
        return None
    owner = _current_fact_writer_owner(s, ctx, product_id)
    if owner is None:
        return None
    from pdos_next.request_proof import request_proof

    proof = request_proof(s)
    key = ("query", (ProfessionalCurrent, product_id, project_id, subject_id))
    saved = proof.read_rows.get(key)
    if saved is not None and saved[0]:
        # The old path needs at most its missing Fact read, not another Current.
        return None
    if saved is not None and not saved[1]:
        return None
    if any(
        isinstance(key, tuple) and len(key) == 2 and key[0] is ProfessionalFact
        for key in proof.read_rows
    ):
        # Fresh pointers may differ from the old nonlocking Current cache. Keep
        # all existing Fact cache hits on the original zero/one-query path.
        return None
    if not _current_fact_refresh_safe(s):
        # Actual selected IDs are only known after this read. Check every loaded
        # Fact so populate_existing cannot erase an untracked JSON mutation.
        return None
    fact_query = (
        select(ProfessionalFact)
        .where(ProfessionalFact.id == ProfessionalCurrent.fact_id)
        .correlate(ProfessionalCurrent)
        .offset(0)
        .lateral()
    )
    fact = aliased(ProfessionalFact, fact_query)
    packed = (
        query.with_only_columns(ProfessionalCurrent, fact)
        .outerjoin(fact, true())
        .with_for_update(of=ProfessionalCurrent)
        .execution_options(populate_existing=True, autoflush=False)
    )
    # A DBAPI failure already aborts the original reader; there is no retry or
    # SAVEPOINT overhead that would turn its two reads into three roundtrips.
    with s.no_autoflush:
        rows = list(s.execute(packed))
    if (
        _current_fact_writer_owner(s, ctx, product_id) != owner
        or request_proof(s) is not proof
    ):
        raise DomainError("SOURCE_STALE", "专业原始行读取期间事务或范围已变化。")
    pointers = [pointer for pointer, _ in rows]
    facts = {pointer.fact_id: row for pointer, row in rows}
    if pointers:
        proof.read_rows[key] = (True, pointers)
    # These are the original exact raw-row keys, including a hidden Fact's None.
    proof.read_rows.update({(ProfessionalFact, key): row for key, row in facts.items()})
    return pointers, facts


def _current_fact_rows(s, pointers):
    """One local read only; pending rows keep the original get behavior.

    Plain JSONB in-place edits need a material check before populate_existing.
    This collection is never retained outside this caller or used as authority.
    """
    identities = tuple(dict.fromkeys(pointer.fact_id for pointer in pointers))
    if not identities:
        return {}
    if not _current_fact_refresh_safe(s, set(identities)):
        return None
    if isinstance(s, Session):
        from pdos_next.request_proof import batch_read

        with s.no_autoflush:
            return batch_read(s, ProfessionalFact, identities)
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
    refs, private = _sources(
        s,
        ctx,
        product_id,
        reads,
        references=[ref for ref in sources if "line" in ref and "quote" in ref],
    )
    epochs = []
    for read in reads:
        source = s.get(Artifact, UUID(read["artifact_id"]))
        if source.original_id is not None:
            from pdos_next.original_security import security_row
            from pdos_next.originals import require_original

            original = require_original(s, ctx, product_id, source.original_id)
            safety = security_row(s, original, lock=False)
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
        "series_id": str(row.series_id),
        "fact_sha256": row.fact_sha256,
        "state": row.state,
        "operations": list(row.operations),
        "purposes": list(row.purposes),
        "valid_from": row.valid_from.isoformat(),
        "valid_until": row.valid_until.isoformat(),
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
    private |= project.visibility != "category"
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
            or (previous.visibility == "category" and private)
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
        visibility=previous.visibility if previous else "private" if private else "category",
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


def _subject_access(s, ctx, product_id, subject_id):
    if isinstance(s, Session):
        from pdos_next.request_proof import request_proof

        proof = request_proof(s)
        for entry in proof.authority.values():
            for principal, grant in entry["rows"]:
                if principal.id == subject_id:
                    return principal, grant
        key = ("professional-subject", product_id, subject_id)
        if key not in proof.read_rows:
            proof.read_rows[key] = s.execute(
                select(Principal, Grant)
                .join(
                    Grant,
                    (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
                )
                .where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.id == subject_id,
                    Grant.category_id == category_for_product(product_id),
                )
            ).first()
        return proof.read_rows[key] or (None, None)
    return s.get(Principal, subject_id), s.scalar(
        select(Grant).where(
            Grant.category_id == category_for_product(product_id),
            Grant.tenant_id == ctx.tenant_id,
            Grant.principal_id == subject_id,
        )
    )


def _summary_row(pointer):
    """The database fills this projection from the exact immutable imported fact."""
    values = dict(pointer.summary)
    for key in (
        "id",
        "tenant_id",
        "category_id",
        "product_id",
        "project_id",
        "subject_id",
        "owner_id",
        "series_id",
    ):
        values[key] = UUID(values[key])
    for key in ("valid_from", "valid_until"):
        values[key] = datetime.fromisoformat(values[key])
    values["sources"] = values["required_source_read_set"]
    return SimpleNamespace(**values)


def _check_current(pointer, row, ctx, product_id, project_id, subject_id, summary):
    if not summary:
        return _check_pointer(pointer, row, ctx.tenant_id, product_id, project_id, subject_id)
    if (
        (row.tenant_id, row.product_id, row.project_id, row.subject_id, row.id)
        != (ctx.tenant_id, product_id, project_id, subject_id, pointer.fact_id)
        or (row.series_id, row.kind, row.issuer_key, row.external_id, row.revision)
        != (
            pointer.series_id,
            pointer.kind,
            pointer.issuer_key,
            pointer.external_id,
            pointer.fact_revision,
        )
        or pointer.epoch != pointer.fact_revision
    ):
        raise DomainError("AUTHORITY_INTEGRITY_UNKNOWN", "专业 Current 摘要范围无法核对。")


def assess(
    s,
    ctx,
    product_id,
    project_id,
    operation,
    purpose,
    at,
    write=False,
    *,
    retained_fact_refs=None,
    subject_id=None,
):
    at = _aware(at)
    subject_id = subject_id or ctx.requester_id
    if write and subject_id != ctx.requester_id:
        raise DomainError("NAMED_PERSON_REQUIRED", "具名写入不能借用受提名人员的身份。", 403)
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
        "subject_id": str(subject_id),
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
    basis, facts, sources = [], [], []
    blocked = False
    try:
        _project(s, ctx, product_id, project_id, write=write)
    except DomainError as error:
        blocked = True
        result["reason_codes"].append(error.reason)

    identity, grant = _subject_access(s, ctx, product_id, subject_id)
    if identity is None or grant is None or not identity.active:
        blocked = True
        result["reason_codes"].append("PROFESSIONAL_ACCESS_EXPIRED")
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
                grant.expires_at.isoformat() if grant.expires_at else None,
            ]
            if grant
            else None,
        }
    )
    if grant and grant.expires_at is not None and grant.expires_at <= at:
        blocked = True
        result["reason_codes"].append("PROFESSIONAL_ACCESS_EXPIRED")

    query = (
        select(ProfessionalCurrent)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == product_id,
            ProfessionalCurrent.project_id == project_id,
            ProfessionalCurrent.subject_id == subject_id,
        )
        .order_by(ProfessionalCurrent.id)
    )
    joined = _joined_current_fact_rows(
        s, ctx, product_id, project_id, subject_id, query, write=write
    )
    if joined is not None:
        pointers, joined_facts = joined
    elif isinstance(s, Session):
        from pdos_next.request_proof import scoped_rows

        pointers = scoped_rows(
            s, (ProfessionalCurrent, product_id, project_id, subject_id), query, lock=write
        )
    else:
        pointers = list(s.scalars(query.with_for_update() if write else query))
    registry = getattr(engine, "_pdos_professional_issuers", {})
    if not registry:
        blocked = True
        result["reason_codes"].append("TRUSTED_ISSUER_UNAVAILABLE")

    # Build the entire bounded current epoch basis before any source/visibility failure.
    # Negative or inaccessible facts still invalidate a saved review; no facts are exposed.
    current_rows = []
    summary_read = (
        isinstance(s, Session)
        and not write
        and not any(isinstance(row, ProfessionalFact) for row in (*s.new, *s.dirty, *s.deleted))
    )
    current_facts = (
        {pointer.fact_id: _summary_row(pointer) for pointer in pointers}
        if summary_read
        else joined_facts
        if joined is not None
        else _current_fact_rows(s, pointers)
    )
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
            _check_current(pointer, row, ctx, product_id, project_id, subject_id, summary_read)
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
        current_rows.append((pointer, row, entry, usable, configured))
    for pointer, row, entry, usable, configured in current_rows:
        try:
            _check_current(pointer, row, ctx, product_id, project_id, subject_id, summary_read)
            if not usable:
                blocked = True
                result["reason_codes"].append("TRUSTED_ISSUER_UNAVAILABLE")
            if row.nature == "synthetic" and not synthetic_enabled:
                blocked = True
                result["reason_codes"].append("SYNTHETIC_AUTHORITY_NOT_ALLOWED")
            result["synthetic"] |= row.nature == "synthetic"
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
            result["fact_refs"].append(
                {
                    **_fact_view(row, pointer.epoch),
                    "issuer_epoch": configured.epoch if usable else None,
                }
            )
            if usable:
                facts.append(row)
        except DomainError as error:
            blocked = True
            entry["error"] = error.reason
            result["reason_codes"].append(error.reason)
    try:
        result["required_source_read_set"] = _reads(sources)
    except DomainError as error:
        blocked = True
        result["reason_codes"].append(error.reason)
    roles, qualified, reasons = _reduce(
        facts, operation, purpose, at, synthetic_enabled=synthetic_enabled
    )
    result["roles"], result["qualified"] = roles, qualified
    result["reason_codes"].extend(reasons)
    if blocked:
        result["authorized"], result["roles"], result["qualified"] = False, [], None
        result["fact_refs"], result["required_source_read_set"] = [], []
    else:
        result["authorized"] = bool(result["roles"]) and result["qualified"] is True
    result["reason_codes"] = sorted(set(result["reason_codes"]))
    result["facts_revision"] = digest(
        {
            "scope": result["scope"],
            "subject": result["subject_id"],
            "operation": operation,
            "purpose": purpose,
            "synthetic_enabled": synthetic_enabled,
            "complete": True,
            "facts": basis,
            "authorized": result["authorized"],
            "roles": result["roles"],
            "qualified": result["qualified"],
            "reasons": result["reason_codes"],
        }
    )
    return result


def authority_time_current(value, at):
    try:
        facts = []
        for reference in value.get("fact_refs", ()):
            row = dict(reference)
            row["valid_from"] = datetime.fromisoformat(row["valid_from"])
            row["valid_until"] = datetime.fromisoformat(row["valid_until"])
            if row["valid_from"].tzinfo is None or row["valid_until"].tzinfo is None:
                return False
            facts.append(SimpleNamespace(**row))
        roles, qualified, _ = _reduce(
            facts,
            value["operation"],
            value["purpose"],
            at,
            synthetic_enabled=value.get("synthetic") is True,
        )
        return qualified is True and bool(set(roles) & set(value.get("roles", ())))
    except (KeyError, TypeError, ValueError):
        return False


def _historical_facts(s, ctx, product_id, project_id, subject_id, identities):
    if not isinstance(s, Session):
        return {identity: s.get(ProfessionalFact, identity) for identity in identities}
    from pdos_next.request_proof import request_proof

    proof = request_proof(s)
    key = ("professional-signature", product_id, project_id, subject_id, frozenset(identities))
    if key not in proof.read_rows:
        fields = (
            "id",
            "tenant_id",
            "product_id",
            "project_id",
            "subject_id",
            "series_id",
            "revision",
            "kind",
            "role",
            "nature",
            "issuer_key",
            "issuer_version",
            "operations",
            "purposes",
            "state",
            "valid_from",
            "valid_until",
            "fact_sha256",
        )
        rows = s.execute(
            select(*(getattr(ProfessionalFact, key) for key in fields)).where(
                ProfessionalFact.id.in_(identities),
                ProfessionalFact.tenant_id == ctx.tenant_id,
                ProfessionalFact.product_id == product_id,
                ProfessionalFact.project_id == project_id,
                ProfessionalFact.subject_id == subject_id,
            )
        ).mappings()
        proof.read_rows[key] = {row["id"]: SimpleNamespace(**row) for row in rows}
    return proof.read_rows[key]


def _signature_currents(s, ctx, product_id, project_id, subject_id, *, write=False):
    query = (
        select(ProfessionalCurrent)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == product_id,
            ProfessionalCurrent.project_id == project_id,
            ProfessionalCurrent.subject_id == subject_id,
        )
        .order_by(ProfessionalCurrent.id)
    )
    if isinstance(s, Session):
        from pdos_next.request_proof import scoped_rows

        return scoped_rows(
            s, (ProfessionalCurrent, product_id, project_id, subject_id), query, lock=write
        )
    return list(s.scalars(query))


def _rr_signature_facts(s, ctx, product_id, project_id, subject_id, identities, pointers):
    """Reuse only exact immutable facts proved by Current's complete RLS policy."""
    rows = {}
    for pointer in pointers:
        if pointer.fact_id not in identities:
            continue
        row = _summary_row(pointer)
        _check_current(pointer, row, ctx, product_id, project_id, subject_id, True)
        rows[row.id] = row
    missing = identities - rows.keys()
    if missing:
        # Replaced or inaccessible Current rows must still read the real frozen
        # history under RLS; a Current summary never manufactures an older fact.
        rows.update(_historical_facts(s, ctx, product_id, project_id, subject_id, missing))
    return rows


def recheck_snapshot(s, ctx, product_id, project_id, snapshot, at, write=False, *, retained=False):
    """Read a frozen signature under the reader's scope, then compare Current watermarks.

    A later personnel change marks review and blocks new dependent actions. It
    does not erase the recorded signature or impersonate its original signer.
    The current command independently assesses its own named actor at signing.
    """
    invalid = {
        "current": False,
        "historical_valid": False,
        "needs_review": True,
        "assessment": None,
        "reason_codes": ["AUTHORITY_SNAPSHOT_INVALID"],
    }
    if not isinstance(snapshot, dict) or snapshot.get("scope") != {
        "tenant_id": str(ctx.tenant_id),
        "product_id": str(product_id),
        "project_id": str(project_id),
    }:
        return {**invalid, "reason_codes": ["AUTHORITY_SCOPE_MISMATCH"]}
    try:
        subject = UUID(snapshot["subject_id"])
        refs = snapshot["fact_refs"]
        operation, purpose = snapshot["operation"], snapshot["purpose"]
        if (
            not isinstance(refs, list)
            or not refs
            or not isinstance(operation, str)
            or not isinstance(purpose, str)
            or not purpose.strip()
            or snapshot.get("authorized") is not True
            or snapshot.get("qualified") is not True
        ):
            return invalid
        identities = {UUID(ref["id"]) for ref in refs}
        if len(identities) != len(refs):
            return invalid
        _project(s, ctx, product_id, project_id, write=False)
        pointers = None
        if (
            isinstance(s, Session)
            and s.info.get("read_snapshot") is True
            and not write
            and not (s.new or s.dirty or s.deleted)
        ):
            pointers = _signature_currents(s, ctx, product_id, project_id, subject)
            rows = _rr_signature_facts(
                s, ctx, product_id, project_id, subject, identities, pointers
            )
        else:
            rows = _historical_facts(s, ctx, product_id, project_id, subject, identities)
        if set(rows) != identities:
            return invalid
        for ref in refs:
            row = rows[UUID(ref["id"])]
            if (
                row is None
                or (row.tenant_id, row.product_id, row.project_id, row.subject_id)
                != (ctx.tenant_id, product_id, project_id, subject)
                or row.revision != ref["revision"]
                or ref["epoch"] != row.revision
                or row.fact_sha256 != ref["fact_sha256"]
                or str(row.series_id) != ref["series_id"]
            ):
                return invalid
        roles = {
            row.role
            for row in rows.values()
            if row.kind == "duty"
            and row.state == "active"
            and operation in row.operations
            and purpose in row.purposes
        }
        qualified = {
            row.role
            for row in rows.values()
            if row.kind == "qualification"
            and row.state == "active"
            and operation in row.operations
            and purpose in row.purposes
        }
        if not set(snapshot.get("roles", ())) or not set(snapshot["roles"]) <= roles & qualified:
            return invalid
        if pointers is None:
            pointers = _signature_currents(
                s, ctx, product_id, project_id, subject, write=write
            )
        current = {
            pointer.series_id: (pointer.fact_id, pointer.fact_revision, pointer.epoch)
            for pointer in pointers
        }
        changed = any(
            current.get(row.series_id) != (row.id, row.revision, row.revision)
            for row in rows.values()
        )
        registry = getattr(s.get_bind(), "_pdos_professional_issuers", {})
        changed |= any(
            not isinstance(registry.get(ref["issuer_key"]), IssuerContext)
            or registry[ref["issuer_key"]].version != ref["issuer_version"]
            or registry[ref["issuer_key"]].epoch != ref["issuer_epoch"]
            for ref in refs
        )
        # This is a factual eligibility boundary for a new action, not a snapshot TTL.
        changed |= not authority_time_current(snapshot, _aware(at))
        return {
            "current": bool(retained or not changed),
            "historical_valid": True,
            "needs_review": bool(changed),
            "assessment": snapshot,
            "reason_codes": ["PROFESSIONAL_AUTHORITY_CHANGED"] if changed else [],
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return invalid
    except DomainError as error:
        return {**invalid, "reason_codes": [error.reason]}
