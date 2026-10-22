"""Delegated fact append, with a real startup owner and live common consumption.

No Receipt, proof, FactAtom, full FactRef SHA, flush or commit is created here.
Only the actual owner may supply source/issuer/participant/qualification facts.
The opaque phase retains this Session and active UOW, never a cross-phase cache.
"""

from pdos_next.database import category_for_product
from pdos_next.clock import proof_deadline_current


# Common initialization must precede model declarations used by the actual host.
# ruff: noqa: I001
from pdos_next.service import Context, digest

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from pydantic import AwareDatetime, Field, JsonValue, create_model
from sqlalchemy import inspect, select

from pdos_next.contracts import Command
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product

from . import anchor
from . import fact_atom_storage as guards
from . import fact_commands as commands
from . import fact_storage_models as models
from .fact_consumption import ConsumptionHost, LiveConsumption
from .fact_storage_codec import (
    NamedReviewBody,
    ObservationBody,
    RuleBody,
    SCHEMA_VERSION,
    body_payload_sha256,
    decode_fact_body,
)
from .facts import FactRef, _action_bindings, _all_source_refs
from .paired import Closed, Revision

Kind = Literal["rule", "observation", "review"]


def _draft_model(cls, name):
    fields = {}
    for key, field in cls.model_fields.items():
        if key not in {"ref", "created_at"}:
            copied = deepcopy(field)
            fields[key] = (copied.annotation, copied)
    return create_model(name, __base__=Closed, **fields)


RuleDraft = _draft_model(RuleBody, "RuleDraft")
ObservationDraft = _draft_model(ObservationBody, "ObservationDraft")
NamedReviewDraft = _draft_model(NamedReviewBody, "NamedReviewDraft")
Draft = Annotated[RuleDraft | ObservationDraft | NamedReviewDraft, Field(discriminator="kind")]


class CurrentSeries(Closed):
    """Exact owner-read pointer, not a client chosen logical series or latest guess."""

    id: UUID
    series_id: UUID
    fact: FactRef
    epoch: Revision


class FactWriteMaterial(Closed):
    body_material: Draft
    anchor: anchor.StableCapaAnchor
    current_issue_version_id: UUID
    current_issue_revision: Revision
    series: CurrentSeries | None = None
    authority_snapshot: dict[str, JsonValue]
    policy_snapshot: dict[str, JsonValue]
    inspection: dict[str, JsonValue]
    valid_until: AwareDatetime | None = None
    time_constraints: tuple[AwareDatetime, ...] = ()


class FactMaterialOwner(Protocol):
    """Trusted startup owner; all methods use the actual Session/ctx and no commit.

    read/refresh must independently check exact raw source bytes/ACL/security,
    full refs and Current, policy/issuer epochs, current operation qualification
    and actual event fields. Review additionally needs all actual participant
    owners and caller independence. Unknown named conclusions are material, not
    a waiver. Genuine fact/temporary authorization intervals are checked
    individually; the material capture itself does not expire.
    refresh keeps the originally persisted full anchor; it must not reseal it.
    """

    def read(self, s, ctx, product_id, kind, payload, *, new_write) -> FactWriteMaterial: ...
    def refresh(
        self, s, ctx, product_id, kind, payload, previous, *, new_write
    ) -> FactWriteMaterial: ...
    def runtime_stamp(self, s) -> str: ...


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class PreparedFact:
    kind: Kind
    payload_semantic: dict
    material: FactWriteMaterial
    new_write: bool
    session: object
    uow: tuple
    caller_sha256: str
    runtime_stamp: str
    checked_at: datetime

    @property
    def required_source_read_set(self):
        return self.material.body_material.required_source_read_set

    @property
    def owner_id(self):
        return self.material.body_material.owner_id

    @property
    def visibility(self):
        return self.material.body_material.visibility

    @property
    def valid_until(self):
        return self.material.valid_until


def _require(condition, code="FACT_WRITE_OWNER_REQUIRED", status=503):
    if not condition:
        raise DomainError(code, "缺本次真实事实owner、来源或共同写入材料。", status)


def _clock():
    return datetime.now(UTC)


def _time_current(material, at):
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.quality_execution import policy

    return (
        (material.valid_until is None or at < material.valid_until)
        and all(at < bound for bound in material.time_constraints)
        and professional.authority_time_current(material.authority_snapshot, at)
        and policy.policy_time_current(material.policy_snapshot, at)
    )


