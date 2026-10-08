"""Unregistered SQL registry/raw reader; it issues no live owner proof.

Depends on frozen fact_atom_storage v5 for real UOW/caller/group reading. Every
SELECT is exact, bounded and without autoflush; there is no write or commit.
Registry membership is distinct from source/issuer/professional applicability.
"""

# Common registry initialization must precede staged declarations.
# ruff: noqa: I001

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from collections.abc import Callable
from uuid import UUID

import fact_atom_storage as atom_storage
import fact_storage_models as models
from anchor import StableCapaAnchor
from fact_storage_codec import assemble_fact
from facts import FactRef, NamedReview, ObservationVersion, RuleVersion, GATES, _action_bindings
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context, digest
from sqlalchemy import select

Kind = Literal["rule", "observation", "review"]
Fact = RuleVersion | ObservationVersion | NamedReview
MAX_NODES = 64  # Aggregate immutable versions, origins, pointers and candidate.
TABLES = {
    "rule": models.RuleFact.__table__,
    "observation": models.ObservationFact.__table__,
    "review": models.NamedReviewRecord.__table__,
}
CURRENTS = {
    "rule": models.RuleCurrent.__table__,
    "observation": models.ObservationCurrent.__table__,
}


@dataclass(frozen=True)
class RegistryState:
    kind: Kind
    selected: FactRef
    series_id: UUID | None
    current_ref: FactRef | None
    current_epoch: int | None
    state: Literal["current_registered", "historical_registered", "fixed_review"]


@dataclass(frozen=True)
class StoredDependency:
    fact: Fact
    group_sha256: str
    registry: RegistryState


@dataclass(frozen=True)
class CandidateRegistryRead:
    """Future actual candidate owner result; a hash alone grants no permission.

    Callback must read the real candidate/full group under these very objects.
    No existing inspection_sha256 or binding_sha256 is a full FactRef digest.
    This type is raw registry material, NOT one of FactReader's live seven gates.
    """

    session: object
    caller: Context
    product_id: UUID
    ref: FactRef
    scope: Scope
    issue_id: UUID
    capa_id: UUID
    purpose: str
    owner_id: UUID
    visibility: Literal["private", "product"]
    nature: Literal["real", "synthetic"]
    anchor_sha256: str
    requirement_sha256: str


CandidateOwner = Callable[[object, Context, UUID, FactRef], CandidateRegistryRead]


@dataclass(frozen=True)
class StoredFactRead:
    fact: Fact
    group_sha256: str
    registry: RegistryState
    # Direct child order is preserved exactly; chain ancestors are separately
    # verified and bounded, never substituted for these fixed refs.
    dependencies: tuple[StoredDependency, ...]
    candidate: CandidateRegistryRead | None
    registry_observed_at: datetime
    missing: tuple[str, ...]
    needs_lineage_owner: Literal[True] = True
    current_evidence_authorized: Literal[False] = False
    same_uow_consumption_attested: Literal[False] = False


def _require(condition, code):
    if not condition:
        raise DomainError(code, "事实的精确登记、前版或固定父对象尚不能完整核对。", 503)


def _integer(value):
    return type(value) is int and value > 0


