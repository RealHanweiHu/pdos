"""Actual saved method/completion readers for the configured named-review host.

Business read-only in the caller's existing UOW; source readers retain their
normal locks. Neither a method status nor a completion/classification grants
effectiveness, independence, a professional role, or a consumption proof.
"""

# Common registry initializes before its domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

from pdos_next.service import Context, EVENTS, digest
from pdos_next.models import Receipt
from pdos_next.errors import DomainError
from pdos_next.domain.capa_effectiveness import anchor as a, paired
from pdos_next.domain.capa_effectiveness import fact_atom_storage as guards
from pdos_next.domain.capa_effectiveness import fact_commands as commands
from pdos_next.domain.capa_effectiveness import anchor_storage
from pdos_next.domain.capa_effectiveness.facts import (
    ActionFulfillment,
    PairApplicability,
    _action_bindings,
)
from pdos_next.domain.capa_effectiveness.named_review_owner import (
    ActualReviewApplicability,
    _checked_refs,
    _source,
    _sources,
)
from pdos_next.domain.capa_effectiveness.participants_owner import _Read
from pdos_next.domain.capa_effectiveness.fact_sources_owner import (
    _wire,
    _deadline,
    read_source_closure,
)
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.models import QualityIssueVersion, QualityIssueCurrent
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.quality_followup.evidence import verify_completion_line
from pdos_next.service import source_for
from pdos_next.domain.quality_followup.schemas import CompletionAssessment, CompletionFact
from pdos_next import quality_followup_bootstrap as classification
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff import service as methods
from pdos_next.domain.verification_handoff.models import (
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
)
from pdos_next.domain.verification_handoff.schemas import ActualMethodPreparePayload
from pdos_next.domain.sample_handoff import service as physical
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.service import authority_time_current
from pdos_next.schemas.verification.contracts import VerificationRequest