def _instant(value):
    _require(
        isinstance(value, datetime) and value.utcoffset() is not None, "FACT_ACTUAL_CLOCK_REQUIRED"
    )
    return value.astimezone(UTC)


def _json(value):
    # Do not feed a tuple of Pydantic DTOs to JSONB or compare subclasses by
    # Python model identity. Preserve every field and the original sequence.
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(child) for child in value]
    return deepcopy(value)


def _one(s, model, *where, lock=False):
    statement = (
        select(model)
        .where(*where)
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    if lock:
        statement = statement.with_for_update()
    rows = list(s.scalars(statement))
    _require(len(rows) == 1, "FACT_EXACT_CURRENT_REQUIRED")
    return rows[0]


def _row_values(row, names):
    return {key: deepcopy(getattr(row, key)) for key in names}


def _caller(s, ctx, pid, project_id):
    _require(
        isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
        "FORBIDDEN_SCOPE",
        403,
    )
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    project = _one(
        s,
        Project,
        Project.tenant_id == ctx.tenant_id,
        Project.product_id == pid,
        Project.id == project_id,
    )
    person = _one(s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id)
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(pid),
        Grant.principal_id == ctx.actor_id,
    )
    _require(
        person.kind == "human"
        and person.active is True
        and grant.can_write is True
        and project.status == "active"
        and project.visibility in {"private", "category", "audience"}
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    _require((grant.expires_at is None or grant.expires_at > _clock()), "FORBIDDEN_SCOPE", 403)
    return (
        _row_values(product, ("id", "tenant_id", "revision")),
        _row_values(project, ("id", "tenant_id", "product_id", "owner_id", "visibility", "status")),
        _row_values(person, ("id", "tenant_id", "kind", "active", "access_epoch")),
        _row_values(
            grant,
            (
                "id",
                "tenant_id",
                "category_id",
                "principal_id",
                "can_write",
                "expires_at",
                "access_epoch",
            ),
        ),
    )


def _current(s, ctx, pid, material):
    body = material.body_material
    row = _one(
        s,
        QualityIssueCurrent,
        QualityIssueCurrent.tenant_id == ctx.tenant_id,
        QualityIssueCurrent.product_id == pid,
        QualityIssueCurrent.project_id == body.scope.project_id,
        QualityIssueCurrent.issue_id == body.issue_id,
    )
    _require(
        (row.issue_version_id, row.issue_revision)
        == (material.current_issue_version_id, material.current_issue_revision),
        "VERSION_CONFLICT",
        409,
    )
    return _row_values(
        row,
        (
            "id",
            "tenant_id",
            "product_id",
            "project_id",
            "issue_id",
            "issue_version_id",
            "issue_revision",
            "epoch",
        ),
    )


def _series(s, ctx, pid, kind, material, *, new_write, external_id=None):
    if kind == "review":
        _require(
            material.series is None and material.body_material.previous is None,
            "FACT_REVIEW_SERIES_FORBIDDEN",
        )
        return None
    previous, series = material.body_material.previous, material.series
    if previous is None:
        _require(series is None, "FACT_FIRST_SERIES_MISMATCH")
        if new_write:
            _require(
                not _initial_series_exists(s, ctx, pid, kind, material, external_id),
                "FACT_SERIES_CONFLICT",
                409,
            )
        return None
    _require(series is not None, "FACT_CURRENT_SERIES_REQUIRED")
    if new_write:
        _require(series.fact == previous, "FACT_SERIES_CONFLICT", 409)
    cls = models.RuleCurrent if kind == "rule" else models.ObservationCurrent
    row = _one(
        s,
        cls,
        cls.tenant_id == ctx.tenant_id,
        cls.product_id == pid,
        cls.id == series.id,
        lock=True,
    )
    body = material.body_material
    expected = {
        **{
            key: getattr(body, key)
            for key in models.BINDING
            if key
            not in {
                "tenant_id",
                "product_id",
                "project_id",
                "origin_issue_version_id",
                "origin_issue_revision",
            }
        },
        "tenant_id": body.scope.tenant_id,
        "product_id": body.scope.product_id,
        "project_id": body.scope.project_id,
        "origin_issue_version_id": material.anchor.origin.ref.id,
        "origin_issue_revision": material.anchor.origin.ref.revision,
        "series_id": series.series_id,
        "fact_id": series.fact.id,
        "fact_revision": series.fact.revision,
        "epoch": series.epoch,
    }
    _require(_row_values(row, expected) == expected, "FACT_SERIES_CONFLICT", 409)
    if kind == "rule":
        _require(
            row.issuer_key == body.issuer.key and row.external_id == external_id,
            "FACT_SERIES_CONFLICT",
            409,
        )
    else:
        prior = _one(
            s,
            models.ObservationFact,
            models.ObservationFact.tenant_id == ctx.tenant_id,
            models.ObservationFact.product_id == pid,
            models.ObservationFact.id == series.fact.id,
            models.ObservationFact.revision == series.fact.revision,
        )
        _require(
            (
                prior.rule_fact_id,
                prior.rule_revision,
                prior.rule_sha256,
                prior.executor_id,
                prior.issuer_key,
            )
            == (
                body.rule.id,
                body.rule.revision,
                body.rule.sha256,
                body.executor_id,
                body.issuer.key,
            ),
            "FACT_SERIES_CONFLICT",
            409,
        )
    return row


def _initial_series_exists(s, ctx, pid, kind, material, external_id):
    """A fresh row UUID cannot evade the real existing logical series Current."""
    body = material.body_material
    cls = models.RuleCurrent if kind == "rule" else models.ObservationCurrent
    statement = select(cls).where(
        cls.tenant_id == ctx.tenant_id,
        cls.product_id == pid,
        cls.project_id == body.scope.project_id,
        cls.issue_id == body.issue_id,
        cls.capa_id == body.capa_id,
        cls.anchor_sha256 == body.anchor_sha256,
    )
    if kind == "rule":
        _require(isinstance(external_id, str) and bool(external_id), "FACT_RULE_SERIES_ID_REQUIRED")
        statement = statement.where(
            cls.issuer_key == body.issuer.key, cls.external_id == external_id
        )
    else:
        fact = models.ObservationFact
        statement = statement.join(
            fact,
            (fact.id == cls.fact_id)
            & (fact.tenant_id == cls.tenant_id)
            & (fact.product_id == cls.product_id),
        ).where(
            fact.rule_fact_id == body.rule.id,
            fact.rule_revision == body.rule.revision,
            fact.rule_sha256 == body.rule.sha256,
            fact.executor_id == body.executor_id,
        )
    statement = (
        statement.limit(2)
        .execution_options(populate_existing=True, autoflush=False)
        .with_for_update(of=cls)
    )
    return bool(list(s.scalars(statement)))


def _material(value):
    return FactWriteMaterial.model_validate(commands._attributes(value))


def _check_material(ctx, pid, kind, payload, material, *, new_write):
    body, origin = material.body_material, material.anchor.origin
    _require(
        (body.kind, body.scope.tenant_id, body.scope.product_id, body.issue_id, body.capa_id)
        == (kind, ctx.tenant_id, pid, payload.issue_id, payload.capa_id)
        and (
            body.scope,
            body.issue_id,
            body.capa_id,
            body.purpose,
            body.nature,
            body.owner_id,
            body.visibility,
            body.anchor_sha256,
            body.requirement_sha256,
        )
        == (
            origin.scope,
            origin.issue_id,
            origin.issue.capa.id,
            origin.purpose,
            origin.nature,
            origin.owner_id,
            origin.visibility,
            material.anchor.anchor_sha256,
            digest(_json(origin.issue.capa.requirement)),
        ),
        "FACT_SCOPE_MISMATCH",
        409,
    )
    _require(
        payload.visibility == body.visibility
        and (body.visibility != "private" or body.owner_id == ctx.requester_id),
        "FACT_AUDIENCE_MISMATCH",
        403,
    )
    if new_write:
        _require(
            payload.expected_issue_revision == material.current_issue_revision,
            "VERSION_CONFLICT",
            409,
        )
    anchor.source_closure(body.sources, body.required_source_read_set, body.source_basis)
    all_refs = _all_source_refs(body.model_dump(mode="json"))
    _require(
        set(anchor.canonical_sources(all_refs)) <= set(anchor.canonical_sources(body.sources)),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )
    _require(
        set(anchor.canonical_reads(origin.required_source_read_set))
        <= set(anchor.canonical_reads(body.required_source_read_set)),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )
    _require(
        set(anchor.canonical_sources(payload.sources))
        <= set(anchor.canonical_sources(body.sources)),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )
    if body.visibility == "category":
        _require(
            all(v.visibility == "category" for v in body.source_basis),
            "FACT_AUDIENCE_MISMATCH",
            403,
        )
    operation = commands.SPECS[kind][0]
    authority = material.authority_snapshot
    _require(
        authority.get("authorized") is True
        and authority.get("qualified") is True
        and authority.get("subject_id") == str(ctx.actor_id)
        and authority.get("operation") == operation
        and authority.get("purpose") == body.purpose
        and authority.get("scope") == body.scope.model_dump(mode="json"),
        "QUALIFICATION_REQUIRED",
        409,
    )
    _require(
        bool(material.policy_snapshot) and bool(material.inspection), "FACT_WRITE_OWNER_REQUIRED"
    )
    for snapshot in (material.authority_snapshot, material.policy_snapshot):
        reads = snapshot.get("required_source_read_set", [])
        if reads:
            _require(
                set(anchor.canonical_reads(reads))
                <= set(anchor.canonical_reads(body.required_source_read_set)),
                "MISSING_REQUIRED_EVIDENCE",
                409,
            )
    if kind == "rule":
        _require(
            payload.origin == origin.ref
            and body.previous == payload.previous
            and body.failures == origin.issue.failures
            and body.actions == _action_bindings(material.anchor),
            "FACT_RULE_MATERIAL_MISMATCH",
            409,
        )
        for key in (
            "policy_ref",
            "method",
            "criterion",
            "sampling",
            "rule_material",
            "independence_material",
            "valid_from",
            "valid_until",
        ):
            _require(
                _json(getattr(body, key)) == _json(getattr(payload, key)),
                "FACT_RULE_MATERIAL_MISMATCH",
                409,
            )
        _require(body.issuer.nature == body.nature, "FACT_ISSUER_NATURE_MISMATCH")
    elif kind == "observation":
        _require(
            body.rule == payload.rule
            and body.previous == payload.previous
            and body.executor_id == ctx.actor_id
            and body.issuer.nature == body.nature,
            "FACT_OBSERVATION_BINDING_MISMATCH",
            409,
        )
        _require(
            tuple(v.key for v in body.targets) == payload.target_keys,
            "FACT_OBSERVATION_TARGET_MISMATCH",
            409,
        )
        for key in ("observed_from", "observed_until", "at", "coverage_sources"):
            _require(
                _json(getattr(body, key)) == _json(getattr(payload, key)),
                "FACT_OBSERVATION_BINDING_MISMATCH",
                409,
            )
        _require(len(body.records) == len(payload.records), "FACT_OBSERVATION_RECORD_MISMATCH", 409)
        for actual, requested in zip(body.records, payload.records, strict=True):
            _require(
                actual.model_dump(mode="json", exclude={"missing_fields"})
                == requested.model_dump(mode="json"),
                "FACT_OBSERVATION_RECORD_MISMATCH",
                409,
            )
    else:
        _require(
            body.candidate == payload.candidate
            and body.candidate_sha256 == payload.candidate.sha256
            and body.rule == payload.rule
            and body.observations == payload.observations
            and body.reviewer_id == ctx.actor_id
            and body.authority_snapshot == authority
            and body.policy_snapshot == material.policy_snapshot,
            "FACT_REVIEW_BINDING_MISMATCH",
            409,
        )
        for key in ("at", "conclusion", "reason", "pair_applicability"):
            _require(
                _json(getattr(body, key)) == _json(getattr(payload, key)),
                "FACT_REVIEW_BINDING_MISMATCH",
                409,
            )
        _require(
            len(body.action_fulfillment) == len(payload.action_fulfillment)
            and {v.action.action_id for v in body.action_fulfillment}
            == {v.action_id for v in _action_bindings(material.anchor)},
            "FACT_REVIEW_ACTION_MISMATCH",
            409,
        )
        for actual, requested in zip(
            body.action_fulfillment, payload.action_fulfillment, strict=True
        ):
            _require(
                (actual.action.action_id, actual.conclusion, actual.reason)
                == (requested.action_id, requested.conclusion, requested.reason)
                and set(anchor.canonical_sources(requested.sources))
                <= set(anchor.canonical_sources(actual.owner_refs)),
                "FACT_REVIEW_ACTION_MISMATCH",
                409,
            )
        _require(
            bool(body.participants)
            and bool(body.participant_owner_material)
            and len({p.id for p in body.participants}) == len(body.participants)
            and ctx.actor_id not in {p.id for p in body.participants},
            "INDEPENDENT_REVIEWER_REQUIRED",
            409,
        )
    _require(_time_current(material, _clock()), "SOURCE_STALE", 409)


class FactWriteHost:
    """Explicit configured actual owner. A copied DTO/phase never authorizes a write."""

    def __init__(self, owner: FactMaterialOwner):
        _require(
            owner is not None
            and all(
                callable(getattr(owner, key, None)) for key in ("read", "refresh", "runtime_stamp")
            )
        )
        self.owner = owner
        self._phases = WeakKeyDictionary()

    def _runtime(self, s):
        value = self.owner.runtime_stamp(s)
        _require(
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value),
            "FACT_RUNTIME_OWNER_REQUIRED",
        )
        ports = tuple(getattr(self.owner, key) for key in ("read", "refresh", "runtime_stamp"))
        return value, (id(self.owner), *(id(getattr(port, "__func__", port)) for port in ports))

    def prepare(self, s, ctx, pid, payload, *, new_write=False):
        _require(
            isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
            "FORBIDDEN_SCOPE",
            403,
        )
        kind = commands.kind_for_payload(payload)
        payload = commands.payload_for(kind, payload)
        _require(type(new_write) is bool, "FACT_PHASE_KIND_REQUIRED")
        uow, caller, runtime = guards._uow(s), digest(vars(ctx)), self._runtime(s)
        value = _material(self.owner.read(s, ctx, pid, kind, payload, new_write=new_write))
        _check_material(ctx, pid, kind, payload, value, new_write=new_write)
        guard = _caller(s, ctx, pid, value.body_material.scope.project_id)
        current = _current(s, ctx, pid, value)
        _series(
            s,
            ctx,
            pid,
            kind,
            value,
            new_write=new_write,
            external_id=getattr(payload, "external_id", None),
        )
        # All owner/source IO may have changed an earlier proof. A separate
        # complete fresh owner pass and post-IO SQL/caller check is mandatory.
        refreshed = _material(
            self.owner.refresh(s, ctx, pid, kind, payload, value, new_write=new_write)
        )
        _require(refreshed == value, "SOURCE_STALE", 409)
        _check_material(ctx, pid, kind, payload, refreshed, new_write=new_write)
        _series(
            s,
            ctx,
            pid,
            kind,
            value,
            new_write=new_write,
            external_id=getattr(payload, "external_id", None),
        )
        _require(
            _current(s, ctx, pid, value) == current
            and _caller(s, ctx, pid, value.body_material.scope.project_id) == guard,
            "SOURCE_STALE",
            409,
        )
        _require(self._runtime(s) == runtime, "SOURCE_STALE", 409)
        guards._same_uow(s, uow, ctx, caller)
        at = _clock()  # Actual clock after every owner and SQL read.
        _require(
            _time_current(value, at)
            and (guard[3]["expires_at"] is None or at < guard[3]["expires_at"]),
            "SOURCE_STALE",
            409,
        )
        phase = PreparedFact(
            kind, commands.semantic(payload), value, new_write, s, uow, caller, runtime[0], at
        )
        self._phases[phase] = (digest(reviewed_fact_material(phase)), runtime, guard, current)
        return phase

    def require(self, s, ctx, pid, payload, phase):
        self._registered(s, ctx, pid, payload, phase)
        value = _material(
            self.owner.refresh(
                s, ctx, pid, phase.kind, payload, phase.material, new_write=phase.new_write
            )
        )
        _require(value == phase.material, "SOURCE_STALE", 409)
        _check_material(ctx, pid, phase.kind, payload, value, new_write=phase.new_write)
        _series(
            s,
            ctx,
            pid,
            phase.kind,
            value,
            new_write=phase.new_write,
            external_id=getattr(payload, "external_id", None),
        )
        self._final_sql(s, ctx, pid, payload, phase)
        self._registered(s, ctx, pid, payload, phase)
        guards._same_uow(s, phase.uow, ctx, phase.caller_sha256)
        require_prepared_fact_clock(s, ctx, pid, payload, phase, _clock(), host=self)
        return phase

    def _final_sql(self, s, ctx, pid, payload, phase):
        """After the last series IO, recheck Current, actual caller and runtime."""
        state = self._registered(s, ctx, pid, payload, phase)
        current = _current(s, ctx, pid, phase.material)
        guard = _caller(s, ctx, pid, phase.material.body_material.scope.project_id)
        _require(
            guard == state[2] and current == state[3] and self._runtime(s) == state[1],
            "SOURCE_STALE",
            409,
        )
        guards._same_uow(s, phase.uow, ctx, phase.caller_sha256)

    def _registered(self, s, ctx, pid, payload, phase):
        _require(
            type(phase) is PreparedFact and phase in self._phases, "FACT_OPAQUE_PHASE_REQUIRED"
        )
        value = self._phases[phase]
        _require(
            phase.session is s
            and phase.material.body_material.scope.product_id == pid
            and phase.payload_semantic == commands.semantic(payload)
            and digest(reviewed_fact_material(phase)) == value[0],
            "FACT_PHASE_MATERIAL_CHANGED",
        )
        guards._same_uow(s, phase.uow, ctx, phase.caller_sha256)
        return value

    def invalidate(self, phase):
        _require(
            type(phase) is PreparedFact and phase in self._phases, "FACT_OPAQUE_PHASE_REQUIRED"
        )
        del self._phases[phase]


