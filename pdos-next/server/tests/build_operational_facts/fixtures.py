"""Real PG fixture construction; executed only by root in its guarded database."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from test_build_demand import compute
from test_builds import accepted, configuration, definition, project  # noqa: F401
from test_project_first_plan import cmd

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.schemas import (
    DecisionProof,
    FactInput,
    OperationalScope,
)
from pdos_next.domain.build_operational_facts.service import (
    configure_local_synthetic,
    disable_issuer,
    load_bundle,
)
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.models import now
from pdos_next.operational_import import import_operational_fact
from pdos_next.service import digest


@pytest.fixture
def known_configuration(setup, configuration):
    """Uses the existing fixed-scope APIs but creates an entirely known BOM."""
    config = deepcopy(configuration)
    bom_payload = deepcopy(config["bom_payload"])
    bom_payload["name"] = "Synthetic fully known motor BOM"
    bom_payload["lines"] = bom_payload["lines"][:1]
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/configurations", headers=setup.headers
    )
    assert response.status_code == 200, response.text
    saved_bom = next(v for v in response.json()["boms"] if v["id"] == config["bom"]["subject_id"])
    fixed_part = next(v for v in saved_bom["lines"] if v["key"] == "motor")
    bom_payload["lines"][0].pop("part")
    bom_payload["lines"][0].update(
        part_id=fixed_part["part_id"], expected_part_revision=fixed_part["part"]["revision"]
    )
    bom, _ = accepted(setup, cmd(setup, "engineering.bom.revise", bom_payload, config["source"]))
    engineering_payload = {
        **config["engineering_payload"],
        "bom_id": bom["subject_id"],
        "name": "Synthetic known engineering",
    }
    engineering, _ = accepted(
        setup, cmd(setup, "engineering.configuration.create", engineering_payload, config["source"])
    )
    process_payload = {
        **config["process_payload"],
        "engineering_configuration_id": engineering["subject_id"],
        "name": "Synthetic known manufacturing",
    }
    process, _ = accepted(
        setup, cmd(setup, "npi.process.revise", process_payload, config["source"])
    )
    return {
        **config,
        "bom": bom,
        "engineering": engineering,
        "process": process,
        "bom_payload": bom_payload,
        "engineering_payload": engineering_payload,
        "process_payload": process_payload,
    }


def fact_payload(work, *, resource_id=None, pool_id="SYN-PHYSICAL-POOL-1", previous=None):
    at = work.at
    reference = {
        "artifact_id": work.config["source"],
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic requirement is unverified",
    }
    part = work.config["result"]["demands"][0]["material_id"]
    resource = {"id": str(resource_id or work.resource_id), "revision": 1, "kind": "equipment"}
    decisions = [
        {
            "kind": kind,
            "purpose": work.scope.purpose,
            "operation_id": "assembly",
            "status": "accepted",
            "valid_from": at - timedelta(days=1),
            "valid_until": at + timedelta(days=1),
            "actor_id": str(work.setup.human),
            "named_decision_id": str(work.decision_ids[kind]),
            "sources": [reference],
        }
        for kind in ("acceptance", "calibration")
    ]
    return FactInput.model_validate(
        {
            "build_id": work.build_id,
            "expected_build_revision": 1,
            "scope": work.scope,
            "external_id": f"SYN-BUNDLE-{work.build_id}",
            "expected_previous_id": previous.id if previous else None,
            "expected_previous_revision": previous.revision if previous else 0,
            "valid_from": at - timedelta(days=1),
            "valid_until": at + timedelta(days=1),
            "materials_scope_complete": True,
            "materials": [
                {
                    "key": {
                        "source_system": "SYNTHETIC-WH",
                        "pool_id": pool_id,
                        "material_id": part,
                    },
                    "version": 1,
                    "observed_at": at - timedelta(minutes=1),
                    "stage": "on_hand",
                    "quantity": "44",
                    "unit": "ea",
                    "availability": "available",
                    "quality": "released",
                    "external_holds_complete": True,
                    "sources": [reference],
                }
            ],
            "resources": [
                {
                    "resource": resource,
                    "purposes": [work.scope.purpose],
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
                    "calendar_sources": [reference],
                    "external_occupancies_complete": True,
                    "sources": [reference],
                }
            ],
            "requirements": [
                {
                    "operation_key": "assembly",
                    "uses": [{"resource": resource, "units": "1"}],
                    "sources": [reference],
                }
            ],
            "sources": [reference],
            "reason": "Explicit synthetic observed operational facts",
        }
    )


def imported(work, payload=None, *, request_key=None, session=None):
    data = payload or work.payload
    kwargs = {"request_key": request_key or str(uuid4()), "command_id": uuid4()}
    if session is not None:
        return import_operational_fact(session, work.setup.ctx, work.issuer, data, **kwargs)
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.setup.human, category_id=work.setup.category) as s:
        return import_operational_fact(s, work.setup.ctx, work.issuer, data, **kwargs)


def bundle(work, *, context=None, at=None):
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.setup.human, category_id=work.setup.category) as s:
        return load_bundle(
            s,
            context or work.setup.ctx,
            work.setup.product,
            UUID(work.build_id),
            work.scope,
            at or now(),
        )


@pytest.fixture
def operational_work(setup, known_configuration):
    config = compute(setup, known_configuration)
    at = now()
    work = SimpleNamespace(
        setup=setup,
        config=config,
        at=at,
        build_id=config["build_id"],
        resource_id=uuid4(),
        decision_ids={"acceptance": uuid4(), "calibration": uuid4()},
        scope=OperationalScope(
            purpose="Verify preparation",
            quantity="10",
            unit="ea",
            site="SYN-INTERNAL-LAB",
            window={
                "start": at - timedelta(minutes=5),
                "finish": at + timedelta(minutes=20),
                "original_timezone": "UTC",
            },
        ),
    )
    work.named_current = True

    def verifier(s, ctx, binding, resource, decision, checked_at):
        current = (
            work.named_current
            and decision.named_decision_id in work.decision_ids.values()
            and decision.actor_id == setup.human
        )
        return DecisionProof(
            current=current,
            facts_revision=digest(
                {"decision": decision.model_dump(mode="json"), "current": current}
            ),
            valid_until=decision.valid_until,
        )

    work.issuer = configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(config["project"]),
        key=f"synthetic-{setup.product}",
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=verifier,
    )
    work.payload = fact_payload(work)
    yield work
    disable_issuer(setup.engine, work.issuer.key)
