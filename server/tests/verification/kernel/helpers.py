"""Synthetic data and in-memory host adapters; no database, files, or credentials.

These adapters demonstrate consumer requirements only. Their rejection behaviour is
not evidence that a real host transaction, authorization, or confirmation is wired.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pdos_next.domain.verification.ports import (
    Authority,
    BuildContext,
    Invocation,
    Mutation,
    Outcome,
    Preview,
    SampleAvailability,
)
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    Coverage,
    DocumentRequirement,
    EventTime,
    ExecutionConditions,
    Measurement,
    NumericCriterion,
    SampleRef,
    Scope,
    SourceRef,
    TestItem,
    TestRun,
    TimeFact,
    Timeline,
    VerificationRequest,
)

NOW = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"synthetic:verification:{name}")


def source(name="drawing", **changes) -> SourceRef:
    return SourceRef(id=uid(name), revision=1, position="synthetic: sheet 1 / A2", **changes)


def event(name="event", *, offset=0, **changes) -> EventTime:
    return EventTime(
        occurred_at=NOW + timedelta(minutes=offset),
        original_timezone="America/Los_Angeles", source=source(name), **changes,
    )


def fact(name="event", *, offset=0) -> TimeFact:
    return TimeFact(
        **event(name, offset=offset).model_dump(), received_at=NOW + timedelta(hours=2),
        actor_id=uid("actor"),
    )


def scope() -> Scope:
    return Scope(tenant_id=uid("tenant"), product_id=uid("product"), project_id=uid("project"))


def build() -> BuildRef:
    return BuildRef(
        id=uid("build"), revision=1, product_id=uid("product"), project_id=uid("project"),
        engineering_configuration=ConfigurationRef(id=uid("engineering"), revision=2),
        manufacturing_configuration=ConfigurationRef(id=uid("manufacturing"), revision=3),
    )


def sample(name="sample-a", cavity="A", **changes) -> SampleRef:
    data = dict(
        id=uid(name), revision=1, build_id=uid("build"), cavity=cavity,
        actual_configuration=ConfigurationRef(id=uid(f"actual-{name}"), revision=1),
    )
    data.update(changes)
    return SampleRef(**data)


def item(name="dimension", **changes) -> TestItem:
    data = dict(
        id=name, feature=f"synthetic {name}", drawing=source(f"drawing-{name}"),
        method=source(f"method-{name}"),
        criterion=NumericCriterion(
            lower=Decimal("9.5"), upper=Decimal("10.5"), source=source(f"criterion-{name}"),
        ),
        unit="mm", conditions="23 °C, dry", material="synthetic ABS",
        sample_count=2, cavities=("A", "B"), destructive=False,
    )
    data.update(changes)
    return TestItem(**data)


def document(name="drawing", *, items=("dimension",), present=True, required=True):
    return DocumentRequirement(
        id=name, title=f"synthetic {name}", item_ids=items,
        source=source(f"doc-{name}") if present else None, required=required,
    )


def request(**changes) -> VerificationRequest:
    data = dict(
        id=uid("request"), revision=1, scope=scope(), build=build(), title="合成试模验证",
        purpose="尺寸验证", items=(item(),), documents=(document(),),
        return_form="原始读数和具名结论", timeline=Timeline(request_created=fact("created")),
    )
    data.update(changes)
    return VerificationRequest(**data)


def coverage(*, samples=None, item_id="dimension") -> tuple[Coverage, ...]:
    if samples is None:
        samples = (sample(), sample("sample-b", "B"))
    return tuple(Coverage(sample_id=s.id, item_id=item_id) for s in samples)


def execution() -> ExecutionConditions:
    return ExecutionConditions(
        equipment=source("equipment"), calibration=source("calibration"),
        environment="23 °C, humidity 50%", conditions="23 °C, dry", executor_id=uid("actor"),
    )


def run(**changes) -> TestRun:
    samples = (sample(), sample("sample-b", "B"))
    data = dict(
        id=uid("run"), revision=1, scope=scope(), request_id=uid("request"),
        request_revision=1, build=build(), items=(item(),), samples=samples,
        coverage=coverage(samples=samples),
    )
    data.update(changes)
    return TestRun(**data)


def measurement(name="measurement-a", *, pair=None, raw="10.000", **changes) -> Measurement:
    data = dict(
        id=uid(name), coverage=pair or coverage()[0], raw_value=raw, unit="mm",
        conditions="23 °C, dry", equipment=source("equipment"),
        environment="23 °C, humidity 50%", method=source("method-dimension"),
        source=source(name), observed_at=NOW + timedelta(minutes=25), observed_timezone="UTC",
    )
    data.update(changes)
    return Measurement(**data)


class HostRejection(RuntimeError):
    """Explicit synthetic host-adapter refusal."""


class FakeBuilds:
    def __init__(self, *, status="evaluating"):
        self.current = BuildContext(ref=build(), status=status)
        self.calls = []

    def get(self, bound_scope, build_id):
        self.calls.append((bound_scope, build_id))
        if bound_scope != scope() or build_id != self.current.ref.id:
            raise HostRejection("build scope")
        return self.current


class FakeEvidence:
    def __init__(self):
        self.rejected: set[UUID] = set()
        self.calls = []
        self.measurement_calls = []
        self.rejected_raw: set[str | None] = set()
        self.rejected_locators: set[tuple[UUID, int, str]] = set()

    def check(self, bound_scope, ref, purpose):
        self.calls.append((bound_scope, ref, purpose))
        if bound_scope != scope() or ref.id in self.rejected:
            raise HostRejection("source withdrawn / stale / wrong audience")

    def verify_measurement(self, bound_scope, proposed, current_run):
        """Synthetic observation proof only, never an actual source-content verifier.

        Fixture observations are explicitly synthetic. Refusal controls establish
        that raw-value/locator verification is an independent mandatory dependency;
        this fake does not certify deterministic extraction or real instrument data.
        """
        self.measurement_calls.append((bound_scope, proposed, current_run.id))
        if bound_scope != scope() or current_run.scope != bound_scope:
            raise HostRejection("observation scope")
        if proposed.coverage not in current_run.coverage:
            raise HostRejection("observation coverage")
        locator = None if proposed.source is None else (
            proposed.source.id, proposed.source.revision, proposed.source.position,
        )
        if proposed.raw_value in self.rejected_raw or locator in self.rejected_locators:
            raise HostRejection("raw value / source locator lacks synthetic observation proof")


class FakeSamples:
    def __init__(self):
        self.current = {s.id: s for s in (sample(), sample("sample-b", "B"))}
        self.unavailable: set[UUID] = set()
        self.inapplicable: set[UUID] = set()
        self.no_ready: set[UUID] = set()
        self.reservations = []
        self.inspect_calls = []
        self.running_checks = []
        self.reject_reserve = False
        self.reject_running = False

    def inspect(self, bound_scope, ref, purpose):
        self.inspect_calls.append((bound_scope, ref, purpose))
        current = self.current.get(ref.id)
        if bound_scope != scope() or current is None or current != ref:
            raise HostRejection("sample actual configuration / revision drift")
        return SampleAvailability(
            sample=current, available=ref.id not in self.unavailable,
            applicable=ref.id not in self.inapplicable, source=source("production-sample"),
            ready_at=None if ref.id in self.no_ready else event("sample-ready", offset=-5),
            reason="synthetic host state",
        )

    def reserve(self, bound_scope, run_id, refs, pairs, destructive, conditions):
        if self.reject_reserve:
            raise HostRejection("competing sample/resource reservation")
        if bound_scope != scope():
            raise HostRejection("sample scope")
        self.reservations.append((run_id, refs, pairs, destructive, conditions))

    def recheck_running(self, bound_scope, current_run):
        self.running_checks.append(current_run.id)
        if self.reject_running or bound_scope != scope():
            raise HostRejection("configuration drift / owning reservation lost")


class FakeCommands:
    """Host proof/receipt model for checking how the handler consumes its port.

    The real port must add locks, fixed-read-set binding, expiry, SQL rollback,
    audit and outbox. This fake neither implements nor certifies those guarantees.
    """

    def __init__(self):
        self.authority = Authority(
            scope=scope(), actor_id=uid("actor"), actor_kind="human",
            roles=("quality", "engineering", "production", "project"),
            authorized=True, qualified=True, cancelled=False, now=NOW + timedelta(hours=2),
        )
        self.requests = {uid("request"): request()}
        self.run_records = {uid("run"): run()}
        self.records: list[Mutation] = []
        self.confirmations = []
        self.reject_begin = False
        self.reject_confirmation = False
        self.receipts = {}
        self.command_intents = {}
        self.proofs = {}

    def context(self, operation, subject_id):
        return self.authority

    def begin(self, invocation):
        if self.reject_begin:
            raise HostRejection("server scope / role / cancellation refused")
        intent = (
            invocation.operation, invocation.subject_id, invocation.expected_revision,
            invocation.semantic_digest,
        )
        previous = self.command_intents.get(invocation.command_id)
        if previous is not None and previous != intent:
            raise HostRejection("command key payload mismatch")
        self.command_intents[invocation.command_id] = intent
        stored = self.receipts.get(intent)
        if stored is not None:
            if not self.authority.authorized or self.authority.cancelled:
                raise HostRejection("replay authorization revoked")
            return stored.model_copy(update={"replayed": True})
        return self.authority

    def request(self, bound_scope, request_id):
        current = self.requests[request_id]
        if current.scope != bound_scope:
            raise HostRejection("request scope")
        return current

    def run(self, bound_scope, run_id):
        current = self.run_records[run_id]
        if current.scope != bound_scope:
            raise HostRejection("run scope")
        return current

    def runs(self, bound_scope, request_id):
        return tuple(
            current for current in self.run_records.values()
            if current.scope == bound_scope and current.request_id == request_id
        )

    def issue_proof(self, invocation: Invocation, preview: Preview):
        token = f"synthetic-proof-{len(self.proofs)}"
        self.proofs[token] = (
            invocation.operation, invocation.subject_id, invocation.expected_revision,
            invocation.semantic_digest, preview.digest, self.authority.actor_id,
        )
        return token

    def confirm(self, invocation, preview, authority):
        if self.reject_confirmation:
            raise HostRejection("expired / revoked / modified confirmation")
        if invocation.operation in {"test.run.review", "test.disposition.decide"}:
            if authority.actor_kind != "human" or invocation.decision_id is None:
                raise HostRejection("named human decision required")
        else:
            expected = (
                invocation.operation, invocation.subject_id, invocation.expected_revision,
                invocation.semantic_digest, preview.digest, authority.actor_id,
            )
            if self.proofs.pop(invocation.confirmation_token, None) != expected:
                raise HostRejection("confirmation does not bind current substantive preview")
        self.confirmations.append(invocation)

    def record(self, invocation, mutation):
        current = mutation.run or mutation.request
        if current is None:
            raise AssertionError("mutation missing aggregate")
        if mutation.request is not None:
            stored_request = self.requests.get(mutation.request.id)
            revision = 0 if stored_request is None else stored_request.revision
            if revision != mutation.request_before_revision:
                raise HostRejection("request CAS / existing request identity")
        if mutation.run is not None:
            stored_run = self.run_records.get(mutation.run.id)
            revision = 0 if stored_run is None else stored_run.revision
            if revision != mutation.run_before_revision:
                raise HostRejection("run CAS / existing run identity")
        self.records.append(mutation)
        if mutation.request is not None:
            self.requests[mutation.request.id] = mutation.request
        if mutation.run is not None:
            self.run_records[mutation.run.id] = mutation.run
        outcome = Outcome(
            subject_id=current.id, revision=current.revision, status=current.status,
            result=getattr(current, "result", None),
        )
        intent = (
            invocation.operation, invocation.subject_id, invocation.expected_revision,
            invocation.semantic_digest,
        )
        self.receipts[intent] = outcome
        return outcome
