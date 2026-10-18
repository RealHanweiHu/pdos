"""Knowledge content and fixed result provenance in the caller's ordinary scope.

Only explicit artifact references become content sources. Result snapshots supply
their own domain references; aggregate ``sources`` and professional authority
snapshots are deliberately not traversed. Fixed past results need not be the
latest domain version to remain true; applicability is a separate named action.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, exists, func, literal, select

from pdos_next import models as registered_models  # noqa: F401 -- registry before domain models
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Outbox, Receipt, UploadedOriginal
from pdos_next.project_activity import receipt_binding, source_binding
from pdos_next.project_activity_catalog import SOURCES
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import EVENTS, digest, require_access


@dataclass(frozen=True)
class ResultMaterial:
    model: type
    body_field: str | None = None
    hash_field: str | None = None
    fields: tuple[str, ...] = ()

    @property
    def contract(self):
        part = self.body_field or "fixed_fields"
        return f"{self.model.__tablename__}.{part}/v1"


# This finite material contract has no authority fields, clocks of ingestion,
# derived availability or Current state. Do not replace it with to_jsonb(row).
MATERIALS = (
    ResultMaterial(
        Build,
        fields=(
            "name",
            "type",
            "purpose",
            "project_revision",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
            "previous_build_id",
            "planned_quantity",
            "unit",
            "planned_start",
            "planned_end",
            "verification_objectives",
            "disposition_plan",
        ),
    ),
    ResultMaterial(
        ActualConfiguration,
        fields=(
            "build_id",
            "build_revision",
            "planned_engineering_configuration_id",
            "planned_manufacturing_configuration_id",
            "actual_engineering_configuration_id",
            "actual_engineering_revision",
            "actual_manufacturing_configuration_id",
            "actual_manufacturing_revision",
            "observed_at",
            "differences",
        ),
    ),
    ResultMaterial(
        BuildLot,
        fields=(
            "build_id",
            "build_revision",
            "actual_configuration_id",
            "actual_configuration_revision",
            "lot_label",
            "observed_unit_count",
            "unit",
            "observation_system",
            "observation_external_id",
            "observation_nature",
            "occurred_at",
        ),
    ),
    ResultMaterial(QualityIssueVersion, "issue_snapshot", "snapshot_sha256"),
    ResultMaterial(VerificationRunVersion, "run_snapshot", "snapshot_sha256"),
    ResultMaterial(ChangeRequestVersion, "request_snapshot", "request_sha256"),
)
RESULT_SOURCES = tuple(
    (source, material)
    for source in SOURCES
    for material in MATERIALS
    if source.model is material.model
)
SUPPORTED_RESULTS = tuple(sorted({source.subject_kind for source, _ in RESULT_SOURCES}))
_SCOPE = ("tenant_id", "category_id", "product_id", "project_id", "owner_id", "visibility")


def _require(value, message, reason="SOURCE_STALE", status=409):
    if not value:
        raise DomainError(reason, message, status)


def _uuid(value):
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise DomainError("VALIDATION_FAILED", "来源须使用实际 UUID 引用。", 422) from None


def _artifact(s, ctx, identity):
    row = (
        s.execute(
            select(
                Artifact.id,
                Artifact.product_id,
                Artifact.original_id,
                Artifact.revision,
                Artifact.visibility,
            ).where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == ctx.category_id,
                Artifact.id == _uuid(identity),
            )
        )
        .mappings()
        .one_or_none()
    )
    _require(row is not None, "知识内容来源不在当前实际受众内。", "SOURCE_UNAVAILABLE", 403)
    # The publication target cannot substitute for this source's real product.
    product = require_access(s, ctx, row["product_id"])
    private = row["visibility"] != "category" or product.visibility != "category"
    if row["original_id"] is not None:
        original = s.scalar(
            select(UploadedOriginal.visibility).where(
                UploadedOriginal.tenant_id == ctx.tenant_id,
                UploadedOriginal.category_id == ctx.category_id,
                UploadedOriginal.product_id.is_not_distinct_from(row["product_id"]),
                UploadedOriginal.id == row["original_id"],
            )
        )
        _require(
            original is not None, "知识来源原件不在当前实际受众内。", "SOURCE_UNAVAILABLE", 403
        )
        private |= original != "category"
    return row, private


def _entry(row, ctx, value):
    return {
        **value,
        "category_id": str(ctx.category_id),
        "product_id": str(row["product_id"]) if row["product_id"] is not None else None,
    }


def direct_basis(s, ctx, product, refs, reads):
    """Check explicit content under each actual source product, including null."""
    del product  # A consumer's target product never changes an artifact's scope.
    declared = {
        value["artifact_id"]: value["expected_revision"] for value in evidence.merge_reads(reads)
    }
    values, private = {}, False
    for raw in refs:
        try:
            ref = raw if isinstance(raw, SourceRef) else SourceRef.model_validate(raw)
        except ValidationError as error:
            raise DomainError("VALIDATION_FAILED", "知识正文须引用精确原文。", 422) from error
        _require(
            ref.kind == "artifact", "该来源尚无知识内容读取接口。", "INTEGRATION_REQUIRED", 503
        )
        _require(
            str(ref.id) in declared, "知识内容缺少精确来源读集。", "MISSING_REQUIRED_EVIDENCE", 422
        )
        _require(declared[str(ref.id)] == ref.revision, "知识内容与声明的来源版本不一致。")
        row, hidden = _artifact(s, ctx, ref.id)
        _, actual, source_private = evidence.check_source(s, ctx, row["product_id"], ref)
        _require(
            len(actual) == 1 and actual[0]["id"] == str(ref.id),
            "直接来源身份无法核对。",
            "INTEGRITY_MISMATCH",
        )
        entry = _entry(row, ctx, actual[0])
        previous = values.get(str(ref.id))
        _require(previous is None or previous == entry, "同一知识原件不能采用不同来源版本。")
        values[str(ref.id)] = entry
        private |= hidden or source_private
    return [values[key] for key in sorted(values)], private


def sources_current(s, ctx, basis):
    """Recheck active bytes/registration/original safety for a new use, not history."""
    _require(
        isinstance(basis, Mapping) and isinstance(basis.get("artifacts"), list),
        "知识内容来源基准缺失。",
    )
    seen = set()
    for expected in basis["artifacts"]:
        _require(
            isinstance(expected, Mapping) and "product_id" in expected, "知识内容缺实际来源范围。"
        )
        identity = str(_uuid(expected.get("id")))
        _require(identity not in seen, "知识内容来源基准重复。")
        seen.add(identity)
        row, _ = _artifact(s, ctx, identity)
        actual, _ = evidence.source_basis(
            s,
            ctx,
            row["product_id"],
            [{"artifact_id": identity, "expected_revision": expected.get("revision")}],
        )
        _require(
            len(actual) == 1 and dict(expected) == _entry(row, ctx, actual[0]),
            "知识内容来源版本、内容或安全状态已变化。",
        )
    return True


def content_refs(value):
    """Only SourceRef leaves inside a pure domain snapshot; never inspect authority."""
    found = {}

    def visit(node):
        if isinstance(node, dict):
            if set(node) == {"id", "revision", "kind", "position"}:
                try:
                    ref = SourceRef.model_validate(node)
                except ValidationError as error:
                    raise DomainError(
                        "INTEGRITY_MISMATCH", "实际结果中的领域引用格式不完整。"
                    ) from error
                if ref.kind == "artifact":
                    found[(str(ref.id), ref.revision, ref.position)] = ref.model_dump(mode="json")
                return
            for key, child in node.items():
                if key not in {
                    "authority",
                    "authority_snapshot",
                    "policy_snapshot",
                    "source_basis",
                }:
                    visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(value)
    return [found[key] for key in sorted(found)]


def result_group(source):
    """Actual native subject/Receipt binding, plus the same common Outbox evidence."""
    expected_event = EVENTS.get(source.operations[0])
    _require(expected_event is not None, "结果事件尚未登记。", "INTEGRATION_REQUIRED", 503)
    events = and_(
        Outbox.tenant_id == Receipt.tenant_id,
        Outbox.category_id == Receipt.category_id,
        Outbox.receipt_id == Receipt.id,
        Outbox.subject_id == Receipt.subject_id,
        Outbox.subject_revision == Receipt.subject_revision,
        Outbox.actor_id == Receipt.actor_id,
        Outbox.schema_version == 1,
        Outbox.correlation_id
        == func.coalesce(Receipt.agent_run_id, Receipt.run_id, Receipt.command_id),
    )
    # Event operation is finite; it must agree with this actual Receipt row.
    from sqlalchemy import or_

    event = or_(
        *(and_(Receipt.operation == op, Outbox.type == EVENTS[op]) for op in source.operations)
    )
    audit = and_(
        Audit.tenant_id == Receipt.tenant_id,
        Audit.category_id == Receipt.category_id,
        Audit.receipt_id == Receipt.id,
        Audit.actor_id == Receipt.actor_id,
        Audit.operation == Receipt.operation,
    )
    return (
        *receipt_binding(source),
        exists(select(literal(1)).select_from(Outbox).where(events, event)),
        exists(select(literal(1)).select_from(Audit).where(audit)),
    )


def _result(s, ctx, receipt_id):
    receipt = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.category_id == ctx.category_id,
            Receipt.id == _uuid(receipt_id),
        )
    )
    _require(receipt is not None, "结果回执不在当前实际受众内。", "SOURCE_UNAVAILABLE", 403)
    matches = [
        (source, material)
        for source, material in RESULT_SOURCES
        if source.subject_kind == receipt.subject_type and receipt.operation in source.operations
    ]
    _require(
        len(matches) == 1,
        "此结果尚无知识来源读取接口；可用类型：" + "、".join(SUPPORTED_RESULTS),
        "INTEGRATION_REQUIRED",
        503,
    )
    source, material = matches[0]
    product = require_access(s, ctx, receipt.product_id)
    model = source.model
    fields = (
        *_SCOPE,
        "id",
        "revision",
        *((material.body_field, material.hash_field) if material.body_field else material.fields),
    )
    row = (
        s.execute(
            select(*(getattr(model, key) for key in dict.fromkeys(fields)))
            .select_from(model)
            .join(Receipt, and_(*result_group(source)))
            .where(
                Receipt.id == receipt.id,
                *source_binding(source, ctx.tenant_id, ctx.category_id, receipt.product_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    _require(row is not None, "回执未绑定当前实际可读的原生结果。", "SOURCE_UNAVAILABLE", 403)
    project_visibility = s.scalar(
        select(Project.visibility).where(
            Project.tenant_id == ctx.tenant_id,
            Project.category_id == ctx.category_id,
            Project.product_id == row["product_id"],
            Project.id == row["project_id"],
        )
    )
    _require(
        project_visibility is not None, "原生结果的实际项目不可读。", "SOURCE_UNAVAILABLE", 403
    )
    body = (
        row[material.body_field]
        if material.body_field
        else {key: row[key] for key in material.fields}
    )
    body_sha256 = digest(body)
    if material.hash_field:
        _require(
            row[material.hash_field] == body_sha256,
            "原生结果内容摘要无法核对。",
            "INTEGRITY_MISMATCH",
        )
    refs = content_refs(body) if material.body_field else []
    reads = [{"artifact_id": ref["id"], "expected_revision": ref["revision"]} for ref in refs]
    artifacts, private = direct_basis(s, ctx, None, refs, reads)
    metadata = {
        "receipt_id": str(receipt.id),
        "operation": receipt.operation,
        "subject_type": receipt.subject_type,
        "subject_id": str(receipt.subject_id),
        "subject_revision": receipt.subject_revision,
        "receipt_request_digest": receipt.request_digest,
        "receipt_result_sha256": digest(receipt.result),
        "receipt_visibility": receipt.visibility,
        "table": model.__tablename__,
        "row_id": str(row["id"]),
        "revision": row["revision"],
        **{key: str(row[key]) for key in _SCOPE if key not in {"visibility"}},
        "visibility": row["visibility"],
        "material_contract": material.contract,
        "body_sha256": body_sha256,
        "direct_content_refs": refs,
        "artifacts": artifacts,
    }
    private |= any(
        value != "category"
        for value in (
            receipt.visibility,
            row["visibility"],
            product.visibility,
            project_visibility,
        )
    )
    return metadata, artifacts, private


def results(s, ctx, refs):
    """Resolve finite actual result receipts, with no copied professional credentials."""
    fixed, artifacts, private = {}, {}, False
    for ref in refs:
        identity = ref.get("receipt_id") if isinstance(ref, Mapping) else ref.receipt_id
        key = str(_uuid(identity))
        _require(key not in fixed, "知识结果回执不得重复。", "VALIDATION_FAILED", 422)
        metadata, direct, hidden = _result(s, ctx, key)
        fixed[key] = metadata
        for entry in direct:
            previous = artifacts.get(entry["id"])
            _require(previous is None or previous == entry, "结果引用了不同版本的同一原文。")
            artifacts[entry["id"]] = entry
        private |= hidden
    return (
        [fixed[key] for key in sorted(fixed)],
        [artifacts[key] for key in sorted(artifacts)],
        private,
    )


def results_current(s, ctx, basis):
    """Fixed actual results survive Current advancement; changed sources block new use."""
    _require(
        isinstance(basis, Mapping) and isinstance(basis.get("result_receipts"), list),
        "知识结果来源基准缺失。",
    )
    seen = set()
    for expected in basis["result_receipts"]:
        _require(isinstance(expected, Mapping), "知识结果来源基准格式不完整。")
        identity = str(_uuid(expected.get("receipt_id")))
        _require(identity not in seen, "知识结果来源基准重复。")
        seen.add(identity)
        actual, _, _ = _result(s, ctx, identity)
        _require(dict(expected) == actual, "固定结果身份、业务内容或直接来源已变化。")
    return True
