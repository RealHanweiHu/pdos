"""Batch-read runtime evidence and separately verify operator-pinned provider originals.

Only the registered suite names may be supplied: they must reproduce the original
manifest pin. Every other binding field comes from original persisted records.
The caller authorizes scope and keeps the complete run population independently.
"""

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import Connection, Select, func, select

from app.ai.issue_business_call_publication import load_publication, verify_call
from app.ai.issue_event_runs import model_context
from app.ai.model_catalog import ProviderName
from app.ai.observations import digest
from app.ai.write_evaluation_publication import WriteEvaluationPublicationError
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.runtime_records import ContextManifest, Observation
from app.db.schema import tables

REASONS = {
    "run_missing": "原范围中缺少运行记录",
    "run_unfinished": "运行未成功完成，仍保留在采集分母",
    "scope_mismatch": "原证据的租户、项目或运行范围不一致",
    "identity_mismatch": "原调用、上下文或结果引用不一致",
    "generation_unverified": "生成时原政策和来源绑定无法核实",
    "usage_unverified": "原调用状态或完整用量无法核实",
    "model_version_unknown": "原模型提供方或明确修订版本无法核实",
    "time_unverified": "原证据时间顺序或采集截止时点不一致",
    "result_unverified": "不可变结果与原成功检查点不一致",
    "observation_unverified": "原来源观察合同或摘要不一致",
    "manifest_unverified": "原运行清单合同、完整性或摘要不一致",
    "bundle_unverified": "原运行版本束、适配器或提示词摘要不一致",
    "admission_unverified": "原预算准入与实际调用不一致",
    "suite_binding_unverified": "登记的网关评测版本不能复现原运行固定摘要",
    "binding_invalid": "原证据不足以构造完整版本绑定",
    "ambiguous_originals": "同一运行存在多组不同原证据，不能任选一组",
    "provider_unverified": "持久链不能独立证明真实提供方调用，仍需核验外部原件",
}
_PARTS = ("generation", "result", "call", "observation", "checkpoint", "manifest", "admission")
for _part, _label in zip(
    _PARTS,
    ("生成政策", "成功结果", "调用", "来源观察", "结果检查点", "运行清单", "预算准入"),
    strict=True,
):
    REASONS[_part + "_missing"] = f"缺少原{_label}记录"
_TIME = TypeAdapter(AwareDatetime)


def provenance_query(tenant_id: UUID, project_id: UUID, run_ids: list[UUID]) -> Select[Any]:
    a, g, r = tables.agent_runs, tables.ai_issue_generation_bindings, tables.ai_issue_event_results
    c, o = tables.model_invocations, tables.application_context_observations
    cp, m, b = (
        tables.application_result_checkpoints,
        tables.application_context_manifests,
        tables.budget_journal,
    )
    sources = (
        a.outerjoin(g, (g.c.tenant_id == a.c.tenant_id) & (g.c.run_id == a.c.id))
        .outerjoin(r, (r.c.tenant_id == a.c.tenant_id) & (r.c.run_id == a.c.id))
        .outerjoin(c, (c.c.tenant_id == a.c.tenant_id) & (c.c.id == r.c.model_invocation_id))
        .outerjoin(
            cp,
            (cp.c.tenant_id == a.c.tenant_id)
            & (cp.c.run_id == a.c.id)
            & (cp.c.invocation_id == c.c.id),
        )
        .outerjoin(
            o,
            (o.c.tenant_id == a.c.tenant_id)
            & (o.c.run_id == a.c.id)
            & (o.c.id == cp.c.observation_id),
        )
        .outerjoin(
            m,
            (m.c.tenant_id == a.c.tenant_id)
            & (m.c.run_id == a.c.id)
            & (m.c.id == cp.c.manifest_id),
        )
        .outerjoin(
            b,
            (b.c.tenant_id == a.c.tenant_id)
            & (b.c.run_id == a.c.id)
            & (b.c.id == m.c.admission_id),
        )
    )
    return (
        select(
            *(
                func.to_jsonb(table.table_valued()).label(label)
                for table, label in (
                    (a, "run"),
                    (g, "generation"),
                    (r, "result"),
                    (c, "call"),
                    (o, "observation"),
                    (cp, "checkpoint"),
                    (m, "manifest"),
                    (b, "admission"),
                )
            )
        )
        .select_from(sources)
        .where(a.c.tenant_id == tenant_id, a.c.project_id == project_id, a.c.id.in_(run_ids))
        .order_by(a.c.id)
    )


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _same(a: Any, b: Any) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def _answer(
    row: Mapping[str, Any], reasons: set[str], binding: IssueEvaluationBinding | None = None
) -> dict[str, Any]:
    r = _obj(row.get("result"))
    stamp = r.get("created_at")
    try:
        original_at = _TIME.validate_python(stamp).isoformat() if stamp is not None else None
    except ValidationError:
        original_at = None
    return {
        "binding": binding.model_dump(mode="json") if binding is not None and not reasons else None,
        "provenance_verified": not reasons,
        "provider_verified": False,
        "reasons": [
            {"code": code, "message": REASONS[code]}
            for code in sorted(reasons | {"provider_unverified"})
        ],
        "references": {
            name: str(_obj(row.get(part))["id"]) if _obj(row.get(part)).get("id") else None
            for name, part in (
                ("result_id", "result"),
                ("invocation_id", "call"),
                ("observation_id", "observation"),
                ("checkpoint_id", "checkpoint"),
                ("manifest_id", "manifest"),
                ("admission_id", "admission"),
            )
        },
        "original_result_at": original_at,
    }


