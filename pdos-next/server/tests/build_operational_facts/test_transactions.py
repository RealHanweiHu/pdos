"""Root-only PG/host-UOW checks. No synthetic qualification is production proof."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_builds import accepted, build_command, configuration, definition, project  # noqa: F401
from test_project_first_plan import cmd, post

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.build_operational_facts.service import disable_issuer, load_bundle, reserve
from pdos_next.domain.builds.models import BuildReadiness
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Grant, Outbox, Receipt, RequestKey, now
from pdos_next.service import Context

from .fixtures import (  # noqa: F401
    bundle,
    fact_payload,
    imported,
    known_configuration,
    operational_work,
)


def count(work, model):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        return s.scalar(select(func.count()).select_from(model))


def fact(work, receipt):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        row = s.get(BuildOperationalFact, UUID(receipt["subject_id"]))
        s.expunge(row)
        return row


def successor(work, first, transform=None):
    data = work.payload.model_dump(mode="json")
    data.update(expected_previous_id=str(first.id), expected_previous_revision=first.revision)
    if transform:
        transform(data)
    return FactInput.model_validate(data)


def test_known_fixed_demand_host_import_and_category_clock_stability(operational_work):
    work = operational_work
    result = imported(work)
    one, two = bundle(work), bundle(work, at=now())
    assert one.state == two.state == "READY"
    assert one.facts_revision == two.facts_revision
    assert one.coverage.lines[0].demand.required_quantity == 22
    assert one.resources.capacity_status == "checked" and one.nature == "synthetic"
    assert one.binding.basis.build.build_id == work.build_id
    assert result["subject_type"] == "build_operational_fact"
    assert one.required_source_read_set[0].artifact_id == UUID(work.config["source"])
    assert count(work, MaterialHold) == count(work, ResourceOccupancy) == 0


def test_import_same_and_alias_key_replays_one_receipt_without_rewriting_assets(operational_work):
    work, key = operational_work, str(uuid4())
    first = imported(work, request_key=key)
    again = imported(work, request_key=key)
    alias = imported(work)
    assert first["id"] == again["id"] == alias["id"]
    assert count(work, BuildOperationalFact) == count(work, BuildOperationalCurrent) == 1
    assert count(work, OperationalAsset) == 2
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "build.operational_facts.import")
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count()).select_from(Audit).where(Audit.receipt_id == UUID(first["id"]))
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.receipt_id == UUID(first["id"]))
            )
            == 1
        )
        assert set(s.scalars(select(OperationalAsset.occupancy_epoch))) == {1}
    changed = work.payload.model_dump(mode="json")
    changed["reason"] = "Different intention"
    with pytest.raises(DomainError, match="同一导入编号") as caught:
        imported(work, changed, request_key=key)
    assert caught.value.reason == "DUPLICATE_INTENT_CONFLICT"


def test_history_replay_never_rewinds_current_bundle_or_global_asset(operational_work):
    work = operational_work
    first = fact(work, imported(work))
    updated = successor(work, first, lambda d: d["materials"][0].update(version=2, quantity="30"))
    second_receipt = imported(work, updated)
    replay = imported(work)
    assert replay["subject_id"] == str(first.id)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        current = s.scalar(select(BuildOperationalCurrent))
        asset = s.scalar(select(OperationalAsset).where(OperationalAsset.kind == "material"))
        assert str(current.fact_id) == second_receipt["subject_id"] and current.fact_revision == 2
        assert asset.revision == 2 and asset.data["value"]["quantity"] == "30"
    assert count(work, BuildOperationalFact) == 2


def test_import_replay_retains_receipt_after_source_withdrawal_and_new_intent_blocks(
    operational_work,
):
    work, key = operational_work, str(uuid4())
    original = imported(work, request_key=key)
    with Session(work.setup.admin) as s, s.begin():
        s.execute(
            update(Artifact)
            .where(Artifact.id == UUID(work.config["source"]))
            .values(status="withdrawn", revision=2)
        )
    assert imported(work, request_key=key)["id"] == original["id"]
    changed = work.payload.model_copy(update={"external_id": "SYN-NEW-INTENT"})
    with pytest.raises(DomainError) as caught:
        imported(work, changed)
    assert caught.value.reason == "SOURCE_UNAVAILABLE"
    assert count(work, BuildOperationalFact) == 1


def test_current_acl_is_independent_of_physical_facts_and_named_decision_guard(
    operational_work,
):
    work = operational_work
    imported(work)
    old = bundle(work)
    work.named_current = False
    changed = bundle(work)
    assert changed.state != "READY" and changed.facts_revision != old.facts_revision
    work.named_current = True
    with Session(work.setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
            )
        )
        original_expiry = grant.expires_at
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as caught:
        bundle(work)
    assert caught.value.reason == "FORBIDDEN_SCOPE"
    with Session(work.setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human)
            .values(expires_at=original_expiry)
        )
    restored = bundle(work)
    assert restored.state == "READY" and restored.facts_revision == old.facts_revision
    assert imported(work)["id"] == imported(work)["id"]


@pytest.mark.parametrize("case", ["issuer", "private_peer", "agent", "other_tenant"])
def test_opaque_scope_and_current_person_guard_without_productgrant_upgrade(operational_work, case):
    work = operational_work
    imported(work)
    if case == "issuer":
        disable_issuer(work.setup.engine, work.issuer.key)
        assert bundle(work).state == "UNKNOWN"
        return
    identity = (
        work.setup.peer
        if case == "private_peer"
        else work.setup.agent
        if case == "agent"
        else work.setup.other_human
    )
    tenant = uuid4() if case == "other_tenant" else work.setup.tenant
    with tenant_session(
        work.setup.engine, tenant, actor_id=identity, category_id=work.setup.category
    ) as s, pytest.raises(DomainError) as caught:
        load_bundle(
            s,
            Context(tenant, identity, identity, category_id=work.setup.category),
            work.setup.product,
            UUID(work.build_id),
            work.scope,
            now(),
        )
    # A private G0 product gives no audience to the Agent; opacity precedes person checks.
    assert caught.value.reason == "FORBIDDEN_SCOPE"


def test_same_physical_version_different_content_and_bom_quantity_shrinking_are_rejected(
    operational_work,
):
    work = operational_work
    first = fact(work, imported(work))
    changed = successor(work, first, lambda d: d["materials"][0].update(quantity="45"))
    with pytest.raises(DomainError) as caught:
        imported(work, changed)
    assert caught.value.reason == "OPERATIONAL_ASSET_VERSION_CONFLICT"
    with (
        tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as s,
        pytest.raises(DomainError) as caught,
    ):
        load_bundle(
            s,
            work.setup.ctx,
            work.setup.product,
            UUID(work.build_id),
            work.scope.model_copy(update={"quantity": work.scope.quantity / 2}),
            now(),
        )
    assert caught.value.reason == "OPERATIONAL_SCOPE_MISMATCH"
    assert count(work, BuildOperationalFact) == 1


def test_fact_withdrawal_changes_global_epoch_and_blocks_old_bundle(operational_work):
    work = operational_work
    first = fact(work, imported(work))
    previous = bundle(work).facts_revision
    imported(work, successor(work, first, lambda d: d.update(state="withdrawn")))
    assert bundle(work).state == "BLOCKED" and bundle(work).facts_revision != previous
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        assert set(s.scalars(select(OperationalAsset.occupancy_epoch))) == {2}
        assert all(v["state"] == "withdrawn" for v in s.scalars(select(OperationalAsset.data)))


def test_concurrent_successor_cas_keeps_one_complete_atomic_global_version(operational_work):
    work = operational_work
    first = fact(work, imported(work))

    def attempt(quantity):
        proposed = successor(
            work, first, lambda d: d["materials"][0].update(version=2, quantity=quantity)
        )
        try:
            return imported(work, proposed)["subject_id"]
        except DomainError as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("30", "35")))
    assert results.count("VERSION_CONFLICT") == 1
    assert count(work, BuildOperationalFact) == 2
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        assert s.scalar(select(BuildOperationalCurrent.fact_revision)) == 2


def test_terminal_outbox_failure_rolls_back_facts_assets_pointer_and_requestkey(
    operational_work, monkeypatch
):
    from pdos_next import operational_import

    work = operational_work
    models = (
        BuildOperationalFact,
        OperationalAsset,
        BuildOperationalCurrent,
        Receipt,
        Audit,
        Outbox,
        RequestKey,
    )
    before = {model: count(work, model) for model in models}
    original = operational_import.append_receipt

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic outer UOW failure")

    monkeypatch.setattr(operational_import, "append_receipt", fail)
    with pytest.raises(RuntimeError, match="outer UOW"):
        imported(work)
    assert {model: count(work, model) for model in models} == before


def test_reserve_cannot_commit_without_exact_same_uow_buildstart_owner(operational_work):
    work = operational_work
    imported(work)
    selected = bundle(work)
    with pytest.raises(DBAPIError, match="foreign key"):
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as s:
            result = reserve(
                s,
                work.setup.ctx,
                work.setup.product,
                UUID(work.build_id),
                work.scope,
                owner_execution_id=uuid4(),
                intent_digest="a" * 64,
                expected_facts_revision=selected.facts_revision,
                at=now(),
            )
            assert len(result.material_holds) == len(result.resource_reservations) == 1
    assert count(work, MaterialHold) == count(work, ResourceOccupancy) == 0
    assert bundle(work).facts_revision == selected.facts_revision


def test_other_private_build_is_fully_counted_but_hidden_from_public_computation(operational_work):
    work = operational_work
    imported(work)
    created, _ = accepted(
        work.setup,
        build_command(
            work.setup, work.config, name="Synthetic distinct private shared-resource Build"
        ),
    )
    assert created["subject_id"] != work.build_id
    calculated = post(
        work.setup,
        cmd(
            work.setup,
            "build.readiness.compute",
            {
                "build_id": created["subject_id"],
                "expected_build_revision": 1,
            },
            work.config["source"],
        ),
    )
    assert calculated.status_code == 200, calculated.text
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        readiness = s.get(BuildReadiness, UUID(calculated.json()["subject_id"]))
        second_config = {
            **work.config,
            "build_id": created["subject_id"],
            "result": deepcopy(readiness.result),
        }
    second = SimpleNamespace(
        **{**vars(work), "config": second_config, "build_id": second_config["build_id"]}
    )
    second.payload = fact_payload(second)
    imported(second)
    selected = bundle(work)
    owner = uuid4()
    # These are real staged PG rows; deliberate outer rollback avoids inventing
    # a committed BuildStart merely to test the accounting/read boundary.
    with pytest.raises(RuntimeError, match="privacy check rollback"):
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as s:
            reserve(
                s,
                work.setup.ctx,
                work.setup.product,
                UUID(work.build_id),
                work.scope,
                owner_execution_id=owner,
                intent_digest="b" * 64,
                expected_facts_revision=selected.facts_revision,
                at=now(),
            )
            public = load_bundle(
                s, work.setup.ctx, work.setup.product, UUID(second.build_id), second.scope, now()
            )
            assert public.state == "BLOCKED"
            held = public.coverage.input_snapshot.reservations
            assert len(held) == 1 and held[0].quantity == 22
            assert held[0].build_id == "other-builds" and held[0].bom_item_id is None
            serialized = str(public.model_dump(mode="json"))
            assert work.build_id not in serialized and str(owner) not in serialized
            assert "occupancies" not in public.resources.model_dump(mode="json")
            raise RuntimeError("Synthetic privacy check rollback")
    assert count(work, MaterialHold) == count(work, ResourceOccupancy) == 0


def test_exact_source_quote_and_final_tables_have_rls_agent_zero_and_immutable_facts(
    operational_work,
):
    work = operational_work
    bad = work.payload.model_dump(mode="json")
    bad["sources"][0]["quote"] = "Invented released inventory"
    with pytest.raises(DomainError) as caught:
        imported(work, bad)
    assert caught.value.reason == "MISSING_REQUIRED_EVIDENCE"
    saved = fact(work, imported(work))
    with (
        Session(work.setup.admin) as s,
        s.begin(),
        pytest.raises(DBAPIError, match="immutable|Immutable"),
    ):
        s.execute(
            update(BuildOperationalFact)
            .where(BuildOperationalFact.id == saved.id)
            .values(reason="Overwrite fixed fact")
        )
    tables = (
        BuildOperationalFact,
        BuildOperationalCurrent,
        OperationalAsset,
        MaterialHold,
        ResourceOccupancy,
    )
    with Session(work.setup.engine) as s:
        assert all(s.scalar(select(func.count()).select_from(model)) == 0 for model in tables)
    with Session(work.setup.admin) as s:
        for model in tables:
            assert s.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid=CAST(:name AS regclass)"
                ),
                {"name": model.__tablename__},
            ).one() == (True, True)
            assert (
                s.scalar(
                    text("SELECT has_table_privilege('pdos_agent',:name,'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )
