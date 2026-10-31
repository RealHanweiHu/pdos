"""Frozen historical dependencies, checked in batches without replaying READs.

Only persisted server READ results supply identities. The manifest is a list of
dependencies, never an ACL copy: every send checks ordinary current RLS again.
Content/version movement annotates the next history view, not the frozen view.
"""

from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID

from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONPATH

from pdos_next.errors import DomainError
from pdos_next.service import digest

VERSION = "conversation-access/v1"
ASSISTANT = frozenset({
    "assistant.search", "assistant.materials.read", "assistant.extract",
    "assistant.citations.read", "assistant.compare", "assistant.passage.read",
    "assistant.comparison.read",
})
CATEGORY = frozenset({"category.read", "category.list", "category.knowledge.list",
                      "category.competitors.list", "category.parameters.list"})
OBJECTS = frozenset({"proposal.read", "proposal.items.read", "product.baseline.read",
                     "platform.read", "calc.spec_compare", "calc.derivation_diff"})
PROJECT = {"build.read": "build", "build.lot.read": "lot", "build.sample.read": "sample",
           "quality.issue.read": "issue_version", "test.run.read": "test_version"}
EVIDENCE = frozenset({"evidence.search", "evidence.extract", "evidence.artifact.read"})
RESEARCH = frozenset({"research.search", "research.read", "research.fanout"})
MCP = frozenset({"mcp.tools.list", "mcp.read", "mcp.result.read"})
PURE = frozenset({"calc.cost_subtotal", "calc.market_size", "calc.opportunity_score",
                  "calc.price_band"})
OTHER = frozenset({"conversation.history", "result.read", "skill.load"})
READ_TOOLS = (ASSISTANT | CATEGORY | OBJECTS | PROJECT.keys() | EVIDENCE
              | RESEARCH | MCP | PURE | OTHER)

# Explicit metadata projections. No table name or selected field comes from a
# model, a document, a stored Reference, or a browser request.
TABLES = {
    "category": "categories", "product": "products", "proposal": "proposals",
    "proposal_item": "proposal_items", "definition": "definition_revisions",
    "variant": "product_variants", "knowledge": "category_knowledge_entries",
    "parameter": "parameter_versions", "artifact": "artifact_versions", "claim": "claims",
    "snapshot": "public_web_snapshots", "original": "uploaded_originals",
    "platform": "platforms", "platform_link": "platform_product_links",
    "configuration": "engineering_configurations", "bom": "bom_revisions",
    "bom_line": "bom_lines", "part": "parts", "build": "builds",
    "lot": "build_lots", "sample": "sample_units", "issue_version": "quality_issue_versions",
    "test_version": "verification_run_versions", "project": "projects",
    "receipt": "action_receipts", "run": "agent_runs", "connector": "mcp_connectors",
    "mcp_grant": "mcp_tool_grants",
    "plan": "plan_revisions", "plan_task": "project_tasks",
    "work_task": "work_task_versions", "work_commitment": "work_commitment_versions",
    "project_status_update": "project_status_updates", "project_open_item": "project_open_items",
    "project_governance": "project_governance_events", "release_package": "release_packages",
    "release_decision": "release_decisions", "release_exception": "release_exception_decisions",
}
PROJECT_REFERENCES = frozenset({
    "project", "plan", "plan_task", "work_task", "work_commitment", "project_status_update",
    "project_open_item", "project_governance", "release_package", "release_decision",
    "release_exception", "definition",
})
REFERENCE_KINDS = {"artifact": "artifact", "original": "artifact", "claim": "claim",
                   "knowledge": "knowledge", "parameter": "parameter",
                   "definition": "definition", "snapshot": "snapshot"}


def _id(value):
    return str(UUID(str(value)))


def dependency(kind, identity, version=None):
    value = {"kind": kind, "id": _id(identity)}
    if type(version) is int:
        value["version"] = version
    return value


def _references(value):
    """Registered internal domain projections only; never external MCP JSON."""
    if isinstance(value, list):
        for child in value:
            yield from _references(child)
    elif isinstance(value, dict):
        if {"type", "id", "version"} <= value.keys() and value["type"] in REFERENCE_KINDS:
            yield dependency(REFERENCE_KINDS[value["type"]], value["id"], value["version"])
        elif {"artifact_id", "expected_revision"} <= value.keys():
            yield dependency("artifact", value["artifact_id"], value["expected_revision"])
        if value.get("parameter_id") and value.get("parameter_version"):
            yield dependency("parameter", value["parameter_id"], value["parameter_version"])
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _references(child)


def project_context(binding, run):
    """Only a carried server-owned project projection can add these dependencies."""
    if not isinstance(binding, dict) or binding.get("kind") not in {
        "project-current-facts/v1", "project-current-facts/v2",
    }:
        raise ValueError("Unknown retained project context")
    for key in ("tenant_id", "category_id", "product_id", "project_id", "requester_id"):
        if binding.get(key) != str(getattr(run, key)):
            raise ValueError("Project context does not belong to the retained Run")
    deps = [dependency("project", binding["project_id"]),
            dependency("product", binding["product_id"])]
    for ref in binding.get("source_proof", []):
        source = dependency("artifact", ref["artifact_id"], ref["expected_revision"])
        if ref.get("content_hash"):
            source["content_hash"] = ref["content_hash"]
        deps.append(source)
    for ref in binding.get("references", []):
        if ref.get("kind") not in PROJECT_REFERENCES:
            raise ValueError("Unregistered project reference")
        # PlanTask itself has no revision column; its fixed PlanRevision is
        # independently referenced. Do not invent a task revision from its plan.
        deps.append(dependency(ref["kind"], ref["id"],
                               None if ref["kind"] == "plan_task" else ref.get("revision")))
        if ref.get("receipt_id"):
            deps.append(dependency("receipt", ref["receipt_id"]))
    snapshot = binding.get("metadata_snapshot")
    context = None
    if binding["kind"] == "project-current-facts/v2" and not isinstance(snapshot, dict):
        raise ValueError("Missing retained project pointer snapshot")
    if snapshot is not None:
        if snapshot.get("version") != "project-current-metadata/v1":
            raise ValueError("Unknown retained project pointer snapshot")
        for key in ("tasks", "task_commitments"):
            if (not isinstance(snapshot.get(key), dict)
                    or not isinstance(snapshot[key].get("items"), list)
                    or type(snapshot[key].get("has_more")) is not bool):
                raise ValueError("Incomplete retained project pointer snapshot")
        if not {"project_revision", "current_plan_id"} <= snapshot.keys():
            raise ValueError("Missing retained project pointer")
        context = {"project_id": binding["project_id"], "metadata_snapshot": deepcopy(snapshot)}
    return deps, context


def _object_dependencies(name, args, value):
    for field, kind in (("product_id", "product"), ("proposal_id", "proposal"),
                        ("variant_id", "variant"), ("definition_id", "definition")):
        if args.get(field):
            yield dependency(kind, args[field], args.get("definition_revision")
                             if kind == "definition" else None)
    if name == "calc.spec_compare":
        for subject in value.get("subjects", []):
            if subject.get("type") in {"product", "proposal", "competitor"}:
                kind = "knowledge" if subject["type"] == "competitor" else subject["type"]
                yield dependency(kind, subject["id"],
                                 subject.get("revision", subject.get("version")))
            if subject.get("definition_id"):
                yield dependency("definition", subject["definition_id"],
                                 subject.get("definition_revision"))
            if subject.get("baseline_definition_id"):
                yield dependency("definition", subject["baseline_definition_id"],
                                 subject.get("baseline_definition_revision"))
    # Typed comparison selectors contain several independently readable objects.
    for field in ("subjects", "baseline", "proposed", "three_way"):
        nested = args.get(field)
        stack = nested if isinstance(nested, list) else [nested]
        for node in stack:
            if not isinstance(node, dict):
                continue
            if field == "three_way":
                stack.extend(child for child in node.values() if isinstance(child, dict))
            for key, kind in (("product_id", "product"), ("proposal_id", "proposal"),
                              ("variant_id", "variant"), ("definition_id", "definition")):
                if node.get(key):
                    yield dependency(kind, node[key], node.get("definition_revision"))
            if node.get("type") in {"product", "proposal", "competitor"} and node.get("id"):
                yield dependency("knowledge" if node["type"] == "competitor" else node["type"],
                                 node["id"], node.get("revision"))
    if name == "proposal.read":
        yield dependency("proposal", value.get("id", args["proposal_id"]), value.get("revision"))
    if name.startswith("proposal."):
        for item in value.get("items", []):
            if item.get("item_id"):
                yield dependency("proposal_item", item["item_id"], item.get("version"))
    if name == "platform.read":
        for item in value.get("items", []):
            yield dependency("platform", item["id"])
            for link in item.get("links", []):
                yield dependency("platform_link", link["id"], link.get("version"))
                yield dependency("product", link["product_id"])
                if link.get("variant_id"):
                    yield dependency("variant", link["variant_id"])
    if name == "product.baseline.read":
        definition = value.get("definition")
        if definition:
            yield dependency("definition", definition["id"], definition.get("revision"))
        # Native block DTOs have fixed configuration/BOM/part identity fields.
        def blocks(node):
            if isinstance(node, list):
                for child in node:
                    yield from blocks(child)
            elif isinstance(node, dict):
                if isinstance(node.get("configuration"), dict):
                    config = node["configuration"]
                    yield dependency("configuration", config["id"], config.get("revision"))
                for field, kind in (("configuration_id", "configuration"), ("bom_id", "bom"),
                                    ("part_id", "part"), ("bom_line_id", "bom_line")):
                    if node.get(field):
                        yield dependency(kind, node[field])
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        yield from blocks(child)
        yield from blocks(value.get("blocks", {}))
    yield from _references(value)


