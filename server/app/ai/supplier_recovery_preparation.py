"""Bounded actual material and tooling evidence for supply recovery preparation."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from app.ai.executor import PromptFile
from app.auth.repository import AuthContext
from app.contracts.supplier_recovery import Selection as Selection
from app.contracts.supplier_recovery import SupplierRecoveryAssessment
from app.db.schema import tables
from app.domain.material_exceptions import _authorize, _row
from app.domain.material_schedule import latest_bindings, observations
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_engineering import current_query, metric_query, supplier_row
from app.domain.tooling_schedule import assess as tooling_state

CONTEXT_VERSION = "supplier-recovery-context-v1"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "supplier_recovery_v1.json").read_text()
)


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pick(value: Any, *keys: str) -> dict[str, Any]:
    return _plain({key: value[key] for key in keys if key in value})


def source_state(
    c: Connection, tenant: UUID, project: UUID, selection: Selection
) -> dict[str, Any]:
    records: list[tuple[str, str, dict[str, Any]]] = []
    gaps = [
        "预测仅引用原保存版本，本次未重新评估预测有效性或全局资源容量",
        "未读取未授权项目的库存或供方联系方式",
    ]
    nodes: set[UUID] = set()
    entries = [
        _row(c, tenant, project, identity) for identity in sorted(selection.exception_ids, key=str)
    ]
    actual = observations(c, tenant, project, entries)
    bindings = {value["exception_id"]: value for value in latest_bindings(c, tenant, project)}
    for entry in entries:
        value = actual[entry["id"]]
        state = {
            **pick(entry, "id", "build_id", "issue_id", "material_key", "created_at"),
            "material": value["material"],
            "supply_ready": value["supply_ready"],
            "review_current": value["review_current"],
            "source_digest": value["source_digest"],
            "latest_review": pick(
                value["latest_review"], "id", "version", "disposition", "reason", "created_at"
            ),
        }
        records.append((f"material_exception:{entry['id']}", "实际物料异常与当前供给核对", state))
        # The core contains scoped normalized pools and anonymous quantities, not original files.
        records.append(
            (f"supply_basis:{entry['id']}", "固定需求、规范供给与实际分配", value["core"])
        )
        issue = NpiExecutionService._row(
            c, tables.issues, tenant_id=tenant, project_id=project, record_id=entry["issue_id"]
        )
        records.append(
            (
                f"issue:{issue['id']}",
                "原短缺问题办理",
                pick(
                    issue,
                    "id",
                    "title",
                    "status",
                    "description",
                    "severity",
                    "target_date",
                    "updated_at",
                ),
            )
        )
        binding = bindings.get(entry["id"])
        if binding:
            records.append(
                (
                    f"material_binding:{binding['id']}",
                    "明确登记的排程影响",
                    pick(
                        binding,
                        "id",
                        "version",
                        "mode",
                        "target_point",
                        "node_ids",
                        "ready_at",
                        "reason",
                        "source_digest",
                    ),
                )
            )
            if binding["mode"] != "released":
                nodes.update(UUID(value) for value in binding["node_ids"])
        build_nodes = c.execute(
            select(tables.schedule_nodes.c.id).where(
                tables.schedule_nodes.c.tenant_id == tenant,
                tables.schedule_nodes.c.project_id == project,
                tables.schedule_nodes.c.build_id == entry["build_id"],
            )
        ).scalars()
        nodes.update(build_nodes)
    for identity in sorted(selection.tooling_ids, key=str):
        row = NpiExecutionService._row(
            c, tables.tooling_rounds, tenant_id=tenant, project_id=project, record_id=identity
        )
        payload = row["payload"]
        fields = {
            **pick(
                row,
                "id",
                "code",
                "title",
                "version",
                "status",
                "outcome",
                "asset_reference",
                "tooling_kind",
                "round_label",
                "phase",
                "planning_resource_id",
            ),
            "facts": pick(
                payload,
                "promised",
                "estimated_ready",
                "started",
                "completed",
                "available",
                "conditions",
                "report_id",
                "report_location",
                "inspected_count",
                "accepted_count",
                "build_ids",
                "sample_ids",
                "issue_ids",
                "need_node_ids",
                "schedule_target_point",
            ),
            "first_promise": row["snapshot"].get("first_promise"),
            "availability": tooling_state(c, tenant, project, row),
        }
        records.append((f"tooling_round:{identity}", "实际工装轮次、承诺及可用证据", fields))
        nodes.update(UUID(value) for value in payload["need_node_ids"])
        nodes.update(
            c.execute(
                select(tables.schedule_nodes.c.id).where(
                    tables.schedule_nodes.c.tenant_id == tenant,
                    tables.schedule_nodes.c.project_id == project,
                    tables.schedule_nodes.c.tooling_id == identity,
                )
            ).scalars()
        )
    for identity in sorted(selection.supplier_ids, key=str):
        supplier = supplier_row(c, tenant, identity)
        metrics = _plain(dict(c.execute(metric_query(tenant, project, identity)).mappings().one()))
        records.append(
            (
                f"supplier:{identity}",
                "人员明确选择的供方及本项目工程指标",
                {
                    **pick(supplier, "id", "code", "name"),
                    "metrics": metrics,
                    "scope": "本项目；选择供方不构成对所选短缺的归因",
                },
            )
        )
        rows = list(
            c.execute(
                current_query(tenant, project, identity)
                .order_by(
                    tables.supplier_engineering_records.c.created_at.desc(),
                    tables.supplier_engineering_records.c.id,
                )
                .limit(21)
            ).mappings()
        )
        if len(rows) > 20:
            gaps.append(f"供方 {identity} 仅纳入最近20项工程事项，指标计算覆盖全部当前有效事项")
        for row in rows[:20]:
            records.append(
                (
                    f"supplier_record:{row['id']}",
                    "本项目供方工程事项",
                    {
                        **pick(
                            row, "id", "record_id", "version", "kind", "status", "source_reference"
                        ),
                        "facts": pick(
                            row["payload"],
                            "title",
                            "requested",
                            "promised",
                            "responded",
                            "received",
                            "detected",
                            "build_id",
                            "issue_id",
                            "test_run_id",
                            "reason",
                        ),
                        "first_promise": row["snapshot"].get("first_promise"),
                    },
                )
            )
    # Preserve the latest saved four-time records individually; never synthesize dates.
    if len(nodes) > 100:
        gaps.append("需用节点时间资料超过100个，仅纳入按标识排序的前100个")
    selected_nodes = sorted(nodes, key=str)[:100]
    time_values: dict[UUID, dict[str, Any]] = {node: {} for node in selected_nodes}
    tr, tn = tables.schedule_time_records, tables.schedule_time_nodes
    for kind in ("baseline", "commitment", "forecast", "actual"):
        if kind == "commitment":
            ranked = (
                select(
                    tr.c.id,
                    tr.c.version,
                    tr.c.created_at,
                    tn.c.node_id,
                    tn.c.start,
                    tn.c.end,
                    func.row_number()
                    .over(partition_by=tn.c.node_id, order_by=tr.c.version.desc())
                    .label("position"),
                )
                .join(tn, (tn.c.tenant_id == tr.c.tenant_id) & (tn.c.record_id == tr.c.id))
                .where(
                    tr.c.tenant_id == tenant,
                    tr.c.project_id == project,
                    tr.c.time_kind == kind,
                    tn.c.node_id.in_(selected_nodes),
                )
                .subquery()
            )
            values = {
                row["node_id"]: pick(row, "id", "version", "created_at", "start", "end")
                for row in c.execute(select(ranked).where(ranked.c.position == 1)).mappings()
            }
        else:
            latest = (
                c.execute(
                    select(tr.c.id, tr.c.version, tr.c.created_at)
                    .where(
                        tr.c.tenant_id == tenant, tr.c.project_id == project, tr.c.time_kind == kind
                    )
                    .order_by(tr.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            points = (
                {
                    row["node_id"]: pick(row, "start", "end")
                    for row in c.execute(
                        select(tn.c.node_id, tn.c.start, tn.c.end).where(
                            tn.c.tenant_id == tenant,
                            tn.c.record_id == latest["id"],
                            tn.c.node_id.in_(selected_nodes),
                        )
                    ).mappings()
                }
                if latest
                else {}
            )
            values = (
                {
                    node: {**_plain(dict(latest)), **points.get(node, {"start": None, "end": None})}
                    for node in selected_nodes
                }
                if latest
                else {}
            )
        for node in selected_nodes:
            time_values[node][kind] = values.get(node)
    for node_id in selected_nodes:
        records.append(
            (
                f"schedule_node:{node_id}",
                "需用节点原保存四时间",
                {
                    "node_id": str(node_id),
                    "times": time_values[node_id],
                    "forecast_current": "not_rechecked",
                },
            )
        )
    refs = []
    omitted = []
    used = 0
    identities = {}
    for reference_id, label, value in records:
        value = _plain(value)
        identities[reference_id] = digest(value)
        fields = {}
        skipped = []
        for key, item in value.items():
            if len(encoded({**fields, key: item})) <= 12000:
                fields[key] = item
            else:
                skipped.append(key)
        ref = {
            "reference_id": reference_id,
            "label": label,
            "digest": digest(value),
            "fields": fields,
            "omitted_fields": skipped,
        }
        size = len(encoded(ref))
        if used + size > 160000:
            omitted.append(reference_id)
        else:
            used += size
            refs.append(ref)
    basis = {
        "context_version": CONTEXT_VERSION,
        "project_id": str(project),
        "selection": selection.model_dump(mode="json"),
        "source_digests": identities,
        "gaps": gaps,
    }
    return {
        **basis,
        "digest": digest(basis),
        "model_context": {
            "question": (
                "依据所选实际异常、工装与供方工程事实准备可核对的供应恢复选项；未知条件先补资料。"
            ),
            "references": refs,
            "omitted_references": omitted,
            "coverage_limits": gaps,
        },
    }


def validate_assessment(output: SupplierRecoveryAssessment, snapshot: dict[str, Any]) -> None:
    refs = {row["reference_id"]: row for row in snapshot["model_context"]["references"]}
    statements = list(output.observations)
    for option in output.options:
        if any(
            identity not in refs
            or identity.split(":", 1)[0] not in {"material_exception", "tooling_round"}
            for identity in option.target_reference_ids
        ):
            raise ProductWorkError("供应方案对象须来自本次选定且实际可引用的异常或工装")
        if option.kind == "tooling_recovery" and not any(
            identity.startswith("tooling_round:") for identity in option.target_reference_ids
        ):
            raise ProductWorkError("工装恢复建议须对应实际工装轮次")
        if not any(
            citation.reference_id in option.target_reference_ids
            for citation in option.basis.citations
        ):
            raise ProductWorkError("每个恢复方案须引用其实际对象依据")
        statements.append(option.basis)
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if not ref or ref["digest"] != citation.digest:
                raise ProductWorkError("引用不属于本次原资料版本")
            value: Any = ref["fields"]
            for part in citation.field_path:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
                    value = value[int(part)]
                else:
                    raise ProductWorkError("引用字段不在本次原资料中")
            if citation.quoted_value != (value if isinstance(value, str) else encoded(value)):
                raise ProductWorkError("引用摘录与实际字段不一致")


class SupplierRecoveryPreparation:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project: UUID, selection: Selection) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            return source_state(c, context.tenant.id, project, selection)

    def choices(self, context: AuthContext, project: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, context, project)
            e, i, t, s = (
                tables.material_exceptions,
                tables.issues,
                tables.tooling_rounds,
                tables.suppliers,
            )
            exceptions = list(
                c.execute(
                    select(e.c.id, i.c.title, e.c.build_id)
                    .join(
                        i,
                        (i.c.tenant_id == e.c.tenant_id)
                        & (i.c.project_id == e.c.project_id)
                        & (i.c.id == e.c.issue_id),
                    )
                    .where(e.c.tenant_id == context.tenant.id, e.c.project_id == project)
                    .order_by(e.c.created_at.desc(), e.c.id)
                    .limit(101)
                ).mappings()
            )
            tooling = list(
                c.execute(
                    select(t.c.id, t.c.code, t.c.title, t.c.round_label, t.c.version, t.c.status)
                    .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
                    .order_by(t.c.updated_at.desc(), t.c.id)
                    .limit(101)
                ).mappings()
            )
            suppliers = list(
                c.execute(
                    select(s.c.id, s.c.code, s.c.name)
                    .where(s.c.tenant_id == context.tenant.id)
                    .order_by(s.c.name, s.c.id)
                    .limit(201)
                ).mappings()
            )
            return {
                "exceptions": [_plain(dict(row)) for row in exceptions[:100]],
                "tooling": [_plain(dict(row)) for row in tooling[:100]],
                "suppliers": [_plain(dict(row)) for row in suppliers[:200]],
                "has_more": {
                    "exceptions": len(exceptions) > 100,
                    "tooling": len(tooling) > 100,
                    "suppliers": len(suppliers) > 200,
                },
            }
