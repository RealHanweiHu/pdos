"""Actual saved participant material; no professional/independence authorization.

Bounded Core reads use the real caller's active Session/UOW. Fixed historical
Run versions remain fixed; new selections must match actual Current. No client
participant list, owner Context, DML, new transaction or seven-gate attestation.
"""

from pdos_next.database import category_for_product


# Initialize the common registry before its domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from pydantic import ValidationError

from pdos_next.service import Context, EVENTS, digest
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Grant,
    Outbox,
    Receipt,
    RequestKey,
    Run,
    UploadedOriginal,
)
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
    VerificationLaunchFact,
)
from pdos_next.domain.verification_results.models import (
    MeasurementRecord,
    MeasurementImportCapture,
    TestResultActionFact,
)
from pdos_next.schemas.verification.contracts import SourceRef
from . import anchor as a
from . import anchor_storage as origin_storage
from . import fact_atom_storage as guards
from .fact_registry_storage import read_stored_fact
from .facts import FactRef, Participant
from .paired import PairBinding
from pdos_next.schemas.verification.contracts import TestRun


@dataclass(frozen=True)
class ParticipantRead:
    participants: tuple[Participant, ...]
    owner_material: dict
    material_sha256: str
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[a.SourceRead, ...]
    checked_at: datetime
    valid_until: datetime | None
    source_basis: list
    missing: tuple[str, ...]
    needs_lineage_owner: bool
    current_evidence_authorized: bool = False
    same_uow_consumption_attested: bool = False
    time_constraints: tuple[datetime, ...] = ()


def _require(value, code="PARTICIPANT_OWNER_MISSING", *, status=503):
    if not value:
        raise DomainError(code, "参与者的固定实绩、范围或完整保存组不能核对。", status)


