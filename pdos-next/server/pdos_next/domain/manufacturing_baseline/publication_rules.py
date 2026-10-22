"""Pure fixed-content/group checks; no source IO, authority, consumption or CAS.

The host must independently read every supplied material and common record in
its actual caller transaction. The returned plan/pointer is structural material,
not permission, asset acceptance, a database Current or manufacturing release.
"""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256

from pdos_next.domain.quality_issues.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef

from .publication_schemas import (
    SCHEMA_VERSION,
    PublicationCurrent,
    PublicationGap,
    PublicationMaterial,
    PublicationPlan,
    PublicationRecord,
    PublishPayload,
    VersionRef,
)
from .schemas import BaselinePayload, ObjectRef, RequiredRead, Source, sources_of


def _require(test, message, code="VALIDATION_FAILED"):
    if not test:
        raise DomainError(code, message)


def semantic(payload: PublishPayload):
    value = payload.model_dump(mode="json")
    value.pop("approval_token")
    return value


def canonical_reads(groups):
    values = {}
    for group in groups:
        for raw in group:
            value = raw if type(raw) is RequiredRead else RequiredRead.model_validate(raw)
            _require(
                value.artifact_id not in values
                or values[value.artifact_id] == value.expected_revision,
                "同一原件不能固定两个来源版本。",
                "SOURCE_STALE",
            )
            values[value.artifact_id] = value.expected_revision
    return tuple(
        RequiredRead(artifact_id=key, expected_revision=values[key])
        for key in sorted(values, key=str)
    )


def source_refs(plan: PublicationPlan):
    return tuple(
        SourceRef(
            id=v.artifact_id,
            revision=v.expected_revision,
            kind="artifact",
            position=f"line:{v.line};quote_sha256:{sha256(v.quote.encode()).hexdigest()}",
        )
        for v in plan.sources
    )


def _previous(previous, current, expected, *, material=None):
    if previous is None:
        _require(
            current is None and expected is None,
            "初版不能覆盖已有发布Current。",
            "VERSION_CONFLICT",
        )
        return
    _require(
        type(previous) is PublicationRecord and type(current) is PublicationCurrent,
        "发布续版需要实际前版和Current材料。",
        "VERSION_CONFLICT",
    )
    plan = previous.plan
    _require(
        expected == previous.ref
        and current.version == previous.ref
        and current.series_id == previous.series_id
        and (
            current.scope,
            current.category_id,
            current.owner_id,
            current.visibility,
        )
        == (plan.scope, plan.category_id, plan.owner_id, plan.visibility),
        "发布前版或Current已改变。",
        "VERSION_CONFLICT",
    )
    if material is not None:
        _require(
            (plan.scope, plan.category_id, plan.owner_id, plan.visibility)
            == (
                material.scope,
                material.category_id,
                material.baseline.owner_id,
                material.baseline.visibility,
            ),
            "发布续版不能暗改固定范围、属主或受众。",
            "FORBIDDEN_SCOPE",
        )


