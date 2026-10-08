"""Offline common-tail fixtures with actual owner, explicit domain/SQL substitutes.

No complete Impact, formal approval, actual qualification, commit, SQL or
database constraint acceptance is asserted by these boundary experiments.
"""

import importlib.util
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from change_execution import kernel_helpers

import pdos_next.models  # noqa: F401 - register before runtime imports
from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.change_coverage_owner import owner
from pdos_next.domain.change_execution import service as impact
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.models import Audit, Grant, Outbox, Principal, Receipt, RequestKey

SERVER = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "_wave28_tail_owner_fixture", SERVER / "tests/change_coverage_owner/test_owner_boundary.py"
)
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)

OPERATIONS = (
    "change.impact.compute",
    "change.order.prepare",
    "change.order.approve",
    "change.implementation.record",
)


def payload_for(e, operation):
    target = {"change_id": e.material.change_id, "expected_change_revision": 1}
    if operation == "change.impact.compute":
        return {**target, "snapshot": {"id": e.graph.id, "revision": 1, "kind": "graph_snapshot"}}
    target["visibility"] = "product"
    if operation == "change.order.prepare":
        return {
            **target,
            "assessment_id": uuid4(),
            "plan": kernel_helpers.plan()
            .model_copy(update={"expires_at": e.at + timedelta(minutes=10)})
            .model_dump(mode="json"),
            "reason": "Offline common-tail order experiment",
            "confirmation_token": "offline-tail-confirmation-token",
        }
    if operation == "change.order.approve":
        return {
            **target,
            "discipline": "engineering",
            "text": "Offline common-tail approval experiment",
            "expires_at": e.at + timedelta(minutes=10),
            "sources": [e.source.model_dump(mode="json")],
            "approval_token": "offline-tail-approval-token",
        }
    return {
        **target,
        "item_id": uuid4(),
        "fact_id": uuid4(),
        "confirmation_token": "offline-tail-confirmation-token",
    }


@pytest.fixture(params=OPERATIONS)
def case(request, monkeypatch):
    generator = existing.env.__wrapped__(monkeypatch)
    e = next(generator)
    try:
        e.publisher = next(row for row in e.rows if isinstance(row, Principal))
        writer = Principal(
            id=uuid4(),
            tenant_id=e.ctx.tenant_id,
            name="distinct current writer",
            active=True,
            kind="human",
            access_epoch=1,
        )
        e.rows.extend(
            (
                writer,
                Grant(
                    id=uuid4(),
                    tenant_id=e.ctx.tenant_id,
                    product_id=e.pid,
                    principal_id=writer.id,
                    can_write=True,
                    access_epoch=1,
                    expires_at=e.at + timedelta(minutes=20),
                ),
            )
        )
        # Set the writer permission before the publication's temporal material
        # is captured. Do not grant authority after a saved owner proof exists.
        existing.publish(e)
        e.ctx = common.Context(e.ctx.tenant_id, writer.id, writer.id)
        assert e.publisher.id != e.ctx.actor_id
        operation = request.param
        product = next(row for row in e.rows if type(row) is common.Product)
        command = Command(
            command_id=uuid4(),
            idempotency_key="offline-coverage-common-tail-" + operation,
            operation=operation,
            product_id=e.pid,
            expected_revision=product.revision,
            source_read_set=[{"artifact_id": e.source.id, "expected_revision": e.source.revision}],
            payload=common.PAYLOADS[operation]
            .model_validate(payload_for(e, operation))
            .model_dump(mode="json"),
        )
        e.command, e.trace, e.drift, e.current = command, [], None, None
        e.domain_runtime, e.attach, e.closure = None, None, None

        def guard():
            owner.recheck_access(
                e.s,
                e.ctx,
                e.pid,
                e.current,
                request=e.request,
                purpose=e.material.purpose,
            )
            e.trace.append("coverage_guard")

        class DomainSubstitute:
            # Common branching, serialization and tail stay actual. Concrete
            # coverage read/last guard stay actual. Domain mutation and T1/T2
            # confirmation are substitutes, not formal approval evidence.
            deduplicate_subject = ()

            def semantic(self, payload):
                return payload.model_dump(
                    mode="json", exclude={"approval_token", "confirmation_token"}
                )

            def validate(self, *args):
                e.current = existing.read(e)
                e.domain_runtime = impact._runtime_stamp(e.s)
                guard()

            def prepare_write_review(self, *args):
                self.validate(*args)
                return object(), {"offline": "review"}

            def apply(self, *args):
                if e.current is None:
                    self.validate(*args)
                guard()
                return self.subject()

            def apply_prepared_write(self, *args, **kwargs):
                # Stand in for the original prepared refresh before domain save.
                guard()
                return self.subject()

            def subject(self):
                row = ChangeRequestVersion(
                    id=uuid4(),
                    tenant_id=e.ctx.tenant_id,
                    product_id=e.pid,
                    project_id=e.scope.project_id,
                    change_id=e.material.change_id,
                    revision=2,
                    status="analysis",
                    operation=command.operation,
                    owner_id=e.ctx.actor_id,
                    visibility="product",
                    source_basis={
                        "coverage": deepcopy(e.current.source_basis),
                        "closure": deepcopy(e.closure),
                    },
                    created_at=e.at,
                )
                e.trace.append("domain_return")
                e.subject = row
                if e.attach is not None:
                    e.attach(row)
                return row, "change_request", "product"

        module = DomainSubstitute()
        e.module = module
        monkeypatch.setattr(common, "handler", lambda op: module if op == operation else None)
        monkeypatch.setattr(
            common, "consume_material_confirmation", lambda *a, **k: (object(), object())
        )
        monkeypatch.setattr(e.s, "scalar", lambda query: next(iter(e.s.scalars(query)), None))
        monkeypatch.setattr(
            e.s,
            "get",
            lambda cls, identity: next(
                row for row in e.rows if isinstance(row, cls) and row.id == identity
            ),
        )
        original_flush = e.s.flush

        def flush(*args, **kwargs):
            original_flush(*args, **kwargs)
            receipts = [
                row
                for row in e.rows
                if isinstance(row, Receipt) and row.command_id == command.command_id
            ]
            if receipts:
                r = receipts[0]
                e.receipt = r
                groups = [
                    row
                    for row in e.rows
                    if isinstance(row, (Audit, Outbox, RequestKey)) and row.receipt_id == r.id
                ]
                if {type(row) for row in groups} == {Audit, Outbox, RequestKey}:
                    e.trace.append("after_full_common_flush")
                    if e.drift is not None:
                        e.drift()

        monkeypatch.setattr(e.s, "flush", flush)
        yield e
    finally:
        generator.close()