class _Read:
    """Per-call raw reader, not a cached owner authorization."""

    def __init__(self, s, ctx, pid, origin):
        self.s, self.ctx, self.pid, self.origin = s, ctx, pid, origin
        self.uow, self.caller = guards._uow(s), digest(vars(ctx))
        self.rows, self.tracked, self.people, self.refs, self.reads = [], [], {}, [], []
        self._request_binding_statements = set()
        self.missing = set()

    def source_refs(self, sources):
        """Normalize both saved source contracts without rewriting raw row material.

        Exact Artifact references require the existing current source/line reader;
        their quoted substring is not the full-line digest used by SourceRef.
        """
        _require(isinstance(sources, (list, tuple)), "PARTICIPANT_SOURCE_SHAPE_INVALID")
        refs = []
        for value in sources:
            raw = a.json_value(value)
            try:
                if isinstance(raw, dict) and "artifact_id" in raw:
                    exact = DefinitionReference.model_validate(raw)
                    refs.extend(evidence.refs_from_exact(self.s, self.ctx, self.pid, (exact,)))
                else:
                    refs.append(SourceRef.model_validate(raw))
            except ValidationError as exc:
                raise DomainError(
                    "PARTICIPANT_SOURCE_SHAPE_INVALID",
                    "已保存参与者来源不符合固定原文引用或领域来源契约。",
                    503,
                ) from exc
        return tuple(refs)

    def one(self, table, *, columns=None, scoped=True, **keys):
        where = [table.c.tenant_id == self.ctx.tenant_id]
        if scoped:
            where.append(table.c.product_id == self.pid)
        where.extend(table.c[k] == v for k, v in keys.items())
        columns = tuple(table.c[k] for k in columns) if columns else tuple(table.c)
        statement = (
            select(*columns)
            .where(*where)
            .limit(2)
            .execution_options(autoflush=False, populate_existing=True)
        )
        from pdos_next.request_proof import snapshot_mappings

        values = snapshot_mappings(self.s, statement, scope_id=self.pid)
        _require(len(values) == 1)
        row = deepcopy(dict(values[0]))
        self.tracked.append((statement, deepcopy(row)))
        self.rows.append({"table": table.name, "value": deepcopy(row)})
        if "owner_id" in row and "visibility" in row:
            _require(row["visibility"] in ("category", "private", "audience"))
            if row["visibility"] == "private" and row["owner_id"] != self.ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "不能借原作者读取私人参与者材料。", 403)
            if self.origin.visibility == "category" and row["visibility"] == "private":
                raise DomainError("FORBIDDEN_SCOPE", "私人实绩不能扩大共享调查受众。", 403)
        if "project_id" in row:
            _require(
                row["project_id"] == self.origin.scope.project_id, "PARTICIPANT_SCOPE_MISMATCH"
            )
        self.refs.extend(self.source_refs(row.get("sources", ())))
        self.reads.extend(
            a.SourceRead.model_validate(v) for v in row.get("required_source_read_set", ())
        )
        return row

    def person(self, identity, role, sources):
        _require(isinstance(identity, UUID), "PARTICIPANT_IDENTITY_MISSING")
        refs = self.source_refs(sources)
        _require(bool(refs), "PARTICIPANT_OWNER_SOURCE_MISSING")
        roles, prior = self.people.setdefault(identity, (set(), []))
        roles.add(role)
        prior.extend(refs)

    def group(self, row, family, actor, event):
        receipt = self.one(
            Receipt.__table__,
            operation=row["operation"],
            subject_type=family,
            subject_id=row["id"],
            subject_revision=row["revision"],
        )
        _require(
            receipt["actor_id"] == actor and receipt["requester_id"] == actor,
            "PARTICIPANT_WRITER_MISMATCH",
        )
        _require(
            receipt["visibility"] == row["visibility"]
            and receipt["result"].get("id") == str(row["id"])
            and type(receipt["result"].get("revision")) is int
            and receipt["result"]["revision"] == row["revision"],
            "PARTICIPANT_RECEIPT_MISMATCH",
        )
        self.companions(receipt, event)
        return SourceRef(id=receipt["id"], revision=1, kind="domain", position="action-receipt")

    def companions(self, receipt, event):
        key = (
            select(RequestKey.__table__)
            .where(
                RequestKey.tenant_id == self.ctx.tenant_id,
                RequestKey.actor_id == receipt["actor_id"],
                RequestKey.receipt_id == receipt["id"],
                RequestKey.digest == receipt["request_digest"],
            )
            .limit(1)
            .execution_options(autoflush=False, populate_existing=True)
        )
        from pdos_next.request_proof import snapshot_mappings

        matches = snapshot_mappings(self.s, key, scope_id=self.pid)
        if not matches and receipt["actor_id"] != self.ctx.actor_id:
            from pdos_next.receipt_request_binding import receipt_request_binding_statement

            binding = receipt_request_binding_statement(self.ctx.tenant_id, self.pid, receipt["id"])
            checked = snapshot_mappings(self.s, binding, scope_id=self.pid)
            _require(
                len(checked) == 1 and set(checked[0]) == {"bound"} and checked[0]["bound"] is True,
                "PARTICIPANT_REQUEST_ASSOCIATION_MISSING",
            )
            self.tracked.append((binding, {"bound": True}))
            self._request_binding_statements.add(binding)
            self.rows.append(
                {"receipt_request_binding": {"receipt_id": receipt["id"], "bound": True}}
            )
        else:
            _require(len(matches) == 1, "PARTICIPANT_REQUEST_ASSOCIATION_MISSING")
            self.tracked.append((key, deepcopy(dict(matches[0]))))
            self.rows.append(
                {"table": RequestKey.__tablename__, "value": deepcopy(dict(matches[0]))}
            )
        self.atomic_companions(receipt, event)

    def atomic_companions(self, receipt, event):
        """Actual worker parse emits Receipt/Audit/Outbox without a RequestKey.

        Public registration still uses companions(), including its original key.
        This method alone does not authorize a parse or assert scan/byte safety.
        """
        audit = self.one(Audit.__table__, scoped=False, receipt_id=receipt["id"])
        outbox = self.one(
            Outbox.__table__,
            scoped=False,
            columns=(
                "id",
                "tenant_id",
                "receipt_id",
                "type",
                "subject_id",
                "subject_revision",
                "schema_version",
                "actor_id",
                "correlation_id",
            ),
            receipt_id=receipt["id"],
        )
        _require(
            audit["actor_id"] == receipt["actor_id"]
            and audit["operation"] == receipt["operation"]
            and outbox["actor_id"] == receipt["actor_id"]
            and outbox["type"] == event
            and outbox["subject_id"] == receipt["subject_id"]
            and outbox["subject_revision"] == receipt["subject_revision"]
            and outbox["correlation_id"] == (receipt["run_id"] or receipt["command_id"])
            and outbox["schema_version"] == 1,
            "PARTICIPANT_ATOMIC_GROUP_MISMATCH",
        )

    def report(self, reference, role):
        if reference is None:
            self.missing.add("REPORT_PARTICIPANT_OWNER_MISSING")
            return
        (ref,) = self.source_refs((reference,))
        _require(ref.kind == "artifact", "REPORT_ARTIFACT_REQUIRED")
        artifact = self.one(Artifact.__table__, id=ref.id, revision=ref.revision)
        _require(
            artifact["content_hash"] == digest(artifact["content"])
            and artifact["status"] == "active",
            "PARTICIPANT_SOURCE_STALE",
        )
        self.refs.append(ref)
        self.reads.append(a.SourceRead(artifact_id=ref.id, expected_revision=ref.revision))
        subject = artifact
        operation, family = "evidence.artifact.register", "artifact"
        registration_revision = artifact["revision"]
        if artifact["original_id"] is not None:
            subject = self.one(UploadedOriginal.__table__, id=artifact["original_id"])
            operation, family = "evidence.original.upload", "uploaded_original"
            # Upload saves v1. The parser increments Original.revision and saves
            # a separate parse Receipt while creating this derived Artifact.
            registration_revision = 1
            _require(
                subject["owner_id"] == artifact["owner_id"]
                and subject["visibility"] == artifact["visibility"]
                and type(subject["revision"]) is int
                and subject["revision"] >= 2
                and subject["status"] == "parsed",
                "REPORT_ORIGINAL_SCOPE_MISMATCH",
            )
        receipt = self.one(
            Receipt.__table__,
            operation=operation,
            subject_type=family,
            subject_id=subject["id"],
            subject_revision=registration_revision,
        )
        _require(
            receipt["requester_id"] == subject["owner_id"]
            and receipt["visibility"] == artifact["visibility"]
            and receipt["result"].get("id") == str(subject["id"])
            and type(receipt["result"].get("revision")) is int
            and receipt["result"]["revision"] == registration_revision,
            "REPORT_REGISTRATION_MISSING",
        )
        if receipt["run_id"] is None:
            _require(receipt["actor_id"] == receipt["requester_id"], "REPORT_REGISTRATION_MISSING")
        else:
            historical = self.one(Run.__table__, id=receipt["run_id"])
            _require(
                historical["writer_id"] == receipt["actor_id"]
                and historical["requester_id"] == receipt["requester_id"],
                "REPORT_REGISTRATION_MISSING",
            )
        self.companions(receipt, EVENTS[operation])
        self.person(receipt["actor_id"], role, (ref,))
        if receipt["requester_id"] != receipt["actor_id"]:
            self.person(receipt["requester_id"], role, (ref,))
        if artifact["original_id"] is not None:
            parsed = self.one(
                Receipt.__table__,
                operation="evidence.original.parse",
                subject_type="uploaded_original",
                subject_id=subject["id"],
                subject_revision=subject["revision"],
            )
            _require(
                parsed["actor_id"] == parsed["requester_id"] == subject["owner_id"]
                and parsed["run_id"] is None
                and parsed["visibility"] == artifact["visibility"]
                and parsed["result"].get("id") == str(subject["id"])
                and type(parsed["result"].get("revision")) is int
                and parsed["result"]["revision"] == subject["revision"]
                and parsed["result"].get("status") == "parsed",
                "REPORT_DERIVATION_MISMATCH",
            )
            self.atomic_companions(parsed, EVENTS["evidence.original.parse"])
            self.person(parsed["actor_id"], role, (ref,))

    def run(self, logical_id, revision, role, *, expected_current=None):
        row = self.one(VerificationRunVersion.__table__, run_id=logical_id, revision=revision)
        _require(
            digest(row["run_snapshot"]) == row["snapshot_sha256"]
            and digest(row["execution_plan"]) == row["plan_sha256"],
            "PARTICIPANT_RUN_HASH_MISMATCH",
        )
        if expected_current is not None:
            _require(
                (row["id"], row["revision"]) == expected_current, "PARTICIPANT_CURRENT_MISMATCH"
            )
        # Traverse exact immutable lineage. Never substitute a current Run for a failure.
        chain, seen = [], set()
        while True:
            _require(row["id"] not in seen, "PARTICIPANT_RUN_CHAIN_INVALID")
            seen.add(row["id"])
            _require(
                digest(row["run_snapshot"]) == row["snapshot_sha256"]
                and digest(row["execution_plan"]) == row["plan_sha256"],
                "PARTICIPANT_RUN_HASH_MISMATCH",
            )
            _require(
                row["run_snapshot"].get("id") == str(logical_id)
                and row["run_snapshot"].get("revision") == row["revision"],
                "PARTICIPANT_RUN_IDENTITY_MISMATCH",
            )
            proof = self.group(row, "test_run", row["writer_id"], EVENTS[row["operation"]])
            self.person(row["writer_id"], role, (proof,))
            chain.append(row)
            if row["revision"] == 1:
                _require(
                    row["previous_run_version_id"] is None and row["previous_revision"] is None
                )
                break
            _require(row["previous_revision"] == row["revision"] - 1)
            before = self.one(
                VerificationRunVersion.__table__,
                run_id=logical_id,
                id=row["previous_run_version_id"],
                revision=row["previous_revision"],
            )
            _require(
                all(
                    before[key] == row[key]
                    for key in (
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "request_id",
                        "request_version_id",
                        "request_revision",
                        "run_id",
                        "build_id",
                        "build_revision",
                        "owner_id",
                        "visibility",
                    )
                ),
                "PARTICIPANT_RUN_CHAIN_INVALID",
            )
            row = before
        latest = chain[0]
        actual_run = TestRun.model_validate(latest["run_snapshot"])
        _require(
            actual_run.scope == self.origin.scope
            and actual_run.id == logical_id
            and actual_run.build.id == latest["build_id"]
            and actual_run.build.revision == latest["build_revision"],
            "PARTICIPANT_RUN_SCOPE_MISMATCH",
        )
        execution = latest["run_snapshot"].get("execution")
        if isinstance(execution, dict) and execution.get("executor_id"):
            self.person(UUID(execution["executor_id"]), role, latest["sources"])
        else:
            self.missing.add("RUN_ACTUAL_EXECUTOR_MISSING")
        # Exact material atoms for every stored transition, no time-based guess.
        for saved in chain:
            launch = saved["operation"] in ("test.run.plan", "test.run.start")
            if launch:
                fact = self.one(
                    VerificationLaunchFact.__table__,
                    run_id=logical_id,
                    run_version_id=saved["id"],
                    run_revision=saved["revision"],
                    operation=saved["operation"],
                )
                _require(
                    fact["owner_id"] == saved["writer_id"]
                    and fact["status"] == saved["status"]
                    and digest(fact["kernel_event"]) == fact["snapshot_sha256"],
                    "PARTICIPANT_RUN_FACT_MISMATCH",
                )
            else:
                fact = self.one(
                    TestResultActionFact.__table__,
                    run_id=logical_id,
                    next_run_version_id=saved["id"],
                    next_run_revision=saved["revision"],
                    operation=saved["operation"],
                )
                _require(
                    fact["actor_id"] == saved["writer_id"]
                    and fact["owner_id"] == saved["owner_id"]
                    and fact["status"] == "recorded"
                    and (fact["run_version_id"], fact["run_revision"])
                    == (saved["previous_run_version_id"], saved["previous_revision"]),
                    "PARTICIPANT_RUN_FACT_MISMATCH",
                )
            # Run input is aggregate material retaining the original physical
            # effect. Launch/ResultAction stores only this transition's semantic.
            # Keep both full rows tracked; compare the actual nested atom only.
            atom = saved["input_snapshot"].get("launch_input" if launch else "result_input")
            _require(
                isinstance(atom, dict)
                and fact["input_snapshot"] == atom
                and fact["revision"] == 1
                and fact["intent_digest"] == saved["intent_digest"]
                and all(
                    fact[key] == saved[key]
                    for key in (
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "build_id",
                        "request_id",
                        "run_id",
                        "visibility",
                        "operation",
                        "sources",
                        "required_source_read_set",
                        "source_basis",
                        "authority_snapshot",
                    )
                )
                and atom.get("request_id") == str(saved["request_id"])
                and atom.get("run_id") == str(saved["run_id"])
                and type(atom.get("expected_request_revision")) is int
                and atom["expected_request_revision"] == fact["request_revision"],
                "PARTICIPANT_RUN_FACT_MISMATCH",
            )
            before = (fact["request_version_id"], fact["request_revision"])
            after = (fact["next_request_version_id"], fact["next_request_revision"])
            _require(
                (after == before) or (after[1] == before[1] + 1 and after[0] != before[0]),
                "PARTICIPANT_RUN_FACT_MISMATCH",
            )
            if saved["operation"] == "test.run.plan":
                _require(
                    before == after == (saved["request_version_id"], saved["request_revision"]),
                    "PARTICIPANT_RUN_FACT_MISMATCH",
                )
            else:
                _require(
                    type(atom.get("expected_run_revision")) is int
                    and atom["expected_run_revision"] == saved["previous_revision"],
                    "PARTICIPANT_RUN_FACT_MISMATCH",
                )
                if not launch:
                    _require(fact["event"] == atom.get("at"), "PARTICIPANT_RUN_FACT_MISMATCH")
        for raw in latest["run_snapshot"].get("measurements", ()):
            measurement = self.one(
                MeasurementRecord.__table__, id=UUID(raw["id"]), run_id=logical_id
            )
            _require(
                measurement["measurement"] == raw
                and digest(raw) == measurement["measurement_sha256"],
                "PARTICIPANT_MEASUREMENT_MISMATCH",
            )
            capture = self.one(
                MeasurementImportCapture.__table__, id=measurement["capture_id"], run_id=logical_id
            )
            self.report(raw.get("source"), "measurement")
            observation = measurement["verified_observation"].get("observation", {})
            executor = observation.get("executor_id")
            if executor:
                self.person(UUID(executor), "measurement", measurement["sources"])
            else:
                self.missing.add("MEASUREMENT_ACTUAL_EXECUTOR_MISSING")
            _require(
                capture["report_binding"].get("run_id") == str(logical_id),
                "PARTICIPANT_CAPTURE_MISMATCH",
            )
        return latest

    def issue_history(self, selected):
        row = self.one(
            QualityIssueVersion.__table__,
            id=selected.ref.id,
            issue_id=selected.issue_id,
            revision=selected.ref.revision,
        )
        _require(
            row["snapshot_sha256"] == selected.ref.snapshot_sha256
            and row["issue_snapshot"] == selected.issue.model_dump(mode="json"),
            "PARTICIPANT_ORIGIN_MISMATCH",
        )
        issue = selected.issue
        roles = {
            "quality.issue.root_cause.decide": "root_cause",
            "quality.issue.containment.record": "containment",
            "quality.capa.actions.complete": "completion",
        }
        seen, found, decisions = set(), set(), []
        while True:
            _require(
                row["id"] not in seen and digest(row["issue_snapshot"]) == row["snapshot_sha256"]
            )
            seen.add(row["id"])
            if row["operation"] in roles:
                ref = self.group(row, "quality_issue", row["writer_id"], EVENTS[row["operation"]])
                self.person(row["writer_id"], roles[row["operation"]], (ref,))
                found.add(row["operation"])
                decisions.append(deepcopy(row))
            if row["revision"] == 1:
                _require(
                    row["previous_revision"] is None and row["previous_issue_version_id"] is None
                )
                break
            _require(row["previous_revision"] == row["revision"] - 1)
            before = self.one(
                QualityIssueVersion.__table__,
                id=row["previous_issue_version_id"],
                revision=row["previous_revision"],
                issue_id=selected.issue_id,
            )
            _require(
                (before["owner_id"], before["visibility"], before["purpose"])
                == (selected.owner_id, selected.visibility, selected.purpose)
            )
            row = before
        if issue.root_cause:
            _require("quality.issue.root_cause.decide" in found)
            _require(
                any(
                    v["operation"] == "quality.issue.root_cause.decide"
                    and v["writer_id"] == issue.root_cause.actor_id
                    and v["issue_snapshot"].get("root_cause")
                    == issue.root_cause.model_dump(mode="json")
                    for v in decisions
                ),
                "PARTICIPANT_ROOT_ACTOR_MISMATCH",
            )
            self.person(issue.root_cause.actor_id, "root_cause", issue.root_cause.sources)
        for containment in issue.containment:
            _require("quality.issue.containment.record" in found)
            _require(
                any(
                    v["operation"] == "quality.issue.containment.record"
                    and v["writer_id"] == containment.executor_id
                    and containment.model_dump(mode="json")
                    in v["issue_snapshot"].get("containment", ())
                    for v in decisions
                ),
                "PARTICIPANT_CONTAINMENT_ACTOR_MISMATCH",
            )
            self.person(containment.executor_id, "containment", containment.evidence)
        for action in issue.capa.actions:
            _require(
                action.completion is not None
                and action.completion.executor_id == action.executor_id
            )
            _require(
                any(
                    v["operation"] == "quality.capa.actions.complete"
                    and v["writer_id"] == action.executor_id
                    and action.model_dump(mode="json")
                    in v["issue_snapshot"].get("capa", {}).get("actions", ())
                    for v in decisions
                ),
                "PARTICIPANT_COMPLETION_ACTOR_MISMATCH",
            )
            self.person(action.executor_id, "completion", action.completion.evidence)

    def finish(self):
        # No cross-phase memo: every tracked raw group is independently reread.
        for statement, old in self.tracked:
            from pdos_next.request_proof import snapshot_mappings

            rows = snapshot_mappings(self.s, statement, scope_id=self.pid)
            _require(len(rows) == 1 and dict(rows[0]) == old, "PARTICIPANT_OWNER_CHANGED")
            if statement in self._request_binding_statements:
                _require(rows[0].get("bound") is True, "PARTICIPANT_OWNER_CHANGED")
        guards._acl(self.s, self.ctx, self.pid)
        guards._same_uow(self.s, self.uow, self.ctx, self.caller)
        return datetime.now(UTC)

    def finish_clock(self):
        guards._acl(self.s, self.ctx, self.pid)
        grant = guards._one(
            self.s,
            Grant,
            Grant.tenant_id == self.ctx.tenant_id,
            Grant.category_id == category_for_product(self.pid),
            Grant.principal_id == self.ctx.actor_id,
        )
        guards._same_uow(self.s, self.uow, self.ctx, self.caller)
        at = datetime.now(UTC)
        _require((grant.expires_at is None or grant.expires_at > at), "FORBIDDEN_SCOPE", status=403)
        return at, grant.expires_at


