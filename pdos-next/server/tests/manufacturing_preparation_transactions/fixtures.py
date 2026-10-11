"""Real manufacturing API case; synthetic facts use the existing trusted persisted import.

No runtime qualification/scope/clock/Source owner is replaced. Bodies are staged
only; Root executes against its explicitly verified independent PostgreSQL target.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_project_first_plan import cmd, post

from pdos_next.database import tenant_session
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.manufacturing_baseline.models import (
    BaselineDocumentLink,
    PreparationCurrent,
    PreparationVersion,
)
from pdos_next.domain.manufacturing_baseline.service import EVENTS
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource, DefinitionSpecRow
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects import service as projects
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.models import Audit, Confirmation, Outbox, Product, Receipt, RequestKey, now
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.professional_import import import_professional_fact
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

OPERATIONS = tuple(EVENTS)
PARENT_MODELS = (
    Product,
    Project,
    ProjectProductLink,
    DefinitionRevision,
    DefinitionSource,
    DefinitionSpecRow,
    PartIdentity,
    BomRevision,
    BomLine,
    EngineeringConfiguration,
    ProcessRevision,
)
EFFECT_MODELS = (
    PreparationVersion,
    PreparationCurrent,
    BaselineDocumentLink,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
)
DOCUMENT_LINES = (
    "Synthetic WI first step: assemble the supplied motor; process torque remains unknown.",
    "Synthetic WI revision: inspect the unpowered assembly before continuing; torque is unknown.",
    "Synthetic CP feature: inspect housing fit; method, acceptance limit and sampling are unknown.",
    "Synthetic baseline: retain fixed current documentation; "
    "tooling qualification and release are unknown.",
)


def registered_text(setup, title, text):
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": text,
                "source_label": "Explicit synthetic manufacturing test",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["subject_id"]


def source_ref(identity, text, line=1):
    return {"artifact_id": identity, "expected_revision": 1, "line": line, "quote": text}


@pytest.fixture
def manufacturing_case(setup, configuration, tmp_path):
    # This exact guard must precede any local synthetic issuer enabling.
    verify_test_target(setup.engine)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        project, _, definition = projects._project(
            session, setup.ctx, setup.product, UUID(configuration["project"])
        )
        process, process_view = configurations.get_process(
            session, setup.ctx, setup.product, UUID(configuration["process"]["subject_id"])
        )
        # Existing Process has no Current pointer; configurations._advance selects
        # the latest exact row in this revision chain. New documents do have Current.
        latest_process = session.scalar(
            select(ProcessRevision)
            .where(
                ProcessRevision.tenant_id == setup.tenant,
                ProcessRevision.product_id == setup.product,
                ProcessRevision.series_id == process.series_id,
            )
            .order_by(ProcessRevision.revision.desc())
            .limit(1)
        )
        assert latest_process.id == process.id and latest_process.revision == process.revision
        assert process_view["source_status"] == definition["source_status"] == "current"
        assert process_view["engineering_configuration"]["definition_id"] == definition["id"]
        project_id, purpose = project.id, project.purpose
        process_ref = {"id": str(process.id), "revision": process.revision}
        operation_keys = tuple(item["key"] for item in process_view["operations"])
        definition_sources = deepcopy(definition["sources"])
        engineering = session.get(EngineeringConfiguration, process.engineering_configuration_id)
        configuration_reads = deepcopy(
            [
                *process.required_source_read_set,
                *engineering.required_source_read_set,
            ]
        )
    assert operation_keys and len(operation_keys) == len(set(operation_keys))
    document_source = registered_text(
        setup, "Synthetic manufacturing documentation", "\n".join(DOCUMENT_LINES)
    )
    credential_text = (
        f"Synthetic named manufacturing duty and personnel qualification for {setup.human}, "
        f"project {project_id}, purpose {purpose}; operations {', '.join(OPERATIONS)}; "
        "isolated test only, no production authority."
    )
    credential_source = registered_text(
        setup, "Synthetic manufacturing issuer basis", credential_text
    )
    prior_store = getattr(setup.engine, "_pdos_change_store", None)
    prior_synthetic = getattr(setup.engine, "_pdos_professional_synthetic", False)
    evidence.configure_store(
        setup.engine, LocalPrivateObjectStore(tmp_path / "manufacturing-sources")
    )
    issuer = professional.configure_local_synthetic_profiles(
        setup.engine,
        [
            {
                "tenant_id": str(setup.tenant),
                "product_id": str(setup.product),
                "project_id": str(project_id),
                "key": f"synthetic-manufacturing:{setup.product}",
                "version": "isolated-manufacturing-v1",
            }
        ],
        enabled=True,
    )[0]
    work = SimpleNamespace(
        setup=setup,
        config=configuration,
        project_id=project_id,
        purpose=purpose,
        process_ref=process_ref,
        operation_keys=operation_keys,
        definition_sources=definition_sources,
        configuration_reads=configuration_reads,
        document_source=document_source,
        credential_source=credential_source,
        credential_text=credential_text,
        issuer=issuer,
        authority_receipts=None,
    )
    try:
        yield work
    finally:
        professional.disable_issuer(setup.engine, issuer.key)
        setup.engine._pdos_professional_synthetic = prior_synthetic
        evidence.configure_store(setup.engine, prior_store)


def bootstrap_authority(work):
    assert work.authority_receipts is None
    setup, at = work.setup, now()
    receipts = {}
    for kind in ("duty", "qualification"):
        payload = {
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "subject_id": str(setup.human),
            "external_id": f"synthetic-mp-{setup.product}-{kind}",
            "kind": kind,
            "role": "manufacturing",
            "operations": list(OPERATIONS),
            "purposes": [work.purpose],
            "state": "active",
            "valid_from": (at - timedelta(minutes=1)).isoformat(),
            "valid_until": (at + timedelta(minutes=45)).isoformat(),
            "approval": {
                "system": "Synthetic manufacturing authority",
                "external_id": str(uuid4()),
                "version": "isolated-manufacturing-v1",
                "approved_by": "Synthetic test issuer",
                "issued_at": (at - timedelta(minutes=1)).isoformat(),
            },
            "sources": [source_ref(work.credential_source, work.credential_text)],
            "reason": "Current bounded synthetic authority; no real manufacturing qualification",
        }
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.ctx.actor_id,
            requester_id=setup.ctx.requester_id,
            category_id=setup.category,
        ) as session:
            receipts[kind] = import_professional_fact(
                session,
                setup.ctx,
                work.issuer,
                payload,
                request_key=str(uuid4()),
                command_id=uuid4(),
            )
    work.authority_receipts = receipts
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        facts = list(
            session.scalars(
                select(ProfessionalFact).where(
                    ProfessionalFact.product_id == setup.product,
                    ProfessionalFact.subject_id == setup.human,
                )
            )
        )
        assert len(facts) == 2 and {fact.kind for fact in facts} == {"duty", "qualification"}
        assert all(
            fact.nature == "synthetic" and fact.project_id == work.project_id for fact in facts
        )
    return receipts


def payload(work, kind, *, previous=None, documents=None, revision=1):
    line = {"work_instruction": revision, "control_plan": 3, "manufacturing_baseline": 4}[kind]
    ref = source_ref(work.document_source, DOCUMENT_LINES[line - 1], line)
    body = {
        "project_id": str(work.project_id),
        "process": deepcopy(work.process_ref),
        "title": f"Synthetic {kind} documentation",
        "previous_id": None,
        "expected_previous_revision": None,
        "visibility": "private",
        "reason": f"Save exact synthetic {kind} draft; qualification for release remains unknown",
        "sources": [ref],
    }
    if previous:
        body.update(previous_id=previous["id"], expected_previous_revision=previous["revision"])
    if kind == "work_instruction":
        body.update(
            operation_key=work.operation_keys[0],
            conditions=None,
            steps=[
                {
                    "key": "assemble",
                    "text": DOCUMENT_LINES[line - 1],
                    "sources": [ref],
                    "safety_notes": None,
                    "parameters": [
                        {
                            "key": "torque",
                            "nominal": None,
                            "lower": None,
                            "upper": None,
                            "unit": None,
                            "sources": [],
                        }
                    ],
                }
            ],
        )
    elif kind == "control_plan":
        body.update(
            operation_key=work.operation_keys[0],
            checks=[
                {
                    "key": "fit",
                    "feature": "Synthetic housing fit",
                    "method": None,
                    "criterion": None,
                    "frequency": None,
                    "sampling_method": None,
                    "reaction_plan": None,
                    "responsible_role": None,
                    "sources": [ref],
                }
            ],
        )
    else:
        selected = documents or {}
        body.update(
            operations=[
                {
                    "operation_key": key,
                    **{
                        name: (
                            selected[name]
                            if key == work.operation_keys[0] and name in selected
                            else None
                        )
                        for name in ("work_instruction", "control_plan")
                    },
                }
                for key in work.operation_keys
            ],
            risk_notes=None,
            packaging_label_basis=None,
        )
    return body


def inputs(work, kind, body):
    setup = work.setup
    command = cmd(setup, f"npi.{kind}.record", deepcopy(body))
    before = deepcopy(command)
    response = setup.client.post(
        f"/v1/categories/{setup.category}/products/{setup.product}/manufacturing-preparations/inputs",
        headers=setup.headers,
        json=command,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    returned = result["command"]
    assert {k: v for k, v in returned.items() if k != "source_read_set"} == {
        k: v for k, v in before.items() if k != "source_read_set"
    }
    reads = returned["source_read_set"]
    required = {
        (str(ref["artifact_id"]), ref["expected_revision"]) for ref in work.definition_sources
    }
    required |= {
        (str(ref["artifact_id"]), ref["expected_revision"]) for ref in work.configuration_reads
    }
    required |= {(work.document_source, 1), (work.credential_source, 1)}
    actual = {(ref["artifact_id"], ref["expected_revision"]) for ref in reads}
    assert actual == required and len(reads) == len(actual) <= 20
    assert result["review"]["required_source_read_set"] == reads
    assert result["review"]["authority"]["synthetic"] is True
    assert result["review"]["authority"]["qualified"] is True
    return result


def prepared(work, material):
    response = post(work.setup, material["command"], True)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["review"] == material["review"]
    return result["command"]


def proof(work, command):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.ctx.actor_id,
        requester_id=work.setup.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        row = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert row is not None
        return row.id, row.consumed


def fixed(work, kind, receipt):
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/manufacturing-preparations/{kind}/{receipt['subject_id']}"
        f"?revision={receipt['subject_revision']}",
        headers=work.setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def history(work):
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/manufacturing-preparations"
        f"?project_id={work.project_id}&process_id={work.process_ref['id']}",
        headers=work.setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def effect_counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.ctx.actor_id,
        requester_id=work.setup.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in EFFECT_MODELS
        }


def effect_hashes(work):
    """Hash all tenant rows and columns, including Product epoch and T1 consumption."""
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.ctx.actor_id,
        requester_id=work.setup.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        return {
            model.__tablename__: digest(
                sorted(
                    [
                        {
                            column.name: getattr(row, column.name)
                            for column in model.__table__.columns
                        }
                        for row in session.scalars(
                            select(model).where(model.tenant_id == work.setup.tenant)
                        )
                    ],
                    key=lambda row: str(row["id"]),
                )
            )
            for model in (*EFFECT_MODELS, Product, Confirmation)
        }


def parents(work):
    # Successfully adding a consuming document reference legitimately advances
    # Product.lifecycle_epoch. Check every other Product business column and all
    # ten parent tables here; effect_hashes retains the epoch for no-effect checks.
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.ctx.actor_id,
        requester_id=work.setup.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        return {
            model.__tablename__: digest(
                sorted(
                    [
                        {
                            column.name: getattr(row, column.name)
                            for column in model.__table__.columns
                            if model is not Product or column.name != "lifecycle_epoch"
                        }
                        for row in session.scalars(
                            select(model).where(model.tenant_id == work.setup.tenant)
                        )
                    ],
                    key=lambda row: str(row["id"]),
                )
            )
            for model in PARENT_MODELS
        }


def assert_atom(work, command, receipt):
    setup = work.setup
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        row = session.get(PreparationVersion, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row is not None and saved is not None
        token = session.get(Confirmation, row.shared_proof_id)
        pointer = session.scalar(
            select(PreparationCurrent).where(
                PreparationCurrent.product_id == setup.product,
                PreparationCurrent.kind == row.kind,
                PreparationCurrent.series_id == row.series_id,
            )
        )
        assert saved.subject_id == row.id and saved.subject_revision == row.revision
        assert pointer.version_id == row.id and pointer.revision == row.revision
        assert token.consumed is True and token.token_hash == row.token_sha256
        assert token.created_at <= row.proof_consumed_at <= row.created_at < token.expires_at
        assert row.input_snapshot["command"]["idempotency_key"] == command["idempotency_key"]
        assert row.input_snapshot["command"]["command_id"] == command["command_id"]
        assert "confirmation_token" not in row.input_snapshot["command"]["payload"]
        assert saved.request_digest == row.input_snapshot["request_digest"]
        audit = list(session.scalars(select(Audit).where(Audit.receipt_id == saved.id)))
        outbox = list(session.scalars(select(Outbox).where(Outbox.receipt_id == saved.id)))
        key = list(
            session.scalars(
                select(RequestKey).where(
                    RequestKey.actor_id == setup.human, RequestKey.key == command["idempotency_key"]
                )
            )
        )
        assert len(audit) == len(outbox) == len(key) == 1
        assert key[0].receipt_id == saved.id and key[0].digest == saved.request_digest
        assert audit[0].operation == command["operation"]
        assert outbox[0].type == EVENTS[command["operation"]]
        assert outbox[0].subject_id == row.id and outbox[0].correlation_id == UUID(
            command["command_id"]
        )
        assert row.status == "draft" and row.authority_snapshot["synthetic"] is True
        assert row.body["manufacturing_release"] is None and row.body["qualification"] == "unknown"
        assert row.body["negative_enumeration_complete"] is False
        identity = row.id
    return identity
