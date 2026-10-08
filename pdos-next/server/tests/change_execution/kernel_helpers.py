"""Synthetic server facts and caller-owned atomic transaction; no DB adapter."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import get_args
from uuid import NAMESPACE_URL, uuid5

from pdos_next.domain.change_control.handlers import OPERATIONS, ChangeControlHandler
from pdos_next.domain.change_control.ports import (
    Authority,
    Currentness,
    Invocation,
    Outcome,
    Policy,
    Ports,
)
from pdos_next.domain.change_control.rules import digest, replace
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    ControlledIntent,
    Coverage,
    Disposition,
    Edge,
    EffectivityFact,
    EffectivityPlan,
    Facet,
    GraphSnapshot,
    ImplementationFact,
    Node,
    PlanItem,
    Ref,
    Selection,
    VerificationFact,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def uid(name):
    return uuid5(NAMESPACE_URL, f"change-control-synthetic:{name}")


SOURCE = SourceRef(id=uid("source"), revision=1, position="synthetic lines 1-20")
SCOPE = Scope(tenant_id=uid("tenant"), product_id=uid("product"), project_id=uid("project"))


def ref(kind, name=None, revision=1):
    return Ref(id=uid(name or kind), revision=revision, kind=kind)


def graph():
    paths = (
        ("spec", "part", "bom", "engineering_configuration", "build", "sample", "test_run"),
        ("part", "operation", "tooling", "sop", "pilot_run", "manufacturing_release"),
    )
    kinds = list(dict.fromkeys(kind for path in paths for kind in path))
    nodes = tuple(
        Node(ref=ref(kind), scope=SCOPE, audience=("internal",), source=SOURCE, label=kind)
        for kind in kinds
    )
    edges = tuple(
        Edge(
            id=f"{origin}-{target}",
            origin=ref(origin),
            target=ref(target),
            source=SOURCE,
            relation="documented dependency",
        )
        for path in paths
        for origin, target in zip(path, path[1:], strict=False)
    )
    return GraphSnapshot(
        id=uid("graph"),
        revision=1,
        scope=SCOPE,
        audience=("internal",),
        roots=(ref("spec"),),
        nodes=nodes,
        edges=edges,
        coverage=tuple(
            Coverage(node=n.ref, facet=facet, status="complete", source=SOURCE)
            for n in nodes
            for facet in get_args(Facet)
        ),
        sources=(SOURCE,),
        captured_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=2),
        nature="synthetic",
    )


def plan():
    items = []
    for discipline, kind, intent_kind in (
        ("engineering", "engineering_configuration", "new_engineering_configuration"),
        ("manufacturing", "operation", "erp_mes_effectivity"),
    ):
        items.append(
            PlanItem(
                id=uid(f"item-{discipline}"),
                discipline=discipline,
                selection=Selection(
                    objects=(ref(kind),),
                    units=("batch:A", "batch:B"),
                    conditions=("confirmed controlled applicability",),
                    sources=(SOURCE,),
                ),
                intent=ControlledIntent(
                    id=uid(f"intent-{discipline}"),
                    kind=intent_kind,
                    basis=(ref(kind),),
                    description="owner creates controlled result",
                ),
                verification_requirement="independent new run covers actual output",
            )
        )
    dispositions = []
    for node in graph().nodes:
        matches = tuple(i.id for i in items if node.ref in i.selection.objects)
        dispositions.append(
            Disposition(
                object=node.ref,
                handling="covered_by_plan" if matches else "reviewed_no_change",
                item_ids=matches,
                rationale="named synthetic impact disposition",
                sources=(SOURCE,),
            )
        )
    return EffectivityPlan(
        id=uid("plan"),
        items=tuple(items),
        dispositions=tuple(dispositions),
        expires_at=NOW + timedelta(days=1),
    )


class FakeHost:
    """Proof checks are a synthetic common executor, not production authority.

    Every mutation needs the exact active caller token. The rollback snapshot
    includes aggregate, receipt, audit, outbox, imported identities and proof use.
    """

    def __init__(self):
        self.authority = Authority(
            scope=SCOPE,
            actor_id=uid("requester"),
            requester_id=uid("requester"),
            actor_kind="human",
            audience=("internal",),
            roles=("engineering",),
            authorized=True,
            qualified=True,
            cancelled=False,
            now=NOW,
        )
        self.snapshot = graph()
        self.policy = Policy(source=SOURCE)
        self.requests = {}
        self.receipts = {}
        self.semantics = {}
        self.keys = {}
        self.proofs = {}
        self.imported = set()
        self.audit = []
        self.outbox = []
        self.implementations = {}
        self.effectivities = {}
        self.verifications = {}
        self.stale_refs = set()
        self.stale_sources = set()
        self.denied_refs = set()
        self.denied_sources = set()
        self.audience_allowed = True
        self.substitute = None
        self.fail_record = False
        self.race_record = False
        self.active = None
        self.confirm_calls = 0
        self.handler = ChangeControlHandler(Ports(commands=self, facts=self, policies=self))
        self.subject = uid("request")

    def actor(self, name, roles=("engineering",), **changes):
        self.authority = replace(self.authority, actor_id=uid(name), roles=roles, **changes)

    @contextmanager
    def transaction(self):
        names = (
            "requests",
            "receipts",
            "semantics",
            "keys",
            "proofs",
            "imported",
            "audit",
            "outbox",
        )
        before = {name: deepcopy(getattr(self, name)) for name in names}
        token = object()
        assert self.active is None
        self.active = token
        try:
            yield token
        except Exception:
            for name, value in before.items():
                setattr(self, name, value)
            raise
        finally:
            self.active = None

    def check(self, uow):
        assert uow is self.active and uow is not None, "caller transaction must be shared"

    def context(self, uow, operation, subject_id):
        self.check(uow)
        return self.authority

    def begin(self, uow, invocation):
        self.check(uow)
        semantic = self.semantic(invocation)
        if invocation.command_id in self.keys and self.keys[invocation.command_id] != semantic:
            raise DomainError("IDEMPOTENCY_CONFLICT", "same key, different intent")
        return self.authority

    def semantic(self, invocation):
        return (
            self.authority.scope,
            invocation.subject_id,
            invocation.operation,
            invocation.expected_revision,
            invocation.semantic_digest,
        )

    def replay(self, uow, invocation, authority):
        self.check(uow)
        outcome = self.receipts.get(invocation.command_id) or self.semantics.get(
            self.semantic(invocation)
        )
        return replace(outcome, replayed=True) if outcome else None

    def request(self, uow, scope, request_id):
        self.check(uow)
        return self.requests[request_id]

    def confirm(self, uow, invocation, preview, authority):
        self.check(uow)
        self.confirm_calls += 1
        proof = self.proofs.get(invocation.confirmation_token)
        if proof is None or proof["used"]:
            raise DomainError("CONFIRMATION_REQUIRED", "one-use common proof required")
        if proof["expires"] <= authority.now:
            raise DomainError("CONFIRMATION_EXPIRED", "common proof expired")
        if proof["actor"] != authority.actor_id or proof["scope"] != authority.scope:
            raise DomainError("CONFIRMATION_ACTOR_MISMATCH", "actor/scope changed")
        if proof["digest"] != preview.digest:
            raise DomainError("CONFIRMATION_STALE", "fixed preview/read set changed")
        proof["used"] = True

    def record(self, uow, invocation, mutation):
        self.check(uow)
        if self.race_record:
            # The production host checks the locked expected revision at write;
            # emulate a losing CAS without starting another transaction here.
            raise DomainError("VERSION_CONFLICT", "synthetic losing compare-and-swap")
        old = self.requests.get(invocation.subject_id)
        if (mutation.insert and old is not None) or (
            not mutation.insert and old.revision != mutation.expected_revision
        ):
            raise DomainError("VERSION_CONFLICT", "CAS failed")
        for fact_id in mutation.new_fact_ids:
            if fact_id in self.imported:
                raise DomainError("FACT_ID_CONFLICT", "imported identity already used")
        self.imported.update(mutation.new_fact_ids)
        self.requests[invocation.subject_id] = mutation.change
        result = Outcome(
            subject_id=invocation.subject_id,
            revision=mutation.change.revision,
            status=mutation.change.status,
        )
        self.receipts[invocation.command_id] = result
        self.keys[invocation.command_id] = self.semantic(invocation)
        self.semantics[self.semantic(invocation)] = result
        self.audit.append(invocation.command_id)
        if mutation.event_name:
            self.outbox.append(mutation.event_name)
        if self.fail_record:
            raise RuntimeError("synthetic failure after all writes")
        return result

    def ref(self, uow, authority, value):
        self.check(uow)
        if value.identity in self.denied_refs:
            raise DomainError("FORBIDDEN_SCOPE", "server reference ACL denied", 403)
        return self.substitute or value

    def audience(self, uow, authority, audience, refs, sources):
        self.check(uow)
        if not self.audience_allowed:
            raise DomainError("FORBIDDEN_AUDIENCE", "read rights do not allow shared output", 403)

    def source(self, uow, authority, source):
        self.check(uow)
        if digest(source) in self.denied_sources:
            raise DomainError("FORBIDDEN_SOURCE", "server source ACL denied", 403)
        stale = digest(source) in self.stale_sources
        return Currentness(
            current=not stale, reasons=("source corrected/withdrawn",) if stale else ()
        )

    def currentness(self, uow, authority, value):
        self.check(uow)
        stale = value.identity in self.stale_refs
        return Currentness(
            current=not stale, reasons=("configuration revision changed",) if stale else ()
        )

    def graph(self, uow, authority, snapshot):
        self.check(uow)
        return self.snapshot

    def selection(self, uow, authority, item):
        self.check(uow)

    def implementation(self, uow, authority, fact_id, order, item):
        self.check(uow)
        return self.implementations[fact_id]

    def effectivity(self, uow, authority, fact_id, order, item):
        self.check(uow)
        return self.effectivities[fact_id]

    def verification(self, uow, authority, fact_id, order):
        self.check(uow)
        return self.verifications[fact_id]

    def assess(self, uow, authority, request):
        self.check(uow)
        return self.policy

    @property
    def request_value(self):
        return self.requests[self.subject]

    @property
    def order(self):
        return self.request_value.orders[-1]

    def invocation(self, operation, payload, revision=None, command=None):
        payload = OPERATIONS[operation][0].model_validate(payload)
        revision = (
            (self.request_value.revision if self.requests else 0) if revision is None else revision
        )
        return Invocation(
            command_id=command or uid(f"command-{len(self.receipts)}-{operation}"),
            operation=operation,
            subject_id=self.subject,
            expected_revision=revision,
            semantic_digest=digest(payload),
            decision_id=uid("decision"),
        )

    def proof(self, invocation, payload):
        with self.transaction() as uow:
            preview = self.handler.preview(
                uow,
                invocation.operation,
                invocation.subject_id,
                invocation.expected_revision,
                payload,
            )
        token = str(uid(f"proof-{len(self.proofs)}"))
        self.proofs[token] = {
            "used": False,
            "actor": self.authority.actor_id,
            "scope": self.authority.scope,
            "digest": preview.digest,
            "expires": NOW + timedelta(minutes=5),
        }
        return replace(invocation, confirmation_token=token)

    def execute(self, invocation, payload):
        with self.transaction() as uow:
            return self.handler.execute(uow, invocation, payload)

    def run(self, operation, payload):
        invocation = self.invocation(operation, payload)
        if OPERATIONS[operation][1] in {"T1", "T2"}:
            invocation = self.proof(invocation, payload)
        return self.execute(invocation, payload)

    def create(self):
        return self.run(
            "change.request.create",
            {
                "title": "change fixture",
                "reason": "failure",
                "roots": self.snapshot.roots,
                "references": (ref("issue"), ref("capa")),
                "sources": (SOURCE,),
            },
        )

    def analyze(self):
        self.create()
        return self.run(
            "change.impact.compute",
            {
                "snapshot": Ref(
                    id=self.snapshot.id, revision=self.snapshot.revision, kind="graph_snapshot"
                )
            },
        )

    def prepare(self):
        self.analyze()
        return self.run(
            "change.order.prepare",
            {
                "assessment_id": self.request_value.assessments[-1].id,
                "plan": plan(),
                "reason": "controlled implementation",
            },
        )

    def approve(self):
        self.prepare()
        for discipline in ("engineering", "manufacturing"):
            self.actor(f"approver-{discipline}", (discipline,))
            self.run(
                "change.order.approve",
                {
                    "discipline": discipline,
                    "text": "named approval",
                    "expires_at": NOW + timedelta(hours=12),
                },
            )

    def implementation_fact(self, item, outcome="succeeded", **changes):
        self.actor("executor", ("engineering", "manufacturing"))
        kind = (
            "engineering_configuration"
            if item.discipline == "engineering"
            else "manufacturing_configuration"
        )
        fact = ImplementationFact(
            id=uid(f"implementation-{item.id}-{len(self.implementations)}"),
            item_id=item.id,
            intent_id=item.intent.id,
            executor_id=self.authority.actor_id,
            outcome=outcome,
            occurred_at=NOW,
            received_at=NOW,
            sources=(SOURCE,),
            outputs=(ref(kind, f"output-{item.id}"),) if outcome == "succeeded" else (),
            note="owner-verified synthetic execution",
            nature="synthetic",
        )
        fact = replace(fact, **changes)
        self.implementations[fact.id] = fact
        return fact

    def record_implementation(self, item, **changes):
        fact = self.implementation_fact(item, **changes)
        self.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id})
        return fact

    def effectivity_fact(self, item, **changes):
        implementation = next(
            f
            for f in self.order.implementations
            if f.item_id == item.id
            and (
                f.outcome == "succeeded"
                or not any(
                    x.item_id == item.id and x.outcome == "succeeded"
                    for x in self.order.implementations
                )
            )
        )
        fact = EffectivityFact(
            id=uid(f"effectivity-{item.id}-{len(self.effectivities)}"),
            item_id=item.id,
            intent_id=item.intent.id,
            stage="effective",
            outcome="succeeded",
            covered_units=item.selection.units,
            conditions_digest=digest(item.selection),
            occurred_at=NOW,
            received_at=NOW,
            sources=(SOURCE,),
            output_refs=implementation.outputs,
            system="synthetic-owner",
            external_id=f"receipt-{len(self.effectivities)}",
            nature="synthetic",
        )
        fact = replace(fact, **changes)
        self.effectivities[fact.id] = fact
        return fact

    def record_effectivity(self, item, **changes):
        fact = self.effectivity_fact(item, **changes)
        self.run("change.effectivity.record", {"item_id": item.id, "fact_id": fact.id})
        return fact

    def effective(self):
        self.approve()
        for item in self.order.plan.items:
            self.record_implementation(item)
            self.record_effectivity(item)

    def verification_fact(self, **changes):
        self.actor("independent-quality", ("quality",))
        fact = VerificationFact(
            id=uid("verification"),
            verifier_id=self.authority.actor_id,
            executor_ids=(uid("test-executor"),),
            content_digest=self.order.content_digest,
            result="pass",
            item_ids=tuple(i.id for i in self.order.plan.items),
            output_refs=tuple(r for f in self.order.implementations for r in f.outputs),
            sources=(SOURCE,),
            observed_from=NOW,
            observed_until=NOW,
            applicable=True,
            current=True,
            nature="synthetic",
        )
        fact = replace(fact, **changes)
        self.verifications[fact.id] = fact
        return fact
