"""Actual fact material assembly; missing professional owners fail explicitly.

Rule publication authority is a trusted startup port, never a request object.
Observation source JSON is compared with the exact registered original line.
This owner does not certify effectiveness or change an Issue pointer.
"""

# ruff: noqa: I001
from pdos_next.service import Context, digest, source_for

from copy import deepcopy
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.capa_effectiveness import anchor as a, anchor_owner, candidate_anchor_restore
from pdos_next.domain.capa_effectiveness import fact_atom_storage as guards
from pdos_next.domain.capa_effectiveness import (
    fact_commands as commands,
    fact_storage_models as models,
)
from pdos_next.domain.capa_effectiveness.fact_registry_storage import read_stored_fact
from pdos_next.domain.capa_effectiveness.fact_write import CurrentSeries, FactWriteMaterial
from pdos_next.domain.capa_effectiveness.facts import IssuerRef, _action_bindings, _all_source_refs
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.errors import DomainError
from pdos_next.quality_result_bridge import _runtime_stamp


def require(value, code="INTEGRATION_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "规则、原记录或当前专业核验依据尚不完整。", status)


def instant(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    require(at.utcoffset() is not None, "FACT_TIME_INVALID", 422)
    return at.astimezone(UTC)


def same_original_material(actual, wanted, *, clock_paths=()):
    """Exact JSON values; only declared aware clocks admit equivalent offsets."""
    left, right = deepcopy(actual), deepcopy(wanted)
    try:
        for value in (left, right):
            for path in clock_paths:
                parent = value
                for key in path[:-1]:
                    parent = parent[key]
                raw = parent[path[-1]]
                if type(raw) is not str:
                    return False
                parent[path[-1]] = instant(raw).isoformat()
        return json.dumps(
            left, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) == json.dumps(
            right, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, KeyError, IndexError, DomainError):
        return False


@dataclass(frozen=True)
class PublishedRuleMaterial:
    """Returned only by the configured publisher after original/issuer checks."""

    anchor: a.StableCapaAnchor
    issuer: IssuerRef
    sources: tuple
    inspection: dict
    valid_until: datetime


class ActualFactOwner:
    def __init__(self, *, publisher=None, review_owner=None):
        self.publisher, self.review_owner = publisher, review_owner

    def runtime_stamp(self, s):
        engine = s.get_bind()

        def port(owner, name):
            method = getattr(owner, name, None)
            return [id(owner), id(getattr(method, "__func__", method))]

        paired_owner = getattr(self.review_owner, "paired_owner", None)
        applicability_owner = getattr(self.review_owner, "applicability_owner", None)
        action_owner = getattr(applicability_owner, "action_owner", None)
        implementation_owner = getattr(action_owner, "implementation_owner", None)
        followup_owner = getattr(engine, "_pdos_paired_followup_owner", None)
        review_method = getattr(self.review_owner, "read", None)
        review_globals = getattr(
            getattr(review_method, "__func__", review_method), "__globals__", {}
        )
        return digest(
            {
                "result": _runtime_stamp(s),
                "publisher": id(self.publisher),
                "publisher_epoch": getattr(self.publisher, "epoch", None),
                "paired_followup_owner": {
                    "identity": id(followup_owner),
                    "runtime": getattr(followup_owner, "runtime", None),
                    "read": port(followup_owner, "read"),
                    "refresh": port(followup_owner, "refresh"),
                },
                "review_owner": id(self.review_owner),
                "review_owner_dependencies": {
                    key: id(review_globals.get(key))
                    for key in (
                        "read_candidate",
                        "read_participants",
                        "refresh_participants",
                        "read_source_closure",
                        "read_stored_fact",
                    )
                },
                "review_owner_ports": [
                    id(getattr(self.review_owner, "candidate_semantic_owner", None)),
                    getattr(paired_owner, "epoch", None),
                    getattr(applicability_owner, "epoch", None),
                    id(action_owner),
                    getattr(action_owner, "epoch", None),
                    id(implementation_owner),
                    getattr(implementation_owner, "epoch", None),
                    port(action_owner, "read"),
                    port(action_owner, "refresh"),
                    port(implementation_owner, "read"),
                    port(implementation_owner, "refresh"),
                ],
                "rule_issuers": {
                    k: [
                        id(v),
                        getattr(v, "epoch", None),
                        getattr(v, "version", None),
                        str(getattr(v, "tenant_id", None)),
                        str(getattr(v, "product_id", None)),
                        str(getattr(v, "project_id", None)),
                    ]
                    for k, v in getattr(engine, "_pdos_capa_rule_issuers", {}).items()
                },
                "fact_ports": [
                    port(self.publisher, "read"),
                    port(self.publisher, "current"),
                    port(self.review_owner, "read"),
                    port(paired_owner, "read"),
                    port(paired_owner, "refresh"),
                    port(paired_owner, "attest"),
                    port(applicability_owner, "read"),
                    port(applicability_owner, "refresh"),
                ],
                "professional_epochs": getattr(engine, "_pdos_professional_issuer_epochs", {}),
                "professional_issuers": {
                    k: id(v) for k, v in getattr(engine, "_pdos_professional_issuers", {}).items()
                },
                "policy_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
                "policy_issuers": {
                    k: id(v) for k, v in getattr(engine, "_pdos_quality_policy_issuers", {}).items()
                },
                "completion_profiles": [
                    (str(k), id(v), v.epoch, digest(v.data.model_dump(mode="json")))
                    for k, v in sorted(
                        getattr(engine, "_pdos_quality_completion_profiles", {}).items(),
                        key=lambda item: str(item[0]),
                    )
                ],
                "completion_profile_epochs": {
                    str(k): v
                    for k, v in getattr(
                        engine, "_pdos_quality_completion_profile_epochs", {}
                    ).items()
                },
                "roles": {
                    op: sorted(professional.OPERATION_ROLES.get(op, ()))
                    for op, *_ in commands.SPECS.values()
                },
                "ports": [
                    id(anchor_owner.read_anchor_from_actual_owner),
                    id(evidence.check_source),
                    id(evidence.source_basis),
                    id(professional.assess),
                    id(policy.assess),
                    id(read_stored_fact),
                ],
            }
        )

    def _authority(self, s, ctx, pid, origin, operation):
        at = datetime.now(UTC)
        value = deepcopy(
            professional.assess(
                s, ctx, pid, origin.scope.project_id, operation, origin.purpose, at, write=False
            )
        )
        require(
            value.get("scope") == origin.scope.model_dump(mode="json")
            and value.get("subject_id") == str(ctx.actor_id)
            and value.get("operation") == operation
            and value.get("purpose") == origin.purpose
        )
        require(
            value.get("authorized") is True and value.get("qualified") is True,
            "QUALIFICATION_REQUIRED",
            403,
        )
        require(value.get("fact_refs") and value.get("facts_revision"))
        require(
            origin.nature == "synthetic" or value.get("synthetic") is False, "NATURE_MISMATCH", 403
        )
        sources = []
        for ref in value["fact_refs"]:
            row = guards._one(
                s,
                ProfessionalFact,
                ProfessionalFact.tenant_id == ctx.tenant_id,
                ProfessionalFact.product_id == pid,
                ProfessionalFact.project_id == origin.scope.project_id,
                ProfessionalFact.subject_id == ctx.actor_id,
                ProfessionalFact.id == UUID(ref["id"]),
                ProfessionalFact.revision == ref["revision"],
            )
            sources.extend(
                evidence.refs_from_exact(
                    s,
                    ctx,
                    pid,
                    [DefinitionReference.model_validate(value) for value in row.sources],
                )
            )
        require(
            professional.authority_time_current(value, datetime.now(UTC)),
            "QUALIFICATION_REQUIRED",
            403,
        )
        return value, tuple(a.canonical_sources(sources))

    def _anchor(self, s, ctx, pid, saved):
        require(type(saved) is a.StableCapaAnchor)
        fresh = anchor_owner.read_anchor_from_actual_owner(
            s, ctx, pid, saved.origin.issue_id, saved.origin.ref
        )
        require(
            fresh.needs_lineage_owner is False
            and fresh.origin_descriptor.current.ref == saved.origin.ref,
            "FACT_LINEAGE_OWNER_REQUIRED",
        )
        require(
            candidate_anchor_restore._stable_anchor(fresh.anchor)
            == candidate_anchor_restore._stable_anchor(saved),
            "SOURCE_STALE",
            409,
        )
        return fresh.origin_descriptor.current.ref

    def _rule(self, s, ctx, pid, payload):
        require(
            self.publisher is not None and callable(getattr(self.publisher, "current", None)),
            "FACT_ISSUER_OWNER_REQUIRED",
        )
        stored = read_stored_fact(s, ctx, pid, "rule", payload.rule)
        require(stored.registry.state == "current_registered", "SOURCE_STALE", 409)
        row = guards._one(
            s,
            models.RuleFact,
            models.RuleFact.tenant_id == ctx.tenant_id,
            models.RuleFact.product_id == pid,
            models.RuleFact.id == payload.rule.id,
            models.RuleFact.revision == payload.rule.revision,
        )
        saved = a.StableCapaAnchor.model_validate(row.anchor_snapshot)
        self.publisher.current(s, ctx, pid, stored.fact)
        require(
            stored.fact.anchor_sha256 == saved.anchor_sha256
            and stored.fact.scope == saved.origin.scope
        )
        at = datetime.now(UTC)
        require(stored.fact.valid_from <= at < stored.fact.valid_until, "RULE_NOT_CURRENT", 409)
        return stored.fact, saved

    def _series(self, s, ctx, pid, kind, payload, saved, issuer, *, new_write):
        cls = models.RuleCurrent if kind == "rule" else models.ObservationCurrent
        where = [
            cls.tenant_id == ctx.tenant_id,
            cls.product_id == pid,
            cls.project_id == saved.origin.scope.project_id,
            cls.issue_id == payload.issue_id,
            cls.capa_id == payload.capa_id,
            cls.anchor_sha256 == saved.anchor_sha256,
        ]
        if kind == "rule":
            where += [cls.issuer_key == issuer.key, cls.external_id == payload.external_id]
        statement = select(cls)
        if kind == "observation":
            fact = models.ObservationFact
            statement = statement.join(
                fact,
                (fact.tenant_id == cls.tenant_id)
                & (fact.product_id == cls.product_id)
                & (fact.id == cls.fact_id)
                & (fact.revision == cls.fact_revision),
            )
            where += [
                fact.rule_fact_id == payload.rule.id,
                fact.rule_revision == payload.rule.revision,
                fact.rule_sha256 == payload.rule.sha256,
                fact.executor_id == ctx.actor_id,
            ]
        rows = list(
            s.scalars(
                statement.where(*where)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        require(len(rows) <= 1, "FACT_EXACT_CURRENT_REQUIRED")
        if payload.previous is None:
            require(not rows or not new_write, "VERSION_CONFLICT", 409)
            return None
        require(len(rows) == 1, "VERSION_CONFLICT", 409)
        row = rows[0]
        previous = read_stored_fact(s, ctx, pid, kind, payload.previous)
        current = previous.registry.current_ref
        require(
            current is not None
            and row.fact_id == current.id
            and row.fact_revision == current.revision,
            "VERSION_CONFLICT",
            409,
        )
        require(
            not new_write
            or (previous.registry.state == "current_registered" and current == payload.previous),
            "VERSION_CONFLICT",
            409,
        )
        return CurrentSeries(id=row.id, series_id=row.series_id, fact=current, epoch=row.epoch)

    def _original_record(self, s, ctx, pid, origin, rule, payload, record):
        """Compare original structured native material; never infer a measurement."""
        import json

        wanted = {
            "schema_version": "pdos-capa-observation-source-v1",
            "nature": origin.nature,
            "scope": origin.scope.model_dump(mode="json"),
            "issue_id": str(payload.issue_id),
            "capa_id": str(payload.capa_id),
            "purpose": origin.purpose,
            "rule": rule.ref.model_dump(mode="json"),
            "record": record.model_dump(mode="json"),
            "observed_from": payload.observed_from.isoformat(),
            "observed_until": payload.observed_until.isoformat(),
            "at": {
                "occurred_at": payload.at.occurred_at.isoformat(),
                "original_timezone": payload.at.original_timezone,
            },
        }
        # The source-position itself cannot occur in its own hashed line. Only
        # business fields are serialized; SourceRefs are checked independently.
        wanted["record"].pop("sources")
        matched = False
        for ref in record.sources:
            match = evidence.POSITION.fullmatch(ref.position) if ref.kind == "artifact" else None
            require(match is not None, "FACT_OBSERVATION_SOURCE_OWNER_REQUIRED")
            row = source_for(s, ctx, pid, ref.id, ref.revision)
            evidence.check_source(s, ctx, pid, ref)
            require(row.original_id is None, "FACT_OBSERVATION_SOURCE_OWNER_REQUIRED")
            try:

                def pairs(items):
                    value = {}
                    for key, item in items:
                        if key in value:
                            raise ValueError("duplicate")
                        value[key] = item
                    return value

                actual = json.loads(
                    row.content.splitlines()[int(match[1]) - 1],
                    object_pairs_hook=pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
                )
            except (ValueError, IndexError):
                continue
            if same_original_material(
                actual,
                wanted,
                clock_paths=(
                    ("record", "occurred_at"),
                    ("observed_from",),
                    ("observed_until",),
                    ("at", "occurred_at"),
                ),
            ):
                matched = True
        require(matched, "FACT_OBSERVATION_ORIGINAL_MISMATCH", 409)

    def read(self, s, ctx, pid, kind, payload, *, new_write):
        return self._read(s, ctx, pid, kind, payload, previous=None, new_write=new_write)

    def refresh(self, s, ctx, pid, kind, payload, previous, *, new_write):
        return self._read(s, ctx, pid, kind, payload, previous=previous, new_write=new_write)

    def _read(self, s, ctx, pid, kind, payload, *, previous, new_write):
        uow, caller, stamp = guards._uow(s), digest(vars(ctx)), self.runtime_stamp(s)
        require(
            isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
            "FORBIDDEN_SCOPE",
            403,
        )
        require(kind in {"rule", "observation", "review"})
        if kind == "review":
            require(
                self.review_owner is not None
                and callable(getattr(self.review_owner, "read", None)),
                "FACT_APPLICABILITY_OWNER_REQUIRED",
            )
            # The configured actual review owner must use participants_owner,
            # exact completed pair owners and all original sources. No fallback.
            value = self.review_owner.read(
                s, ctx, pid, payload, previous=previous, new_write=new_write
            )
            require(type(value) is FactWriteMaterial)
            guards._same_uow(s, uow, ctx, caller)
            require(stamp == self.runtime_stamp(s), "SOURCE_STALE", 409)
            return value
        if kind == "rule":
            require(
                self.publisher is not None and callable(getattr(self.publisher, "read", None)),
                "FACT_ISSUER_OWNER_REQUIRED",
            )
            published = self.publisher.read(s, ctx, pid, payload)
            require(type(published) is PublishedRuleMaterial)
            saved, issuer = published.anchor, published.issuer
            if previous is not None:
                require(saved == previous.anchor, "SOURCE_STALE", 409)
            extra_sources, inspection = published.sources, deepcopy(published.inspection)
            body_extra = {
                key: a.json_value(getattr(payload, key))
                for key in (
                    "policy_ref",
                    "method",
                    "criterion",
                    "sampling",
                    "rule_material",
                    "independence_material",
                    "valid_from",
                    "valid_until",
                )
            }
            body_extra.update(
                issuer=issuer.model_dump(mode="json"),
                policy_sha256=None,
                failures=a.json_value(saved.origin.issue.failures),
                actions=a.json_value(_action_bindings(saved)),
            )
            fact_deadline = min(instant(published.valid_until), payload.valid_until)
        else:
            rule, saved = self._rule(s, ctx, pid, payload)
            issuer, extra_sources = rule.issuer, rule.sources
            require(previous is None or saved == previous.anchor, "SOURCE_STALE", 409)
            targets = {target.key: target for target in rule.sampling.targets}
            require(
                all(key in targets for key in payload.target_keys),
                "FACT_OBSERVATION_TARGET_MISMATCH",
                409,
            )
            at = datetime.now(UTC)
            require(payload.at.occurred_at <= at, "FACT_TIME_INVALID", 409)
            for record in payload.records:
                self._original_record(s, ctx, pid, saved.origin, rule, payload, record)
            require(
                payload.at.source in {ref for record in payload.records for ref in record.sources},
                "FACT_OBSERVATION_EVENT_SOURCE_MISMATCH",
                409,
            )
            gaps = []
            if set(payload.target_keys) != set(targets):
                gaps.append("OBSERVATION_TARGETS_INCOMPLETE")
            if len(payload.records) < rule.sampling.minimum_records:
                gaps.append("OBSERVATION_SAMPLING_INCOMPLETE")
            if (
                payload.observed_from > rule.sampling.observation_from
                or payload.observed_until < rule.sampling.observation_until
            ):
                gaps.append("OBSERVATION_INTERVAL_INCOMPLETE")
            inspection = {
                "record_sources_verified": True,
                "missing": gaps,
                "observation_complete": None,
                "effectiveness": "indeterminate",
                "rule": payload.rule.model_dump(mode="json"),
            }
            body_extra = {
                "rule": payload.rule.model_dump(mode="json"),
                "issuer": issuer.model_dump(mode="json"),
                "targets": [targets[key].model_dump(mode="json") for key in payload.target_keys],
                "executor_id": str(ctx.actor_id),
                "observed_from": payload.observed_from.isoformat(),
                "observed_until": payload.observed_until.isoformat(),
                "at": payload.at.model_dump(mode="json"),
                "records": [
                    dict(r.model_dump(mode="json"), missing_fields=[]) for r in payload.records
                ],
                "coverage_sources": a.json_value(payload.coverage_sources),
                "sampling_material": {
                    "required": rule.sampling.model_dump(mode="json"),
                    "observed_records": len(payload.records),
                    "missing": gaps,
                    "current_complete": None,
                },
            }
            fact_deadline = rule.valid_until
        current = self._anchor(s, ctx, pid, saved)
        origin = saved.origin
        require(
            (origin.issue_id, origin.issue.capa.id) == (payload.issue_id, payload.capa_id),
            "FORBIDDEN_SCOPE",
            403,
        )
        require(
            origin.visibility == payload.visibility
            and (origin.visibility != "private" or origin.owner_id == ctx.actor_id),
            "FORBIDDEN_SCOPE",
            403,
        )
        authority, authority_sources = self._authority(s, ctx, pid, origin, commands.SPECS[kind][0])
        active_policy = deepcopy(
            policy.assess(s, ctx, pid, origin.scope.project_id, origin.purpose)
        )
        require(
            active_policy.get("nature") == origin.nature
            and active_policy.get("facts_revision")
            and policy.policy_time_current(active_policy, datetime.now(UTC))
        )
        if kind == "rule":
            body_extra["policy_sha256"] = digest(active_policy)
            require(
                a.SourceRef.model_validate(payload.policy_ref.model_dump(mode="json"))
                in a.canonical_sources(active_policy["sources"]),
                "FACT_POLICY_BINDING_MISMATCH",
                409,
            )
        common = {
            "previous": a.json_value(payload.previous),
            "scope": origin.scope.model_dump(mode="json"),
            "issue_id": str(origin.issue_id),
            "capa_id": str(origin.issue.capa.id),
            "purpose": origin.purpose,
            "anchor_sha256": saved.anchor_sha256,
            "requirement_sha256": digest(origin.issue.capa.requirement.model_dump(mode="json")),
            "nature": origin.nature,
            "owner_id": str(origin.owner_id),
            "visibility": origin.visibility,
            "kind": kind,
        }
        references = a.canonical_sources(
            (
                *saved.origin_sources,
                *extra_sources,
                *payload.sources,
                *authority_sources,
                *(a.SourceRef.model_validate(ref) for ref in active_policy["sources"]),
                *_all_source_refs(body_extra),
            )
        )
        reads = [
            *saved.origin_required_source_read_set,
            *authority["required_source_read_set"],
            *active_policy["required_source_read_set"],
        ]
        # Domain/report locators already have exact original-byte proofs from
        # anchor_owner; every new manual/record/policy line is checked directly.
        known = set(saved.origin_sources)
        for ref in references:
            if ref in known and evidence.POSITION.fullmatch(ref.position) is None:
                continue
            checked, _, private = evidence.check_source(s, ctx, pid, ref)
            reads.extend(checked)
            require(not private or origin.visibility == "private", "FORBIDDEN_SCOPE", 403)
        reads = evidence.merge_reads(reads)
        basis, private = evidence.source_basis(s, ctx, pid, reads)
        require(not private or origin.visibility == "private", "FORBIDDEN_SCOPE", 403)
        common.update(
            sources=a.json_value(references), required_source_read_set=reads, source_basis=basis
        )
        series = self._series(s, ctx, pid, kind, payload, saved, issuer, new_write=new_write)
        value = FactWriteMaterial(
            body_material={**common, **body_extra},
            anchor=saved,
            current_issue_version_id=current.id,
            current_issue_revision=current.revision,
            series=series,
            authority_snapshot=authority,
            policy_snapshot=active_policy,
            inspection=inspection,
            time_constraints=(fact_deadline,),
        )
        # A complete fresh pass runs in FactWriteHost after this read, and again
        # after consumption. Any later source IO invalidates the earlier basis.
        guards._same_uow(s, uow, ctx, caller)
        require(
            stamp == self.runtime_stamp(s)
            and datetime.now(UTC) < fact_deadline
            and professional.authority_time_current(authority, datetime.now(UTC))
            and policy.policy_time_current(active_policy, datetime.now(UTC)),
            "SOURCE_STALE",
            409,
        )
        return value
