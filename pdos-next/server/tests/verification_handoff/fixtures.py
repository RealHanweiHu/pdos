"""Real API fixtures with explicit synthetic authority; only root runs PostgreSQL."""

# ruff: noqa: F811 - imported pytest fixtures are intentional

import json
import secrets
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from build_operational_facts.fixtures import operational_work  # noqa: F401
from build_start.test_transactions import (
    approved,
    import_authority,
    ready_work,  # noqa: F401
    shared_configuration,
)
from sqlalchemy.orm import Session
from test_build_execution import actual_command, allocation_command, execution_view, output_command
from test_project_first_plan import accepted, cmd, post
from test_verification_execution import command as prep_command
from test_verification_execution import payload as prep_payload
from test_verification_execution import row_for

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.verification_handoff.service import event_source
from pdos_next.models import Grant, LoginSession, Principal, now
from pdos_next.service import Context, digest


@pytest.fixture
def known_configuration(setup):
    return shared_configuration(setup)


def caller(setup, identity, token):
    return SimpleNamespace(
        **{
            **vars(setup),
            "human": identity,
            "ctx": Context(setup.tenant, identity, identity, category_id=setup.category),
            "headers": {"Authorization": f"Bearer {token}"},
        }
    )


def artifact(setup, content, title="Synthetic event"):
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "source_label": "Synthetic fixture only",
                "visibility": "category",
                "content": content,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return {
        "artifact_id": response.json()["subject_id"],
        "expected_revision": 1,
        "line": 1,
        "quote": content.splitlines()[0],
    }


def start(work):
    engineer, _ = approved(work, "engineering")
    manufacturer, _ = approved(work, "manufacturing")
    at = now()
    reference = artifact(
        work.setup,
        json.dumps(
            {
                "build_id": work.build_id,
                "occurred_at": at.isoformat(),
                "purpose": work.scope.purpose,
                "engineering_configuration_id": work.config["engineering"]["subject_id"],
                "manufacturing_configuration_id": work.config["process"]["subject_id"],
            }
        ),
    )
    command = cmd(
        work.setup,
        "build.start",
        {
            "assessment_id": work.assessment["id"],
            "expected_assessment_revision": work.assessment["revision"],
            "expected_assessment_sha256": work.assessment["snapshot_sha256"],
            "engineering_authorization_id": engineer["id"],
            "expected_engineering_authorization_revision": engineer["revision"],
            "manufacturing_authorization_id": manufacturer["id"],
            "expected_manufacturing_authorization_revision": manufacturer["revision"],
            "occurred_at": at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": reference,
            "reason": "Synthetic shared start, no production qualification",
        },
    )
    command["source_read_set"] = _merge_reads(
        work.assessment["required_source_read_set"], [reference]
    )
    receipt, _ = accepted(work.setup, command)
    work.start_receipt = receipt
    return at


