"""Legacy cache supplements retain only complete actual project-root closures."""

from uuid import uuid4

import pytest

from pdos_next.agent_kernel import conversation_acl as acl
from tests.agent_kernel.test_conversation_acl import batch_session, manifest, native_ledger


@pytest.mark.parametrize("project_source", ["artifact", "definition"])
def test_legacy_project_upgrade_checks_original_scan_and_retains_frozen_read_roots(
    monkeypatch, project_source,
):
    project_artifact, project_original, definition, old_read, new_read, read_original = (
        str(uuid4()) for _ in range(6)
    )
    run, calls = native_ledger("evidence.search", {
        "items": [{"artifact_id": new_read, "revision": 1}],
    })
    run.project_id, run.product_id = uuid4(), uuid4()
    calls[-1]["execution_binding"].update(product_id=str(run.product_id),
                                         project_id=str(run.project_id))
    binding = {key: str(getattr(run, key)) for key in (
        "tenant_id", "category_id", "product_id", "project_id", "requester_id")}
    project_root = acl.dependency("artifact", project_artifact, 1)
    binding.update(kind="project-current-facts/v1", references=[], source_proof=[])
    if project_source == "artifact":
        binding["source_proof"] = [
            {"artifact_id": project_artifact, "expected_revision": 1}]
    else:
        binding["references"] = [{"kind": "definition", "id": definition, "revision": 1}]
    frozen_row = {"id": run.id, "proposal_refs": [], "citations": [],
                  "project_context": binding, "project_carried": True}
    rows = {
        ("run", str(run.id)): [{"revision": 1}],
        ("project", str(run.project_id)): [{"revision": 1}],
        ("product", str(run.product_id)): [{"revision": 1}],
        ("definition", definition): [{"revision": 1}],
        ("artifact", project_artifact): [
            {"status": "active", "revision": 1, "original_id": project_original}],
        ("original", project_original): [{"status": "parsed", "scan_status": "clean"}],
        ("artifact", old_read): [{"status": "active", "revision": 1}],
        ("artifact", new_read): [
            {"status": "active", "revision": 1, "original_id": read_original}],
        ("original", read_original): [{"status": "parsed", "scan_status": "clean"}],
    }
    monkeypatch.setattr(acl, "metadata", lambda _session, dependencies: {
        (dep["kind"], dep["id"]): rows[dep["kind"], dep["id"]]
        for dep in dependencies if (dep["kind"], dep["id"]) in rows})
    monkeypatch.setattr(acl, "definition_edges", lambda _session, _dependencies:
                        {definition: [project_root]} if project_source == "definition" else {})
    rebuilt = acl.manifests(batch_session(calls, [run], frozen=[frozen_row]), [run])[str(run.id)]
    assert not rebuilt["project_unavailable"]
    assert acl.dependency("original", project_original) in rebuilt["dependencies"]
    # A full rebuild also sees the new adapter's READ root. It must not replace
    # or supplement the already frozen legacy READ when adding project roots.
    assert acl.dependency("artifact", new_read, 1) in rebuilt["dependencies"]
    assert acl.dependency("original", read_original) in rebuilt["dependencies"]
    old = manifest(run, dependencies=[acl.dependency("artifact", old_read, 1)])
    for key in ("projects", "project_dependencies", "project_unavailable"):
        old.pop(key)
    upgraded = acl.upgrade_project_roots(old, rebuilt)
    actual = {(dep["kind"], dep["id"]) for dep in upgraded["dependencies"]}
    assert ("artifact", old_read) in actual
    assert ("artifact", project_artifact) in actual and ("original", project_original) in actual
    assert ("artifact", new_read) not in actual and ("original", read_original) not in actual

    checked = []

    def scan_unavailable(_session, identities):
        checked.append({str(identity) for identity in identities})
        return set()

    monkeypatch.setattr("pdos_next.enterprise_search.safety.safe_originals", scan_unavailable)
    assert acl.classify(None, {str(run.id): upgraded}) == {str(run.id): "hidden"}
    assert checked == [{project_original}]
    # Original.status and scan_status alone remain clean. The actual scan gate,
    # e.g. after configuration/epoch changes, owns the current safety decision.
    assert rows["artifact", project_artifact][0]["status"] == "active"
    assert rows["original", project_original][0]["scan_status"] == "clean"


@pytest.mark.parametrize("footprint,expected", [
    (None, "current"), ({"kind": "project-current-facts/v2"}, "hidden"),
])
def test_legacy_basic_project_metadata_is_not_a_claimed_native_fact_projection(
    monkeypatch, footprint, expected,
):
    source = str(uuid4())
    run, calls = native_ledger("evidence.search", {
        "items": [{"artifact_id": source, "revision": 1}],
    })
    run.project_id, run.product_id = uuid4(), uuid4()
    calls[-1]["execution_binding"].update(product_id=str(run.product_id),
                                         project_id=str(run.project_id))
    frozen = [{"id": run.id, "proposal_refs": [], "citations": [],
               "project_carried": True, "project_context": footprint}]
    rows = {("run", str(run.id)): [{"revision": 1}],
            ("artifact", source): [{"status": "active", "revision": 1}]}
    monkeypatch.setattr(acl, "metadata", lambda _session, dependencies: {
        (dep["kind"], dep["id"]): rows[dep["kind"], dep["id"]]
        for dep in dependencies if (dep["kind"], dep["id"]) in rows})
    access = acl.manifests(batch_session(calls, [run], frozen=frozen), [run])
    manifest = access[str(run.id)]
    assert manifest["project_unavailable"] is (expected == "hidden")
    assert acl.dependency("artifact", source, 1) in manifest["dependencies"]
    assert manifest["projects"] == manifest["project_dependencies"] == []
    assert acl.classify(None, access) == {str(run.id): expected}