def _json(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


class _Read:
    def __init__(self, s, ctx, product_id, candidate_owner):
        self.s, self.ctx, self.product_id = s, ctx, product_id
        self.candidate_owner = candidate_owner
        self.uow, self.caller = atom_storage._uow(s), digest(vars(ctx))
        self.nodes, self.facts, self.states, self.pointers = set(), {}, {}, {}
        self.origins, self.projects = {}, {}

    def _budget(self, key):
        self.nodes.add(key)
        _require(len(self.nodes) <= MAX_NODES, "FACT_REGISTRY_LIMIT_EXCEEDED")

    def _one(self, table, where):
        rows = list(
            self.s.execute(
                select(table)
                .where(*where)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            ).mappings()
        )
        _require(len(rows) == 1, "FACT_EXACT_REGISTRY_ROW_MISSING")
        return deepcopy(dict(rows[0]))

    def _scoped(self, table, **values):
        where = [table.c.tenant_id == self.ctx.tenant_id, table.c.product_id == self.product_id]
        where.extend(table.c[name] == value for name, value in values.items())
        return self._one(table, where)

    def _project(self, project_id):
        self._budget(("project", project_id))
        value = self._scoped(Project.__table__, id=project_id)
        _require(
            value["visibility"] in ("private", "product") and value["status"] == "active",
            "FACT_PROJECT_STATE_INVALID",
        )
        if value["visibility"] == "private" and value["owner_id"] != self.ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "私有项目的事实仅允许原合法受众读取。", 403)
        # The current plan/name/revision may advance without enlarging the
        # audience. Only the exact current ACL binding is captured here.
        stamp = {
            k: value[k]
            for k in ("tenant_id", "product_id", "id", "owner_id", "visibility", "status")
        }
        if project_id in self.projects:
            _require(self.projects[project_id] == stamp, "FACT_PROJECT_CHANGED_DURING_READ")
        self.projects[project_id] = stamp

    def _origin(self, row):
        anchor = StableCapaAnchor.model_validate(row["anchor_snapshot"])
        origin = anchor.origin
        expected = {
            "tenant_id": origin.scope.tenant_id,
            "product_id": origin.scope.product_id,
            "project_id": origin.scope.project_id,
            "issue_id": origin.issue_id,
            "capa_id": origin.issue.capa.id,
            "origin_issue_version_id": origin.ref.id,
            "origin_issue_revision": origin.ref.revision,
            "owner_id": origin.owner_id,
            "visibility": origin.visibility,
            "nature": origin.nature,
            "purpose": origin.purpose,
            "anchor_sha256": anchor.anchor_sha256,
            "requirement_sha256": digest(_json(origin.issue.capa.requirement)),
        }
        _require(all(row[k] == v for k, v in expected.items()), "FACT_ANCHOR_BINDING_MISMATCH")
        _require(
            origin.scope.tenant_id == self.ctx.tenant_id
            and origin.scope.product_id == self.product_id,
            "FACT_ANCHOR_SCOPE_MISMATCH",
        )
        key = ("origin", origin.ref.id, origin.ref.revision)
        self._budget(key)
        saved = self._scoped(
            QualityIssueVersion.__table__,
            project_id=origin.scope.project_id,
            issue_id=origin.issue_id,
            id=origin.ref.id,
            revision=origin.ref.revision,
        )
        actual = {
            "issue_snapshot": _json(origin.issue),
            "snapshot_sha256": origin.ref.snapshot_sha256,
            "owner_id": origin.owner_id,
            "writer_id": origin.writer_id,
            "visibility": origin.visibility,
            "purpose": origin.purpose,
            "operation": origin.operation,
            "created_at": origin.created_at,
            "input_snapshot": origin.input_snapshot,
            "authority_snapshot": origin.authority_snapshot,
            "policy_snapshot": origin.policy_snapshot,
            "source_basis": origin.persisted_source_basis,
            "sources": [_json(v) for v in origin.sources],
            "required_source_read_set": [_json(v) for v in origin.required_source_read_set],
        }
        _require(all(saved[k] == v for k, v in actual.items()), "FACT_ORIGIN_ROW_MISMATCH")
        _require(
            (saved["previous_issue_version_id"], saved["previous_revision"])
            == (
                origin.previous_ref.id if origin.previous_ref else None,
                origin.previous_ref.revision if origin.previous_ref else None,
            ),
            "FACT_ORIGIN_PREVIOUS_MISMATCH",
        )
        if key in self.origins:
            _require(self.origins[key] == saved, "FACT_ORIGIN_CHANGED_DURING_READ")
        self.origins[key] = saved
        return anchor

    def _fact(self, kind, ref, *, revision=None):
        fact_id, version = (ref.id, ref.revision) if ref is not None else revision
        key = (kind, fact_id, version)
        if key in self.facts:
            saved = self.facts[key]
            _require(ref is None or saved[0].ref == ref, "FACT_FULL_REF_MISMATCH")
            return saved
        self._budget(key)
        row = self._scoped(TABLES[kind], id=fact_id, revision=version)
        self._project(row["project_id"])
        group = atom_storage.read_fact_atom(
            self.s, self.ctx, self.product_id, kind=kind, fact_id=fact_id, revision=version
        )
        fact = assemble_fact(
            row["fact_body"],
            group.atom,
            expected_payload_sha256=row["payload_sha256"],
            expected_ref=ref,
        )
        anchor = self._origin(row)
        _require(
            fact.anchor_sha256 == anchor.anchor_sha256
            and fact.requirement_sha256 == row["requirement_sha256"],
            "FACT_ANCHOR_MATERIAL_MISMATCH",
        )
        _require(
            row["sources"] == [_json(v) for v in fact.sources]
            and row["required_source_read_set"] == [_json(v) for v in fact.required_source_read_set]
            and row["source_basis"] == [_json(v) for v in fact.source_basis],
            "FACT_SOURCE_MIRROR_MISMATCH",
        )
        if kind != "review":
            previous = fact.previous
            _require(
                (row["previous_fact_id"], row["previous_revision"])
                == (previous.id if previous else None, previous.revision if previous else None)
                and (
                    previous is not None
                    or (fact.ref.revision == 1 and row["series_id"] == fact.ref.id)
                ),
                "FACT_SERIES_PREVIOUS_MISMATCH",
            )
            _require(
                (row["issuer_key"], row["issuer_version"], row["issuer_epoch"])
                == (fact.issuer.key, fact.issuer.version, fact.issuer.epoch),
                "FACT_ISSUER_MIRROR_MISMATCH",
            )
        if kind == "rule":
            _require(
                fact.failures == anchor.origin.issue.failures
                and fact.actions == _action_bindings(anchor)
                and row["valid_from"] == fact.valid_from
                and row["valid_until"] == fact.valid_until,
                "FACT_RULE_FIXED_MATERIAL_MISMATCH",
            )
        elif kind == "observation":
            _require(
                (row["rule_fact_id"], row["rule_revision"], row["rule_sha256"])
                == (fact.rule.id, fact.rule.revision, fact.rule.sha256)
                and row["executor_id"] == fact.executor_id
                and row["observed_from"] == fact.observed_from
                and row["observed_until"] == fact.observed_until,
                "FACT_OBSERVATION_MIRROR_MISMATCH",
            )
        else:
            _require(
                (row["rule_fact_id"], row["rule_revision"], row["rule_sha256"])
                == (fact.rule.id, fact.rule.revision, fact.rule.sha256)
                and (row["candidate_id"], row["candidate_revision"], row["candidate_sha256"])
                == (fact.candidate.id, fact.candidate.revision, fact.candidate.sha256)
                and row["reviewer_id"] == fact.reviewer_id
                and row["valid_until"] == fact.valid_until
                and row["authority_snapshot"] == fact.authority_snapshot
                and row["policy_snapshot"] == fact.policy_snapshot
                and fact.ref.revision == 1
                and fact.previous is None,
                "FACT_REVIEW_MIRROR_MISMATCH",
            )
        self.facts[key] = fact, group.group_sha256, row
        return self.facts[key]

    def _same_binding(self, a, b):
        _require(
            all(a[k] == b[k] for k in models.BINDING)
            and a["anchor_snapshot"] == b["anchor_snapshot"],
            "FACT_SERIES_SCOPE_OR_ANCHOR_MISMATCH",
        )

    def _registry(self, kind, fact):
        key = (kind, fact.ref.id, fact.ref.revision)
        if key in self.states:
            return self.states[key]
        if kind == "review":
            state = RegistryState(kind, fact.ref, None, None, None, "fixed_review")
            self.states[key] = state
            return state
        row = self.facts[key][2]
        pointer_key = (kind, row["series_id"])
        self._budget(("pointer", *pointer_key))
        pointer = self._scoped(
            CURRENTS[kind],
            project_id=row["project_id"],
            issue_id=row["issue_id"],
            capa_id=row["capa_id"],
            series_id=row["series_id"],
        )
        self._same_binding(row, pointer)
        _require(
            _integer(pointer["fact_revision"]) and _integer(pointer["epoch"]),
            "FACT_CURRENT_VERSION_OR_EPOCH_INVALID",
        )
        if pointer_key in self.pointers:
            _require(self.pointers[pointer_key] == pointer, "FACT_CURRENT_CHANGED_DURING_READ")
        self.pointers[pointer_key] = pointer
        current, _, latest_row = self._fact(
            kind, None, revision=(pointer["fact_id"], pointer["fact_revision"])
        )
        self._same_binding(row, latest_row)
        _require(latest_row["series_id"] == row["series_id"], "FACT_CURRENT_SERIES_MISMATCH")
        if kind == "rule":
            _require(
                all(
                    pointer[k] == latest_row[k]
                    for k in ("issuer_key", "issuer_version", "external_id")
                ),
                "FACT_CURRENT_ISSUER_SERIES_MISMATCH",
            )
        chain, previous = [], current
        while True:
            selected_row = self.facts[(kind, previous.ref.id, previous.ref.revision)][2]
            self._same_binding(latest_row, selected_row)
            _require(selected_row["series_id"] == row["series_id"], "FACT_PREVIOUS_SERIES_MISMATCH")
            if kind == "rule":
                _require(
                    all(selected_row[k] == latest_row[k] for k in ("issuer_key", "external_id")),
                    "FACT_RULE_EXTERNAL_SERIES_MISMATCH",
                )
            else:
                _require(
                    all(
                        selected_row[k] == latest_row[k]
                        for k in ("rule_fact_id", "rule_revision", "rule_sha256", "executor_id")
                    ),
                    "FACT_OBSERVATION_SERIES_REBOUND",
                )
            _require(previous.ref not in chain, "FACT_PREVIOUS_CYCLE")
            chain.append(previous.ref)
            if previous.previous is None:
                break
            previous, _, _ = self._fact(kind, previous.previous)
        _require(fact.ref in chain, "FACT_SELECTED_VERSION_NOT_IN_CURRENT_SERIES")
        for member in chain:
            self.states[(kind, member.id, member.revision)] = RegistryState(
                kind,
                member,
                row["series_id"],
                current.ref,
                pointer["epoch"],
                "current_registered" if member == current.ref else "historical_registered",
            )
        return self.states[key]

    def _dependency(self, kind, ref, parent_row):
        value, group, row = self._fact(kind, ref)
        self._same_binding(parent_row, row)
        return StoredDependency(value, group, self._registry(kind, value))

    def _candidate(self, value, row):
        _require(callable(self.candidate_owner), "FACT_CANDIDATE_OWNER_REQUIRED")
        self._budget(("candidate", value.candidate.id, value.candidate.revision))
        raw = self._scoped(
            CapaVerificationEvidence.__table__,
            project_id=row["project_id"],
            issue_id=row["issue_id"],
            capa_id=row["capa_id"],
            id=value.candidate.id,
            revision=value.candidate.revision,
        )
        _require(
            value.candidate.revision == 1
            and all(raw[k] == row[k] for k in ("owner_id", "visibility", "purpose", "nature"))
            and raw["status"] == "candidate"
            and raw["result"] == "indeterminate"
            and all(
                raw[k] is None
                for k in ("applicable", "independently_verified", "observation_complete")
            ),
            "FACT_CANDIDATE_RAW_BINDING_MISMATCH",
        )
        result = self.candidate_owner(self.s, self.ctx, self.product_id, value.candidate)
        _require(isinstance(result, CandidateRegistryRead), "FACT_TYPED_CANDIDATE_OWNER_REQUIRED")
        _require(
            result.session is self.s
            and result.caller is self.ctx
            and result.product_id == self.product_id
            and result.ref == value.candidate
            and result.scope == value.scope
            and all(
                getattr(result, k) == row[k]
                for k in (
                    "issue_id",
                    "capa_id",
                    "purpose",
                    "owner_id",
                    "visibility",
                    "nature",
                    "anchor_sha256",
                    "requirement_sha256",
                )
            ),
            "FACT_CANDIDATE_OWNER_BINDING_MISMATCH",
        )
        atom_storage._same_uow(self.s, self.uow, self.ctx, self.caller)
        return result

    def finish(self):
        # All immutable/group/parent/callback IO has finished before this pass.
        for (kind, _), saved in self.pointers.items():
            current = self._scoped(CURRENTS[kind], id=saved["id"])
            _require(current == saved, "FACT_CURRENT_CHANGED_DURING_READ")
        for project_id in tuple(self.projects):
            self._project(project_id)
        atom_storage._acl(self.s, self.ctx, self.product_id)
        atom_storage._same_uow(self.s, self.uow, self.ctx, self.caller)
        return datetime.now(UTC)  # Actual post-IO observation, not a validity grant.


