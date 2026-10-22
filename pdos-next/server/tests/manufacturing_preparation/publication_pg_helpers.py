"""Root-run real publication fixture; every business step uses an actual port.

The shortest shared G0/configuration function is reused without its S3 callers.
Original bytes are synthetic; scanner and professional issuer are explicitly
controlled test profiles. No clock, material, authority or consumption is mocked.
"""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from change_execution.approved_configuration_helpers import initial_configuration
from fastapi.testclient import TestClient
from manufacturing_preparation_transactions import fixtures as preparation_fixture
from manufacturing_preparation_transactions.test_transactions import reference, save
from security_fixture import secured_parse, synthetic_runtime
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input
from test_project_first_plan import accepted, cmd, post

from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import EngineeringConfiguration
from pdos_next.domain.manufacturing_baseline.models import (
    BaselineDocumentLink,
    PreparationCurrent,
    PreparationVersion,
)
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication as Publication,
)
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublicationCurrent as Current,
)
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingPublicationDocument as Document,
)
from pdos_next.domain.manufacturing_baseline.publication_schemas import OPERATION
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.projects import service as projects
from pdos_next.models import (
    Artifact,
    Audit,
    Category,
    Confirmation,
    Consumption,
    OriginalSecurity,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
    now,
)
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.original_security import configure as configure_security
from pdos_next.originals import object_reference
from pdos_next.professional_import import import_professional_fact
from pdos_next.safety import verify_test_target
from pdos_next.service import Context, digest

OPERATIONS = (*preparation_fixture.OPERATIONS, OPERATION)
EXTRA_LINES = (
    "Synthetic named publication: fixed project documentation only; "
    "asset and manufacturing release remain unknown.",
    "Synthetic revision: preserve original fixed process and documents "
    "while recording this named review.",
    "Synthetic reaction and packaging basis: isolate anomalies; "
    "packaging validation remains unknown.",
)
LINES = (*preparation_fixture.DOCUMENT_LINES, *EXTRA_LINES)
PUBLICATION_MODELS = (Publication, Current, Document)
EFFECT_MODELS = (
    *PUBLICATION_MODELS,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
    Product,
)
ROLLBACK_MODELS = (*EFFECT_MODELS, Category, Consumption, Artifact, OriginalSecurity)
DRAFT_MODELS = (PreparationVersion, PreparationCurrent, BaselineDocumentLink)


def session(work, actor=None):
    setup = work.setup
    identity = actor or setup.human
    return tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=identity,
        requester_id=identity,
        category_id=setup.category,
    )


def headers(work, actor=None):
    setup = work.setup
    return {"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"}


def root_url(work):
    setup = work.setup
    return f"/v1/categories/{setup.category}/products/{setup.product}/manufacturing-publications"


def register_text(setup, title, text):
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": text,
                "source_label": "Bounded synthetic publication fixture",
                "visibility": "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["subject_id"]


