"""Storage-level launch atom faults; root alone runs these PostgreSQL checks.

Only new objects in the caller's unit of work are corrupted. Retained rows and
their triggers are never changed. Six start faults share one real window wait.
"""

# ruff: noqa: F811 - imported fixtures deliberately register their dependencies
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from test_project_first_plan import post
from verification_launch.fixtures import (  # noqa: F401
    accepted_work,
    advance_clock,
    command,
    known_configuration,
    launch_work,
    operational_work,
    planned,
    promised,
    ready_work,
)

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.build_execution.models import ActualConfiguration, SampleUnit
from pdos_next.domain.build_operational_facts.models import OperationalAsset, ResourceOccupancy
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
    TestResourceReservation,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.models import Audit, Confirmation, Outbox, Product, Receipt, RequestKey
from pdos_next.service import digest, execute


def storage_snapshot(work):
    """Counts plus mutable pointers, gates and token state must all roll back."""
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        tables = (
            FormalVerificationRequest,
            FormalVerificationCurrent,
            VerificationRunIdentity,
            VerificationRunVersion,
            VerificationRunCurrent,
            VerificationLaunchFact,
            TestResourceReservation,
            SampleRunUsage,
            SampleUsageSentinel,
            ResourceOccupancy,
            Receipt,
            Audit,
            Outbox,
            RequestKey,
            Confirmation,
        )
        return {
            "counts": {
                model.__tablename__: s.scalar(select(func.count()).select_from(model))
                for model in tables
            },
            "product_revisions": tuple(
                s.execute(select(Product.id, Product.revision).order_by(Product.id))
            ),
            "asset_epochs": tuple(
                s.execute(
                    select(OperationalAsset.id, OperationalAsset.occupancy_epoch).order_by(
                        OperationalAsset.id
                    )
                )
            ),
            "sample_epochs": tuple(
                s.execute(
                    select(SampleUsageSentinel.id, SampleUsageSentinel.epoch).order_by(
                        SampleUsageSentinel.id
                    )
                )
            ),
            "formal_pointers": tuple(
                s.execute(
                    select(
                        FormalVerificationCurrent.id,
                        FormalVerificationCurrent.request_version_id,
                        FormalVerificationCurrent.request_revision,
                    ).order_by(FormalVerificationCurrent.id)
                )
            ),
            "run_pointers": tuple(
                s.execute(
                    select(
                        VerificationRunCurrent.id,
                        VerificationRunCurrent.run_version_id,
                        VerificationRunCurrent.run_revision,
                    ).order_by(VerificationRunCurrent.id)
                )
            ),
            "confirmations": tuple(
                s.execute(select(Confirmation.id, Confirmation.consumed).order_by(Confirmation.id))
            ),
        }


def assert_rollback(work, baseline, prepared=None):
    assert storage_snapshot(work) == baseline
    if prepared is not None:
        token = prepared["payload"]["confirmation_token"]
        with tenant_session(work.setup.engine, work.setup.tenant) as s:
            assert (
                s.scalar(
                    select(Confirmation.consumed).where(Confirmation.token_hash == digest(token))
                )
                is False
            )


def other_physical_sample(work):
    accepted_id = work.binding.pairs[0].sample.id
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        sample = s.scalar(
            select(SampleUnit).where(
                SampleUnit.product_id == work.setup.product,
                SampleUnit.build_id == work.binding.build_id,
                SampleUnit.id != accepted_id,
            )
        )
        assert sample is not None
        actual = s.get(ActualConfiguration, sample.actual_configuration_id)
        assert actual is not None
        return {
            "id": sample.id,
            "revision": sample.revision,
            "actual_id": actual.id,
            "actual_revision": actual.revision,
            "has_gate": s.scalar(
                select(SampleUsageSentinel.id).where(SampleUsageSentinel.sample_id == sample.id)
            )
            is not None,
        }


