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
from pdos_next.change_coverage_binding import covered_graph
from pdos_next.contracts import Command
from pdos_next.domain.change_coverage_owner import owner
from pdos_next.domain.change_execution import service as impact
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.models import Audit, Category, Grant, Outbox, Principal, Receipt, RequestKey

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
    target["visibility"] = "category"
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
    if operation == "change.effectivity.record":
        return {
            **target,
            "item_id": uuid4(),
            "lot": {"id": uuid4(), "revision": 1},
            "sample_refs": [{"kind": "sample", "id": uuid4(), "revision": 1}],
            "confirmation_token": "offline-tail-confirmation-token",
        }
    if operation == "change.verification.record":
        return {
            **target,
            "mappings": [
                {
                    "item_id": uuid4(),
                    "run": {"kind": "test_run", "id": uuid4(), "revision": 1},
                    "sample_id": uuid4(),
                    "test_item_id": "voltage",
                    "method": e.source.model_dump(mode="json"),
                    "requirement_sha256": "a" * 64,
                    "rationale": "Explicit offline fixed sample/method applicability",
                }
            ],
            "text": "Offline independent completion verification",
            "approval_token": "offline-tail-approval-token",
        }
    if operation == "change.close":
        return {
            **target,
            "text": "Offline separate named completion close",
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
        e.rows.append(
            Category(
                id=e.ctx.category_id,
                tenant_id=e.ctx.tenant_id,
                owner_id=e.ctx.requester_id,
                name="explicit offline category",
                purpose="offline guard boundary",
                status="active",
                revision=1,
            )
        )
        e.rows.extend(
            (
                writer,
                Grant(
                    id=uuid4(),
                    tenant_id=e.ctx.tenant_id,
                    category_id=e.ctx.category_id,
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
        e.ctx = common.Context(e.ctx.tenant_id, writer.id, writer.id, category_id=e.ctx.category_id)
        assert e.publisher.id != e.ctx.actor_id
        operation = request.param
        product = next(row for row in e.rows if type(row) is common.Product)
        command = Command(
            command_id=uuid4(),
            idempotency_key="offline-coverage-common-tail-" + operation,
            operation=operation,
            category_id=e.ctx.category_id,
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
                if operation in {
                    "change.implementation.record",
                    "change.effectivity.record",
                    "change.verification.record",
                    "change.close",
                }:
                    e.current = owner.read_retained(
                        e.s,
                        e.ctx,
                        e.pid,
                        change_id=e.material.change_id,
                        purpose=e.material.purpose,
                        graph=covered_graph(e.graph, e.current),
                        saved=e.current.source_basis,
                    )
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
                    visibility="category",
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
                return row, "change_request", "category"

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
        # Actual common branching and final owner guards, with SQL ports
        # explicitly substituted. This fixture never proves app RLS or bytes.
        monkeypatch.setattr(common, "require_access", lambda *a, **k: product)
        monkeypatch.setattr(common, "prove_sources", lambda *a: None)

        def remember(session, ctx, key, request_digest, receipt):
            session.add(
                RequestKey(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    actor_id=ctx.actor_id,
                    key=key,
                    digest=request_digest,
                    receipt_id=receipt.id,
                )
            )

        monkeypatch.setattr(common, "remember_key", remember)
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