def readiness(work, sample, *, state="ready", previous=None, caller_setup=None):
    setup = caller_setup or work.setup
    at = now()
    reference = artifact(
        setup,
        json.dumps(
            {
                "sample_id": sample["id"],
                "lot_id": sample["lot_id"],
                "actual_configuration_id": sample["actual_configuration_id"],
                "build_id": work.build_id,
                "state": state,
                "purpose": work.scope.purpose,
                "occurred_at": at.isoformat(),
            }
        ),
    )
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/sample-handoff",
        headers=setup.headers,
        params={"purpose": work.scope.purpose, "build_id": work.build_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    cap = data["capabilities_by_sample"][sample["id"]]
    fixed = data["current_by_sample"].get(sample["id"])
    command = cmd(
        setup,
        "build.sample.readiness.record",
        {
            "sample_id": sample["id"],
            "expected_sample_revision": sample["revision"],
            "previous_readiness_id": fixed["readiness_id"] if fixed else None,
            "expected_previous_revision": fixed["revision"] if fixed else 0,
            "state": state,
            "purpose": work.scope.purpose,
            "occurred_at": at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": reference,
            "sources": [reference],
            "reason": "Synthetic physical readiness, separate from quality",
        },
    )
    command["source_read_set"] = _merge_reads(
        cap["required_source_read_set"],
        data["availability_by_sample"][sample["id"]]["required_source_read_set"],
        [reference],
    )
    receipt, prepared = accepted(setup, command)
    return receipt, prepared


@pytest.fixture
def handoff_work(ready_work):
    work = ready_work
    setup = work.setup
    quality_id, token = uuid4(), secrets.token_urlsafe(32)
    with Session(setup.admin) as session, session.begin():
        session.add(
            Principal(
                id=quality_id,
                tenant_id=setup.tenant,
                name="Synthetic qualified quality",
                kind="human",
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=setup.category,
                principal_id=quality_id,
                can_write=True,
                expires_at=now() + timedelta(minutes=53),
            )
        )
        session.add(
            LoginSession(
                tenant_id=setup.tenant,
                principal_id=quality_id,
                token_hash=digest(token),
                expires_at=now() + timedelta(hours=1),
            )
        )
    work.engineer = caller(setup, setup.peer, setup.tokens[setup.peer])
    work.quality = caller(setup, quality_id, token)
    work.extra_authority = {}
    for role, identity, operations in [
        ("engineering", setup.peer, ["verification.request.create", "verification.handoff.offer"]),
        ("manufacturing", setup.human, ["build.sample.readiness.record"]),
        (
            "quality",
            quality_id,
            [
                "verification.request.create",
                "verification.method.prepare",
                "verification.actual_method.prepare",
                "verification.handoff.accept",
                "verification.handoff.return",
            ],
        ),
    ]:
        for kind in ("duty", "qualification"):
            work.extra_authority[(role, kind)] = import_authority(
                work,
                role,
                kind,
                subject_id=str(identity),
                operations=operations,
                external_id=f"synthetic-handoff-{role}-{kind}-{identity}",
            )
    # All professional facts precede the signers' fixed authorization snapshots.
    start(work)
    planned = {**work.config, "build": {"subject_id": work.build_id}}
    observed_at = now()
    actual, _ = accepted(setup, actual_command(setup, planned, observed_at=observed_at.isoformat()))
    if getattr(work, "s2_batched_lots", False) is True:
        # Only the explicit two-Run chain requests two separately observed Lots.
        # Both physical output and sample identity use the existing host commands.
        work.samples, work.s2_batched_lot_ids = [], []
        for cavity in ("A", "B"):
            output, _ = accepted(
                setup,
                output_command(
                    setup,
                    planned,
                    actual,
                    units=1,
                    observation={
                        "system": "Synthetic batched fixture",
                        "external_id": str(uuid4()),
                        "nature": "synthetic",
                        "occurred_at": now().isoformat(),
                    },
                ),
            )
            allocated, _ = accepted(
                setup,
                allocation_command(
                    setup,
                    planned,
                    output,
                    samples=[{"label": f"SYN-{uuid4()}", "cavity": cavity}],
                ),
            )
            work.s2_batched_lot_ids.append(output["subject_id"])
            work.samples.extend(
                row
                for row in execution_view(setup)["samples"]
                if row["allocation_id"] == allocated["subject_id"]
            )
    else:
        output, _ = accepted(
            setup,
            output_command(
                setup,
                planned,
                actual,
                units=2,
                observation={
                    "system": "Synthetic fixture",
                    "external_id": str(uuid4()),
                    "nature": "synthetic",
                    "occurred_at": now().isoformat(),
                },
            ),
        )
        allocated, _ = accepted(
            setup,
            allocation_command(
                setup,
                planned,
                output,
                samples=[{"label": f"SYN-{uuid4()}", "cavity": cavity} for cavity in ("A", "B")],
            ),
        )
        work.samples = [
            row
            for row in execution_view(setup)["samples"]
            if row["allocation_id"] == allocated["subject_id"]
        ]
    for sample in work.samples:
        readiness(work, sample)
    source = artifact(
        setup,
        "Synthetic drawing\nSynthetic limits 9.5 to 10.5\nSynthetic report basis",
        "Synthetic actual method dossier",
    )
    work.source = source
    material = {**planned, "preparation_source": source["artifact_id"]}
    data = prep_payload(material, purpose=work.scope.purpose)

    def ref(line):
        return {
            **source,
            "line": line,
            "quote": [
                "Synthetic drawing",
                "Synthetic limits 9.5 to 10.5",
                "Synthetic report basis",
            ][line - 1],
        }

    data["items"][0].update(
        drawing=ref(1),
        method=ref(2),
        criterion={"lower": "9.5", "upper": "10.5", "source": ref(2)},
        sample_count=2,
        cavities=["A", "B"],
    )
    data["documents"][0]["source"] = ref(3)
    data["sources"] = [ref(1)]
    receipt, _ = accepted(setup, prep_command(setup, material, data))
    prep = row_for(setup, receipt)
    create = cmd(
        work.engineer,
        "verification.request.create",
        {
            "request_id": str(uuid4()),
            "preparation_id": prep["id"],
            "expected_preparation_revision": prep["revision"],
            "preparation_sha256": prep["sha256"],
            "reason": "Synthetic exact formal request",
        },
    )
    create["source_read_set"] = prep["required_source_read_set"]
    response = post(work.engineer, create)
    assert response.status_code == 200, response.text
    work.request_id = create["payload"]["request_id"]
    row = current(work)
    method = cmd(
        work.quality,
        "verification.method.prepare",
        {
            "request_id": work.request_id,
            "expected_request_revision": row["revision"],
            "assessments": [
                {
                    "item_id": "dimension",
                    "status": "applicable",
                    "conditions": [],
                    "reason": "Synthetic planned configuration method review",
                    "sources": [ref(2)],
                }
            ],
            "reason": "Synthetic planned method; does not prove actual applicability",
        },
    )
    method["source_read_set"] = row["required_source_read_set"]
    accepted(work.quality, method)
    work.actual_source = ref(2)
    yield work


def listing(work, setup=None):
    setup = setup or work.quality
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/verification-handoff",
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def current(work, setup=None):
    data = listing(work, setup)
    fixed = data["current_by_request"][work.request_id]
    return next(row for row in data["requests"] if row["id"] == fixed["request_version_id"])


def selected(work, setup=None):
    return [
        row
        for row in listing(work, setup)["reference_samples"]
        if row["request_id"] == work.request_id
    ]


def command(work, operation, payload, *, setup=None, _view=None):
    setup = setup or (work.engineer if operation.endswith("offer") else work.quality)
    view = _view or listing(work, setup)
    fixed = view["current_by_request"][work.request_id]
    row = next(row for row in view["requests"] if row["id"] == fixed["request_version_id"])
    data = {
        "request_id": work.request_id,
        "expected_request_revision": row["revision"],
        "sources": [],
        "reason": "Synthetic exact physical handoff",
        **deepcopy(payload),
    }
    result = cmd(setup, operation, data)
    reads = row["required_source_read_set"]
    samples = [row for row in view["reference_samples"] if row["request_id"] == work.request_id]
    reads = _merge_reads(
        reads,
        *(v["required_source_read_set"] for v in samples),
        *(
            v["required_source_read_set"]
            for v in view["actual_methods"]
            if v["request_id"] == work.request_id
        ),
        data["sources"],
    )
    for assessment in data.get("assessments", []):
        reads = _merge_reads(reads, assessment["sources"])
    if operation == "verification.method.prepare":
        # Planned review has nested assessment sources only; the handoff wrapper's
        # top-level sources are intentionally not part of its closed payload.
        result["payload"].pop("sources", None)
    result["source_read_set"] = reads
    return result


def actual_method(work, *, status="applicable"):
    view = listing(work)
    sample_views = [
        row for row in view["reference_samples"] if row["request_id"] == work.request_id
    ]
    pointers = {
        r["sample_id"]: r["revision"]
        for r in view["method_current_by_pair"]
        if r["request_id"] == work.request_id
    }
    return command(
        work,
        "verification.actual_method.prepare",
        {
            "assessments": [
                {
                    "sample": row["reference"],
                    "item_id": "dimension",
                    "expected_assessment_revision": pointers.get(row["id"], 0),
                    "status": status,
                    "conditions": [],
                    "reason": "Explicit actual pair review",
                    "sources": [work.actual_source] if status == "applicable" else [],
                }
                for row in sample_views
            ]
        },
        _view=view,
    )


def handoff(work, *, operation="verification.handoff.offer", coverage=None, returned=()):
    setup = work.engineer if operation.endswith("offer") else work.quality
    source = artifact(setup, f"Synthetic actual {operation} event")
    view = listing(work, setup)
    samples = [row for row in view["reference_samples"] if row["request_id"] == work.request_id]
    scope = coverage or [{"sample_id": sample["id"], "item_id": "dimension"} for sample in samples]
    at = {
        "occurred_at": now().isoformat(),
        "original_timezone": "UTC",
        "source": event_source(DefinitionReference.model_validate(source)).model_dump(mode="json"),
    }
    data = {"coverage": scope, "sources": [source], "at": at}
    if operation.endswith("offer"):
        data["samples"] = [sample["reference"] for sample in samples]
    else:
        data["next_owner_id"] = str(work.engineer.human)
        if operation.endswith("accept"):
            data["returned_coverage"] = list(returned)
    return command(work, operation, data, setup=setup, _view=view)