def corrupt_new_atom(work, case, other, seen):
    def inject(s, flush_context, instances):
        uses = [
            v for v in s.new if isinstance(v, SampleRunUsage) and v.run_id == work.binding.run_id
        ]
        occupancies = [
            v
            for v in s.new
            if isinstance(v, ResourceOccupancy) and v.test_run_id == work.binding.run_id
        ]
        if seen or not uses or len(occupancies) != 2:
            return
        assert len(uses) == 1
        seen.append(case)
        use = uses[0]
        if case == "wrong_same_build_sample":
            assert other["id"] != use.sample_id
            use.sample_id = other["id"]
            use.sample_revision = other["revision"]
            use.actual_configuration_id = other["actual_id"]
            use.actual_configuration_revision = other["actual_revision"]
            use.coverage = [
                {"sample_id": str(other["id"]), "item_id": work.binding.pairs[0].item_id}
            ]
            if not other["has_gate"]:
                s.add(
                    SampleUsageSentinel(
                        tenant_id=work.setup.tenant,
                        product_id=work.setup.product,
                        sample_id=other["id"],
                        epoch=1,
                    )
                )
        elif case == "missing_resource":
            s.expunge(occupancies[0])
        elif case == "wrong_resource_units":
            occupancies[0].units = Decimal("0.5")
        elif case == "wrong_coverage":
            use.coverage = [{"sample_id": str(use.sample_id), "item_id": "not-a-fixed-item"}]
        elif case == "wrong_event":
            basis = deepcopy(use.source_basis)
            at = datetime.fromisoformat(basis["actual_start"]["occurred_at"].replace("Z", "+00:00"))
            basis["actual_start"]["occurred_at"] = (at + timedelta(seconds=1)).isoformat()
            use.source_basis = basis
        elif case == "wrong_asset_identity":
            # Both assets exist in this same tenant. Preserve the correct
            # declared resource IDs, set, revisions, units and windows.
            occupancies[0].asset_id, occupancies[1].asset_id = (
                occupancies[1].asset_id,
                occupancies[0].asset_id,
            )
        else:
            raise AssertionError(case)

    return inject


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_corrupt_new_start_atom_rolls_back_all_eight_storage_boundaries(launch_work, monkeypatch):
    """Six corrupt starts below plus two independent orphan tests cover eight faults."""
    work = launch_work
    promised(work)
    advance_clock(work, monkeypatch)  # Real clock; never move Python ahead of PostgreSQL.
    other = other_physical_sample(work)
    confirmation_hashes = set()
    cases = (
        ("wrong_same_build_sample", "exact complete physical sample set"),
        ("missing_resource", "exact full-window use"),
        ("wrong_resource_units", "exact full-window use"),
        ("wrong_coverage", "exact Run coverage, configuration, event and window"),
        ("wrong_event", "exact Run coverage, configuration, event and window"),
        (
            "wrong_asset_identity",
            "exact current physical sentinel|operational_resource_asset_identity",
        ),
    )
    for case, message in cases:
        # Each fault tests a fresh, real T1 without extending the production
        # token TTL. All faults still share this one persisted Plan/Promise.
        response = post(work.quality, command(work, "test.run.start"), True)
        assert response.status_code == 200, response.text
        prepared = response.json()["command"]
        confirmation_hashes.add(digest(prepared["payload"]["confirmation_token"]))
        baseline = storage_snapshot(work)
        seen = []
        with pytest.raises(DBAPIError, match=message):
            with tenant_session(work.setup.engine, work.setup.tenant) as s:
                inject = corrupt_new_atom(work, case, other, seen)
                event.listen(s, "before_flush", inject)
                try:
                    receipt = execute(
                        s, work.quality.ctx, Command.model_validate(deepcopy(prepared))
                    )
                    assert receipt["subject_type"] == "test_run"
                    assert seen == [case]
                    # Enforce the same deferred atom before leaving this UOW;
                    # the exception leaves tenant_session to roll it all back.
                    s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                finally:
                    event.remove(s, "before_flush", inject)
        assert seen == [case]
        assert_rollback(work, baseline, prepared)
        with tenant_session(work.setup.engine, work.setup.tenant) as s:
            consumed = dict(
                s.execute(
                    select(Confirmation.token_hash, Confirmation.consumed).where(
                        Confirmation.token_hash.in_(confirmation_hashes)
                    )
                ).all()
            )
            assert consumed == dict.fromkeys(confirmation_hashes, False)


def test_orphan_sample_usage_without_actual_start_rolls_back(launch_work):
    work = launch_work
    planned(work)
    baseline = storage_snapshot(work)
    pair = work.binding.pairs[0]
    with pytest.raises(
        DBAPIError, match="Every test use requires its exact actual Run and request start"
    ):
        with tenant_session(work.setup.engine, work.setup.tenant) as s:
            if (
                s.scalar(
                    select(SampleUsageSentinel.id).where(
                        SampleUsageSentinel.sample_id == pair.sample.id
                    )
                )
                is None
            ):
                s.add(
                    SampleUsageSentinel(
                        tenant_id=work.setup.tenant,
                        product_id=work.setup.product,
                        sample_id=pair.sample.id,
                        epoch=1,
                    )
                )
                s.flush()
            s.add(
                SampleRunUsage(
                    tenant_id=work.setup.tenant,
                    product_id=work.setup.product,
                    project_id=work.binding.project_id,
                    build_id=work.binding.build_id,
                    run_id=work.binding.run_id,
                    sample_id=pair.sample.id,
                    sample_revision=pair.sample.revision,
                    actual_configuration_id=pair.sample.actual_configuration.id,
                    actual_configuration_revision=pair.sample.actual_configuration.revision,
                    revision=1,
                    owner_id=work.quality.human,
                    visibility="product",
                    destructive=False,
                    state="reserved",
                    window_start=work.binding.window.start,
                    window_finish=work.binding.window.finish,
                    coverage=[{"sample_id": str(pair.sample.id), "item_id": pair.item_id}],
                    intent_digest=digest({"orphan": "sample-use"}),
                    source_basis={},
                    required_source_read_set=[],
                )
            )
            s.flush()  # All FKs and immediate scope checks are valid.
            s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert_rollback(work, baseline)


def test_orphan_resource_reservation_without_actual_start_rolls_back(launch_work):
    work = launch_work
    planned(work)
    baseline = storage_snapshot(work)
    reservation = {
        "request": resources._request(work.binding, work.test_input).model_dump(mode="json")
    }
    with pytest.raises(
        DBAPIError, match="Every test use requires its exact actual Run and request start"
    ):
        with tenant_session(work.setup.engine, work.setup.tenant) as s:
            s.add(
                TestResourceReservation(
                    id=uuid4(),
                    tenant_id=work.setup.tenant,
                    product_id=work.setup.product,
                    project_id=work.binding.project_id,
                    build_id=work.binding.build_id,
                    run_id=work.binding.run_id,
                    fact_id=work.test_fact_id,
                    fact_revision=1,
                    owner_id=work.quality.human,
                    visibility="product",
                    revision=1,
                    state="formal",
                    intent_digest=digest({"orphan": "resource-reservation"}),
                    binding=work.binding.model_dump(mode="json"),
                    reservation=reservation,
                    reservation_sha256=digest(reservation),
                    required_source_read_set=[],
                    facts_revision=digest({"standalone": True}),
                )
            )
            s.flush()
            s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert_rollback(work, baseline)