def require(value, code="INTEGRATION_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "实际方法、措施履行或当前权威依据尚不能完整核对。", status)


def instant(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    require(at.tzinfo is not None and at.utcoffset() is not None, "INVALID_TIME", 422)
    return at.astimezone(UTC)


def _port(owner, name):
    value = getattr(owner, name, None)
    return id(getattr(value, "__func__", value))


def _same_source(left, right):
    return _source(left) == _source(right)


def _source_keys(values):
    return {(v.kind, v.id, v.revision, v.position) for v in _sources(values)}


def _professional_current(s, ctx, pid, snapshot):
    """Check exact selected facts and their actual operation, without a capture TTL."""
    require(snapshot.get("fact_refs"))
    for ref in snapshot["fact_refs"]:
        guards._one(
            s,
            ProfessionalFact,
            ProfessionalFact.tenant_id == ctx.tenant_id,
            ProfessionalFact.product_id == pid,
            ProfessionalFact.project_id == UUID(snapshot["scope"]["project_id"]),
            ProfessionalFact.subject_id == UUID(snapshot["subject_id"]),
            ProfessionalFact.id == UUID(ref["id"]),
            ProfessionalFact.revision == ref["revision"],
        )
    require(authority_time_current(snapshot, datetime.now(UTC)), "SOURCE_STALE", 409)
    return ()


@dataclass(frozen=True)
class ActualActionAttestation:
    """Output of an explicitly configured implementation/fulfillment owner.

    A caller cannot install that owner or pass this DTO into read(). The owner
    must independently read and refresh its own actual implementation evidence.
    Investigation classification alone never creates this conclusion.
    """

    session: object
    caller: Context
    product_id: UUID
    anchor_sha256: str
    action: object
    classification: str
    conclusion: str
    owner_refs: tuple
    owner_material: dict
    reads: tuple
    checked_at: datetime
    valid_until: datetime | None
    time_constraints: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class ActionRead:
    value: ActionFulfillment
    owner_material: dict
    sources: tuple
    reads: tuple
    valid_until: datetime | None
    missing: tuple[str, ...]
    time_constraints: tuple[datetime, ...] = ()


class ActualActionFulfillmentOwner:
    """Read actual completed action and current controlled classification.

    A saved nine-field completion proves that occurrence only. The current
    synthetic investigation publisher can prove classification, not physical
    remediation or fulfillment. Non-unknown fulfillment needs the separate
    explicit implementation_owner read/refresh port.
    """

    def __init__(self, *, implementation_owner=None, epoch=1):
        require(type(epoch) is int and epoch > 0)
        self.implementation_owner, self.epoch = implementation_owner, epoch

    def runtime_stamp(self, s):
        engine = s.get_bind()
        return digest(
            {
                "epoch": self.epoch,
                "implementation": [
                    id(self.implementation_owner),
                    getattr(self.implementation_owner, "epoch", None),
                    _port(self.implementation_owner, "read"),
                    _port(self.implementation_owner, "refresh"),
                ],
                "classification_profiles": [
                    (str(k), id(v), v.epoch, digest(v.data.model_dump(mode="json")))
                    for k, v in sorted(
                        getattr(engine, "_pdos_quality_completion_profiles", {}).items(),
                        key=lambda x: str(x[0]),
                    )
                ],
                "classification_epochs": {
                    str(k): v
                    for k, v in getattr(
                        engine, "_pdos_quality_completion_profile_epochs", {}
                    ).items()
                },
                "classification_ports": [
                    id(classification._classification),
                    id(classification._active),
                ],
            }
        )

    def read(self, s, ctx, pid, selection, *, anchor, candidate, rule, observations):
        origin = anchor.origin
        captured, caller, stamp = guards._uow(s), digest(vars(ctx)), self.runtime_stamp(s)
        with s.no_autoflush:
            guards._acl(s, ctx, pid)
            project = anchor_storage._project(s, ctx, pid, origin.scope.project_id)
            reader = _Read(s, ctx, pid, origin)
            raw = reader.one(
                QualityIssueVersion.__table__, id=origin.ref.id, revision=origin.ref.revision
            )
            current = reader.one(QualityIssueCurrent.__table__, issue_id=origin.issue_id)
            require(
                (current["issue_version_id"], current["issue_revision"])
                == (origin.ref.id, origin.ref.revision),
                "FACT_LINEAGE_OWNER_REQUIRED",
            )
            require(
                raw["issue_snapshot"] == origin.issue.model_dump(mode="json")
                and raw["snapshot_sha256"] == origin.ref.snapshot_sha256
                and raw["operation"] == "quality.capa.actions.complete",
                "ACTION_ORIGIN_MISMATCH",
                409,
            )
            reader.group(raw, "quality_issue", origin.writer_id, EVENTS[raw["operation"]])
            binding = next(
                (v for v in _action_bindings(anchor) if v.action_id == selection.action_id), None
            )
            action = next(
                (v for v in origin.issue.capa.actions if v.id == selection.action_id), None
            )
            require(
                binding is not None and action is not None and action.completion is not None,
                "ACTION_COMPLETION_OWNER_REQUIRED",
            )
            completion = action.completion
            require(
                binding.completion_sha256 == digest(completion.model_dump(mode="json"))
                and binding.completed_at == completion.at
                and completion.executor_id == action.executor_id,
                "ACTION_COMPLETION_MISMATCH",
                409,
            )
            records = raw["source_basis"].get("completion_observations", [])
            matches = [
                v
                for v in records
                if isinstance(v, dict) and v.get("fact", {}).get("action_id") == str(action.id)
            ]
            require(len(matches) == 1, "ACTION_COMPLETION_OBSERVATION_MISSING")
            observed = CompletionFact.model_validate(matches[0]["fact"])
            require(
                (
                    observed.issue_id,
                    observed.capa_id,
                    observed.action_id,
                    observed.executor_id,
                    observed.purpose,
                    observed.text,
                    observed.occurred_at,
                    observed.original_timezone,
                )
                == (
                    origin.issue_id,
                    origin.issue.capa.id,
                    action.id,
                    action.executor_id,
                    origin.purpose,
                    completion.text,
                    completion.at.occurred_at,
                    completion.at.original_timezone,
                )
                and observed.occurred_at <= instant(matches[0]["received_at"]) <= raw["created_at"],
                "ACTION_COMPLETION_MISMATCH",
                409,
            )
            actual_event, event_reads, event_basis = self._completion(
                s, ctx, pid, origin, completion
            )
            require(actual_event == observed, "ACTION_COMPLETION_MISMATCH", 409)
            sources = [*completion.evidence, completion.at.source]
            reads, bounds, missing = list(event_reads), [rule.valid_until], set()
            material = {
                "action_runtime": stamp,
                "raw_origin": raw,
                "current": current,
                "completion": completion,
                "observation": matches[0],
                "completion_source_basis": event_basis,
                "group": reader.rows,
            }
            kind = "unknown"
            assessments = raw["source_basis"].get("completion_assessments", [])
            selected = [v for v in assessments if v.get("action_id") == str(action.id)]
            require(len(selected) <= 1, "ACTION_CLASSIFICATION_AMBIGUOUS", 409)
            if selected:
                saved = CompletionAssessment.model_validate(selected[0])
                require(
                    (
                        saved.scope,
                        saved.issue_id,
                        saved.capa_id,
                        saved.action_id,
                        saved.executor_id,
                        saved.purpose,
                        saved.action_sha256,
                        saved.completion_sha256,
                        _source(saved.event_source),
                        saved.nature,
                    )
                    == (
                        origin.scope,
                        origin.issue_id,
                        origin.issue.capa.id,
                        action.id,
                        action.executor_id,
                        origin.purpose,
                        binding.action_sha256,
                        binding.completion_sha256,
                        _source(completion.at.source),
                        origin.nature,
                    )
                    and selected[0].get("proof_sha256")
                    == digest({k: v for k, v in selected[0].items() if k != "proof_sha256"}),
                    "ACTION_CLASSIFICATION_MISMATCH",
                    409,
                )
                material["saved_classification"] = deepcopy(selected[0])
                sources.extend(saved.sources)
                reads.extend(saved.required_source_read_set)
                profile = getattr(s.get_bind(), "_pdos_quality_completion_profiles", {}).get(
                    (ctx.tenant_id, pid, origin.scope.project_id)
                )
                if (
                    saved.classification == "investigation"
                    and origin.nature == "synthetic"
                    and profile is not None
                ):
                    classification._active(s.get_bind(), profile)
                    entries = [
                        v
                        for v in profile.data.entries
                        if (
                            v.issue_id,
                            v.capa_id,
                            v.action_id,
                            v.executor_id,
                            v.purpose,
                            v.action_sha256,
                        )
                        == (
                            origin.issue_id,
                            origin.issue.capa.id,
                            action.id,
                            action.executor_id,
                            origin.purpose,
                            binding.action_sha256,
                        )
                    ]
                    require(
                        len(entries) == 1
                        and selected[0].get("profile_epoch") == profile.epoch
                        and selected[0].get("profile_sha256")
                        == digest(profile.data.model_dump(mode="json")),
                        "SOURCE_STALE",
                        409,
                    )
                    current_reads, source_basis = classification._classification(
                        s, ctx, pid, entries[0], profile
                    )
                    require(
                        _wire(source_basis) == selected[0].get("classification_source_basis"),
                        "SOURCE_STALE",
                        409,
                    )
                    require(entries[0].valid_until > datetime.now(UTC), "SOURCE_STALE", 409)
                    reads.extend(current_reads)
                    bounds.append(entries[0].valid_until)
                    material["current_classification"] = {
                        "entry": entries[0],
                        "source_basis": source_basis,
                        "profile_epoch": profile.epoch,
                        "profile_sha256": selected[0]["profile_sha256"],
                    }
                    kind = "investigation"
                else:
                    missing.add("CURRENT_ACTION_CLASSIFICATION_OWNER_REQUIRED")
            else:
                missing.add("CURRENT_ACTION_CLASSIFICATION_OWNER_REQUIRED")
            conclusion = "unknown"
            port = self.implementation_owner
            if selection.conclusion != "unknown":
                require(
                    port is not None
                    and all(callable(getattr(port, k, None)) for k in ("read", "refresh")),
                    "ACTION_FULFILLMENT_OWNER_REQUIRED",
                )
                kwargs = dict(
                    anchor=anchor,
                    candidate=candidate,
                    rule=rule,
                    observations=observations,
                    action=action,
                    completion=completion,
                    classification_material=deepcopy(_wire(material)),
                )
                proof = port.read(s, ctx, pid, selection, **kwargs)
                self._check(s, ctx, pid, anchor, binding, selection, proof)
                late = port.refresh(s, ctx, pid, selection, proof, **kwargs)
                self._check(s, ctx, pid, anchor, binding, selection, late)
                require(
                    _wire(proof.owner_material) == _wire(late.owner_material)
                    and proof.owner_refs == late.owner_refs
                    and proof.reads == late.reads
                    and proof.valid_until == late.valid_until
                    and proof.time_constraints == late.time_constraints
                    and proof.classification == late.classification,
                    "SOURCE_STALE",
                    409,
                )
                kind, conclusion = proof.classification, proof.conclusion
                if kind == "formal_change":
                    # Current formal classification comes from the configured
                    # live owner after both exact proof checks and full refresh
                    # equality. The saved completion label alone cannot clear it.
                    missing.discard("CURRENT_ACTION_CLASSIFICATION_OWNER_REQUIRED")
                material["fulfillment"] = proof.owner_material
                sources.extend(proof.owner_refs)
                reads.extend(proof.reads)
                bounds.append(proof.valid_until)
                bounds.extend(proof.time_constraints)
            else:
                missing.add("ACTION_FULFILLMENT_UNDETERMINED")
            sources = a.canonical_sources(sources)
            require(
                _source_keys(selection.sources) <= _source_keys(sources),
                "ACTION_SOURCE_MISMATCH",
                409,
            )
            reads = a.canonical_reads(
                (
                    *reader.reads,
                    *reads,
                    *(
                        a.SourceRead(artifact_id=v.id, expected_revision=v.revision)
                        for v in sources
                        if v.kind == "artifact"
                    ),
                )
            )
            closure = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                boundaries=bounds,
            )
            reader.finish()
            late_event, late_reads, late_basis = self._completion(s, ctx, pid, origin, completion)
            require(
                late_event == actual_event
                and late_reads == event_reads
                and late_basis == event_basis,
                "SOURCE_STALE",
                409,
            )
            require(
                anchor_storage._project(s, ctx, pid, origin.scope.project_id) == project
                and self.runtime_stamp(s) == stamp,
                "SOURCE_STALE",
                409,
            )
            final = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                expected_basis=a.canonical_basis(closure.source_basis, reads),
                boundaries=bounds,
            )
            require(
                final.material_sha256 == closure.material_sha256 and self.runtime_stamp(s) == stamp,
                "SOURCE_STALE",
                409,
            )
            checked, time_constraints = _deadline(
                s, ctx, pid, (*bounds, final.valid_until, *final.time_constraints)
            )
            guards._same_uow(s, captured, ctx, caller)
            value = ActionFulfillment(
                action=binding,
                classification=kind,
                conclusion=conclusion,
                reason=selection.reason,
                owner_refs=tuple(_source(v) for v in selection.sources),
                owner_material={
                    **_wire(material),
                    "source_basis": closure.source_basis,
                    "missing": sorted(missing),
                },
            )
            result = ActionRead(
                value,
                _wire(material),
                sources,
                reads,
                None,
                tuple(sorted(missing)),
                time_constraints,
            )
            require(
                all(datetime.now(UTC) < value for value in time_constraints), "SOURCE_STALE", 409
            )
            guards._same_uow(s, captured, ctx, caller)
            return result

    @staticmethod
    def _completion(s, ctx, pid, origin, completion):
        source = completion.at.source
        reads, basis, private = evidence.check_source(s, ctx, pid, source)
        require(origin.visibility != "category" or not private, "FORBIDDEN_SCOPE", 403)
        match = evidence.POSITION.fullmatch(source.position)
        require(match is not None and source.kind == "artifact", "ACTION_COMPLETION_OWNER_REQUIRED")
        row = source_for(s, ctx, pid, source.id, source.revision)
        fact = verify_completion_line(
            row.content.splitlines()[int(match[1]) - 1],
            origin.issue,
            origin.purpose,
            completion,
            completion.executor_id,
            datetime.now(UTC),
        )
        return fact, reads, basis

    @staticmethod
    def _check(s, ctx, pid, anchor, binding, selection, proof):
        require(
            type(proof) is ActualActionAttestation
            and proof.session is s
            and proof.caller is ctx
            and proof.product_id == pid
            and proof.anchor_sha256 == anchor.anchor_sha256
            and proof.action == binding,
            "ACTION_FULFILLMENT_OWNER_REQUIRED",
        )
        require(
            proof.classification in {"investigation", "formal_change"}
            and proof.conclusion == selection.conclusion
            and _sources(proof.owner_refs) == _sources(selection.sources)
            and bool(proof.owner_material),
            "ACTION_FULFILLMENT_MISMATCH",
            409,
        )
        require(
            proof.checked_at <= datetime.now(UTC)
            and (proof.valid_until is None or datetime.now(UTC) < proof.valid_until)
            and all(datetime.now(UTC) < value for value in proof.time_constraints),
            "SOURCE_STALE",
            409,
        )

    def refresh(self, s, ctx, pid, selection, previous, **kwargs):
        actual = self.read(s, ctx, pid, selection, **kwargs)
        require(
            actual.value == previous.value
            and actual.owner_material == previous.owner_material
            and actual.sources == previous.sources
            and actual.reads == previous.reads
            and actual.valid_until == previous.valid_until
            and actual.time_constraints == previous.time_constraints,
            "SOURCE_STALE",
            409,
        )
        return actual


