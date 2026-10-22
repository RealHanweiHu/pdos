"""Actual read/registration verification over synthetic rows; no database or I/O ports."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.category_research_refs import CategoryResearchRefs
from pdos_next.agent_kernel.execution import check_run_binding, scope_for_run
from pdos_next.agent_kernel.models import AgentToolCall, PublicWebSnapshot
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.research_read_ledger import page_result as ordinary_page
from pdos_next.domain.preproject.models import Proposal
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.research.types import ReadPage, Snapshot
from pdos_next.service import digest
from tests.agent_kernel.test_snapshot_command import proof as ordinary_ledger  # noqa: F401
from tests.agent_kernel.test_snapshot_read_ledger import ledger as registered_ledger  # noqa: F401


class ReadSession:
    def __init__(self, source, scope):
        self.rows, self.scope = source.rows, scope

    def get(self, cls, identity):
        return self.rows.get((cls, identity))

    def scalar(self, query):
        if str(query) == "SELECT to_regclass('public.proposals') IS NOT NULL":
            return True
        assert query.column_descriptions[0]["entity"] is Proposal
        params = query.compile().params
        assert set(params) == {"tenant_id_1", "category_id_1", "id_1"}
        row = self.get(Proposal, params["id_1"])
        return row if row and (row.tenant_id, row.category_id) == (
            params["tenant_id_1"], params["category_id_1"],
        ) else None

    def scalars(self, query):
        cls = query.column_descriptions[0]["entity"]
        rows = [row for (model, _), row in self.rows.items() if model is cls]
        if cls is AgentToolCall:
            rows = [row for row in rows if row.tool == "research.read"
                    and row.state == "completed" and row.run_id == self.scope.run_id
                    and row.tenant_id == self.scope.tenant_id]
        return NS(all=lambda: rows)


class ReadStore:
    def __init__(self, session, run):
        self.session, self.run = session, run
        self.checked = []
        self.revoked = False

    def current(self, scope):
        self.checked.append(scope)
        if self.revoked:
            raise DomainError("FORBIDDEN_SCOPE", "Synthetic revoked authority")
        check_run_binding(self.run, scope, for_write=False)

    @contextmanager
    def transaction(self, scope):
        self.current(scope)
        yield self.session, self.run

    def authority(self, session, scope):
        KernelStore(None).authority(session, scope)


def wrap(f, snapshot):
    scope = scope_for_run(f.run)
    session = ReadSession(f.session, scope)
    if scope.proposal_id is not None:
        session.rows[Proposal, scope.proposal_id] = NS(
            id=scope.proposal_id, tenant_id=scope.tenant_id, category_id=scope.category_id,
        )
    store = ReadStore(session, f.run)
    retained = {snapshot.id: snapshot}
    artifacts = NS(snapshot=lambda actual, identity: retained[identity])
    callback = CategoryResearchRefs(store, artifacts)
    result = {
        "snapshots": [{"id": str(snapshot.id), "content_hash": snapshot.content_hash}],
        "coverage": [{"task_key": "synthetic", "reads": [{
            "snapshot_id": str(snapshot.id), "locator": f.call.result["locator"], "error": None,
        }]}],
    }
    return NS(**{**vars(f), "scope": scope, "session": session, "store": store,
                 "retained": retained, "artifacts": artifacts, "callback": callback,
                 "result": result, "snapshot": snapshot})


@pytest.fixture
def ordinary(request):
    source = request.getfixturevalue("ordinary_ledger")
    return wrap(source, source.snapshot)


@pytest.fixture
def registered(request):
    f = request.getfixturevalue("registered_ledger")
    row = f.snapshot
    row.title, row.summary, row.provider, row.credibility = "Synthetic", "", "fixture", "public_web"
    row.retrieved_at = datetime(2026, 10, 11, tzinfo=UTC)
    snapshot = Snapshot(**{field.name: getattr(row, field.name) for field in fields(Snapshot)})
    value = wrap(f, snapshot)
    value.registered = row
    return value


def check(f):
    return f.callback(f.scope, f.result)


def restore(f):
    f.result["snapshot_read_refs"] = check(f)
    return check(f)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
def test_fresh_and_restore_bind_actual_read_without_raw_page(request, fixture_name):
    f = request.getfixturevalue(fixture_name)
    refs = check(f)
    assert refs == [{"call_id": str(f.call.id), "snapshot_id": str(f.snapshot.id),
                     "content_hash": f.snapshot.content_hash, "locator": f.call.result["locator"]}]
    f.result["snapshot_read_refs"] = deepcopy(refs)
    assert check(f) == refs
    assert set(refs[0]) == {"call_id", "snapshot_id", "content_hash", "locator"}
    assert f.store.checked and all(scope == f.scope for scope in f.store.checked)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
@pytest.mark.parametrize("change", ["missing_model", "model_state", "model_run", "model_isolation",
    "model_version", "model_prompt", "model_arguments", "read_state", "read_run", "read_digest",
    "read_kind", "read_binding", "read_tool", "read_error", "read_receipt", "page_body",
    "page_locator", "page_extra", "page_hash", "coverage", "snapshot_hash", "missing_artifact",
    "revoked", "requester_inactive", "writer_inactive", "grant", "failed", "cancelled", "epoch"])
def test_each_restored_ref_needs_current_full_model_read_page_proof(request, fixture_name, change):
    f = request.getfixturevalue(fixture_name)
    f.result["snapshot_read_refs"] = check(f)
    if change == "missing_model":
        del f.session.rows[AgentToolCall, f.model.id]
    elif change.startswith("model_"):
        part = change.removeprefix("model_")
        if part in {"state", "run"}:
            setattr(f.model, "state" if part == "state" else "run_id",
                    "started" if part == "state" else uuid4())
        elif part == "arguments":
            f.model.result["calls"][0]["arguments"]["cursor"] = 999
        else:
            key = {"isolation": "isolation", "version": "model_version",
                   "prompt": "prompt_digest"}[part]
            f.model.execution_binding[key] = "main" if part == "isolation" else "f" * 64
    elif change.startswith("read_"):
        part = change.removeprefix("read_")
        if part in {"kind", "binding"}:
            f.call.execution_binding["read_kind" if part == "kind" else "extra"] = "fake"
        else:
            key, value = {
                "state": ("state", "started"), "run": ("run_id", uuid4()),
                "digest": ("input_digest", "f" * 64), "tool": ("tool", "research.search"),
                "error": ("error_code", "error"), "receipt": ("receipt_id", uuid4()),
            }[part]
            setattr(f.call, key, value)
    elif change.startswith("page_"):
        part = change.removeprefix("page_")
        key = {"body": "markdown", "locator": "locator",
               "extra": "extra", "hash": "content_hash"}[part]
        f.call.result[key] = "altered"
    elif change == "coverage":
        f.result["coverage"][0]["reads"][0]["locator"] = "chars:0:9999"
    elif change == "snapshot_hash":
        f.result["snapshots"][0]["content_hash"] = "f" * 64
    elif change == "missing_artifact":
        f.retained.clear()
    elif change == "revoked":
        f.store.revoked = True
    elif change.endswith("inactive"):
        identity = f.scope.requester_id if change.startswith("requester") else f.scope.writer_id
        f.session.get(Principal, identity).active = False
    elif change == "grant":
        for key, row in list(f.session.rows.items()):
            if key[0] is Grant and row.principal_id == f.scope.writer_id:
                del f.session.rows[key]
    elif change == "epoch":
        f.run.cancel_epoch += 1
    else:
        f.run.state = change
    with pytest.raises(DomainError):
        check(f)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
def test_restore_does_not_replace_original_call_with_later_matching_page(request, fixture_name):
    f = request.getfixturevalue(fixture_name)
    refs = restore(f)
    other = deepcopy(f.call)
    other.id = uuid4()
    f.session.rows[AgentToolCall, other.id] = other
    assert check(f) == refs
    del f.session.rows[AgentToolCall, f.call.id]
    with pytest.raises(DomainError):
        check(f)
    del f.result["snapshot_read_refs"]
    assert check(f)[0]["call_id"] == str(other.id)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
def test_all_coverage_pages_need_distinct_actual_returned_page(request, fixture_name):
    f = request.getfixturevalue(fixture_name)
    ref = deepcopy(f.result["coverage"][0]["reads"][0])
    ref["locator"] = "chars:0:1"
    f.result["coverage"][0]["reads"].append(ref)
    with pytest.raises(DomainError):
        check(f)


def test_second_real_page_and_unicode_offsets_are_kept_as_separate_refs(ordinary):
    f = ordinary
    start, end = 18, len(f.snapshot.markdown)
    model, call = deepcopy(f.model), deepcopy(f.call)
    model.id, call.id = uuid4(), uuid4()
    model.result["calls"][0]["arguments"]["cursor"] = start
    call.call_key = execution_key(f.run.id, model.id, 0)
    call.execution_binding.update(model_call_id=str(model.id), call_key=call.call_key)
    call.input_digest = digest([call.tool, model.result["calls"][0]["arguments"]])
    call.result = ordinary_page(ReadPage(f.snapshot, f"chars:{start}:{end}",
                                        f.snapshot.markdown[start:end], None))
    f.session.rows[AgentToolCall, model.id] = model
    f.session.rows[AgentToolCall, call.id] = call
    f.result["coverage"][0]["reads"].append({"snapshot_id": str(f.snapshot.id),
                                           "locator": call.result["locator"], "error": None})
    refs = check(f)
    assert len(refs) == 2 and {ref["call_id"] for ref in refs} == {str(f.call.id), str(call.id)}
    assert refs == sorted(refs, key=lambda ref: ref["call_id"])


@pytest.mark.parametrize("change", ["private", "registration", "marker", "registered_body"])
def test_registered_read_retains_real_registration_and_shared_visibility(registered, change):
    f = registered
    if change == "private":
        f.registered.visibility = "private"
    elif change == "registration":
        f.receipt.result["registered_by_run_id"] = str(uuid4())
    elif change == "marker":
        f.receipt.result["proof_version"] = True
    else:
        f.registered.markdown += "changed"
    with pytest.raises(DomainError):
        check(f)


def test_registered_model_url_must_identify_the_returned_snapshot(registered):
    f = registered
    f.model.result["calls"][0]["arguments"]["url"] = "https://other.example/not-this-snapshot"
    f.call.input_digest = digest([f.call.tool, f.model.result["calls"][0]["arguments"]])
    with pytest.raises(DomainError):
        check(f)


def test_registered_snapshot_must_belong_to_actual_run_category(registered):
    f = registered
    f.registered.category_id = uuid4()
    f.receipt.category_id = f.registered.category_id
    with pytest.raises(DomainError):
        check(f)


def test_registered_snapshot_status_cannot_be_withdrawn(registered):
    f = registered
    f.registered.status = "withdrawn"
    f.retained[f.snapshot.id] = replace(f.snapshot, status="withdrawn")
    with pytest.raises(DomainError):
        check(f)


def test_ordinary_page_is_not_reclassified_after_matching_snapshot_registration(ordinary):
    f = ordinary
    f.session.rows[PublicWebSnapshot, f.snapshot.id] = NS(id=f.snapshot.id, visibility="private")
    assert restore(f)[0]["call_id"] == str(f.call.id)


def test_empty_research_has_no_invented_refs(ordinary):
    ordinary.result = {"snapshots": [], "coverage": [{"reads": []}]}
    assert check(ordinary) == []


@pytest.mark.parametrize("field", ["proof_version", "version"])
def test_registered_page_bool_cannot_impersonate_integer_proof(registered, field):
    registered.call.result[field] = True
    with pytest.raises(DomainError):
        check(registered)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
def test_model_arguments_must_follow_the_actual_read_schema(request, fixture_name):
    f = request.getfixturevalue(fixture_name)
    f.model.result["calls"][0]["arguments"]["approved"] = True
    f.call.input_digest = digest([f.call.tool, f.model.result["calls"][0]["arguments"]])
    with pytest.raises(DomainError):
        check(f)


@pytest.mark.parametrize("fixture_name", ["ordinary", "registered"])
def test_restored_read_references_cannot_duplicate_one_call(request, fixture_name):
    f = request.getfixturevalue(fixture_name)
    f.result["snapshot_read_refs"] = check(f) * 2
    with pytest.raises(DomainError):
        check(f)