@pytest.fixture
def publication_case(setup, tmp_path):
    # These runtime guards use only the caller's explicit isolated test target.
    # Collection never invokes them or opens a connection.
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    configuration = initial_configuration(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        project, _, definition = projects._project(
            s, setup.ctx, setup.product, UUID(configuration["project"])
        )
        process, viewed = configurations.get_process(
            s, setup.ctx, setup.product, UUID(configuration["process"]["subject_id"])
        )
        engineering = s.get(EngineeringConfiguration, process.engineering_configuration_id)
        project_id, purpose = project.id, project.purpose
        process_ref = {"id": str(process.id), "revision": process.revision}
        operation_keys = tuple(row["key"] for row in viewed["operations"])
        definition_sources = deepcopy(definition["sources"])
        configuration_reads = deepcopy(
            [
                *process.required_source_read_set,
                *engineering.required_source_read_set,
            ]
        )
    prior_client = setup.client
    prior_store = getattr(setup.engine, "_pdos_change_store", None)
    prior_result_store = getattr(setup.engine, "_pdos_results_store", None)
    prior_security = getattr(setup.engine, "_pdos_security_runtime", None)
    prior_synthetic = getattr(setup.engine, "_pdos_professional_synthetic", False)
    store = LocalPrivateObjectStore(tmp_path / "publication-originals")
    client = TestClient(
        create_app(
            setup.engine,
            setup.auth,
            object_store=store,
            security_runtime=synthetic_runtime(),
        )
    )
    setup.client = client
    work = SimpleNamespace(
        setup=setup,
        config=configuration,
        project_id=project_id,
        purpose=purpose,
        process_ref=process_ref,
        operation_keys=operation_keys,
        definition_sources=definition_sources,
        configuration_reads=configuration_reads,
        store=store,
        authority_receipts={},
    )
    issuer = None
    try:
        content = ("\n".join(LINES) + "\n").encode("utf-8")
        uploaded = client.post(
            f"/v1/categories/{setup.category}/products/{setup.product}/originals",
            headers=setup.headers,
            json=upload_input(
                content,
                title="Synthetic fixed manufacturing publication originals",
                visibility="category",
            ).model_dump(mode="json"),
        )
        assert uploaded.status_code == 200, uploaded.text
        work.original_id = UUID(uploaded.json()["subject_id"])
        parsed = secured_parse(
            setup.engine,
            {
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "actor_id": str(setup.human),
                "requester_id": str(setup.human),
                "product_id": str(setup.product),
                "subject_id": str(work.original_id),
            },
            store,
        )
        assert parsed["status"] == "parsed", parsed
        with session(work) as s:
            artifact = s.scalar(select(Artifact).where(Artifact.original_id == work.original_id))
            original = s.get(UploadedOriginal, work.original_id)
            assert artifact is not None and artifact.content.splitlines() == list(LINES)
            assert store.read_original(object_reference(original)) == content
            work.document_source = str(artifact.id)
        work.credential_text = (
            f"Synthetic named manufacturing duty and qualification for {setup.human} and "
            f"{setup.peer}, project {project_id}, purpose {purpose}; operations "
            f"{', '.join(OPERATIONS)}. Isolated test only; no real qualification."
        )
        work.credential_source = register_text(
            setup, "Synthetic publication personnel qualification basis", work.credential_text
        )
        issuer = professional.configure_local_synthetic_profiles(
            setup.engine,
            [
                {
                    "tenant_id": str(setup.tenant),
                    "product_id": str(setup.product),
                    "project_id": str(project_id),
                    "key": f"synthetic-publication:{setup.product}",
                    "version": "isolated-publication-v1",
                }
            ],
            enabled=True,
        )[0]
        work.issuer = issuer
        yield work
    finally:
        if issuer is not None:
            professional.disable_issuer(setup.engine, issuer.key)
        setup.engine._pdos_professional_synthetic = prior_synthetic
        client.close()
        setup.client = prior_client
        evidence.configure_store(setup.engine, prior_store)
        from pdos_next.domain.verification_results.service import configure_store

        configure_store(setup.engine, prior_result_store)
        configure_security(setup.engine, prior_security)


def import_authority(work, actor):
    """Actual trusted synthetic import; no qualification business row is assigned."""
    assert actor not in work.authority_receipts
    setup, at = work.setup, now()
    receipts = {}
    for kind in ("duty", "qualification"):
        payload = {
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "subject_id": str(actor),
            "external_id": f"synthetic-pub-{actor}-{kind}",
            "kind": kind,
            "role": "manufacturing",
            "operations": list(OPERATIONS),
            "purposes": [work.purpose],
            "state": "active",
            "valid_from": (at - timedelta(minutes=1)).isoformat(),
            "valid_until": (at + timedelta(minutes=45)).isoformat(),
            "approval": {
                "system": "Synthetic controlled publication authority",
                "external_id": str(uuid4()),
                "version": "isolated-publication-v1",
                "approved_by": "Explicit synthetic test issuer",
                "issued_at": (at - timedelta(minutes=1)).isoformat(),
            },
            "sources": [
                preparation_fixture.source_ref(
                    work.credential_source,
                    work.credential_text,
                )
            ],
            "reason": "Current synthetic duty/qualification; never production enablement",
        }
        with session(work) as s:
            receipts[kind] = import_professional_fact(
                s,
                setup.ctx,
                work.issuer,
                payload,
                request_key=str(uuid4()),
                command_id=uuid4(),
            )
    work.authority_receipts[actor] = receipts
    with session(work, actor) as s:
        assessed = professional.assess(
            s,
            Context(setup.tenant, actor, actor, category_id=setup.category),
            setup.product,
            work.project_id,
            OPERATION,
            work.purpose,
            now(),
        )
        assert assessed["authorized"] is assessed["qualified"] is True
        assert assessed["roles"] == ["manufacturing"] and assessed["synthetic"] is True
    return receipts


def save_drafts(work):
    documents, commands, receipts = {}, {}, {}
    for kind in ("work_instruction", "control_plan"):
        body = preparation_fixture.payload(work, kind)
        body["visibility"] = "category"
        commands[kind], receipts[kind], documents[kind] = save(
            work,
            preparation_fixture.inputs(work, kind, body),
        )
    body = preparation_fixture.payload(
        work,
        "manufacturing_baseline",
        documents={kind: reference(view) for kind, view in documents.items()},
    )
    body["visibility"] = "category"
    (
        commands["manufacturing_baseline"],
        receipts["manufacturing_baseline"],
        documents["manufacturing_baseline"],
    ) = save(
        work,
        preparation_fixture.inputs(work, "manufacturing_baseline", body),
    )
    work.draft_commands, work.draft_receipts, work.documents = commands, receipts, documents
    return documents["manufacturing_baseline"]


def publication_payload(work, *, previous=None, revision=1):
    baseline = work.documents["manufacturing_baseline"]
    selected = preparation_fixture.source_ref(
        work.document_source, LINES[4 if revision == 1 else 5], 5 if revision == 1 else 6
    )
    reaction = preparation_fixture.source_ref(work.document_source, LINES[6], 7)
    return {
        "project_id": str(work.project_id),
        "baseline": {"kind": "manufacturing_baseline", "id": baseline["id"], "revision": 1},
        "purpose": work.purpose,
        "applicability": {
            "site": "SYN-INTERNAL-LAB",
            "lines": None,
            "conditions": {"text": selected["quote"], "sources": [selected]},
            "sources": [selected],
        },
        "requirements": [],
        "risk": None,
        "packaging": None,
        "reaction_plan": {"text": reaction["quote"], "sources": [reaction]},
        "previous_id": previous["id"] if previous else None,
        "expected_previous_revision": previous["revision"] if previous else None,
        "visibility": "category",
        "reason": f"Named synthetic fixed documentation revision {revision}",
        "sources": [selected],
    }


def input_response(work, payload, actor=None):
    return work.setup.client.post(
        root_url(work) + "/inputs",
        headers=headers(work, actor),
        json=cmd(
            work.setup,
            OPERATION,
            deepcopy(payload),
        ),
    )


def prepare_publication(work, payload):
    request = cmd(work.setup, OPERATION, deepcopy(payload))
    original = deepcopy(request)
    response = work.setup.client.post(
        root_url(work) + "/inputs", headers=headers(work), json=request
    )
    assert response.status_code == 200, response.text
    material = response.json()
    assert request == original
    assert {
        key: value for key, value in material["command"].items() if key != "source_read_set"
    } == {key: value for key, value in original.items() if key != "source_read_set"}
    preview = post(work.setup, material["command"], True)
    assert preview.status_code == 200, preview.text
    value = preview.json()
    assert value["review"] == material["review"]
    assert value["write_tier"] == "T2" and value["named_decision"] is True
    assert value["expires_at"] is None
    assert value["command"]["payload"]["approval_token"]
    return value["command"], value["review"]


def publication(work, receipt, actor=None):
    identity = receipt.get("subject_id", receipt.get("id"))
    revision = receipt.get("subject_revision", receipt.get("revision"))
    response = work.setup.client.get(
        root_url(work) + f"/{identity}?revision={revision}",
        headers=headers(work, actor),
    )
    assert response.status_code == 200, response.text
    return response.json()


def publications(work, actor=None):
    response = work.setup.client.get(
        root_url(work) + f"?project_id={work.project_id}",
        headers=headers(work, actor),
    )
    assert response.status_code == 200, response.text
    return response.json()


def proof(work, command):
    with session(work) as s:
        row = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["approval_token"]),
            )
        )
        assert row is not None
        return row.id, row.consumed, row.expires_at