def collect_call(name, args, value, run):
    """Return exact known dependencies; unknown tools are explicitly unverified."""
    deps, citations, unverified = [], [], name not in READ_TOOLS
    if not isinstance(value, dict):
        return deps, citations, True
    if name in ASSISTANT:
        # Search/materials issue complete fixed metadata rows. Other assistant
        # results refer to those CIDs; all root calls are collected together.
        for item in value.get("items", []):
            if (isinstance(item, dict)
                    and {"source_type", "source_id", "citation_id"} <= item.keys()):
                citations.append(deepcopy(item))
    elif name in CATEGORY:
        if name in {"category.read", "category.list"}:
            for item in value.get("items", [value]):
                deps.append(dependency("category", item["id"], item.get("revision")))
        elif name == "category.parameters.list":
            deps.extend(dependency("parameter", item["parameter_id"], item["version"])
                        for item in value.get("items", []))
        else:
            deps.extend(dependency("knowledge", item["id"], item.get("version"))
                        for item in value.get("items", []))
            deps.extend(_references(value))
    elif name in OBJECTS:
        deps.extend(_object_dependencies(name, args, value))
    elif name in PROJECT:
        for item in value.get("items", []):
            deps.append(dependency(PROJECT[name], item.get("version_id", item["id"]),
                                   item.get("revision")))
            for field, kind in (("project_id", "project"), ("build_id", "build"),
                                ("lot_id", "lot")):
                if item.get(field):
                    deps.append(dependency(kind, item[field]))
    elif name in EVIDENCE:
        deps.extend(_references(run.read_sources))
        if name == "evidence.search":
            deps.extend(dependency("artifact", item["artifact_id"], item.get("revision"))
                        for item in value.get("items", []))
    elif name in MCP:
        if name == "mcp.read" and args.get("connector_id"):
            deps.append(dependency("connector", args["connector_id"]))
        items = value.get("tools", []) if name == "mcp.tools.list" else [value]
        for item in items:
            if item.get("connector_id"):
                deps.append(dependency("connector", item["connector_id"],
                                       item.get("connector_revision")))
            for identity in item.get("grant_ids", []):
                deps.append(dependency("mcp_grant", identity,
                                       item.get("grant_versions", {}).get(identity)))
            if item.get("grant_id"):
                deps.append(dependency("mcp_grant", item["grant_id"], item.get("grant_revision")))
    elif name in RESEARCH:
        # Private snapshots live under this exact originating Run; published
        # snapshots are separately captured from registered child read bindings.
        deps.append(dependency("run", run.id))
    elif name in PURE:
        # References in pure arithmetic are model inputs, not issued provenance.
        # Their actual READs are collected independently; do not mint new roots.
        pass
    return deps, citations, unverified


def _columns(kind, table):
    names = {"id", "tenant_id", "category_id", "product_id", "project_id", "owner_id",
             "revision", "version", "current_version", "status", "action", "reverted_at",
             "original_id", "scan_status", "active", "expires_at", "parameter_id"}
    # Actual persisted source edges are metadata, not business body projections.
    if kind in {"knowledge", "claim"}:
        names |= {"source_refs", "source_kind", "artifact_id", "snapshot_id", "source_revision"}
    if kind == "knowledge":
        names |= {"lineage_id"}
    if kind == "artifact":
        names |= {"content_hash"}
    if kind in {"configuration", "bom", "bom_line", "part"}:
        names |= {"sources", "required_source_read_set", "external_design_refs"}
    return [column for column in table.c if column.key in names]


def metadata(session, dependencies):
    """One UNION statement over a finite set of current ordinary RLS tables."""
    from pdos_next.models import Base

    grouped = defaultdict(set)
    for item in dependencies:
        grouped[item["kind"]].add(UUID(item["id"]))
    queries = []
    for kind, identities in sorted(grouped.items()):
        table = Base.metadata.tables[TABLES[kind]]
        identity = table.c.parameter_id if kind == "parameter" else table.c.id
        pairs = [part for col in _columns(kind, table) for part in (literal(col.key), col)]
        pointers = {
            "knowledge": ("category_knowledge_current", "lineage_id", "lineage_id",
                          "current_version", "status"),
            "parameter": ("parameter_current", "parameter_id", "parameter_id",
                          "current_version", None),
            "proposal_item": ("proposal_items", "id", "id", "current_version", None),
            "work_task": ("work_task_currents", "task_id", "task_id", "revision", None),
            "work_commitment": (
                "work_commitment_currents", "series_id", "series_id", "revision", None),
        }
        if kind in pointers:
            target, own, other, revision, status = pointers[kind]
            pointer = Base.metadata.tables[target].alias("history_" + kind + "_pointer")
            condition = (pointer.c.tenant_id == table.c.tenant_id) & (
                pointer.c[other] == table.c[own])
            pairs.extend((literal("current_revision"), select(pointer.c[revision])
                          .where(condition).correlate(table).scalar_subquery()))
            if status:
                pairs.extend((literal("current_status"), select(pointer.c[status])
                              .where(condition).correlate(table).scalar_subquery()))
        queries.append(select(literal(kind).label("kind"), cast(identity, String).label("id"),
                              func.jsonb_build_object(*pairs).label("metadata")).where(
                                  identity.in_(identities)))
    if not queries:
        return {}
    queries[0] = queries[0].prefix_with("/* conversation_history_metadata */")
    rows = session.execute(union_all(*queries)).mappings().all()
    result = defaultdict(list)
    for row in rows:
        result[(row["kind"], row["id"])].append(dict(row["metadata"]))
    return result


