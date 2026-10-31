"""Historical source closure and frozen-send semantics without DB/provider access."""

import re
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import conversation
from pdos_next.agent_kernel import conversation_acl as acl
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError


def run():
    return NS(id=uuid4(), session_id=uuid4(), read_sources=[], result={
        "summary": "先前的原回答", "unfinished": []})


def manifest(origin, *, dependencies=(), citations=(), **changes):
    return {"version": acl.VERSION, "run_id": str(origin.id),
            "dependencies": list(dependencies), "citations": list(citations),
            "unverified": [], "prepared": False, "research": [], "projects": [],
            "project_dependencies": [], "project_unavailable": False, **changes}


def test_all_current_registered_read_kinds_have_a_closed_history_classification():
    actual = {spec.name for spec in default_registry()._specs.values() if spec.tier == "READ"}
    assert actual == acl.READ_TOOLS
    assert len(actual) == 39
    assert {"assistant.passage.read", "assistant.comparison.read", "mcp.result.read",
            "evidence.artifact.read", "research.read"} <= actual


@pytest.mark.parametrize("tool", sorted(acl.READ_TOOLS))
def test_no_read_classification_calls_a_reader_or_runs_network(tool):
    original = run()
    value = {"items": [], "tools": []}
    args = {"proposal_id": str(uuid4())} if tool.startswith("proposal.") else {}
    # category.read always has one actual selected row, unlike an empty list.
    if tool == "category.read":
        value = {"id": str(uuid4()), "revision": 2}
    deps, _citations, unverified = acl.collect_call(tool, args, value, original)
    assert not unverified
    assert all(item["kind"] in acl.TABLES for item in deps)


def test_every_known_unquoted_search_candidate_and_private_root_is_retained():
    original = run()
    first, second = [{"source_type": "artifact", "source_id": str(uuid4()),
                      "citation_id": str(uuid4())} for _ in range(2)]
    _, refs, _ = acl.collect_call("assistant.search", {}, {"items": [first, second]}, original)
    assert refs == [first, second]  # Not just citations used by the final answer.


def test_internal_definition_bom_part_and_parameter_refs_are_dependencies():
    original = run()
    definition, config, bom, part, source, parameter = [str(uuid4()) for _ in range(6)]
    value = {"definition": {"id": definition, "revision": 3}, "blocks": {"bom": {
        "items": [{"configuration": {"id": config, "revision": 2}, "bom_id": bom,
                   "bom": {"lines": [{"part_id": part, "part": {"sources": [{
                       "type": "artifact", "id": source, "version": 1}],
                       "parameter_id": parameter, "parameter_version": 2}}]}}]}}}
    deps, _, _ = acl.collect_call("product.baseline.read", {}, value, original)
    assert {(item["kind"], item["id"]) for item in deps} >= {
        ("definition", definition), ("configuration", config), ("bom", bom),
        ("part", part), ("artifact", source), ("parameter", parameter)}


def test_spec_compare_freezes_returned_subject_revision_and_definition_root():
    product, definition = str(uuid4()), str(uuid4())
    deps, _, _ = acl.collect_call("calc.spec_compare", {"subjects": [{
        "type": "product", "id": product}]}, {"subjects": [{
            "type": "product", "id": product, "revision": 7,
            "definition_id": definition, "definition_revision": 3}], "groups": []}, run())
    assert acl.dependency("product", product, 7) in deps
    assert acl.dependency("definition", definition, 3) in deps


def test_unknown_and_external_json_never_mint_internal_object_dependencies():
    original = run()
    injected = {"type": "artifact", "id": str(uuid4()), "version": 1}
    assert acl.collect_call("invented.read", {}, injected, original) == ([], [], True)
    connector, grant = str(uuid4()), str(uuid4())
    deps, _, unknown = acl.collect_call("mcp.read", {}, {
        "connector_id": connector, "grant_ids": [grant], "grant_versions": {grant: 2},
        "rows": [{"value": injected}],
    }, original)
    assert not unknown
    assert {(item["kind"], item["id"]) for item in deps} == {
        ("connector", connector), ("mcp_grant", grant)}


