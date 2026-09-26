"""Versioned cost evidence projections for the existing private project discussion."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.cost_alternatives import source_for_change
from app.domain.cost_backtests import source_state
from app.domain.cost_freezes import row
from app.domain.document_previews import document_row, metadata
from app.domain.material_exceptions import _authorize
from app.domain.product_workspace import ProductWorkAccessError, _plain, digest

VERSION = "cost-discussion-sources.v1"
KINDS = {"cost_gap_observation", "cost_alternative", "cost_backtest"}
LINE_LIMIT = 12
INPUT_FIELDS = (
    "title",
    "stage",
    "source_reference",
    "source_line",
    "source_type",
    "source_as_of",
    "amount",
    "price_quantity",
    "actual_quantity",
    "currency",
    "unit",
    "subsystem",
    "basis",
    "category",
    "tax_basis",
    "tax_rate",
    "freight_basis",
    "scope_basis",
    "evidence_id",
    "evidence_location",
    "location",
    "as_of",
    "from_currency",
    "to_currency",
    "rate",
    "rate_type",
    "supplier_id",
    "bom_item_id",
    "valid_from",
    "valid_until",
    "minimum_order_quantity",
    "maximum_order_quantity",
    "actual_source",
)


def authorize(c: Connection, context: AuthContext, project: UUID) -> None:
    from app.auth.errors import ObjectPermissionDeniedError

    try:
        _authorize(c, context, project)
    except (PermissionError, ObjectPermissionDeniedError) as error:
        raise ProductWorkAccessError("此讨论需原发起人继续有权读取项目成本和问题依据") from error


def options(c: Connection, context: AuthContext, project: UUID) -> list[dict[str, Any]]:
    try:
        authorize(c, context, project)
    except ProductWorkAccessError:
        return []
    choices = []
    for kind, t in (
        ("cost_gap_observation", tables.cost_gap_observations),
        ("cost_alternative", tables.cost_alternatives),
        ("cost_backtest", tables.cost_backtests),
    ):
        columns = [t.c.id, t.c.created_at]
        if kind == "cost_gap_observation":
            columns += [
                t.c.version,
                t.c.state,
                t.c.snapshot["assessment"]["metric"]["scope"]["subsystem"]
                .as_string()
                .label("title"),
            ]
        elif kind == "cost_alternative":
            columns += [t.c.title, t.c.revision_number, t.c.status]
        else:
            columns += [t.c.title, t.c.purpose]
        q = select(*columns).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
        if kind == "cost_alternative":
            newer = t.alias("newer")
            q = q.where(
                ~select(newer.c.id)
                .where(
                    newer.c.tenant_id == t.c.tenant_id,
                    newer.c.root_id == t.c.root_id,
                    newer.c.revision_number > t.c.revision_number,
                )
                .exists()
            )
        for r in c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(100)).mappings():
            version = r.get("revision_number", r.get("version"))
            choices.append(
                {
                    "kind": kind,
                    "id": str(r["id"]),
                    "title": r["title"] + (f" · v{version}" if version else ""),
                    "status": r.get("status", r.get("state", r.get("purpose"))),
                }
            )
    return choices


def calculation_projection(
    calculation: Any, *, subsystem: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    result = calculation["result"]
    lines = [v for v in result["lines"] if subsystem is None or v["subsystem"] == subsystem]
    # Sample unit costs and NRE separately: their amounts have different denominators.
    selected = []
    for bucket in ("unit", "nre"):
        ranked = sorted(
            (v for v in lines if v["basis"] == bucket),
            key=lambda v: (
                v["value"] is None,
                Decimal(v["value"]).copy_abs().copy_negate()
                if v["value"] is not None
                else Decimal(0),
                v["input_id"],
            ),
        )
        selected.extend(ranked[: LINE_LIMIT // 2])
    comparisons = [
        v for v in result["comparisons"] if subsystem is None or v["subsystem"] == subsystem
    ]
    input_ids = {v["input_id"] for v in selected}
    input_ids.update(v["rate_input_id"] for v in selected if v.get("rate_input_id"))
    for group in comparisons:
        for bucket in ("unit", "nre"):
            target = group[bucket]["target"]
            if target:
                input_ids.add(target["input_id"])
                if target.get("rate_input_id"):
                    input_ids.add(target["rate_input_id"])
    current_inputs = {v["id"]: v for v in calculation["snapshot"]["inputs"]}
    inputs = []
    for identity in sorted(input_ids):
        original = current_inputs[identity]
        inputs.append(
            {
                "id": identity,
                "record_id": original["record_id"],
                "version": original["version"],
                "payload": {
                    k: original["payload"][k] for k in INPUT_FIELDS if k in original["payload"]
                },
                "source_digest": original["snapshot"]["source_digest"],
                "snapshot_digest": digest(original["snapshot"]),
            }
        )
    omitted: list[str] = []
    if len(lines) > len(selected):
        omitted.append(
            f"费用行共{len(lines)}项，单位成本与NRE各取最多6项高金额行，共{len(selected)}项；"
            "其余需回原计算查阅，不能据此声称完整归因或范围覆盖"
        )
    comparisons = [
        v for v in result["comparisons"] if subsystem is None or v["subsystem"] == subsystem
    ]
    # The immutable full result remains addressable by id and digest; gaps are never hidden as zero.
    projected = {
        "id": calculation["id"],
        "title": calculation["title"],
        "algorithm": calculation["algorithm"],
        "calculation_digest": calculation["calculation_digest"],
        "source_digest": calculation["source_digest"],
        "command": {
            k: v
            for k, v in calculation["command"].items()
            if k not in {"prices", "target_ids", "rate_ids"}
        },
        "selected_input_count": len(calculation["snapshot"]["inputs"]),
        "complete": result["complete"],
        "comparisons": comparisons,
        "totals": {
            k: result[k]
            for k in (
                "unit_total",
                "known_unit_subtotal",
                "nre_total",
                "known_nre_subtotal",
                "including_allocated_nre",
            )
        },
        "representative_lines": selected,
        "line_count": len(lines),
        "selected_line_count": len(selected),
        "selected_input_versions": inputs,
        "result_digest": digest(result),
        "scope_notice": result.get("scope_notice"),
        "gaps": result.get("gaps", []),
        "warnings": result.get("warnings", []),
    }
    return projected, omitted


def evidence_current(c: Connection, tenant: UUID, project: UUID, record: Any) -> bool:
    try:
        return bool(
            metadata(document_row(c, tenant, project, record["evidence_id"]))
            == record["snapshot"]["evidence"]
        )
    except (ValueError, LookupError, PermissionError):
        return False


def projection(
    c: Connection, context: AuthContext, project: UUID, kind: str, identity: UUID
) -> tuple[str, dict[str, Any], list[str]]:
    authorize(c, context, project)
    tenant = context.tenant.id
    omitted: list[str] = []
    if kind == "cost_gap_observation":
        saved = row(c, tenant, project, tables.cost_gap_observations, identity)
        case = row(c, tenant, project, tables.cost_gap_cases, saved["case_id"])
        fixed = saved["snapshot"]
        metric = fixed["assessment"]["metric"]
        calculation, omitted = calculation_projection(
            fixed["calculation"], subsystem=case["subsystem"]
        )
        title = f"Cost Gap · {case['subsystem']} · 观察 v{saved['version']}"
        fields = {
            "id": str(identity),
            "case_id": str(saved["case_id"]),
            "issue_id": str(case["issue_id"]),
            "version": saved["version"],
            "state": saved["state"],
            "recorded_at": saved["created_at"],
            "basis": case["basis"],
            "comparison": metric["comparison"],
            "scope": {k: v for k, v in metric["scope"].items() if k != "fees"},
            "scope_key": metric["scope_key"],
            "fee_count": len(metric["scope"]["fees"]),
            "assessment_reasons": fixed["assessment"]["reasons"],
            "calculation": calculation,
            "source_now": source_state(c, tenant, project, fixed["calculation"]),
            "semantics": (
                "超标/回到目标内是本次固定范围观察，不代表Issue验证或关闭；"
                "目标变化、费用范围差异不能视作降本"
            ),
        }
    elif kind == "cost_alternative":
        basis = source_for_change(c, tenant, project, identity)
        saved = basis["source"]
        fixed = saved["snapshot"]
        original, omitted = calculation_projection(
            fixed["baseline_calculation"], subsystem=fixed["case"]["subsystem"]
        )
        proposed = None
        if fixed["proposal_calculation"]:
            proposed, more = calculation_projection(
                fixed["proposal_calculation"], subsystem=fixed["case"]["subsystem"]
            )
            omitted += more
        title = f"降本方案 · {saved['title']} · v{saved['revision_number']}"
        fields = {
            "id": str(identity),
            "root_id": saved["root_id"],
            "revision_number": saved["revision_number"],
            "status": saved["status"],
            "command": fixed["command"],
            "comparison": fixed["comparison"],
            "baseline_calculation": original,
            "proposal_calculation": proposed,
            "evidence": fixed["evidence"],
            "source_now": {
                "current": basis["ready"],
                "latest_id": basis["latest_id"],
                "references": basis["references"],
            },
            "semantics": (
                "方案与预期费用不代表已实现降本；质量、时间、供方、NRE代价和未知项"
                "必须分别保留，实施走原ECR批准与验证"
            ),
        }
    elif kind == "cost_backtest":
        saved = row(c, tenant, project, tables.cost_backtests, identity)
        fixed = saved["snapshot"]
        original, omitted = calculation_projection(fixed["frozen_calculation"])
        actual, more = calculation_projection(fixed["actual_calculation"])
        omitted += more
        result = saved["result"]
        # Preserve exact comparison totals and human scope explanations.
        title = "成本回测 · " + saved["title"]
        current = source_state(c, tenant, project, fixed["actual_calculation"])
        current = {**current, "evidence_current": evidence_current(c, tenant, project, saved)}
        current["current"] = current["current"] and current["evidence_current"]
        command = {k: v for k, v in fixed["command"].items() if k != "pairs"}
        pairs = sorted(
            result.get("pairs", []),
            key=lambda v: (
                v["delta"] is None,
                Decimal(v["delta"]).copy_abs().copy_negate()
                if v["delta"] is not None
                else Decimal(0),
                v["frozen_input_id"],
            ),
        )
        selected_pairs = [
            v for bucket in ("unit", "nre") for v in [p for p in pairs if p["basis"] == bucket][:3]
        ]
        if len(pairs) > len(selected_pairs):
            omitted.append(
                f"回测逐项对应共{len(pairs)}项，单位成本与NRE各取最多3项较大差额对应；"
                "其他原对应须在回测记录查阅"
            )
        if result["unmatched_frozen"] or result["unmatched_actual"]:
            omitted.append(
                "回测仍有未对应费用；本次提供未对应数量与结果缺口，逐项原值须在回测页面核对"
            )
        fields = {
            "id": str(identity),
            "purpose": saved["purpose"],
            "command": command,
            "freeze": fixed["freeze"],
            "comparison": {
                k: v
                for k, v in result.items()
                if k
                not in {
                    "pairs",
                    "unmatched_frozen",
                    "unmatched_actual",
                    "unit_drivers",
                    "nre_drivers",
                }
            },
            "representative_pairs": selected_pairs,
            "pair_count": len(pairs),
            "unmatched_counts": {
                k: len(result[k]) for k in ("unmatched_frozen", "unmatched_actual")
            },
            "result_digest": digest(result),
            "frozen_calculation": original,
            "actual_calculation": actual,
            "evidence": fixed["evidence"],
            "source_now": current,
            "semantics": (
                "授权历史快照与当期量产实际用途分列，原币、税费、数量及汇率时点均保留；"
                "费用差异不等于纯单价归因或已实现降本"
            ),
        }
    else:
        raise ValueError("未知成本讨论来源")
    fields = _plain({"projection_version": VERSION, **fields})
    if not fields["source_now"]["current"]:
        omitted.append(
            "原来源已有新版、撤回或原件变化；此为固定历史依据，需补最新资料后评估当前结论"
        )
    return title, fields, omitted


def references(
    title: str, kind: str, identity: UUID, fields: dict[str, Any], omitted: list[str]
) -> list[dict[str, Any]]:
    """Split large projected records without cutting text or losing their fixed identity."""
    from app.ai.project_discussion_sources import json_encoded

    sections: list[tuple[str, Any]] = []

    def divide(path: str, value: Any) -> None:
        if len(json_encoded(value)) <= 8000:
            sections.append((path, value))
        elif isinstance(value, dict):
            for key, child in value.items():
                divide(path + "." + key if path else key, child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                divide(f"{path}[{index}]", child)
        else:
            # A larger indivisible business field is not shortened.
            from app.domain.product_workspace import ProductWorkError

            raise ProductWorkError("所选成本资料含超出讨论容量的单项正文，请先拆分业务说明")

    for key, value in fields.items():
        divide(key, value)
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for path, value in sections:
        if current and len(json_encoded({**current, path: value})) > 16000:
            groups.append(current)
            current = {}
        current[path] = value
    if current:
        groups.append(current)
    result = []
    for i, group in enumerate(groups):
        content = {
            "origin_kind": kind,
            "origin_id": str(identity),
            "projection_version": VERSION,
            "projected_record_digest": digest(fields),
            "part": i + 1,
            "parts": len(groups),
            "sections": group,
        }
        result.append(
            {
                "reference_id": f"{kind}:{identity}" + (f":part:{i + 1}" if i else ""),
                "category": "project_topic_evidence",
                "label": title + f" · 资料 {i + 1}/{len(groups)}",
                "fields": content,
                "digest": digest(content),
                "omitted_fields": omitted,
            }
        )
    return result
