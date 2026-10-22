"""Register retained research artifacts through the common domain transaction only."""

import hashlib
import re
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from pydantic import Field, ValidationError
from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.request_proof import command_inputs_once
from pdos_next.research.types import ReadPage
from pdos_next.research.web import canonical_url
from pdos_next.schema_base import StrictModel

from .bindings import ModelBinding, WriteSource, execution_key
from .disclosure import disclosed_in_run
from .models import AgentEvent, AgentRun, AgentToolCall, PublicWebSnapshot

OPERATION = "research.snapshot.register"
CANDIDATE = "snapshot_candidate"


class SnapshotRegister(StrictModel):
    snapshot_id: UUID
    prepared_event_id: UUID | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


def digest(value):
    from pdos_next.service import digest as command_digest

    return command_digest(value)


def content(payload):
    return payload.model_dump(mode="json", exclude={"prepared_event_id", "confirmation_token"})


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def supports_confirmation(command):
    return command.payload.get("prepared_event_id") is not None


def needs_confirmation(payload):
    return payload.prepared_event_id is not None


def _deny(reason="snapshot_registration_proof_required"):
    error = DomainError("SOURCE_UNAVAILABLE", "快照登记须引用当前运行实际读取的不可变原文。")
    error.detail["reason"] = reason
    raise error


def _artifacts(session):
    owner = session.info.get("domain_command_owner")
    artifacts = getattr(owner, "artifacts", None) or session.info.get("research_artifacts")
    if artifacts is None:
        artifacts = getattr(session.get_bind(), "_pdos_research_artifacts", None)
    if artifacts is None:
        _deny("snapshot_artifacts_unavailable")
    return artifacts


def verify_snapshot_page(snapshot, result, arguments):
    """Prove the full retained document as well as its actually returned page."""
    from .research_read_ledger import page_result

    try:
        location = re.fullmatch(r"chars:(0|[1-9][0-9]*):(0|[1-9][0-9]*)", result["locator"])
        if location is None:
            raise ValueError
        start, end = map(int, location.groups())
        if (
            snapshot.content_hash != hashlib.sha256(snapshot.markdown.encode()).hexdigest()
            or snapshot.url != canonical_url(arguments["url"])
            or start != arguments.get("cursor", 0)
            or not start <= end <= len(snapshot.markdown)
            or (end == start and end < len(snapshot.markdown))
            or snapshot.status not in {"ok", "partial"}
        ):
            raise ValueError
        page = ReadPage(
            snapshot,
            result["locator"],
            snapshot.markdown[start:end],
            end if end < len(snapshot.markdown) else None,
        )
        if page_result(page) != result:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        _deny("snapshot_read_content_mismatch")


@dataclass(frozen=True)
class RegistrationProof:
    run: object
    snapshot: object
    read_call_id: UUID
    snapshot_digest: str
    visibility: str


def _proof(session, run, snapshot_id, *, artifacts=None, read_call_id=None):
    from .deterministic_proofs import _historical_read
    from .execution import check_run_binding, scope_for_run

    scope = scope_for_run(run)
    check_run_binding(run, scope, for_write=False)
    if run.category_id is None:
        _deny("snapshot_category_required")
    try:
        snapshot = (artifacts or _artifacts(session)).snapshot(scope, snapshot_id)
    except (OSError, KeyError, TypeError, ValueError):
        _deny("snapshot_artifacts_unavailable")
    if snapshot.id != snapshot_id:
        _deny("snapshot_identity_mismatch")
    if read_call_id is not None:
        calls = [session.get(AgentToolCall, read_call_id)]
    else:
        calls = session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.tool == "research.read",
                AgentToolCall.state == "completed",
            )
        ).all()
        calls = [
            call
            for call in calls
            if isinstance(call.result, dict) and call.result.get("snapshot_id") == str(snapshot_id)
        ]
    if not calls:
        _deny("snapshot_actual_read_required")
    call = calls[0]
    if call is None or call.tool != "research.read":
        _deny("snapshot_actual_read_required")
    _, actual, binding, arguments = _historical_read(
        session,
        scope,
        call.id,
        "ordinary/v1",
        deny=_deny,
    )
    if binding.isolation != "research":
        _deny("snapshot_research_read_required")
    verify_snapshot_page(snapshot, actual.result, arguments)
    if not run.private_context and (
        run.customer_identities or set(run.data_categories) & {"customer", "customer_original"}
    ):
        _deny("snapshot_run_privacy_inconsistent")
    return RegistrationProof(
        run,
        snapshot,
        call.id,
        digest(asdict(snapshot)),
        "private" if run.private_context else "category",
    )


