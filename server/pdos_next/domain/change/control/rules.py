"""Deterministic explicit-edge traversal and completeness; zero model calls."""

import hashlib
import json
from collections import deque
from typing import get_args
from uuid import NAMESPACE_URL, uuid5

from pdos_next.schemas.change_control.contracts import (
    Facet,
    GraphSnapshot,
    ImpactAssessment,
    ImpactRow,
    Unknown,
)

ENGINEERING = {
    "spec",
    "part",
    "bom",
    "interface",
    "engineering_configuration",
    "build",
    "sample",
    "test_run",
}
MANUFACTURING = {
    "part",
    "interface",
    "operation",
    "tooling",
    "fixture",
    "sop",
    "work_instruction",
    "control_plan",
    "manufacturing_baseline",
    "pilot_run",
    "manufacturing_release",
    "manufacturing_configuration",
}
# Canonical continuations are checked against actual edges or a separately
# sourced, exact non-applicability declaration. Completeness alone cannot waive one.
NEXT = {
    "spec": {"part", "bom"},
    "part": {"bom", "engineering_configuration", "operation"},
    "bom": {"engineering_configuration"},
    "interface": {"engineering_configuration", "operation"},
    "engineering_configuration": {"build"},
    "build": {"sample", "test_run"},
    "sample": {"test_run"},
    "operation": {"tooling", "fixture"},
    "tooling": {"sop", "control_plan"},
    "fixture": {"sop", "control_plan"},
    "sop": {"pilot_run"},
    "work_instruction": {"pilot_run"},
    "control_plan": {"pilot_run"},
    "manufacturing_baseline": {"pilot_run"},
    "pilot_run": {"manufacturing_release"},
}
EFFECTS = {
    "change.request.create": "建立固定引用的变更请求，未批准或修改任何配置。",
    "change.impact.compute": "保存显式依赖的双线影响与未知，AI推测单独保留。",
    "change.order.prepare": "准备受控实施意图与生效范围，等待各专业具名批准。",
    "change.order.approve": "记录本专业批准；实施、生效和独立复核另行办理。",
    "change.implementation.record": "记录已核验实施事实；未知或失败不代表实际生效。",
    "change.effectivity.record": "保存精确范围的真实回执；发送、接收与生效分开。",
    "change.verification.record": "记录独立适用复核决定，不自动关闭变更。",
    "change.close": "具名关闭全部已实施、生效及独立验证的固定范围。",
    "change.recheck": "记录当前待重核原因；保留全部历史决定与执行事实。",
}


def digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def replace(record, **changes):
    return type(record).model_validate({**record.model_dump(), **changes})


def identity(scope, subject, revision, operation, payload):
    return uuid5(
        NAMESPACE_URL,
        digest(
            {
                "scope": scope.model_dump(mode="json"),
                "subject": str(subject),
                "revision": revision,
                "operation": operation,
                "payload": digest(payload),
            }
        ),
    )


def graph_sources(graph):
    values = list(graph.sources)
    values += [n.source for n in graph.nodes]
    values += [e.source for e in graph.edges]
    values += [c.source for c in graph.coverage if c.source is not None]
    values += [p.source for p in graph.path_applicability if p.source is not None]
    return tuple({digest(s): s for s in values}.values())


