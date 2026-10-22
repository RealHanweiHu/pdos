"""Run locally with --confcutdir here; PostgreSQL cases are root-owned runs."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from pydantic import ValidationError

from pdos_next.domain.build_operational_facts import service
from pdos_next.domain.build_operational_facts.schemas import FactInput, OperationalScope

from .support import AT, NoDatabase, example


@pytest.fixture(autouse=True)
def fixed_capacity_port(monkeypatch):
    from pdos_next.domain.build_operational_facts import physical_summary

    def summary(s, ctx, pid, kind, identities, **options):
        assert isinstance(s, NoDatabase)
        if kind == "material":
            return [
                {"asset_id": str(row.asset_id), "quantity": str(row.quantity), "unit": row.unit}
                for row in s.holds if row.asset_id in identities
            ]
        return [
            {
                "id": str(uuid5(NAMESPACE_URL, f"capacity:{row.window_start}:{row.window_finish}")),
                "resource_id": str(row.resource_id),
                "window_start": row.window_start.isoformat(),
                "window_finish": row.window_finish.isoformat(),
                "units": str(row.units),
            }
            for row in s.occupied if row.resource_id in identities
        ]

    monkeypatch.setattr(physical_summary, "capacity_summary", summary)


def evaluated(data_transform=None, issuer_transform=None, *, holds=(), occupied=()):
    ctx, fact, data, bound, assets, issuer = example()
    if data_transform:
        raw = data.model_dump(mode="json")
        data_transform(raw)
        data = FactInput.model_validate(raw)
    if issuer_transform:
        issuer = issuer_transform(issuer)
    s = NoDatabase(holds, occupied)
    coverage = service._material_coverage(s, ctx, fact, data, bound, assets, AT, None)
    report, proofs, total = service._resource_report(
        s, ctx, fact, data, bound, data.scope, assets, issuer, AT, None
    )
    return coverage, report, proofs, total


def test_complete_actual_stock_and_verified_named_full_resource_window_positive():
    coverage, report, proofs, total = evaluated()
    assert service._material_check(coverage).status == "READY" and report.status == "READY"
    assert coverage.lines[0].demand.required_quantity == Decimal("22")
    assert total == {UUID(int=50): Decimal("1")}
    assert all(v["proof"]["current"] for v in proofs)


@pytest.mark.parametrize("stage", ["commitment", "in_transit"])
def test_promises_and_transit_never_supply_physical_ready(stage):
    coverage, _, _, _ = evaluated(lambda d: d["materials"][0].update(stage=stage))
    assert service._material_check(coverage).status != "READY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", None),
        ("quality", "unknown"),
        ("availability", "unknown"),
        ("external_holds_complete", False),
    ],
)
def test_unknown_material_fact_and_incomplete_global_holds_never_ready(field, value):
    coverage, _, _, _ = evaluated(lambda d: d["materials"][0].update({field: value}))
    assert service._material_check(coverage).status == "UNKNOWN"


def test_foreign_project_hold_is_counted_without_acl_filter():
    ctx, fact, data, bound, assets, _ = example()
    aid = next(key for key, value in assets.items() if value.kind == "material")
    held = SimpleNamespace(
        id=UUID(int=99),
        asset_id=aid,
        build_id=UUID(int=100),
        bom_item_id="motor",
        quantity=Decimal("1"),
        unit="ea",
    )
    coverage = service._material_coverage(
        NoDatabase((held,)), ctx, fact, data, bound, assets, AT, None
    )
    assert service._material_check(coverage).status == "BLOCKED"
    public = coverage.model_dump(mode="json")
    assert str(held.build_id) not in str(public) and str(held.id) not in str(public)
    assert public["input_snapshot"]["reservations"][0]["bom_item_id"] is None


@pytest.mark.parametrize("verifier", [None, lambda *args: None])
def test_source_and_named_uuid_without_verified_decision_never_qualify(verifier):
    _, report, _, _ = evaluated(
        issuer_transform=lambda issuer: replace(issuer, verify_named_decision=verifier)
    )
    assert report.status == "UNKNOWN"


def test_reconfigured_issuer_does_not_validate_old_named_facts():
    _, report, _, _ = evaluated(
        issuer_transform=lambda issuer: replace(issuer, epoch=issuer.epoch + 1)
    )
    assert report.status == "UNKNOWN"


@pytest.mark.parametrize(
    "field,value",
    [
        ("maintenance", None),
        ("calendar", None),
        ("capacity", None),
        ("external_occupancies_complete", False),
    ],
)
def test_missing_resource_facts_never_ready(field, value):
    def change(raw):
        raw["resources"][0][field] = value
        if field == "calendar":
            raw["resources"][0]["calendar_sources"] = []

    _, report, _, _ = evaluated(change)
    assert report.status == "UNKNOWN"


def test_all_operation_capacity_is_combined_without_inventing_schedule():
    ctx, fact, data, bound, assets, issuer = example()
    raw = data.model_dump(mode="json")
    raw["requirements"].append({**deepcopy(raw["requirements"][0]), "operation_key": "second"})
    raw["resources"][0]["operation_ids"].append("second")
    raw["resources"][0]["facts"].extend(
        {**v, "operation_id": "second"} for v in deepcopy(raw["resources"][0]["facts"])
    )
    data = FactInput.model_validate(raw)
    bound = bound.model_copy(update={"manufacturing_operation_ids": ("assembly", "second")})
    report, _, _ = service._resource_report(
        NoDatabase(), ctx, fact, data, bound, data.scope, assets, issuer, AT, None
    )
    assert report.status == "BLOCKED"
    assert any(v.code == "combined_capacity_conflict" for v in report.checks)


def test_empty_operation_requirements_do_not_become_empty_ready():
    _, report, _, _ = evaluated(lambda d: d.update(requirements=[], resources=[]))
    assert report.status == "UNKNOWN"


def test_global_identity_stable_and_non_consuming_mirror_has_no_source_refs():
    ctx, _, data, _, _, _ = example()
    raw = data.model_dump(mode="json")
    raw["sources"][0]["quote"] = "Another source"
    raw["resources"][0]["sources"][0]["artifact_id"] = str(UUID(int=92))
    other = FactInput.model_validate(raw)
    before, after = service._assets(data, ctx.tenant_id), service._assets(other, ctx.tenant_id)
    assert [(v[0], v[1], v[2]) for v in before] == [(v[0], v[1], v[2]) for v in after]
    assert "artifact_id" not in str([v[5] for v in after])
    assert len(service._sources(other)) == 3


@pytest.mark.parametrize("extra", ["nature", "tenant_id", "approved_by", "source_current"])
def test_client_cannot_supply_server_authority_fields(extra):
    raw = example()[2].model_dump(mode="json")
    raw[extra] = True
    with pytest.raises(ValidationError):
        FactInput.model_validate(raw)


def test_synthetic_config_default_closed_and_binary_float_rejected():
    with pytest.raises(ValueError, match="verified host marker"):
        service.configure_local_synthetic(
            SimpleNamespace(), tenant_id=UUID(int=1), product_id=UUID(int=4)
        )
    raw = example()[2].model_dump(mode="json")
    raw["materials"][0]["quantity"] = 1.2
    with pytest.raises(ValidationError, match="binary floats"):
        FactInput.model_validate(raw)


def test_ledger_precision_is_exact_and_never_rounds_recurring_conversion():
    assert service._persistable(Decimal("22"))
    assert not service._persistable(Decimal("0.333333333333333333"))
    assert not service._persistable(Decimal("1000000000000"))
    assert not service._persistable(Decimal("0.000000000001"))


def test_foreign_resource_owner_and_nonintersecting_windows_never_enter_public_report():
    ctx, fact, data, bound, assets, issuer = example()
    owner = UUID(int=800)
    resource_id = data.resources[0].resource.id
    private = SimpleNamespace(
        id=owner,
        resource_id=resource_id,
        window_start=data.scope.window.start,
        window_finish=data.scope.window.finish,
        units=Decimal("1"),
    )
    report, _, _ = service._resource_report(
        NoDatabase(occupied=(private,)),
        ctx,
        fact,
        data,
        bound,
        data.scope,
        assets,
        issuer,
        AT,
        None,
    )
    assert report.status == "BLOCKED"
    public = str(report.model_dump(mode="json"))
    assert str(owner) not in public
    # Only this Build's fixed window, resources and capacity conflict are exposed;
    # no foreign reservation/owner or unrelated calendar occupancy list exists.
    assert "occupancies" not in public and "owner_execution_id" not in public


@pytest.mark.parametrize("quantity", ["10", "10.0", "10.00000000", "1E+1"])
def test_equivalent_scope_quantity_keeps_exact_binding_and_payload_hash(quantity):
    original = example()[2]
    raw = original.model_dump(mode="json")
    raw["scope"]["quantity"] = quantity
    raw["scope"]["purpose"] = f"  {raw['scope']['purpose']}  "
    raw["scope"]["site"] = f"  {raw['scope']['site']}  "
    raw["scope"]["unit"] = " ea "
    same = FactInput.model_validate(raw)
    assert same.scope.quantity == Decimal("10")
    assert same.model_dump(mode="json") == original.model_dump(mode="json")
    assert service.digest(same.model_dump(mode="json")) == service.digest(
        original.model_dump(mode="json")
    )


@pytest.mark.parametrize("field", ["purpose", "site", "unit"])
def test_scope_identifiers_reject_blank_after_trim(field):
    raw = example()[2].scope.model_dump(mode="json")
    raw[field] = "  "
    with pytest.raises(ValidationError):
        OperationalScope.model_validate(raw)


def test_quantity_canonicalization_does_not_round_a_distinct_fraction():
    raw = example()[2].scope.model_dump(mode="json")
    raw["quantity"] = "10.00000001"
    other = OperationalScope.model_validate(raw)
    assert other.quantity == Decimal("10.00000001")
    assert other.model_dump(mode="json")["quantity"] == "10.00000001"
    assert service.digest(other) != service.digest(example()[2].scope)
