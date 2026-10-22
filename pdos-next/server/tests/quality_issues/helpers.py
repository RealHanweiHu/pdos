"""Explicit synthetic records and caller-owned in-memory transaction contract.

No database, real evidence, credentials, network or qualification is used. This
fake tests handler/port interactions; it does not prove PostgreSQL/RLS/HTTP safety.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from pdos_next.domain.quality_issues.handlers import OPERATIONS, QualityIssueHandler
from pdos_next.domain.quality_issues.ports import (
    Authority,
    Currentness,
    Invocation,
    Outcome,
    Ports,
    QualityPolicy,
    VerificationEvidence,
    VerifiedRun,
)
from pdos_next.domain.quality_issues.rules import replace, semantic_digest
from pdos_next.domain.verification.rules import compute_results
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import (
    ActionsComplete,
    CapaAction,
    CapaDraft,
    Containment,
    ContainmentRecord,
    EffectivenessRequirement,
    Hypothesis,
    IssueCreate,
    IssueTriage,
    Ref,
    RootCauseDecide,
)
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    Coverage,
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
)

NOW = datetime(2026, 10, 2, 18, tzinfo=UTC)


def uid(name):
    return uuid5(NAMESPACE_URL, "synthetic:quality-issues:" + name)


def source(name="reading", **changes):
    return SourceRef(**dict(id=uid(name), revision=1, position="synthetic: sheet 1 / A2") | changes)


def scope():
    return Scope(tenant_id=uid("tenant"), product_id=uid("product"), project_id=uid("project"))


def event(name="completion"):
    return EventTime(
        occurred_at=NOW - timedelta(hours=1),
        original_timezone="America/Los_Angeles",
        source=source(name),
    )


def fixed_run(name="run", raw="11", **changes):
    configuration = ConfigurationRef(id=uid("configuration"), revision=1)
    build = BuildRef(
        id=uid("build"),
        revision=1,
        product_id=uid("product"),
        project_id=uid("project"),
        engineering_configuration=configuration,
        manufacturing_configuration=ConfigurationRef(id=uid("manufacturing"), revision=2),
    )
    sample = SampleRef(
        id=uid("sample"),
        revision=1,
        build_id=build.id,
        actual_configuration=configuration,
        cavity="A",
    )
    pair = Coverage(sample_id=sample.id, item_id="diameter")
    item = TestItem(
        id="diameter",
        feature="Synthetic diameter",
        method=source("method"),
        criterion=NumericCriterion(
            lower=Decimal("9"), upper=Decimal("10"), source=source("criterion")
        ),
        unit="mm",
        conditions="23 C dry",
        sample_count=1,
        cavities=("A",),
    )
    execution = ExecutionConditions(
        equipment=source("equipment"),
        calibration=source("calibration"),
        environment="23 C",
        conditions="23 C dry",
        executor_id=uid("tester"),
    )
    m = Measurement(
        id=uid(name + "-measurement"),
        coverage=pair,
        raw_value=raw,
        unit=item.unit,
        conditions=item.conditions,
        equipment=execution.equipment,
        environment=execution.environment,
        method=item.method,
        source=source(name + "-reading"),
        observed_at=NOW - timedelta(hours=2),
        observed_timezone="America/Los_Angeles",
    )
    start = TimeFact(
        **replace(event("start"), occurred_at=NOW - timedelta(hours=3)).model_dump(),
        received_at=NOW,
        actor_id=uid("tester"),
    )
    end = TimeFact(**event("end").model_dump(), received_at=NOW, actor_id=uid("tester"))
    run = TestRun(
        id=uid(name),
        revision=1,
        scope=scope(),
        request_id=uid("request"),
        request_revision=1,
        build=build,
        items=(item,),
        samples=(sample,),
        coverage=(pair,),
        status="results_pending",
        execution=execution,
        actual_start=start,
        actual_end=end,
        final_result=end,
        measurements=(m,),
    )
    computed, result = compute_results(run, run.measurements)
    return replace(run, computed_results=computed, result=result, **changes)


class Rejection(RuntimeError):
    """Synthetic host contract refusal."""


class FakeCommands:
    def __init__(self):
        self.authority = Authority(
            scope=scope(),
            actor_id=uid("executor"),
            actor_kind="human",
            roles=("quality", "engineering", "test"),
            audience=("team",),
            authorized=True,
            qualified=True,
            cancelled=False,
            now=NOW,
        )
        self.issues = {}
        self.failure_map = {}
        self.deliveries = {}
        self.intents = {}
        self.receipts = {}
        self.audit = []
        self.outbox = []
        self.proofs = {}
        self.consumed = set()
        self.fail_at = None
        self.race_revision = False

    def intent(self, invocation):
        return (
            invocation.operation,
            invocation.subject_id,
            invocation.expected_revision,
            invocation.semantic_digest,
        )

    @contextmanager
    def transaction(self):
        names = (
            "issues",
            "failure_map",
            "deliveries",
            "intents",
            "receipts",
            "audit",
            "outbox",
            "proofs",
            "consumed",
        )
        snapshot = {n: deepcopy(getattr(self, n)) for n in names}
        try:
            yield
        except Exception:
            for n, value in snapshot.items():
                setattr(self, n, value)
            raise

    def context(self, operation, subject_id):
        return self.authority

    def begin(self, invocation):
        intent = self.intent(invocation)
        previous = self.intents.get(invocation.command_id)
        if previous is not None and previous != intent:
            raise Rejection("same command key with changed substantive payload")
        self.intents[invocation.command_id] = intent
        return self.authority

    def issue(self, bound_scope, issue_id):
        issue = self.issues[issue_id]
        if issue.scope != bound_scope:
            raise DomainError("FORBIDDEN_SCOPE", "synthetic tenant/project scope", 403)
        return issue

    def replay(self, invocation, authority):
        # Explicitly synthetic proof of the host lookup contract only.
        return self.receipts.get(self.intent(invocation))

    def by_failure(self, bound_scope, identity):
        key = (bound_scope, identity)
        issue_id = self.failure_map.get(key)
        if issue_id is None:
            return None
        issue = self.issue(bound_scope, issue_id)
        while issue.merged_into is not None:
            issue = self.issue(bound_scope, issue.merged_into)
        return issue

    def proof(self, invocation, preview):
        token = f"synthetic-proof-{len(self.proofs)}"
        self.proofs[token] = (
            self.intent(invocation),
            preview.digest,
            self.authority.actor_id,
            self.authority.audience,
        )
        return token

    def confirm(self, invocation, preview, authority):
        expected = (self.intent(invocation), preview.digest, authority.actor_id, authority.audience)
        if invocation.confirmation_token in self.consumed:
            raise Rejection("proof replay")
        if self.proofs.get(invocation.confirmation_token) != expected:
            raise Rejection("confirmation read-set/actor drift or missing proof")
        if OPERATIONS[invocation.operation][1] == "T2" and invocation.decision_id is None:
            raise Rejection("named T2 decision missing")
        self.consumed.add(invocation.confirmation_token)
        if self.fail_at == "after-proof":
            raise Rejection("injected confirmation failure")

    def record(self, invocation, mutation):
        intent = self.intent(invocation)
        if intent in self.receipts:
            return replace(self.receipts[intent], replayed=True)
        if self.race_revision:
            raise Rejection("synthetic concurrent CAS loss")
        for ref in mutation.before:
            if self.issues[ref.id].revision != ref.revision:
                raise Rejection("CAS conflict")
        for iid in mutation.insert_ids:
            if iid in self.issues:
                raise Rejection("insert-only identity collision")
        for issue in mutation.changes:
            for failure in issue.failures:
                existing = self.failure_map.get((issue.scope, failure.identity))
                if issue.merged_into is not None and existing == issue.merged_into:
                    continue
                if existing is not None and existing != issue.id:
                    original = self.issues[existing]
                    if original.id not in issue.aliases and original.merged_into != issue.id:
                        raise Rejection("stable failure identity collision")
            self.issues[issue.id] = issue
            if issue.merged_into is None:
                for failure in issue.failures:
                    self.failure_map[(issue.scope, failure.identity)] = issue.id
        if self.fail_at == "after-facts":
            raise Rejection("injected post-fact failure")
        for delivery in mutation.deliveries:
            key = (delivery.event_id, delivery.failure_identity)
            existing = self.deliveries.get(key)
            if existing is None:
                self.deliveries[key] = delivery
        if self.fail_at == "after-inbox":
            raise Rejection("injected inbox failure")
        target = (
            mutation.changes[0]
            if mutation.changes
            else self.issues[mutation.deliveries[0].issue_id]
        )
        outcome = Outcome(subject_id=target.id, revision=target.revision, status=target.status)
        self.receipts[intent] = outcome
        self.audit.append((invocation.command_id, mutation.event_name))
        if self.fail_at == "after-receipt":
            raise Rejection("injected receipt/audit failure")
        if mutation.event_name is not None:
            self.outbox.append((target.id, mutation.event_name))
        if self.fail_at == "after-outbox":
            raise Rejection("injected outbox failure")
        return outcome


class FakeRuns:
    def __init__(self):
        self.records = {uid("run"): VerifiedRun(run=fixed_run(), nature="synthetic")}
        self.archives = {(v.run.id, v.run.revision): v for v in self.records.values()}
        self.events = {}
        self.stale = {}
        self.denied = False

    def delivery(self, bound_scope, event_id, failure):
        allowed = self.events.get(event_id, ())
        identity = (failure.run.id, failure.measurement_id, failure.criterion)
        if bound_scope != scope() or identity not in allowed:
            raise Rejection("unregistered synthetic failure event")

    def original(self, bound_scope, ref):
        if self.denied or bound_scope != scope():
            raise DomainError("FORBIDDEN_SCOPE", "synthetic archived run ACL", 403)
        return self.archives[(ref.id, ref.revision)]

    def fixed(self, bound_scope, run_id):
        record = self.records[run_id]
        if self.denied or record.run.scope != bound_scope:
            raise DomainError("FORBIDDEN_SCOPE", "synthetic run/source ACL", 403)
        return record

    def currentness(self, bound_scope, failure):
        if self.denied or bound_scope != scope():
            raise DomainError("FORBIDDEN_SCOPE", "synthetic currentness ACL", 403)
        reasons = self.stale.get(failure.source, ())
        return Currentness(current=not reasons, reasons=reasons)


class FakePolicies:
    def __init__(self):
        self.policy = QualityPolicy(
            ref=Ref(id=uid("policy"), revision=1), risk="high", independent_verification=True
        )
        self.evidence = {}

    def assess(self, authority, failures):
        return self.policy

    def verification(self, authority, evidence_id, issue):
        return self.evidence[evidence_id]


class FakeEvidence:
    def __init__(self):
        self.denied = set()
        self.stale = {}

    def currentness(self, bound_scope, ref, purpose):
        self.check(bound_scope, ref, purpose)
        reasons = self.stale.get(ref, ())
        return Currentness(current=not reasons, reasons=reasons)

    def check(self, bound_scope, ref, purpose):
        if bound_scope != scope() or ref in self.denied:
            raise Rejection("source revoked/ACL denied")


class Harness:
    def __init__(self):
        self.commands = FakeCommands()
        self.runs = FakeRuns()
        self.policies = FakePolicies()
        self.evidence = FakeEvidence()
        self.handler = QualityIssueHandler(
            Ports(
                commands=self.commands,
                runs=self.runs,
                policies=self.policies,
                evidence=self.evidence,
            )
        )
        self.sequence = 0

    def invocation(self, operation, subject_id, revision, payload, key=None):
        self.sequence += 1
        return Invocation(
            command_id=uid(key or f"command-{self.sequence}"),
            operation=operation,
            subject_id=subject_id,
            expected_revision=revision,
            semantic_digest=semantic_digest(payload),
        )

    def prepared(self, operation, subject_id, revision, payload, key=None):
        inv = self.invocation(operation, subject_id, revision, payload, key)
        if OPERATIONS[operation][1] != "T0":
            preview = self.handler.preview(operation, subject_id, revision, payload)
            token = self.commands.proof(inv, preview)
            inv = replace(
                inv,
                confirmation_token=token,
                decision_id=uid(f"decision-{self.sequence}")
                if OPERATIONS[operation][1] == "T2"
                else None,
            )
        return inv

    def execute(self, inv, payload):
        with self.commands.transaction():
            return self.handler.execute(inv, payload)

    def call(self, operation, subject_id, revision, payload, key=None):
        return self.execute(self.prepared(operation, subject_id, revision, payload, key), payload)

    def create(self, run_name="run", event_name="delivery", title="Synthetic failure", key=None):
        verified = self.runs.records[uid(run_name)]
        self.runs.archives.setdefault((verified.run.id, verified.run.revision), verified)
        payload = IssueCreate(
            run_id=verified.run.id,
            measurement_id=verified.run.measurements[0].id,
            event_id=uid(event_name),
            title=title,
        )
        identities = self.runs.events.setdefault(payload.event_id, set())
        identities.add(
            (verified.run.id, payload.measurement_id, verified.run.items[0].criterion.source)
        )
        return self.call("quality.issue.create", payload.run_id, 0, payload, key)

    def issue(self, iid):
        return self.commands.issues[iid]

    def action(self, name="corrective"):
        return Containment(
            id=uid(name),
            text="Synthetic action evidence",
            executor_id=self.commands.authority.actor_id,
            evidence=(source(name),),
            at=event(name),
        )

    def ready(self):
        iid = self.create().subject_id
        self.call(
            "quality.issue.triage",
            iid,
            self.issue(iid).revision,
            IssueTriage(reason="Synthetic triage"),
        )
        self.call(
            "quality.issue.containment.record",
            iid,
            self.issue(iid).revision,
            ContainmentRecord(action=self.action("containment")),
        )
        draft = CapaDraft(
            capa_id=uid("capa"),
            hypotheses=(Hypothesis(text="Synthetic hypothesis", sources=(source("hypothesis"),)),),
            actions=(
                CapaAction(
                    id=uid("corrective"),
                    kind="corrective",
                    text="Synthetic correction",
                    executor_id=uid("executor"),
                ),
            ),
            requirement=EffectivenessRequirement(
                method="Synthetic new run",
                acceptance="All failures pass",
                observation_until=NOW - timedelta(minutes=1),
                required_failure_ids=tuple(f.identity for f in self.issue(iid).failures),
            ),
        )
        self.call("quality.capa.draft", iid, self.issue(iid).revision, draft)
        self.call(
            "quality.issue.root_cause.decide",
            iid,
            self.issue(iid).revision,
            RootCauseDecide(text="Synthetic named root cause", sources=(source("root"),)),
        )
        self.call(
            "quality.capa.actions.complete",
            iid,
            self.issue(iid).revision,
            ActionsComplete(completions=(self.action(),)),
        )
        self.commands.authority = replace(
            self.commands.authority, actor_id=uid("independent-reviewer")
        )
        evidence = VerificationEvidence(
            id=uid("verification"),
            sources=(source("new-run-result"),),
            failure_ids=tuple(f.identity for f in self.issue(iid).failures),
            run_ids=(uid("new-run"),),
            verifier_id=uid("independent-reviewer"),
            executor_ids=(uid("new-tester"),),
            requirement_digest=semantic_digest(self.issue(iid).capa.requirement),
            observed_from=NOW - timedelta(minutes=30),
            result="pass",
            observed_until=NOW,
            applicable=True,
            current=True,
            nature="synthetic",
        )
        self.policies.evidence[evidence.id] = evidence
        return iid