def prepare_fact(s, ctx, product_id, payload, *, host, new_write=False):
    _require(type(host) is FactWriteHost)
    return host.prepare(s, ctx, product_id, payload, new_write=new_write)


def reviewed_fact_material(phase):
    """Stable 13-key reviewed material; saved UUID/received clock are not proposed."""
    m, body = phase.material, phase.material.body_material
    return {
        "operation": commands.SPECS[phase.kind][0],
        "payload_semantic": deepcopy(phase.payload_semantic),
        "stable_anchor": m.anchor.model_dump(mode="json"),
        "binding": {
            "kind": phase.kind,
            "body_material": body.model_dump(mode="json"),
            "current_issue_version_id": str(m.current_issue_version_id),
            "series": _json(m.series),
        },
        "inspection": deepcopy(m.inspection),
        "raw_source_basis": [_json(v) for v in body.source_basis],
        "required_source_read_set": [_json(v) for v in body.required_source_read_set],
        "sources": [_json(v) for v in body.sources],
        "authority_snapshot": deepcopy(m.authority_snapshot),
        "policy_snapshot": deepcopy(m.policy_snapshot),
        "owner_id": str(body.owner_id),
        "visibility": body.visibility,
        "current_issue_revision": m.current_issue_revision,
    }


def reviewed_fact(phase, *, host):
    _require(type(host) is FactWriteHost and phase in host._phases, "FACT_OPAQUE_PHASE_REQUIRED")
    _require(
        digest(reviewed_fact_material(phase)) == host._phases[phase][0],
        "FACT_PHASE_MATERIAL_CHANGED",
    )
    return reviewed_fact_material(phase)