def _available(kind, row):
    if row.get("status") in {"withdrawn", "quarantined", "deleted"}:
        return False
    if kind in {"connector", "mcp_grant"}:
        if row.get("active") is not True:
            return False
        if kind == "mcp_grant":
            from datetime import UTC, datetime
            expiry = row.get("expires_at")
            if not expiry or datetime.fromisoformat(expiry) <= datetime.now(UTC):
                return False
    if kind == "run" and row.get("reverted_at"):
        return False
    if kind == "original":
        return row.get("status") == "parsed" and row.get("scan_status") == "clean"
    if kind in {"artifact", "claim"}:
        return row.get("status") == "active"
    if kind == "snapshot":
        return row.get("status") in {"ok", "partial"}
    if kind == "knowledge" and (row.get("action") == "withdraw"
                                or row.get("current_status") == "withdrawn"):
        return False
    return True


def _expand(deps, rows):
    extra = []
    for item in deps:
        for row in rows.get((item["kind"], item["id"]), []):
            if row.get("original_id"):
                extra.append(dependency("original", row["original_id"]))
            if item["kind"] == "knowledge":
                extra.extend(_references(row.get("source_refs", [])))
            if item["kind"] in {"configuration", "bom", "bom_line", "part"}:
                for field in ("sources", "required_source_read_set", "external_design_refs"):
                    extra.extend(_references(row.get(field, [])))
            if item["kind"] == "claim":
                if row.get("source_kind") == "artifact" and row.get("artifact_id"):
                    extra.append(dependency("artifact", row["artifact_id"],
                                            row.get("source_revision")))
                if row.get("source_kind") == "snapshot" and row.get("snapshot_id"):
                    extra.append(dependency("snapshot", row["snapshot_id"], 1))
    known = {digest(item) for item in deps}
    return [item for item in extra if digest(item) not in known]


def unique(items):
    return list({digest(item): item for item in items}.values())


def definition_edges(session, deps):
    """Fixed definition source edges; never quote/spec/BOM body reconstruction."""
    from pdos_next.domain.products.models import DefinitionSource

    ids = {UUID(item["id"]) for item in deps if item["kind"] == "definition"}
    if not ids:
        return {}
    rows = session.execute(select(
        DefinitionSource.definition_id, DefinitionSource.artifact_id,
        DefinitionSource.source_revision,
    ).where(DefinitionSource.definition_id.in_(ids))).all()
    result = defaultdict(list)
    for row in rows:
        result[str(row.definition_id)].append(
            dependency("artifact", row.artifact_id, row.source_revision))
    return result


def mcp_access(session, targets):
    """Current grants and registered connector contract, with no transport/raw read.

    The credential *reference* is read only inside connector_binding; neither it,
    endpoints nor tool schema leave this function or enter the manifest/log.
    """
    from datetime import UTC, datetime

    from sqlalchemy import tuple_
    from sqlalchemy.orm import load_only

    from .mcp_binding import connector_binding
    from .models import McpConnector, McpToolGrant

    if not targets:
        return {}
    rows = session.execute(select(McpConnector, McpToolGrant).join(
        McpToolGrant, (McpToolGrant.tenant_id == McpConnector.tenant_id)
        & (McpToolGrant.connector_id == McpConnector.id),
    ).where(tuple_(McpToolGrant.connector_id, McpToolGrant.tool).in_(
        {(UUID(item["connector_id"]), item["tool"]) for item in targets}
    )).options(
        load_only(McpConnector.id, McpConnector.key, McpConnector.endpoint,
                  McpConnector.secret_ref, McpConnector.tools, McpConnector.active),
        load_only(McpToolGrant.id, McpToolGrant.connector_id, McpToolGrant.tool,
                  McpToolGrant.active, McpToolGrant.expires_at, McpToolGrant.skill_key,
                  McpToolGrant.connector_binding_digest),
    )).all()
    valid = defaultdict(set)
    for connector, grant in rows:
        if (connector.active and grant.active and grant.expires_at > datetime.now(UTC)
                and grant.connector_binding_digest == connector_binding(connector, grant.tool)):
            valid[(str(connector.id), grant.tool)].add((str(grant.id), grant.skill_key))
    result = {}
    for item in targets:
        current = valid[(item["connector_id"], item["tool"])]
        expected = set(item.get("grant_ids", []))
        result[digest(item)] = bool(
            expected <= {identity for identity, _key in current} if expected else
            any(key in item.get("skill_keys", []) for _identity, key in current)
        )
    return result


