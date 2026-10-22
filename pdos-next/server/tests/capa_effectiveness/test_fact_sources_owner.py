"""Actual source closure code under no-connect UOW and synthetic byte ports.

This tests source/private/hash/time guards, not installed PG enforcement, trusted
scanner qualification, observation completeness or a successful seven-owner gate.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_effectiveness.test_participants_owner import work as work

from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import anchor as a
from pdos_next.domain.capa_effectiveness import fact_sources_owner as owner
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Receipt
from pdos_next.schemas.verification.contracts import SourceRef


def native(work, *, private=False, identity=None, content="actual synthetic source line"):
    identity = identity or uuid4()
    source = work.s.seed(
        Artifact,
        id=identity,
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        product_id=work.pid,
        owner_id=work.actor,
        visibility="private" if private else "category",
        revision=1,
        original_id=None,
        status="active",
        content=content,
        content_hash=common.digest(content),
    )
    receipt = work.s.seed(
        Receipt,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        actor_id=work.actor,
        requester_id=work.actor,
        run_id=None,
        operation="evidence.artifact.register",
        subject_type="artifact",
        subject_id=identity,
        subject_revision=1,
        visibility=source["visibility"],
        result={"id": str(identity), "revision": 1, "status": "active"},
    )
    ref = SourceRef(
        id=identity,
        revision=1,
        kind="artifact",
        position=f"line:1;quote_sha256:{sha256(content.splitlines()[0].encode()).hexdigest()}",
    )
    return source, receipt, ref, a.SourceRead(artifact_id=identity, expected_revision=1)


def project(work, *, private=False, owner_id=None):
    return work.s.seed(
        Project,
        id=work.scope.project_id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        owner_id=owner_id or work.actor,
        visibility="private" if private else "category",
        status="active",
        scope="product",
    )


def closure(work, refs, reads, **kwargs):
    return owner.read_source_closure(
        work.s,
        work.ctx,
        work.pid,
        scope=work.scope,
        owner_id=work.actor,
        visibility=kwargs.pop("visibility", "category"),
        sources=refs,
        reads=reads,
        **kwargs,
    )


def test_native_actual_line_registration_and_sparse_raw_basis(work):
    project(work)
    row, receipt, ref, read = native(work)
    result = closure(work, [ref], [read])
    assert result.sources == (ref,) and result.required_source_read_set == (read,)
    assert result.source_basis[0]["registration"]["receipt_id"] == str(receipt["id"])
    assert result.source_basis[0]["source_kind"] == "registered_native_text"
    assert "original" not in result.source_basis[0]
    assert result.byte_material[0]["content_hash"] == row["content_hash"]
    assert result.valid_until is None
    assert work.grant["expires_at"] in result.time_constraints
    assert result.current_evidence_authorized is False
    assert result.same_uow_consumption_attested is False
    assert "qualified" not in owner.FactSourcesRead.__dataclass_fields__
    assert not work.s.new


@pytest.mark.parametrize(
    "change",
    [
        "withdrawn",
        "wrong_revision",
        "wrong_content_hash",
        "wrong_receipt",
        "missing_receipt",
        "wrong_line",
    ],
)
def test_actual_source_integrity_and_locator_failure_never_pass(work, change):
    project(work)
    row, receipt, ref, read = native(work)
    if change == "withdrawn":
        row["status"] = "withdrawn"
    elif change == "wrong_revision":
        row["revision"] = 2
    elif change == "wrong_content_hash":
        row["content_hash"] = "0" * 64
    elif change == "wrong_receipt":
        receipt["requester_id"] = uuid4()
    elif change == "missing_receipt":
        work.s.rows[Receipt.__tablename__].clear()
    else:
        ref = ref.model_copy(update={"position": "line:1;quote_sha256:" + "0" * 64})
    with pytest.raises(DomainError):
        closure(work, [ref], [read])


def test_current_product_grant_does_not_expand_private_project(work):
    project(work, private=True, owner_id=uuid4())
    _row, _receipt, ref, read = native(work)
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read])
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_private_source_never_expands_product_fact_audience(work):
    project(work)
    _row, _receipt, ref, read = native(work, private=True)
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read])
    assert error.value.reason == "FORBIDDEN_SCOPE"
    assert (
        closure(work, [ref], [read], visibility="private").source_basis[0]["visibility"]
        == "private"
    )


def test_complete_union_accepts_more_than_twenty_without_truncation(work):
    project(work)
    selected = [native(work, content=f"synthetic line {i}") for i in range(21)]
    refs, reads = [v[2] for v in selected], [v[3] for v in selected]
    assert len(closure(work, refs[:20], reads[:20]).required_source_read_set) == 20
    result = closure(work, refs, reads)
    assert set(result.required_source_read_set) == set(reads)
    assert len(result.sources) == 21


def test_conflicting_revision_or_omitted_actual_artifact_read_is_rejected(work):
    project(work)
    _row, _receipt, ref, read = native(work)
    with pytest.raises(DomainError):
        closure(work, [ref], [read, read.model_copy(update={"expected_revision": 2})])
    _row2, _receipt2, _ref2, read2 = native(work)
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read2])
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_domain_reference_remains_explicit_owner_missing(work):
    project(work)
    _row, _receipt, ref, read = native(work)
    domain = SourceRef(id=uuid4(), revision=1, kind="domain", position="action-receipt")
    result = closure(work, [ref, domain], [read])
    assert result.missing == ("DOMAIN_SOURCE_OWNER_REQUIRED",)
    assert not result.current_evidence_authorized


def test_source_changes_during_later_project_read_are_rejected(work):
    project(work)
    row, _receipt, ref, read = native(work)
    calls = 0

    def after(table):
        nonlocal calls
        if table == Project.__tablename__:
            calls += 1
            if calls == 2:
                row["status"] = "withdrawn"

    work.s.after_query = after
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read])
    assert error.value.reason == "SOURCE_UNAVAILABLE"


def test_current_project_changes_at_last_query_do_not_reuse_old_descriptor(work):
    value = project(work)
    _row, _receipt, ref, read = native(work)
    calls = 0

    def after(table):
        nonlocal calls
        if table == Project.__tablename__:
            calls += 1
            if calls == 1:
                value["owner_id"] = uuid4()
                value["visibility"] = "private"

    work.s.after_query = after
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read])
    assert error.value.reason == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("boundary", ["expired", "naive", "future"])
def test_earliest_actual_boundary_controls_post_io_clock(work, boundary):
    project(work)
    _row, _receipt, ref, read = native(work)
    time = datetime.now(UTC) + timedelta(seconds=10)
    if boundary == "expired":
        time = datetime.now(UTC) - timedelta(seconds=1)
    elif boundary == "naive":
        time = time.replace(tzinfo=None)
    if boundary == "future":
        result = closure(work, [ref], [read], boundaries=(time,))
        assert result.valid_until is None and time in result.time_constraints
    else:
        with pytest.raises(DomainError):
            closure(work, [ref], [read], boundaries=(time,))


def uploaded(work, monkeypatch, *, content=b"synthetic uploaded report bytes"):
    project(work)
    row, _receipt, ref, read = native(work)
    original = SimpleNamespace(
        id=uuid4(),
        product_id=work.pid,
        category_id=work.ctx.category_id,
        status="parsed",
        visibility="category",
    )
    row["original_id"] = original.id
    expected = SimpleNamespace(size_bytes=len(content), content_sha256=sha256(content).hexdigest())
    epoch = {"value": 1}
    store = SimpleNamespace(content=content, calls=0)
    work.s.get_bind()._pdos_results_store = store
    # Controlled synthetic byte/safety ports explicitly stand in for scanner and
    # filesystem gates. Real source-for/line/hash/current checks stay exercised.
    monkeypatch.setattr("pdos_next.originals.require_original", lambda *_a, **_k: original)
    monkeypatch.setattr(
        "pdos_next.original_security.require_safe", lambda *_a, **_k: (epoch["value"], None)
    )
    monkeypatch.setattr(owner, "require_original", lambda *_a, **_k: original)
    monkeypatch.setattr(owner, "require_safe", lambda *_a, **_k: (epoch["value"], None))
    monkeypatch.setattr(owner, "object_reference", lambda _original: expected)
    actual_basis = owner.evidence.source_basis

    def basis(s, ctx, pid, reads):
        assert len(reads) == 1
        # This test's uploaded source requires the same scoped active row; the
        # sparse security basis is a named synthetic substitute, not a clean scan.
        source = common.source_for(s, ctx, pid, ref.id, ref.revision)
        return [
            {
                "id": str(source.id),
                "revision": 1,
                "hash": source.content_hash,
                "status": source.status,
                "owner_id": str(work.actor),
                "visibility": source.visibility,
                "source_kind": "uploaded_original",
                "original": {
                    "id": str(original.id),
                    "epoch": epoch["value"],
                    "source_state": "active",
                    "disposition": "active",
                },
            }
        ], False

    monkeypatch.setattr(owner.evidence, "source_basis", basis)

    def bytes_port(actual_store, reference, tenant, product, category):
        assert category == work.ctx.category_id
        assert actual_store is store and reference is expected
        assert (tenant, product) == (work.ctx.tenant_id, work.pid)
        store.calls += 1
        return store.content

    monkeypatch.setattr(owner, "read_registered_bytes", bytes_port)
    return row, ref, read, original, epoch, store, actual_basis


def test_uploaded_source_reads_actual_bounded_bytes_and_returns_only_digest(work, monkeypatch):
    _row, ref, read, _original, _epoch, store, _ = uploaded(work, monkeypatch)
    result = closure(work, [ref], [read])
    assert store.calls == 1
    assert result.byte_material[0]["sha256"] == sha256(store.content).hexdigest()
    assert "content" not in result.byte_material[0]
    assert result.byte_material[0]["security_epoch"] == 1
    assert not result.current_evidence_authorized


@pytest.mark.parametrize(
    "failure",
    ["missing_store", "wrong_bytes", "security_epoch", "runtime_store", "replacement_uow"],
)
def test_original_byte_io_never_skips_current_security_or_uow(work, monkeypatch, failure):
    _row, ref, read, _original, epoch, store, _ = uploaded(work, monkeypatch)
    if failure == "missing_store":
        del work.s.get_bind()._pdos_results_store
    elif failure == "wrong_bytes":
        store.content = b"different bytes"
    else:
        actual = owner.read_registered_bytes

        def changed(*args):
            value = actual(*args)
            if failure == "security_epoch":
                epoch["value"] += 2  # withdrawn/restore ABA cannot keep epoch.
            elif failure == "runtime_store":
                work.s.get_bind()._pdos_results_store = object()
            else:
                work.s.rollback()
                work.s.begin()
            return value

        monkeypatch.setattr(owner, "read_registered_bytes", changed)
    with pytest.raises(DomainError):
        closure(work, [ref], [read])


def test_final_original_io_cannot_change_earlier_native_source(work, monkeypatch):
    row, ref, read, _original, _epoch, _store, _ = uploaded(work, monkeypatch)
    actual = owner.read_registered_bytes

    def withdrawn(*args):
        result = actual(*args)
        row["status"] = "withdrawn"
        return result

    monkeypatch.setattr(owner, "read_registered_bytes", withdrawn)
    with pytest.raises(DomainError) as error:
        closure(work, [ref], [read])
    assert error.value.reason == "SOURCE_UNAVAILABLE"


def test_refresh_is_an_independent_actual_read_and_not_previous_boolean(work, monkeypatch):
    previous = SimpleNamespace(material_sha256="old", source_basis=[])
    calls = []
    changed = SimpleNamespace(
        material_sha256="changed", source_basis=[], current_evidence_authorized=True
    )
    monkeypatch.setattr(
        owner, "read_fact_sources", lambda *args, **kwargs: calls.append(args) or changed
    )
    with pytest.raises(DomainError):
        owner.refresh_fact_sources(
            work.s, work.ctx, work.pid, object(), previous, operations=("actual-op",)
        )
    assert len(calls) == 1


def test_wire_and_recursive_union_preserve_original_record_null_and_missing():
    raw = {
        "records": [
            {
                "target_key": "actual-target",
                "raw_material": {"unknown": None, "raw": "1.5000"},
                "missing_fields": ["environment"],
            }
        ]
    }
    result = owner._wire(raw)
    assert result == raw
    refs, reads = [], []
    owner._collect(result, refs, reads)
    assert refs == [] and reads == []
    assert result["records"][0]["raw_material"]["raw"] == "1.5000"


def context_ports(work, monkeypatch, *, qualified=True):
    project(work)
    _source, _receipt, ref, read = native(work)
    now = datetime.now(UTC)
    future = now + timedelta(seconds=30)
    fact_refs = []
    operation = "quality.capa.verification.review"
    for kind, start in (
        ("duty", now - timedelta(minutes=1)),
        ("qualification", now - timedelta(minutes=1)),
        ("qualification", future),
    ):
        identity = uuid4()
        basis = dict(
            id=str(identity),
            revision=1,
            epoch=1,
            kind=kind,
            role="quality",
            nature="synthetic",
            state="active",
            operations=[operation],
            purposes=["exact purpose"],
            valid_from=start.isoformat(),
            valid_until=(now + timedelta(hours=1)).isoformat(),
        )
        fact_refs.append(basis)
        work.s.seed(
            ProfessionalFact,
            id=identity,
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.scope.project_id,
            subject_id=work.actor,
            revision=1,
            state="active",
            kind=kind,
            role="quality",
            nature="synthetic",
            valid_from=start,
            valid_until=now + timedelta(hours=1),
            sources=[
                dict(
                    artifact_id=str(ref.id),
                    expected_revision=1,
                    line=1,
                    quote="actual synthetic source line",
                )
            ],
            required_source_read_set=[read.model_dump(mode="json")],
        )
    authority = {
        "scope": work.scope.model_dump(mode="json"),
        "subject_id": str(work.actor),
        "operation": operation,
        "purpose": "exact purpose",
        "authorized": True,
        "qualified": qualified,
        "roles": ["quality"],
        "synthetic": True,
        "fact_refs": fact_refs,
        "facts_revision": common.digest("all scoped facts including future negative"),
        "valid_until": None,
    }
    monkeypatch.setattr(owner.professional, "assess", lambda *_a, **_k: deepcopy(authority))
    monkeypatch.setattr(
        owner.policy,
        "assess",
        lambda *_a, **_k: {
            "nature": "synthetic",
            "id": str(ref.id),
            "revision": 1,
            "valid_until": None,
            "source_basis": [
                dict(
                    id=str(ref.id),
                    revision=1,
                    state="active",
                    valid_from=(now - timedelta(minutes=1)).isoformat(),
                    valid_until=(now + timedelta(hours=1)).isoformat(),
                )
            ],
            "facts_revision": common.digest("current policy"),
            "sources": [ref.model_dump(mode="json")],
            "required_source_read_set": [read.model_dump(mode="json")],
        },
    )
    return authority, ref, read, future


def test_exact_current_professional_sources_and_future_activation_preserved_without_verdict(
    work, monkeypatch
):
    authority, ref, read, future = context_ports(work, monkeypatch)
    material, policy_material, bounds = owner._current_context(
        work.s,
        work.ctx,
        work.pid,
        work.scope,
        "exact purpose",
        "synthetic",
        ("quality.capa.verification.review",),
    )
    saved = material["quality.capa.verification.review"]
    assert saved["assessment_sha256"] == common.digest(authority)
    assert "qualified" not in saved["assessment_material"]
    assert "authorized" not in saved["assessment_material"]
    assert saved["source_material"][0]["sources"] == [ref.model_dump(mode="json")]
    assert saved["source_material"][0]["reads"] == [read.model_dump(mode="json")]
    assert bounds == ()
    assert any(
        value["valid_from"] == future.isoformat()
        for value in saved["assessment_material"]["fact_refs"]
    )
    assert policy_material["facts_revision"] == common.digest("current policy")


@pytest.mark.parametrize("qualified", [None, False])
def test_failed_assessor_cannot_claim_complete_current_professional_source_closure(
    work, monkeypatch, qualified
):
    context_ports(work, monkeypatch, qualified=qualified)
    with pytest.raises(DomainError) as error:
        owner._current_context(
            work.s,
            work.ctx,
            work.pid,
            work.scope,
            "exact purpose",
            "synthetic",
            ("quality.capa.verification.review",),
        )
    assert error.value.reason == "CURRENT_AUTHORITY_OWNER_REQUIRED"
