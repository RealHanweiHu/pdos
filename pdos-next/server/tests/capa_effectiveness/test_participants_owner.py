"""No-connect, actual Session/UOW and real Core query guards.

Saved rows below are explicit substitutes. These checks do not demonstrate PG
constraints, actual report bytes, professional qualification or independence.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import participants_owner as owner
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (
    MeasurementImportCapture,
    MeasurementRecord,
)
from pdos_next.domain.verification_results.models import (
    TestResultActionFact as ResultActionFact,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef


class RawSession(Session):
    """Query-aware no-connect substitute; real Session transactions remain real."""

    def __init__(self, engine):
        super().__init__(engine)
        self.rows, self.queries, self.after_query = {}, [], None

    def seed(self, model, **values):
        row = {c.name: values.get(c.name) for c in model.__table__.c}
        self.rows.setdefault(model.__tablename__, []).append(row)
        return row

    def selected(self, statement):
        self.queries.append(statement)
        table = statement.get_final_froms()[0]
        rows = list(self.rows.get(table.name, ()))
        from sqlalchemy.sql import operators

        def matches(row, expression):
            if expression.operator is operators.or_:
                return any(matches(row, part) for part in expression.clauses)
            if expression.operator is operators.and_:
                return all(matches(row, part) for part in expression.clauses)
            key = expression.left.name
            if (
                key == "category_id"
                and getattr(expression.right, "name", None) == "category_for_product"
            ):
                product_id = next(iter(expression.right.clauses)).value
                value = next(
                    row["category_id"]
                    for row in self.rows[Product.__tablename__]
                    if row["id"] == product_id
                )
            else:
                value = getattr(expression.right, "value", None)
            if expression.operator in (operators.eq, operators.is_, operators.is_not_distinct_from):
                return row[key] == value
            if expression.operator is operators.in_op:
                return row[key] in value
            raise AssertionError(f"Unsupported owner predicate: {expression.operator}")

        for expression in statement._where_criteria:
            rows = [row for row in rows if matches(row, expression)]
        if statement._limit_clause is not None:
            rows = rows[: statement._limit_clause.value]
        selected = [deepcopy(v) for v in rows]
        if self.after_query:
            self.after_query(table.name)
        return selected

    def execute(self, statement, *args, **kwargs):
        rows = self.selected(statement)
        fields = [v.name for v in statement.selected_columns]
        values = [{k: v[k] for k in fields} for v in rows]
        return SimpleNamespace(mappings=lambda: values)

    def scalars(self, statement, *args, **kwargs):
        return [SimpleNamespace(**v) for v in self.selected(statement)]

    def scalar(self, statement, *args, **kwargs):
        values = self.scalars(statement)
        return values[0] if values else None

    def flush(self, *args, **kwargs):
        raise AssertionError("owner reader must not flush")


@pytest.fixture
def work():
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*_args):
        raise AssertionError("pure owner tests must not connect")

    s = RawSession(engine)
    s.begin()
    tenant, category, product, project, actor = (uuid4() for _ in range(5))
    ctx = common.Context(tenant, actor, actor, category_id=category)
    scope = Scope(tenant_id=tenant, product_id=product, project_id=project)
    s.seed(Product, id=product, tenant_id=tenant, category_id=category, owner_id=actor)
    s.seed(Principal, id=actor, tenant_id=tenant, kind="human", active=True, access_epoch=1)
    grant = s.seed(
        Grant,
        id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        principal_id=actor,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        access_epoch=1,
    )
    value = SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=product,
        scope=scope,
        actor=actor,
        origin=SimpleNamespace(scope=scope, visibility="category"),
        grant=grant,
    )
    yield value
    s.close()
    engine.dispose()


def reader(work):
    return owner._Read(work.s, work.ctx, work.pid, work.origin)


def saved_group(work, *, operation="quality.capa.actions.complete", family="quality_issue"):
    now = datetime.now(UTC)
    subject = {"id": uuid4(), "revision": 6, "operation": operation, "visibility": "category"}
    receipt = work.s.seed(
        Receipt,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        command_id=uuid4(),
        actor_id=work.actor,
        requester_id=work.actor,
        operation=operation,
        subject_type=family,
        subject_id=subject["id"],
        subject_revision=6,
        visibility="category",
        run_id=None,
        request_digest=common.digest("original request"),
        intent_digest=common.digest("common intent"),
        result={"id": str(subject["id"]), "revision": 6, "status": "awaiting_verification"},
        created_at=now,
    )
    work.s.seed(
        RequestKey,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        actor_id=work.actor,
        receipt_id=receipt["id"],
        digest=receipt["request_digest"],
        key="original-key",
    )
    audit = work.s.seed(
        Audit,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        receipt_id=receipt["id"],
        actor_id=work.actor,
        operation=operation,
    )
    outbox = work.s.seed(
        Outbox,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        receipt_id=receipt["id"],
        actor_id=work.actor,
        type=common.EVENTS[operation],
        subject_id=subject["id"],
        subject_revision=6,
        correlation_id=receipt["command_id"],
        schema_version=1,
    )
    return subject, receipt, audit, outbox


def test_exact_saved_group_preserves_domain_and_common_provenance(work):
    subject, receipt, _audit, _event = saved_group(work)
    raw = reader(work)
    ref = raw.group(subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]])
    assert ref.id == receipt["id"] and ref.kind == "domain"
    assert raw.rows[0]["value"]["intent_digest"] == common.digest("common intent")
    raw.finish()
    assert all(q.get_execution_options()["autoflush"] is False for q in work.s.queries)
    assert all(q._limit_clause.value <= 2 for q in work.s.queries)
    assert not work.s.new


@pytest.mark.parametrize(
    "field",
    ["actor_id", "type", "subject_id", "subject_revision", "correlation_id", "schema_version"],
)
def test_wrong_atomic_outbox_never_proves_participant(work, field):
    subject, _receipt, _audit, event_row = saved_group(work)
    event_row[field] = 2 if field in {"subject_revision", "schema_version"} else uuid4()
    with pytest.raises(DomainError, match="完整保存组") as error:
        reader(work).group(
            subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]]
        )
    assert error.value.reason == "PARTICIPANT_ATOMIC_GROUP_MISMATCH"


@pytest.mark.parametrize(
    "change",
    [
        "missing_receipt",
        "duplicate_receipt",
        "missing_audit",
        "missing_outbox",
        "wrong_result_revision",
        "wrong_writer",
    ],
)
def test_missing_or_ambiguous_exact_atom_is_not_authority(work, change):
    subject, receipt, _audit, _event = saved_group(work)
    if change.startswith("missing_"):
        table = {"missing_receipt": Receipt, "missing_audit": Audit, "missing_outbox": Outbox}[
            change
        ]
        work.s.rows[table.__tablename__].clear()
    elif change == "duplicate_receipt":
        work.s.rows[Receipt.__tablename__].append(deepcopy(receipt))
    elif change == "wrong_result_revision":
        receipt["result"]["revision"] = True
    else:
        receipt["actor_id"] = uuid4()
    with pytest.raises(DomainError):
        reader(work).group(
            subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]]
        )


def test_alias_does_not_replace_original_request_association(work):
    subject, receipt, _audit, _event = saved_group(work)
    work.s.rows[RequestKey.__tablename__][0]["digest"] = common.digest("alias digest")
    with pytest.raises(DomainError) as error:
        reader(work).group(
            subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]]
        )
    assert error.value.reason == "PARTICIPANT_REQUEST_ASSOCIATION_MISSING"
    work.s.seed(
        RequestKey,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        actor_id=work.actor,
        receipt_id=receipt["id"],
        digest=receipt["request_digest"],
        key="real-original",
    )
    reader(work).group(subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]])


def test_private_raw_owner_cannot_be_read_with_peer_product_grant(work):
    work.s.seed(
        Artifact,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=uuid4(),
        visibility="private",
        revision=1,
    )
    with pytest.raises(DomainError) as error:
        reader(work).one(Artifact.__table__, revision=1)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_report_registrant_is_saved_participant_not_inferred_instrument_executor(work):
    subject, receipt, audit, outbox = saved_group(
        work, operation="evidence.artifact.register", family="artifact"
    )
    subject["revision"] = receipt["subject_revision"] = outbox["subject_revision"] = 1
    receipt["result"]["revision"] = 1
    content = "synthetic report, executor unknown"
    work.s.seed(
        Artifact,
        id=subject["id"],
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=work.actor,
        visibility="category",
        revision=1,
        original_id=None,
        status="active",
        content=content,
        content_hash=common.digest(content),
    )
    raw = reader(work)
    raw.report(
        SourceRef(id=subject["id"], revision=1, kind="artifact", position="line:1"), "measurement"
    )
    assert set(raw.people) == {work.actor}
    assert raw.people[work.actor][0] == {"measurement"}
    assert audit["actor_id"] == work.actor
    raw.finish()


def test_final_raw_reread_detects_owner_changed_after_later_io(work):
    subject, _receipt, audit, _event = saved_group(work)
    raw = reader(work)
    raw.group(subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]])
    audit["actor_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"


def test_session_nested_replacement_and_inactive_uow_are_rejected(work, monkeypatch):
    raw = reader(work)
    # SQLAlchemy begins a SAVEPOINT with its mandatory clean-session flush.
    # Permit only that fixture setup; production reader flush stays prohibited.
    with monkeypatch.context() as patch:
        patch.setattr(work.s, "flush", lambda: Session.flush(work.s))
        nested = work.s.begin_nested()
    with pytest.raises(DomainError):
        raw.finish()
    nested.rollback()
    work.s.rollback()
    with pytest.raises(DomainError):
        raw.finish()


def test_final_grant_query_clock_expiry_is_rechecked(work):
    raw = reader(work)

    def expire(table):
        if table == Grant.__tablename__:
            work.grant["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)

    work.s.after_query = expire
    with pytest.raises(DomainError) as error:
        raw.finish_clock()
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_missing_report_and_missing_independence_are_not_positive(work):
    raw = reader(work)
    raw.report(None, "measurement")
    assert raw.missing == {"REPORT_PARTICIPANT_OWNER_MISSING"}
    assert "qualified" not in owner.ParticipantRead.__dataclass_fields__
    assert (
        owner.ParticipantRead.__dataclass_fields__["current_evidence_authorized"].default is False
    )


def exact_source(work, monkeypatch, *, artifact_id=None):
    """Explicit no-connect source_for substitute; actual refs_from_exact still runs."""
    artifact_id = artifact_id or uuid4()
    line = "  synthetic executor report: raw=1.5000; retained whitespace  "
    artifact = SimpleNamespace(id=artifact_id, revision=3, content=f"header\n{line}\nfooter")
    calls = []

    def source_for(s, ctx, pid, identity, revision):
        assert s is work.s and ctx is work.ctx and pid == work.pid
        assert (identity, revision) == (artifact.id, artifact.revision)
        calls.append((identity, revision))
        return artifact

    monkeypatch.setattr(owner.evidence, "source_for", source_for)
    reference = {
        "artifact_id": str(artifact.id),
        "expected_revision": artifact.revision,
        "line": 2,
        "quote": "raw=1.5000",
    }
    normalized = SourceRef(
        id=artifact.id,
        revision=artifact.revision,
        kind="artifact",
        position=f"line:2;quote_sha256:{sha256(line.encode()).hexdigest()}",
    )
    return reference, normalized, artifact, calls


@pytest.mark.parametrize(
    "model",
    [
        VerificationRunVersion,
        FormalVerificationRequest,
        VerificationLaunchFact,
        ResultActionFact,
        MeasurementRecord,
        MeasurementImportCapture,
        QualityIssueVersion,
    ],
)
def test_saved_row_exact_references_use_actual_full_line_conversion_without_rewriting_material(
    work, monkeypatch, model
):
    exact, normalized, _artifact, calls = exact_source(work, monkeypatch)
    command = SourceRef(id=uuid4(), revision=1, kind="command", position="saved-command")
    original_sources = [deepcopy(exact), command.model_dump(mode="json")]
    row = work.s.seed(
        model,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        owner_id=work.actor,
        visibility="category",
        sources=deepcopy(original_sources),
        required_source_read_set=[
            {"artifact_id": exact["artifact_id"], "expected_revision": exact["expected_revision"]}
        ],
    )
    original_sha = common.digest(row)
    raw = reader(work)
    actual = raw.one(model.__table__, id=row["id"])
    assert actual["sources"] == original_sources == raw.rows[0]["value"]["sources"]
    assert common.digest(actual) == original_sha == common.digest(raw.rows[0]["value"])
    assert raw.refs == [normalized, command]
    assert calls == [(normalized.id, normalized.revision)]
    raw.person(work.actor, "original_test", actual["sources"])
    assert raw.people[work.actor] == ({"original_test"}, [normalized, command])
    assert len(calls) == 2
    raw.finish()
    assert row["sources"] == original_sources and not work.s.new


def test_person_accepts_both_typed_saved_contracts_and_keeps_exact_source_position(
    work, monkeypatch
):
    exact, normalized, _artifact, calls = exact_source(work, monkeypatch)
    domain = SourceRef(id=uuid4(), revision=7, kind="domain", position="action-receipt")
    raw = reader(work)
    raw.person(work.actor, "measurement", (DefinitionReference.model_validate(exact), domain))
    assert raw.people[work.actor] == ({"measurement"}, [normalized, domain])
    assert calls == [(normalized.id, 3)]
    assert raw.missing == set()
    assert (
        owner.ParticipantRead.__dataclass_fields__["same_uow_consumption_attested"].default is False
    )


def test_raw_quote_change_is_detected_even_when_derived_full_line_ref_is_unchanged(
    work, monkeypatch
):
    exact, normalized, _artifact, _calls = exact_source(work, monkeypatch)
    row = work.s.seed(
        VerificationRunVersion,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        owner_id=work.actor,
        visibility="category",
        sources=[deepcopy(exact)],
        required_source_read_set=[],
    )
    raw = reader(work)
    raw.one(VerificationRunVersion.__table__, id=row["id"])
    row["sources"][0]["quote"] = "retained whitespace"
    assert raw.source_refs(row["sources"]) == (normalized,)
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"
    assert raw.rows[0]["value"]["sources"] == [exact]


def test_exact_reference_still_requires_its_actual_line_and_current_source_access(
    work, monkeypatch
):
    exact, _normalized, _artifact, calls = exact_source(work, monkeypatch)
    wrong_line = {**exact, "line": 1}
    with pytest.raises(DomainError) as error:
        reader(work).person(work.actor, "original_test", (wrong_line,))
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"
    assert len(calls) == 1

    def withdrawn(*_args):
        raise DomainError("FORBIDDEN_SCOPE", "真实当前来源访问已撤回。", 403)

    monkeypatch.setattr(owner.evidence, "source_for", withdrawn)
    with pytest.raises(DomainError) as error:
        reader(work).source_refs((exact,))
    assert error.value.reason == "FORBIDDEN_SCOPE" and error.value.status == 403


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {"unknown": "cannot silently omit"},
        {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1},
        {"id": str(uuid4()), "revision": 1, "position": "line:1", "quote": "mixed schema"},
        {
            "artifact_id": str(uuid4()),
            "expected_revision": 1,
            "line": 1,
            "quote": "x",
            "id": str(uuid4()),
        },
    ],
)
def test_invalid_saved_source_shape_is_missing_and_never_silently_skipped(work, invalid):
    raw = reader(work)
    with pytest.raises(DomainError) as error:
        raw.person(work.actor, "original_test", (invalid,))
    assert error.value.reason == "PARTICIPANT_SOURCE_SHAPE_INVALID"
    assert not raw.people and not raw.refs


def test_missing_saved_sources_array_is_not_treated_as_empty_material(work):
    row = work.s.seed(
        VerificationRunVersion,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        owner_id=work.actor,
        visibility="category",
        sources=None,
        required_source_read_set=[],
    )
    with pytest.raises(DomainError) as error:
        reader(work).one(VerificationRunVersion.__table__, id=row["id"])
    assert error.value.reason == "PARTICIPANT_SOURCE_SHAPE_INVALID"


def test_report_exact_reference_retains_real_registration_participant(work, monkeypatch):
    subject, receipt, _audit, outbox = saved_group(
        work, operation="evidence.artifact.register", family="artifact"
    )
    exact, normalized, artifact, _calls = exact_source(work, monkeypatch, artifact_id=subject["id"])
    subject["revision"] = receipt["subject_revision"] = outbox["subject_revision"] = 3
    receipt["result"]["revision"] = 3
    work.s.seed(
        Artifact,
        id=artifact.id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=work.actor,
        visibility="category",
        revision=3,
        original_id=None,
        status="active",
        content=artifact.content,
        content_hash=common.digest(artifact.content),
    )
    raw = reader(work)
    raw.report(exact, "measurement")
    assert raw.people[work.actor] == ({"measurement"}, [normalized])
    assert raw.refs == [normalized]
    raw.finish()


def writer_shaped_run_history(work, monkeypatch):
    """Explicit saved-row substitutes shaped by the actual five writer semantics."""
    from pdos_next.domain.verification_launch import service as launch
    from pdos_next.domain.verification_launch.schemas import (
        ExecutionPlan,
        PlanPayload,
        StartPayload,
    )
    from pdos_next.domain.verification_results import service as results
    from pdos_next.domain.verification_results.schemas import (
        DispositionPayload,
        ImportPayload,
        ReviewPayload,
    )
    from pdos_next.schemas.verification.contracts import EventTime
    from pdos_next.schemas.verification.contracts import TestRun as SavedTestRun

    exact, source, _artifact, _calls = exact_source(work, monkeypatch)
    now = datetime.now(UTC)
    run_id, request_id, build_id, sample_id = (uuid4() for _ in range(4))
    origin_id, scheduled_id, executing_id, reported_id, disposed_id = (uuid4() for _ in range(5))
    execution_plan = {
        "window": {
            "start": (now - timedelta(minutes=5)).isoformat(),
            "finish": (now + timedelta(minutes=15)).isoformat(),
            "original_timezone": "UTC",
        },
        "executor_id": str(work.actor),
        "equipment": exact,
        "calibration": exact,
        "environment": "synthetic environment, no physical assertion",
        "conditions": "synthetic known conditions",
        "resource_fact_id": str(uuid4()),
        "expected_resource_fact_revision": 1,
    }
    execution_plan = ExecutionPlan.model_validate(execution_plan).model_dump(mode="json")
    build = {
        "id": str(build_id),
        "revision": 1,
        "product_id": str(work.pid),
        "project_id": str(work.scope.project_id),
        "engineering_configuration": {"id": str(uuid4()), "revision": 1},
        "manufacturing_configuration": {"id": str(uuid4()), "revision": 1},
    }
    sample = {
        "id": str(sample_id),
        "revision": 1,
        "build_id": str(build_id),
        "actual_configuration": {"id": str(uuid4()), "revision": 1},
        "cavity": None,
    }
    coverage = [{"sample_id": str(sample_id), "item_id": "item-a"}]
    event = EventTime(occurred_at=now, original_timezone="UTC", source=source)
    common_input = {"request_id": request_id, "run_id": run_id, "reason": "saved transition"}
    payloads = [
        PlanPayload(
            **common_input,
            expected_request_revision=3,
            coverage=coverage,
            execution_plan=execution_plan,
            sources=[exact],
        ),
        StartPayload(
            **common_input,
            expected_request_revision=4,
            expected_run_revision=1,
            expected_plan_sha256=common.digest(execution_plan),
            at=event,
            sources=[exact],
        ),
        ImportPayload(
            **common_input,
            expected_request_revision=5,
            expected_run_revision=2,
            final=True,
            at=event,
            actual_end=event,
            sources=[exact],
        ),
        ReviewPayload(
            **common_input,
            expected_request_revision=6,
            expected_run_revision=3,
            projection_id=uuid4(),
            expected_projection_revision=1,
            expected_basis_sha256="b" * 64,
            text="synthetic named review",
            at=event,
            sources=[exact],
        ),
        DispositionPayload(
            **common_input,
            expected_request_revision=6,
            expected_run_revision=4,
            projection_id=uuid4(),
            expected_projection_revision=1,
            expected_basis_sha256="b" * 64,
            text="synthetic named disposition",
            at=event,
            sources=[exact],
        ),
    ]
    formal_pairs = [
        ((origin_id, 3), (origin_id, 3)),
        ((scheduled_id, 4), (executing_id, 5)),
        ((executing_id, 5), (reported_id, 6)),
        ((reported_id, 6), (reported_id, 6)),
        ((reported_id, 6), (disposed_id, 7)),
    ]
    operations = [
        "test.run.plan",
        "test.run.start",
        "test.results.import",
        "test.run.review",
        "test.disposition.decide",
    ]
    statuses = ["planned", "running", "results_pending", "reviewed", "disposed"]
    actors = [work.actor, work.actor, work.actor, uuid4(), uuid4()]
    rows, facts, aggregate = [], [], {}
    for revision, (operation, payload, status, actor, (before, after)) in enumerate(
        zip(operations, payloads, statuses, actors, formal_pairs, strict=True), start=1
    ):
        module = launch if revision <= 2 else results
        atom = module.semantic(payload)
        domain_intent = module._intent(
            SimpleNamespace(requester_id=actor), SimpleNamespace(operation=operation), payload
        )
        aggregate = deepcopy(aggregate)
        if revision <= 2:
            aggregate.update(
                launch_input=deepcopy(atom),
                plan_binding={"actual_saved_binding": str(run_id)},
                resource_facts_revision="r" * 64,
                reservation={"owner_execution_id": str(run_id), "retained": True}
                if revision == 2
                else None,
            )
        else:
            aggregate["result_input"] = deepcopy(atom)
            aggregate["original_start_intent"] = rows[1]["intent_digest"]
        snapshot = SavedTestRun(
            id=run_id,
            revision=revision,
            scope=work.scope,
            request_id=request_id,
            request_revision=3,
            build=build,
            items=[{"id": "item-a", "feature": "synthetic feature", "sample_count": 1}],
            samples=[sample],
            coverage=coverage,
            status=status,
            result="pending" if revision <= 2 else "indeterminate",
            execution=None
            if revision == 1
            else {
                "executor_id": actor if revision == 2 else work.actor,
                "equipment": source,
                "calibration": source,
                "environment": execution_plan["environment"],
                "conditions": execution_plan["conditions"],
            },
        ).model_dump(mode="json")
        shared = {
            "tenant_id": work.ctx.tenant_id,
            "product_id": work.pid,
            "project_id": work.scope.project_id,
            "build_id": build_id,
            "request_id": request_id,
            "run_id": run_id,
            "visibility": "category",
            "operation": operation,
            "sources": deepcopy(atom["sources"]),
            "required_source_read_set": [
                {
                    "artifact_id": exact["artifact_id"],
                    "expected_revision": exact["expected_revision"],
                }
            ],
            "source_basis": {"actual_saved_security_epoch": revision},
            "authority_snapshot": {"subject_id": str(actor), "actual_fact_epoch": revision},
            "intent_digest": domain_intent,
        }
        row = work.s.seed(
            VerificationRunVersion,
            **shared,
            id=uuid4(),
            revision=revision,
            owner_id=work.actor,
            writer_id=actor,
            build_revision=1,
            request_version_id=origin_id,
            request_revision=3,
            previous_run_version_id=rows[-1]["id"] if rows else None,
            previous_revision=revision - 1 if rows else None,
            status=status,
            input_snapshot=deepcopy(aggregate),
            execution_plan=deepcopy(execution_plan),
            plan_sha256=common.digest(execution_plan),
            run_snapshot=snapshot,
            snapshot_sha256=common.digest(snapshot),
        )
        fact_fields = {
            **shared,
            "id": uuid4(),
            "revision": 1,
            "request_version_id": before[0],
            "request_revision": before[1],
            "next_request_version_id": after[0],
            "next_request_revision": after[1],
            "input_snapshot": deepcopy(atom),
        }
        if revision <= 2:
            kernel_event = {"operation": operation, "actual_saved_event": str(uuid4())}
            fact = work.s.seed(
                VerificationLaunchFact,
                **fact_fields,
                owner_id=actor,
                status=status,
                run_version_id=row["id"],
                run_revision=revision,
                kernel_event=kernel_event,
                snapshot_sha256=common.digest(kernel_event),
            )
        else:
            fact = work.s.seed(
                ResultActionFact,
                **fact_fields,
                owner_id=work.actor,
                actor_id=actor,
                status="recorded",
                run_version_id=rows[-1]["id"],
                run_revision=revision - 1,
                next_run_version_id=row["id"],
                next_run_revision=revision,
                event=event.model_dump(mode="json"),
            )
        _subject, receipt, audit, outbox = saved_group(work, operation=operation, family="test_run")
        receipt.update(
            actor_id=actor,
            requester_id=actor,
            subject_id=row["id"],
            subject_revision=revision,
            result={"id": str(row["id"]), "revision": revision, "status": status},
        )
        work.s.rows[RequestKey.__tablename__][-1]["actor_id"] = actor
        audit["actor_id"] = outbox["actor_id"] = actor
        outbox.update(subject_id=row["id"], subject_revision=revision)
        rows.append(row)
        facts.append(fact)
    return SimpleNamespace(rows=rows, facts=facts, actors=actors, run_id=run_id)


@pytest.mark.parametrize("revision", [1, 2, 3, 4, 5])
def test_real_writer_nested_atoms_and_complete_original_aggregate_are_both_retained(
    work, monkeypatch, revision
):
    history = writer_shaped_run_history(work, monkeypatch)
    saved = history.rows[revision - 1]
    before = deepcopy(saved)
    raw = reader(work)
    actual = raw.run(history.run_id, revision, "original_test")
    assert actual == before == saved
    assert saved["input_snapshot"] != history.facts[revision - 1]["input_snapshot"]
    assert set(raw.people) == set(history.actors[:revision])
    retained = next(
        v["value"]
        for v in raw.rows
        if v["table"] == VerificationRunVersion.__tablename__ and v["value"]["id"] == saved["id"]
    )
    assert retained["input_snapshot"] == before["input_snapshot"]
    assert common.digest(retained) == common.digest(before)
    receipts = [v["value"] for v in raw.rows if v["table"] == Receipt.__tablename__]
    assert all(v["intent_digest"] != saved["intent_digest"] for v in receipts)
    raw.finish()
    assert not work.s.new


@pytest.mark.parametrize(
    "revision,field,value",
    [
        (2, "owner_id", uuid4()),
        (3, "actor_id", uuid4()),
        (3, "owner_id", uuid4()),
        (2, "intent_digest", "f" * 64),
        (3, "intent_digest", "f" * 64),
        (2, "build_id", uuid4()),
        (3, "build_id", uuid4()),
        (3, "request_id", uuid4()),
        (3, "run_version_id", uuid4()),
        (3, "run_revision", 1),
        (3, "next_request_revision", 8),
        (2, "snapshot_sha256", "f" * 64),
        (3, "authority_snapshot", {"forged": "different saved authority"}),
        (3, "source_basis", {"actual_saved_security_epoch": -1}),
    ],
)
def test_real_writer_fact_actor_intent_scope_or_lineage_mismatch_is_rejected(
    work, monkeypatch, revision, field, value
):
    history = writer_shaped_run_history(work, monkeypatch)
    history.facts[revision - 1][field] = value
    with pytest.raises(DomainError) as error:
        reader(work).run(history.run_id, revision, "original_test")
    assert error.value.reason == "PARTICIPANT_RUN_FACT_MISMATCH"


@pytest.mark.parametrize("revision", [2, 3])
def test_whole_aggregate_cannot_be_substituted_for_the_actual_action_atom(
    work, monkeypatch, revision
):
    history = writer_shaped_run_history(work, monkeypatch)
    history.facts[revision - 1]["input_snapshot"] = deepcopy(
        history.rows[revision - 1]["input_snapshot"]
    )
    with pytest.raises(DomainError) as error:
        reader(work).run(history.run_id, revision, "original_test")
    assert error.value.reason == "PARTICIPANT_RUN_FACT_MISMATCH"


def test_result_input_cannot_be_matched_to_retained_launch_input(work, monkeypatch):
    history = writer_shaped_run_history(work, monkeypatch)
    row = history.rows[2]
    row["input_snapshot"]["result_input"] = deepcopy(row["input_snapshot"]["launch_input"])
    with pytest.raises(DomainError) as error:
        reader(work).run(history.run_id, 3, "original_test")
    assert error.value.reason == "PARTICIPANT_RUN_FACT_MISMATCH"


def test_final_raw_reread_does_not_project_away_retained_reservation_material(work, monkeypatch):
    history = writer_shaped_run_history(work, monkeypatch)
    raw = reader(work)
    raw.run(history.run_id, 5, "original_test")
    history.rows[-1]["input_snapshot"]["reservation"]["retained"] = False
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"


def test_fixed_run_origin_cannot_change_across_saved_result_lineage(work, monkeypatch):
    history = writer_shaped_run_history(work, monkeypatch)
    history.rows[2]["request_version_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        reader(work).run(history.run_id, 3, "original_test")
    assert error.value.reason == "PARTICIPANT_RUN_CHAIN_INVALID"


def parsed_original_report(work, *, parsed_revision=2):
    """Actual upload v1 + worker parse current-vN groups; no Artifact register.

    Explicit no-connect rows prove only the reader's canonical association shape.
    Real original bytes/scan safety remain the unchanged independent source owner.
    """
    original_id, artifact_id = uuid4(), uuid4()
    content = '{"raw_value":"11.0000","nature":"synthetic"}\n'
    original = work.s.seed(
        UploadedOriginal,
        id=original_id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=work.actor,
        visibility="category",
        revision=parsed_revision,
        status="parsed",
        content_hash=sha256(content.encode()).hexdigest(),
        byte_count=len(content.encode()),
        scan_status="clean",
    )
    artifact = work.s.seed(
        Artifact,
        id=artifact_id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=work.actor,
        visibility="category",
        revision=1,
        original_id=original_id,
        status="active",
        content=content,
        content_hash=common.digest(content),
    )
    groups = {}
    for operation, revision, status in (
        ("evidence.original.upload", 1, "uploaded"),
        ("evidence.original.parse", parsed_revision, "parsed"),
    ):
        _subject, receipt, audit, outbox = saved_group(
            work, operation=operation, family="uploaded_original"
        )
        receipt.update(
            subject_id=original_id,
            subject_revision=revision,
            result={"id": str(original_id), "revision": revision, "status": status},
        )
        outbox.update(subject_id=original_id, subject_revision=revision)
        groups[operation] = (receipt, audit, outbox)
    parsed_receipt = groups["evidence.original.parse"][0]
    # parse_uploaded really calls append_receipt only; it writes no RequestKey.
    work.s.rows[RequestKey.__tablename__] = [
        v for v in work.s.rows[RequestKey.__tablename__] if v["receipt_id"] != parsed_receipt["id"]
    ]
    ref = SourceRef(
        id=artifact_id,
        revision=1,
        kind="artifact",
        position=f"line:1;quote_sha256:{sha256(content.rstrip(chr(10)).encode()).hexdigest()}",
    )
    return SimpleNamespace(original=original, artifact=artifact, groups=groups, ref=ref)


@pytest.mark.parametrize("parsed_revision", [2, 3])
def test_uploaded_report_uses_upload_v1_and_exact_worker_parse_group_without_fake_keys(
    work, parsed_revision
):
    report = parsed_original_report(work, parsed_revision=parsed_revision)
    before = deepcopy(work.s.rows)
    raw = reader(work)
    raw.report(report.ref, "measurement")
    assert set(raw.people) == {work.actor}
    assert raw.people[work.actor][0] == {"measurement"}
    assert {v.position for v in raw.people[work.actor][1]} == {report.ref.position}
    actual_receipts = [v["value"] for v in raw.rows if v["table"] == Receipt.__tablename__]
    assert [(v["operation"], v["subject_revision"]) for v in actual_receipts] == [
        ("evidence.original.upload", 1),
        ("evidence.original.parse", parsed_revision),
    ]
    actual_keys = [v["value"] for v in raw.rows if v["table"] == RequestKey.__tablename__]
    assert len(actual_keys) == 1
    assert actual_keys[0]["receipt_id"] == report.groups["evidence.original.upload"][0]["id"]
    assert all(v["operation"] != "evidence.artifact.register" for v in actual_receipts)
    raw.finish()
    assert work.s.rows == before and not work.s.new
    assert (
        owner.ParticipantRead.__dataclass_fields__["current_evidence_authorized"].default is False
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_upload",
        "missing_upload_key",
        "missing_parse",
        "duplicate_parse",
        "wrong_parse_actor",
        "wrong_parse_revision",
        "wrong_parse_status",
        "missing_parse_audit",
        "missing_parse_outbox",
        "wrong_parse_event",
        "unparsed_original",
    ],
)
def test_uploaded_report_requires_both_actual_registration_and_derivation_groups(work, change):
    report = parsed_original_report(work)
    upload, _upload_audit, _upload_outbox = report.groups["evidence.original.upload"]
    parsed, parse_audit, parse_outbox = report.groups["evidence.original.parse"]
    if change == "missing_upload":
        work.s.rows[Receipt.__tablename__].remove(upload)
    elif change == "missing_upload_key":
        work.s.rows[RequestKey.__tablename__].clear()
    elif change == "missing_parse":
        work.s.rows[Receipt.__tablename__].remove(parsed)
    elif change == "duplicate_parse":
        work.s.rows[Receipt.__tablename__].append(deepcopy(parsed))
    elif change == "wrong_parse_actor":
        parsed["actor_id"] = uuid4()
    elif change == "wrong_parse_revision":
        parsed["subject_revision"] += 1
    elif change == "wrong_parse_status":
        parsed["result"]["status"] = "failed"
    elif change == "missing_parse_audit":
        work.s.rows[Audit.__tablename__].remove(parse_audit)
    elif change == "missing_parse_outbox":
        work.s.rows[Outbox.__tablename__].remove(parse_outbox)
    elif change == "wrong_parse_event":
        parse_outbox["type"] = common.EVENTS["evidence.artifact.register"]
    else:
        report.original["status"] = "uploaded"
    with pytest.raises(DomainError):
        reader(work).report(report.ref, "measurement")


def test_uploaded_report_never_falls_back_to_an_unrelated_artifact_register_receipt(work):
    report = parsed_original_report(work)
    work.s.rows[Receipt.__tablename__].clear()
    _subject, receipt, _audit, outbox = saved_group(
        work, operation="evidence.artifact.register", family="artifact"
    )
    receipt.update(
        subject_id=report.artifact["id"],
        subject_revision=1,
        result={"id": str(report.artifact["id"]), "revision": 1, "status": "active"},
    )
    outbox.update(subject_id=report.artifact["id"], subject_revision=1)
    with pytest.raises(DomainError):
        reader(work).report(report.ref, "measurement")


def test_actual_parse_group_changed_after_read_fails_final_reread(work):
    report = parsed_original_report(work)
    raw = reader(work)
    raw.report(report.ref, "measurement")
    report.groups["evidence.original.parse"][1]["actor_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"