@contextmanager
def owner_snapshot(session, consumer):
    """Project only for the immutable Run's actual requester; never change caller GUCs."""
    if consumer is None:
        yield session
        return
    from pdos_next.domain.preproject.access import human
    from pdos_next.enterprise_search.assistant_sources import human_snapshot
    from pdos_next.service import Context

    from .execution import check_run_binding, scope_for_run
    from .models import AgentRun

    actual = session.get(AgentRun, consumer.id)
    if actual is None:
        raise DomainError("FORBIDDEN_SCOPE", "历史上下文未绑定实际本人运行。", 403)
    bound = scope_for_run(actual)
    check_run_binding(consumer, bound, for_write=False)
    transaction_scope = session.info.get("scope")
    if not transaction_scope or transaction_scope[:3] not in {
        (actual.tenant_id, actual.writer_id, actual.requester_id),
        (actual.tenant_id, actual.requester_id, actual.requester_id),
    }:
        raise DomainError("FORBIDDEN_SCOPE", "历史上下文请求者与实际运行不一致。", 403)
    if transaction_scope[3] not in (None, actual.category_id):
        raise DomainError("FORBIDDEN_SCOPE", "历史上下文品类与实际运行不一致。", 403)
    owner = Context(actual.tenant_id, actual.requester_id, actual.requester_id,
                    category_id=actual.category_id)
    if transaction_scope[1] == actual.requester_id:
        human(session, owner)
        yield session
        return
    with human_snapshot(session.get_bind(), bound) as reading:
        retained = reading.get(AgentRun, actual.id)
        check_run_binding(retained, bound, for_write=False)
        human(reading, owner)
        yield reading


def manifests(session, runs, *, ancestors=None, consumer=None):
    with owner_snapshot(session, consumer) as reading:
        return _manifests(reading, runs, ancestors=ancestors)


