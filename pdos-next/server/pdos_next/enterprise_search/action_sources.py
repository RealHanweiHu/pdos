"""Carry checked discussion sources into verification candidates, under ordinary RLS.

These functions take locating IDs, never caller-supplied audience facts. They do
not grant applicability, qualification, confirmation or execution authority.
Persist their JSON only in the server's candidate ledger and recheck it at every
candidate read/preview/confirmation. A digest is an integrity check, not a grant.
"""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.domain.builds.service import _build, _linked
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.supply_execution.service import _human, _sources
from pdos_next.domain.verification_execution.service import _row as preparation_row
from pdos_next.domain.verification_execution.service import _snapshot as preparation_snapshot
from pdos_next.errors import DomainError
from pdos_next.models import Base, ObjectAudience
from pdos_next.service import digest, require_access

from . import assistant_ledger as ledger
from .assistant_sources import current

SOURCE_TABLES = {
    "artifact": "artifact_versions",
    "knowledge": ("category_knowledge_entries", "knowledge_rule_versions"),
    "issue": "quality_issue_versions",
    "capa": "quality_issue_versions",
    "change": "change_request_versions",
    "external_wait": "external_wait_versions",
    "supply": "supply_snapshots",
    "build": ("builds", "build_starts", "actual_configurations", "build_lots"),
    "test_run": ("verification_run_versions", "test_result_actions"),
    "field_feedback": ("field_feedback_versions", "field_response_records"),
    "project_status": "project_status_updates",
    "manufacturing_document": (
        "manufacturing_preparation_versions",
        "manufacturing_publication_documents",
    ),
    "verification_handoff": "verification_handoff_facts",
}


def _deny(reason, message="所选来源不能带入当前复验准备。"):
    raise DomainError(
        "FORBIDDEN_SCOPE", message, 403, detail={"reason_key": "assistant_action_" + reason}
    )


def _run(session, ctx, run):
    actual = session.get(AgentRun, run.id)
    if (
        actual is None
        or actual.tenant_id != ctx.tenant_id
        or actual.requester_id != ctx.requester_id
        or actual.category_id != ctx.category_id
        or actual.reverted_at is not None
        or actual.state not in {"queued", "running", "waiting_input", "completed", "partial"}
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or ctx.agent_run_id is not None
    ):
        _deny("run_invalid")
    return actual


def _target(session, ctx, run, product_id, build_id, references, preparation_id):
    product_id, build_id = UUID(str(product_id)), UUID(str(build_id))
    if run.product_id != product_id:
        _deny("target_scope_invalid")
    _human(session, ctx, product_id)
    product = require_access(session, ctx, product_id, write=True)
    build = _build(session, ctx, product_id, build_id)
    _project, _engineering, _manufacturing, planned = _linked(
        session, ctx, product_id, build, new_consumption=True
    )
    if run.project_id is not None and run.project_id != build.project_id:
        _deny("target_scope_invalid")
    previous = (
        preparation_row(session, ctx, product_id, UUID(str(preparation_id)))[0]
        if preparation_id is not None
        else None
    )
    if previous is not None and (
        previous.build_id != build.id
        or previous.visibility == "private"
        and previous.owner_id != ctx.requester_id
    ):
        _deny("target_owner_invalid")
    if previous is not None:
        preparation_snapshot(previous)
        if previous.build_revision != build.revision or previous.sources != references:
            raise DomainError("SOURCE_CHANGED", "固定准备的Build或完整来源引用与候选不一致。")
    reads = _merge_reads(planned, references, previous.required_source_read_set if previous else [])
    _values, private = _sources(session, ctx, product_id, reads, references)
    visibility = (
        previous.visibility
        if previous
        else "private"
        if build.visibility == "private" or private
        else "category"
    )
    if visibility not in {"private", "category"}:
        _deny("target_audience_unsupported")
    value = {
        "tenant_id": str(ctx.tenant_id),
        "category_id": str(product.category_id),
        "product_id": str(product.id),
        "project_id": str(build.project_id),
        "build_id": str(build.id),
        "build_revision": build.revision,
        "owner_id": str(previous.owner_id if previous else ctx.requester_id),
        "visibility": visibility,
        "preparation_id": str(previous.id) if previous else None,
        "preparation_revision": previous.revision if previous else None,
        "preparation_sha256": previous.snapshot_sha256 if previous else None,
    }
    return value, reads