def _verify(
    row: Mapping[str, Any],
    *,
    tenant_id: UUID,
    project_id: UUID,
    run_id: UUID,
    as_of: datetime,
    expected_binding: IssueEvaluationBinding | None,
) -> dict[str, Any]:
    a = _obj(row.get("run"))
    reasons: set[str] = set()
    if not a:
        return _answer(row, {"run_missing"})
    if (
        not _same(a.get("id"), run_id)
        or not _same(a.get("tenant_id"), tenant_id)
        or not _same(a.get("project_id"), project_id)
    ):
        reasons.add("scope_mismatch")
    if (
        a.get("agent_key") != "quality_intelligence"
        or a.get("context_version") != "event-issue-request-v1"
    ):
        reasons.add("identity_mismatch")
    if a.get("status") != "succeeded":
        reasons.add("run_unfinished")
    parts = {name: _obj(row.get(name)) for name in _PARTS}
    for name, part in parts.items():
        if not part.get("id"):
            reasons.add(name + "_missing")
        elif not _same(part.get("tenant_id"), tenant_id) or not _same(part.get("run_id"), run_id):
            reasons.add("scope_mismatch")
        if (
            name in {"generation", "result", "call"}
            and part
            and not _same(part.get("project_id"), project_id)
        ):
            reasons.add("scope_mismatch")
    if any(code.endswith("_missing") for code in reasons):
        return _answer(row, reasons)
    g, r, c, o, cp, m, b = (parts[name] for name in _PARTS)
    snapshot = _obj(g.get("snapshot"))
    policy = _obj(snapshot.get("policy"))
    source = _obj(r.get("source_snapshot"))
    if (
        snapshot.get("version") != "event-issue-generation-binding-v1"
        or snapshot.get("operation_key") != "event.issue.create"
        or any(
            not _same(snapshot.get(k), a.get("id" if k == "run_id" else k))
            for k in ("tenant_id", "project_id", "run_id", "requested_by_user_id", "request_id")
        )
        or not _same(g.get("requested_by_user_id"), a.get("requested_by_user_id"))
        or not _same(policy.get("id"), g.get("policy_id"))
        or policy.get("operation_key") != "event.issue.create"
        or not _same(policy.get("principal_id"), g.get("principal_id"))
        or any(
            source.get(k) != g.get(k) or snapshot.get(k) != g.get(k)
            for k in ("event_row_id", "source_digest")
        )
        or r.get("event_row_id") != g.get("event_row_id")
        or r.get("source_digest") != g.get("source_digest")
        or source.get("tenant_id") != str(tenant_id)
        or source.get("project_id") != str(project_id)
        or source != _obj(a.get("run_context")).get("issue_event_source")
    ):
        reasons.add("generation_unverified")
    pairs = (
        (r.get("model_invocation_id"), c.get("id")),
        (cp.get("invocation_id"), c.get("id")),
        (cp.get("model_call_id"), c.get("budget_call_id")),
        (o.get("model_call_id"), c.get("budget_call_id")),
        (cp.get("observation_id"), o.get("id")),
        (cp.get("manifest_id"), m.get("id")),
        (m.get("observation_id"), o.get("id")),
        (m.get("authorization_id"), o.get("authorization_id")),
        (m.get("admission_id"), b.get("id")),
        (m.get("attempt_id"), b.get("attempt_id")),
    )
    if c.get("agent_key") != "quality_intelligence" or any(not _same(x, y) for x, y in pairs):
        reasons.add("identity_mismatch")
    if (
        c.get("status") != "succeeded"
        or c.get("usage_status") != "known"
        or c.get("input_meter_version") != "normalized_input.v1"
        or type(c.get("structured_attempts")) is not int
        or not 1 <= c["structured_attempts"] <= 3
        or any(
            type(c.get(k)) is not int or c[k] < 0
            for k in ("input_tokens", "output_tokens", "total_tokens")
        )
    ) or c["total_tokens"] != c["input_tokens"] + c["output_tokens"]:
        reasons.add("usage_unverified")
    try:
        ProviderName(str(c.get("provider")))
        if any(
            v is None
            or str(v).strip().casefold()
            in {"", "unknown", "unspecified", "unavailable", "latest", "default", "未知", "未登记"}
            for v in (c.get("model"), c.get("model_version"))
        ):
            raise ValueError("unknown revision")
    except ValueError:
        reasons.add("model_version_unknown")
    try:
        stamps = {
            name: _TIME.validate_python(part.get("created_at"))
            for name, part in {"run": a, **parts}.items()
        }
        if (
            any(not stamps["run"] <= stamp <= as_of for stamp in stamps.values())
            or not max(stamps["observation"], stamps["admission"])
            <= stamps["manifest"]
            <= stamps["call"]
            <= stamps["checkpoint"]
            <= stamps["result"]
            or stamps["generation"] > stamps["observation"]
            or _TIME.validate_python(policy.get("created_at")) > stamps["generation"]
            or _TIME.validate_python(snapshot.get("run_created_at")) != stamps["run"]
        ):
            reasons.add("time_unverified")
    except (ValidationError, TypeError):
        reasons.add("time_unverified")
    bundle, manifest, result = _obj(o.get("bundle")), _obj(m.get("body")), _obj(cp.get("body"))
    compiled, context, admission = (
        _obj(bundle.get("compiled")),
        _obj(o.get("context_body")),
        _obj(b.get("request_binding")),
    )
    if (
        result.get("version") != "application-result.v1"
        or result.get("status") != "succeeded"
        or not isinstance(r.get("proposal"), dict)
        or result.get("output") != r.get("proposal")
        or result.get("structured_attempts") != c.get("structured_attempts")
    ):
        reasons.add("result_unverified")
    try:
        actual_context = model_context(source)
        if context.get("context") != actual_context:
            reasons.add("observation_unverified")
    except (KeyError, TypeError, ValueError):
        actual_context = None
        reasons.add("observation_unverified")
    try:
        observed = Observation.model_validate(o.get("metadata"))
        if (
            not _same(observed.id, o["id"])
            or not _same(observed.tenant_id, tenant_id)
            or not _same(observed.run_id, run_id)
            or observed.allowed_purpose != "event_issue"
            or observed.status != "completed"
            or observed.truncated
            or observed.tool_version != compiled.get("reader")
            or observed.input_digest != digest(actual_context)
            or o.get("output_body") != source
            or observed.output_digest != digest(o.get("output_body"))
        ):
            reasons.add("observation_unverified")
    except ValidationError:
        reasons.add("observation_unverified")
    try:
        pinned = ContextManifest.model_validate(manifest)
        if (
            not _same(pinned.id, m["id"])
            or not _same(pinned.tenant_id, tenant_id)
            or not _same(pinned.run_id, run_id)
            or not _same(pinned.authorization_id, m.get("authorization_id"))
            or UUID(str(o["id"])) not in pinned.observation_ids
            or pinned.completeness != "complete"
            or pinned.missing
            or pinned.digest != digest({k: v for k, v in manifest.items() if k != "digest"})
        ):
            reasons.add("manifest_unverified")
    except (ValidationError, ValueError):
        reasons.add("manifest_unverified")
    if (
        not bundle.get("source_sha256")
        or compiled.get("purpose") != "event_issue"
        or not compiled.get("reader")
        or manifest.get("release_bundle_version") != "sha256:" + digest(bundle)
        or context.get("output_schema_sha256") != digest(compiled.get("schema"))
        or manifest.get("output_schema_version")
        != "sha256:" + str(context.get("output_schema_sha256"))
        or c.get("prompt_version") != context.get("prompt_version")
        or c.get("prompt_version") != manifest.get("prompt_version")
        or c.get("prompt_version") != _obj(compiled.get("prompt")).get("version")
    ):
        reasons.add("bundle_unverified")
    if (
        not admission.get("qualification_ref")
        or not admission.get("meter_version")
        or not _same(admission.get("model_call_id"), c.get("budget_call_id"))
        or any(admission.get(k) != c.get(k) for k in ("provider", "model", "protocol"))
        or b.get("call_kind") != "model"
        or b.get("reservation_status") != "reserved"
    ):
        reasons.add("admission_unverified")
    binding = None
    if expected_binding is None:
        reasons.add("suite_binding_unverified")
    else:
        qualification = dict(
            provider=c.get("provider"),
            model=c.get("model"),
            status="passed",
            suite_version=expected_binding.suite_version,
            suite_digest="sha256:" + expected_binding.suite_digest,
        )
        pin = "sha256:" + digest(
            dict(
                qualification=qualification,
                meter_ref=admission.get("qualification_ref"),
                meter_version=admission.get("meter_version"),
            )
        )
        if manifest.get("model_qualification_version") != pin:
            reasons.add("suite_binding_unverified")
        try:
            binding = IssueEvaluationBinding.model_validate(
                dict(
                    operation_key="event.issue.create",
                    provider=c.get("provider"),
                    model=c.get("model"),
                    model_version=c.get("model_version"),
                    release_bundle_version=manifest.get("release_bundle_version"),
                    suite_version=expected_binding.suite_version,
                    suite_digest=expected_binding.suite_digest,
                    adapter_version=compiled.get("reader"),
                    policy_version=policy.get("contract_version"),
                    policy_revision=policy.get("revision"),
                )
            )
        except ValidationError:
            reasons.add("binding_invalid")
    return _answer(row, reasons, binding)