def _manifests(session, runs, *, ancestors=None):
    """Build once from actual immutable ledgers, without any read adapter call."""
    from .models import AgentRun, AgentToolCall

    requested = {str(run.id) for run in runs}
    by_run = {str(run.id): run for run in (ancestors if ancestors is not None else runs)}
    result = {identity: {"version": VERSION, "run_id": identity, "dependencies": [],
                         "citations": [], "unverified": [], "prepared": False,
                         "research": [], "history_runs": [], "inherited": [], "mcp": [],
                         "projects": [], "project_dependencies": [], "project_unavailable": False}
              for identity in by_run}
    calls = session.execute(select(
        AgentToolCall.id, AgentToolCall.run_id, AgentToolCall.tool, AgentToolCall.state,
        AgentToolCall.receipt_id, AgentToolCall.execution_binding, AgentToolCall.result,
    ).where(AgentToolCall.run_id.in_([run.id for run in by_run.values()]))
    ).mappings().all() if by_run else []
    frozen = session.execute(select(
        AgentRun.id,
        AgentRun.versions["proposal_context"]["references"].label("proposal_refs"),
        AgentRun.versions["work_state"]["citations"].label("citations"),
        AgentRun.versions["work_state_access"].label("state_access"),
        AgentRun.versions["work_state_access_digest"].astext.label("state_access_digest"),
        AgentRun.versions["conversation_access"].label("history_access"),
        AgentRun.versions["project_current_context"].label("project_context"),
        func.jsonb_path_exists(AgentRun.versions["context_snapshots"], cast(literal(
            '$.*.fields[*] ? (@ == "project")'), JSONPATH)).label("project_carried"),
        func.jsonb_path_query_array(AgentRun.versions["conversation_memory"], cast(literal(
            '$.turns[*] ? (@.outcome_state != "hidden").run_id'), JSONPATH)).label("history_runs"),
    ).where(AgentRun.id.in_([run.id for run in by_run.values()]))
    ).mappings().all() if by_run else []
    for row in frozen:
        value = result[str(row["id"])]
        value["dependencies"].extend(_references(row["proposal_refs"] or []))
        value["inherited"].extend(row["citations"] or [])
        state_access = row.get("state_access") or {}
        if state_access and digest(state_access) != row.get("state_access_digest"):
            value["unavailable"] = True
        elif state_access:
            for source, carried in state_access.items():
                value["dependencies"].append(dependency("run", source))
                for key in ("dependencies", "citations", "mcp", "projects",
                            "project_dependencies"):
                    value[key].extend(deepcopy(carried.get(key, [])))
                value["project_unavailable"] |= carried.get("project_unavailable", False)
                if carried.get("unavailable"):
                    value["unavailable"] = True
        historical = row.get("history_access")
        if historical is not None:
            for origin, carried in historical.items():
                value["dependencies"].append(dependency("run", origin))
                value["dependencies"].extend(deepcopy(carried["dependencies"]))
                value["citations"].extend(deepcopy(carried["citations"]))
                value["mcp"].extend(deepcopy(carried.get("mcp", [])))
                value["projects"].extend(deepcopy(carried.get("projects", [])))
                value["project_dependencies"].extend(
                    deepcopy(carried.get("project_dependencies", [])))
                value["project_unavailable"] |= carried.get("project_unavailable", False)
                if carried.get("unavailable"):
                    value["unavailable"] = True
        else:
            # Legacy runs freeze actual visible history IDs, even when the model
            # made no READ of its own. Do not substitute all ancestors.
            value["history_runs"].extend(row.get("history_runs") or [])
    frozen_by_id = {str(row["id"]): row for row in frozen}
    project_root_cache = {}

    def project_roots(identity, seen):
        # Older frozen conversation_access did not contain project facts. Repair
        # only from the exact originating Run's retained server projection;
        # never replace frozen source roots with a new adapter/READ result.
        row = frozen_by_id.get(identity)
        if identity in seen:
            return [], [], True
        if row is None:
            return [], [], False
        if identity in project_root_cache:
            return project_root_cache[identity]
        deps, projects, unavailable = [], [], False
        if row.get("project_carried") and row.get("project_context") is not None:
            try:
                deps, context = project_context(row["project_context"], by_run[identity])
                if context:
                    projects.append(context)
            except (KeyError, TypeError, ValueError, AttributeError):
                unavailable = True
        carried = row.get("history_access")
        origins = carried.keys() if carried is not None else row.get("history_runs") or []
        for origin in origins:
            inherited_deps, inherited_projects, missing = project_roots(
                origin, seen | {identity})
            deps.extend(inherited_deps)
            projects.extend(inherited_projects)
            unavailable |= missing
        result = unique(deps), unique(projects), unavailable
        project_root_cache[identity] = result
        return result

    for identity, value in result.items():
        deps, projects, unavailable = project_roots(identity, set())
        value["dependencies"].extend(deps)
        value["projects"].extend(projects)
        value["project_dependencies"].extend(deps)
        value["project_unavailable"] |= unavailable
        if unavailable:
            value["unavailable"] = True
    models = {row["id"]: row for row in calls if row["tool"] == "model"}
    for identity, run in by_run.items():
        manifest = result[identity]
        manifest["dependencies"].extend(_references(run.read_sources))
        manifest["dependencies"].append(dependency("run", run.id))
    for call in calls:
        if call["tool"] == "model":
            continue
        manifest = result[str(call["run_id"])]
        bound, name = call["execution_binding"] or {}, call["tool"]
        if (name == "model.count_tokens" and bound.get("kind") == "unbound"
                and bound.get("dispatch") == "anthropic-count-tokens/v1"
                and isinstance(call["result"], dict) and set(call["result"]) == {"input_tokens"}
                and type(call["result"]["input_tokens"]) is int):
            from .bindings import ModelBinding

            try:
                ModelBinding.model_validate(bound["model_binding"])
                continue
            except (KeyError, ValueError, TypeError):
                pass
        if bound.get("kind") == "domain_t0":
            if call["receipt_id"]:
                manifest["dependencies"].append(dependency("receipt", call["receipt_id"]))
            else:
                manifest["unverified"].append(name)
            continue
        if bound.get("kind") == "unbound":
            if bound.get("dispatch") == "mcp-read/v1" and bound.get("parent_read_call_id"):
                # The server dispatch result carries the admitted connector and
                # exact grant set. It is never parsed from external raw JSON.
                value = call["result"] or {}
                parent = next((row for row in calls if str(row["id"]) ==
                               bound["parent_read_call_id"] and row["tool"] == "mcp.read"), None)
                if (parent is not None and value.get("call_id") == str(call["id"])
                        and value.get("connector_id") and value.get("tool")):
                    manifest["mcp"].append({"connector_id": value["connector_id"],
                        "tool": value["tool"], "grant_ids": value.get("grant_ids", [])})
                    manifest["dependencies"].append(dependency("connector", value["connector_id"]))
                    manifest["dependencies"].extend(dependency("mcp_grant", grant)
                                                    for grant in value.get("grant_ids", []))
                    continue
            from .tools import default_registry
            try:
                manifest["prepared"] |= default_registry().get(name).kind == "write"
            except DomainError:
                manifest["unverified"].append(name)
            continue
        if bound.get("kind") != "read":
            continue
        try:
            from .read_execution import ReadBinding

            binding = ReadBinding.model_validate(bound)
            model = models[binding.model_call_id]
            request = model["result"]["calls"][binding.response_index]
            origin = by_run[str(call["run_id"])]
            if (call["state"] != "completed" or model["state"] != "completed"
                    or str(binding.run_id) != str(call["run_id"])
                    or binding.tool != name
                    or model["run_id"] != call["run_id"] or request["name"] != name
                    or any(getattr(binding, field) != getattr(origin, field) for field in (
                        "tenant_id", "category_id", "requester_id", "writer_id", "session_id",
                        "product_id", "proposal_id"))):
                raise ValueError("Unproven history read")
            deps, refs, unknown = collect_call(name, request["arguments"], call["result"],
                                             by_run[str(call["run_id"])])
            manifest["dependencies"].extend(deps)
            manifest["citations"].extend(refs)
            if unknown:
                manifest["unverified"].append(name)
            if name == "mcp.read":
                actual = call["result"]
                model_binding = model["execution_binding"]
                manifest["mcp"].append({"connector_id": request["arguments"]["connector_id"],
                    "tool": request["arguments"]["tool"],
                    "grant_ids": actual.get("grant_ids", []),
                    "skill_keys": [item["key"] for item in model_binding.get("loaded_skills", [])]})
            if name == "mcp.tools.list":
                manifest["mcp"].extend({"connector_id": item["connector_id"],
                    "tool": item["tool"], "grant_ids": [item["grant_id"]]}
                    for item in call["result"].get("tools", []))
            if name == "research.read" and binding.read_kind == "registered_snapshot/v1":
                manifest["dependencies"].append(
                    dependency("snapshot", call["result"]["snapshot_id"], 1))
            if name == "conversation.history":
                manifest["history_runs"].extend(turn["run_id"] for turn in
                    call["result"].get("turns", []) if turn.get("outcome_state") != "hidden")
            if name == "assistant.citations.read":
                manifest["inherited"].extend(call["result"].get("items", []))
            if name == "research.fanout":
                value = call["result"]
                manifest["research"].append({key: deepcopy(value[key]) for key in (
                    "job_id", "status", "snapshots", "ledger", "coverage", "failures")})
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            manifest["unverified"].append(name)
            # Legacy unproven readers remain unverified, but known result roots
            # may only add restrictions. Never discard an identifiable restricted
            # Artifact/subject merely because the old binding is incomplete.
            try:
                deps, refs, _ = collect_call(name, {}, call["result"],
                                             by_run[str(call["run_id"])])
                manifest["dependencies"].extend(deps)
                manifest["citations"].extend(refs)
            except (KeyError, TypeError, ValueError):
                pass
    issued = {(identity, item["citation_id"]): item
              for identity, manifest in result.items() for item in manifest["citations"]}
    # A budget restart carries only a proven state, not the old conversation
    # lineage. Resolve its exact saved roots before classifying inherited refs;
    # a missing root without this server proof remains unavailable below.
    from .context_restart import citation_roots

    for identity, manifest in result.items():
        if any(ref.get("origin_run_id")
               and (ref["origin_run_id"], ref.get("origin_citation_id")) not in issued
               for ref in manifest["inherited"]):
            actual_run = session.get(AgentRun, UUID(identity))
            if actual_run is not None:
                issued.update(((origin, cid), item) for cid, (origin, item)
                              in citation_roots(session, actual_run).items())
    for manifest in result.values():
        for ref in manifest.pop("inherited"):
            origin = ref.get("origin_run_id")
            if origin:
                manifest["dependencies"].append(dependency("run", origin))
                actual = issued.get((origin, ref.get("origin_citation_id")))
                if actual:
                    manifest["citations"].append(deepcopy(actual))
                elif not {"source_type", "source_id", "citation_id"} <= ref.keys():
                    manifest["unavailable"] = True
        # Relation endpoints were both delivered by the issuing root search.
        # Check them independently for ongoing access: their content/version may
        # move without changing permission to the dated historical answer.
        independent = []
        for ref in manifest["citations"]:
            relation = ref.get("relation")
            if relation:
                origins = [item for item in issued.values() if all(
                    item.get(key) == relation[key] for key in
                    ("source_type", "source_id", "source_revision", "content_hash"))]
                if origins:
                    independent.append({key: value for key, value in origins[0].items()
                                        if key != "relation"})
                else:
                    manifest["unavailable"] = True
            independent.append({key: value for key, value in ref.items() if key != "relation"})
        manifest["citations"] = unique(independent)
    closed = {}

    def close(identity, seen):
        if identity in closed:
            return closed[identity]
        value = deepcopy(result[identity])
        for parent in value.pop("history_runs"):
            if parent in seen:
                value["unavailable"] = True
                continue
            value["dependencies"].append(dependency("run", parent))
            if parent not in result:
                value["unavailable"] = True
                continue
            inherited = close(parent, seen | {parent})
            value["dependencies"].extend(inherited["dependencies"])
            value["citations"].extend(inherited["citations"])
            value["mcp"].extend(inherited["mcp"])
            value["projects"].extend(inherited["projects"])
            value["project_dependencies"].extend(inherited["project_dependencies"])
            value["project_unavailable"] |= inherited["project_unavailable"]
            if inherited.get("unavailable"):
                value["unavailable"] = True
        for key in ("dependencies", "citations", "mcp", "projects", "project_dependencies"):
            value[key] = unique(value[key])
        closed[identity] = value
        return value
    result = {identity: close(identity, {identity}) for identity in requested}
    edges = definition_edges(session, [item for value in result.values()
                                      for item in value["dependencies"]])
    for value in result.values():
        value["projects"] = unique(value["projects"])
        for key in ("dependencies", "project_dependencies"):
            value[key].extend(child for item in list(value[key])
                              if item["kind"] == "definition"
                              for child in edges.get(item["id"], []))
    # Follow only actual metadata edges until a fixed point. This occurs once
    # during history assembly, not on each provider attempt. Old root IDs remain.
    all_deps = unique(item for value in result.values() for item in value["dependencies"])
    rows = metadata(session, all_deps)
    for _ in range(8):
        added = unique(_expand(all_deps, rows))
        if not added:
            break
        all_deps.extend(added)
        rows.update(metadata(session, added))
    else:
        raise DomainError("SOURCE_UNAVAILABLE", "历史资料依赖未能完整核对。")
    for manifest in result.values():
        for key in ("dependencies", "project_dependencies"):
            deps = unique(manifest[key])
            for _ in range(8):
                added = unique(_expand(deps, rows))
                if not added:
                    break
                deps.extend(added)
            manifest[key] = deps
        manifest["unverified"] = sorted(set(manifest["unverified"]))
    return result