def test_pure_calculator_input_references_do_not_confer_read_provenance():
    assert acl.collect_call("calc.cost_subtotal", {}, {
        "source_ref": {"type": "artifact", "id": str(uuid4()), "version": 1}}, run()) == (
            [], [], False)


def test_metadata_all_kinds_compile_as_one_union_with_no_business_bodies():
    statements = []

    def execute(statement):
        statements.append(statement)
        return NS(mappings=lambda: NS(all=lambda: []))

    acl.metadata(NS(execute=execute), [acl.dependency(kind, uuid4()) for kind in acl.TABLES])
    assert len(statements) == 1
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in sql
    for forbidden in (".content", ".markdown", ".body", ".quote", ".filename", ".secret_ref"):
        assert re.search(re.escape(forbidden) + r"\b", sql) is None
    assert "category_knowledge_current" in sql and "parameter_current" in sql


@pytest.mark.parametrize("kind,row", [
    ("artifact", {"status": "withdrawn"}),
    ("original", {"status": "parsed", "scan_status": "quarantined"}),
    ("knowledge", {"action": "add", "current_status": "withdrawn"}),
    ("connector", {"active": False}),
    ("mcp_grant", {"active": True, "expires_at": "2000-01-01T00:00:00+00:00"}),
    ("run", {"reverted_at": "2026-10-29"}),
])
def test_actual_revocation_states_hide_historical_answer(monkeypatch, kind, row):
    original, identity = run(), str(uuid4())
    access = {str(original.id): manifest(original, dependencies=[acl.dependency(kind, identity)])}
    monkeypatch.setattr(acl, "metadata", lambda *_: {(kind, identity): [row]})
    from pdos_next.enterprise_search import safety
    monkeypatch.setattr(safety, "safe_originals", lambda *_: set())
    assert acl.classify(None, access) == {str(original.id): "hidden"}


def test_update_is_annotated_and_receipt_access_loss_still_wins(monkeypatch):
    original, artifact, receipt = run(), str(uuid4()), str(uuid4())
    deps = [acl.dependency("artifact", artifact, 1), acl.dependency("receipt", receipt)]
    access = {str(original.id): manifest(original, dependencies=deps)}
    rows = {("artifact", artifact): [{"status": "active", "revision": 2}],
            ("receipt", receipt): [{"id": receipt}]}
    monkeypatch.setattr(acl, "metadata", lambda *_: rows)
    assert acl.classify(None, access) == {str(original.id): "updated"}
    rows.pop(("receipt", receipt))
    assert acl.classify(None, access) == {str(original.id): "hidden"}


def test_old_fixed_knowledge_new_pointer_is_updated_not_hidden(monkeypatch):
    original, entry = run(), str(uuid4())
    access = {str(original.id): manifest(original, dependencies=[
        acl.dependency("knowledge", entry, 1)])}
    monkeypatch.setattr(acl, "metadata", lambda *_: {("knowledge", entry): [{
        "version": 1, "current_revision": 2, "action": "add", "current_status": "active"}]})
    assert acl.classify(None, access) == {str(original.id): "updated"}


def test_unavailable_inherited_origin_cannot_be_restored_by_other_version_movement(monkeypatch):
    original, identity = run(), str(uuid4())
    access = {str(original.id): manifest(original, unavailable=True,
        dependencies=[acl.dependency("category", identity, 1)])}
    monkeypatch.setattr(acl, "metadata", lambda *_: {("category", identity): [{"revision": 2}]})
    assert acl.classify(None, access) == {str(original.id): "hidden"}


