"""Exact preparation material rules. No source/qualification/current attestations."""

import hashlib

from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef

from .schemas import BaselinePayload, ControlPlanPayload, InstructionPayload, sources_of


def require(condition, code, message, status=409):
    if not condition:
        raise DomainError(code, message, status)


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    return value


def exact_sources(payload):
    return [v.model_dump(mode="json") for v in sources_of(payload)]


def source_refs(payload):
    return [
        SourceRef(
            id=v.artifact_id,
            revision=v.expected_revision,
            kind="artifact",
            position=f"line:{v.line};quote_sha256:{hashlib.sha256(v.quote.encode()).hexdigest()}",
        )
        for v in sources_of(payload)
    ]


def source_reads(payload):
    return _merge_reads(
        [
            {"artifact_id": str(v.artifact_id), "expected_revision": v.expected_revision}
            for v in sources_of(payload)
        ]
    )


def fixed_operations(process):
    values = process.get("operations")
    require(
        isinstance(values, list) and bool(values) and len(values) <= 500,
        "INVALID_FIXED_PROCESS",
        "真实制造配置未提供有界固定工序。",
        503,
    )
    keys = [v.get("key") if isinstance(v, dict) else None for v in values]
    require(
        all(isinstance(v, str) and v for v in keys) and len(keys) == len(set(keys)),
        "INVALID_FIXED_PROCESS",
        "真实制造配置工序身份重复或缺失。",
        503,
    )
    return tuple(keys)


def check_material(payload, process, documents):
    """documents comes from the actual fixed-row owner, never client flags."""
    keys = fixed_operations(process)
    gaps = []
    if isinstance(payload, BaselinePayload):
        require(
            set(keys) == {v.operation_key for v in payload.operations},
            "PROCESS_OPERATION_COVERAGE_MISMATCH",
            "须逐项覆盖所选固定配置的全部工序。",
            422,
        )
        expected = {
            (v.operation_key, key): ref
            for v in payload.operations
            for key in ("work_instruction", "control_plan")
            if (ref := getattr(v, key)) is not None
        }
        require(
            set(documents) == set(expected),
            "FIXED_DOCUMENT_SET_MISMATCH",
            "固定文档集合与提交材料不一致。",
            503,
        )
        for item in payload.operations:
            for kind in ("work_instruction", "control_plan"):
                ref = getattr(item, kind)
                if ref is None:
                    gaps.append(
                        {
                            "code": "MISSING_OPERATION_DOCUMENT",
                            "operation_key": item.operation_key,
                            "kind": kind,
                            "detail": "该工序的固定作业或检验资料未知。",
                        }
                    )
                    continue
                row = documents[(item.operation_key, kind)]
                require(
                    row.get("kind") == kind
                    and row.get("id") == str(ref.id)
                    and type(row.get("revision")) is int
                    and row["revision"] == ref.revision
                    and row.get("operation_key") == item.operation_key
                    and row.get("process") == payload.process.model_dump(mode="json")
                    and row.get("status") == "draft",
                    "FIXED_DOCUMENT_SCOPE_MISMATCH",
                    "工序资料必须是相同制造配置及固定工序的真实不可变版本。",
                )
                require(
                    row.get("is_current") is True and row.get("source_status") == "current",
                    "RECHECK_REQUIRED",
                    "工序资料已不是当前或来源需重核。",
                )
                require(
                    row.get("visibility") in {"private", "category", "audience"}
                    and not (
                        payload.visibility != "private" and row.get("visibility") == "private"
                    ),
                    "FORBIDDEN_SCOPE",
                    "私人工序资料不能被共享基线扩大。",
                    403,
                )
        if payload.risk_notes is None:
            gaps.append({"code": "PROCESS_RISK_UNKNOWN", "detail": "过程风险依据未知。"})
        if payload.packaging_label_basis is None:
            gaps.append({"code": "PACKAGING_LABEL_UNKNOWN", "detail": "包装标识依据未知。"})
    else:
        require(
            payload.operation_key in keys, "UNKNOWN_OPERATION_KEY", "所选工序不在固定配置内。", 422
        )
        if isinstance(payload, InstructionPayload) and payload.conditions is None:
            gaps.append({"code": "INSTRUCTION_CONDITIONS_UNKNOWN", "detail": "作业适用条件未知。"})
        if isinstance(payload, ControlPlanPayload):
            for check in payload.checks:
                missing = [
                    v
                    for v in (
                        "method",
                        "criterion",
                        "frequency",
                        "sampling_method",
                        "reaction_plan",
                        "responsible_role",
                    )
                    if getattr(check, v) is None
                ]
                if check.criterion is not None and all(
                    v is None
                    for v in (check.criterion.nominal, check.criterion.lower, check.criterion.upper)
                ):
                    missing.append("criterion_values")
                if missing:
                    gaps.append(
                        {
                            "code": "CONTROL_CHECK_INCOMPLETE",
                            "key": check.key,
                            "fields": missing,
                            "detail": "控制项的检验、采样、反应或责任依据未齐。",
                        }
                    )
    # These need independent accepted assets/qualification and scope enumeration.
    # A descriptive Process.resource_requirements or an Artifact is not an owner.
    gaps.extend(
        {"code": code, "detail": text}
        for code, text in (
            ("TOOLING_ACCEPTANCE_OWNER_NOT_CONFIGURED", "模具真实验收与适用性尚未接通。"),
            ("FIXTURE_QUALIFICATION_OWNER_NOT_CONFIGURED", "治具真实验收及校准尚未接通。"),
            ("MANUFACTURING_BASELINE_RELEASE_NOT_CONFIGURED", "制造基线尚无具名发布决定。"),
            ("MANUFACTURING_SCOPE_ENUMERATION_NOT_CONFIGURED", "制造影响范围全集尚未核对。"),
        )
    )
    return gaps
