"""Actual shared publication -> new physical Build -> Pilot original material.

Root alone executes this synthetic fixture against its explicitly verified PG
target. All business facts use public commands or existing controlled imports.
The reused S2 failure/Issue is part of this one case, not another acceptance.
"""

import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from manufacturing_preparation import publication_pg_helpers as publication
from quality_execution import fixtures as quality
from security_fixture import secured_parse
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_build_execution import actual_command, allocation_command, execution_view, output_command
from test_builds import build_command
from test_durable_evidence import upload_input
from test_project_first_plan import accepted, cmd, post

from pdos_next.domain.build_execution import service as physical
from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.schemas import FactInput, OperationalScope
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.manufacturing_trials.native_models import (
    NativePilotCurrent,
    NativePilotObservation,
    NativePilotRun,
)
from pdos_next.domain.manufacturing_trials.native_schemas import (
    CREATE_OPERATION,
    RESULT_OPERATION,
    PilotCreatePayload,
    PilotResultPayload,
    StatisticsBasis,
)
from pdos_next.domain.manufacturing_trials.native_statistics_owner import (
    result_values,
    statistics_declaration,
)
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
    now,
)
from pdos_next.operational_import import import_operational_fact
from pdos_next.originals import object_reference
from pdos_next.safety import verify_test_target
from pdos_next.schemas.manufacturing_trials.contracts import (
    Counts,
    ExceptionFact,
    LotBasis,
    PilotCreate,
    Ref,
    ResultRecord,
    YieldScope,
)
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest

PILOT_MODELS = (NativePilotRun, NativePilotCurrent, NativePilotObservation)
EFFECT_MODELS = (*PILOT_MODELS, Receipt, Audit, Outbox, RequestKey, Confirmation, Product)
ROLLBACK_MODELS = (*EFFECT_MODELS, Category, Consumption, Artifact, OriginalSecurity)


def root_url(work):
    setup = work.setup
    return f"/v1/categories/{setup.category}/products/{setup.product}/pilots"


def input_response(work, operation, payload, *, actor=None):
    return work.setup.client.post(
        root_url(work) + "/inputs",
        headers=publication.headers(work, actor),
        json=cmd(work.setup, operation, deepcopy(payload)),
    )


def prepare(work, operation, payload):
    response = input_response(work, operation, payload)
    assert response.status_code == 200, response.text
    prepared = response.json()
    preview = post(work.setup, prepared["command"], True)
    assert preview.status_code == 200, preview.text
    value = preview.json()
    assert value.get("write_tier", "T1") == "T1"
    assert value["review"] == prepared["review"]
    assert value["command"]["payload"]["confirmation_token"]
    assert value["expires_at"] is not None
    return value["command"], value["review"]


def read_pilot(work, identity, *, actor=None):
    response = work.setup.client.get(
        root_url(work) + f"/{identity}", headers=publication.headers(work, actor)
    )
    assert response.status_code == 200, response.text
    return response.json()


def list_pilots(work, *, actor=None):
    response = work.setup.client.get(
        root_url(work),
        params={"project_id": str(work.project_id)},
        headers=publication.headers(work, actor),
    )
    assert response.status_code == 200, response.text
    return response.json()


def proof(work, command):
    with publication.session(work) as s:
        row = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert row is not None
        return row.id, row.consumed, row.expires_at


def snapshots(work, models=EFFECT_MODELS):
    return publication.snapshots(work, models)