def test_runtime_unions_frozen_and_all_opened_pages_once_without_rebuilding_memory(monkeypatch):
    first, second = run(), run()
    access = {str(first.id): manifest(first)}
    page_access = {str(second.id): manifest(second)}
    active = NS(continued_from_id=first.id, versions={
        "conversation_memory": {"turns": []}, "conversation_access": access,
        "conversation_history_pages": {"older": {"access": page_access}},
    })
    original = deepcopy(active.versions)
    host = Bootstrap.__new__(Bootstrap)

    @contextmanager
    def transaction(_):
        yield None, active

    host.store = NS(transaction=transaction)
    calls = []
    monkeypatch.setattr(conversation, "memory", lambda *_a, **_k: pytest.fail("body rebuilt"))
    monkeypatch.setattr(acl, "manifests", lambda *_a, **_k: pytest.fail("manifest rebuilt"))
    def checking(_session, merged, **_kwargs):
        calls.append(deepcopy(merged))
        return {identity: "updated" for identity in merged}
    monkeypatch.setattr(acl, "classify", checking)
    scope = NS(project_id=None, isolation="main")
    host.check_conversation(scope)
    assert len(calls) == 1 and set(calls[0]) == {str(first.id), str(second.id)}
    assert active.versions == original
    monkeypatch.setattr(acl, "classify", lambda *_a, **_k: {str(second.id): "hidden"})
    with pytest.raises(DomainError, match="会话中引用"):
        host.check_conversation(scope)


def native_ledger(name="category.read", value=None):
    from tests.agent_kernel.test_read_execution import build, fixture

    f = fixture()
    binding = build(f).model_dump(mode="json")
    binding["tool"] = name
    f.run.read_sources = []
    f.run.result = {"summary": "历史正文", "unfinished": []}
    model = {key: getattr(f.model, key) for key in (
        "id", "run_id", "tool", "state", "receipt_id", "execution_binding", "result")}
    model = deepcopy(model)
    model["result"]["calls"][0]["name"] = name
    call = {"id": uuid4(), "run_id": f.run.id, "tool": name, "state": "completed",
            "receipt_id": None, "execution_binding": binding, "result": value or {
                "id": str(f.run.category_id), "revision": 1}}
    return f.run, [model, call]


def batch_session(calls, originals, *, frozen=None):
    results = iter([calls, frozen or [{"id": original.id, "proposal_refs": [], "citations": []}
                                    for original in originals]])
    return NS(execute=lambda _statement: NS(mappings=lambda: NS(all=lambda: next(results))))


def test_manifest_uses_actual_completed_model_read_binding_and_all_known_roots(monkeypatch):
    original, calls = native_ledger()
    observed = []
    def metadata(_session, deps):
        observed.append(deepcopy(deps))
        return {}
    monkeypatch.setattr(acl, "metadata", metadata)
    value = acl.manifests(batch_session(calls, [original]), [original])[str(original.id)]
    assert not value["unverified"]
    assert {("run", str(original.id)), ("category", str(original.category_id))} <= {
        (item["kind"], item["id"]) for item in value["dependencies"]}
    assert len(observed) == 1  # The number of reads is independent of original READ count.


def test_legacy_malformed_binding_remains_unverified_but_known_root_stays_restricted(monkeypatch):
    original, calls = native_ledger()
    calls[1]["execution_binding"] = {"kind": "read"}
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    value = acl.manifests(batch_session(calls, [original]), [original])[str(original.id)]
    assert value["unverified"] == ["category.read"]
    assert acl.dependency("category", original.category_id, 1) in value["dependencies"]


def test_nested_history_page_carries_original_sources_without_replaying_that_page(monkeypatch):
    parent, parent_calls = native_ledger()
    child, child_calls = native_ledger("conversation.history", {"turns": [{
        "run_id": str(parent.id), "outcome_state": "current"}]})
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    value = acl.manifests(batch_session([*parent_calls, *child_calls], [parent, child]),
                          [child], ancestors=[parent, child])[str(child.id)]
    assert acl.dependency("category", parent.category_id, 1) in value["dependencies"]
    assert acl.dependency("run", parent.id) in value["dependencies"]


