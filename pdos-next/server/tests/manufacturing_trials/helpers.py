"""Pure synthetic ports. No SQL, runtime, shared services or production fixtures."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pdos_next.domain.manufacturing_trials.handlers import (
    ManufacturingTrialsHandler,
    semantic_digest,
)
from pdos_next.domain.manufacturing_trials.ports import (
    Authority,
    Invocation,
    LotFacts,
    Outcome,
    Ports,
    PreparationFacts,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import (
    Counts,
    LotBasis,
    PilotCreate,
    Ref,
    ResultRecord,
    YieldScope,
)
from pdos_next.schemas.verification.contracts import EventTime, Scope, SourceRef

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
SCOPE = Scope(tenant_id=UUID(int=1), product_id=UUID(int=2), project_id=UUID(int=3))
SOURCE = SourceRef(id=UUID(int=4), revision=1, position="synthetic row 1")


def ref(kind, key=10):
    return Ref(kind=kind, id=UUID(int=key), revision=1)


def basis():
    return LotBasis(
        build=ref("build", 11),
        lot=ref("build_lot", 12),
        actual_configuration=ref("actual_configuration", 13),
        engineering_configuration=ref("engineering_configuration", 14),
        process_revision=ref("process_revision", 15),
        unit="ea",
    )


def creation():
    return PilotCreate(pilot_id=UUID(int=20), basis=basis(), purpose="合成候选", source=SOURCE)


def counts(**changes):
    values = dict(
        input_count=10,
        output_count=10,
        first_pass=6,
        first_failed=4,
        first_unknown=0,
        final_good=8,
        reworked_good=2,
        scrap=1,
        rework_pending=1,
        undecided=0,
        unprocessed=0,
        rework_cycles=7,
    )
    return Counts(**{**values, **changes})


def record(pilot, **changes):
    scope = YieldScope(
        basis=pilot.details.basis,
        manufacturing_baseline=pilot.details.manufacturing_baseline,
        line=pilot.details.line,
        cohort_key="all-10",
        window_start=NOW - timedelta(hours=2),
        window_end=NOW,
        criterion=ref("criterion", 30),
        nature="synthetic",
        minimum_sample=30,
    )
    values = dict(
        observation_id=uuid4(),
        expected_pilot_revision=pilot.revision,
        scope=scope,
        counts=counts(),
        observed=EventTime(occurred_at=NOW, original_timezone="UTC", source=SOURCE),
        source=SOURCE,
    )
    return ResultRecord(**{**values, **changes})


class FakeFacts:
    def __init__(self):
        self.lot_facts = LotFacts(
            scope=SCOPE, basis=basis(), observed_unit_count=10, nature="synthetic", source=SOURCE
        )
        self.gaps = ()
        self.preparation_refs = (ref("qualification", 60),)
        self.revoked = set()
        self.bad_source = False
        self.scope_override = None
        self.parameters_override = None

    def check_ref(self, scope, ref, purpose):
        if ref.id in self.revoked:
            raise DomainError("SOURCE_UNAVAILABLE", "source withdrawn")

    def source(self, scope, source, purpose):
        if self.bad_source:
            raise DomainError("SOURCE_UNAVAILABLE", "source withdrawn")

    def lot(self, scope, basis):
        return self.lot_facts

    def verify_parameters(self, scope, parameters, purpose):
        return parameters if self.parameters_override is None else self.parameters_override

    def preparation(self, scope, details):
        return PreparationFacts(gaps=self.gaps, read_set=self.preparation_refs, sources=(SOURCE,))

    def verify_result(self, scope, pilot, result):
        return self.scope_override or result.scope


class FakeCommands:
    def __init__(self):
        self.authority = Authority(
            scope=SCOPE,
            actor_id=UUID(int=5),
            actor_kind="human",
            roles=("npi",),
            authorized=True,
            qualified=True,
            cancelled=False,
            now=NOW,
        )
        self.pilots, self.observations, self.trials, self.receipts = {}, {}, {}, {}
        self.keys, self.intents, self.proofs, self.events, self.verifications = {}, {}, {}, [], {}
        self.fail_at = None
        self.revoke_at_recheck = False

    @contextmanager
    def atomic(self):
        fields = (
            "pilots",
            "observations",
            "trials",
            "receipts",
            "keys",
            "intents",
            "proofs",
            "events",
            "verifications",
        )
        saved = {name: deepcopy(getattr(self, name)) for name in fields}
        try:
            yield self
        except BaseException:
            for name, value in saved.items():
                setattr(self, name, value)
            raise

    def context(self, operation, subject_id):
        return self.authority

    def begin(self, invocation):
        identity = (
            invocation.operation,
            invocation.subject_id,
            invocation.expected_revision,
            invocation.semantic_digest,
        )
        if not self.authority.authorized:
            raise DomainError("FORBIDDEN", "replay ACL")
        if invocation.command_id in self.keys and self.keys[invocation.command_id] != identity:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "different payload")
        self.keys[invocation.command_id] = identity
        if identity in self.intents:
            outcome = self.intents[identity]
            return Outcome(**{**outcome.model_dump(), "replayed": True})
        return self.authority

    def pilot(self, scope, pilot_id):
        return self.pilots[pilot_id]

    def observation(self, scope, observation_id):
        return self.observations[observation_id]

    def confirm(self, invocation, preview, authority):
        proof = self.proofs.get(invocation.confirmation_token)
        if proof is None or proof[0] != preview.digest or proof[1] < authority.now or proof[2]:
            raise DomainError("CONFIRMATION_REQUIRED", "expired/changed/consumed proof")
        self.proofs[invocation.confirmation_token] = (proof[0], proof[1], True)

    def recheck(self, authority, preview):
        if self.revoke_at_recheck:
            raise DomainError("QUALIFICATION_REQUIRED", "current qualification withdrawn")

    def record(self, invocation, mutation):
        if mutation.trial:
            if mutation.trial.id in self.trials:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "insert only")
            self.trials[mutation.trial.id] = mutation.trial
        if mutation.pilot:
            current = self.pilots.get(mutation.pilot.id)
            if (current.revision if current else 0) != mutation.before_revision:
                raise DomainError("VERSION_CONFLICT", "CAS")
            if not current and any(
                p.details.basis.lot == mutation.pilot.details.basis.lot
                for p in self.pilots.values()
            ):
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "unique extension")
            self.pilots[mutation.pilot.id] = mutation.pilot
        if mutation.observation:
            if mutation.observation.id in self.observations:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "immutable observation")
            self.observations[mutation.observation.id] = mutation.observation
        if self.fail_at == "domain":
            raise RuntimeError("synthetic persistence failure")
        if mutation.verification_intent:
            request = mutation.verification_intent
            if request.request_id in self.verifications:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "unique verification owner")
            self.verifications[request.request_id] = request
        if self.fail_at == "verification":
            raise RuntimeError("synthetic verification failure")
        self.events.append(mutation.event)
        if self.fail_at == "event":
            raise RuntimeError("synthetic outbox failure")
        result = Outcome(
            subject_id=invocation.subject_id,
            revision=mutation.pilot.revision if mutation.pilot else 1,
            receipt_id=uuid4(),
        )
        self.receipts[result.receipt_id] = result
        if self.fail_at == "receipt":
            raise RuntimeError("synthetic receipt failure")
        identity = self.keys[invocation.command_id]
        self.intents[identity] = result
        return result


def host():
    commands, facts = FakeCommands(), FakeFacts()
    handler = ManufacturingTrialsHandler(Ports(commands=commands, facts=facts))
    return handler, commands, facts


def prepare(handler, commands, payload, operation="npi.pilot.create", target=None):
    target = target or getattr(payload, "pilot_id", getattr(payload, "trial_id", None))
    expected = getattr(payload, "expected_pilot_revision", 0)
    preview = handler.preview(operation, target, expected, payload)
    token = str(uuid4())
    commands.proofs[token] = (preview.digest, NOW + timedelta(minutes=5), False)
    return Invocation(
        command_id=uuid4(),
        operation=operation,
        subject_id=target,
        expected_revision=expected,
        semantic_digest=semantic_digest(payload),
        confirmation_token=token,
    )


def create_pilot():
    handler, commands, facts = host()
    payload = creation()
    invocation = prepare(handler, commands, payload)
    handler.execute(invocation, payload)
    return handler, commands, facts, commands.pilots[payload.pilot_id]