def upload_json(work, value, title, *, visibility="category"):
    """Actual upload, scanner/parse, retained bytes and exact whole-line hash."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    content = (text + "\n").encode()
    response = work.setup.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
        headers=work.setup.headers,
        json=upload_input(content, title=title, visibility=visibility).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    original_id = UUID(response.json()["subject_id"])
    parsed = secured_parse(
        work.setup.engine,
        {
            "tenant_id": str(work.setup.tenant),
            "category_id": str(work.setup.category),
            "actor_id": str(work.setup.human),
            "requester_id": str(work.setup.human),
            "product_id": str(work.setup.product),
            "subject_id": str(original_id),
        },
        work.store,
    )
    assert parsed["status"] == "parsed", parsed
    with publication.session(work) as s:
        artifact = s.scalar(select(Artifact).where(Artifact.original_id == original_id))
        original = s.get(publication.UploadedOriginal, original_id)
        assert artifact is not None and artifact.content.splitlines() == [text]
        assert work.store.read_original(object_reference(original)) == content
        source = SourceRef(
            kind="artifact",
            id=artifact.id,
            revision=artifact.revision,
            position="line:1;quote_sha256:" + sha256(text.encode()).hexdigest(),
        )
    return source, original_id


def new_physical_build(work):
    """Actual APIs leave the prior Build, start, resources and samples intact."""
    setup, config = work.setup, work.config
    with publication.session(work) as s:
        project, _, _ = projects._project(s, setup.ctx, setup.product, work.project_id)
        engineering, _ = configurations.get_engineering(
            s, setup.ctx, setup.product, UUID(config["engineering"]["subject_id"])
        )
        process, viewed = configurations.get_process(
            s, setup.ctx, setup.product, UUID(config["process"]["subject_id"])
        )
        revisions = project.revision, engineering.revision, process.revision
        work.operation_key = viewed["operations"][0]["key"]
        # Some legitimate fixed Processes leave site unspecified. In that case
        # use this case's actual prior operational declaration; the new line
        # original below explicitly records it, without rewriting the Process.
        work.site = process.site if process.site is not None else work.upstream.scope.site
    built, _ = accepted(
        setup,
        build_command(
            setup,
            config,
            expected_project_revision=revisions[0],
            name="Synthetic native Pilot continuation",
            type="pilot",
            purpose=work.purpose,
            planned_quantity="2",
            unit="ea",
            previous_build_id=work.upstream.build_id,
        ),
    )
    planned = {**config, "build": built}
    actual, _ = accepted(
        setup,
        actual_command(
            setup,
            planned,
            expected_actual_engineering_revision=revisions[1],
            expected_actual_manufacturing_revision=revisions[2],
            observed_at=(now() - timedelta(minutes=3)).isoformat(),
        ),
    )
    work.output_occurred_at = now() - timedelta(minutes=2)
    lot, _ = accepted(
        setup,
        output_command(
            setup,
            planned,
            actual,
            units=2,
            observation={
                "system": "Synthetic native Pilot external record",
                "external_id": str(uuid4()),
                "nature": "synthetic",
                "occurred_at": work.output_occurred_at.isoformat(),
            },
        ),
    )
    allocated, _ = accepted(
        setup,
        allocation_command(
            setup,
            planned,
            lot,
            samples=[
                {"label": f"SYN-PILOT-{uuid4()}", "operation_key": work.operation_key}
                for _ in range(2)
            ],
        ),
    )
    actual_view = execution_view(setup)
    samples = [
        sample
        for sample in actual_view["samples"]
        if sample["allocation_id"] == allocated["subject_id"]
    ]
    assert len(samples) == 2
    with publication.session(work) as s:
        row, view = physical.get_lot(s, setup.ctx, setup.product, UUID(lot["subject_id"]))
        actual_row, _ = physical.get_actual_configuration(
            s, setup.ctx, setup.product, row.actual_configuration_id
        )
        assert row.observed_unit_count == len(samples) == 2
        work.basis = LotBasis(
            build=Ref(kind="build", id=row.build_id, revision=row.build_revision),
            lot=Ref(kind="build_lot", id=row.id, revision=row.revision),
            actual_configuration=Ref(
                kind="actual_configuration", id=actual_row.id, revision=actual_row.revision
            ),
            engineering_configuration=Ref(
                kind="engineering_configuration",
                id=actual_row.actual_engineering_configuration_id,
                revision=actual_row.actual_engineering_revision,
            ),
            process_revision=Ref(
                kind="process_revision",
                id=actual_row.actual_manufacturing_configuration_id,
                revision=actual_row.actual_manufacturing_revision,
            ),
            unit=row.unit,
        )
        assert row.project_id == work.project_id and view["observation"]["nature"] == "synthetic"
        work.population_count = row.observed_unit_count
    work.new_build_receipt, work.new_lot_receipt = built, lot
    work.samples = tuple(
        Ref(kind="sample", id=sample["id"], revision=sample["revision"]) for sample in samples
    )
    work.line = Ref(kind="line", id=uuid4(), revision=1)


def import_line(work):
    """A new actual Fact/Current/Asset relation with no accepted decision facts."""
    setup, at = work.setup, now()
    scope = OperationalScope(
        purpose=work.purpose,
        quantity=str(work.population_count),
        unit=work.basis.unit,
        site=work.site,
        window={
            "start": work.output_occurred_at - timedelta(minutes=2),
            "finish": at + timedelta(minutes=60),
            "original_timezone": "UTC",
        },
    )
    statement = {
        "build": work.basis.build.model_dump(mode="json"),
        "process": work.basis.process_revision.model_dump(mode="json"),
        "scope": scope.model_dump(mode="json"),
        "operation_key": work.operation_key,
        "resource": work.line.model_dump(mode="json"),
        "lifecycle": "active",
        "facts": [],
        "meaning": (
            "Synthetic actual line identity/relation; acceptance, calibration "
            "and qualification unknown"
        ),
    }
    text = json.dumps(statement, ensure_ascii=False, separators=(",", ":"))
    identity = publication.register_text(setup, "Synthetic Pilot line relation original", text)
    source = {"artifact_id": identity, "expected_revision": 1, "line": 1, "quote": text}
    issuer = operational.configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=work.project_id,
        key=f"native-pilot-line:{work.basis.build.id}",
        enabled=True,
        test_marker_verified=True,
    )
    payload = FactInput.model_validate(
        {
            "build_id": work.basis.build.id,
            "expected_build_revision": work.basis.build.revision,
            "scope": scope.model_dump(mode="json"),
            "external_id": f"SYN-PILOT-{work.basis.build.id}",
            "valid_from": scope.window.start - timedelta(minutes=1),
            "valid_until": at + timedelta(minutes=65),
            "sources": [source],
            "reason": "Controlled synthetic identity and relationship only",
            "resources": [
                {
                    "resource": work.line.model_dump(mode="json"),
                    "purposes": [scope.purpose],
                    "operation_ids": [work.operation_key],
                    "lifecycle": "active",
                    "facts": [],
                    "sources": [source],
                }
            ],
            "requirements": [
                {
                    "operation_key": work.operation_key,
                    "uses": [{"resource": work.line.model_dump(mode="json"), "units": "1"}],
                    "sources": [source],
                }
            ],
        }
    )
    with publication.session(work) as s:
        work.line_receipt = import_operational_fact(
            s, setup.ctx, issuer, payload, request_key=str(uuid4()), command_id=uuid4()
        )
    work.line_issuer, work.execution_scope = issuer, scope


def create_payload(work):
    placeholder = SourceRef(
        kind="artifact",
        id=work.document_source,
        revision=1,
        position="line:5;quote_sha256:" + sha256(publication.LINES[4].encode()).hexdigest(),
    )
    details = PilotCreate(
        pilot_id=uuid4(),
        basis=work.basis,
        purpose=work.purpose,
        manufacturing_baseline=Ref(
            kind="manufacturing_baseline",
            id=work.published["id"],
            revision=work.published["revision"],
        ),
        line=work.line,
        source=placeholder,
    )
    statistics = StatisticsBasis(
        site=work.site,
        original_timezone="UTC",
        window_start=work.output_occurred_at - timedelta(seconds=1),
        window_end=now() - timedelta(seconds=20),
        cohort_mode="entire_lot",
        samples=work.samples,
        statistics_basis_key=f"native-lot-{work.basis.lot.id}",
        criterion_id=uuid4(),
        criterion_text=(
            "Synthetic fixed Pilot wording: first pass and final good "
            "use the same actual input units"
        ),
        minimum_sample=1,
        operation_key=work.operation_key,
        operational_scope=work.execution_scope,
        source=placeholder,
    )
    source, original_id = upload_json(
        work,
        statistics_declaration(details.pilot_id, statistics),
        "Synthetic exact fixed Pilot statistics declaration",
    )
    statistics = statistics.model_copy(update={"source": source})
    work.statistics_original_id = original_id
    return PilotCreatePayload(
        project_id=work.project_id,
        details=details,
        statistics=statistics,
        visibility="category",
    )


def result_payload(work, create, *, revision=1, previous=None, complete=False, exception=False):
    stats = create.statistics
    assert stats is not None
    occurred = work.output_occurred_at + timedelta(seconds=20 if complete else 10)
    scope = YieldScope(
        basis=create.details.basis,
        manufacturing_baseline=create.details.manufacturing_baseline,
        line=create.details.line,
        cohort_key=stats.statistics_basis_key,
        window_start=stats.window_start,
        window_end=stats.window_end,
        criterion=Ref(kind="criterion", id=stats.criterion_id, revision=1),
        nature="synthetic",
        minimum_sample=stats.minimum_sample,
    )
    source = create.details.source
    exceptions = ()
    if exception:
        with publication.session(work) as s:
            from pdos_next.domain.quality_execution import service as issue_owner

            row, view = issue_owner.get_issue_for_change(
                s, work.setup.ctx, work.setup.product, work.issue_id
            )
            assert row.project_id == work.project_id and view.is_current
            selected = Ref(kind="issue", id=row.issue_id, revision=row.revision)
        exceptions = (
            ExceptionFact(
                key="real-current-issue",
                description=(
                    "One actual input required rework; retain the existing "
                    "same-project failure Issue"
                ),
                source=source,
                issue=selected,
                disposition=source,
            ),
        )
    record = ResultRecord(
        observation_id=uuid4(),
        expected_pilot_revision=revision,
        previous_observation_id=UUID(previous["id"]) if previous else None,
        correction_reason="Recorded completed rework from the next original" if previous else None,
        scope=scope,
        counts=Counts(
            input_count=work.population_count,
            output_count=work.population_count,
            first_pass=1,
            first_failed=1,
            first_unknown=0,
            final_good=2 if complete else 1,
            reworked_good=1 if complete else 0,
            scrap=0,
            rework_pending=0 if complete else 1,
            undecided=0,
            unprocessed=0,
            rework_cycles=1 if complete else 0,
        ),
        exceptions=exceptions,
        observed={"occurred_at": occurred, "original_timezone": "UTC", "source": source},
        source=source,
    )
    original_source, original_id = upload_json(
        work,
        result_values(create.details.pilot_id, record),
        "Synthetic exact Pilot original observation",
    )
    record = record.model_copy(
        update={
            "source": original_source,
            "observed": record.observed.model_copy(update={"source": original_source}),
            "exceptions": tuple(
                value.model_copy(update={"source": original_source, "disposition": original_source})
                for value in record.exceptions
            ),
        }
    )
    return PilotResultPayload(
        pilot_id=create.details.pilot_id, expected_pilot_revision=revision, record=record
    ), original_id


def assert_atom(work, command, receipt, model):
    with publication.session(work) as s:
        row = s.get(model, UUID(receipt["subject_id"]))
        saved = s.get(Receipt, UUID(receipt["id"]))
        proof = s.get(Confirmation, row.shared_proof_id)
        assert row.command_id == saved.command_id == UUID(command["command_id"])
        assert row.receipt_id == saved.id and saved.confirmation_id == proof.id
        assert row.proof_consumed_at <= row.created_at <= saved.created_at < row.proof_expires_at
        assert proof.consumed and proof.expires_at == row.proof_expires_at
        assert row.write_tier == "T1" and row.request_digest == saved.request_digest
        assert (
            row.input_snapshot["original_key_sha256"]
            == sha256(command["idempotency_key"].encode()).hexdigest()
        )
        assert command["idempotency_key"] not in str(row.input_snapshot)
        assert command["payload"]["confirmation_token"] not in str(row.input_snapshot)
        for kind in (Audit, Outbox):
            assert len(list(s.scalars(select(kind).where(kind.receipt_id == saved.id)))) == 1


def observation_snapshot(work, identity):
    with Session(work.setup.admin) as s:
        row = s.get(NativePilotObservation, UUID(identity))
        return {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.columns}


def withdraw(work, original_id):
    with publication.session(work) as s:
        security = s.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original_id)
        )
        epoch = security.epoch
    return accepted(
        work.setup,
        cmd(
            work.setup,
            "evidence.original.withdraw",
            {
                "original_id": str(original_id),
                "expected_epoch": epoch,
                "reason": "Synthetic Pilot source withdrawn; retain history, block new consumption",
            },
        ),
    )[0]


@pytest.fixture
def native_case(quality_work, tmp_path, monkeypatch):
    upstream = quality_work
    setup = upstream.setup
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    # Fixture construction aliases only: reuse actual saved Project/configs and
    # the actual source store, so old failure bytes remain readable to owners.
    monkeypatch.setattr(
        publication, "initial_configuration", lambda selected: deepcopy(upstream.config)
    )
    monkeypatch.setattr(publication, "LocalPrivateObjectStore", lambda _path: upstream.report_store)
    monkeypatch.setattr(
        publication, "OPERATIONS", (*publication.OPERATIONS, CREATE_OPERATION, RESULT_OPERATION)
    )
    factory = publication.publication_case.__wrapped__(setup, tmp_path)
    work = next(factory)
    work.upstream = upstream
    work.line_issuer = None
    try:
        publication.import_authority(work, setup.human)
        publication.import_authority(work, setup.peer)
        quality.publish_policy(upstream)
        issue_command = quality.command(
            upstream,
            "quality.issue.create",
            {**quality.payload_create(upstream), "visibility": "category"},
        )
        issue_response = post(upstream.quality, issue_command)
        assert issue_response.status_code == 200, issue_response.text
        issue_receipt = issue_response.json()
        work.issue_id = UUID(issue_receipt["result"]["issue_id"])
        work.issue_receipt = issue_receipt
        new_physical_build(work)
        import_line(work)
        publication.save_drafts(work)
        payload = publication.publication_payload(work)
        payload["applicability"]["lines"] = [work.line.model_dump(mode="json")]
        pub_command, _ = publication.prepare_publication(work, payload)
        pub_response = post(setup, pub_command)
        assert pub_response.status_code == 200, pub_response.text
        work.publication_receipt = pub_response.json()
        work.published = publication.publication(work, work.publication_receipt)
        work.create = create_payload(work)
        yield work
    finally:
        if work.line_issuer is not None:
            operational.disable_issuer(setup.engine, work.line_issuer.key)
        factory.close()