def prepare_publication(payload, material, *, previous=None, current=None):
    payload = PublishPayload.model_validate(payload)
    material = PublicationMaterial.model_validate(material)
    baseline, process = material.baseline, material.process_snapshot
    _require(
        material.scope.project_id == payload.project_id == baseline.project_id
        and payload.baseline
        == ObjectRef(kind=baseline.kind, id=baseline.id, revision=baseline.revision)
        and baseline.kind == "manufacturing_baseline",
        "须发布当前项目所选的精确制造基线。",
        "FORBIDDEN_SCOPE",
    )
    _require(
        payload.visibility == baseline.visibility,
        "基线发布不能暗改原资料受众。",
        "FORBIDDEN_SCOPE",
    )
    _require(
        process.get("id") == str(baseline.process.id)
        and type(process.get("revision")) is int
        and process["revision"] == baseline.process.revision,
        "固定制造配置的真实身份与基线不一致。",
        "SOURCE_STALE",
    )
    declaration = BaselinePayload.model_validate(baseline.body.get("input"))
    _require(
        declaration.project_id == baseline.project_id
        and declaration.process == baseline.process
        and declaration.visibility == baseline.visibility,
        "保存的基线正文与固定身份不一致。",
    )
    keys = [v.get("key") for v in process.get("operations", ()) if isinstance(v, dict)]
    _require(
        keys
        and len(keys) == len(process.get("operations", ()))
        and all(isinstance(v, str) and v for v in keys)
        and len(keys) == len(set(keys))
        and set(keys) == {v.operation_key for v in declaration.operations},
        "发布须精确保留实际制造配置的全部固定工序。",
    )
    fixed_process = baseline.body.get("process_snapshot", {})
    _require(
        all(
            key in process and fixed_process.get(key) == process[key]
            for key in (
                "id",
                "revision",
                "engineering_configuration_id",
                "engineering_revision",
                "operations",
                "site",
                "line",
            )
        ),
        "基线保存的制造配置与本次实际固定内容不一致。",
        "SOURCE_STALE",
    )
    expected = {
        (v.operation_key, kind): ref
        for v in declaration.operations
        for kind in ("work_instruction", "control_plan")
        if (ref := getattr(v, kind)) is not None
    }
    documents = {(v.operation_key, v.kind): v for v in material.documents}
    _require(
        len(documents) == len(material.documents) and set(documents) == set(expected),
        "实际工序资料必须与基线固定集合精确一致。",
    )
    links, snapshots = [], []
    for key, ref in expected.items():
        view = documents[key]
        _require(
            ref == ObjectRef(kind=view.kind, id=view.id, revision=view.revision)
            and view.project_id == baseline.project_id
            and view.process == baseline.process
            and not (baseline.visibility != "private" and view.visibility == "private"),
            "工序资料身份、项目、制造配置或受众不匹配。",
            "FORBIDDEN_SCOPE",
        )
        link = {
            "operation_key": key[0],
            "kind": key[1],
            "id": str(ref.id),
            "revision": ref.revision,
            "body_sha256": digest(view.body),
        }
        links.append(link)
        snapshots.append({**link, "body": deepcopy(view.body)})
    saved_links = baseline.body.get("document_bindings")
    _require(
        isinstance(saved_links, list)
        and len(saved_links) == len(links)
        and sorted(saved_links, key=lambda v: (v["operation_key"], v["kind"]))
        == sorted(links, key=lambda v: (v["operation_key"], v["kind"])),
        "发布不能替换基线保存的固定文档或正文。",
        "SOURCE_STALE",
    )
    for group in payload.requirements:
        for item in group.requirements:
            _require(set(item.operation_keys) <= set(keys), "资源要求不能引用范围外工序。")
    selected_previous = (
        VersionRef(id=payload.previous_id, revision=payload.expected_previous_revision)
        if payload.previous_id is not None
        else None
    )
    _previous(previous, current, selected_previous, material=material)
    process_sources = tuple(Source.model_validate(v) for v in process.get("sources", ()))
    sources = tuple(
        dict.fromkeys(
            (
                *sources_of(payload),
                *baseline.sources,
                *process_sources,
                *(s for v in material.documents for s in v.sources),
                *material.additional_sources,
            )
        )
    )
    reads = canonical_reads((material.required_source_read_set,))
    required = canonical_reads(
        (
            baseline.required_source_read_set,
            process.get("required_source_read_set", ()),
            *(v.required_source_read_set for v in material.documents),
            tuple(
                RequiredRead(artifact_id=v.artifact_id, expected_revision=v.expected_revision)
                for v in sources
            ),
        )
    )
    _require(
        set(required) <= set(reads), "发布须保留完整固定来源读集。", "MISSING_REQUIRED_EVIDENCE"
    )
    gaps = []
    if material.current_process != baseline.process:
        gaps.append(
            PublicationGap(
                code="process_reference_drift",
                detail="已出现另一制造配置版本；保留本次固定版本，适用性由实际用途owner核对。",
            )
        )
    if not baseline.is_current:
        gaps.append(
            PublicationGap(code="baseline_reference_drift", detail="所选固定基线已有后续版本。")
        )
    for view in (baseline, *material.documents):
        if not view.is_current and view is not baseline:
            gaps.append(
                PublicationGap(
                    code="document_reference_drift",
                    detail="所选工序资料已有后续版本。",
                    operation_key=view.operation_key,
                )
            )
        if view.source_status != "current":
            gaps.append(
                PublicationGap(
                    code="source_recheck_required",
                    detail="固定来源需实际来源owner核对；本结构不授予当前适用性。",
                    operation_key=view.operation_key,
                )
            )
    if process.get("source_status") != "current":
        gaps.append(
            PublicationGap(
                code="source_recheck_required", detail="制造配置来源需实际来源owner核对。"
            )
        )
    for field, detail in (
        ("risk", "过程风险依据未知。"),
        ("packaging", "包装标识依据未知。"),
        ("reaction_plan", "反应计划依据未知。"),
    ):
        if getattr(payload, field) is None:
            gaps.append(PublicationGap(code=field + "_unknown", detail=detail))
    if payload.applicability.site is None:
        gaps.append(PublicationGap(code="site_unknown", detail="适用场地尚未明确。"))
    if not payload.applicability.lines:
        gaps.append(PublicationGap(code="line_scope_unknown", detail="实际适用产线范围未知。"))
    for kind in ("tooling", "fixture", "equipment", "line", "person"):
        if not any(v.kind == kind for v in payload.requirements):
            gaps.append(
                PublicationGap(code=kind + "_requirements_unknown", detail=f"{kind}要求依据未知。")
            )
    for item in declaration.operations:
        for kind in ("work_instruction", "control_plan"):
            if getattr(item, kind) is None:
                gaps.append(
                    PublicationGap(
                        code="operation_document_unknown",
                        detail=f"{kind}固定资料未知。",
                        operation_key=item.operation_key,
                    )
                )
    body = {
        "schema_version": SCHEMA_VERSION,
        "scope": material.scope.model_dump(mode="json"),
        "category_id": str(material.category_id),
        "owner_id": str(baseline.owner_id),
        "declaration": semantic(payload),
        "baseline_snapshot": deepcopy(baseline.body),
        "process_snapshot": deepcopy(process),
        "fixed_process": baseline.process.model_dump(mode="json"),
        "documents": snapshots,
        "qualification": "unknown",
        "manufacturing_release": None,
    }
    return PublicationPlan(
        scope=material.scope,
        category_id=material.category_id,
        product_revision=material.product_revision,
        owner_id=baseline.owner_id,
        visibility=baseline.visibility,
        purpose=payload.purpose,
        baseline=payload.baseline,
        process=baseline.process,
        observed_latest_process=material.current_process,
        operations=declaration.operations,
        previous=selected_previous,
        input_snapshot=semantic(payload),
        body=body,
        body_sha256=digest(body),
        payload_sha256=digest(semantic(payload)),
        sources=sources,
        required_source_read_set=reads,
        gaps=tuple(gaps),
    )