def read_stored_fact(
    s,
    ctx: Context,
    product_id: UUID,
    kind: Kind,
    ref: FactRef,
    *,
    candidate_owner: CandidateOwner | None = None,
) -> StoredFactRead:
    """Exact raw registry read; historic parents stay fixed and unauthorized.

    Missing source/issuer/participant/applicability/observation/professional/
    same-UOW owner integrations are explicit even when this registry is current.
    Does not compare origin Issue with Issue Current or grant finite lineage.
    """
    _require(isinstance(ctx, Context), "FACT_ACTUAL_NAMED_CALLER_REQUIRED")
    _require(isinstance(kind, str) and kind in TABLES, "FACT_KIND_NOT_SUPPORTED")
    _require(isinstance(product_id, UUID), "FACT_ACTUAL_PRODUCT_REQUIRED")
    _require(type(ref) is FactRef, "FACT_TYPED_FULL_REF_REQUIRED")
    ref = FactRef.model_validate(ref.model_dump(mode="json"))
    read = _Read(s, ctx, product_id, candidate_owner)
    with s.no_autoflush:
        atom_storage._acl(s, ctx, product_id)
        value, group, row = read._fact(kind, ref)
        state = read._registry(kind, value)
        dependencies, candidate = [], None
        if kind != "rule":
            rule = read._dependency("rule", value.rule, row)
            dependencies.append(rule)
            if kind == "review":
                _require(
                    len(value.observations) == len(set(value.observations)),
                    "FACT_DUPLICATE_OBSERVATION_REF",
                )
                for child in value.observations:
                    observation = read._dependency("observation", child, row)
                    _require(
                        observation.fact.rule == value.rule, "FACT_REVIEW_OBSERVATION_RULE_MISMATCH"
                    )
                    dependencies.append(observation)
                candidate = read._candidate(value, row)
        observed_at = read.finish()
    return StoredFactRead(
        value,
        group,
        state,
        tuple(dependencies),
        candidate,
        observed_at,
        tuple("FACT_" + gate.upper() + "_OWNER_REQUIRED" for gate in GATES)
        + ("FACT_ISSUER_OWNER_REQUIRED", "FACT_LINEAGE_OWNER_REQUIRED"),
    )