def _audience_roots(session, ctx, table_name, identity, seen=None, *, optional=False):
    """Use actual flattened domain audience dependencies, without an ACL cache.

    The DB-maintained dependencies are the same fixed parents ordinary business
    RLS checks. Equal restricted parents imply equal restrictions; a private
    output for this requester is already bounded by the current source read.
    """
    seen = set() if seen is None else seen
    key = (table_name, UUID(str(identity)))
    if key in seen:
        return set()
    seen.add(key)
    table = Base.metadata.tables[table_name]
    names = {
        "id",
        "tenant_id",
        "category_id",
        "owner_id",
        "visibility",
        "privacy",
        "product_id",
        "project_id",
        "original_id",
        "audience_dependencies",
        "required_source_read_set",
        "reads",
        "source_refs",
        "source_kind",
        "artifact_id",
        "snapshot_id",
    }
    from .role_native_audience import BASIS_TABLES, PARENT_FIELDS

    if table_name in SOURCE_TABLES["field_feedback"] or table_name in BASIS_TABLES:
        names.add("source_basis")
    names.update(field for field, _table in PARENT_FIELDS.get(table_name, ()))
    row = (
        session.execute(
            select(*(col for col in table.c if col.key in names)).where(
                table.c.tenant_id == ctx.tenant_id, table.c.id == key[1]
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None and optional:
        return None
    if row is None or row["category_id"] != ctx.category_id:
        _deny("audience_unavailable")
    roots = set()
    if row.get("visibility", "category") != "category" or row.get("privacy") == "private":
        roots.add((table_name, str(row["id"]), str(row.get("owner_id"))))
    parents = [(ref["type"], ref["id"]) for ref in row.get("audience_dependencies", [])]
    parents.extend(
        (name, row[field])
        for field, name in (
            ("product_id", "products"),
            ("project_id", "projects"),
            ("original_id", "uploaded_originals"),
        )
        if row.get(field) is not None
    )
    parents.extend(
        ("artifact_versions", ref["artifact_id"])
        for ref in row.get("required_source_read_set", row.get("reads", []))
    )
    parents.extend(
        (parent_table, row[field])
        for field, parent_table in PARENT_FIELDS.get(table_name, ())
        if row.get(field) is not None
    )
    if table_name in SOURCE_TABLES["field_feedback"] or table_name in BASIS_TABLES:
        parents.extend(
            ("artifact_versions", ref["id"])
            for ref in row.get("source_basis", {}).get("artifacts", [])
        )
    for ref in row.get("source_refs", []):
        name = {
            "artifact": "artifact_versions",
            "original": "artifact_versions",
            "claim": "claims",
            "snapshot": "public_web_snapshots",
        }.get(ref["type"])
        if name:
            parents.append((name, ref["id"]))
    if row.get("source_kind") in {"artifact", "snapshot"}:
        field, name = (
            ("artifact_id", "artifact_versions")
            if row["source_kind"] == "artifact"
            else ("snapshot_id", "public_web_snapshots")
        )
        parents.append((name, row[field]))
    for name, parent in parents:
        roots |= _audience_roots(session, ctx, name, parent, seen)
    return roots


def _source_roots(session, ctx, source_type, identity):
    names = SOURCE_TABLES[source_type]
    for name in (names,) if isinstance(names, str) else names:
        roots = _audience_roots(session, ctx, name, identity, optional=True)
        if roots is not None:
            return roots
    _deny("audience_unavailable")


def _owned_members(session, ctx, root):
    name, identity, owner = root
    if owner != str(ctx.requester_id):
        return None  # Recipient RLS exposes only that recipient, not the roster.
    return {ctx.requester_id} | set(
        session.scalars(
            select(ObjectAudience.principal_id).where(
                ObjectAudience.tenant_id == ctx.tenant_id,
                ObjectAudience.category_id == ctx.category_id,
                ObjectAudience.object_type == name,
                ObjectAudience.subject_id == UUID(identity),
                ObjectAudience.owner_id == ctx.requester_id,
            )
        ).all()
    )


def _covers(session, ctx, target_roots, source_roots):
    if source_roots.issubset(target_roots):
        return True
    # Owners can read the complete existing ACL. This also handles a category
    # child whose actual private parent bounds its audience to this requester,
    # and distinct owned objects with compatible explicitly designated readers.
    members = None
    for root in target_roots:
        known = _owned_members(session, ctx, root)
        if known is not None:
            members = known if members is None else members & known
    if members == {ctx.requester_id}:
        return True  # current() proved every source readable for this sole reader.
    if members is None:
        return False
    for root in source_roots - target_roots:
        known = _owned_members(session, ctx, root)
        if known is None or not members.issubset(known):
            return False
    return True


def _audience(session, ctx, target, selected, actual):
    work = target.get("kind") == "work_followup"
    if target["visibility"] == "private" and not work:
        # _target binds the owner to this real Human, and current() has just
        # reauthorized every source and dependency for that same principal.
        return
    if target["visibility"] != "private" and any(
        row["customer_original"] for row in actual.values()
    ):
        _deny("customer_original_shared", "客户原件及其派生内容不能带入共享品类对象。")
    restricted = [cid for cid, row in actual.items()
                  if row["private"] or work and row["customer_original"]]
    if not restricted:
        return
    target_roots = _audience_roots(
        session, ctx, "projects" if work else "builds",
        target["project_id"] if work else target["build_id"],
    )
    if not work and target["preparation_id"]:
        target_roots |= _audience_roots(
            session, ctx, "verification_preparations", target["preparation_id"]
        )
    for cid in restricted:
        source = actual[cid]
        roots = _source_roots(session, ctx, source["source_type"], source["source_id"])
        relation = selected[cid].get("relation")
        if relation:
            roots |= _source_roots(session, ctx, relation["source_type"], relation["source_id"])
        if not roots or not _covers(session, ctx, target_roots, roots):
            _deny("audience_widened", "本次讨论携带的来源受众未覆盖当前复验准备。")


def _root_read(session, run, cid, item):
    origin_cid = item.get("origin_citation_id", cid)
    if item.get("origin_run_id"):
        origins = [session.get(AgentRun, UUID(item["origin_run_id"]))]
    else:
        origins = (
            session.scalars(
                select(AgentRun)
                .join(AgentToolCall, AgentToolCall.run_id == AgentRun.id)
                .where(
                    AgentRun.session_id == run.session_id,
                    AgentRun.requester_id == run.requester_id,
                    AgentToolCall.tool.in_(ledger.ROOT_TOOLS),
                    AgentToolCall.result["items"].contains([{"citation_id": origin_cid}]),
                )
            )
            .unique()
            .all()
        )
    for origin in origins:
        if (
            origin is None
            or origin.tenant_id != run.tenant_id
            or origin.session_id != run.session_id
            or origin.requester_id != run.requester_id
        ):
            _deny("origin_invalid")
        for call, _args in ledger.completed(
            session, scope_for_run(origin), ledger.ROOT_TOOLS, archive=True
        ):
            for root in call.result.get("items", []):
                if root.get("citation_id") != origin_cid:
                    continue
                if root["citation_id"] != ledger.citation_id(origin.id, call.id, root):
                    _deny("origin_invalid")
                expected = {
                    key: val
                    for key, val in item.items()
                    if key not in {"citation_id", "origin_run_id", "origin_citation_id"}
                }
                if expected != {key: val for key, val in root.items() if key != "citation_id"}:
                    _deny("origin_changed")
                return {
                    "origin_run_id": str(origin.id),
                    "origin_citation_id": origin_cid,
                    "read_proof": {
                        "call_id": str(call.id),
                        "tool": call.tool,
                        "result_digest": digest(call.result),
                        "citation_digest": digest(root),
                    },
                }
    _deny("read_proof_missing")


def _discussion_footprint(session, ctx, run):
    """The frozen action explicitly carries selected direct-parent discussion.

    Ordinary context_selection still limits child reads/citations. The separate
    native action can select parent discussion as well as current execution
    inputs; only its actual parent/proof authorizes that bridge. The parent's
    unselected footprint participates solely in currentness/audience checks.
    """
    carried, historical = ledger.carried(session, scope_for_run(run))
    action = getattr(run, "versions", {}).get("verification_action")
    if action is None:
        action = getattr(run, "versions", {}).get("work_followup_action")
        if action is None:
            return carried, historical, carried
        from .work_followup_actions import check_action
    else:
        from .verification_actions import check_action

    proof = check_action(session, ctx, run, action)
    parent = session.get(AgentRun, UUID(proof["run_id"]))
    parent_carried, _parent_historical = ledger.carried(session, scope_for_run(parent))
    selected_ids = {row["citation_id"] for row in proof["discussion_sources"]}
    if selected_ids - set(parent_carried):
        _deny("citation_not_carried")

    def merged(extra):
        if any(cid in carried and carried[cid] != item for cid, item in extra.items()):
            _deny("origin_changed")
        return {**extra, **carried}

    return (
        merged({cid: parent_carried[cid] for cid in selected_ids}),
        set(historical) | set(parent_carried),
        merged(parent_carried),
    )


def capture(
    session,
    ctx,
    run,
    citation_ids,
    *,
    product_id,
    build_id,
    execution_references=(),
    preparation_id=None,
    include_taint=False,
):
    """Server-only capture; session must be the ordinary requester's transaction."""
    run = _run(session, ctx, run)
    references = [
        DefinitionReference.model_validate(ref).model_dump(mode="json")
        for ref in execution_references
    ]
    target, reads = _target(session, ctx, run, product_id, build_id, references, preparation_id)
    carried, historical, footprint = _discussion_footprint(session, ctx, run)
    identities = list(dict.fromkeys(str(UUID(str(cid))) for cid in citation_ids))
    if set(identities) - set(carried):
        _deny("citation_not_carried")
    selected = {cid: carried[cid] for cid in identities}
    # Discussion may retain a historical fixed read after a primary update.
    # It is never silently promoted into the current execution reference set.
    # The generated prose may use any actually disclosed context, even when the
    # Human selects only A as a discussion citation. Check the whole footprint
    # against the target; never silently select B or bind it as execution input.
    actual, missing = current(session, footprint, allow_updated=historical)
    if missing:
        raise DomainError("SOURCE_UNAVAILABLE", "本次讨论携带的依据已无权读取、撤回或失效。")
    _audience(session, ctx, target, footprint, actual)
    discussions = []
    for cid, item in selected.items():
        discussions.append(
            {
                "citation_id": cid,
                "purpose": "historical_discussion",
                **{
                    key: deepcopy(item[key])
                    for key in (
                        "source_type",
                        "source_id",
                        "source_revision",
                        "content_hash",
                        "locator",
                    )
                },
                **_root_read(session, run, cid, item),
            }
        )
    pinned = {ref["artifact_id"]: ref["expected_revision"] for ref in run.read_sources}
    execution = []
    for ref in references:
        candidates = {
            cid: item
            for cid, item in carried.items()
            if item["source_type"] == "artifact"
            and item["source_id"] == ref["artifact_id"]
            and item["source_revision"] == ref["expected_revision"]
        }
        if pinned.get(ref["artifact_id"]) != ref["expected_revision"] or not candidates:
            _deny("execution_read_missing", "执行定义须来自本次运行已固定并实际读取的资料。")
        verified, unavailable = current(session, candidates, with_body=True)
        if unavailable and not verified:
            raise DomainError("SOURCE_UNAVAILABLE", "执行定义的固定原文已不可用。")
        cid = next(iter(verified))
        source = verified[cid]
        lines = source["body"].splitlines()
        if ref["line"] > len(lines) or ref["quote"] not in lines[ref["line"] - 1]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "执行定义须在当前固定原文行精确定位。")
        _audience(session, ctx, target, {cid: candidates[cid]}, {cid: source})
        execution.append(
            {
                "reference": ref,
                "citation_id": cid,
                "content_hash": source["content_hash"],
                **_root_read(session, run, cid, candidates[cid]),
            }
        )
    value = {
        "version": 1,
        "run_id": str(run.id),
        "target": target,
        "discussion_sources": discussions,
        "execution_references": references,
        "execution_sources": execution,
        "read_set": reads,
        "applicability_status": "not_assessed",
    }
    if include_taint:
        from .action_taint import classify

        value["taint"] = classify(actual)
    return {**value, "digest": digest(value)}


def recheck(session, ctx, run, frozen, *, preparation_id=None):
    """Re-derive provenance and current authority; accept only the real preparation transition."""
    expected = {
        "version",
        "run_id",
        "target",
        "discussion_sources",
        "execution_references",
        "execution_sources",
        "read_set",
        "applicability_status",
        "digest",
    }
    if isinstance(frozen, dict) and "taint" in frozen:
        expected.add("taint")
    if (
        not isinstance(frozen, dict)
        or set(frozen) != expected
        or type(frozen["version"]) is not int
    ):
        _deny("proof_changed")
    body = {key: val for key, val in frozen.items() if key != "digest"}
    if frozen.get("version") != 1 or digest(body) != frozen.get("digest"):
        _deny("proof_changed")
    target = frozen["target"]
    saved_id = target["preparation_id"]
    if saved_id and preparation_id is not None and str(preparation_id) != saved_id:
        _deny("preparation_changed")
    checked = capture(
        session,
        ctx,
        run,
        [row["citation_id"] for row in frozen["discussion_sources"]],
        product_id=target["product_id"],
        build_id=target["build_id"],
        execution_references=frozen["execution_references"],
        preparation_id=preparation_id if preparation_id is not None else saved_id,
        include_taint="taint" in frozen,
    )
    before, after = deepcopy(frozen), deepcopy(checked)
    for value in (before, after):
        value.pop("digest")
        if not saved_id:
            for key in ("preparation_id", "preparation_revision", "preparation_sha256"):
                value["target"].pop(key)
    if before != after:
        _deny("proof_changed")
    return checked


def capture_work(session, ctx, run, citation_ids, *, execution_references=()):
    """Existing action proof for a project task; originals remain explicit inputs."""
    from pdos_next.domain.work_management import owner
    from pdos_next.schemas.verification.contracts import SourceRef
    from pdos_next.source_current import direct_source_basis

    run = _run(session, ctx, run)
    product = require_access(session, ctx, run.product_id, write=True)
    project = owner.project(session, ctx, run.product_id, run.project_id)
    target = {
        "kind": "work_followup", "tenant_id": str(ctx.tenant_id),
        "category_id": str(ctx.category_id), "product_id": str(product.id),
        "project_id": str(project.id), "project_revision": project.revision,
        "owner_id": str(project.owner_id), "visibility": project.visibility,
    }
    carried, historical, footprint = _discussion_footprint(session, ctx, run)
    identities = list(dict.fromkeys(str(UUID(str(cid))) for cid in citation_ids))
    if not identities or set(identities) - set(carried):
        _deny("citation_not_carried")
    actual, missing = current(session, footprint, allow_updated=historical)
    if missing:
        raise DomainError("SOURCE_UNAVAILABLE", "本次讨论的依据已撤回、失权或失效。")
    _audience(session, ctx, target, footprint, actual)
    discussion = []
    for cid in identities:
        item = carried[cid]
        discussion.append({
            "citation_id": cid, "purpose": "historical_discussion",
            **{key: deepcopy(item[key]) for key in (
                "source_type", "source_id", "source_revision", "content_hash", "locator",
            )},
            **_root_read(session, run, cid, item),
        })
    references = [SourceRef.model_validate(ref) for ref in execution_references]
    revisions = {}
    for ref in references:
        if str(ref.id) in revisions and revisions[str(ref.id)] != ref.revision:
            _deny("execution_read_missing")
        revisions[str(ref.id)] = ref.revision
    reads = [{"artifact_id": identity, "expected_revision": revision}
             for identity, revision in sorted(revisions.items())]
    pinned = {str(row["artifact_id"]): row["expected_revision"] for row in run.read_sources}
    execution = []
    for ref in references:
        selected = {cid: item for cid, item in carried.items()
                    if item["source_type"] == "artifact" and item["source_id"] == str(ref.id)
                    and item["source_revision"] == ref.revision}
        if ref.kind != "artifact" or pinned.get(str(ref.id)) != ref.revision or not selected:
            _deny("execution_read_missing", "任务原件须由本人选择并在本次运行实际读取。")
        verified, unavailable = current(session, selected, with_body=True)
        if not verified or unavailable:
            raise DomainError("SOURCE_UNAVAILABLE", "任务原件当前不可读。")
        cid = next(iter(verified))
        direct_source_basis(session, ctx, product, [ref], reads)
        _audience(session, ctx, target, selected, verified)
        execution.append({"reference": ref.model_dump(mode="json"), "citation_id": cid,
                          "content_hash": verified[cid]["content_hash"],
                          **_root_read(session, run, cid, selected[cid])})
    from .action_taint import classify

    value = {
        "version": 1, "run_id": str(run.id), "target": target,
        "discussion_sources": discussion,
        "execution_references": [ref.model_dump(mode="json") for ref in references],
        "execution_sources": execution, "read_set": reads,
        "taint": classify(actual),
        "applicability_status": "not_assessed",
    }
    return {**value, "digest": digest(value)}


def recheck_work(session, ctx, run, frozen):
    if not isinstance(frozen, dict) or frozen.get("target", {}).get("kind") != "work_followup":
        _deny("proof_changed")
    checked = capture_work(
        session, ctx, run, [row["citation_id"] for row in frozen["discussion_sources"]],
        execution_references=frozen["execution_references"],
    )
    if checked != frozen:
        _deny("proof_changed")
    return checked
