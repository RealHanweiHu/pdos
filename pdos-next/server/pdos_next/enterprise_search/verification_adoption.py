"""Recheck assistant provenance inside ordinary Human verification commands.

Only persisted server events and native receipts establish a bridge. Client
payloads cannot attach a source proof, replace an event or confer permission.
The native command owners still enforce every T1 and professional domain rule.
"""

from sqlalchemy import Text, and_, cast, select

from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Receipt

from . import verification_candidates as bridge
from .action_sources import recheck


def _reject():
    raise DomainError("FORBIDDEN_SCOPE", "复验办理与原候选、固定准备或真实回执无法核对。", 403)


def _same_command(command, frozen):
    """The native T1 confirmation token is the only mutable candidate field."""
    actual, expected = command.model_dump(mode="json"), frozen.model_dump(mode="json")
    for value in (actual, expected):
        value["payload"].pop("confirmation_token", None)
    if actual != expected:
        _reject()


def _preparation_candidate(session, ctx, event):
    # read() checks the real Run/model/skill/source ledger and rechecks all
    # auxiliary discussion and execution references in this same transaction.
    view = bridge.read(session, ctx, event.run_id, event.id)
    command = Command.model_validate(view["command"])
    if command.operation != bridge.PREPARATION:
        _reject()
    return view, command


def recheck_preparation(session, ctx, command):
    """Bind native preview/execute to its actual persisted candidate, if any."""
    events = session.scalars(
        select(AgentEvent)
        .where(
            AgentEvent.tenant_id == ctx.tenant_id,
            AgentEvent.body["type"].astext == bridge.EVENT,
            AgentEvent.body["command"]["command_id"].astext == str(command.command_id),
        )
        .limit(2)
    ).all()
    if not events:
        return  # Independently authored Human preparations retain native rules.
    if len(events) != 1:
        _reject()
    _view, frozen = _preparation_candidate(session, ctx, events[0])
    _same_command(command, frozen)


def recheck_request(session, ctx, preparation):
    """Trace an actual preparation's receipt to its parent candidate, if any.

    The preparation is loaded by the native owner under ordinary RLS, with its
    expected revision and SHA already checked. This stage needs no new model
    response: the Human submits the existing professional request command.
    """
    pairs = session.execute(
        select(Receipt, AgentEvent)
        .join(
            AgentEvent,
            and_(
                AgentEvent.tenant_id == Receipt.tenant_id,
                AgentEvent.body["type"].astext == bridge.EVENT,
                AgentEvent.body["command"]["command_id"].astext
                == cast(Receipt.command_id, Text),
            ),
        )
        .where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.category_id == ctx.category_id,
            Receipt.product_id == preparation.product_id,
            Receipt.operation == bridge.PREPARATION,
            Receipt.subject_type == "verification_preparation",
            Receipt.subject_id == preparation.id,
            Receipt.subject_revision == preparation.revision,
        )
        .limit(2)
    ).all()
    if not pairs:
        return  # No bridge provenance on this actual native preparation.
    if len(pairs) != 1:
        _reject()
    receipt, event = pairs[0]
    view, command = _preparation_candidate(session, ctx, event)
    binding = bridge.preparation_binding(command, receipt, preparation)
    proof = recheck(
        session,
        ctx,
        session.get(AgentRun, event.run_id),
        view["source_proof"],
        preparation_id=preparation.id,
    )
    target = proof["target"]
    if (
        target["preparation_id"] != binding["preparation_id"]
        or target["preparation_revision"] != binding["expected_preparation_revision"]
        or target["preparation_sha256"] != binding["preparation_sha256"]
    ):
        _reject()