class ActualApplicabilityOwner:
    """Real current actual-method owner, with separate action fulfillment owner."""

    def __init__(self, fact_owner, *, paired_owner=None, action_owner=None, epoch=1):
        require(type(epoch) is int and epoch > 0)
        self.fact_owner, self.paired_owner, self.epoch = fact_owner, paired_owner, epoch
        self.action_owner = (
            action_owner if action_owner is not None else ActualActionFulfillmentOwner()
        )

    def runtime_stamp(self, s):
        require(
            all(
                callable(getattr(self.fact_owner, k, None))
                for k in ("_rule", "_anchor", "_authority", "runtime_stamp")
            )
        )
        return digest(
            {
                "epoch": self.epoch,
                "fact_owner": [id(self.fact_owner), self.fact_owner.runtime_stamp(s)],
                "pair": [
                    id(self.paired_owner),
                    getattr(self.paired_owner, "epoch", None),
                    *(_port(self.paired_owner, k) for k in ("read", "refresh", "attest")),
                ],
                "action": [id(self.action_owner), self.action_owner.runtime_stamp(s)],
                "methods": [
                    id(methods._actual_check),
                    id(methods._actual_binding),
                    id(physical._chain),
                    id(front._recheck),
                    id(policy.assess),
                    id(read_source_closure),
                ],
            }
        )

    def _pair(self, s, ctx, pid, supplied, anchor):
        require(
            isinstance(supplied, tuple)
            and len(supplied) == 2
            and type(supplied[0]) is paired.ServerPairRead,
            "LIVE_PAIRED_OWNER_REQUIRED",
        )
        raw, prior = supplied
        require(
            raw.binding.scope == anchor.origin.scope
            and raw.binding.caller_id == ctx.requester_id
            and raw.binding.purpose == anchor.origin.purpose,
            "FACT_REVIEW_PAIR_SCOPE_MISMATCH",
            409,
        )
        reader = self.paired_owner
        require(
            reader is not None
            and all(callable(getattr(reader, k, None)) for k in ("read", "refresh", "attest")),
            "LIVE_PAIRED_OWNER_REQUIRED",
        )
        actual = paired.read_paired_formal_output(
            s, ctx, pid, raw.binding.output_ref, at=datetime.now(UTC), reader=reader, write=False
        )
        require(
            actual.structure is not None
            and actual.host_gate is not None
            and not actual.host_gate.needs_review
            and not actual.missing
            and actual.structure.meaning == "performed",
            "LIVE_PAIRED_OWNER_REQUIRED",
        )
        inspected = paired.verify_paired_material(raw.binding, raw.material, at=datetime.now(UTC))
        require(
            inspected.proof is not None
            and actual.structure == inspected.proof
            and type(prior) is paired.PairedReadOutcome
            and prior.structure == actual.structure,
            "SOURCE_STALE",
            409,
        )
        return actual

    def _method(self, reader, selection, raw_pair, rule):
        s, ctx, pid = reader.s, reader.ctx, reader.pid
        request = raw_pair.material.request_after.snapshot
        mapping = selection.mapping
        require(
            mapping.run.kind == "verification_run"
            and (mapping.run.id, mapping.run.revision)
            == (raw_pair.material.run_after.ref.id, raw_pair.material.run_after.ref.revision),
            "FACT_REVIEW_PAIR_SCOPE_MISMATCH",
            409,
        )
        sample = next((v for v in request.samples if v.id == mapping.sample_id), None)
        require(
            sample is not None
            and sample.revision == mapping.sample_revision
            and (sample.actual_configuration.id, sample.actual_configuration.revision)
            == (mapping.actual_configuration_id, mapping.actual_configuration_revision),
            "SOURCE_CHANGED",
            409,
        )
        current = reader.one(
            ActualMethodCurrent.__table__,
            request_id=request.id,
            sample_id=sample.id,
            item_id=mapping.item_id,
        )
        row = reader.one(
            ActualMethodApplicability.__table__,
            id=current["assessment_id"],
            revision=current["assessment_revision"],
        )
        item = next((v for v in request.items if v.id == mapping.item_id), None)
        require(item is not None, "ACTUAL_METHOD_UNKNOWN", 409)
        chain = physical._chain(s, ctx, pid, sample.id, write=False)
        inspected = physical._physical(chain)
        require(
            chain["sample"].revision == sample.revision
            and chain["sample"].cavity == sample.cavity
            and chain["build"].id == sample.build_id,
            "SOURCE_CHANGED",
            409,
        )
        reader.reads.extend(a.SourceRead.model_validate(v) for v in chain["reads"])
        saved = SimpleNamespace(**deepcopy(row))
        methods._actual_check(s, ctx, pid, request, sample, inspected, saved, positive=False)
        batch = reader.one(ActualMethodBatch.__table__, id=row["batch_id"])
        payload = ActualMethodPreparePayload.model_validate(batch["input_snapshot"])
        semantic = methods.semantic(payload)
        require(
            batch["input_snapshot"] == semantic
            and batch["snapshot_sha256"] == digest(semantic)
            and batch["intent_digest"]
            == digest(
                {
                    "operation": "verification.actual_method.prepare",
                    "actor": batch["owner_id"],
                    "payload": semantic,
                }
            )
            and batch["revision"] == 1
            and batch["status"] == "prepared"
            and str(row["id"]) in batch["assessment_ids"]
            and len(batch["assessment_ids"]) == len(set(batch["assessment_ids"])),
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        require(
            all(
                row[k] == batch[k]
                for k in (
                    "request_id",
                    "request_version_id",
                    "request_revision",
                    "project_id",
                    "owner_id",
                    "visibility",
                    "sources",
                    "required_source_read_set",
                    "source_basis",
                    "authority_snapshot",
                    "created_at",
                )
            ),
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        selected = [
            v for v in payload.assessments if v.sample.id == sample.id and v.item_id == item.id
        ]
        require(
            len(selected) == 1
            and selected[0].sample == sample
            and selected[0].status == row["status"]
            and selected[0].conditions == tuple(row["assessment_snapshot"]["conditions"])
            and selected[0].reason == row["assessment_snapshot"]["reason"]
            and sorted((v.model_dump(mode="json") for v in selected[0].sources), key=digest)
            == sorted(row["assessment_snapshot"]["sources"], key=digest),
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        require(
            row["assessment_snapshot"]
            == {
                "scope": request.scope.model_dump(mode="json"),
                "purpose": request.purpose,
                "build": request.build.model_dump(mode="json"),
                "sample": sample.model_dump(mode="json"),
                "fixed_item": item.model_dump(mode="json"),
                "actual_configuration": inspected["actual_configuration"],
                "reviewer_id": str(row["owner_id"]),
                "status": row["status"],
                "conditions": list(selected[0].conditions),
                "reason": selected[0].reason,
                "sources": row["assessment_snapshot"]["sources"],
            },
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        parent = reader.one(
            FormalVerificationRequest.__table__,
            id=row["request_version_id"],
            revision=row["request_revision"],
        )
        require(
            parent["request_id"] == request.id
            and parent["snapshot_sha256"] == digest(parent["request_snapshot"])
            and VerificationRequest.model_validate(parent["request_snapshot"]).items
            == request.items,
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        receipt_ref = reader.group(
            {**batch, "operation": "verification.actual_method.prepare"},
            "verification_actual_method",
            batch["owner_id"],
            EVENTS["verification.actual_method.prepare"],
        )
        receipt = next(
            v["value"] for v in reversed(reader.rows) if v["table"] == Receipt.__tablename__
        )
        require(
            receipt["result"].get("status") == batch["status"], "ACTUAL_METHOD_BATCH_MISMATCH", 409
        )
        require(
            batch["id"]
            == uuid5(NAMESPACE_URL, f"pdos-verification-handoff:{receipt['command_id']}:batch")
            and row["id"]
            == uuid5(
                NAMESPACE_URL,
                f"pdos-verification-handoff:{receipt['command_id']}:pair:{sample.id}:{item.id}",
            ),
            "ACTUAL_METHOD_BATCH_MISMATCH",
            409,
        )
        criterion = item.criterion.source if item.criterion is not None else item.criterion_source
        require(
            _same_source(selection.method, item.method)
            and _same_source(selection.criterion, criterion),
            "ACTUAL_METHOD_REFERENCE_MISMATCH",
            409,
        )
        require(
            _same_source(item.method, rule.method) and _same_source(criterion, rule.criterion),
            "RULE_METHOD_CRITERION_MISMATCH",
            409,
        )
        require(selection.conclusion == row["status"], "ACTUAL_METHOD_CONCLUSION_MISMATCH", 409)
        actual_sources = (
            a.canonical_sources(
                (
                    *reader.source_refs(row["sources"]),
                    *reader.source_refs(row["assessment_snapshot"]["sources"]),
                    item.method,
                    criterion,
                )
            )
            if item.method and criterion
            else a.canonical_sources(reader.source_refs(row["sources"]))
        )
        require(
            _source_keys(selection.sources) <= _source_keys(actual_sources),
            "ACTUAL_METHOD_SOURCE_MISMATCH",
            409,
        )
        if row["status"] == "applicable":
            require(item.method is not None and criterion is not None, "ACTUAL_METHOD_UNKNOWN", 409)
        reader.refs.extend(actual_sources)
        bounds = _professional_current(s, ctx, pid, row["authority_snapshot"])
        value = PairApplicability(
            mapping=mapping,
            method=item.method,
            criterion=criterion,
            conclusion=row["status"],
            reason=selection.reason,
            sources=tuple(_source(v) for v in selection.sources),
        )
        material = {
            "current": current,
            "actual": row,
            "batch": batch,
            "parent": parent,
            "physical": inspected,
            "receipt_source": receipt_ref,
        }
        return value, material, bounds, (request, sample, inspected, saved)

    def read(self, s, ctx, pid, payload, *, anchor, candidate, pairs, observations):
        require(type(payload) is commands.NamedReviewPayload and type(anchor) is a.StableCapaAnchor)
        require(
            isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
            "FORBIDDEN_SCOPE",
            403,
        )
        origin = anchor.origin
        require(
            origin.scope.tenant_id == ctx.tenant_id
            and origin.scope.product_id == pid
            and candidate.binding.mappings == tuple(v.mapping for v in payload.pair_applicability)
            and candidate.body.stable_anchor == anchor,
            "FACT_APPLICABILITY_SCOPE_MISMATCH",
            409,
        )
        captured, caller, stamp = guards._uow(s), digest(vars(ctx)), self.runtime_stamp(s)
        with s.no_autoflush:
            guards._acl(s, ctx, pid)
            project = anchor_storage._project(s, ctx, pid, origin.scope.project_id)
            rule, saved = self.fact_owner._rule(s, ctx, pid, payload)
            require(
                saved == anchor and self.fact_owner._anchor(s, ctx, pid, anchor) == origin.ref,
                "SOURCE_STALE",
                409,
            )
            authority, professional_sources = self.fact_owner._authority(
                s, ctx, pid, origin, commands.REVIEW_OPERATION
            )
            policy_value = deepcopy(
                policy.assess(s, ctx, pid, origin.scope.project_id, origin.purpose)
            )
            require(
                policy_value.get("nature") == origin.nature
                and policy.policy_time_current(policy_value, datetime.now(UTC)),
                "CURRENT_POLICY_OWNER_REQUIRED",
            )
            live = tuple(self._pair(s, ctx, pid, v, anchor) for v in pairs)
            indexed = {
                (v[0].material.run_after.ref.id, v[0].material.run_after.ref.revision): v[0]
                for v in pairs
            }
            require(len(indexed) == len(pairs), "FACT_REVIEW_PAIR_SCOPE_MISMATCH", 409)
            reader = _Read(s, ctx, pid, origin)
            values, material, checks = [], [], []
            bounds = [
                rule.valid_until,
                *_professional_current(s, ctx, pid, authority),
                *(v.host_gate.valid_until for v in live),
                *(value for v in live for value in v.host_gate.time_constraints),
            ]
            for selected in payload.pair_applicability:
                raw = indexed.get((selected.mapping.run.id, selected.mapping.run.revision))
                require(raw is not None, "FACT_REVIEW_PAIR_SCOPE_MISMATCH", 409)
                value, raw_material, until, check = self._method(reader, selected, raw, rule)
                values.append(value)
                material.append(raw_material)
                bounds.extend(until)
                checks.append(check)
            required = _action_bindings(anchor)
            require(
                {v.action_id for v in payload.action_fulfillment}
                == {v.action_id for v in required},
                "FACT_REVIEW_ACTION_COVERAGE_MISMATCH",
                409,
            )
            actions = tuple(
                self.action_owner.read(
                    s,
                    ctx,
                    pid,
                    selected,
                    anchor=anchor,
                    candidate=candidate,
                    rule=rule,
                    observations=observations,
                )
                for selected in payload.action_fulfillment
            )
            conclusions = tuple(v.conclusion for v in values) + tuple(
                v.value.conclusion for v in actions
            )
            overall = (
                "not_applicable"
                if "not_applicable" in conclusions
                else (
                    "applicable"
                    if conclusions and all(v == "applicable" for v in conclusions)
                    else "unknown"
                )
            )
            require(payload.conclusion == overall, "FACT_APPLICABILITY_CONCLUSION_MISMATCH", 409)
            sources = a.canonical_sources(
                (
                    *anchor.origin_sources,
                    *rule.sources,
                    *professional_sources,
                    *(a.SourceRef.model_validate(v) for v in policy_value["sources"]),
                    *reader.refs,
                    *_checked_refs(s, ctx, pid, material),
                    *(v for item in actions for v in item.sources),
                )
            )
            reads = a.canonical_reads(
                (
                    *anchor.origin_required_source_read_set,
                    *rule.required_source_read_set,
                    *authority["required_source_read_set"],
                    *policy_value["required_source_read_set"],
                    *reader.reads,
                    *candidate.inspection.required_source_read_set,
                    *(v for item in actions for v in item.reads),
                    *(v for pair in live for v in pair.structure.required_source_read_set),
                    *(
                        a.SourceRead(artifact_id=v.id, expected_revision=v.revision)
                        for v in sources
                        if v.kind == "artifact"
                    ),
                )
            )
            bounds.extend(v.valid_until for v in actions)
            bounds.extend(value for v in actions for value in v.time_constraints)
            closure = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                expected_basis=anchor.origin_source_basis,
                boundaries=bounds,
            )
            for request, sample, inspected, saved in checks:
                methods._actual_check(
                    s, ctx, pid, request, sample, inspected, saved, positive=False
                )
            late_actions = tuple(
                self.action_owner.refresh(
                    s,
                    ctx,
                    pid,
                    selected,
                    old,
                    anchor=anchor,
                    candidate=candidate,
                    rule=rule,
                    observations=observations,
                )
                for selected, old in zip(payload.action_fulfillment, actions, strict=True)
            )
            for supplied, old in zip(pairs, live, strict=True):
                late = self._pair(s, ctx, pid, supplied, anchor)
                require(
                    late.structure == old.structure
                    and late.host_gate.stamps == old.host_gate.stamps
                    and late.host_gate.valid_until == old.host_gate.valid_until
                    and late.host_gate.time_constraints == old.host_gate.time_constraints
                    and late.host_gate.needs_review == old.host_gate.needs_review,
                    "SOURCE_STALE",
                    409,
                )
            require(
                self.fact_owner._rule(s, ctx, pid, payload) == (rule, anchor)
                and self.fact_owner._anchor(s, ctx, pid, anchor) == origin.ref
                and self.fact_owner._authority(s, ctx, pid, origin, commands.REVIEW_OPERATION)
                == (authority, professional_sources)
                and policy.assess(s, ctx, pid, origin.scope.project_id, origin.purpose)
                == policy_value,
                "SOURCE_STALE",
                409,
            )
            reader.finish()
            require(
                anchor_storage._project(s, ctx, pid, origin.scope.project_id) == project,
                "SOURCE_STALE",
                409,
            )
            final = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                expected_basis=a.canonical_basis(closure.source_basis, reads),
                boundaries=bounds,
            )
            require(
                final.material_sha256 == closure.material_sha256 and self.runtime_stamp(s) == stamp,
                "SOURCE_STALE",
                409,
            )
            checked, time_constraints = _deadline(
                s, ctx, pid, (*bounds, final.valid_until, *final.time_constraints)
            )
            guards._same_uow(s, captured, ctx, caller)
            result = ActualReviewApplicability(
                session=s,
                caller=ctx,
                product_id=pid,
                anchor_sha256=anchor.anchor_sha256,
                candidate_ref=candidate.ref,
                conclusion=overall,
                pairs=tuple(values),
                actions=tuple(v.value for v in late_actions),
                owner_material={
                    "methods": _wire(material),
                    "rows": _wire(reader.rows),
                    "actions": [_wire(v.owner_material) for v in actions],
                    "authority": authority,
                    "policy": policy_value,
                    "source_basis": final.source_basis,
                    "pair_stamps": [
                        [
                            {"kind": stamp.kind, "basis_sha256": stamp.basis_sha256}
                            for stamp in v.host_gate.stamps
                        ]
                        for v in live
                    ],
                    "runtime": stamp,
                },
                sources=sources,
                reads=reads,
                checked_at=checked,
                valid_until=None,
                time_constraints=time_constraints,
            )
            require(
                all(datetime.now(UTC) < value for value in time_constraints), "SOURCE_STALE", 409
            )
            guards._same_uow(s, captured, ctx, caller)
            return result

    def refresh(self, s, ctx, pid, payload, previous, **kwargs):
        require(
            type(previous) is ActualReviewApplicability
            and previous.session is s
            and previous.caller is ctx,
            "FACT_APPLICABILITY_OWNER_REQUIRED",
        )
        actual = self.read(s, ctx, pid, payload, **kwargs)
        require(
            actual.owner_material == previous.owner_material
            and actual.pairs == previous.pairs
            and actual.actions == previous.actions
            and actual.sources == previous.sources
            and actual.reads == previous.reads
            and actual.valid_until == previous.valid_until
            and actual.time_constraints == previous.time_constraints,
            "SOURCE_STALE",
            409,
        )
        return actual