def _command_material(command):
    value = command.model_dump(mode="json")
    # Transport retry identifiers do not change the confirmed business action.
    value.pop("command_id")
    value.pop("idempotency_key")
    value["payload"] = semantic(SnapshotRegister.model_validate(value["payload"]))
    return value


def _verify_candidate_source(session, run, event):
    """Historical Human adoption retains the exact main-model output and skill load."""
    from .execution import scope_for_run, validate_skill_load

    try:
        source = WriteSource.model_validate(event.body["source"])
        binding = ModelBinding.model_validate(event.body["model_binding"])
        model = session.get(AgentToolCall, source.model_call_id)
        if (
            not model
            or model.tenant_id != run.tenant_id
            or model.run_id != run.id
            or model.tool != "model"
            or model.state != "completed"
            or model.error_code is not None
            or model.receipt_id is not None
            or model.execution_binding != binding.model_dump(mode="json")
            or binding.isolation != "main"
            or binding.cancel_epoch != run.cancel_epoch
            or source.skill not in binding.loaded_skills
            or event.body["intent_key"] != execution_key(run.id, model.id, source.response_index)
            or binding.model_version != run.versions.get("model_version")
            or binding.model_route_digest != run.versions.get("model_route_digest")
            or not disclosed_in_run(run.versions, "main", binding.tool_definitions_digest)
            or binding.prompt_digest != run.versions["prompt_prefixes"].get("main")
        ):
            _deny("snapshot_candidate_source_invalid")
        call = model.result["calls"][source.response_index]
        actual = SnapshotRegister.model_validate(call["arguments"])
        original = SnapshotRegister.model_validate(event.body["command"]["payload"])
        if (
            call["name"] != OPERATION
            or actual.prepared_event_id
            or actual.confirmation_token
            or content(actual) != content(original)
            or original.prepared_event_id != event.id
            or original.confirmation_token is not None
            or event.body["command"]["operation"] != OPERATION
        ):
            _deny("snapshot_candidate_source_invalid")
        validate_skill_load(session, scope_for_run(run), source.skill)
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        _deny("snapshot_candidate_source_invalid")