def test_technical_count_call_is_ignored_only_for_the_narrow_registered_shape(monkeypatch):
    original, calls = native_ledger()
    technical = {"id": uuid4(), "run_id": original.id, "tool": "model.count_tokens",
                 "state": "completed", "receipt_id": None,
                 "execution_binding": {"kind": "unbound", "dispatch": "anthropic-count-tokens/v1",
                                       "model_binding": calls[0]["execution_binding"]},
                 "result": {"input_tokens": 500}}
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    value = acl.manifests(batch_session([*calls, technical], [original]), [original])
    assert not value[str(original.id)]["unverified"]
    technical["execution_binding"]["model_binding"] = {}
    value = acl.manifests(batch_session([*calls, technical], [original]), [original])
    assert value[str(original.id)]["unverified"] == ["model.count_tokens"]


@pytest.mark.parametrize("hidden", [False, True])
def test_default_carried_history_propagates_private_roots_without_a_new_read(monkeypatch, hidden):
    source = str(uuid4())
    parent, calls = native_ledger("evidence.search", {"items": [{
        "artifact_id": source, "revision": 1}]})
    child = deepcopy(parent)
    child.id = uuid4()
    child.continued_from_id = parent.id
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    frozen = [{"id": parent.id, "proposal_refs": [], "citations": []}, {
        "id": child.id, "proposal_refs": [], "citations": [],
        "history_runs": [] if hidden else [str(parent.id)],
    }]
    access = acl.manifests(batch_session(calls, [parent, child], frozen=frozen),
                           [parent, child], ancestors=[child, parent])
    rows = {("run", str(item.id)): [{"id": str(item.id)}] for item in [parent, child]}
    monkeypatch.setattr(acl, "metadata", lambda *_: rows)
    result = acl.classify(None, access)
    assert result[str(parent.id)] == "hidden"
    assert result[str(child.id)] == ("current" if hidden else "hidden")


def test_frozen_history_preserves_old_root_ids_instead_of_current_replacement(monkeypatch):
    old, new = str(uuid4()), str(uuid4())
    parent, calls = native_ledger("evidence.search", {"items": [{
        "artifact_id": new, "revision": 2}]})
    child = deepcopy(parent)
    child.id = uuid4()
    carried = manifest(parent, dependencies=[acl.dependency("artifact", old, 1)])
    frozen = [{"id": parent.id, "proposal_refs": [], "citations": []}, {
        "id": child.id, "proposal_refs": [], "citations": [], "history_access": {
            str(parent.id): carried}, "history_runs": [str(parent.id)],
    }]
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    value = acl.manifests(batch_session(calls, [parent, child], frozen=frozen),
                          [child], ancestors=[child, parent])[str(child.id)]
    assert acl.dependency("artifact", old, 1) in value["dependencies"]
    assert all(item["id"] != new for item in value["dependencies"])


def test_writer_opens_a_separate_snapshot_of_the_actual_persisted_human_owner(monkeypatch):
    from pdos_next.domain.preproject import access
    from pdos_next.enterprise_search import assistant_sources
    from tests.agent_kernel.test_read_execution import fixture

    f = fixture()
    scope = (f.run.tenant_id, f.run.writer_id, f.run.requester_id, f.run.category_id)
    writer = NS(get=lambda *_: f.run, info={"scope": scope}, get_bind=lambda: "actual-engine")
    reading = NS(get=lambda *_: f.run)
    calls = []
    @contextmanager
    def snapshot(engine, bound):
        calls.append((engine, bound.requester_id, bound.writer_id))
        yield reading
    monkeypatch.setattr(assistant_sources, "human_snapshot", snapshot)
    monkeypatch.setattr(access, "human", lambda _s, ctx: calls.append(ctx.actor_id))
    with acl.owner_snapshot(writer, f.run) as actual:
        assert actual is reading
    assert writer.info["scope"] == scope
    assert calls == [("actual-engine", f.run.requester_id, f.run.writer_id), f.run.requester_id]
    borrowed = deepcopy(f.run)
    borrowed.requester_id = uuid4()
    with pytest.raises(DomainError):
        with acl.owner_snapshot(writer, borrowed):
            pytest.fail("Borrowed owner admitted")


