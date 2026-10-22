"""No-connect DTO regression. Negative owner seams never attest qualification."""

import copy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Connection, Engine

from pdos_next.domain.manufacturing_baseline import service as m


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No database or network in owned DTO regression")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)
    monkeypatch.setattr(Connection, "execute", deny)
    monkeypatch.setattr(httpx.Client, "request", deny)


@pytest.fixture
def actual_definition_dto(monkeypatch, request):
    from pdos_next import original_security, service
    from pdos_next.domain.products import definitions
    from pdos_next.domain.products.definitions import definition_view

    monkeypatch.setattr(service, "require_access", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        definitions,
        "batch_read",
        lambda session, model, identities: {key: session.get(model, key) for key in identities},
    )

    tenant, owner, product, identity = (uuid4() for _ in range(4))
    refs = [
        SimpleNamespace(
            artifact_id=uuid4(),
            source_revision=revision,
            line=line,
            quote=f"精确原定义行 {line}",
            spec_keys=[],
        )
        for revision, line in ((2, 1), (3, 7))
    ]
    empty_g0 = getattr(request, "param", None) == "g0_empty"
    if empty_g0:
        refs = []
    artifacts = {
        ref.artifact_id: SimpleNamespace(
            tenant_id=tenant,
            owner_id=owner,
            visibility="category",
            revision=ref.source_revision,
            title="固定来源",
        )
        for ref in refs
    }

    class ActualViewNoIOSeam:
        def __init__(self):
            self.calls = 0

        def scalars(self, statement):
            self.calls += 1
            return refs if self.calls == 1 else []

        def get(self, model, key):
            return artifacts[key]

    row = SimpleNamespace(
        id=identity,
        tenant_id=tenant,
        product_id=product,
        variant_id=None,
        category_id=CategoryUUID(int=1000000),
        owner_id=owner,
        parent_definition_id=None,
        revision=1,
        status="draft",
        sealed=empty_g0,
        publication_receipt_id=None,
        derived_from_definition_id=None,
        derived_from_definition_revision=None,
        g0_decision_id=uuid4() if empty_g0 else None,
        source_proposal_id=uuid4() if empty_g0 else None,
        source_submission_id=uuid4() if empty_g0 else None,
        source_proposal_revision=3 if empty_g0 else None,
        visibility="category",
        title="固定定义",
        purpose="内部合成准备",
        use_cases=["内部"],
        requirements=[],
        constraints=[],
        unknowns=[],
        exclusions=[],
        change_reason="首次记录",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(original_security, "source_status", lambda *args: "active")
    return definition_view(
        ActualViewNoIOSeam(), SimpleNamespace(tenant_id=tenant, requester_id=owner), row
    )


def test_real_definition_view_sources_field_is_complete_and_not_mutated(actual_definition_dto):
    before = copy.deepcopy(actual_definition_dto)
    assert "required_source_read_set" not in actual_definition_dto
    expected = m.configurations._merge_reads(actual_definition_dto["sources"])
    assert m._definition_reads(actual_definition_dto) == expected
    assert len(expected) == 2
    assert actual_definition_dto == before


def test_union_keeps_definition_source_not_in_process_or_engineering(actual_definition_dto):
    refs = actual_definition_dto["sources"]
    upstream = [
        dict(artifact_id=refs[0]["artifact_id"], expected_revision=refs[0]["expected_revision"])
    ]
    merged = m.configurations._merge_reads(
        upstream, upstream, m._definition_reads(actual_definition_dto)
    )
    assert len(merged) == 2
    assert refs[1]["artifact_id"] in {v["artifact_id"] for v in merged}


@pytest.mark.parametrize("shape", [None, {}, {"sources": None}, {"sources": "bad"}])
def test_missing_sources_cannot_be_empty_closure(shape):
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(shape)
    assert error.value.reason == "INVALID_FIXED_DEFINITION"
    assert error.value.status == 503


@pytest.mark.parametrize("actual_definition_dto", ["g0_empty"], indirect=True)
def test_actual_g0_definition_without_artifact_edges_has_explicit_empty_closure(
    actual_definition_dto,
):
    before = copy.deepcopy(actual_definition_dto)
    assert actual_definition_dto["sealed"] and actual_definition_dto["g0_decision_id"]
    assert actual_definition_dto["sources"] == []
    assert actual_definition_dto["source_status"] == "current"
    assert m._definition_reads(actual_definition_dto) == []
    assert actual_definition_dto == before


@pytest.mark.parametrize("status", [None, "needs_recheck", "withdrawn", "unavailable"])
def test_empty_artifact_closure_still_requires_current_source_projection(status):
    with pytest.raises(m.DomainError) as error:
        m._definition_reads({"sources": [], "source_status": status})
    assert error.value.reason == "RECHECK_REQUIRED"


def test_definition_artifact_closure_stays_bounded(actual_definition_dto):
    actual_definition_dto["sources"] *= 11
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "INVALID_FIXED_DEFINITION"


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", "not-uuid"),
        ("expected_revision", True),
        ("expected_revision", 0),
        ("expected_revision", "2"),
        ("line", True),
        ("line", 0),
        ("quote", None),
        ("quote", ""),
    ],
)
def test_invalid_exact_source_is_typed_rejection(actual_definition_dto, field, value):
    actual_definition_dto["sources"][0][field] = value
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "INVALID_FIXED_DEFINITION"
    assert error.value.status == 503


def test_missing_source_key_is_typed_rejection(actual_definition_dto):
    del actual_definition_dto["sources"][0]["artifact_id"]
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "INVALID_FIXED_DEFINITION"