def check_publication_record(record, plan, *, previous=None, current=None, at: datetime):
    """Validate a supplied saved group; never write or attest a real consumption."""
    record, plan = PublicationRecord.model_validate(record), PublicationPlan.model_validate(plan)
    _require(at.utcoffset() is not None, "须使用服务器aware时钟。")
    _previous(previous, current, plan.previous)
    _require(
        record.plan == plan
        and record.previous == plan.previous
        and digest(plan.body) == plan.body_sha256
        and digest(plan.input_snapshot) == plan.payload_sha256
        and plan.body.get("scope") == plan.scope.model_dump(mode="json")
        and plan.body.get("category_id") == str(plan.category_id)
        and plan.body.get("owner_id") == str(plan.owner_id)
        and plan.body.get("declaration") == plan.input_snapshot
        and plan.input_snapshot.get("purpose") == plan.purpose
        and plan.input_snapshot.get("baseline") == plan.baseline.model_dump(mode="json")
        and plan.body.get("fixed_process") == plan.process.model_dump(mode="json"),
        "保存的发布内容与实际审阅计划不一致。",
        "SOURCE_STALE",
    )
    if previous is None:
        _require(
            record.ref.revision == 1 and record.series_id == record.ref.id, "初版发布身份不一致。"
        )
    else:
        _require(
            record.series_id == previous.series_id
            and record.ref.id != previous.ref.id
            and record.ref.revision == previous.ref.revision + 1
            and (plan.scope, plan.category_id, plan.owner_id, plan.visibility)
            == (
                previous.plan.scope,
                previous.plan.category_id,
                previous.plan.owner_id,
                previous.plan.visibility,
            ),
            "发布续版须保留同一范围、前版及连续版本。",
            "VERSION_CONFLICT",
        )
    decision, receipt = record.decision, record.receipt
    _require(
        plan.visibility != "private" or record.actor_id == plan.owner_id,
        "私有基线不能借另一具名人的身份发布。",
        "FORBIDDEN_SCOPE",
    )
    _require(
        decision.scope == plan.scope
        and decision.category_id == plan.category_id
        and decision.actor_id == decision.requester_id == record.actor_id
        and decision.subject_id == plan.scope.product_id
        and decision.product_revision == plan.product_revision
        and decision.body_sha256 == plan.body_sha256
        and decision.payload_sha256 == plan.payload_sha256
        and decision.read_set_sha256
        == digest([v.model_dump(mode="json") for v in plan.required_source_read_set]),
        "须绑定本次具名人、完整内容、范围与真实共同T2。",
        "NAMED_DECISION_REQUIRED",
    )
    _require(
        (
            receipt.tenant_id,
            receipt.category_id,
            receipt.product_id,
            receipt.command_id,
            receipt.confirmation_id,
            receipt.actor_id,
            receipt.requester_id,
            receipt.subject_id,
            receipt.subject_revision,
            receipt.visibility,
        )
        == (
            plan.scope.tenant_id,
            plan.category_id,
            plan.scope.product_id,
            decision.command_id,
            decision.id,
            record.actor_id,
            record.actor_id,
            record.ref.id,
            record.ref.revision,
            plan.visibility,
        )
        and receipt.result.get("id") == str(record.ref.id)
        and type(receipt.result.get("revision")) is int
        and receipt.result["revision"] == record.ref.revision
        and receipt.result.get("status") == "published",
        "共同回执必须对应本次实际发布版本及具名决定。",
    )
    _require(
        decision.consumed_at <= record.created_at <= receipt.created_at <= at
        and (decision.expires_at is None or receipt.created_at < decision.expires_at),
        "实际共同消费、保存及回执时间需有效；不得附加T2固定TTL。",
        "NAMED_DECISION_REQUIRED",
    )
    authority = record.authority_snapshot
    _require(
        authority.get("scope") == plan.scope.model_dump(mode="json")
        and authority.get("subject_id") == str(record.actor_id)
        and authority.get("operation") == decision.operation
        and authority.get("purpose") == plan.purpose
        and bool(authority.get("fact_refs"))
        and bool(authority.get("facts_revision")),
        "保存的专业来源必须绑定本次具名人及用途；当前权限仍由实际owner核对。",
        "NAMED_DECISION_REQUIRED",
    )
    basis = record.source_basis.get("artifact_sources")
    _require(
        isinstance(basis, list)
        and all(
            isinstance(v, dict)
            and isinstance(v.get("id"), str)
            and type(v.get("revision")) is int
            and v["revision"] > 0
            for v in basis
        )
        and len({v.get("id") for v in basis}) == len(basis)
        and {(v.get("id"), v.get("revision")) for v in basis}
        == {(str(v.artifact_id), v.expected_revision) for v in plan.required_source_read_set},
        "保存来源必须完整绑定实际已核读集。",
        "MISSING_REQUIRED_EVIDENCE",
    )
    _require(
        all(v.get("status") == "active" for v in basis),
        "来源已撤回或失效，不能用引用漂移提示替代实际来源核对。",
        "SOURCE_STALE",
    )
    return PublicationCurrent(
        scope=plan.scope,
        category_id=plan.category_id,
        series_id=record.series_id,
        owner_id=plan.owner_id,
        visibility=plan.visibility,
        version=record.ref,
        epoch=1 if current is None else current.epoch + 1,
    )
