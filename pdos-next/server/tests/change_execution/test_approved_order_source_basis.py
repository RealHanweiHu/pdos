"""Pure approved_order regression with real kernel snapshots and transient ORM.

SQL, source IO, shared-proof and professional owners are explicit substitutes.
These checks prove their invocation and the artifact-wrapper contract, never real
qualification, source authorization, a persisted common atom or PostgreSQL.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from pdos_next import change_controlled_owner as controlled
from pdos_next import change_order_store as store
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context

from . import kernel_helpers as helper
from .test_change_order import no_connection  # noqa: F401 - forbid DB/HTTP in this pure file


def approved_material(monkeypatch):
    host = helper.FakeHost()
    host.prepare()
    stages = [("order", host.request_value, host.request_value.requester_id)]
    for discipline in ("engineering", "manufacturing"):
        host.actor(f"basis-approver-{discipline}", (discipline,))
        host.run(
            "change.order.approve",
            {
                "discipline": discipline,
                "text": f"Actual kernel {discipline} approval",
                "expires_at": helper.NOW + timedelta(hours=12),
            },
        )
        stages.append((discipline, host.request_value, host.authority.actor_id))
    request, order = host.request_value, host.order
    session = object()
    ctx = Context(helper.SCOPE.tenant_id, helper.uid("basis-reader"), helper.uid("basis-reader"))
    rows, atoms, actual, groups, expected = [], [], {}, {}, {}
    calls = {"proof": [], "authority": [], "sources": [], "group": []}
    for label, fixed, actor in stages:
        operation = "change.order.prepare" if label == "order" else "change.order.approve"
        parent = ChangeRequestVersion(
            id=helper.uid(f"basis-parent-{label}"),
            tenant_id=helper.SCOPE.tenant_id,
            product_id=helper.SCOPE.product_id,
            project_id=helper.SCOPE.project_id,
            change_id=request.id,
            revision=fixed.revision,
            status=fixed.status,
            operation=operation,
            request_snapshot=fixed.model_dump(mode="json"),
            request_sha256=controlled.digest(fixed),
        )
        source = SourceRef(
            id=helper.uid(f"basis-original-{label}"),
            revision=1,
            kind="artifact",
            position="line:1;quote_sha256:" + controlled.digest(label),
        )
        artifacts = {
            str(source.id): {
                "revision": source.revision,
                "sha256": controlled.digest({"actual_original": label}),
                "owner_id": str(actor),
                "visibility": "category",
            }
        }
        wrapper = {
            "artifacts": deepcopy(artifacts),
            "owners": {label: {"id": str(parent.id), "revision": parent.revision}},
            "outputs": {},
            "verified_sources": [source.model_dump(mode="json")],
            "closure": {"sha256": controlled.digest({"fixed_parent": str(parent.id)})},
            "coverage": {"retained_original": label},
        }
        atom_type = store.ChangeOrderRecord if label == "order" else store.ChangeApprovalRecord
        values = {
            "id": helper.uid(f"basis-atom-{label}"),
            "tenant_id": helper.SCOPE.tenant_id,
            "product_id": helper.SCOPE.product_id,
            "project_id": helper.SCOPE.project_id,
            "change_id": request.id,
            "change_version_id": parent.id,
            "change_revision": parent.revision,
            "order_id": order.id,
            "actor_id": actor,
            "owner_id": request.requester_id,
            "visibility": "category",
            "operation": operation,
            "sources": [source.model_dump(mode="json")],
            "required_source_read_set": [{"artifact_id": str(source.id), "expected_revision": 1}],
            "source_basis": wrapper,
        }
        if label == "order":
            values.update(
                content_sha256=order.content_digest,
                order_snapshot=fixed.orders[-1].model_dump(mode="json"),
            )
        else:
            decision = fixed.orders[-1].approvals[-1]
            values.update(
                discipline=label,
                approval_snapshot=decision.model_dump(mode="json"),
                shared_proof_id=decision.decision_id,
            )
        atom = atom_type(**values)
        rows.extend((parent, atom))
        atoms.append(atom)
        actual[str(source.id)] = artifacts
        groups[parent.id] = {
            "receipt": {
                "id": helper.uid(f"basis-receipt-{label}"),
                "subject_type": "change_request",
            }
        }
        expected[parent.id] = (
            atom,
            "change.order_prepared" if label == "order" else "change.approved",
        )

    def one(s, model, *where):
        assert s is session
        keys = {clause.left.name: clause.right.value for clause in where}
        assert keys["tenant_id"] == ctx.tenant_id
        assert keys["product_id"] == helper.SCOPE.product_id
        assert keys["change_id"] == request.id
        matches = [
            row
            for row in rows
            if type(row) is model and all(getattr(row, key) == value for key, value in keys.items())
        ]
        assert len(matches) == 1, (model, keys)
        return matches[0]

    def group(s, caller, pid, parent, *, operation, event, actor):
        atom, expected_event = expected[parent.id]
        assert (s, caller, pid) == (session, ctx, helper.SCOPE.product_id)
        assert (operation, event, actor) == (atom.operation, expected_event, atom.actor_id)
        calls["group"].append(atom.id)
        return groups[parent.id]

    def proof(s, caller, pid, atom, received):
        assert (s, caller, pid) == (session, ctx, helper.SCOPE.product_id)
        assert received is groups[atom.change_version_id]
        calls["proof"].append(atom.id)

    def authority(s, caller, pid, atom):
        assert (s, caller, pid) == (session, ctx, helper.SCOPE.product_id)
        calls["authority"].append(atom.id)
        # Distinct actual owner deadlines ensure all three results are used.
        return helper.NOW + timedelta(hours=3 - atoms.index(atom))

    def sources(s, caller, pid, visibility, owner_id, reads, refs):
        assert (s, caller, pid) == (session, ctx, helper.SCOPE.product_id)
        assert visibility == "category" and owner_id == request.requester_id
        assert len(refs) == 1
        assert reads == [{"artifact_id": str(refs[0].id), "expected_revision": refs[0].revision}]
        calls["sources"].append(refs[0].id)
        return deepcopy(actual[str(refs[0].id)])

    monkeypatch.setattr(controlled, "_one", one)
    monkeypatch.setattr(controlled, "common_group", group)
    monkeypatch.setattr(controlled, "_atom_proof", proof)
    monkeypatch.setattr(controlled, "original_authority", authority)
    monkeypatch.setattr(controlled, "_source_guard", sources)
    return SimpleNamespace(
        session=session,
        ctx=ctx,
        request=request,
        order=order,
        atoms=atoms,
        actual=actual,
        calls=calls,
    )


def invoke(work):
    return controlled.approved_order(
        work.session, work.ctx, helper.SCOPE.product_id, work.request, work.order
    )


def test_approved_order_uses_artifact_layer_and_rechecks_all_three_original_owners(monkeypatch):
    work = approved_material(monkeypatch)

    deadline = invoke(work)

    assert deadline == helper.NOW + timedelta(hours=1)
    ids = [atom.id for atom in work.atoms]
    assert work.calls["group"] == work.calls["proof"] == work.calls["authority"] == ids
    assert work.calls["sources"] == [
        SourceRef.model_validate(atom.sources[0]).id for atom in work.atoms
    ]
    assert all(
        set(atom.source_basis)
        == {"artifacts", "owners", "outputs", "verified_sources", "closure", "coverage"}
        for atom in work.atoms
    )


@pytest.mark.parametrize("atom_index", range(3), ids=["order", "engineering", "manufacturing"])
@pytest.mark.parametrize(
    "change", ["artifact_changed", "missing", "empty", "not_map", "direct_map"]
)
def test_approved_order_rejects_changed_or_missing_artifact_layer(monkeypatch, atom_index, change):
    work = approved_material(monkeypatch)
    atom = work.atoms[atom_index]
    if change == "artifact_changed":
        source_id = atom.required_source_read_set[0]["artifact_id"]
        work.actual[source_id][source_id]["sha256"] = controlled.digest("changed actual original")
    elif change == "missing":
        del atom.source_basis["artifacts"]
    elif change == "empty":
        atom.source_basis["artifacts"] = {}
    elif change == "not_map":
        atom.source_basis["artifacts"] = []
    else:
        atom.source_basis = deepcopy(atom.source_basis["artifacts"])

    with pytest.raises(DomainError) as error:
        invoke(work)
    assert error.value.reason == "SOURCE_STALE"