def prepare(session, scope, spec, arguments, intent_key, bootstrap):
    from .execution import verify_source

    try:
        prefix, run_id, kind, model_id, index = intent_key.split(":")
        model_id, index = UUID(model_id), int(index)
        if (
            prefix != "agent"
            or kind != "model"
            or run_id != str(scope.run_id)
            or index < 0
            or intent_key != execution_key(scope.run_id, model_id, index)
        ):
            raise ValueError
        model = session.get(AgentToolCall, model_id)
        binding = ModelBinding.model_validate(model.execution_binding)
    except (ValueError, AttributeError, ValidationError):
        _deny("snapshot_candidate_source_invalid")
    run = session.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    matching = [
        skill
        for skill in binding.loaded_skills
        if skill.key in bootstrap.catalog._skills
        and spec.name in bootstrap.catalog._skills[skill.key].operations
    ]
    if not matching or spec.name != OPERATION or spec.operation_key != OPERATION:
        _deny("snapshot_candidate_source_invalid")
    source = WriteSource(skill=matching[0], model_call_id=model_id, response_index=index)
    verify_source(
        session,
        scope,
        run,
        spec,
        arguments,
        source,
        catalog=bootstrap.catalog,
        registry=bootstrap.registry,
        route=bootstrap.route(session, scope),
        prepare_only=True,
    )
    command = bootstrap.commands.command(session, scope, spec.name, arguments, intent_key)
    payload = SnapshotRegister.model_validate(command.payload)
    if payload.prepared_event_id or payload.confirmation_token:
        _deny("snapshot_candidate_source_invalid")
    events = session.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)).all()
    previous = next(
        (
            event
            for event in events
            if event.body.get("type") == CANDIDATE and event.body.get("intent_key") == intent_key
        ),
        None,
    )
    try:
        original_read = UUID(previous.body["read_call_id"]) if previous else None
    except (KeyError, TypeError, ValueError):
        _deny("snapshot_candidate_binding_invalid")
    proof = _proof(
        session,
        run,
        payload.snapshot_id,
        artifacts=bootstrap.commands.artifacts,
        read_call_id=original_read,
    )
    identity = previous.id if previous else uuid4()
    command.payload["prepared_event_id"] = str(identity)
    body = {
        "type": CANDIDATE,
        "intent_key": intent_key,
        "command": command.model_dump(mode="json"),
        "cancel_epoch": run.cancel_epoch,
        "source": source.model_dump(mode="json"),
        "model_binding": binding.model_dump(mode="json"),
        "read_call_id": str(proof.read_call_id),
        "snapshot_digest": proof.snapshot_digest,
    }
    if previous and previous.body != body:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原候选已绑定不同内容或来源。")
    if previous is None:
        previous = AgentEvent(
            id=identity,
            tenant_id=run.tenant_id,
            run_id=run.id,
            sequence=_sequence(session, run.id),
            body=body,
        )
        session.add(previous)
        session.flush()
    return {
        "command": previous.body["command"],
        "requires_human": True,
        "write_tier": "T1",
        "state": "candidate",
        "event_id": str(previous.id),
    }


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from pdos_next.contracts import Command
    from pdos_next.domain.preproject.access import human

    from .execution import command_call, command_run

    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前范围版本已变化。")
    if ctx.agent_run_id:
        if payload.prepared_event_id or payload.confirmation_token:
            _deny("snapshot_candidate_ai_adoption_forbidden")
        run = command_run(session, ctx, scope.id)
        command_call(session, ctx, command.operation)
        return _proof(session, run, payload.snapshot_id)
    human(session, ctx)
    if payload.prepared_event_id is None:
        _deny("snapshot_candidate_required")
    event = session.get(AgentEvent, payload.prepared_event_id)
    run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.id == event.run_id if event else AgentRun.id.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not event
        or event.tenant_id != ctx.tenant_id
        or event.body.get("type") != CANDIDATE
        or not run
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.product_id != scope.id
        or run.requester_id != ctx.requester_id
        or run.cancel_epoch != event.body.get("cancel_epoch")
        or run.reverted_at
        or run.state not in {"queued", "running", "waiting_input", "completed", "partial"}
    ):
        _deny("snapshot_candidate_binding_invalid")
    writer = session.get(Principal, run.writer_id)
    if not writer or not writer.active or writer.kind != "agent":
        _deny("snapshot_candidate_writer_invalid")
    try:
        original = Command.model_validate(event.body["command"])
        if _command_material(original) != _command_material(command):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原候选已绑定不同内容或来源。")
        _verify_candidate_source(session, run, event)
        proof = _proof(
            session,
            run,
            payload.snapshot_id,
            read_call_id=UUID(event.body["read_call_id"]),
        )
        if proof.snapshot_digest != event.body["snapshot_digest"]:
            _deny("snapshot_candidate_content_changed")
    except (ValidationError, KeyError, TypeError, ValueError):
        _deny("snapshot_candidate_binding_invalid")
    return proof


def validate(session, ctx, command, scope, payload):
    prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    proof = prepared(session, ctx, command, scope, payload)
    return {
        "payload": semantic(payload),
        "snapshot_id": str(proof.snapshot.id),
        "title": proof.snapshot.title,
        "url": proof.snapshot.url,
        "content_hash": proof.snapshot.content_hash,
        "visibility": proof.visibility,
        "registered_by_run_id": str(proof.run.id),
        "effect": "登记实际读取的快照原文，保留原运行与来源。",
    }


def apply(session, ctx, command, scope, payload):
    proof = prepared(session, ctx, command, scope, payload)
    if session.get(PublicWebSnapshot, proof.snapshot.id) is not None:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "此快照已有登记回执。")
    receipt_id = uuid4()
    row = PublicWebSnapshot(
        **asdict(proof.snapshot),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        visibility=proof.visibility,
        registered_by_run_id=proof.run.id,
        receipt_id=receipt_id,
    )
    row.revision = 1
    row.prepared_receipt_id = receipt_id
    row.action_result = {
        "proof_version": 1,
        "snapshot_id": str(row.id),
        "content_hash": row.content_hash,
        "registered_by_run_id": str(proof.run.id),
    }
    if payload.prepared_event_id:
        row.prepared_by_run_id = proof.run.id
        row.action_result["prepared_by_run_id"] = str(proof.run.id)
    return row, "public_web_snapshot", proof.visibility


def _sequence(session, run_id):
    return (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run_id,
            )
        )
        + 1
    )


def finalize_receipt(session, ctx, command, scope, payload, subject, receipt):
    from .proposal_context import admit_created

    admit_created(session, subject, receipt)
    if payload.prepared_event_id is None:
        return
    session.add(
        AgentEvent(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            run_id=subject.prepared_by_run_id,
            sequence=_sequence(session, subject.prepared_by_run_id),
            body={
                "type": "snapshot_candidate_adopted",
                "prepared_event_id": str(payload.prepared_event_id),
                "receipt_id": str(receipt.id),
            },
        )
    )
    session.flush()
