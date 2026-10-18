"""Fixed owner reads and bounded graph capture; no invented completeness manifests."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import get_args
from uuid import UUID

from sqlalchemy import and_, select

from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    Coverage,
    Edge,
    Facet,
    GraphSnapshot,
    Node,
    Ref,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

UNKNOWN_REASONS = {
    "engineering": "仅已读固定定义、BOM与配置关系；完整工程依赖和正式发布未接入。",
    "manufacturing": "仅已读固定工序/SOP声明；正式治具、夹具、ControlPlan与PilotRun未接入。",
    "evidence_applicability": "原证据固定关系已读，变更后的方法/判据/证据适用性尚未批准。",
    "in_process_builds": "已登记Build关系不证明全体在制及外部MES范围已覆盖。",
    "customer_samples": "内部样件身份不证明客户样件、外发或接收范围已完整核对。",
    "supply_inventory_wip": "供给快照不证明ERP库存、WIP及切换占用的完整范围。",
    "production_switch": "缺固定单位、批次/序号的正式生产切换及实际生效端口。",
    "training": "缺具名培训对象、版本、实施与完成事实端口。",
}


@dataclass(frozen=True)
class OwnedObject:
    ref: Ref
    label: str
    scope: Scope
    owner_id: UUID
    visibility: str
    view: dict
    reads: list[dict]
    source_basis: dict
    current: bool

    @property
    def source(self):
        return SourceRef(
            id=self.ref.id,
            revision=self.ref.revision,
            kind="domain",
            position=f"change-owner:{self.ref.kind}:{self.ref.key or ''}",
        )


class CapturedInputReader:
    """Use fixed graph references after the host checks its persisted watermark.

    This reader supplies the pure input projection only. It cannot traverse a
    graph, reload an owner, or participate in a write command's preparation.
    """

    def __init__(self, capture, request, graph):
        self.scope, self.target = request.scope, request.audience
        if graph.scope != self.scope or graph.audience != self.target:
            raise DomainError("FORBIDDEN_SCOPE", "固定影响图范围或受众不一致。", 403)
        labels = {}
        for node in graph.nodes:
            if node.scope != self.scope or node.audience != self.target:
                raise DomainError("FORBIDDEN_SCOPE", "固定影响节点范围或受众不一致。", 403)
            labels[node.ref.identity] = node.label
        basis = capture.source_basis["owners"]
        self.objects = {}
        for ref in (*request.roots, *request.references, *(n.ref for n in graph.nodes)):
            if ref.identity not in basis:
                raise DomainError("INTEGRITY_MISMATCH", "固定图缺少已登记的所有者依据。")
            self.objects[ref.identity] = OwnedObject(
                ref,
                labels.get(ref.identity, ref.kind),
                self.scope,
                capture.owner_id,
                capture.visibility,
                {"source_status": "current"},
                [],
                basis[ref.identity],
                True,
            )

    def resolve(self, ref):
        value = self.objects.get(ref.identity)
        if value is None or value.ref != ref:
            raise DomainError("FIXED_REFERENCE_MISMATCH", "引用不属于已核对的固定影响图。")
        return value


def audience(product_id, owner_id, visibility):
    return (f"private:{owner_id}" if visibility == "private" else f"product:{product_id}",)


def require_audience(target, obj):
    # A product-scoped object can be narrowed to a private result. A private
    # source can only contribute to that same named private audience.
    source = audience(obj.scope.product_id, obj.owner_id, obj.visibility)
    if obj.visibility == "private" and target != source:
        raise DomainError("AUDIENCE_USE_FORBIDDEN", "私有变更依据不能扩大受众。", 403)


def _row(s, ctx, pid, model, identity):
    row = s.scalar(
        select(model)
        .where(model.id == identity, model.tenant_id == ctx.tenant_id, model.product_id == pid)
        .execution_options(populate_existing=True, autoflush=False, yield_per=100)
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "固定变更引用不在当前可读范围。", 403)
    return row


def _version(row, ref):
    if row.revision != ref.revision:
        raise DomainError("FIXED_REFERENCE_MISMATCH", "固定引用ID与版本不一致。")


def _raw(view):
    return view.model_dump(mode="json") if hasattr(view, "model_dump") else view


class OwnerReader:
    """One explicit phase's owner reads. Never reused across public calls/phases."""

    def __init__(self, s, ctx, pid, scope, target, issue_loader):
        self.s, self.ctx, self.pid = s, ctx, pid
        self.scope, self.target, self.issue_loader = scope, target, issue_loader
        self.objects = {}
        self.issue_wrappers = {}

    def resolve(self, ref):
        if ref.identity in self.objects:
            return self.objects[ref.identity]
        row, view, reads, basis = self._load(ref)
        _version(row, ref)
        project = getattr(row, "project_id", self.scope.project_id)
        if project != self.scope.project_id:
            raise DomainError("FORBIDDEN_SCOPE", "固定引用跨项目。", 403)
        obj = OwnedObject(
            ref,
            str(view.get("name", view.get("title", view.get("label", ref.kind))))[:2000],
            self.scope,
            row.owner_id,
            row.visibility,
            view,
            reads,
            basis,
            view.get("source_status", "current") == "current"
            and not view.get("needs_recheck", False),
        )
        require_audience(self.target, obj)
        self.objects[ref.identity] = obj
        return obj

    def _load(self, ref):
        from pdos_next.domain.configurations import models as cm
        from pdos_next.domain.configurations import service as cs
        from pdos_next.domain.products.definitions import definition_view
        from pdos_next.domain.products.models import DefinitionRevision

        s, ctx, pid = self.s, self.ctx, self.pid
        basis = {}
        if ref.kind == "field_feedback":
            from .field_bridge import get as field_feedback

            row, view, _, _ = field_feedback(s, ctx, pid, ref)
            return (
                row,
                view,
                view["required_source_read_set"],
                {
                    "feedback_version_id": str(row.id),
                    "feedback_sha256": row.body_sha256,
                    "feedback_source_basis": deepcopy(row.source_basis),
                },
            )
        if ref.kind in {"issue", "capa"}:
            identity = (ref.id, ref.revision)
            if identity not in self.issue_wrappers:
                self.issue_wrappers[identity] = self.issue_loader(s, ctx, pid, ref.id, ref.revision)
            row, typed = self.issue_wrappers[identity]
            wrapper = _raw(typed)
            view = wrapper["issue"]
            if ref.kind == "capa":
                capa = view.get("capa")
                if not capa or ref.key != str(capa["id"]):
                    raise DomainError("FIXED_REFERENCE_MISMATCH", "CAPA key不属于固定Issue版。")
                view = {**view, "selected_capa": capa}
            elif ref.key is not None:
                raise DomainError("FIXED_REFERENCE_MISMATCH", "Issue引用不能附任意字段key。")
            view = {**view, "source_status": wrapper["source_status"]}
            return (
                row,
                view,
                wrapper["required_source_read_set"],
                {
                    "issue_source_basis": row.source_basis,
                    "current_policy": wrapper.get("policy"),
                },
            )
        if ref.kind == "engineering_configuration":
            row, view = cs.get_engineering(s, ctx, pid, ref.id)
        elif ref.kind in {"manufacturing_configuration", "operation", "sop"}:
            row, view = cs.get_process(s, ctx, pid, ref.id)
            if ref.kind in {"operation", "sop"}:
                op = next((v for v in view["operations"] if v["key"] == ref.key), None)
                if op is None or (ref.kind == "sop" and not op.get("sop")):
                    raise DomainError("FIXED_REFERENCE_MISMATCH", "工序/SOP key不在固定制造版。")
                view = {**view, "selected_operation": op, "name": op["name"]}
        elif ref.kind == "bom":
            row, view = cs.get_bom(s, ctx, pid, ref.id)
            if ref.key is not None:
                line = next((v for v in view["lines"] if v["key"] == ref.key), None)
                if line is None:
                    raise DomainError("FIXED_REFERENCE_MISMATCH", "BOM行key不在固定版。")
                view = {**view, "selected_line": line}
        elif ref.kind == "part":
            row = _row(s, ctx, pid, cm.PartIdentity, ref.id)
            view = cs._part_view(s, ctx, pid, row)
        elif ref.kind == "spec":
            row = _row(s, ctx, pid, DefinitionRevision, ref.id)
            view = definition_view(s, ctx, row)
            if ref.key is not None and not any(v["key"] == ref.key for v in view["specs"]):
                raise DomainError("FIXED_REFERENCE_MISMATCH", "规格key不在固定定义。")
            reads = [
                {"artifact_id": v["artifact_id"], "expected_revision": v["expected_revision"]}
                for v in view["sources"]
            ]
            return row, view, reads, basis
        elif ref.kind == "build":
            from pdos_next.domain.builds.service import _build, _linked

            row = _build(s, ctx, pid, ref.id)
            _, eng, process, reads = _linked(s, ctx, pid, row)
            view = {
                "name": row.name,
                "source_status": "current"
                if all(v["source_status"] == "current" for v in (eng, process))
                else "needs_recheck",
                "engineering": eng,
                "manufacturing": process,
            }
            return row, view, reads, basis
        elif ref.kind == "sample":
            from pdos_next.domain.build_execution.service import get_sample

            row, view = get_sample(s, ctx, pid, ref.id)
        elif ref.kind == "test_run":
            from pdos_next.domain.test_resources.retained import inspect_retained_execution
            from pdos_next.domain.verification_launch.models import VerificationRunVersion

            row = s.scalar(
                select(VerificationRunVersion).where(
                    VerificationRunVersion.tenant_id == ctx.tenant_id,
                    VerificationRunVersion.product_id == pid,
                    VerificationRunVersion.run_id == ref.id,
                    VerificationRunVersion.revision == ref.revision,
                )
            )
            if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
                raise DomainError("FORBIDDEN_SCOPE", "固定Run不在当前可读范围。", 403)
            proof = inspect_retained_execution(s, ctx, pid, row)
            basis = {
                k: v
                for k, v in proof.items()
                if k not in {"checked_at", "execution_window_elapsed"}
            }
            view = {
                **row.run_snapshot,
                "name": "固定测试Run",
                "source_status": "current" if proof["current"] else "needs_recheck",
                "owner_port": "plan_not_integrated"
                if row.status == "planned"
                else "retained_execution",
                "reason_codes": proof.get("reason_codes", []),
            }
        elif ref.kind in {"work_instruction", "control_plan", "manufacturing_baseline"}:
            from pdos_next.domain.manufacturing_baseline.schemas import ObjectRef
            from pdos_next.domain.manufacturing_baseline.service import get_preparation

            row, view = get_preparation(
                s, ctx, pid, ObjectRef(kind=ref.kind, id=ref.id, revision=ref.revision)
            )
            basis = {
                "body_sha256": row.body_sha256,
                "source_basis": row.source_basis,
                "authority_snapshot": row.authority_snapshot,
                "series_id": str(row.series_id),
                "is_current": view["is_current"],
                "receipt_id": view["receipt_id"],
            }
            if view["is_current"] is not True:
                view = {**view, "source_status": "needs_recheck"}
        else:
            raise DomainError("INTEGRATION_REQUIRED", f"{ref.kind}真实所有者读取端口未接入。", 503)
        if ref.kind not in {"bom", "spec", "operation", "sop"} and ref.key is not None:
            raise DomainError("FIXED_REFERENCE_MISMATCH", "该对象不支持任意字段key。")
        reads = view.get("required_source_read_set")
        if reads is None:
            reads = row.required_source_read_set
        return row, view, reads, basis

    def _query(self, model, *conditions):
        rows = self.s.scalars(
            select(model)
            .where(
                model.tenant_id == self.ctx.tenant_id,
                model.product_id == self.pid,
                *conditions,
            )
            .order_by(model.id)
            .execution_options(populate_existing=True, autoflush=False, yield_per=100)
        ).all()
        return rows

    def _current_preparations(self, process_id, process_revision, *, operation_key=None):
        from pdos_next.domain.manufacturing_baseline.models import (
            PreparationCurrent,
            PreparationVersion,
        )

        query = (
            select(PreparationVersion)
            .join(
                PreparationCurrent,
                and_(
                    *[
                        getattr(PreparationCurrent, column) == getattr(PreparationVersion, column)
                        for column in (
                            "tenant_id",
                            "product_id",
                            "project_id",
                            "kind",
                            "series_id",
                            "owner_id",
                            "visibility",
                        )
                    ],
                    PreparationCurrent.version_id == PreparationVersion.id,
                    PreparationCurrent.revision == PreparationVersion.revision,
                ),
            )
            .where(
                PreparationVersion.tenant_id == self.ctx.tenant_id,
                PreparationVersion.product_id == self.pid,
                PreparationVersion.project_id == self.scope.project_id,
                PreparationVersion.process_id == process_id,
                PreparationVersion.process_revision == process_revision,
            )
            .order_by(PreparationVersion.id)
            .execution_options(populate_existing=True, autoflush=False, yield_per=100)
        )
        if operation_key is None:
            query = query.where(PreparationVersion.kind == "manufacturing_baseline")
        else:
            query = query.where(
                PreparationVersion.operation_key == operation_key,
                PreparationVersion.kind.in_(("work_instruction", "control_plan")),
            )
        rows = self.s.scalars(query).all()
        return rows

    def _current_runs(self, build_id):
        """Discover exact current versions; explicit historical Refs stay fixed."""
        from pdos_next.domain.verification_launch.models import (
            VerificationRunCurrent,
            VerificationRunVersion,
        )

        rows = self.s.scalars(
            select(VerificationRunVersion)
            .join(
                VerificationRunCurrent,
                and_(
                    VerificationRunCurrent.tenant_id == VerificationRunVersion.tenant_id,
                    VerificationRunCurrent.product_id == VerificationRunVersion.product_id,
                    VerificationRunCurrent.request_id == VerificationRunVersion.request_id,
                    VerificationRunCurrent.run_id == VerificationRunVersion.run_id,
                    VerificationRunCurrent.run_version_id == VerificationRunVersion.id,
                    VerificationRunCurrent.run_revision == VerificationRunVersion.revision,
                ),
            )
            .where(
                VerificationRunVersion.tenant_id == self.ctx.tenant_id,
                VerificationRunVersion.product_id == self.pid,
                VerificationRunVersion.build_id == build_id,
            )
            .order_by(VerificationRunVersion.id)
            .execution_options(populate_existing=True, autoflush=False, yield_per=100)
        ).all()
        return rows

    def links(self, obj):
        """Only relations present in actual fixed owner columns/fields are emitted."""
        from pdos_next.domain.build_execution.models import SampleUnit
        from pdos_next.domain.builds.models import Build
        from pdos_next.domain.configurations.models import (
            BomLine,
            EngineeringConfiguration,
            ProcessRevision,
        )

        ref, v, links = obj.ref, obj.view, []

        def add(kind, identity, revision, relation, key=None):
            links.append((Ref(id=identity, revision=revision, kind=kind, key=key), relation))

        if ref.kind == "field_feedback":
            from .field_bridge import configuration_refs

            links.extend(
                (configuration, "现场反馈固定定位配置") for configuration in configuration_refs(v)
            )
        elif ref.kind in {"issue", "capa"}:
            for failure in v["failures"]:
                for kind, value in (
                    ("build", failure["build"]),
                    ("sample", failure["sample"]),
                    ("test_run", failure["run"]),
                ):
                    add(kind, value["id"], value["revision"], "固定失败引用")
        elif ref.kind == "engineering_configuration":
            add("spec", v["definition_id"], v["definition_revision"], "固定工程定义")
            add("bom", v["bom_id"], v["bom_revision"], "固定工程BOM")
            for row in self._query(
                ProcessRevision, ProcessRevision.engineering_configuration_id == ref.id
            ):
                add("manufacturing_configuration", row.id, row.revision, "制造版固定工程版")
            for row in self._query(Build, Build.engineering_configuration_id == ref.id):
                add("build", row.id, row.revision, "Build固定工程版")
        elif ref.kind == "spec":
            for row in self._query(
                EngineeringConfiguration, EngineeringConfiguration.definition_id == ref.id
            ):
                add("engineering_configuration", row.id, row.revision, "工程版固定定义")
        elif ref.kind == "bom":
            for line in v["lines"]:
                if ref.key is None or ref.key == line["key"]:
                    add(
                        "part", line["part_id"], line["expected_part_revision"], "固定BOM行物料身份"
                    )
            for row in self._query(
                EngineeringConfiguration, EngineeringConfiguration.bom_id == ref.id
            ):
                add("engineering_configuration", row.id, row.revision, "工程版固定BOM")
        elif ref.kind == "part":
            boms, line_keys = {}, {}
            for line in self._query(
                BomLine, BomLine.part_id == ref.id, BomLine.part_revision == ref.revision
            ):
                from pdos_next.domain.configurations.models import BomRevision

                if line.bom_id not in boms:
                    boms[line.bom_id] = _row(
                        self.s, self.ctx, self.pid, BomRevision, line.bom_id
                    )
                bom = boms[line.bom_id]
                line_keys.setdefault(bom.id, set()).add(line.key)
                add("bom", bom.id, bom.revision, "固定BOM行引用物料", line.key)
            # Line keys are local to a fixed BOM, not global Part/Operation names.
            # Preserve immutable historical bindings rather than choosing a newer
            # configuration. Capturing each discovered target still uses its real
            # owner/currentness/ACL and original source checks in resolve().
            for bom_id, keys in line_keys.items():
                for engineering in self._query(
                    EngineeringConfiguration,
                    EngineeringConfiguration.bom_id == bom_id,
                    EngineeringConfiguration.bom_revision == boms[bom_id].revision,
                ):
                    for process in self._query(
                        ProcessRevision,
                        ProcessRevision.engineering_configuration_id == engineering.id,
                        ProcessRevision.engineering_revision == engineering.revision,
                    ):
                        for operation in process.operations:
                            if keys.intersection(operation["bom_line_keys"]):
                                add(
                                    "operation",
                                    process.id,
                                    process.revision,
                                    "工序明确使用固定BOM物料行",
                                    operation["key"],
                                )
        elif ref.kind == "manufacturing_configuration":
            add(
                "engineering_configuration",
                v["engineering_configuration_id"],
                v["engineering_revision"],
                "固定工程版",
            )
            for op in v["operations"]:
                add("operation", ref.id, ref.revision, "制造版声明固定工序", op["key"])
            for row in self._current_preparations(ref.id, ref.revision):
                add(row.kind, row.id, row.revision, "制造版当前固定准备基线")
        elif ref.kind == "operation":
            op = v["selected_operation"]
            if op.get("sop"):
                add("sop", ref.id, ref.revision, "工序固定SOP引用字段", ref.key)
            for row in self._current_preparations(ref.id, ref.revision, operation_key=ref.key):
                add(row.kind, row.id, row.revision, "工序当前固定准备文档")
            eng = self.resolve(
                Ref(
                    id=v["engineering_configuration_id"],
                    revision=v["engineering_revision"],
                    kind="engineering_configuration",
                )
            )
            for key in op["bom_line_keys"]:
                add("bom", eng.view["bom_id"], eng.view["bom_revision"], "工序声明固定BOM行", key)
        elif ref.kind in {"work_instruction", "control_plan", "manufacturing_baseline"}:
            process = v["process"]
            add("manufacturing_configuration", process["id"], process["revision"], "文档固定制造版")
            if ref.kind == "manufacturing_baseline":
                for item in v["body"]["input"]["operations"]:
                    for kind in ("work_instruction", "control_plan"):
                        if child := item.get(kind):
                            add(kind, child["id"], child["revision"], "基线固定子文档")
            else:
                add(
                    "operation",
                    process["id"],
                    process["revision"],
                    "文档固定工序",
                    v["operation_key"],
                )
        elif ref.kind == "build":
            for kind, value in (
                ("engineering_configuration", v["engineering"]),
                ("manufacturing_configuration", v["manufacturing"]),
            ):
                add(kind, value["id"], value["revision"], "Build固定计划配置")
            for row in self._query(SampleUnit, SampleUnit.build_id == ref.id):
                add("sample", row.id, row.revision, "已发生批次产生样件身份")
            for row in self._current_runs(ref.id):
                add("test_run", row.run_id, row.revision, "捕获时当前指针的固定Run版本")
        elif ref.kind == "sample":
            for row in self._current_runs(UUID(str(v["build_id"]))):
                if any(str(value["id"]) == str(ref.id) for value in row.run_snapshot["samples"]):
                    add("test_run", row.run_id, row.revision, "固定Run使用该样件")
        return tuple({(r.identity, relation): (r, relation) for r, relation in links}.values())


