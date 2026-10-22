"""Offline publication material/group checks; no real owner or T2 attestation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from pdos_next.domain.manufacturing_baseline import publication_models as models
from pdos_next.domain.manufacturing_baseline import publication_rules as rules
from pdos_next.domain.manufacturing_baseline import publication_schemas as pub
from pdos_next.domain.manufacturing_baseline import rules as preparation_rules
from pdos_next.domain.manufacturing_baseline import schemas
from pdos_next.domain.quality_issues.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope


def source(label):
    return schemas.Source(
        artifact_id=uuid4(), expected_revision=1, line=2, quote=f"{label}：完整原文  精确空格"
    )


def preparation(kind, payload, process, owner, *, documents=None):
    identity = uuid4()
    body = {
        "schema_version": "pdos-manufacturing-preparation-v1",
        "kind": kind,
        "status": "draft",
        "input": preparation_rules.semantic(payload),
        "scope": {"project_id": str(payload.project_id), "purpose": "本项目固定制造用途"},
        "process_snapshot": deepcopy(process),
        "document_bindings": [
            {
                "operation_key": key[0],
                "kind": key[1],
                "id": str(view.id),
                "revision": view.revision,
                "body_sha256": digest(view.body),
            }
            for key, view in (documents or {}).items()
        ],
        "gaps": preparation_rules.check_material(
            payload,
            process,
            {key: view.model_dump(mode="json") for key, view in (documents or {}).items()},
        ),
        "qualification": "unknown",
        "manufacturing_release": None,
        "negative_enumeration_complete": False,
    }
    return schemas.PreparationView(
        schema_version="pdos-manufacturing-preparation-v1",
        id=identity,
        kind=kind,
        revision=1,
        series_id=identity,
        project_id=payload.project_id,
        owner_id=owner,
        visibility=payload.visibility,
        title=payload.title,
        status="draft",
        purpose="本项目固定制造用途",
        process=payload.process,
        operation_key=getattr(payload, "operation_key", None),
        previous_id=None,
        previous_revision=None,
        created_at="2026-10-16T09:00:00Z",
        is_current=True,
        source_status="current",
        required_source_read_set=preparation_rules.source_reads(payload),
        body=body,
        sources=preparation_rules.exact_sources(payload),
        receipt_id=uuid4(),
        manufacturing_release=None,
        qualification="unknown",
        negative_enumeration_complete=False,
    )


@pytest.fixture
def case():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    owner, category = uuid4(), uuid4()
    process_source = source("制造配置")
    process = {
        "id": str(uuid4()),
        "product_id": str(scope.product_id),
        "revision": 3,
        "name": "固定制造配置",
        "status": "draft",
        "visibility": "private",
        "owner_id": str(owner),
        "engineering_configuration_id": str(uuid4()),
        "engineering_revision": 2,
        "site": "研发现场",
        "line": "A线",
        "operations": [
            {"key": "assemble", "name": "装配", "kind": "assembly"},
            {"key": "inspect", "name": "检验", "kind": "inspection"},
        ],
        "sources": [process_source.model_dump(mode="json")],
        "required_source_read_set": [
            {"artifact_id": str(process_source.artifact_id), "expected_revision": 1}
        ],
        "source_status": "current",
        "qualification_status": "unknown",
        "external_verification": "not_checked",
    }
    process_ref = schemas.ProcessRef(id=process["id"], revision=process["revision"])
    documents = {}
    for key in ("assemble", "inspect"):
        for kind in ("work_instruction", "control_plan"):
            evidence = source(f"{key}/{kind}")
            common = dict(
                project_id=scope.project_id,
                process=process_ref,
                title=f"固定{key}资料",
                reason="保留实际拟定资料",
                sources=(evidence,),
                operation_key=key,
            )
            if kind == "work_instruction":
                payload = schemas.InstructionPayload(
                    **common,
                    conditions="按固定图纸",
                    steps=({"key": "step", "text": "真实作业步骤", "sources": [evidence]},),
                )
            else:
                payload = schemas.ControlPlanPayload(
                    **common,
                    checks=(
                        {
                            "key": "check",
                            "feature": "固定位置",
                            "method": "按图核查",
                            "criterion": {
                                "key": "width",
                                "lower": "1.000000000001",
                                "upper": "2",
                                "unit": "mm",
                                "sources": [evidence],
                            },
                            "frequency": "每件",
                            "sampling_method": "全检",
                            "reaction_plan": "异常隔离",
                            "responsible_role": "品质",
                            "sources": [evidence],
                        },
                    ),
                )
            documents[(key, kind)] = preparation(kind, payload, process, owner)
    baseline_source = source("制造基线")
    baseline_payload = schemas.BaselinePayload(
        project_id=scope.project_id,
        process=process_ref,
        title="固定制造基线草稿",
        reason="汇集全部固定工序",
        sources=(baseline_source,),
        operations=tuple(
            {
                "operation_key": key,
                **{
                    kind: {"kind": kind, "id": documents[(key, kind)].id, "revision": 1}
                    for kind in ("work_instruction", "control_plan")
                },
            }
            for key in ("assemble", "inspect")
        ),
    )
    baseline = preparation(
        "manufacturing_baseline", baseline_payload, process, owner, documents=documents
    )
    declared = (
        source("发布声明"),
        source("适用条件"),
        source("风险"),
        source("包装"),
        source("反应计划"),
    )
    payload = pub.PublishPayload(
        project_id=scope.project_id,
        baseline=schemas.ObjectRef(kind=baseline.kind, id=baseline.id, revision=1),
        purpose="本项目固定制造用途",
        applicability={
            "site": "研发现场",
            "lines": [{"kind": "line", "id": uuid4(), "revision": 1}],
            "conditions": {"text": "仅已声明的固定范围", "sources": [declared[1]]},
            "sources": [declared[0]],
        },
        requirements=tuple(
            {"kind": kind, "requirements": [], "sources": [declared[0]]}
            for kind in ("tooling", "fixture", "equipment", "line", "person")
        ),
        risk={"text": "按原文保留风险", "sources": [declared[2]]},
        packaging={"text": "固定包装标识", "sources": [declared[3]]},
        reaction_plan={"text": "异常后按原文办理", "sources": [declared[4]]},
        reason="本人具名发布固定内容",
        sources=(declared[0],),
        approval_token="original-named-token-for-pure-material",
    )
    additional, read_only = source("实际owner补充来源"), source("其他上游读依赖")
    reads = rules.canonical_reads(
        (
            baseline.required_source_read_set,
            process["required_source_read_set"],
            *(v.required_source_read_set for v in documents.values()),
            tuple(
                {"artifact_id": v.artifact_id, "expected_revision": v.expected_revision}
                for v in (*schemas.sources_of(payload), additional, read_only)
            ),
        )
    )
    material = pub.PublicationMaterial(
        scope=scope,
        category_id=category,
        product_revision=7,
        baseline=baseline,
        process_snapshot=process,
        current_process=process_ref,
        documents=tuple(documents.values()),
        additional_sources=(additional,),
        required_source_read_set=reads,
    )
    return SimpleNamespace(
        scope=scope,
        owner=owner,
        category=category,
        payload=payload,
        material=material,
        plan=rules.prepare_publication(payload, material),
        additional=additional,
        read_only=read_only,
        now=datetime(2026, 10, 17, 10, 1, tzinfo=UTC),
    )


def record(case, plan=None, *, previous=None, expires_at=None):
    """Explicit saved-group substitute, never a database or real consumed proof."""
    plan = plan or case.plan
    identity = uuid4()
    ref = pub.VersionRef(id=identity, revision=1 if previous is None else previous.ref.revision + 1)
    decision = pub.PublicationDecision(
        id=uuid4(),
        scope=plan.scope,
        category_id=plan.category_id,
        actor_id=case.owner,
        requester_id=case.owner,
        actor_kind="human",
        command_id=uuid4(),
        subject_id=plan.scope.product_id,
        product_revision=plan.product_revision,
        consumed_at=case.now - timedelta(seconds=4),
        expires_at=expires_at,
        token_sha256=digest("pure-token"),
        material_sha256=digest("pure-common-material"),
        payload_sha256=plan.payload_sha256,
        body_sha256=plan.body_sha256,
        read_set_sha256=digest([v.model_dump(mode="json") for v in plan.required_source_read_set]),
    )
    receipt = pub.PublicationReceipt(
        id=uuid4(),
        tenant_id=plan.scope.tenant_id,
        category_id=plan.category_id,
        product_id=plan.scope.product_id,
        command_id=decision.command_id,
        confirmation_id=decision.id,
        actor_id=case.owner,
        requester_id=case.owner,
        subject_id=identity,
        subject_revision=ref.revision,
        visibility=plan.visibility,
        request_digest=digest("pure-request"),
        intent_digest=digest("pure-intent"),
        result={"id": str(identity), "revision": ref.revision, "status": "published"},
        created_at=case.now - timedelta(seconds=1),
    )
    return pub.PublicationRecord(
        ref=ref,
        series_id=identity if previous is None else previous.series_id,
        previous=plan.previous,
        plan=plan,
        actor_id=case.owner,
        created_at=case.now - timedelta(seconds=2),
        decision=decision,
        receipt=receipt,
        authority_snapshot={
            "scope": plan.scope.model_dump(mode="json"),
            "subject_id": str(case.owner),
            "operation": pub.OPERATION,
            "purpose": plan.purpose,
            "fact_refs": [{"id": str(uuid4()), "revision": 1}],
            "facts_revision": "actual-source-selector",
        },
        source_basis={
            "artifact_sources": [
                {"id": str(v.artifact_id), "revision": v.expected_revision, "status": "active"}
                for v in plan.required_source_read_set
            ]
        },
    )


def raw_material(case):
    return case.material.model_dump(mode="json")


def rebuild_links(material):
    material["baseline"]["body"]["document_bindings"] = [
        {
            "operation_key": v["operation_key"],
            "kind": v["kind"],
            "id": v["id"],
            "revision": v["revision"],
            "body_sha256": digest(v["body"]),
        }
        for v in material["documents"]
    ]


def test_fixed_publication_preserves_actual_draft_process_and_document_material(case):
    before = raw_material(case)
    plan = rules.prepare_publication(case.payload, case.material)
    assert plan.structural_only is True and not plan.gaps
    assert plan.process == case.material.baseline.process
    assert (
        plan.operations
        == schemas.BaselinePayload.model_validate(case.material.baseline.body["input"]).operations
    )
    assert plan.body["baseline_snapshot"] == before["baseline"]["body"]
    assert len(plan.body["documents"]) == 4
    assert plan.qualification == "unknown" and plan.manufacturing_release is None
    assert raw_material(case) == before and case.material.baseline.status == "draft"
    assert all(v.status == "draft" for v in case.material.documents)
    plan.body["documents"][0]["body"]["input"]["title"] = "修改返回副本"
    assert raw_material(case) == before


@pytest.mark.parametrize(
    "field", ["qualified", "authorized", "released", "actor_id", "receipt", "current"]
)
def test_public_selector_does_not_accept_client_owner_or_qualification_claims(case, field):
    with pytest.raises(ValidationError):
        pub.PublishPayload.model_validate({**case.payload.model_dump(mode="json"), field: True})


@pytest.mark.parametrize(
    "fault",
    [
        "project",
        "baseline_ref",
        "process_ref",
        "document_project",
        "document_process",
        "document_operation",
        "document_revision",
        "document_body",
        "missing",
        "extra",
    ],
)
def test_exact_project_process_operation_and_fixed_document_set_cannot_be_substituted(case, fault):
    value = raw_material(case)
    if fault == "project":
        value["scope"]["project_id"] = str(uuid4())
    elif fault == "baseline_ref":
        value["baseline"]["id"] = str(uuid4())
    elif fault == "process_ref":
        value["process_snapshot"]["id"] = str(uuid4())
    elif fault == "document_project":
        value["documents"][0]["project_id"] = str(uuid4())
    elif fault == "document_process":
        value["documents"][0]["process"]["revision"] = 4
    elif fault == "document_operation":
        value["documents"][0]["operation_key"] = "other"
    elif fault == "document_revision":
        value["documents"][0]["revision"] = 2
    elif fault == "document_body":
        value["documents"][0]["body"]["input"]["title"] = "替换正文"
    elif fault == "missing":
        value["documents"].pop()
    else:
        value["documents"].append(deepcopy(value["documents"][0]))
    with pytest.raises(DomainError):
        rules.prepare_publication(case.payload, value)


@pytest.mark.parametrize(
    "field", ["operations", "engineering_configuration_id", "engineering_revision", "site", "line"]
)
def test_actual_process_must_match_frozen_baseline_contents(case, field):
    value = raw_material(case)
    value["process_snapshot"][field] = [] if field == "operations" else "changed"
    with pytest.raises(DomainError):
        rules.prepare_publication(case.payload, value)


def test_private_baseline_accepts_shared_documents_but_shared_cannot_widen_private(
    case,
):
    value = raw_material(case)
    for document in value["documents"]:
        document["visibility"] = document["body"]["input"]["visibility"] = "category"
    rebuild_links(value)
    assert rules.prepare_publication(case.payload, value).visibility == "private"
    payload = case.payload.model_dump(mode="json")
    payload["visibility"] = "category"
    value["baseline"]["visibility"] = value["baseline"]["body"]["input"]["visibility"] = "category"
    value["documents"][0]["visibility"] = value["documents"][0]["body"]["input"]["visibility"] = (
        "private"
    )
    rebuild_links(value)
    with pytest.raises(DomainError) as error:
        rules.prepare_publication(payload, value)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_explicit_unknown_documents_requirements_and_risk_remain_gaps_not_qualification(case):
    payload = case.payload.model_dump(mode="json")
    payload.update(requirements=[], risk=None, packaging=None, reaction_plan=None)
    payload["applicability"].update(site=None, lines=None)
    material = raw_material(case)
    material["baseline"]["body"]["input"]["operations"][0]["work_instruction"] = None
    material["documents"] = [
        v
        for v in material["documents"]
        if not (v["operation_key"] == "assemble" and v["kind"] == "work_instruction")
    ]
    rebuild_links(material)
    plan = rules.prepare_publication(payload, material)
    codes = {v.code for v in plan.gaps}
    assert {
        "operation_document_unknown",
        "risk_unknown",
        "packaging_unknown",
        "reaction_plan_unknown",
        "site_unknown",
        "line_scope_unknown",
        "tooling_requirements_unknown",
    } <= codes
    assert plan.operations[0].work_instruction is None
    assert plan.qualification == "unknown" and plan.manufacturing_release is None
    assert record(case, plan).qualification == "unknown"


def test_latest_reference_drift_is_explicit_without_rewriting_fixed_content_hash(case):
    material = raw_material(case)
    material["current_process"] = {"id": str(uuid4()), "revision": 4}
    material["baseline"]["is_current"] = False
    material["documents"][0]["is_current"] = False
    material["documents"][1]["source_status"] = "needs_recheck"
    plan = rules.prepare_publication(case.payload, material)
    assert {
        "process_reference_drift",
        "baseline_reference_drift",
        "document_reference_drift",
        "source_recheck_required",
    } <= {v.code for v in plan.gaps}
    assert plan.process == case.plan.process and plan.observed_latest_process != plan.process
    assert plan.body == case.plan.body and plan.body_sha256 == case.plan.body_sha256


def test_one_real_resource_may_supply_multiple_distinct_operation_requirements(case):
    payload = case.payload.model_dump(mode="json")
    resource = {"kind": "person", "id": str(uuid4()), "revision": 1}
    payload["requirements"][-1]["requirements"] = [
        {
            "text": key + "职责要求",
            "operation_keys": [key],
            "resource": resource,
            "sources": payload["sources"],
        }
        for key in ("assemble", "inspect")
    ]
    assert rules.prepare_publication(payload, case.material).qualification == "unknown"
    payload["requirements"][-1]["requirements"][0]["operation_keys"] = ["other"]
    with pytest.raises(DomainError):
        rules.prepare_publication(payload, case.material)


def test_complete_source_union_retains_nested_originals_additional_and_upstream_reads(case):
    plan = case.plan
    assert case.additional in plan.sources
    assert case.read_only.artifact_id not in {v.artifact_id for v in plan.sources}
    assert case.read_only.artifact_id in {v.artifact_id for v in plan.required_source_read_set}
    nested = case.payload.applicability.conditions.sources[0]
    assert nested in plan.sources
    refs = rules.source_refs(plan)
    exact = next(v for v in refs if v.id == nested.artifact_id)
    assert (
        exact.position
        == f"line:{nested.line};quote_sha256:{sha256(nested.quote.encode()).hexdigest()}"
    )
    missing = raw_material(case)
    removed = case.material.documents[0].required_source_read_set[0].artifact_id
    missing["required_source_read_set"] = [
        v for v in missing["required_source_read_set"] if v["artifact_id"] != str(removed)
    ]
    with pytest.raises(DomainError) as error:
        rules.prepare_publication(case.payload, missing)
    assert error.value.code == "MISSING_REQUIRED_EVIDENCE"


def test_source_closure_is_not_truncated_and_conflicting_revisions_are_rejected(case):
    material = raw_material(case)
    extras = [source(str(v)) for v in range(24)]
    material["additional_sources"].extend(v.model_dump(mode="json") for v in extras)
    material["required_source_read_set"].extend(
        {"artifact_id": str(v.artifact_id), "expected_revision": 1} for v in extras
    )
    plan = rules.prepare_publication(case.payload, material)
    assert len(plan.required_source_read_set) > 24 and set(extras) <= set(plan.sources)
    material["required_source_read_set"].append(
        {"artifact_id": str(extras[0].artifact_id), "expected_revision": 2}
    )
    with pytest.raises(DomainError) as error:
        rules.prepare_publication(case.payload, material)
    assert error.value.code == "SOURCE_STALE"
    with pytest.raises(ValidationError):
        rules.canonical_reads(([{"artifact_id": uuid4(), "expected_revision": True}],))


def test_semantic_removes_only_the_common_approval_token_and_preserves_declarations(case):
    semantic = rules.semantic(case.payload)
    assert "approval_token" not in semantic
    assert semantic == {
        k: v for k, v in case.payload.model_dump(mode="json").items() if k != "approval_token"
    }
    assert semantic["requirements"][0]["requirements"] == []
    assert semantic["sources"][0]["quote"] == case.payload.sources[0].quote


@pytest.mark.parametrize("expires", [None, "long"])
def test_t2_saved_group_allows_no_deadline_or_long_deadline_without_new_fixed_ttl(case, expires):
    saved = record(case, expires_at=None if expires is None else case.now + timedelta(days=365))
    pointer = rules.check_publication_record(saved, case.plan, at=case.now)
    assert (
        pointer.version == saved.ref and pointer.series_id == saved.series_id and pointer.epoch == 1
    )
    assert saved.status == "published" and saved.qualification == "unknown"
    assert case.material.baseline.status == "draft"


@pytest.mark.parametrize(
    "fault",
    [
        "private_peer",
        "decision_actor",
        "category",
        "product",
        "body_hash",
        "reads_hash",
        "authority_person",
        "authority_purpose",
        "tier",
    ],
)
def test_named_t2_group_cannot_borrow_another_actor_scope_or_reviewed_material(case, fault):
    saved = record(case).model_dump(mode="json")
    if fault == "private_peer":
        other = str(uuid4())
        saved["actor_id"] = saved["decision"]["actor_id"] = saved["decision"]["requester_id"] = (
            other
        )
        saved["receipt"]["actor_id"] = saved["receipt"]["requester_id"] = other
        saved["authority_snapshot"]["subject_id"] = other
    elif fault == "decision_actor":
        saved["decision"]["requester_id"] = str(uuid4())
    elif fault == "category":
        saved["decision"]["category_id"] = str(uuid4())
    elif fault == "product":
        saved["decision"]["subject_id"] = str(uuid4())
    elif fault == "body_hash":
        saved["decision"]["body_sha256"] = "b" * 64
    elif fault == "reads_hash":
        saved["decision"]["read_set_sha256"] = "b" * 64
    elif fault == "authority_person":
        saved["authority_snapshot"]["subject_id"] = str(uuid4())
    elif fault == "authority_purpose":
        saved["authority_snapshot"]["purpose"] = "其他用途"
    else:
        saved["decision"]["tier"] = "T1"
    with pytest.raises((DomainError, ValidationError)):
        rules.check_publication_record(saved, case.plan, at=case.now)


@pytest.mark.parametrize(
    "fault",
    ["command", "confirmation", "actor", "subject", "revision", "result", "clock", "expired"],
)
def test_receipt_must_bind_the_actual_publication_and_real_save_sequence(case, fault):
    saved = record(case).model_dump(mode="json")
    if fault in {"command", "confirmation", "actor", "subject"}:
        saved["receipt"][fault + "_id"] = str(uuid4())
    elif fault == "revision":
        saved["receipt"]["subject_revision"] = 2
    elif fault == "result":
        saved["receipt"]["result"]["revision"] = True
    elif fault == "clock":
        saved["receipt"]["created_at"] = (case.now - timedelta(seconds=3)).isoformat()
    else:
        saved["decision"]["expires_at"] = saved["receipt"]["created_at"]
    with pytest.raises(DomainError):
        rules.check_publication_record(saved, case.plan, at=case.now)


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "duplicate", "withdrawn", "bool", "old_revision"]
)
def test_saved_source_basis_is_exact_complete_active_and_strictly_versioned(case, fault):
    saved = record(case).model_dump(mode="json")
    basis = saved["source_basis"]["artifact_sources"]
    if fault == "missing":
        basis.pop()
    elif fault == "extra":
        basis.append({"id": str(uuid4()), "revision": 1, "status": "active"})
    elif fault == "duplicate":
        basis.append(deepcopy(basis[0]))
    elif fault == "withdrawn":
        basis[0]["status"] = "withdrawn"
    elif fault == "bool":
        basis[0]["revision"] = True
    else:
        basis[0]["revision"] = 2
    with pytest.raises(DomainError):
        rules.check_publication_record(saved, case.plan, at=case.now)


def test_successor_uses_exact_previous_current_and_monotonic_pointer_epoch(case):
    first = record(case)
    current = rules.check_publication_record(first, case.plan, at=case.now)
    payload = case.payload.model_dump(mode="json")
    payload.update(previous_id=str(first.ref.id), expected_previous_revision=first.ref.revision)
    plan = rules.prepare_publication(payload, case.material, previous=first, current=current)
    next_record = record(case, plan, previous=first)
    pointer = rules.check_publication_record(
        next_record, plan, previous=first, current=current, at=case.now
    )
    assert pointer.version.revision == 2 and pointer.version.id != first.ref.id
    assert pointer.series_id == first.series_id and pointer.epoch == current.epoch + 1
    for changed in (
        None,
        current.model_copy(update={"version": pub.VersionRef(id=uuid4(), revision=1)}),
        current.model_copy(update={"series_id": uuid4()}),
    ):
        with pytest.raises(DomainError) as error:
            rules.prepare_publication(payload, case.material, previous=first, current=changed)
        assert error.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError):
        rules.prepare_publication(case.payload, case.material, current=current)
    wrong = next_record.model_dump(mode="json")
    wrong["ref"]["revision"] = 3
    with pytest.raises(DomainError):
        rules.check_publication_record(wrong, plan, previous=first, current=current, at=case.now)


@pytest.mark.parametrize("field", ["owner_id", "category_id", "scope"])
def test_plan_cannot_change_fixed_owner_scope_while_retaining_the_approved_body(case, field):
    plan = case.plan.model_dump(mode="json")
    if field == "scope":
        plan[field]["project_id"] = str(uuid4())
    else:
        plan[field] = str(uuid4())
    saved = record(case).model_dump(mode="json")
    saved["plan"] = deepcopy(plan)
    with pytest.raises(DomainError):
        rules.check_publication_record(saved, plan, at=case.now)


@pytest.mark.parametrize("field", ["category_id", "owner_id", "visibility"])
def test_successor_does_not_change_the_original_owner_scope_or_audience(case, field):
    first = record(case)
    current = rules.check_publication_record(first, case.plan, at=case.now)
    payload = case.payload.model_dump(mode="json")
    payload.update(previous_id=str(first.ref.id), expected_previous_revision=1)
    material = raw_material(case)
    if field == "category_id":
        material[field] = str(uuid4())
    elif field == "owner_id":
        material["baseline"][field] = str(uuid4())
    else:
        material["baseline"][field] = payload[field] = "category"
        material["baseline"]["body"]["input"][field] = "category"
        for document in material["documents"]:
            document[field] = document["body"]["input"][field] = "category"
        rebuild_links(material)
    with pytest.raises(DomainError) as error:
        rules.prepare_publication(payload, material, previous=first, current=current)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_fixed_content_publication_needs_no_project_or_observation_classification(case):
    saved = record(case)
    current = rules.check_publication_record(saved, case.plan, at=case.now)
    for shape in (pub.PublicationMaterial, pub.PublicationPlan, pub.PublicationCurrent):
        assert "nature" not in shape.model_fields
    for value in (raw_material(case), case.plan.body, current.model_dump(mode="json")):
        assert "nature" not in value
    assert "nature" not in case.material.process_snapshot
    assert "nature" not in case.material.baseline.body
    assert current.version == saved.ref
    assert saved.qualification == "unknown" and saved.manufacturing_release is None


def test_offline_publication_models_fix_scope_documents_t2_actor_and_nullable_expiry():
    for model in (
        models.ManufacturingBaselinePublication,
        models.ManufacturingBaselinePublicationCurrent,
        models.ManufacturingPublicationDocument,
    ):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert model.__tablename__ in sql and "FOREIGN KEY" in sql
        assert "nature" not in model.__table__.columns
        assert "nature" not in sql
        for foreign_key in model.__table__.foreign_key_constraints:
            remote = foreign_key.referred_table
            target = tuple(element.column.name for element in foreign_key.elements)
            unique_keys = {
                tuple(remote.primary_key.columns.keys()),
                *(
                    tuple(constraint.columns.keys())
                    for constraint in remote.constraints
                    if isinstance(constraint, UniqueConstraint)
                ),
            }
            assert target in unique_keys, (model.__tablename__, remote.name, target)
    table = models.ManufacturingBaselinePublication.__table__
    assert table.c.proof_expires_at.nullable
    checks = " ".join(str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint))
    assert "write_tier='T2'" in checks and "actor_id=requester_id" in checks
    assert "writer_id=actor_id" in checks and "proof_expires_at IS NULL" in checks
    assert "revision=previous_revision+1" in checks
    current = models.ManufacturingBaselinePublicationCurrent.__table__
    assert any(
        tuple(c.columns.keys()) == (*models.SCOPE, "series_id")
        for c in current.constraints
        if isinstance(c, UniqueConstraint)
    )
    link = models.ManufacturingPublicationDocument.__table__
    child = next(
        c
        for c in link.constraints
        if isinstance(c, ForeignKeyConstraint) and "document_kind" in c.column_keys
    )
    assert tuple(child.column_keys) == (
        "tenant_id",
        "product_id",
        "project_id",
        "document_kind",
        "document_id",
        "document_revision",
        "process_id",
        "process_revision",
        "operation_key",
    )
    assert all(not link.c[key].nullable for key in child.column_keys)
