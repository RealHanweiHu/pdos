"""Declared native-fact events resolve only through the actual committed receipt."""

from sqlalchemy import select

from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.external_wait.models import ExternalWaitVersion
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.supply_execution.models import SupplySnapshot
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import TestResultActionFact
from pdos_next.service import EVENTS as DOMAIN_EVENTS

from . import field_feedback_events, role_native_events

QUALITY = frozenset(
    {
        "quality.issue.create",
        "quality.issue.merge",
        "quality.issue.triage",
        "quality.issue.containment.record",
        "quality.capa.draft",
        "quality.issue.root_cause.decide",
        "quality.capa.actions.complete",
    }
)
CHANGE = frozenset(
    {
        "change.request.create",
        "change.impact.compute",
        "change.order.prepare",
        "change.order.approve",
        "change.implementation.record",
        "change.effectivity.record",
        "change.verification.record",
        "change.close",
    }
)
RUN = frozenset(
    {
        "test.run.plan",
        "test.run.start",
        "test.results.import",
        "test.run.review",
        "test.disposition.decide",
    }
)
BUILD = {
    "build.create": Build,
    "build.start": BuildStart,
    "build.configuration.actual.record": ActualConfiguration,
    "build.output.record": BuildLot,
}
OPERATIONS = (
    QUALITY
    | CHANGE
    | RUN
    | field_feedback_events.OPERATIONS
    | role_native_events.OPERATIONS
    | {
        "work.external_wait.record",
        "supply.snapshot.record",
        *BUILD,
    }
)
EVENTS = frozenset(DOMAIN_EVENTS[operation] for operation in OPERATIONS)


def targets(session, event, receipt):
    operation = receipt.operation
    if DOMAIN_EVENTS.get(operation) != event.type or operation not in OPERATIONS:
        return []
    if operation in role_native_events.OPERATIONS:
        return role_native_events.targets(session, event, receipt)
    if operation in field_feedback_events.OPERATIONS:
        return field_feedback_events.targets(session, event, receipt)
    if operation in QUALITY:
        model, kinds = QualityIssueVersion, ("issue", "capa")
    elif operation in CHANGE:
        model, kinds = ChangeRequestVersion, ("change",)
    elif operation in RUN:
        model, kinds = VerificationRunVersion, ("test_run",)
    elif operation == "work.external_wait.record":
        model, kinds = ExternalWaitVersion, ("external_wait",)
    elif operation == "supply.snapshot.record":
        model, kinds = SupplySnapshot, ("supply",)
    else:
        model, kinds = BUILD[operation], ("build",)
    query = select(model.id).where(
        model.tenant_id == event.tenant_id,
        model.category_id == event.category_id,
        model.product_id == receipt.product_id,
    )
    if operation in QUALITY | CHANGE:
        snapshot = model.issue_snapshot if operation in QUALITY else model.request_snapshot
        # Domain intent and common receipt intent use different canonical inputs.
        # The appended kernel history carries the actual common command identity,
        # including every version changed by an Issue merge.
        query = query.where(
            model.operation == operation,
            snapshot["history"][-1]["command_id"].astext == str(receipt.command_id),
        )
    elif operation in RUN:
        query = query.where(
            model.operation == operation,
            model.revision == receipt.subject_revision,
            (model.id == receipt.subject_id) | (model.run_id == receipt.subject_id),
        )
    elif operation == "work.external_wait.record":
        query = query.where(model.receipt_id == receipt.id)
    else:
        query = query.where(model.id == event.subject_id)
    identities = list(session.scalars(query))
    result = [(kind, identity) for identity in identities for kind in kinds]
    if operation in {"test.results.import", "test.run.review", "test.disposition.decide"}:
        result += [
            ("test_run", identity)
            for identity in session.scalars(
                select(TestResultActionFact.id).where(
                    TestResultActionFact.tenant_id == event.tenant_id,
                    TestResultActionFact.category_id == event.category_id,
                    TestResultActionFact.product_id == receipt.product_id,
                    TestResultActionFact.actor_id == receipt.actor_id,
                    TestResultActionFact.operation == operation,
                    TestResultActionFact.next_run_version_id.in_(identities),
                    TestResultActionFact.next_run_revision == receipt.subject_revision,
                )
            )
        ]
    return result