def has_project_roots(manifest):
    return {"projects", "project_dependencies", "project_unavailable"} <= manifest.keys()


def upgrade_project_roots(frozen, rebuilt):
    """Supplement old caches only with immutable project projections.

    Existing READ/citation roots remain frozen even if a new adapter projection
    would return replacement source identities today.
    """
    value = deepcopy(frozen)
    value["projects"] = unique([*value.get("projects", []), *rebuilt["projects"]])
    value["project_dependencies"] = unique([
        *value.get("project_dependencies", []), *rebuilt["project_dependencies"]])
    value["dependencies"] = unique([
        *value["dependencies"], *value["project_dependencies"]])
    value["project_unavailable"] = (value.get("project_unavailable", False)
                                    or rebuilt["project_unavailable"])
    if value["project_unavailable"]:
        value["unavailable"] = True
    return value


def classify(session, access, *, consumer=None):
    with owner_snapshot(session, consumer) as reading:
        return _classify(reading, access)


def _classify(session, access):
    """Return per-origin state. Read body, filename, quote and raw JSON never occur here."""
    from pdos_next.enterprise_search.assistant_sources import current
    from pdos_next.enterprise_search.safety import safe_originals

    from .project_history_metadata import states as project_states

    deps = unique(item for manifest in access.values() for item in manifest["dependencies"])
    rows = metadata(session, deps)
    projects = project_states(session, unique(item for manifest in access.values()
                                              for item in manifest.get("projects", [])))
    mcp = mcp_access(session, unique(item for manifest in access.values()
                                   for item in manifest.get("mcp", [])))
    originals = {UUID(item["id"]) for item in deps if item["kind"] == "original"}
    safe = safe_originals(session, originals) if originals else set()
    citations = {str(index): item for index, item in enumerate(
        item for manifest in access.values() for item in manifest["citations"])}
    valid, missing = current(session, citations, with_body=False,
                             allow_updated=frozenset(citations)) if citations else ({}, {})
    citation_states = {digest(item): ("hidden" if key in missing else
                       "updated" if valid[key].get("updated") else "current")
                       for key, item in citations.items()}
    result = {}
    for identity, manifest in access.items():
        if manifest.get("unavailable"):
            result[identity] = "hidden"
            continue
        state = "current"
        for project in manifest.get("projects", []):
            current_state = projects[digest(project)]
            if current_state == "hidden":
                state = "hidden"
                break
            if current_state == "updated":
                state = "updated"
        if state == "hidden":
            result[identity] = state
            continue
        if any(not mcp[digest(item)] for item in manifest.get("mcp", [])):
            result[identity] = "hidden"
            continue
        for item in manifest["dependencies"]:
            candidates = rows.get((item["kind"], item["id"]), [])
            readable = [row for row in candidates if _available(item["kind"], row)]
            if item["kind"] == "original" and UUID(item["id"]) not in safe:
                readable = []
            if not readable:
                state = "hidden"
                break
            versions = {row.get("revision", row.get("version", row.get("current_version")))
                        for row in readable}
            if item.get("version") is not None and item["version"] not in versions:
                state = "updated"
            if item.get("content_hash") and item["content_hash"] not in {
                row.get("content_hash") for row in readable
            }:
                state = "updated"
            if any(row.get("current_revision") not in (None, item.get("version"))
                   for row in readable) and item.get("version") is not None:
                state = "updated"
        for ref in manifest["citations"]:
            status = citation_states[digest(ref)]
            if status == "hidden":
                state = "hidden"
                break
            if status == "updated" and state != "hidden":
                state = "updated"
        result[identity] = state
    return result
