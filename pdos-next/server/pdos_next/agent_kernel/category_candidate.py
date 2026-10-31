"""Personal-run category material, sealed by the server for one Human T1 adoption."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from pydantic import Field, ValidationError
from sqlalchemy import func, select

from pdos_next.database import require_context
from pdos_next.domain.preproject.category_creation import CategoryCreate, InitialGroups
from pdos_next.domain.preproject.category_service import _references
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from . import policy
from .bindings import ModelBinding, WriteSource, execution_key
from .deterministic_proofs import _historical_read
from .disclosure import binding_operations, disclosure
from .execution import _check_session, check_run_binding, scope_for_run, validate_skill_load
from .models import AgentEvent, AgentRun, AgentSession, AgentToolCall
from .snapshot_command import verify_snapshot_page

OPERATION = "category.create"
CANDIDATE = "category_candidate"


class CategoryCandidateInput(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1)
    groups: InitialGroups = Field(default_factory=InitialGroups)


@dataclass(frozen=True)
class CategorySnapshotProof:
    snapshot: object
    read_call_id: UUID
    snapshot_digest: str
    page_start: int
    page_end: int

    def manifest(self):
        return {
            "snapshot_id": str(self.snapshot.id),
            "read_call_id": str(self.read_call_id),
            "content_hash": self.snapshot.content_hash,
            "snapshot_digest": self.snapshot_digest,
            "page_start": self.page_start,
            "page_end": self.page_end,
        }


@dataclass(frozen=True)
class CategoryProof:
    run: object
    event: object
    snapshots: tuple[CategorySnapshotProof, ...]


def _deny(reason="category_candidate_source_invalid"):
    error = DomainError(
        "SOURCE_UNAVAILABLE", "新品类候选须来自当前授权的实际个人运行和可核对来源。",
    )
    error.detail["reason"] = reason
    raise error


def _owner(session):
    owner = session.info.get("category_candidate_owner") or session.info.get("domain_command_owner")
    if owner is None:
        owner = getattr(session.get_bind(), "_pdos_category_candidate_owner", None)
    if owner is None:
        _deny("category_candidate_owner_unavailable")
    return owner


def _artifacts(owner):
    return (
        getattr(owner, "artifacts", None)
        or getattr(getattr(owner, "commands", None), "artifacts", None)
        or getattr(getattr(owner, "ports", None), "research_artifacts", None)
    )


def _personal(session, run, scope, *, preparing=False):
    check_run_binding(run, scope, for_write=preparing)
    if (
        run.state not in {"queued", "running", "waiting_input", "completed", "partial"}
        or any(getattr(run, key) is not None
               for key in ("category_id", "product_id", "proposal_id"))
        or run.private_context or run.customer_identities or run.read_sources
        or set(run.data_categories) & {"customer", "customer_original"}
        or scope.isolation != "main"
    ):
        _deny("category_personal_run_required")
    conversation = session.get(AgentSession, run.session_id)
    if (
        not conversation or conversation.tenant_id != run.tenant_id
        or conversation.owner_id != run.requester_id
        or any(getattr(conversation, key) is not None
               for key in ("category_id", "product_id", "proposal_id"))
    ):
        _deny("category_personal_session_required")
    for identity, kind in ((run.requester_id, "human"), (run.writer_id, "agent")):
        principal = session.get(Principal, identity)
        if (
            not principal or principal.tenant_id != run.tenant_id
            or principal.kind != kind or not principal.active
        ):
            _deny("category_principal_inactive")


def _source(session, run, owner, source, binding, arguments, intent_key, *, spec=None):
    """Recheck the historical model and current skill/route without T0 qualification."""
    scope = scope_for_run(run)
    model = session.get(AgentToolCall, source.model_call_id)
    current = owner.registry.get(OPERATION)
    route = owner.route(session, scope)
    disclosed = disclosure(
        owner.registry, binding.isolation, binding_operations(owner.catalog, binding.loaded_skills)
    )
    if (
        not model or model.tenant_id != run.tenant_id or model.run_id != run.id
        or model.tool != "model" or model.state != "completed"
        or model.error_code is not None or model.receipt_id is not None
        or digest(model.execution_binding) != digest(binding.model_dump(mode="json"))
        or binding.isolation != "main" or binding.cancel_epoch != run.cancel_epoch
        or source.skill.key != "category_framing" or source.skill not in binding.loaded_skills
        or intent_key != execution_key(run.id, model.id, source.response_index)
        or not route or binding.model_version != route.version
        or binding.model_route_digest != route.digest
        or binding.model_version != run.versions.get("model_version")
        or binding.model_route_digest != run.versions.get("model_route_digest")
        or binding.tool_definitions_digest != run.versions.get("tool_definitions", {}).get("main")
        or binding.prompt_digest != run.versions.get("prompt_prefixes", {}).get("main")
        or current.name != OPERATION or current.operation_key != OPERATION
        or current.kind != "write" or current.tier != "T1"
        or current.input_schema != CategoryCandidateInput.model_json_schema()
        or (spec is not None and current != spec)
        or digest(disclosed) != binding.tool_definitions_digest
        or not any(item["name"] == OPERATION for item in disclosed)
    ):
        _deny()
    try:
        original = model.result["calls"][source.response_index]
        if original["name"] != OPERATION or digest(original["arguments"]) != digest(arguments):
            _deny()
        value = CategoryCandidateInput.model_validate(arguments)
    except (TypeError, KeyError, IndexError, ValidationError):
        _deny()
    validate_skill_load(session, scope, source.skill)
    skill = owner.catalog.load(
        source.skill.key, scope, lambda _, item: policy.skill_enabled(session, scope, item)
    )
    if (
        skill.version != source.skill.version or skill.digest != source.skill.digest
        or OPERATION not in skill.operations
    ):
        _deny("category_skill_changed")
    return value


def _snapshots(session, run, refs, artifacts):
    if refs and artifacts is None:
        _deny("category_snapshot_artifacts_unavailable")
    scope = scope_for_run(run)
    result, seen = [], set()
    for ref in refs:
        if ref.call_id in seen:
            _deny("category_duplicate_snapshot_read")
        seen.add(ref.call_id)
        _, call, binding, arguments = _historical_read(
            session, scope, ref.call_id, "ordinary/v1", deny=_deny,
        )
        if call.tool != "research.read" or binding.isolation != "research":
            _deny("category_snapshot_read_required")
        try:
            identity = UUID(call.result["snapshot_id"])
            snapshot = artifacts.snapshot(scope, identity)
            if snapshot.id != identity or snapshot.content_hash != ref.content_hash:
                _deny("category_snapshot_identity_mismatch")
            verify_snapshot_page(snapshot, call.result, arguments)
            _, start, end = call.result["locator"].split(":")
            result.append(CategorySnapshotProof(
                snapshot, call.id, digest(asdict(snapshot)), int(start), int(end),
            ))
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            _deny("category_snapshot_artifacts_unavailable")
    return tuple(result)


def _quote_in_page(ref, proof):
    if ref.version != 1 or not ref.line or not ref.quote or not ref.quote.strip():
        return False
    lines = proof.snapshot.markdown.splitlines(keepends=True)
    if ref.line > len(lines):
        return False
    offset = sum(map(len, lines[:ref.line - 1]))
    line = lines[ref.line - 1].rstrip("\r\n")
    cursor = 0
    while (found := line.find(ref.quote, cursor)) >= 0:
        if proof.page_start <= offset + found and offset + found + len(ref.quote) <= proof.page_end:
            return True
        cursor = found + 1
    return False


def _knowledge(session, run, knowledge, snapshots):
    for item in knowledge:
        refs = _references(item)
        if item.kind in {"competitor", "voice", "regulation"} and not refs:
            _deny("category_knowledge_source_required")
        for ref in refs:
            if ref.type == "human":
                person = session.get(Principal, ref.id)
                if (
                    not person or person.tenant_id != run.tenant_id or person.kind != "human"
                    or not person.active or not ref.statement or not ref.statement.strip()
                ):
                    _deny("category_human_source_invalid")
            elif ref.type == "snapshot":
                if not any(p.snapshot.id == ref.id and _quote_in_page(ref, p) for p in snapshots):
                    _deny("category_snapshot_quote_unread")
            else:
                _deny("category_source_scope_invalid")


def candidate_digest(run, body):
    """Public algorithm for the immutable ledger and its database guard."""
    return digest({
        "operation": OPERATION, "tenant_id": str(run.tenant_id), "run_id": str(run.id),
        "requester_id": str(run.requester_id), "writer_id": str(run.writer_id),
        "body": {key: value for key, value in body.items() if key != "candidate_digest"},
    })


def _events(session, run):
    return session.scalars(select(AgentEvent).where(
        AgentEvent.tenant_id == run.tenant_id, AgentEvent.run_id == run.id,
        AgentEvent.body["type"].astext == CANDIDATE,
    )).all()


def prepare(session, scope, spec, arguments, intent_key, bootstrap):
    _check_session(session, scope)
    run = session.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    _personal(session, run, scope, preparing=True)
    try:
        prefix, run_id, kind, model_id, index = intent_key.split(":")
        model_id, index = UUID(model_id), int(index)
        if prefix != "agent" or kind != "model" or run_id != str(run.id) or index < 0:
            _deny()
        model = session.get(AgentToolCall, model_id)
        binding = ModelBinding.model_validate(model.execution_binding)
        skills = [skill for skill in binding.loaded_skills if skill.key == "category_framing"]
        if len(skills) != 1:
            _deny()
        source = WriteSource(skill=skills[0], model_call_id=model_id, response_index=index)
        value = _source(session, run, bootstrap, source, binding, arguments, intent_key, spec=spec)
    except (ValueError, AttributeError, ValidationError):
        _deny()
    snapshots = _snapshots(session, run, value.groups.snapshot_refs, _artifacts(bootstrap))
    _knowledge(session, run, value.groups.knowledge, snapshots)
    body = {
        "type": CANDIDATE, "intent_key": intent_key, "session_id": str(run.session_id),
        "cancel_epoch": run.cancel_epoch, "input": value.model_dump(mode="json"),
        "arguments": deepcopy(arguments), "source": source.model_dump(mode="json"),
        "model_binding": binding.model_dump(mode="json"),
        "snapshots": [item.manifest() for item in snapshots],
    }
    body["candidate_digest"] = candidate_digest(run, body)
    previous = [event for event in _events(session, run)
                if event.body.get("intent_key") == intent_key]
    if previous:
        if len(previous) != 1 or previous[0].body != body:
            _deny("category_candidate_changed")
        event = previous[0]
    else:
        sequence = session.scalar(select(func.max(AgentEvent.sequence)).where(
            AgentEvent.run_id == run.id,
        )) or 0
        event = AgentEvent(
            id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, sequence=sequence + 1, body=body,
        )
        session.add(event)
        session.flush()
    payload = CategoryCreate(
        **value.model_dump(mode="json"), deidentified_confirmed=False,
        prepared_by_run_id=run.id, candidate_digest=body["candidate_digest"],
        idempotency_key=f"category-candidate:{event.id}",
    )
    return {
        "payload": payload.model_dump(mode="json"), "requires_human": True,
        "write_tier": "T1", "state": "candidate", "event_id": str(event.id),
    }


def validate(session, ctx, data, *, artifacts=None, _read_only=False):
    require_context(session, ctx)
    query = select(AgentRun).where(
        AgentRun.id == data.prepared_by_run_id,
    ).execution_options(populate_existing=True)
    run = session.scalar(query if _read_only else query.with_for_update())
    if (
        not run or not data.candidate_digest or data.seed_key is not None
        or ctx.tenant_id != run.tenant_id or ctx.requester_id != run.requester_id
        or ctx.actor_id != run.requester_id or ctx.category_id is not None
        or ctx.run_id is not None or ctx.agent_run_id is not None
    ):
        _deny("category_candidate_requester_mismatch")
    _personal(session, run, scope_for_run(run))
    events = [event for event in _events(session, run)
              if event.body.get("candidate_digest") == data.candidate_digest]
    if len(events) != 1:
        _deny("category_candidate_not_found")
    event = events[0]
    body = event.body
    owner = _owner(session)
    try:
        if (
            set(body) != {"type", "intent_key", "session_id", "cancel_epoch", "input", "arguments",
                          "source", "model_binding", "snapshots", "candidate_digest"}
            or body["type"] != CANDIDATE or event.tenant_id != run.tenant_id
            or event.run_id != run.id or body["session_id"] != str(run.session_id)
            or type(body["cancel_epoch"]) is not int or body["cancel_epoch"] != run.cancel_epoch
            or body["candidate_digest"] != candidate_digest(run, body)
        ):
            _deny("category_candidate_changed")
        source = WriteSource.model_validate(body["source"])
        binding = ModelBinding.model_validate(body["model_binding"])
        if (digest(source.model_dump(mode="json")) != digest(body["source"])
                or digest(binding.model_dump(mode="json")) != digest(body["model_binding"])):
            _deny()
        original = _source(
            session, run, owner, source, binding, body["arguments"], body["intent_key"],
        )
        if original.model_dump(mode="json") != body["input"]:
            _deny("category_candidate_changed")
        for key in ("key", "name", "purpose"):
            if getattr(data, key) != getattr(original, key):
                _deny("category_candidate_content_changed")
        chosen = data.groups.model_dump(mode="json")
        for group, items in chosen.items():
            if items and items != body["input"]["groups"][group]:
                _deny("category_candidate_group_changed")
        # Revalidate the complete original manifest before permitting any selection.
        # A retained candidate cannot silently change sources while awaiting adoption.
        all_snapshots = _snapshots(
            session, run, original.groups.snapshot_refs, artifacts or _artifacts(owner),
        )
        if [item.manifest() for item in all_snapshots] != body["snapshots"]:
            _deny("category_candidate_snapshot_changed")
        snapshots = all_snapshots if data.groups.snapshot_refs else ()
        _knowledge(session, run, data.groups.knowledge, snapshots)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, ValidationError):
        _deny()
    return CategoryProof(run, event, snapshots)


def read_metadata(session, ctx, run, event):
    """Run the native pending proof in this readonly session; never acquire write locks."""
    if (event.tenant_id != run.tenant_id or event.run_id != run.id
            or event.body.get("type") != CANDIDATE):
        _deny()
    if (run.reverted_at or run.state == "cancelled"
            or event.body.get("cancel_epoch") != run.cancel_epoch):
        return {"operation": OPERATION, "state": "cancelled", "receipt_id": None}
    original = CategoryCandidateInput.model_validate(event.body["input"])
    data = CategoryCreate(
        **original.model_dump(mode="json"),
        deidentified_confirmed=False,
        prepared_by_run_id=run.id,
        candidate_digest=event.body["candidate_digest"],
        idempotency_key=f"category-candidate:{event.id}",
    )
    proof = validate(session, ctx, data, _read_only=True)
    if proof.event.id != event.id:
        _deny()
    return {"operation": OPERATION, "state": "pending", "receipt_id": None}
