"""Workflow-side helpers and the Activity-side node shell, without a Temporal server."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError

from pdos_next.errors import DomainError
from pdos_next.workflows import graph_nodes
from pdos_next.workflows.graph_runtime import AnswerRefs, check_reference, stop_code


def reference():
    return {key: str(uuid4()) for key in (
        "tenant_id", "category_id", "actor_id", "requester_id", "subject_id",
    )}


def test_answer_queue_preserves_distinct_refs_and_deduplicates():
    answers = AnswerRefs()
    first, second = str(uuid4()), str(uuid4())
    for value in (first, second, first, first.upper()):
        answers.offer(value)
    assert answers.queue == [first, second] and answers.seen == {first, second}


@pytest.mark.parametrize("value", [None, {}, {"receipt_id": str(uuid4())}, 1, "", "approved"])
def test_signal_payload_cannot_supply_business_answer_or_receipt(value):
    answers = AnswerRefs()
    answers.offer(value)
    assert answers.queue == [] and answers.seen == set()


@pytest.mark.parametrize("change", [
    lambda ref: {**ref, "api_key": "x"}, lambda ref: {**ref, "subject_id": 1},
    lambda ref: {k: v for k, v in ref.items() if k != "tenant_id"}, lambda ref: "reference",
])
def test_workflow_accepts_only_the_fixed_reference(change):
    check_reference(reference())
    with pytest.raises(ApplicationError) as error:
        check_reference(change(reference()))
    assert error.value.non_retryable


def activity_error(cause):
    return ActivityError(
        "failed", scheduled_event_id=1, started_event_id=2, identity="worker",
        activity_type="xiaopai.model", activity_id="1", retry_state=None,
    ), cause


def test_only_a_stopped_node_names_its_code():
    def code(cause):
        error, _ = activity_error(cause)
        error.__cause__ = cause
        return stop_code(error)

    assert code(ApplicationError("x", type="CANCELLED_RUN", non_retryable=True)) == "CANCELLED_RUN"
    # Attempts or time ran out: the outcome is unknown and reconciliation decides.
    assert code(ApplicationError("x", type="CANCELLED_RUN")) is None
    assert code(ApplicationError("x", type="not a code", non_retryable=True)) is None
    assert code(TimeoutError("x", type=None, last_heartbeat_details=[])) is None


def guarded(body):
    return graph_nodes._guarded(body, {}, {}, None)


def test_node_shell_stops_on_a_domain_error_and_retries_only_a_lost_database():
    def refused(*_):
        raise DomainError("FORBIDDEN_SCOPE", "synthetic")

    with pytest.raises(ApplicationError) as error:
        guarded(refused)
    assert error.value.type == "FORBIDDEN_SCOPE" and error.value.non_retryable

    def lost(*_):
        raise OperationalError("synthetic", {}, ConnectionError())

    with pytest.raises(OperationalError):  # Temporal retries this one
        guarded(lost)

    def broken(*_):
        raise RuntimeError("private detail must not travel")

    with pytest.raises(ApplicationError) as error:
        guarded(broken)
    assert error.value.type == "INTERNAL_ERROR" and error.value.non_retryable
    assert "private detail" not in str(error.value)


def test_node_shell_runs_the_body_inside_the_registered_graph():
    from pdos_agent_runtime.graph import in_registered_agent_graph

    assert not in_registered_agent_graph()
    assert guarded(lambda *_: {"inside": in_registered_agent_graph()}) == {"inside": True}


def test_node_shell_keeps_the_body_identity_the_plugin_caches_by():
    def read_personal_summary(state, context, stop):
        return {}

    node = graph_nodes.activity_node(read_personal_summary)
    assert asyncio.iscoroutinefunction(node)
    assert (node.__module__, node.__qualname__) == (
        read_personal_summary.__module__, read_personal_summary.__qualname__,
    )


def test_missing_worker_dependency_is_a_visible_stop():
    with pytest.raises(DomainError) as error:
        graph_nodes.dependency("not-configured")
    assert error.value.code == "SOURCE_UNAVAILABLE"