def compute_impact(graph: GraphSnapshot, request_revision, hypotheses=()):
    nodes = {n.ref.identity: n for n in graph.nodes}
    outgoing = {}
    for edge in sorted(graph.edges, key=lambda e: e.id):
        outgoing.setdefault(edge.origin.identity, []).append(edge)
    paths = {root.identity: () for root in sorted(graph.roots, key=lambda r: r.identity)}
    queue = deque(paths)
    while queue:
        key = queue.popleft()
        for edge in outgoing.get(key, ()):
            target = edge.target.identity
            if target not in paths:
                paths[target] = (*paths[key], edge.id)
                queue.append(target)
    rows, unknown = [], []
    coverage = {(c.node.identity, c.facet): c for c in graph.coverage}
    applicability = {(p.node.identity, frozenset(p.targets)): p for p in graph.path_applicability}
    for declaration in graph.path_applicability:
        if set(declaration.targets) != NEXT.get(declaration.node.kind):
            unknown.append(
                Unknown(
                    node=declaration.node, facet="manufacturing", reason="后续路径声明范围不匹配。"
                )
            )
    for key in sorted(paths):
        node = nodes[key]
        lanes = []
        if node.ref.kind in ENGINEERING:
            lanes.append("engineering")
        if node.ref.kind in MANUFACTURING:
            lanes.append("manufacturing")
        if not lanes:
            lanes.append("operational")
        rows.append(ImpactRow(node=node, path=paths[key], lanes=tuple(lanes)))
        for facet in get_args(Facet):
            entry = coverage.get((key, facet))
            if entry is None or entry.status == "unknown":
                unknown.append(
                    Unknown(
                        node=node.ref,
                        facet=facet,
                        reason=entry.reason
                        if entry
                        else f"{node.label}的{facet}来源范围未完整核对。",
                    )
                )
        if node.ref.kind in NEXT:
            targets = {e.target.kind for e in outgoing.get(key, ())}
            expected = NEXT[node.ref.kind]
            # A definition's real engineering configuration names its BOM. This
            # sourced path is sufficient; a fabricated direct Spec->BOM is not.
            if node.ref.kind == "spec":
                for edge in outgoing.get(key, ()):
                    if edge.target.kind == "engineering_configuration":
                        targets.update(
                            e.target.kind for e in outgoing.get(edge.target.identity, ())
                        )
            declaration = applicability.get((key, frozenset(expected)))
            present = bool(targets & expected)
            not_applicable = declaration is not None and declaration.status == "not_applicable"
            if present and not_applicable:
                unknown.append(
                    Unknown(
                        node=node.ref,
                        facet="manufacturing" if node.ref.kind in MANUFACTURING else "engineering",
                        reason=f"{node.label}的不适用声明与实际后续关系冲突。",
                    )
                )
            elif not present and not not_applicable:
                facet = "manufacturing" if node.ref.kind in MANUFACTURING else "engineering"
                unknown.append(
                    Unknown(
                        node=node.ref,
                        facet=facet,
                        reason=declaration.reason
                        if declaration is not None and declaration.status == "unknown"
                        else f"{node.label}缺少通往{'/'.join(sorted(expected))}的有出处边。",
                    )
                )
        if node.ref.kind in {"part", "interface"} and not any(
            e.target.kind == "operation" for e in outgoing.get(key, ())
        ):
            unknown.append(
                Unknown(
                    node=node.ref,
                    facet="manufacturing",
                    reason="Part/Interface至Operation关系未知。",
                )
            )
        if node.ref.kind in {"part", "interface"} and not any(
            e.target.kind in {"bom", "engineering_configuration"} for e in outgoing.get(key, ())
        ):
            unknown.append(
                Unknown(
                    node=node.ref,
                    facet="engineering",
                    reason="Part/Interface至BOM/工程配置关系未知。",
                )
            )
    for lane in ("engineering", "manufacturing"):
        if not any(lane in row.lanes and row.path for row in rows):
            unknown.append(Unknown(facet=lane, reason=f"{lane}下游路径未完整建立。"))
    fixed_digest = digest(graph)
    return ImpactAssessment(
        id=uuid5(NAMESPACE_URL, f"change-impact:{fixed_digest}:{request_revision}"),
        request_revision=request_revision,
        graph=graph,
        input_digest=fixed_digest,
        known=tuple(rows),
        unknown=tuple(unknown),
        hypotheses=tuple(hypotheses),
        computed_at=graph.captured_at,
    )


def effectivity_status(order, item):
    receipts = [r for r in order.effectivity if r.item_id == item.id]
    reconciled = {r.reconciles_id for r in receipts if r.reconciles_id is not None}
    active = [r for r in receipts if r.id not in reconciled]
    latest = {}
    for receipt in sorted(active, key=lambda r: (r.received_at, r.occurred_at, str(r.id))):
        if receipt.stage == "effective":
            for unit in receipt.covered_units:
                latest[unit] = receipt.outcome
    effective = {unit for unit, outcome in latest.items() if outcome == "succeeded"}
    if any(
        r.stage == "effective" and r.outcome == "unknown" and not r.covered_units for r in active
    ):
        return "unknown"
    if effective == set(item.selection.units):
        return "effective"
    if effective:
        return "partial"
    if any(r.outcome == "unknown" for r in active):
        return "unknown"
    if any(r.outcome == "failed" for r in active):
        return "failed"
    return "not_effective"


def fully_effective(order):
    return all(effectivity_status(order, item) == "effective" for item in order.plan.items)
