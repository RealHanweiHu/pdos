"""Closed immutable DTOs; authority lives exclusively in server ports."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.schemas.verification.contracts import DTO, Key, Revision, Scope, SourceRef, Text

State = Literal["draft", "analysis", "review", "approved", "implementing", "verifying", "closed"]
Discipline = Literal["engineering", "manufacturing", "customer", "regulatory"]
Kind = Literal[
    "spec",
    "part",
    "bom",
    "interface",
    "engineering_configuration",
    "build",
    "sample",
    "test_run",
    "operation",
    "tooling",
    "fixture",
    "sop",
    "work_instruction",
    "control_plan",
    "manufacturing_baseline",
    "pilot_run",
    "manufacturing_release",
    "customer_sample",
    "supply_commitment",
    "inventory",
    "wip",
    "training",
    "evidence",
    "issue",
    "capa",
    "field_feedback",
    "manufacturing_configuration",
    "graph_snapshot",
]
Facet = Literal[
    "engineering",
    "manufacturing",
    "evidence_applicability",
    "in_process_builds",
    "customer_samples",
    "supply_inventory_wip",
    "production_switch",
    "training",
]


class Ref(DTO):
    id: UUID
    revision: Revision
    kind: Kind
    key: Key | None = None

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.id}:{self.revision}:{self.key or ''}"


class Node(DTO):
    ref: Ref
    scope: Scope
    audience: tuple[Key, ...] = Field(min_length=1)
    source: SourceRef
    label: Text


class Edge(DTO):
    id: Key
    origin: Ref
    target: Ref
    source: SourceRef
    relation: Text


class Coverage(DTO):
    node: Ref
    facet: Facet
    status: Literal["complete", "unknown", "not_applicable"]
    source: SourceRef | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def supported(self):
        if self.status != "unknown" and self.source is None:
            raise ValueError("完整或不适用范围声明须有固定来源")
        if self.status != "complete" and self.reason is None:
            raise ValueError("未知或不适用范围须有具体原因")
        return self


class PathApplicability(DTO):
    """One fixed continuation, never permission to remove actual dependencies."""

    node: Ref
    targets: tuple[Kind, ...] = Field(min_length=1)
    status: Literal["applicable", "not_applicable", "unknown"]
    reason: Text
    source: SourceRef | None = None

    @model_validator(mode="after")
    def supported(self):
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("后续目标种类不可重复")
        if self.status != "unknown" and self.source is None:
            raise ValueError("路径适用性判断须有固定来源")
        return self


class Hypothesis(DTO):
    text: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class GraphSnapshot(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    audience: tuple[Key, ...] = Field(min_length=1)
    roots: tuple[Ref, ...] = Field(min_length=1)
    nodes: tuple[Node, ...] = Field(min_length=1)
    edges: tuple[Edge, ...] = Field()
    coverage: tuple[Coverage, ...] = Field()
    # Empty on legacy snapshots: do not change their canonical saved digest.
    path_applicability: tuple[PathApplicability, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    captured_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    nature: Literal["real", "synthetic"]

    @model_validator(mode="after")
    def fixed(self):
        identities = {n.ref.identity for n in self.nodes}
        if len(identities) != len(self.nodes) or len({e.id for e in self.edges}) != len(self.edges):
            raise ValueError("节点/依赖边身份不可重复")
        if len({r.identity for r in self.roots}) != len(self.roots):
            raise ValueError("影响根不可重复")
        if any(r.identity not in identities for r in self.roots):
            raise ValueError("影响根必须是固定节点")
        if any(
            e.origin.identity not in identities or e.target.identity not in identities
            for e in self.edges
        ):
            raise ValueError("依赖边必须引用固定节点")
        pairs = {(c.node.identity, c.facet) for c in self.coverage}
        if len(pairs) != len(self.coverage) or any(
            c.node.identity not in identities for c in self.coverage
        ):
            raise ValueError("范围覆盖须引用唯一固定节点/切片")
        paths = {(p.node.identity, frozenset(p.targets)) for p in self.path_applicability}
        if len(paths) != len(self.path_applicability) or any(
            p.node.identity not in identities for p in self.path_applicability
        ):
            raise ValueError("路径适用性须引用唯一固定节点/后续目标")
        if self.expires_at is not None and self.expires_at <= self.captured_at:
            raise ValueError("快照有效期必须晚于固定时点")
        return self


class ImpactRow(DTO):
    node: Node
    path: tuple[Key, ...]
    lanes: tuple[Literal["engineering", "manufacturing", "operational"], ...]


class Unknown(DTO):
    node: Ref | None = None
    facet: Facet
    reason: Text


class ImpactAssessment(DTO):
    id: UUID
    request_revision: Revision
    graph: GraphSnapshot
    input_digest: Key
    known: tuple[ImpactRow, ...]
    unknown: tuple[Unknown, ...]
    hypotheses: tuple[Hypothesis, ...]
    computed_at: AwareDatetime


class Selection(DTO):
    objects: tuple[Ref, ...] = Field(min_length=1)
    units: tuple[Key, ...] = Field(min_length=1)
    conditions: tuple[Text, ...] = Field(min_length=1)
    sources: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact(self):
        if len({r.identity for r in self.objects}) != len(self.objects):
            raise ValueError("生效对象不可重复")
        if len(set(self.units)) != len(self.units) or any(
            not (u.startswith(("object:", "batch:", "serial:")) and u.split(":", 1)[1])
            for u in self.units
        ):
            raise ValueError("生效范围须有明确唯一对象/批次/序号，不靠到期日期")
        return self


class ControlledIntent(DTO):
    id: UUID
    kind: Literal[
        "new_engineering_configuration",
        "new_manufacturing_configuration",
        "new_build",
        "new_test_run",
        "erp_mes_effectivity",
    ]
    basis: tuple[Ref, ...] = Field(min_length=1)
    description: Text


class PlanItem(DTO):
    id: UUID
    discipline: Discipline
    selection: Selection
    intent: ControlledIntent
    verification_requirement: Text


class Disposition(DTO):
    object: Ref
    handling: Literal["covered_by_plan", "reviewed_no_change", "unknown"]
    item_ids: tuple[UUID, ...] = ()
    rationale: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_handling(self):
        if self.handling == "covered_by_plan" and not self.item_ids:
            raise ValueError("实施影响处置须引用明确计划项")
        if self.handling != "covered_by_plan" and self.item_ids:
            raise ValueError("非实施处置不能声明实施计划项")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("处置计划项不可重复")
        return self


class EffectivityPlan(DTO):
    id: UUID
    items: tuple[PlanItem, ...] = Field(min_length=1)
    expires_at: AwareDatetime | None = None
    dispositions: tuple[Disposition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        if len({i.id for i in self.items}) != len(self.items):
            raise ValueError("生效项不可重复")
        if len({i.intent.id for i in self.items}) != len(self.items):
            raise ValueError("实施意图不可重复")
        if len({d.object.identity for d in self.dispositions}) != len(self.dispositions):
            raise ValueError("影响处置对象不可重复")
        item_ids = {i.id for i in self.items}
        if any(not set(d.item_ids) <= item_ids for d in self.dispositions):
            raise ValueError("影响处置须引用固定计划项")
        return self


class NamedRecord(DTO):
    actor_id: UUID
    at: AwareDatetime
    text: Text
    read_digest: Key
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class Approval(NamedRecord):
    discipline: Discipline
    decision_id: UUID
    content_digest: Key
    expires_at: AwareDatetime | None = None


class ImplementationFact(DTO):
    id: UUID
    reconciles_id: UUID | None = None
    item_id: UUID
    intent_id: UUID
    executor_id: UUID
    outcome: Literal["succeeded", "failed", "unknown"]
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    outputs: tuple[Ref, ...] = ()
    note: Text
    nature: Literal["real", "synthetic"]


class EffectivityFact(DTO):
    id: UUID
    reconciles_id: UUID | None = None
    item_id: UUID
    intent_id: UUID
    stage: Literal["sent", "accepted", "effective"]
    outcome: Literal["succeeded", "failed", "unknown"]
    covered_units: tuple[Key, ...]
    conditions_digest: Key
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    output_refs: tuple[Ref, ...] = ()
    system: Key
    external_id: Key
    nature: Literal["real", "synthetic"]

    @model_validator(mode="after")
    def unique_units(self):
        if len(set(self.covered_units)) != len(self.covered_units):
            raise ValueError("实际生效范围不可重复")
        return self


class VerificationFact(DTO):
    id: UUID
    verifier_id: UUID
    executor_ids: tuple[UUID, ...]
    content_digest: Key
    result: Literal["pass", "fail", "unknown"]
    item_ids: tuple[UUID, ...]
    output_refs: tuple[Ref, ...]
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    observed_from: AwareDatetime
    observed_until: AwareDatetime
    applicable: bool = Field(strict=True)
    current: bool = Field(strict=True)
    nature: Literal["real", "synthetic"]


class Verification(NamedRecord):
    fact: VerificationFact
    decision_id: UUID


class ChangeOrder(DTO):
    id: UUID
    assessment_id: UUID
    assessment_digest: Key
    plan: EffectivityPlan
    policy: SourceRef
    required_disciplines: tuple[Discipline, ...]
    content_digest: Key
    approvals: tuple[Approval, ...] = ()
    implementations: tuple[ImplementationFact, ...] = ()
    effectivity: tuple[EffectivityFact, ...] = ()
    verifications: tuple[Verification, ...] = ()
    closure: NamedRecord | None = None


class History(DTO):
    command_id: UUID
    operation: Key
    actor_id: UUID
    at: AwareDatetime
    from_state: State | None
    to_state: State
    note: Text


class ChangeRequest(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    audience: tuple[Key, ...] = Field(min_length=1)
    requester_id: UUID
    title: Text
    reason: Text
    roots: tuple[Ref, ...] = Field(min_length=1)
    references: tuple[Ref, ...] = Field()
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    status: State = "draft"
    assessments: tuple[ImpactAssessment, ...] = ()
    orders: tuple[ChangeOrder, ...] = ()
    needs_recheck: bool = False
    recheck_reasons: tuple[Text, ...] = ()
    history: tuple[History, ...] = ()

    @model_validator(mode="after")
    def unique(self):
        for values in (self.roots, self.references):
            if len({r.identity for r in values}) != len(values):
                raise ValueError("固定引用不可重复")
        return self


class RequestCreate(DTO):
    title: Text
    reason: Text
    roots: tuple[Ref, ...] = Field(min_length=1)
    references: tuple[Ref, ...] = Field(default=())
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class ImpactCompute(DTO):
    snapshot: Ref

    @model_validator(mode="after")
    def snapshot_kind(self):
        if self.snapshot.kind != "graph_snapshot" or self.snapshot.key is not None:
            raise ValueError("影响计算必须引用精确依赖快照")
        return self

    hypotheses: tuple[Hypothesis, ...] = Field(default=())


class OrderPrepare(DTO):
    assessment_id: UUID
    plan: EffectivityPlan
    reason: Text


class OrderApprove(DTO):
    discipline: Discipline
    text: Text
    expires_at: AwareDatetime | None = None


class ImplementationRecord(DTO):
    item_id: UUID
    fact_id: UUID


class EffectivityRecord(DTO):
    item_id: UUID
    fact_id: UUID


class VerificationRecord(DTO):
    fact_id: UUID
    text: Text


class Close(DTO):
    text: Text


class Recheck(DTO):
    reason: Text