def require_prepared_fact_clock(s, ctx, pid, payload, phase, at, *, host):
    state = host._registered(s, ctx, pid, payload, phase)
    _require(host._runtime(s) == state[1], "SOURCE_STALE", 409)
    at = _instant(at)
    _require(
        phase.checked_at <= at
        and _time_current(phase.material, at)
        and (state[2][3]["expires_at"] is None or at < state[2][3]["expires_at"]),
        "SOURCE_STALE",
        409,
    )
    if phase.kind == "review":
        until = phase.material.body_material.valid_until
        _require(until is None or at < until, "SOURCE_STALE", 409)
    return at


def _product(s, ctx, command, product):
    _require(isinstance(product, Product), "FACT_ACTUAL_PRODUCT_REQUIRED")
    state = inspect(product)
    _require(
        state.persistent is True
        and state.session is s
        and not state.deleted
        and not {"id", "tenant_id", "revision"} & state.unloaded,
        "FACT_ACTUAL_PRODUCT_REQUIRED",
    )
    _require(
        (product.id, product.tenant_id) == (command.product_id, ctx.tenant_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        type(product.revision) is int and product.revision == command.expected_revision,
        "VERSION_CONFLICT",
        409,
    )


def _command(s, ctx, command, product, payload, phase, host, module):
    _require(isinstance(command, Command) and isinstance(ctx, Context), "FACT_COMMAND_REQUIRED")
    host._registered(s, ctx, command.product_id, payload, phase)
    _require(
        phase.new_write is True and command.operation == commands.SPECS[phase.kind][0],
        "FACT_NEW_WRITE_REQUIRED",
    )
    checked = commands.payload_for(phase.kind, command.payload)
    _require(
        checked == commands.payload_for(phase.kind, payload)
        and callable(getattr(module, "semantic", None))
        and module.semantic(checked) == commands.semantic(checked),
        "FACT_ACTUAL_SEMANTIC_REQUIRED",
    )
    _require(
        anchor.canonical_reads(command.source_read_set)
        == anchor.canonical_reads(phase.required_source_read_set),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )
    _product(s, ctx, command, product)


def _construct_row(ctx, command, payload, phase, at, live):
    m, draft = phase.material, phase.material.body_material
    previous = draft.previous
    fact_id, revision = uuid4(), previous.revision + 1 if previous else 1
    body = draft.model_dump(mode="json")
    body.update(ref={"id": str(fact_id), "revision": revision}, created_at=at.isoformat())
    document = decode_fact_body({"schema_version": SCHEMA_VERSION, "body": body})
    # Cross-field checks that require a FactAtom stay with the actual saved
    # reader. Clock/executor/nature/scope/material checks run before this add.
    body = document.body
    if phase.kind == "observation":
        _require(
            body.observed_from < body.observed_until <= body.at.occurred_at <= at
            and all(
                body.observed_from <= r.occurred_at <= body.observed_until for r in body.records
            ),
            "FACT_TIME_INVALID",
            409,
        )
    if phase.kind == "review":
        _require(
            body.at.occurred_at <= at and (body.valid_until is None or at < body.valid_until),
            "FACT_TIME_INVALID",
            409,
        )
    origin = m.anchor.origin
    values = {
        "id": fact_id,
        "tenant_id": ctx.tenant_id,
        "created_at": at,
        "product_id": body.scope.product_id,
        "project_id": body.scope.project_id,
        "issue_id": body.issue_id,
        "capa_id": body.capa_id,
        "origin_issue_version_id": origin.ref.id,
        "origin_issue_revision": origin.ref.revision,
        "owner_id": body.owner_id,
        "visibility": body.visibility,
        "nature": body.nature,
        "purpose": body.purpose,
        "anchor_snapshot": m.anchor.model_dump(mode="json"),
        "anchor_sha256": body.anchor_sha256,
        "requirement_sha256": body.requirement_sha256,
        "revision": revision,
        "writer_id": ctx.actor_id,
        "actor_id": ctx.actor_id,
        "requester_id": ctx.requester_id,
        "command_id": command.command_id,
        "operation": commands.SPECS[phase.kind][0],
        "tier": commands.SPECS[phase.kind][1],
        "fact_kind": phase.kind,
        "status": {"rule": "published", "observation": "recorded", "review": "reviewed"}[
            phase.kind
        ],
        "fact_body": document.model_dump(mode="json"),
        "payload_sha256": body_payload_sha256(document),
        "sources": [_json(v) for v in body.sources],
        "required_source_read_set": [_json(v) for v in body.required_source_read_set],
        "source_basis": [_json(v) for v in body.source_basis],
        "input_snapshot": {
            "semantic": commands.semantic(payload),
            "shared_proof": None if live is None else {"id": str(live.proof_id), "tier": live.tier},
            "proof_consumed_at": None if live is None else live.consumed_at.isoformat(),
        },
        "authority_snapshot": deepcopy(m.authority_snapshot),
        "policy_snapshot": deepcopy(m.policy_snapshot),
    }
    if phase.kind in {"rule", "observation"}:
        values.update(
            series_id=fact_id if m.series is None else m.series.series_id,
            previous_fact_id=None if previous is None else previous.id,
            previous_revision=None if previous is None else previous.revision,
            issuer_key=body.issuer.key,
            issuer_version=body.issuer.version,
            issuer_epoch=body.issuer.epoch,
        )
    if phase.kind == "rule":
        values.update(
            external_id=payload.external_id,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
        )
        cls = models.RuleFact
    elif phase.kind == "observation":
        values.update(
            rule_fact_id=body.rule.id,
            rule_revision=body.rule.revision,
            rule_sha256=body.rule.sha256,
            executor_id=ctx.actor_id,
            observed_from=body.observed_from,
            observed_until=body.observed_until,
        )
        cls = models.ObservationFact
    else:
        values.update(
            candidate_id=body.candidate.id,
            candidate_revision=body.candidate.revision,
            candidate_sha256=body.candidate.sha256,
            rule_fact_id=body.rule.id,
            rule_revision=body.rule.revision,
            rule_sha256=body.rule.sha256,
            reviewer_id=ctx.actor_id,
            valid_until=body.valid_until,
        )
        cls = models.NamedReviewRecord
    if live:
        values.update(live.storage_columns())
    return cls(**values)


def apply_prepared_fact(
    s,
    ctx,
    command,
    product,
    payload,
    phase,
    *,
    host,
    consumption_host,
    module,
    proof,
    consumption_binding,
    consumption_marker,
):
    _require(type(host) is FactWriteHost and type(consumption_host) is ConsumptionHost)
    _command(s, ctx, command, product, payload, phase, host, module)
    _require(phase.kind in {"observation", "review"}, "FACT_RULE_HOST_ONLY")
    review = reviewed_fact(phase, host=host)
    _require(proof.snapshot == review, "FACT_REVIEW_MATERIAL_CHANGED", 409)
    live = consumption_host.require_live(
        s,
        ctx,
        command,
        payload,
        module,
        proof,
        binding=consumption_binding,
        marker=consumption_marker,
    )
    _require(
        type(live) is LiveConsumption
        and live is consumption_marker
        and live.tier == commands.SPECS[phase.kind][1],
        "FACT_LIVE_CONSUMPTION_REQUIRED",
    )
    host.require(s, ctx, command.product_id, payload, phase)
    _command(s, ctx, command, product, payload, phase, host, module)
    _require(proof.snapshot == review, "FACT_REVIEW_MATERIAL_CHANGED", 409)
    # Stage pointer lookup is an IO boundary. Complete it before the last live
    # check and real save clock; never do source/SQL work after that final check.
    pointer = _series(
        s,
        ctx,
        command.product_id,
        phase.kind,
        phase.material,
        new_write=True,
        external_id=getattr(payload, "external_id", None),
    )
    host._final_sql(s, ctx, command.product_id, payload, phase)
    live = consumption_host.require_live(
        s,
        ctx,
        command,
        payload,
        module,
        proof,
        binding=consumption_binding,
        marker=consumption_marker,
    )
    at = require_prepared_fact_clock(
        s, ctx, command.product_id, payload, phase, _clock(), host=host
    )
    _require(live.consumed_at <= at and proof_deadline_current(live.tier, live.expires_at, at),
             "FACT_CONSUMPTION_CLOCK_INVALID", 409)
    row = _construct_row(ctx, command, payload, phase, at, live)
    consumption_host.require_live(
        s,
        ctx,
        command,
        payload,
        module,
        proof,
        binding=consumption_binding,
        marker=consumption_marker,
    )
    require_prepared_fact_clock(s, ctx, command.product_id, payload, phase, _clock(), host=host)
    host.invalidate(phase)
    _stage_without_io(s, phase, row, pointer)
    return row


def _stage_without_io(s, phase, row, pointer):
    if phase.kind in {"rule", "observation"}:
        if pointer is None:
            cls = models.RuleCurrent if phase.kind == "rule" else models.ObservationCurrent
            values = {key: getattr(row, key) for key in models.BINDING}
            values.update(
                id=uuid4(),
                created_at=row.created_at,
                anchor_snapshot=deepcopy(row.anchor_snapshot),
                series_id=row.series_id,
                fact_id=row.id,
                fact_revision=row.revision,
                epoch=1,
            )
            if phase.kind == "rule":
                values.update(
                    issuer_key=row.issuer_key,
                    issuer_version=row.issuer_version,
                    external_id=row.external_id,
                )
            pointer = cls(**values)
            s.add(pointer)
        else:
            pointer.fact_id, pointer.fact_revision, pointer.epoch = (
                row.id,
                row.revision,
                pointer.epoch + 1,
            )
            if phase.kind == "rule":
                pointer.issuer_version = row.issuer_version
    s.add(row)


def append_prepared_rule(
    s, ctx, command, product, payload, phase, *, host, module, common_intent_digest
):
    _require(type(host) is FactWriteHost and phase.kind == "rule", "FACT_RULE_HOST_ONLY")
    _command(s, ctx, command, product, payload, phase, host, module)
    host.require(s, ctx, command.product_id, payload, phase)
    _command(s, ctx, command, product, payload, phase, host, module)
    pointer = _series(
        s,
        ctx,
        command.product_id,
        "rule",
        phase.material,
        new_write=True,
        external_id=payload.external_id,
    )
    host._final_sql(s, ctx, command.product_id, payload, phase)
    intent = digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "payload": commands.semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id if payload.visibility == "private" else None,
        }
    )
    _require(common_intent_digest == intent, "FACT_COMMON_INTENT_REQUIRED")
    at = require_prepared_fact_clock(
        s, ctx, command.product_id, payload, phase, _clock(), host=host
    )
    row = _construct_row(ctx, command, payload, phase, at, None)
    row.intent_digest = intent
    row.read_set_sha256 = digest(
        [_json(v) for v in anchor.canonical_reads(phase.required_source_read_set)]
    )
    for key in (
        "shared_proof_id",
        "shared_proof_revision",
        "proof_expires_at",
        "proof_consumed_at",
        "token_sha256",
        "material_sha256",
    ):
        setattr(row, key, None)
    require_prepared_fact_clock(s, ctx, command.product_id, payload, phase, _clock(), host=host)
    host.invalidate(phase)
    _stage_without_io(s, phase, row, pointer)
    return row