def refresh_participants(
    s, ctx, product_id, previous: ParticipantRead, *, anchor, pairs=(), observations=()
):
    """Independent full read, not a stored DTO's assertion of currentness."""
    actual = read_participants(
        s, ctx, product_id, anchor=anchor, pairs=pairs, observations=observations
    )
    _require(
        actual.material_sha256 == previous.material_sha256
        and actual.source_basis == previous.source_basis,
        "PARTICIPANT_OWNER_CHANGED",
    )
    return actual


def read_participants(
    s,
    ctx: Context,
    product_id: UUID,
    *,
    anchor: a.StableCapaAnchor,
    pairs: tuple[PairBinding, ...] = (),
    observations: tuple[FactRef, ...] = (),
) -> ParticipantRead:
    """Raw actual owner evidence. DTO selections do not grant access or authority."""
    _require(
        isinstance(ctx, Context) and isinstance(product_id, UUID), "PARTICIPANT_CALLER_REQUIRED"
    )
    _require(type(anchor) is a.StableCapaAnchor, "PARTICIPANT_ANCHOR_REQUIRED")
    _require(
        anchor.origin.scope.tenant_id == ctx.tenant_id
        and anchor.origin.scope.product_id == product_id,
        "PARTICIPANT_SCOPE_MISMATCH",
        status=403,
    )
    reader = _Read(s, ctx, product_id, anchor.origin)
    with s.no_autoflush:
        descriptor = origin_storage.read_origin_descriptor(
            s, ctx, product_id, anchor.origin.issue_id, anchor.origin.ref
        )
        _require(descriptor.origin == anchor.origin, "PARTICIPANT_ORIGIN_MISMATCH")
        reader.issue_history(anchor.origin)
        runs = {}
        for failure in anchor.origin.issue.failures:
            key = (failure.run.id, failure.run.revision)
            if key not in runs:
                runs[key] = reader.run(*key, "original_test")
            _require(
                (runs[key]["build_id"], runs[key]["build_revision"])
                == (failure.build.id, failure.build.revision)
                and any(
                    v["id"] == str(failure.measurement_id)
                    for v in runs[key]["run_snapshot"].get("measurements", ())
                ),
                "PARTICIPANT_FAILURE_SCOPE_MISMATCH",
            )
        for pair in pairs:
            _require(
                type(pair) is PairBinding
                and pair.scope == anchor.origin.scope
                and pair.purpose == anchor.origin.purpose
                and pair.caller_id == ctx.actor_id,
                "PARTICIPANT_SCOPE_MISMATCH",
                status=403,
            )
            pointer = reader.one(FormalVerificationCurrent.__table__, request_id=pair.request_id)
            _require(
                (pointer["request_version_id"], pointer["request_revision"])
                == (pair.output_ref.id, pair.output_ref.revision),
                "PARTICIPANT_CURRENT_MISMATCH",
            )
            formal = reader.one(
                FormalVerificationRequest.__table__,
                request_id=pair.request_id,
                id=pair.output_ref.id,
                revision=pair.output_ref.revision,
            )
            _require(
                formal["purpose"] == pair.purpose
                and formal["build_id"] == pair.build.id
                and digest(formal["request_snapshot"]) == formal["snapshot_sha256"]
            )
            run_pointer = reader.one(
                VerificationRunCurrent.__table__, request_id=pair.request_id, run_id=pair.run_id
            )
            current_run = reader.run(
                pair.run_id,
                run_pointer["run_revision"],
                "new_test",
                expected_current=(run_pointer["run_version_id"], run_pointer["run_revision"]),
            )
            _require(
                current_run["request_id"] == pair.request_id
                and (current_run["build_id"], current_run["build_revision"])
                == (pair.build.id, pair.build.revision),
                "PARTICIPANT_SCOPE_MISMATCH",
            )
        for ref in observations:
            stored = read_stored_fact(s, ctx, product_id, "observation", ref)
            value = stored.fact
            _require(
                value.scope == anchor.origin.scope
                and value.issue_id == anchor.origin.issue_id
                and value.capa_id == anchor.origin.issue.capa.id
                and value.purpose == anchor.origin.purpose
                and value.anchor_sha256 == anchor.anchor_sha256
            )
            _require(
                stored.registry.state == "current_registered",
                "PARTICIPANT_OBSERVATION_CURRENT_MISMATCH",
            )
            reader.person(value.executor_id, "observation", value.sources)
            reader.refs.extend(value.sources)
            reader.reads.extend(value.required_source_read_set)
            reader.rows.append(
                {
                    "observation": value.model_dump(mode="json"),
                    "group_sha256": stored.group_sha256,
                    "registry": vars(stored.registry),
                }
            )
        from .fact_sources_owner import _wire, read_source_closure

        participants = tuple(
            Participant(id=k, roles=tuple(sorted(v[0])), owner_sources=a.canonical_sources(v[1]))
            for k, v in sorted(reader.people.items(), key=lambda item: str(item[0]))
        )
        refs = a.canonical_sources((*anchor.origin_sources, *reader.refs))
        reads = a.canonical_reads((*anchor.origin_required_source_read_set, *reader.reads))
        material = {
            "scope": anchor.origin.scope.model_dump(mode="json"),
            "origin_ref": anchor.origin.ref.model_dump(mode="json"),
            "current": descriptor.current.model_dump(mode="json"),
            "rows": deepcopy(reader.rows),
            "participants": [v.model_dump(mode="json") for v in participants],
        }
        material = _wire(material)
        reader.finish()
        final = origin_storage.read_origin_descriptor(
            s, ctx, product_id, anchor.origin.issue_id, anchor.origin.ref
        )
        _require(final == descriptor, "PARTICIPANT_CURRENT_CHANGED")
        guards._same_uow(s, reader.uow, ctx, reader.caller)
        # Byte/source security is independent from raw participant associations.
        closure = read_source_closure(
            s,
            ctx,
            product_id,
            scope=anchor.origin.scope,
            owner_id=anchor.origin.owner_id,
            visibility=anchor.origin.visibility,
            sources=refs,
            reads=reads,
            expected_basis=anchor.origin_source_basis,
        )
        _require(
            origin_storage.read_origin_descriptor(
                s, ctx, product_id, anchor.origin.issue_id, anchor.origin.ref
            )
            == descriptor,
            "PARTICIPANT_CURRENT_CHANGED",
        )
        for ref in observations:
            refreshed = read_stored_fact(s, ctx, product_id, "observation", ref)
            selected = next(
                row
                for row in reader.rows
                if row.get("observation", {}).get("ref") == ref.model_dump(mode="json")
            )
            _require(
                refreshed.fact.model_dump(mode="json") == selected["observation"]
                and refreshed.group_sha256 == selected["group_sha256"]
                and vars(refreshed.registry) == selected["registry"],
                "PARTICIPANT_OBSERVATION_CHANGED",
            )
        reader.finish()
        checked, caller_expires_at = reader.finish_clock()
        time_constraints = tuple(
            value
            for value in (caller_expires_at, closure.valid_until, *closure.time_constraints)
            if value is not None
        )
        _require(all(checked < value for value in time_constraints), "PARTICIPANT_SOURCE_EXPIRED")
        material["source_closure_sha256"] = closure.material_sha256
        material_hash = digest(material)
    return ParticipantRead(
        participants,
        material,
        material_hash,
        refs,
        reads,
        checked,
        None,
        closure.source_basis,
        tuple(
            sorted(
                reader.missing | set(closure.missing) | {"PARTICIPANT_INDEPENDENCE_OWNER_REQUIRED"}
            )
        ),
        descriptor.needs_lineage_owner,
        time_constraints=time_constraints,
    )
