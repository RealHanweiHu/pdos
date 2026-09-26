"""Authorized current material exposure and explicit source-version supplier attribution."""

from datetime import UTC, datetime
from decimal import localcontext
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.formal_schedule import current_plan
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError, knowledge_scope
from app.domain.material_allocations import (
    MaterialAllocationError,
    _key,
    _pools,
    _source_query,
    read_material_state,
)
from app.domain.material_coverage import CoverageSelection, calculate
from app.domain.material_schedule import latest_bindings
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest


class AttributionDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    supplier_id: UUID | None = None
    evidence_id: UUID
    reason: Text


def _latest(c: Connection, tenant: UUID, source_id: UUID) -> dict[str, Any] | None:
    t = tables.material_supplier_attributions
    row = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.supply_snapshot_id == source_id)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return _plain(dict(row)) if row else None


def _source(
    c: Connection, tenant: UUID, project: UUID, source_id: UUID, *, lock: bool = False
) -> dict[str, Any]:
    s = tables.supply_snapshots
    row = (
        c.execute(_source_query(tenant).where(s.c.project_id == project, s.c.id == source_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MaterialAllocationError("当前项目中没有所选供给原快照")
    key = _key(row)
    if lock:
        lock_pools(c, tenant, [key])
    pool = _pools(c, tenant, project, [key])[key]
    source = _plain(dict(row))
    source["document"] = metadata(document_row(c, tenant, project, row["document_id"]))
    current = bool(pool["source"] and pool["source"]["id"] == str(source_id))
    return {"source": source, "digest": digest(source), "current": current, "state": pool["state"]}


def _project_ids(c: Connection, context: AuthContext) -> Any:
    unrestricted, principals = knowledge_scope(c, context.tenant.id, context.user.id)
    p, m = tables.projects, tables.project_members
    query = select(p.c.id).where(p.c.tenant_id == context.tenant.id)
    if not unrestricted:
        query = query.where(
            p.c.id.in_(
                select(m.c.project_id).where(
                    m.c.tenant_id == context.tenant.id, m.c.user_id.in_(principals)
                )
            )
        )
    return query


def _trace(formal: dict[str, Any] | None, seeds: set[str]) -> dict[str, Any]:
    if formal is None:
        return {
            "baseline_id": None,
            "nodes": [],
            "edges": [],
            "missing_seeds": sorted(seeds),
            "truncated": False,
        }
    nodes = {str(row["schedule_node_id"]): row for row in formal["nodes"]}
    by_key = {row["node_key"]: str(row["schedule_node_id"]) for row in formal["nodes"]}
    edges = formal["plan"]["dependencies"]
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(by_key[edge["predecessor"]], []).append(by_key[edge["successor"]])
    available = sorted(set(seeds) & nodes.keys())
    reached = set(available[:300])
    queue = sorted(reached)
    for identity in queue:
        for successor in sorted(outgoing.get(identity, [])):
            if successor not in reached and len(reached) < 300:
                reached.add(successor)
                queue.append(successor)
    return _plain(
        {
            "baseline_id": formal["baseline_id"],
            "baseline_version": formal["baseline_version"],
            "missing_seeds": sorted(seeds - nodes.keys()),
            "truncated": len(available) > 300
            or any(
                child not in reached for parent in reached for child in outgoing.get(parent, [])
            ),
            "nodes": [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "node_key",
                        "node_kind",
                        "title",
                        "task_id",
                        "build_id",
                        "test_run_id",
                        "gate_id",
                        "certification_id",
                    )
                }
                for identity in queue
                for row in [nodes[identity]]
            ],
            "edges": [
                edge
                for edge in edges
                if by_key[edge["predecessor"]] in reached and by_key[edge["successor"]] in reached
            ],
        }
    )


class MaterialExposureService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def attribution(
        self, context: AuthContext, project_id: UUID, source_id: UUID
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project_id)
            observed = _source(c, context.tenant.id, project_id, source_id)
            t, s, d = tables.material_supplier_attributions, tables.suppliers, tables.documents
            history = [
                _plain(dict(row))
                for row in c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.supply_snapshot_id == source_id,
                    )
                    .order_by(t.c.version.desc())
                    .limit(20)
                ).mappings()
            ]
            try:
                BuildMaterialService._authorize(c, context, project_id, write=True)
                can_edit = True
            except KnowledgeAccessError:
                can_edit = False
            return {
                **observed,
                "history": history,
                "suppliers": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(s.c.id, s.c.code, s.c.name, s.c.status)
                        .where(s.c.tenant_id == context.tenant.id)
                        .order_by(s.c.code)
                    ).mappings()
                ],
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project_id)
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
                "can_edit": can_edit,
            }

    def attribute(
        self, context: AuthContext, project_id: UUID, source_id: UUID, command: AttributionDraft
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project_id),
                "source": str(source_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            BuildMaterialService._authorize(c, context, project_id, write=True)
            t = tables.material_supplier_attributions
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("原请求已用于不同供方关联")
                return _plain(dict(prior))
            original = _source(c, context.tenant.id, project_id, source_id, lock=True)
            latest = _latest(c, context.tenant.id, source_id)
            if (
                not original["current"]
                or original["digest"] != command.expected_digest
                or command.expected_version != (latest["version"] if latest else 0)
            ):
                raise MaterialAllocationError("供给来源或关联版本已变化，请刷新并核对当前原件")
            supplier = None
            if command.supplier_id is not None:
                s = tables.suppliers
                row = (
                    c.execute(
                        select(s).where(
                            s.c.tenant_id == context.tenant.id,
                            s.c.id == command.supplier_id,
                            s.c.status == "active",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise MaterialAllocationError("请选择本租户当前有效的实际供方")
                supplier = _plain(dict(row))
            elif latest is None or latest["supplier_id"] is None:
                raise MaterialAllocationError("没有可解除的原供方关联")
            evidence = metadata(document_row(c, context.tenant.id, project_id, command.evidence_id))
            snapshot = {
                "original": original,
                "supplier": supplier,
                "evidence": evidence,
                "previous_id": latest["id"] if latest else None,
            }
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        supply_snapshot_id=source_id,
                        version=command.expected_version + 1,
                        supplier_id=command.supplier_id,
                        evidence_id=command.evidence_id,
                        snapshot=snapshot,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=source_id,
                record_type="material_supplier",
                action="attributed" if supplier else "unlinked",
                before=latest,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))

    def list(
        self,
        context: AuthContext,
        project_id: UUID,
        *,
        material_reference: str | None = None,
        supplier_id: UUID | None = None,
        scope_project_id: UUID | None = None,
        after: UUID | None = None,
        include_finished: bool = False,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            BuildMaterialService._authorize(c, context, project_id)
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.WORK_ITEM_VIEW
            )
            r, b, p = tables.build_material_revisions, tables.build_batches, tables.projects
            newest = r.alias("newer_material_demand")
            query = (
                select(
                    r,
                    b.c.code.label("build_code"),
                    b.c.status.label("build_status"),
                    p.c.name.label("project_name"),
                )
                .join(b, (b.c.tenant_id == r.c.tenant_id) & (b.c.id == r.c.build_id))
                .join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
                .where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.project_id.in_(_project_ids(c, context)),
                    ~select(newest.c.id)
                    .where(
                        newest.c.tenant_id == r.c.tenant_id,
                        newest.c.build_id == r.c.build_id,
                        newest.c.version > r.c.version,
                    )
                    .exists(),
                )
            )
            if scope_project_id is not None:
                query = query.where(r.c.project_id == scope_project_id)
            if material_reference:
                query = query.where(
                    r.c.lines.cast(JSONB).contains([{"material_reference": material_reference}])
                )
            if not include_finished:
                query = query.where(b.c.status.in_(("planned", "in_progress")))
            if after:
                query = query.where(r.c.build_id > after)
            # Supplier filtering happens on the bounded page's actual current readable pools.
            # The cursor advances even when none of this page matches, so no source is skipped.
            page = list(c.execute(query.order_by(r.c.build_id).limit(21)).mappings())
            result = []
            formal_cache: dict[UUID, dict[str, Any] | None] = {}
            formal_errors: dict[UUID, str] = {}
            for row in page[:20]:
                pid, build_id = row["project_id"], row["build_id"]
                state = read_material_state(c, context.tenant.id, pid, build_id)
                coverage = calculate(
                    state,
                    {"node": None, "calendar": None, "times": {}, "issues": []},
                    CoverageSelection(),
                )
                materials = [
                    value
                    for value in coverage["materials"]
                    if not material_reference or value["material_reference"] == material_reference
                ]
                pools = state["pools"]
                for pool in pools:
                    pool["supplier_attribution"] = (
                        _latest(c, context.tenant.id, UUID(pool["source"]["id"]))
                        if pool["source"] and not pool["source"].get("source_grant_id")
                        else None
                    )
                if supplier_id:
                    matched = {
                        (pool["source"]["external_item_id"], pool["source"]["unit"])
                        for pool in pools
                        if pool["source"]
                        and pool["supplier_attribution"]
                        and pool["supplier_attribution"]["supplier_id"] == str(supplier_id)
                    }
                    materials = [
                        value
                        for value in materials
                        if (value["material_reference"], value["unit"]) in matched
                    ]
                if not materials:
                    continue
                selected_keys = {value["material_key"] for value in materials}
                references = {value["material_reference"] for value in materials}
                e, i = tables.material_exceptions, tables.issues
                issues = [
                    _plain(dict(item))
                    for item in c.execute(
                        select(
                            e.c.id.label("exception_id"),
                            e.c.material_key,
                            i.c.id,
                            i.c.title,
                            i.c.status,
                            i.c.owner_user_id,
                            i.c.target_date,
                        )
                        .join(i, (i.c.tenant_id == e.c.tenant_id) & (i.c.id == e.c.issue_id))
                        .where(
                            e.c.tenant_id == context.tenant.id,
                            e.c.project_id == pid,
                            e.c.build_id == build_id,
                            e.c.material_key.in_(selected_keys),
                        )
                        .order_by(e.c.id)
                    ).mappings()
                ]
                exception_ids = {item["exception_id"] for item in issues}
                bindings = [
                    value
                    for value in latest_bindings(c, context.tenant.id, pid)
                    if str(value["exception_id"]) in exception_ids and value["mode"] != "released"
                ]
                seeds = {str(row["need_by_node_id"])} | {
                    value for binding in bindings for value in binding["node_ids"]
                }
                if pid not in formal_cache:
                    try:
                        formal_cache[pid] = current_plan(c, context.tenant.id, pid)
                    except ProductWorkError as error:
                        formal_cache[pid] = None
                        formal_errors[pid] = str(error)
                trace = _trace(formal_cache[pid], seeds)
                trace["unavailable_reason"] = formal_errors.get(pid)
                tr = tables.test_runs
                test_ids = [
                    UUID(node["test_run_id"]) for node in trace["nodes"] if node["test_run_id"]
                ]
                cases = (
                    {
                        str(item["id"]): str(item["test_case_id"])
                        for item in c.execute(
                            select(tr.c.id, tr.c.test_case_id).where(
                                tr.c.tenant_id == context.tenant.id,
                                tr.c.project_id == pid,
                                tr.c.id.in_(test_ids),
                            )
                        ).mappings()
                    }
                    if test_ids
                    else {}
                )
                for node in trace["nodes"]:
                    node["test_case_id"] = cases.get(node["test_run_id"])

                ap, g = tables.material_admission_policies, tables.gates
                ap_new = ap.alias("newer_admission")
                gates = [
                    _plain(dict(item))
                    for item in c.execute(
                        select(
                            g.c.id,
                            g.c.name,
                            g.c.status,
                            ap.c.id.label("policy_id"),
                            ap.c.version,
                            ap.c.configuration,
                        )
                        .select_from(ap)
                        .join(g, (g.c.tenant_id == ap.c.tenant_id) & (g.c.id == ap.c.target_id))
                        .where(
                            ap.c.tenant_id == context.tenant.id,
                            ap.c.project_id == pid,
                            ap.c.target_kind == "gate",
                            ap.c.configuration["build_ids"].cast(JSONB).contains([str(build_id)]),
                            ~select(ap_new.c.id)
                            .where(
                                ap_new.c.tenant_id == ap.c.tenant_id,
                                ap_new.c.target_kind == ap.c.target_kind,
                                ap_new.c.target_id == ap.c.target_id,
                                ap_new.c.version > ap.c.version,
                            )
                            .exists(),
                        )
                        .order_by(g.c.id)
                    ).mappings()
                ]
                result.append(
                    {
                        "project": {"id": str(pid), "name": row["project_name"]},
                        "build": state["build"],
                        "revision": {
                            "id": str(row["id"]),
                            "version": row["version"],
                            "digest": row["content_digest"],
                        },
                        "materials": materials,
                        "pools": [pool for pool in pools if pool["pool_key"][2] in references],
                        "issues": issues,
                        "bindings": [_plain(binding) for binding in bindings],
                        "trace": trace,
                        "gates": gates,
                        "pool_limit_reached": state["pool_limit_reached"],
                    }
                )
            return {
                "items": result,
                "next_cursor": str(page[19]["build_id"]) if len(page) > 20 else None,
                "scanned_builds": min(len(page), 20),
                "as_of": datetime.now(UTC).isoformat(),
                "scope": "current_authorized_projects",
                "suppliers": [
                    _plain(dict(value))
                    for value in c.execute(
                        select(
                            tables.suppliers.c.id, tables.suppliers.c.code, tables.suppliers.c.name
                        )
                        .where(tables.suppliers.c.tenant_id == context.tenant.id)
                        .order_by(tables.suppliers.c.code)
                    ).mappings()
                ],
                "material_reference": material_reference,
                "supplier_id": str(supplier_id) if supplier_id else None,
                "projects": [
                    _plain(dict(value))
                    for value in c.execute(
                        select(p.c.id, p.c.name)
                        .where(
                            p.c.tenant_id == context.tenant.id, p.c.id.in_(_project_ids(c, context))
                        )
                        .order_by(p.c.name)
                        .limit(200)
                    ).mappings()
                ],
            }
