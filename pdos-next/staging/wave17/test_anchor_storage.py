"""Synthetic storage rows and explicit SQL returns; no DB or actual owner gates."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import anchor_storage as storage
import pytest
import test_anchor_lineage as pure
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_followup.schemas import ActionsCompletePayload
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.service import Context, digest
from quality_issues.helpers import uid
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from test_paired_storage import SelectMemory


@pytest.fixture
def work(monkeypatch):
    sample = pure.origin_fixture()
    origin = sample.origin
    original = origin.issue.model_copy(
        update={
            "history": (
                *origin.issue.history[:-1],
                origin.issue.history[-1].model_copy(update={"note": storage.OPERATION}),
            ),
        }
    )
    prior = original.model_dump(mode="json")
    prior.update(revision=original.revision - 1, status="actioning", history=prior["history"][:-1])
    for action in prior["capa"]["actions"]:
        action["completion"] = None
    previous = storage.Issue.model_validate(prior)
    payload = ActionsCompletePayload(
        issue_id=origin.issue_id,
        expected_issue_revision=previous.revision,
        completions=tuple(
            action.completion.model_dump(mode="json") for action in original.capa.actions
        ),
    )
    semantic = storage.followup.semantic(payload)
    proof_id = uid("origin-proof")
    basis = {
        "artifact_sources": [value.model_dump(mode="json") for value in origin.source_basis],
        "result_proofs": [digest("synthetic original failure declaration")],
        "followup_basis": {"issue_revision": previous.revision, "nature": "synthetic"},
        "completion_assessments": [{"synthetic_structural_only": True}],
        "shared_proof": {"id": str(proof_id), "tier": "T1"},
        "completion_observations": [{"actual_source_metadata": "unchanged synthetic input"}],
    }
    row_base = dict(
        tenant_id=origin.scope.tenant_id,
        product_id=origin.scope.product_id,
        project_id=origin.scope.project_id,
        issue_id=origin.issue_id,
        owner_id=origin.owner_id,
        writer_id=origin.writer_id,
        visibility="product",
        purpose=origin.purpose,
        created_at=origin.created_at,
        input_snapshot=semantic,
        authority_snapshot={"subject_id": str(origin.writer_id), "synthetic": True},
        policy_snapshot={"synthetic": True, "version": "original-policy"},
        sources=[value.model_dump(mode="json") for value in origin.sources],
        required_source_read_set=[
            value.model_dump(mode="json") for value in origin.required_source_read_set
        ],
        source_basis=basis,
        reason="Synthetic storage fixture",
    )
    before = QualityIssueVersion(
        **row_base,
        id=uid("before-origin"),
        revision=previous.revision,
        previous_issue_version_id=uid("predecessor-before"),
        previous_revision=previous.revision - 1,
        issue_snapshot=previous.model_dump(mode="json"),
        snapshot_sha256=digest(previous.model_dump(mode="json")),
        status=previous.status,
        operation="quality.issue.root_cause.decide",
        intent_digest=digest("older intent"),
    )
    row = QualityIssueVersion(
        **deepcopy(row_base),
        id=origin.ref.id,
        revision=original.revision,
        previous_issue_version_id=before.id,
        previous_revision=before.revision,
        issue_snapshot=original.model_dump(mode="json"),
        snapshot_sha256=digest(original.model_dump(mode="json")),
        status=original.status,
        operation=storage.OPERATION,
        intent_digest=digest(
            {
                "operation": storage.OPERATION,
                "actor": str(origin.writer_id),
                "product": str(origin.scope.product_id),
                "payload": semantic,
            }
        ),
    )
    pointer = QualityIssueCurrent(
        id=uid("origin-current"),
        tenant_id=row.tenant_id,
        product_id=row.product_id,
        project_id=row.project_id,
        issue_id=row.issue_id,
        issue_version_id=row.id,
        issue_revision=row.revision,
        epoch=3,
        created_at=row.created_at,
    )
    receipt = Receipt(
        id=uid("origin-receipt"),
        tenant_id=row.tenant_id,
        product_id=row.product_id,
        command_id=original.history[-1].command_id,
        actor_id=row.writer_id,
        requester_id=row.writer_id,
        operation=storage.OPERATION,
        subject_type="quality_issue",
        subject_id=row.id,
        subject_revision=row.revision,
        visibility=row.visibility,
        run_id=None,
        result={"id": str(row.id), "revision": row.revision, "status": row.status},
        request_digest=digest("actual original request digest; no token reconstruction"),
        intent_digest=digest(
            {
                "operation": storage.OPERATION,
                "category": None,
                "product": row.product_id,
                "payload": semantic,
                "named_actor": row.writer_id,
                "source_revision": None,
                "private_owner": row.writer_id,
            }
        ),
        created_at=row.created_at + timedelta(seconds=1),
    )
    audit = Audit(
        id=uid("origin-audit"),
        tenant_id=row.tenant_id,
        receipt_id=receipt.id,
        actor_id=row.writer_id,
        operation=storage.OPERATION,
    )
    outbox = Outbox(
        id=uid("origin-outbox"),
        tenant_id=row.tenant_id,
        receipt_id=receipt.id,
        actor_id=row.writer_id,
        type=storage.EVENT,
        subject_id=row.id,
        subject_revision=row.revision,
        schema_version=1,
        correlation_id=receipt.command_id,
    )
    reads = row.required_source_read_set
    snapshot = {
        "before": {str(row.issue_id): previous.model_dump(mode="json")},
        "after": {str(row.issue_id): storage.followup._preview_issue(original, previous)},
        "read_basis": {
            "authority": deepcopy(row.authority_snapshot),
            "policy": deepcopy(row.policy_snapshot),
            "source_basis": {
                k: deepcopy(v)
                for k, v in basis.items()
                if k not in {"shared_proof", "completion_observations"}
            },
            "read_set": deepcopy(reads),
        },
    }
    proof = Confirmation(
        id=proof_id,
        tenant_id=row.tenant_id,
        product_id=row.product_id,
        actor_id=row.writer_id,
        subject_id=row.product_id,
        operation=storage.OPERATION,
        revision=42,
        consumed=True,
        token_hash=digest("historical-secret-not-read"),
        created_at=row.created_at - timedelta(minutes=1),
        expires_at=row.created_at + timedelta(minutes=10),
        payload_digest=digest(
            {
                "tenant": row.tenant_id,
                "actor": row.writer_id,
                "requester": row.writer_id,
                "operation": storage.OPERATION,
                "category": None,
                "product": row.product_id,
                "expected_revision": 42,
                "read_set": sorted(
                    reads, key=lambda value: (value["artifact_id"], value["expected_revision"])
                ),
                "payload": semantic,
            }
        ),
        snapshot=snapshot,
    )
    key = RequestKey(
        id=uid("original-key"),
        tenant_id=row.tenant_id,
        actor_id=row.writer_id,
        receipt_id=receipt.id,
        digest=receipt.request_digest,
        key="original-key",
    )
    caller = uid("actual-shared-reader")
    principal = Principal(id=caller, tenant_id=row.tenant_id, kind="human", active=True)
    writer = Principal(id=row.writer_id, tenant_id=row.tenant_id, kind="human", active=False)
    grant = Grant(
        id=uid("caller-grant"),
        tenant_id=row.tenant_id,
        product_id=row.product_id,
        principal_id=caller,
        expires_at=row.created_at + timedelta(days=2),
        can_write=False,
    )
    product = Product(id=row.product_id, tenant_id=row.tenant_id, revision=900)
    project = Project(
        id=row.project_id,
        tenant_id=row.tenant_id,
        product_id=row.product_id,
        owner_id=row.owner_id,
        visibility="product",
        scope="Original actual project scope",
        status="active",
        revision=1,
    )
    memory = SelectMemory(
        [
            before,
            row,
            pointer,
            receipt,
            audit,
            outbox,
            proof,
            key,
            principal,
            writer,
            grant,
            product,
            project,
        ]
    )
    bind = create_engine("sqlite://")
    event.listen(
        bind, "do_connect", lambda *_args: pytest.fail("Owned pure must not connect to a database")
    )
    session = Session(bind=bind)
    session.begin()
    monkeypatch.setattr(session, "scalars", memory.scalars)
    clock = SimpleNamespace(at=row.created_at + timedelta(hours=1))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.at if tz is not None else clock.at.replace(tzinfo=None)

    monkeypatch.setattr(storage.guards, "datetime", Clock)
    value = SimpleNamespace(
        s=session,
        memory=memory,
        clock=clock,
        ctx=Context(row.tenant_id, caller, caller),
        pid=row.product_id,
        logical=row.issue_id,
        row=row,
        before=before,
        pointer=pointer,
        receipt=receipt,
        audit=audit,
        outbox=outbox,
        proof=proof,
        key=key,
        grant=grant,
        principal=principal,
        project=project,
        ref=storage.a.VersionRef(
            id=row.id, revision=row.revision, snapshot_sha256=row.snapshot_sha256
        ),
    )
    yield value
    session.close()


def read(work, **replace):
    return storage.read_origin_descriptor(
        work.s, replace.get("ctx", work.ctx), work.pid, work.logical, replace.get("ref", work.ref)
    )


def seal(work):
    work.row.snapshot_sha256 = digest(work.row.issue_snapshot)
    work.ref = storage.a.VersionRef(
        id=work.row.id, revision=work.row.revision, snapshot_sha256=work.row.snapshot_sha256
    )


def successor(work):
    saved = deepcopy(work.row.issue_snapshot)
    saved["revision"] += 1
    next_row = QualityIssueVersion(
        id=uid("explicit-descendant"),
        tenant_id=work.row.tenant_id,
        product_id=work.pid,
        project_id=work.row.project_id,
        issue_id=work.logical,
        revision=saved["revision"],
        previous_issue_version_id=work.row.id,
        previous_revision=work.row.revision,
        owner_id=work.row.owner_id,
        writer_id=work.row.writer_id,
        visibility=work.row.visibility,
        purpose=work.row.purpose,
        status=saved["status"],
        operation="future.owner.must.prove",
        issue_snapshot=saved,
        snapshot_sha256=digest(saved),
        created_at=work.row.created_at + timedelta(minutes=1),
    )
    work.memory.add(next_row)
    work.pointer.issue_version_id, work.pointer.issue_revision = next_row.id, next_row.revision
    work.pointer.epoch += 1
    return next_row


def test_real_storage_shape_preserves_original_and_never_attests(work):
    result = read(work)
    assert result.origin.ref == work.ref and result.origin.previous_ref.id == work.before.id
    assert result.origin.issue.model_dump(mode="json") == work.row.issue_snapshot
    assert result.origin.persisted_source_basis == work.row.source_basis
    assert result.origin.input_snapshot == work.row.input_snapshot
    assert result.origin.authority_snapshot == work.row.authority_snapshot
    assert result.origin.policy_snapshot == work.row.policy_snapshot
    assert result.current.ref == work.ref and result.needs_lineage_owner is False
    assert (
        result.current_evidence_authorized
        is result.source_bytes_verified
        is result.original_failures_verified
        is False
    )
    assert result.completion_group.same_uow_consumption_attested is False
    assert (
        result.completion_group.domain_intent_sha256 != result.completion_group.common_intent_sha256
    )
    assert "original_failure_bytes_owner" in result.missing_owners
    assert (
        work.proof.expires_at < work.clock.at
    )  # Original valid consumption may now be historical.
    assert result.completion_group.proof_revision == 42  # Not current Product revision 900.


def test_current_descendant_retains_original_full_history_and_requires_owner(work):
    current = successor(work)
    result = read(work)
    assert result.origin.ref == work.ref and result.current.ref.id == current.id
    assert (
        result.origin.issue.history
        and result.origin.issue.model_dump(mode="json") == work.row.issue_snapshot
    )
    assert result.needs_lineage_owner and "limited_issue_lineage_owner" in result.missing_owners
    assert result.current_evidence_authorized is False
    with pytest.raises(DomainError, match="原锚"):
        read(work, ref=result.current.ref)


@pytest.mark.parametrize(
    "field,value", [("id", uid("unknown-origin")), ("revision", 8), ("snapshot_sha256", "0" * 64)]
)
def test_explicit_ref_must_match_actual_origin(work, field, value):
    raw = work.ref.model_dump(mode="json")
    raw[field] = str(value) if field == "id" else value
    with pytest.raises(DomainError):
        read(work, ref=raw)


def test_product_grant_cannot_read_private_origin(work):
    work.row.visibility = work.before.visibility = "private"
    for row in (work.row, work.before):
        row.issue_snapshot["audience"] = [f"private:{row.owner_id}"]
        row.snapshot_sha256 = digest(row.issue_snapshot)
    seal(work)
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_product_and_shared_issue_cannot_bypass_private_project(work):
    work.project.visibility = "private"
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("change", ["scope", "owner", "private", "foreign"])
def test_project_scope_and_acl_refreshed_after_all_group_io(work, change):
    count = 0

    def during_group(model, _statement):
        nonlocal count
        if model is Audit:
            count += 1
            if count == 1:
                if change == "scope":
                    work.project.scope = "Changed actual project scope"
                elif change == "owner":
                    work.project.owner_id = uid("different-project-owner")
                elif change == "private":
                    work.project.visibility = "private"
                else:
                    work.project.product_id = uid("foreign-product")

    work.memory.hook = during_group
    with pytest.raises(DomainError):
        read(work)


@pytest.mark.parametrize(
    "change",
    [
        "no_root",
        "not_complete",
        "merged",
        "needs_recheck",
        "history",
        "failure_requirement",
        "root_rewritten",
    ],
)
def test_resealed_snapshot_cannot_forge_completion_origin(work, change):
    raw = work.row.issue_snapshot
    if change == "no_root":
        raw["root_cause"] = None
    elif change == "not_complete":
        raw["capa"]["actions"][0]["completion"] = None
    elif change == "merged":
        raw["merged_into"] = str(uid("merged-target"))
    elif change == "needs_recheck":
        raw["needs_recheck"] = True
    elif change == "history":
        raw["history"] = raw["history"][1:]
    elif change == "failure_requirement":
        raw["capa"]["requirement"]["required_failure_ids"] = ["wrong-failure"]
    else:
        raw["root_cause"]["text"] = "silently rewritten original cause"
    seal(work)
    with pytest.raises(DomainError):
        read(work)


@pytest.mark.parametrize("change", ["missing", "gap", "foreign", "owner", "purpose", "unknown"])
def test_predecessor_cas_and_scope_are_real(work, change):
    if change == "missing":
        work.row.previous_issue_version_id = None
    elif change == "gap":
        work.row.previous_revision -= 1
    elif change == "foreign":
        work.before.project_id = uid("foreign-project")
    elif change == "owner":
        work.before.owner_id = uid("other-owner")
    elif change == "purpose":
        work.before.purpose = "Another exact purpose"
    else:
        work.row.previous_issue_version_id = uid("unknown-before")
    with pytest.raises(DomainError):
        read(work)


@pytest.mark.parametrize(
    "change",
    ["basis_missing", "source_hash", "private_expansion", "root_source_omitted", "missing_reads"],
)
def test_original_source_declarations_are_complete_but_not_authorization(work, change):
    if change == "basis_missing":
        work.row.source_basis.pop("artifact_sources")
    elif change == "source_hash":
        work.row.source_basis["artifact_sources"][0]["hash"] = "invalid"
    elif change == "private_expansion":
        work.row.source_basis["artifact_sources"][0]["visibility"] = "private"
    elif change == "root_source_omitted":
        wanted = work.row.issue_snapshot["root_cause"]["sources"][0]
        work.row.sources = [v for v in work.row.sources if v != wanted]
    else:
        work.row.required_source_read_set = work.row.required_source_read_set[1:]
    with pytest.raises(DomainError):
        read(work)


@pytest.mark.parametrize("model", [Receipt, Audit, Outbox, Confirmation, RequestKey])
def test_exact_original_common_group_is_required(work, model):
    work.memory.drop(model)
    with pytest.raises(DomainError):
        read(work)


@pytest.mark.parametrize(
    "change",
    [
        "domain_as_common",
        "wrong_writer",
        "wrong_event",
        "result_bool",
        "no_consumed",
        "late_proof",
        "material",
        "view",
        "secret",
    ],
)
def test_original_group_wrong_binding_does_not_pass(work, change):
    if change == "domain_as_common":
        work.receipt.intent_digest = work.row.intent_digest
    elif change == "wrong_writer":
        work.receipt.actor_id = work.ctx.actor_id
    elif change == "wrong_event":
        work.outbox.type = "wrong-event"
    elif change == "result_bool":
        work.receipt.result["revision"] = True
    elif change == "no_consumed":
        work.proof.consumed = False
    elif change == "late_proof":
        work.proof.expires_at = work.row.created_at
    elif change == "material":
        work.proof.payload_digest = "0" * 64
    elif change == "view":
        work.proof.snapshot["before"] = {}
    else:
        work.row.input_snapshot["confirmation_token"] = "not-allowed"
    with pytest.raises(DomainError):
        read(work)


def test_alias_key_does_not_replace_original_request_digest(work):
    work.memory.add(
        RequestKey(
            id=uid("alias-key"),
            tenant_id=work.row.tenant_id,
            actor_id=work.row.writer_id,
            receipt_id=work.receipt.id,
            digest=digest("different alias digest"),
            key="alias",
        )
    )
    assert read(work).completion_group.original_request_digest == work.receipt.request_digest
    work.key.digest = digest("original no longer matches")
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "ORIGIN_REQUEST_KEY_MISSING"


def test_current_epoch_drift_in_later_group_io_rejected(work):
    count = 0

    def during_group(model, _statement):
        nonlocal count
        if model is Audit:
            count += 1
            if count == 1:
                work.pointer.epoch += 1

    work.memory.hook = during_group
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "SOURCE_STALE"


def test_current_pointer_replacement_without_epoch_is_not_ignored(work):
    count = 0

    def during_group(model, _statement):
        nonlocal count
        if model is Audit:
            count += 1
            if count == 1:
                work.pointer.id = uid("replaced-current-identity")

    work.memory.hook = during_group
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "SOURCE_STALE"


def test_successful_nested_uow_reads_same_explicit_origin(work):
    with work.s.begin_nested():
        with work.s.begin_nested():
            assert read(work).origin.ref == work.ref


def test_grant_expires_during_final_current_io_rejected(work):
    count = 0
    work.grant.expires_at = work.clock.at + timedelta(seconds=1)

    def during_current(model, _statement):
        nonlocal count
        if model is QualityIssueCurrent:
            count += 1
            if count == 3:
                work.clock.at = work.grant.expires_at

    work.memory.hook = during_current
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_activity_and_transaction_change_rejected(work):
    work.s.rollback()
    with pytest.raises(DomainError):
        read(work)


def test_failed_nested_transaction_is_rejected(work):
    nested = work.s.begin_nested()
    # Actual rollback leaves the object inactive until the context exits.
    nested.rollback()
    assert nested.is_active is False
    # No stale explicit nested object is accepted as the active chain.
    work.s._transaction = nested
    with pytest.raises(DomainError):
        read(work)
    work.s._transaction = nested.parent


def test_late_uow_replacement_or_context_change_rejected(work, monkeypatch):
    real = storage.guards._same_uow

    def changed(s, captured, ctx, caller):
        s.rollback()
        s.begin()
        return real(s, captured, ctx, caller)

    monkeypatch.setattr(storage.guards, "_same_uow", changed)
    with pytest.raises(DomainError) as error:
        read(work)
    assert error.value.code == "FACT_CALLER_UOW_CHANGED"


def test_queries_are_bounded_scoped_and_do_not_autoflush(work):
    flushes = []
    event.listen(work.s, "before_flush", lambda *_args: flushes.append(True))
    work.s.add(Product(id=uid("unflushed"), tenant_id=work.row.tenant_id))
    read(work)
    assert not flushes
    for query in work.memory.queries:
        assert query._limit_clause.value in {1, 2}
        assert query.get_execution_options()["autoflush"] is False
        assert query.get_execution_options()["populate_existing"] is True
        compiled = str(query.compile(dialect=postgresql.dialect()))
        assert "WHERE" in compiled and compiled.index("WHERE") < compiled.index("LIMIT")
        assert "tenant_id" in compiled
    origin_queries = [
        v for v in work.memory.queries if v.column_descriptions[0]["entity"] is QualityIssueVersion
    ]
    for query in origin_queries:
        keys = {v.left.key for v in query._where_criteria}
        assert {"tenant_id", "product_id", "issue_id", "id", "revision"} <= keys


def test_reader_never_builds_anchor_or_calls_actual_owner(work, monkeypatch):
    monkeypatch.setattr(
        storage.a,
        "build_anchor",
        lambda *_args, **_kw: pytest.fail("No actual source/failure owners configured"),
    )
    assert read(work).current_evidence_authorized is False