@pytest.mark.parametrize("status", ["stale", "withdrawn", "unavailable", None])
def test_each_source_must_remain_active(actual_definition_dto, status):
    actual_definition_dto["sources"][1]["status"] = status
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "RECHECK_REQUIRED"


def test_definition_overall_currentness_is_required(actual_definition_dto):
    actual_definition_dto["source_status"] = "needs_recheck"
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "RECHECK_REQUIRED"


def test_conflicting_revisions_still_use_original_strict_merge(actual_definition_dto):
    copied = copy.deepcopy(actual_definition_dto["sources"][0])
    copied["expected_revision"] += 1
    actual_definition_dto["sources"].append(copied)
    with pytest.raises(m.DomainError) as error:
        m._definition_reads(actual_definition_dto)
    assert error.value.reason == "SOURCE_STALE"
    assert error.value.status == 422


@pytest.mark.parametrize("actual_definition_dto", ["with_artifacts", "g0_empty"], indirect=True)
@pytest.mark.parametrize("operation", list(m.PAYLOADS))
def test_actual_load_fixed_reaches_unchanged_negative_authority_not_keyerror(
    actual_definition_dto,
    monkeypatch,
    operation,
):
    from pdos_next.models import Artifact
    from pdos_next.service import Context

    tenant, actor, product, project_id, process_id, engineering_id = (uuid4() for _ in range(6))
    product = CategoryUUID(actual_definition_dto["product_id"])
    ctx = Context(tenant, actor, actor, category_id=CategoryUUID(int=1000000))
    # The manufacturing document has its own source even when G0 had no
    # Artifact references. It is never inserted into the sealed definition.
    ref = (
        {
            key: actual_definition_dto["sources"][0][key]
            for key in ("artifact_id", "expected_revision", "line", "quote")
        }
        if actual_definition_dto["sources"]
        else {
            "artifact_id": str(uuid4()),
            "expected_revision": 1,
            "line": 1,
            "quote": "制造文件独立来源",
        }
    )
    values = dict(
        project_id=project_id,
        process={"id": process_id, "revision": 1},
        title="真实字段准备",
        visibility="category",
        reason="纯核负例",
        sources=[ref],
    )
    if operation == "npi.work_instruction.record":
        values.update(
            operation_key="assemble", steps=[{"key": "one", "text": "步骤", "sources": [ref]}]
        )
    elif operation == "npi.control_plan.record":
        values.update(
            operation_key="assemble", checks=[{"key": "one", "feature": "尺寸", "sources": [ref]}]
        )
    else:
        values.update(operations=[{"operation_key": "assemble"}])
    payload = m.PAYLOADS[operation].model_validate(values)
    command = m.Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=operation,
        product_id=product,
        expected_revision=1,
        payload=payload.model_dump(mode="json"),
        source_read_set=[],
        category_id=CategoryUUID(int=1000000),
    )
    project = SimpleNamespace(id=project_id, purpose="内部合成准备", visibility="category")
    link = SimpleNamespace(
        definition_id=CategoryUUID(actual_definition_dto["id"]), definition_revision=1
    )
    engineering = SimpleNamespace(
        definition_id=link.definition_id,
        definition_revision=1,
        visibility="category",
        required_source_read_set=[],
    )
    process = SimpleNamespace(
        revision=1,
        engineering_configuration_id=engineering_id,
        visibility="category",
        required_source_read_set=[],
    )
    monkeypatch.setattr(m, "_uow", lambda *a: None)
    monkeypatch.setattr(m, "_persistent_product", lambda *a: None)
    monkeypatch.setattr(m, "_runtime", lambda *a: "no-io-substitute")
    monkeypatch.setattr(m.configurations, "_human", lambda *a: None)
    monkeypatch.setattr(m.projects, "_project", lambda *a: (project, link, actual_definition_dto))
    monkeypatch.setattr(
        m.configurations,
        "get_process",
        lambda *a: (process, {"source_status": "current", "operations": [{"key": "assemble"}]}),
    )
    monkeypatch.setattr(m.configurations, "_row", lambda *a: engineering)
    monkeypatch.setattr(
        m.professional,
        "assess",
        lambda *a, **kw: {
            "reason_codes": ["QUALIFICATION_REQUIRED"],
            "authorized": False,
            "qualified": False,
            "roles": [],
            "scope": {
                "tenant_id": str(tenant),
                "product_id": str(product),
                "project_id": str(project_id),
            },
            "subject_id": str(actor),
            "operation": operation,
            "purpose": project.purpose,
        },
    )
    artifacts = {
        CategoryUUID(ref["artifact_id"]): SimpleNamespace(
            id=CategoryUUID(ref["artifact_id"]),
            tenant_id=tenant,
            category_id=ctx.category_id,
            product_id=product,
            revision=ref["expected_revision"],
            status="active",
            original_id=None,
            content="\n" * (ref["line"] - 1) + ref["quote"],
        )
        for ref in actual_definition_dto["sources"]
    }

    class SourceReadSession:
        def __init__(self):
            self.info, self.reads, self.transaction = {}, [], object()

        def get_transaction(self):
            return self.transaction

        def scalar(self, query):
            assert query.column_descriptions[0]["entity"] is Artifact
            identity = query.compile().params["id_1"]
            self.reads.append(identity)
            return artifacts[identity]

    session = SourceReadSession()
    with pytest.raises(m.DomainError) as error:
        m._load_fixed(session, ctx, command, object(), payload, require_reads=False)
    assert error.value.reason == "QUALIFICATION_REQUIRED"
    assert error.value.status == 403
    assert set(session.reads) == set(artifacts)
