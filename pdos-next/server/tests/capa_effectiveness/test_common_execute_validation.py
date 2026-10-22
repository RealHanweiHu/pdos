"""Real common execute/consume ordering with explicit owner-I/O substitutes.

No bytes, qualification, persisted atom or database acceptance is attested. A
real unbound SQLAlchemy Session supplies UOW/identity/False->True history, while
every SQL read and flush is intercepted and Engine.connect is forbidden.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import service as common
from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.capa_effectiveness import candidate_commands
from pdos_next.domain.capa_effectiveness.fact_consumption import ConsumptionHost
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Category,
    Confirmation,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)

CANDIDATE = candidate_commands.OPERATION
LEGACY = (
    "quality.issue.root_cause.decide",
    "quality.capa.actions.complete",
    "quality.capa.followup.link",
)


def attach(session, row):
    for column in inspect(type(row)).columns:
        if column.key not in vars(row):
            setattr(row, column.key, None)
    make_transient_to_detached(row)
    session.add(row)
    return row


def payload_for(operation, actor, artifact):
    source = {"kind": "artifact", "id": artifact, "revision": 1, "position": "line:1"}
    target = {"issue_id": uuid4(), "expected_issue_revision": 6}
    if operation == CANDIDATE:
        return {
            **target,
            "capa_id": uuid4(),
            "sources": [],
            "reason": "Explicit offline order test; not actual owner evidence",
            "confirmation_token": "offline-common-candidate-token",
        }
    if operation == LEGACY[0]:
        return {
            **target,
            "text": "Offline root cause",
            "sources": [source],
            "approval_token": "offline-approval-token",
        }
    if operation == LEGACY[1]:
        return {
            **target,
            "completions": [
                {
                    "id": uuid4(),
                    "text": "Offline completion",
                    "executor_id": actor,
                    "evidence": [source],
                    "at": {
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "original_timezone": "UTC",
                        "source": source,
                    },
                }
            ],
            "confirmation_token": "offline-completion-token",
        }
    assert operation == LEGACY[2]
    return {
        **target,
        "capa_id": uuid4(),
        "action_id": uuid4(),
        "output_refs": [{"kind": "verification_request", "id": uuid4(), "revision": 1}],
        "reason": "Offline fixed output",
        "confirmation_token": "offline-link-confirmation-token",
    }


@pytest.fixture
def world(monkeypatch):
    def no_database(*args, **kwargs):
        raise AssertionError("Common execution order test must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    session = Session(bind=SimpleNamespace(offline_only=True))
    session.begin()
    actor = uuid4()
    ctx = common.Context(uuid4(), actor, actor, category_id=uuid4())
    product = Product(id=uuid4(), tenant_id=ctx.tenant_id, category_id=ctx.category_id, revision=7)
    read = SourceRead(artifact_id=uuid4(), expected_revision=1)
    work = SimpleNamespace(
        s=session,
        ctx=ctx,
        product=product,
        read=read,
        trace=[],
        key=None,
        old=None,
        added=[],
        validation_failure=None,
        prepare_failure=None,
        final_failure=None,
        source_failure=False,
        different_review=False,
    )
    original_add = session.add

    def add(row, *args, **kwargs):
        work.trace.append(f"add:{type(row).__name__}")
        work.added.append(row)
        if inspect(row, raiseerr=False) is not None:
            original_add(row, *args, **kwargs)

    def scalar(statement, *args, **kwargs):
        model = statement.column_descriptions[0]["entity"]
        if model is Product:
            work.trace.append("product")
            return product
        if model is Artifact:
            # This fixture's complete source set contains only model artifacts.
            return None
        if model is RequestKey:
            work.trace.append("key_lookup")
            values = statement.compile().params.values()
            assert actor in values and work.command.idempotency_key in values
            return work.key
        assert model is Receipt
        work.trace.append("semantic_lookup")
        assert product.id in statement.compile().params.values()
        return work.old

    def get(model, identity, *args, **kwargs):
        if model is Category:
            assert identity == ctx.category_id
            return SimpleNamespace(id=identity, tenant_id=ctx.tenant_id)
        if model is Principal:
            assert identity == actor
            return SimpleNamespace(kind="human")
        assert model is Receipt and work.old is not None and identity == work.old.id
        work.trace.append("receipt_get")
        return work.old

    def access(*args, **kwargs):
        work.trace.append("access")
        return product

    def source(*args, **kwargs):
        work.trace.append("source")
        if work.source_failure:
            raise DomainError("SOURCE_UNAVAILABLE", "Explicit offline revoked source", 403)
        return SimpleNamespace(revision=read.expected_revision)

    def receipt(row):
        work.trace.append("return_receipt")
        return {"id": str(row.id)}

    def metadata_insert(statement, *args, **kwargs):
        assert statement.is_insert and statement.table.name == RequestKey.__tablename__
        work.trace.append("add:RequestKey")
        work.key = RequestKey(**statement.compile().params)
        work.added.append(work.key)
        return SimpleNamespace()

    monkeypatch.setattr(session, "execute", metadata_insert)
    monkeypatch.setattr(session, "add", add)
    monkeypatch.setattr(session, "scalar", scalar)
    monkeypatch.setattr(session, "get", get)
    monkeypatch.setattr(session, "flush", lambda: work.trace.append("flush"))
    monkeypatch.setattr(common, "require_access", access)
    monkeypatch.setattr(common, "source_for", source)
    monkeypatch.setattr(
        common,
        "prove_sources",
        lambda s, ctx, pid, reads: [
            source(s, ctx, pid, r.artifact_id, r.expected_revision) for r in reads
        ],
    )
    monkeypatch.setattr(common, "receipt_view", receipt)

    def select(operation=CANDIDATE, *, replay=None):
        work.trace.clear()
        work.added.clear()
        data = common.PAYLOADS[operation].model_validate(
            payload_for(operation, actor, read.artifact_id)
        )
        command = Command(
            command_id=uuid4(),
            idempotency_key="offline-common-validation-order",
            operation=operation,
            category_id=ctx.category_id,
            product_id=product.id,
            expected_revision=product.revision,
            source_read_set=[read],
            payload=data.model_dump(mode="json"),
        )
        work.command, work.payload = command, data
        review = {"operation": operation, "explicit_offline_review": command.payload}

        class OwnerSubstitute:
            # Real serializers and common execution remain in use. This class
            # only replaces slow owner callbacks with explicit test outcomes.
            semantic = staticmethod(
                candidate_commands.semantic
                if operation == CANDIDATE
                else lambda value: value.model_dump(
                    mode="json", exclude={"approval_token", "confirmation_token"}
                )
            )

            def validate(self, s, c, cmd, p, payload):
                assert (s, c, cmd, p) == (session, ctx, command, product)
                work.trace.append("full_validate")
                if work.validation_failure:
                    raise DomainError(
                        work.validation_failure, "Explicit offline current-owner failure", 403
                    )

            def prepare_write_review(self, s, c, cmd, p, payload):
                assert (s, c, cmd, p) == (session, ctx, command, product)
                assert cmd.source_read_set == [read]
                work.trace.append("prepare_full_guard")
                if work.prepare_failure:
                    raise DomainError(work.prepare_failure, "Explicit offline new-write guard", 409)
                return work.phase, {
                    **deepcopy(review),
                    **({"changed": True} if work.different_review else {}),
                }

            def bind_consumption(self, s, c, cmd, p, payload, phase, proof):
                assert phase is work.phase and proof is work.proof and proof.consumed is False
                work.trace.append("bind_unconsumed")
                return work.host.bind_before_transition(
                    s, c, cmd, payload, self, proof, reviewed_snapshot=review
                )

            def record_consumption(self, s, c, cmd, p, payload, phase, proof, binding):
                assert phase is work.phase and proof is work.proof and proof.consumed is True
                work.trace.append("capture_actual_transition")
                marker = work.host.capture_after_transition(
                    s, c, cmd, payload, self, proof, binding=binding
                )
                work.live = (binding, marker)
                return marker

            def apply_prepared_write(self, s, c, cmd, p, payload, phase, *, consumption=None):
                assert phase is work.phase
                work.trace.append("apply_prepared")
                if operation == CANDIDATE:
                    assert consumption == work.live
                    binding, marker = consumption
                    work.host.require_live(
                        s, c, cmd, payload, self, work.proof, binding=binding, marker=marker
                    )
                work.trace.append("final_full_owner_guard")
                if work.final_failure:
                    raise DomainError(
                        work.final_failure, "Explicit offline last-owner failure", 409
                    )
                if operation == CANDIDATE:
                    work.host.require_live(
                        s, c, cmd, payload, self, work.proof, binding=binding, marker=marker
                    )
                return work.subject, "capa_verification_candidate", "private"

            def apply(self, *args):
                work.trace.append("apply_legacy")
                return work.subject, "quality_issue", "private"

        module = OwnerSubstitute()
        work.module = module
        work.phase = object()
        work.subject = SimpleNamespace(id=uuid4(), revision=1, status="candidate")
        work.host = ConsumptionHost({operation: module}) if operation == CANDIDATE else None
        token = getattr(data, "approval_token", None) or data.confirmation_token
        clock = datetime.now(UTC)
        proof = Confirmation(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            subject_type="product",
            product_id=product.id,
            actor_id=actor,
            operation=operation,
            subject_id=product.id,
            revision=product.revision,
            token_hash=common.digest(token),
            payload_digest=common.material_digest(ctx, command, data, module),
            snapshot=deepcopy(review),
            created_at=clock,
            expires_at=clock + timedelta(minutes=10),
            consumed=False,
        )
        attach(session, proof)
        work.proof = proof

        def confirmation(*args, **kwargs):
            work.trace.append("confirmation_for")
            return proof

        monkeypatch.setattr(common, "handler", lambda op: module if op == operation else None)
        monkeypatch.setattr(common, "confirmation_for", confirmation)
        if operation != CANDIDATE:
            from pdos_next import quality_followup_host

            monkeypatch.setattr(common, "reviewed_view", lambda *args: deepcopy(review))
            monkeypatch.setattr(
                quality_followup_host,
                "record_consumed_confirmation",
                lambda *args: work.trace.append("legacy_capture"),
            )
        old = SimpleNamespace(id=uuid4(), category_id=ctx.category_id)
        request_digest = common.digest(
            {
                "operation": operation,
                "category_id": command.category_id,
                "product_id": command.product_id,
                "expected_revision": command.expected_revision,
                "source_read_set": [
                    value.model_dump(mode="json") for value in command.source_read_set
                ],
                "payload": data.model_dump(mode="json"),
            }
        )
        work.key = (
            SimpleNamespace(
                digest="0" * 64 if replay == "conflict" else request_digest, receipt_id=old.id
            )
            if replay in {"key", "conflict"}
            else None
        )
        work.old = old if replay in {"key", "semantic", "conflict"} else None
        work.trace.clear()
        work.added.clear()
        return work

    work.select = select
    try:
        yield work
    finally:
        session.close()


def execute(work):
    return common.execute(work.s, work.ctx, work.command)


@pytest.mark.parametrize("replay", ["key", "semantic", "conflict"])
def test_candidate_dedup_recovers_without_revalidating_owner(world, replay):
    work = world.select(replay=replay)
    if replay == "conflict":
        with pytest.raises(DomainError) as caught:
            execute(work)
        assert caught.value.reason == "DUPLICATE_INTENT_CONFLICT"
    else:
        assert execute(work) == {"id": str(work.old.id)}
        assert "full_validate" not in work.trace
    assert "full_validate" not in work.trace
    assert "prepare_full_guard" not in work.trace and work.proof.consumed is False
    keys = [row for row in work.added if isinstance(row, RequestKey)]
    assert len(keys) == (1 if replay == "semantic" else 0)
    if keys:
        assert "full_validate" not in work.trace
        assert keys[0].receipt_id == work.old.id


@pytest.mark.parametrize("replay", ["key", "semantic", "conflict"])
@pytest.mark.parametrize(
    "failure", ["QUALIFICATION_REQUIRED", "SOURCE_UNAVAILABLE", "RECHECK_REQUIRED"]
)
def test_candidate_current_owner_failure_does_not_invalidate_saved_receipt(world, replay, failure):
    work = world.select(replay=replay)
    work.validation_failure = failure
    if replay == "conflict":
        with pytest.raises(DomainError) as caught:
            execute(work)
        assert caught.value.reason == "DUPLICATE_INTENT_CONFLICT"
    else:
        assert execute(work) == {"id": str(work.old.id)}
    assert "full_validate" not in work.trace and "prepare_full_guard" not in work.trace
    assert work.proof.consumed is False


def test_candidate_new_write_prepares_once_without_discarded_front_validation(world):
    work = world.select()
    work.validation_failure = "FRONT_DISCARDED_LOAD_MUST_NOT_RUN"
    result = execute(work)
    assert result["id"] and work.proof.consumed is True
    assert "full_validate" not in work.trace
    assert work.trace.count("prepare_full_guard") == 1
    milestones = [
        "key_lookup",
        "semantic_lookup",
        "prepare_full_guard",
        "bind_unconsumed",
        "capture_actual_transition",
        "apply_prepared",
        "final_full_owner_guard",
        "return_receipt",
    ]
    assert [work.trace.index(value) for value in milestones] == sorted(
        work.trace.index(value) for value in milestones
    )
    assert sum(isinstance(row, Receipt) for row in work.added) == 1
    assert sum(isinstance(row, Audit) for row in work.added) == 1
    assert sum(isinstance(row, Outbox) for row in work.added) == 1


@pytest.mark.parametrize("stage", ["prepare", "final"])
def test_candidate_new_write_still_rejects_actual_prepare_and_last_owner_failure(world, stage):
    work = world.select()
    if stage == "prepare":
        work.prepare_failure = "MISSING_REQUIRED_EVIDENCE"
    else:
        work.final_failure = "SOURCE_STALE"
    with pytest.raises(DomainError) as caught:
        execute(work)
    assert caught.value.reason == (
        "MISSING_REQUIRED_EVIDENCE" if stage == "prepare" else "SOURCE_STALE"
    )
    assert "return_receipt" not in work.trace
    assert not any(isinstance(row, (Receipt, Audit, Outbox, RequestKey)) for row in work.added)
    assert work.proof.consumed is (stage == "final")


def test_candidate_material_conflict_cannot_consume_or_apply(world):
    work = world.select()
    work.different_review = True
    with pytest.raises(DomainError) as caught:
        execute(work)
    assert caught.value.reason == "CONFIRMATION_SCOPE_CHANGED"
    assert work.proof.consumed is False
    assert "capture_actual_transition" not in work.trace and "apply_prepared" not in work.trace


def test_common_source_withdrawal_still_recovers_saved_receipt(world):
    work = world.select(replay="key")
    work.source_failure = True
    assert execute(work) == {"id": str(work.old.id)}
    assert "source" not in work.trace and "full_validate" not in work.trace


@pytest.mark.parametrize("operation", LEGACY)
@pytest.mark.parametrize("replay", [None, "key", "semantic", "conflict"])
def test_root_complete_and_link_validate_only_new_intent(world, operation, replay):
    work = world.select(operation, replay=replay)
    if replay == "conflict":
        with pytest.raises(DomainError) as caught:
            execute(work)
        assert caught.value.reason == "DUPLICATE_INTENT_CONFLICT"
    else:
        execute(work)
    assert work.trace.count("full_validate") == (1 if replay is None else 0)
    if replay is None:
        assert work.trace.index("key_lookup") < work.trace.index("full_validate")
