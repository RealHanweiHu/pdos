"""Pure fixed synthetic inputs. No connection, production issuer or qualification."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from pdos_next.domain.build_operational_facts.schemas import DecisionProof, FactInput
from pdos_next.domain.build_operational_facts.service import (
    _assets,
    configure_local_synthetic,
    digest,
)
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.engines.supply_cost import expand_bom
from pdos_next.engines.supply_cost.dto import FixedBasis
from pdos_next.schemas.supply_cost.dto import BoundDemand

AT = datetime(2026, 10, 2, 8, tzinfo=UTC)
SOURCE = {
    "artifact_id": str(UUID(int=91)),
    "expected_revision": 1,
    "line": 1,
    "quote": "Synthetic requirement is unverified",
}


class NoDatabase:
    def __init__(self, holds=(), occupied=()):
        self.holds, self.occupied = holds, occupied

    def scalars(self, statement):
        name = statement.column_descriptions[0]["entity"].__name__
        return self.holds if name == "MaterialHold" else self.occupied


def reference(name):
    return {
        "source_id": name,
        "version": "1",
        "sha256": "a" * 64,
        "captured_at": AT - timedelta(days=1),
        "state": "current",
    }


def example():
    ctx = SimpleNamespace(tenant_id=UUID(int=1), requester_id=UUID(int=2))
    resource = {"id": str(UUID(int=50)), "revision": 1, "kind": "equipment"}
    scope = {
        "purpose": "internal-prototype",
        "quantity": "10",
        "unit": "ea",
        "site": "SYN-LAB",
        "window": {
            "start": AT + timedelta(hours=1),
            "finish": AT + timedelta(hours=2),
            "original_timezone": "UTC",
        },
    }
    decisions = [
        {
            "kind": kind,
            "purpose": scope["purpose"],
            "operation_id": "assembly",
            "status": "accepted",
            "valid_from": AT - timedelta(days=1),
            "valid_until": AT + timedelta(days=1),
            "named_decision_id": str(UUID(int=60 + i)),
            "actor_id": str(ctx.requester_id),
            "sources": [SOURCE],
        }
        for i, kind in enumerate(("acceptance", "calibration"))
    ]
    data = FactInput.model_validate(
        {
            "build_id": str(UUID(int=3)),
            "expected_build_revision": 1,
            "scope": scope,
            "external_id": "SYN-FACT",
            "valid_from": AT - timedelta(days=1),
            "valid_until": AT + timedelta(days=1),
            "materials_scope_complete": True,
            "materials": [
                {
                    "key": {
                        "source_system": "SYNTHETIC-WH",
                        "pool_id": "POOL-1",
                        "material_id": "motor",
                    },
                    "version": 1,
                    "observed_at": AT - timedelta(hours=1),
                    "stage": "on_hand",
                    "quantity": "22",
                    "unit": "ea",
                    "availability": "available",
                    "quality": "released",
                    "external_holds_complete": True,
                    "sources": [SOURCE],
                }
            ],
            "resources": [
                {
                    "resource": resource,
                    "purposes": [scope["purpose"]],
                    "operation_ids": ["assembly"],
                    "lifecycle": "active",
                    "facts": decisions,
                    "maintenance": [],
                    "capacity": "1",
                    "calendar": {
                        "calendar_id": "SYN-UTC",
                        "version": "1",
                        "timezone": "UTC",
                        "timezone_rules_sha256": frozen_timezone("UTC")[1],
                        "weekly": [
                            {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                            for i in range(7)
                        ],
                    },
                    "calendar_sources": [SOURCE],
                    "external_occupancies_complete": True,
                    "sources": [SOURCE],
                }
            ],
            "requirements": [
                {
                    "operation_key": "assembly",
                    "uses": [{"resource": resource, "units": "1"}],
                    "sources": [SOURCE],
                }
            ],
            "sources": [SOURCE],
            "reason": "Synthetic complete operational fixture",
        }
    )
    basis = FixedBasis.model_validate(
        {
            "build": {
                "build_id": str(data.build_id),
                "ref": reference("build"),
                "quantity": "10",
                "product_unit": "ea",
            },
            "bom": {
                "ref": reference("bom"),
                "engineering_configuration": reference("engineering"),
                "items": [
                    {
                        "item_id": "motor",
                        "material_id": "motor",
                        "quantity_per_parent": "2",
                        "unit": "ea",
                        "loss_rate": "0.1",
                        "supply_required": True,
                    }
                ],
            },
        }
    )
    lines, _ = expand_bom(basis, AT)
    bound = BoundDemand.model_validate(
        {
            "scope": {
                "tenant_id": str(ctx.tenant_id),
                "category_id": str(UUID(int=7)),
                "product_id": str(UUID(int=4)),
                "project_id": str(UUID(int=5)),
                "audience": f"private:{ctx.requester_id}",
            },
            "basis": basis,
            "manufacturing_configuration": reference("manufacturing"),
            "demand": {
                "ref": reference("demand"),
                "basis_sha256": digest(basis),
                "manufacturing_sha256": "b" * 64,
                "lines": lines,
            },
            "manufacturing_operation_ids": ["assembly"],
            "source_read_set_complete": True,
        }
    )
    engine = SimpleNamespace()

    def verify(s, context, binding, ref, decision, at):
        return DecisionProof(
            current=decision.named_decision_id in {UUID(int=60), UUID(int=61)},
            facts_revision=digest(decision.model_dump(mode="json")),
            valid_until=decision.valid_until,
        )

    issuer = configure_local_synthetic(
        engine,
        tenant_id=ctx.tenant_id,
        product_id=UUID(int=4),
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=verify,
    )
    fact = SimpleNamespace(
        id=UUID(int=6),
        tenant_id=ctx.tenant_id,
        product_id=UUID(int=4),
        project_id=UUID(int=5),
        build_id=data.build_id,
        revision=1,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        fact_sha256=digest(data.model_dump(mode="json")),
        created_at=AT - timedelta(minutes=1),
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        binding={"scope": scope},
    )
    assets = {
        aid: SimpleNamespace(
            id=aid,
            kind=kind,
            identity=identity,
            revision=rev,
            data_sha256=digest(physical),
            occupancy_epoch=1,
        )
        for kind, aid, _, identity, rev, physical in _assets(data, ctx.tenant_id)
    }
    return ctx, fact, data, bound, assets, issuer