def capture_graph(
    reader, *, identity, roots, captured_at: datetime, expires_at: datetime | None, nature, sources
):
    pending, nodes, edges = list(roots), {}, {}
    while pending:
        ref = pending.pop(0)
        if ref.identity in nodes:
            continue
        obj = reader.resolve(ref)
        if not obj.current:
            if obj.view.get("owner_port") == "plan_not_integrated":
                raise DomainError(
                    "RECHECK_REQUIRED",
                    "当前Run尚未开测，计划所有者来源端口未接入；不能补造执行证明。",
                )
            raise DomainError("RECHECK_REQUIRED", "图中的固定来源或执行证明待重核。")
        nodes[ref.identity] = Node(
            ref=ref, scope=reader.scope, audience=reader.target, source=obj.source, label=obj.label
        )
        for target, relation in reader.links(obj):
            # Unreadable discovered dependencies remain UNKNOWN without exposing
            # their identity. Explicit user-selected roots/references always reject.
            try:
                reader.resolve(target)
            except DomainError as error:
                if error.status == 403:
                    continue
                raise
            edge_id = f"edge-{len(edges) + 1}"
            key = (ref.identity, target.identity, relation)
            if key not in edges:
                edges[key] = Edge(
                    id=edge_id, origin=ref, target=target, source=obj.source, relation=relation
                )
                pending.append(target)
    coverage = tuple(
        Coverage(node=node.ref, facet=facet, status="unknown", reason=UNKNOWN_REASONS[facet])
        for node in nodes.values()
        for facet in get_args(Facet)
    )
    return GraphSnapshot(
        id=identity,
        revision=1,
        scope=reader.scope,
        audience=reader.target,
        roots=roots,
        nodes=tuple(nodes.values()),
        edges=tuple(edges.values()),
        coverage=coverage,
        sources=sources,
        captured_at=captured_at,
        expires_at=expires_at,
        nature=nature,
    )