def snapshots(work, models=EFFECT_MODELS):
    """Read actual rows as admin for tenant-wide rollback/count comparisons only."""
    with Session(work.setup.admin) as s:
        return {
            model.__tablename__: {
                "count": len(
                    rows := list(
                        s.scalars(select(model).where(model.tenant_id == work.setup.tenant))
                    )
                ),
                "sha256": digest(
                    sorted(
                        [
                            {
                                column.key: getattr(row, column.key)
                                for column in model.__table__.columns
                            }
                            for row in rows
                        ],
                        key=lambda row: str(row["id"]),
                    )
                ),
            }
            for model in models
        }


def assert_published_atom(work, command, receipt):
    with session(work) as s:
        row = s.get(Publication, UUID(receipt["subject_id"]))
        saved = s.get(Receipt, UUID(receipt["id"]))
        confirmation = s.get(Confirmation, row.shared_proof_id)
        pointer = s.scalar(select(Current).where(Current.series_id == row.series_id))
        assert row.receipt_id == saved.id and row.command_id == saved.command_id
        assert row.shared_proof_id == saved.confirmation_id == confirmation.id
        assert confirmation.consumed is True and confirmation.expires_at is None
        assert (
            confirmation.created_at <= row.proof_consumed_at <= row.created_at <= saved.created_at
        )
        assert row.proof_expires_at is None
        assert pointer.version_id == row.id and pointer.revision == row.revision
        assert row.body["qualification"] == "unknown" and row.body["manufacturing_release"] is None
        assert "nature" not in row.body and "nature" not in row.input_snapshot["plan"]
        assert (
            row.input_snapshot["original_key_sha256"]
            == sha256(command["idempotency_key"].encode("utf-8")).hexdigest()
        )
        assert "idempotency_key" not in row.input_snapshot["command"]
        assert "approval_token" not in row.input_snapshot["command"]["payload"]
        assert command["idempotency_key"] not in str(row.input_snapshot)
        assert command["payload"]["approval_token"] not in str(row.input_snapshot)
        assert row.body_sha256 == digest(row.body)
        assert (
            saved.intent_digest == row.intent_digest and saved.request_digest == row.request_digest
        )
        for model in (Audit, Outbox):
            rows = list(s.scalars(select(model).where(model.receipt_id == saved.id)))
            assert len(rows) == 1 and rows[0].actor_id == work.setup.human
        links = list(s.scalars(select(Document).where(Document.publication_id == row.id)))
        assert len(links) == 2 and {link.document_kind for link in links} == {
            "work_instruction",
            "control_plan",
        }


def withdraw_original(work):
    with session(work) as s:
        state = s.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == work.original_id)
        )
        epoch = state.epoch
    receipt, _ = accepted(
        work.setup,
        cmd(
            work.setup,
            "evidence.original.withdraw",
            {
                "original_id": str(work.original_id),
                "expected_epoch": epoch,
                "reason": "Synthetic source withdrawal; preserve fixed publication history",
            },
        ),
    )
    with session(work) as s:
        source = s.get(Artifact, UUID(work.document_source))
        original = s.get(UploadedOriginal, work.original_id)
        assert source.status == "withdrawn" and source.content.splitlines() == list(LINES)
        assert original.status == "parsed"
        assert (
            work.store.read_original(object_reference(original))
            == ("\n".join(LINES) + "\n").encode()
        )
    return receipt
