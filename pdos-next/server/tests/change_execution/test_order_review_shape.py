"""Compare host reviews with real kernel execution; only synthetic facts/proof ports."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from pdos_next import change_order_service as owner
from pdos_next import change_order_store as store
from pdos_next.contracts import Command
from pdos_next.domain.change_control.rules import replace
from pdos_next.service import Context

from . import kernel_helpers as helper
from .test_change_order import no_connection  # noqa: F401 - shared autouse connection guard


def differing_leaves(left, right, path=()):
    """Compare complete values without reimplementing the production mask."""
    assert type(left) is type(right), path
    if isinstance(left, dict):
        assert left.keys() == right.keys(), path
        return set().union(*(differing_leaves(left[key], right[key], (*path, key)) for key in left))
    if isinstance(left, list):
        assert len(left) == len(right), path
        return set().union(
            *(
                differing_leaves(a, b, (*path, index))
                for index, (a, b) in enumerate(zip(left, right, strict=True))
            )
        )
    return set() if left == right else {path}


@pytest.mark.parametrize("step", ["prepare", "engineering", "manufacturing"])
def test_order_review_matches_real_execution_except_new_server_clock_and_named_id(
    monkeypatch, step
):
    host = helper.FakeHost()
    if step == "prepare":
        host.analyze()
        payload = store.OrderPreparePayload(
            change_id=host.request_value.id,
            expected_change_revision=host.request_value.revision,
            visibility="category",
            assessment_id=host.request_value.assessments[-1].id,
            plan=helper.plan(),
            reason="Controlled actual plan",
        )
        operation = "change.order.prepare"
    else:
        host.prepare()
        if step == "manufacturing":
            host.actor("first-engineering-approver", ("engineering",))
            host.run(
                "change.order.approve",
                {
                    "discipline": "engineering",
                    "text": "Retain this first named approval",
                    "expires_at": helper.NOW + timedelta(hours=1),
                },
            )
        host.actor(f"current-{step}-approver", (step,))
        payload = store.OrderApprovePayload(
            change_id=host.request_value.id,
            expected_change_revision=host.request_value.revision,
            visibility="category",
            discipline=step,
            text="Actual named approval",
            expires_at=helper.NOW + timedelta(hours=1),
            sources=(helper.SOURCE,),
        )
        operation = "change.order.approve"
    before = host.request_value
    before_json = before.model_dump(mode="json")
    ctx = Context(helper.SCOPE.tenant_id, host.authority.actor_id, host.authority.requester_id)
    command = Command(
        command_id=helper.uid(f"review-shape-command-{step}"),
        idempotency_key=f"review-shape-{step}",
        operation=operation,
        category_id=helper.uid("category"),
        product_id=helper.SCOPE.product_id,
        expected_revision=1,
        payload=payload.model_dump(mode="json"),
    )
    phase = SimpleNamespace(
        request=before,
        scope=before.scope,
        payload_semantic=owner.semantic(payload),
        authority=host.authority.model_dump(mode="json"),
        reads=[],
        sources=before.sources,
        policy=host.policy,
        source_basis={},
        selections={},
    )
    preview_at = helper.NOW + timedelta(seconds=10)
    with monkeypatch.context() as preview_ports:
        # Reuse the real ChangeControlHandler. Only its synthetic caller-port
        # transaction check differs for the host's deliberately non-writing read.
        preview_ports.setattr(owner, "kernel", lambda *args: host.handler)
        preview_ports.setattr(host, "check", lambda uow: None)
        preview_ports.setattr(owner, "clock", lambda: preview_at)
        review = owner._review(ctx, command, payload, phase)
    assert host.request_value is before
    assert review["before"] == before_json

    actual_at = preview_at + timedelta(seconds=1)
    host.authority = replace(host.authority, now=actual_at)
    parsed = owner.parsed_payload(payload)
    invocation = host.invocation(operation, parsed, command=command.command_id)
    invocation = host.proof(invocation, parsed)
    host.execute(invocation, parsed)
    actual = host.request_value.model_dump(mode="json")
    proposed = review["after"]

    assert proposed["revision"] == actual["revision"] == before.revision + 1
    assert len(proposed["history"]) == len(actual["history"]) == len(before.history) + 1
    assert proposed["history"][:-1] == actual["history"][:-1] == before_json["history"]
    assert proposed["assessments"] == actual["assessments"] == before_json["assessments"]
    assert proposed["sources"] == actual["sources"] == before_json["sources"]
    assert proposed["history"][-1]["command_id"] == str(command.command_id)
    assert actual["history"][-1]["command_id"] == str(command.command_id)
    assert proposed["history"][-1]["at"] == "server_on_save"
    assert actual["history"][-1]["at"] == actual_at.isoformat().replace("+00:00", "Z")

    allowed = {("history", len(before.history), "at")}
    if step != "prepare":
        old_approvals = before_json["orders"][-1]["approvals"]
        assert proposed["orders"][-1]["approvals"][:-1] == old_approvals
        assert actual["orders"][-1]["approvals"][:-1] == old_approvals
        approval = proposed["orders"][-1]["approvals"][-1]
        assert approval["at"] == "server_on_save"
        assert approval["decision_id"] == "actual_consumed_named_proof_on_save"
        assert actual["orders"][-1]["approvals"][-1]["decision_id"] == str(invocation.decision_id)
        path = ("orders", len(actual["orders"]) - 1, "approvals", len(old_approvals))
        allowed.update({(*path, "at"), (*path, "decision_id")})
    assert differing_leaves(proposed, actual) == allowed
