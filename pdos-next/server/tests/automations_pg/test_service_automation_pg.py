"""Actual service grants/admissions; only root executes this guarded PG/HTTP slice.

The shared setup supplies real local human/agent identities and ordinary engines.
No model, external network, alternate clock or direct business-row writes are used.
Temporal waiting is outside this slice: its actual tick Activity is called directly.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.dispatch.outbox import acknowledge, claim_events
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.models import AutomationRuleCurrent
from pdos_next.domain.automations.schemas import ACTIVATE, DRAFT_SAVE, PAUSE
from pdos_next.domain.automations.service_models import (
    AutomationCausalChain,
    AutomationServiceAttempt,
    AutomationServiceGrant,
)
from pdos_next.models import Confirmation, Grant, now
from pdos_next.safety import verify_test_target
from pdos_next.service import EVENTS, digest
from tests.agent_kernel import test_budget_management as budgets
from tests.agent_kernel import test_skill_management as skills
from tests.automations_pg.test_manual_workflow import (
    assert_common_group,
    new_trigger,
    path,
    reading,
    save,
    snapshot,
)
from tests.test_trusted_source_work import source


def _ready(setup):
    for engine in (setup.admin, setup.engine, setup.dispatch):
        verify_test_target(engine)
    skills.promote(setup)
    enabled = skills.post(setup, skills.preview(setup, skills.command(setup))["command"])
    assert enabled.status_code == 200, enabled.text
    _, wallet = budgets.allocate(setup)
    return wallet


def _spec(setup, wallet, *, kind="schedule", config=None):
    skill = SkillCatalog().configuration("public_research")
    return {
        "name": "Synthetic actual service automation",
        "goal": "Read actual category facts without network, MCP or business writes",
        "purpose": "Isolated service admission verification; no production qualification",
        "stop_condition": "Stop after the explicitly bounded read-only inspection",
        "trigger_kind": kind,
        "trigger_config": config
        or {
            "first_at": (now() - timedelta(minutes=5)).isoformat(),
            "original_timezone": "UTC",
            "interval_seconds": None,
            "expires_at": None,
        },
        "conditions": {"task_id": None, "only_states": [], "stop_states": ["completed"]},
        "max_cascade_depth": 3,
        "external_sources_enabled": False,
        "product_id": str(setup.product),
        "skill_keys": [{"key": skill.key, "version": skill.version, "digest": skill.digest}],
        "validation_budget_id": wallet["subject_id"],
        "token_limit": 1000,
        "budget": {
            "limit_micro_usd": 100_000,
            "input_token_limit": 1000,
            "output_token_limit": 1000,
            "call_limit": 3,
        },
        "cooldown_seconds": 0,
        "max_runs": 3,
        "allow_network": False,
        "mcp_tools": [],
        "cross_object_write": False,
    }


def _state(setup):
    result = snapshot(setup)
    with Session(setup.admin) as session:
        for model in (AutomationServiceGrant, AutomationCausalChain, AutomationServiceAttempt):
            rows = session.scalars(select(model).where(model.tenant_id == setup.tenant)).all()
            result[model.__tablename__] = sorted(
                digest({column.name: getattr(row, column.name) for column in model.__table__.c})
                for row in rows
            )
    return result


def _control(setup, rule, operation=ACTIVATE):
    version = rule["draft"] or rule["published"]
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(setup.category),
        "product_id": None,
        "operation": operation,
        "expected_revision": reading(setup)["category_revision"],
        "source_read_set": [],
        "payload": {
            "rule_id": rule["id"],
            "expected_rule_revision": rule["revision"],
            "version_id": version["id"],
        },
    }


def _activate(setup, spec):
    draft_command, draft_receipt = save(
        setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": deepcopy(spec)}
    )
    rule_id = draft_receipt["result"]["rule_id"]
    rule = reading(setup, rule_id)["rule"]
    command = _control(setup, rule)
    prepared = skills.preview(setup, command)
    authorization = prepared["review"]["service_authorization"]
    assert authorization["service_principal_id"] == str(setup.agent)
    assert authorization["delegator_id"] == str(setup.human)
    assert authorization["category_id"] == str(setup.category)
    assert authorization["product_id"] == str(setup.product)
    assert authorization["budget"] == spec["budget"]
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(AutomationServiceGrant.id).where(
                    AutomationServiceGrant.tenant_id == setup.tenant
                )
            )
            is None
        )
        current = session.scalar(
            select(AutomationRuleCurrent).where(AutomationRuleCurrent.rule_id == UUID(rule_id))
        )
        assert current.state == "draft" and current.admitted_count == 0
    command = prepared["command"]
    assert command["payload"]["confirmation_token"]
    response = skills.post(setup, command)
    assert response.status_code == 200, response.text
    receipt = response.json()
    with Session(setup.admin) as session:
        assert_common_group(session, setup, draft_command, draft_receipt)
        version = assert_common_group(session, setup, command, receipt)
        grant = session.scalar(
            select(AutomationServiceGrant).where(
                AutomationServiceGrant.published_version_id == version.id
            )
        )
        assert grant is not None
        assert grant.owner_id == setup.human and grant.writer_id == setup.agent
        assert grant.owner_id != grant.writer_id
        assert grant.rule_id == version.rule_id == UUID(rule_id)
        assert grant.receipt_id == version.receipt_id == UUID(receipt["id"])
        proof = session.get(Confirmation, version.confirmation_id)
        assert proof.consumed and proof.actor_id == setup.human
        assert proof.snapshot["service_authorization"] == authorization
        ref = service_runtime.reference(grant)
    current = reading(setup, rule_id)["rule"]
    assert current["state"] == "active" and current["admitted_count"] == 0
    assert current["service_grant"]["id"] == ref["grant_id"]
    assert current["service_grant"]["service_principal_id"] == str(setup.agent)
    return rule_id, ref


def test_actual_t1_schedule_grant_single_tick_and_pause_keep_original_ai_run(setup):
    wallet = _ready(setup)
    spec = _spec(setup, wallet)
    rule_id, ref = _activate(setup, spec)
    result = service_runtime.tick(setup.engine, ref)
    assert result["state"] == "active"
    assert datetime.fromisoformat(result["wake_at"]).utcoffset() is not None
    with Session(setup.admin) as session:
        attempts = session.scalars(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"])
            )
        ).all()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.state == "admitted" and attempt.error_code is None
        assert attempt.origin["kind"] == attempt.trigger_kind == "schedule"
        assert attempt.origin["original_timezone"] == "UTC"
        assert attempt.depth == 0 and attempt.parent_run_id is None
        assert attempt.admitted_at >= attempt.created_at
        run_id = attempt.run_id
        run = session.get(AgentRun, run_id)
        assert run.trigger == service_runtime.TRIGGER
        assert run.writer_id == setup.agent and run.requester_id == setup.human
        assert run.writer_id != run.requester_id
        assert run.product_id == setup.product and run.category_id == setup.category
        assert run.validation_budget_id == UUID(wallet["subject_id"])
        assert run.intent_digest == attempt.request_digest
        assert run.state == "queued" and run.cancel_epoch == 0
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.run_id == run.id)) is None
        )
        assert session.scalar(select(AgentEvent.id).where(AgentEvent.run_id == run.id))
    store = KernelStore(setup.engine)
    bound = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=run_id,
    )
    with store.transaction(bound) as (session, run):
        actor, requester = session.execute(
            text("SELECT public.scope_actor(),public.scope_requester()")
        ).one()
        assert actor == run.writer_id == setup.agent
        assert requester == run.requester_id == setup.human
        actual, fixed = service_runtime.run_binding(session, run)
        assert actual.run_id == run_id and fixed.trigger_kind == "schedule"
    before_repeat = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    assert _state(setup) == before_repeat
    active = reading(setup, rule_id)["rule"]
    assert active["admitted_count"] == 1
    forbidden = setup.client.post(
        path(setup, rule_id) + "/trigger", headers=setup.headers, json=new_trigger(active)
    )
    assert forbidden.status_code == 403 and forbidden.json()["code"] == "FORBIDDEN_SCOPE"
    assert _state(setup) == before_repeat
    save(
        setup,
        PAUSE,
        {
            "rule_id": rule_id,
            "expected_rule_revision": active["revision"],
            "version_id": active["published"]["id"],
        },
    )
    paused = reading(setup, rule_id)
    assert paused["rule"]["state"] == "paused"
    assert paused["rule"]["service_grant"]["state"] == "paused"
    before_paused_tick = _state(setup)
    assert service_runtime.tick(setup.engine, ref) == {
        "state": "stopped",
        "wake_at": None,
        "reason": "PAUSED",
    }
    assert _state(setup) == before_paused_tick
    # A pause stops admissions. It cannot impersonate cancellation of the old Run.
    with store.transaction(bound) as (_, run):
        assert run.id == run_id and run.state == "queued" and run.cancel_epoch == 0
    response = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{run_id}", headers=setup.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["run_id"] == str(run_id)
    assert response.json()["status"] == "queued"
    # Exercise the real recovery dispatcher and complete Activity entry with the
    # stored agent actor. Missing adapters remain visible without a model call.
    import asyncio

    from pdos_next.agent_kernel.activities import KernelActivities
    from pdos_next.agent_kernel.temporal_port import dispatch_pending_runs

    references = []

    class CapturePort:
        async def start(self, reference):
            references.append(reference)

    delivered = asyncio.run(dispatch_pending_runs(setup.dispatch, setup.tenant, CapturePort()))
    assert delivered == {"delivered": 1, "unavailable": 0}
    assert references[0]["actor_id"] == str(setup.agent)
    assert references[0]["requester_id"] == str(setup.human)
    sentinel = object()
    original = getattr(setup.engine, "_pdos_agent_kernel_adapters", sentinel)
    setup.engine._pdos_agent_kernel_adapters = None
    try:
        result = KernelActivities(setup.engine, technical_engine=setup.dispatch).advance(
            references[0]
        )
    finally:
        if original is sentinel:
            del setup.engine._pdos_agent_kernel_adapters
        else:
            setup.engine._pdos_agent_kernel_adapters = original
    assert result["status"] == "waiting_input" and result["error_code"] == "SOURCE_UNAVAILABLE"
    with Session(setup.admin) as session:
        assert session.get(AgentRun, run_id).state == "waiting_input"
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.run_id == run_id)) is None
        )

    with Session(setup.admin) as session, session.begin():
        revoked = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.agent,
            )
        )
        session.delete(revoked)
    stopped = KernelActivities(setup.engine, technical_engine=setup.dispatch).advance(references[0])
    assert stopped["status"] == "failed" and stopped["error_code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session:
        assert session.get(AgentRun, run_id).state == "failed"
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.run_id == run_id)) is None
        )

    halted = service_runtime.tick(setup.engine, ref)
    assert halted == {"state": "stopped", "wake_at": None, "reason": "SCOPE_INVALID"}
    with Session(setup.admin) as session:
        diagnostic = session.scalar(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"]),
                AutomationServiceAttempt.origin["kind"].astext == "lifecycle",
            )
        )
        assert diagnostic.state == "suppressed" and diagnostic.error_code == "SCOPE_INVALID"
        assert diagnostic.run_id is None

    # Restoring category access does not erase the actual stop or restart its
    # supervisor. A new named service authorization is a separate operation.
    with Session(setup.admin) as session, session.begin():
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=setup.category,
                principal_id=setup.agent,
                can_write=revoked.can_write,
                expires_at=revoked.expires_at,
            )
        )
    restored = _state(setup)
    assert service_runtime.tick(setup.engine, ref) == halted
    assert _state(setup) == restored


def test_actual_expired_schedule_stays_draft_without_new_confirmation_grant_or_run(setup):
    wallet = _ready(setup)
    point = now()
    spec = _spec(
        setup,
        wallet,
        config={
            "first_at": (point - timedelta(days=2)).isoformat(),
            "original_timezone": "UTC",
            "interval_seconds": None,
            "expires_at": (point - timedelta(days=1)).isoformat(),
        },
    )
    _, saved = save(setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": spec})
    rule_id = saved["result"]["rule_id"]
    draft = reading(setup, rule_id)["rule"]
    before = _state(setup)
    rejected = skills.post(setup, _control(setup, draft), "commands/preview")
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "VERSION_CONFLICT"
    assert _state(setup) == before
    final = reading(setup, rule_id)
    assert final["rule"]["state"] == "draft"
    assert final["rule"]["service_grant"] is None
    assert final["runs"] == [] and final["triggers"] == []


def test_actual_original_event_lease_is_retained_suppressed_and_never_admitted(setup):
    wallet = _ready(setup)
    spec = _spec(
        setup,
        wallet,
        kind="domain_event",
        config={
            "event_types": [EVENTS["evidence.artifact.register"]],
            "subject_id": None,
            "merge_window_seconds": 0,
            "expires_at": None,
        },
    )
    rule_id, ref = _activate(setup, spec)
    artifact_id, _ = source(setup)
    # Use the actual dispatcher-issued lease. No client-created event envelope is trusted.
    envelopes = claim_events(setup.dispatch, setup.tenant, limit=100)
    targets = [event for event in envelopes if event.subject_id == artifact_id]
    assert len(targets) == 1
    event = targets[0]
    assert event.event_type == EVENTS["evidence.artifact.register"]
    assert event.actor_id == event.requester_id == str(setup.human)
    before_wrong_actor = _state(setup)
    assert (
        service_runtime.queue_event(setup.engine, ref, replace(event, actor_id=str(setup.agent)))
        is None
    )
    assert _state(setup) == before_wrong_actor
    attempt_id = service_runtime.queue_event(setup.engine, ref, event)
    assert attempt_id is not None
    before_replay = _state(setup)
    assert service_runtime.queue_event(setup.engine, ref, event) == attempt_id
    assert _state(setup) == before_replay
    for envelope in envelopes:
        assert acknowledge(setup.dispatch, envelope, ignored=True)
    with Session(setup.admin) as session:
        attempt = session.get(AutomationServiceAttempt, UUID(attempt_id))
        assert attempt.state == "suppressed" and attempt.error_code == "EXTERNAL_TRIGGER_DISABLED"
        assert attempt.run_id is None and attempt.admitted_at is None
        assert attempt.origin["event_id"] == event.event_id
        assert attempt.origin["subject_id"] == artifact_id
        assert attempt.origin["operation"] == "evidence.artifact.register"
        assert attempt.origin["source_kind"] == "external_input"
        assert session.scalar(select(AgentRun.id).where(AgentRun.tenant_id == setup.tenant)) is None
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    final = reading(setup, rule_id)
    assert final["rule"]["admitted_count"] == 0 and final["runs"] == []
    matching = [row for row in final["triggers"] if row["id"] == attempt_id]
    assert len(matching) == 1 and matching[0]["decision"] == "suppressed"
    assert matching[0]["error_code"] == "EXTERNAL_TRIGGER_DISABLED"
    assert matching[0]["run_id"] is None
