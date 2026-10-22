"""Actual-model and immutable-source admission using synthetic in-memory rows."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import snapshot_command as command
from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.agent_kernel.research_read_ledger import page_result
from pdos_next.agent_kernel.types import RunScope
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal
from pdos_next.research.types import ReadPage, Snapshot
from pdos_next.service import Context, digest


class MemorySession:
    def __init__(self):
        self.rows = {}
        self.info = {}

    def add_row(self, model, row):
        self.rows[model, row.id] = row
        return row

    def get(self, model, identity):
        return self.rows.get((model, identity))

    def scalar(self, query):
        return next(row for (model, _), row in self.rows.items() if model is AgentRun)

    def scalars(self, query):
        entity = query.column_descriptions[0]["entity"]
        rows = [row for (model, _), row in self.rows.items() if model is entity]
        return SimpleNamespace(all=lambda: rows)


@pytest.fixture
def proof():
    session = MemorySession()
    scope = RunScope(*(uuid4() for _ in range(6)))
    values = asdict(scope)
    values["id"] = values.pop("run_id")
    run = session.add_row(
        AgentRun,
        SimpleNamespace(
            **values,
            state="completed",
            reverted_at=None,
            versions={
                "model_version": "synthetic",
                "model_route_digest": "a" * 64,
                "tool_definitions": {"research": "b" * 64, "main": "d" * 64},
                "prompt_prefixes": {"research": "c" * 64, "main": "e" * 64},
            },
        ),
    )
    for identity in (scope.requester_id, scope.writer_id):
        session.add_row(
            Principal,
            SimpleNamespace(
                id=identity,
                tenant_id=scope.tenant_id,
                active=True,
                kind="human" if identity == scope.requester_id else "agent",
            ),
        )
        session.add_row(Grant, SimpleNamespace(id=uuid4(), principal_id=identity))
    session.add_row(Category, SimpleNamespace(id=scope.category_id))
    body = "Visible beginning\nUnread tail 完整原文\n"
    snapshot = Snapshot(
        uuid4(),
        "https://example.test/article",
        "https://example.test/article",
        "Synthetic",
        "Summary",
        datetime(2026, 10, 11, tzinfo=UTC),
        body,
        sha256(body.encode()).hexdigest(),
        "synthetic",
        "public_web",
    )
    artifacts = SimpleNamespace(snapshot=lambda bound, identity: snapshot)
    session.info["research_artifacts"] = artifacts
    model_binding = ModelBinding(
        model_version="synthetic",
        model_route_digest="a" * 64,
        tool_definitions_digest="b" * 64,
        prompt_digest="c" * 64,
        isolation="research",
        cancel_epoch=0,
    )
    args = {"url": snapshot.url, "cursor": 0}
    model = session.add_row(
        AgentToolCall,
        SimpleNamespace(
            id=uuid4(),
            tenant_id=run.tenant_id,
            run_id=run.id,
            tool="model",
            state="completed",
            error_code=None,
            receipt_id=None,
            execution_binding=model_binding.model_dump(mode="json"),
            result={"calls": [{"name": "research.read", "arguments": args}]},
        ),
    )
    binding = ReadBinding(
        read_kind="ordinary/v1",
        isolation="research",
        run_id=run.id,
        **{
            key: getattr(run, key)
            for key in (
                "tenant_id",
                "category_id",
                "session_id",
                "requester_id",
                "writer_id",
                "product_id",
                "proposal_id",
                "cancel_epoch",
                "private_context",
            )
        },
        data_categories=("public",),
        customer_identities=(),
        tool="research.read",
        call_key=execution_key(run.id, model.id, 0),
        model_call_id=model.id,
        response_index=0,
        **{
            key: getattr(model_binding, key)
            for key in (
                "model_version",
                "model_route_digest",
                "tool_definitions_digest",
                "prompt_digest",
            )
        },
    )
    call = session.add_row(
        AgentToolCall,
        SimpleNamespace(
            id=uuid4(),
            tenant_id=run.tenant_id,
            run_id=run.id,
            tool="research.read",
            state="completed",
            error_code=None,
            receipt_id=None,
            call_key=binding.call_key,
            input_digest=digest(["research.read", args]),
            execution_binding=binding.model_dump(mode="json"),
            result=page_result(ReadPage(snapshot, "chars:0:18", body[:18], 18)),
        ),
    )
    skill = SkillBinding(key="public-research", version="1", digest="f" * 64, load_event_id=uuid4())
    session.add_row(
        AgentEvent,
        SimpleNamespace(
            id=skill.load_event_id,
            tenant_id=run.tenant_id,
            run_id=run.id,
            body={
                "type": "skill_loaded",
                "key": skill.key,
                "version": skill.version,
                "digest": skill.digest,
                "isolation": "main",
            },
        ),
    )
    write_binding = ModelBinding(
        **{
            **model_binding.model_dump(),
            "isolation": "main",
            "tool_definitions_digest": "d" * 64,
            "prompt_digest": "e" * 64,
            "loaded_skills": (skill,),
        },
    )
    write_model = session.add_row(
        AgentToolCall,
        SimpleNamespace(
            **{
                **vars(model),
                "id": uuid4(),
                "execution_binding": write_binding.model_dump(mode="json"),
                "result": {
                    "calls": [
                        {"name": command.OPERATION, "arguments": {"snapshot_id": str(snapshot.id)}}
                    ]
                },
            },
        ),
    )
    source = WriteSource(skill=skill, model_call_id=write_model.id, response_index=0)
    event_id = uuid4()
    dto = Command(
        command_id=uuid4(),
        idempotency_key="synthetic-confirm",
        operation=command.OPERATION,
        category_id=scope.category_id,
        expected_revision=1,
        payload={"snapshot_id": str(snapshot.id), "prepared_event_id": str(event_id)},
    )
    event = session.add_row(
        AgentEvent,
        SimpleNamespace(
            id=event_id,
            tenant_id=scope.tenant_id,
            run_id=run.id,
            body={
                "type": command.CANDIDATE,
                "intent_key": execution_key(run.id, write_model.id, 0),
                "command": dto.model_dump(mode="json"),
                "cancel_epoch": 0,
                "source": source.model_dump(mode="json"),
                "model_binding": write_binding.model_dump(mode="json"),
                "read_call_id": str(call.id),
                "snapshot_digest": digest(asdict(snapshot)),
            },
        ),
    )
    return SimpleNamespace(
        session=session,
        run=run,
        snapshot=snapshot,
        call=call,
        model=model,
        args=args,
        write_model=write_model,
        event=event,
        command=dto,
        ctx=Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id),
        category_scope=SimpleNamespace(id=None, revision=1),
    )


def assess(proof):
    return command.prepared(
        proof.session,
        proof.ctx,
        proof.command,
        proof.category_scope,
        command.SnapshotRegister.model_validate(proof.command.payload),
    )


def test_completed_bound_read_can_register_entire_immutable_snapshot(proof):
    admitted = assess(proof)
    assert admitted.snapshot == proof.snapshot
    assert admitted.read_call_id == proof.call.id
    assert admitted.visibility == "category"
    row, subject, visibility = command.apply(
        proof.session,
        proof.ctx,
        proof.command,
        proof.category_scope,
        command.SnapshotRegister.model_validate(proof.command.payload),
    )
    assert subject == "public_web_snapshot" and visibility == "category"
    assert row.id == proof.snapshot.id and row.markdown == proof.snapshot.markdown
    assert row.receipt_id == row.prepared_receipt_id and row.revision == 1
    assert row.prepared_by_run_id == proof.run.id
    assert row.action_result["prepared_by_run_id"] == str(proof.run.id)


@pytest.mark.parametrize("field", ["run_id", "writer_id", "visibility", "content_hash", "url"])
def test_payload_cannot_supply_authority_or_source_facts(field):
    with pytest.raises(ValidationError):
        command.SnapshotRegister.model_validate({"snapshot_id": uuid4(), field: "forged"})


@pytest.mark.parametrize(
    "mutation",
    [
        "unread_content",
        "read_run",
        "read_result",
        "read_model",
        "write_model",
        "cancelled",
        "failed",
        "epoch",
        "reverted",
        "writer",
        "grant",
        "event_payload",
        "request_payload",
        "read_kind",
        "event_digest",
        "event_source",
        "event_binding",
        "request_scope",
    ],
)
def test_forged_or_stale_candidate_rejected(proof, mutation):
    if mutation == "unread_content":
        changed = replace(proof.snapshot, markdown=proof.snapshot.markdown + "changed")
        proof.session.info["research_artifacts"].snapshot = lambda *_: changed
    elif mutation == "read_run":
        proof.call.run_id = uuid4()
    elif mutation == "read_result":
        proof.call.result["content_hash"] = "0" * 64
    elif mutation == "read_model":
        proof.model.result["calls"][0]["arguments"]["url"] = "https://different.test/"
    elif mutation == "write_model":
        proof.write_model.result["calls"][0]["arguments"]["snapshot_id"] = str(uuid4())
    elif mutation in {"cancelled", "failed"}:
        proof.run.state = mutation
    elif mutation == "epoch":
        proof.run.cancel_epoch = 1
    elif mutation == "reverted":
        proof.run.reverted_at = datetime.now(UTC)
    elif mutation == "writer":
        proof.session.get(Principal, proof.run.writer_id).active = False
    elif mutation == "grant":
        proof.session.rows = {
            key: row
            for key, row in proof.session.rows.items()
            if key[0] is not Grant or row.principal_id != proof.run.writer_id
        }
    elif mutation == "event_payload":
        proof.event.body["command"]["payload"]["snapshot_id"] = str(uuid4())
    elif mutation == "request_payload":
        proof.command.payload["snapshot_id"] = str(uuid4())
    elif mutation == "read_kind":
        proof.call.execution_binding["read_kind"] = "registered_snapshot/v1"
    elif mutation == "event_digest":
        proof.event.body["snapshot_digest"] = "0" * 64
    elif mutation == "event_source":
        proof.event.body["source"]["model_call_id"] = str(uuid4())
    elif mutation == "event_binding":
        proof.event.body["model_binding"]["model_version"] = "forged"
    elif mutation == "request_scope":
        proof.command.category_id = uuid4()
    with pytest.raises(DomainError):
        assess(proof)


def test_human_confirmation_transport_token_is_not_editing_the_candidate(proof):
    proof.command.payload["confirmation_token"] = "server-confirmation-token"
    proof.command.idempotency_key = "human-confirmation-retry"
    assert assess(proof).snapshot.id == proof.snapshot.id


def test_consistent_private_run_cannot_publish_category_snapshot(proof):
    proof.run.private_context = True
    proof.call.execution_binding["private_context"] = True
    assert assess(proof).visibility == "private"


def test_proof_checks_unread_document_metadata(proof):
    changed = replace(proof.snapshot, title="Changed metadata")
    with pytest.raises(DomainError):
        command.verify_snapshot_page(changed, deepcopy(proof.call.result), proof.args)


@pytest.mark.parametrize("private", [False, True])
def test_internal_category_context_preserves_actual_run_visibility(proof, private):
    proof.run.data_categories = ["internal"]
    proof.run.private_context = private
    proof.call.execution_binding["data_categories"] = ["internal"]
    proof.call.execution_binding["private_context"] = private
    assert assess(proof).visibility == ("private" if private else "category")


@pytest.mark.parametrize("category", ["customer", "customer_original"])
def test_customer_category_requires_consistent_private_run(proof, category):
    proof.run.data_categories = [category]
    proof.call.execution_binding["data_categories"] = [category]
    with pytest.raises(DomainError) as error:
        assess(proof)
    assert error.value.detail["reason"] == "snapshot_run_privacy_inconsistent"


def test_customer_identity_requires_consistent_private_run(proof):
    proof.run.customer_identities = ["synthetic-customer"]
    proof.call.execution_binding["customer_identities"] = ["synthetic-customer"]
    with pytest.raises(DomainError) as error:
        assess(proof)
    assert error.value.detail["reason"] == "snapshot_run_privacy_inconsistent"
    proof.run.private_context = True
    proof.call.execution_binding["private_context"] = True
    assert assess(proof).visibility == "private"