@pytest.mark.parametrize("changed", ["active", "expiry", "contract", "grant"])
def test_mcp_current_grants_and_connector_digest_revoke_without_transport(changed):
    from datetime import UTC, datetime, timedelta

    from pdos_next.agent_kernel.mcp_binding import connector_binding

    connector = NS(id=uuid4(), active=True, key="local-test", endpoint="https://example.test/mcp",
                   secret_ref="server-only-reference", tools={"parts.read": {"kind": "read"}})
    grant = NS(id=uuid4(), connector_id=connector.id, tool="parts.read", active=True,
               expires_at=datetime.now(UTC) + timedelta(days=1), skill_key="public_research",
               connector_binding_digest=connector_binding(connector, "parts.read"))
    target = {"connector_id": str(connector.id), "tool": grant.tool, "grant_ids": [str(grant.id)]}
    session = NS(execute=lambda _: NS(all=lambda: [(connector, grant)]))
    assert acl.mcp_access(session, [target]) == {acl.digest(target): True}
    if changed == "active":
        grant.active = False
    elif changed == "expiry":
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif changed == "contract":
        connector.secret_ref = "new-server-only-reference"
    else:
        target["grant_ids"] = [str(uuid4())]
    assert acl.mcp_access(session, [target]) == {acl.digest(target): False}


def test_legacy_recent_ten_round_closure_does_not_expand_exponentially(monkeypatch):
    originals = [native_ledger()[0] for _ in range(20)]
    frozen = [{"id": original.id, "proposal_refs": [], "citations": [],
               "history_runs": [str(row.id) for row in originals[max(0, index - 10):index]]}
              for index, original in enumerate(originals)]
    copies = []

    def measured(value):
        copies.append(None)
        return deepcopy(value)

    monkeypatch.setattr(acl, "deepcopy", measured)
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    value = acl.manifests(batch_session([], originals, frozen=frozen), [originals[-1]],
                          ancestors=list(reversed(originals)))[str(originals[-1].id)]
    assert {item["id"] for item in value["dependencies"]} == {
        str(original.id) for original in originals}
    assert len(value["dependencies"]) == len(originals)
    assert len(copies) <= 2 * len(originals)


def test_old_inflight_cache_adds_project_roots_without_replacing_frozen_reads(monkeypatch):
    parent = run()
    identity = str(parent.id)
    old, replacement, project_source = [str(uuid4()) for _ in range(3)]
    frozen = manifest(parent, dependencies=[acl.dependency("artifact", old, 1)])
    for key in ("projects", "project_dependencies", "project_unavailable"):
        frozen.pop(key)
    active = NS(continued_from_id=parent.id, state="running", versions={
        "conversation_memory": {"turns": [{"run_id": identity, "outcome_state": "current"}]},
        "conversation_access": {identity: frozen},
    })
    project_dep = acl.dependency("artifact", project_source, 1)
    rebuilt = manifest(parent, dependencies=[acl.dependency("artifact", replacement, 2),
                                            project_dep], project_dependencies=[project_dep])
    host = Bootstrap.__new__(Bootstrap)

    @contextmanager
    def transaction(_):
        yield None, active

    host.store = NS(transaction=transaction)
    monkeypatch.setattr(conversation, "lineage", lambda *_: [parent])
    rebuilt_calls, checked = [], []

    def rebuild(_session, origins, **_kwargs):
        rebuilt_calls.append([item.id for item in origins])
        return {identity: rebuilt}

    monkeypatch.setattr(acl, "manifests", rebuild)
    monkeypatch.setattr(acl, "classify", lambda _session, access, **_kwargs:
                        checked.append(deepcopy(access)) or {identity: "current"})
    scope = NS(project_id=None, isolation="main")
    host.check_conversation(scope)
    assert rebuilt_calls == [[parent.id]]
    dependencies = checked[0][identity]["dependencies"]
    assert {item["id"] for item in dependencies} == {old, project_source}
    assert checked[0][identity]["project_dependencies"] == [project_dep]
    # A second send uses the supplemented frozen cache without rebuilding bodies.
    host.check_conversation(scope)
    assert len(rebuilt_calls) == 1
    monkeypatch.setattr(acl, "classify", lambda *_a, **_k: {identity: "hidden"})
    with pytest.raises(DomainError, match="会话中引用"):
        host.check_conversation(scope)
