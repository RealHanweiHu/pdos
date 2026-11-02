"""Explicit candidate startup integration; no publisher/qualification is synthesized."""

from pdos_next.domain.change import controlled_owner as controlled
from pdos_next.domain.change import order_integration as change_order_integration
from pdos_next.domain.change import selection_integration as change_selection_integration
from pdos_next.domain.change.completion_adapter import FormalChangeCompletionOwner
from pdos_next.domain.quality.followup import service as followup


def configure(engine):
    change_order_integration.configure_integration(
        engine,
        policy_read=controlled.policy_callback,
        policy_refresh=controlled.policy_callback,
        selection_read=controlled.selection_callback,
        selection_refresh=controlled.selection_callback,
    )
    change_selection_integration.configure(engine)
    # Preserve the trusted pre-existing investigation callback. A missing formal
    # owner never falls back to it; configuration itself imports/grants nothing.
    old = getattr(engine, "_pdos_quality_followup", None)
    if old is None:
        return None
    completion = FormalChangeCompletionOwner(engine, investigation=old.assess_action_completion)
    followup.configure_followup(
        engine,
        append_issue=old.append_issue,
        consumed_proof=old.consumed_proof,
        assess_action_completion=completion,
    )
    return completion