def collect_provenance(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    run_ids: list[UUID],
    as_of: datetime,
    *,
    expected_binding: IssueEvaluationBinding | None = None,
) -> dict[str, dict[str, Any]]:
    """One read snapshot, including every requested run; no success-only selection."""
    as_of = _TIME.validate_python(as_of)
    ids = sorted(set(run_ids), key=str)
    if not ids:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {str(key): [] for key in ids}
    for raw in c.execute(provenance_query(tenant_id, project_id, ids)).mappings():
        row = dict(raw)
        key = str(_obj(row.get("run")).get("id"))
        if key in grouped and row not in grouped[key]:
            grouped[key].append(row)
    answers = {
        str(key): _answer({}, {"ambiguous_originals"})
        if len(grouped[str(key)]) > 1
        else _verify(
            grouped[str(key)][0] if grouped[str(key)] else {},
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=key,
            as_of=as_of,
            expected_binding=expected_binding,
        )
        for key in ids
    }

    # Loading trusted configuration never changes local provenance or the cohort.
    # Missing, expired or mismatched originals remain unverified, not excluded.
    try:
        loaded = load_publication(os.environ, tenant_id, as_of)
    except WriteEvaluationPublicationError:
        loaded = None
    for key, answer in answers.items():
        if not answer["provenance_verified"] or expected_binding is None:
            continue
        proof = verify_call(
            loaded,
            grouped[key][0],
            project_id=project_id,
            run_id=UUID(key),
            binding=expected_binding,
            as_of=as_of,
        )
        if proof is not None:
            answer["provider_verified"] = True
            answer["provider_evidence"] = proof
            answer["reasons"] = [r for r in answer["reasons"] if r["code"] != "provider_unverified"]
    return answers
