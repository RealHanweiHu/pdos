"""Actual research ports with local artifacts; no model, database or network calls."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel.bootstrap import RuntimePorts
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts, ResearchReadAdapter
from pdos_next.errors import DomainError
from pdos_next.research import HTTPResponse, ResearchToolHost, ResourceLimits
from pdos_next.service import digest
from tests.agent_kernel.research.test_research import Transport, scope, service


def fixture(tmp_path):
    bound = scope()
    checked = []

    def current(actual):
        assert actual.run_id == bound.run_id
        checked.append(actual)

    artifacts = ResearchArtifacts(tmp_path, current=current)
    body = "<p>参数🌡️：20 摄氏度；逐字片段。</p><p>未读尾部不可引用。</p>".encode()
    transport = Transport({
        "https://maker.example/specs": HTTPResponse(
            200, (("content-type", "text/html; charset=utf-8"),), body,
        ),
    })
    runtime = service(
        transport=transport, limits=ResourceLimits(page_chars=17),
        snapshot_sink=artifacts.save_snapshot,
    )
    runs = []

    async def researcher(task, child):
        runs.append(task.key)
        hit = (await child.search(task.focus))[0]
        page = await child.read(hit.url)
        return [{
            "free_key": "temperature", "quote": page.markdown[:7],
            "snapshot_id": str(page.snapshot.id), "locator": page.locator,
        }]

    ports = RuntimePorts(research_service=runtime, research_artifacts=artifacts)
    host = ResearchToolHost(
        ports.research_service, researcher=researcher, parameter_versions=lambda _: (),
    )
    adapter = ResearchReadAdapter(host, ports.research_artifacts, user_messages=lambda _: ())
    args = {"tasks": [{"key": "a", "focus": "temperature"}]}
    return SimpleNamespace(
        scope=bound, checked=checked, artifacts=artifacts, service=runtime,
        runs=runs, adapter=adapter, arguments=args, ports=ports,
    )


def replay(f):
    runtime = service()

    async def forbidden(*_):
        pytest.fail("Completed fanout must never start a researcher or a new job")

    adapter = ResearchReadAdapter(
        ResearchToolHost(runtime, researcher=forbidden, parameter_versions=lambda _: ()),
        f.artifacts, user_messages=lambda _: pytest.fail("Replay must use persisted authority"),
    )
    return adapter, runtime


def write_artifact(f, identity, payload):
    """Simulate corruption with a recomputed local checksum, not trusted receipt changes."""
    path = f.artifacts._path(f.scope, UUID(identity))
    path.write_text(json.dumps({"payload": payload, "digest": digest(payload)}, ensure_ascii=False))


def result(f):
    return f.adapter.handlers()["research.fanout"](f.scope, f.arguments)


def test_search_adapter_wraps_tool_host_list_and_restores_url_grants(tmp_path):
    f = fixture(tmp_path)
    args = {"query": "temperature"}
    prior = f.adapter.handlers()["research.search"](f.scope, args)
    assert set(prior) == {"hits", "provider"}
    assert prior["provider"] == f.service.search_adapter.provider
    assert len(prior["hits"]) == 1
    assert isinstance(asyncio.run(f.adapter.tool_host.call(
        f.scope, "research.search", args,
    )), list)
    adapter, runtime = replay(f)
    assert adapter.restores()["research.search"](f.scope, args, prior) is prior
    key = f.scope.tenant_id, f.scope.requester_id, f.scope.session_id, f.scope.run_id
    assert runtime._allowlists[key] == {prior["hits"][0]["url"]}
    assert runtime.search_adapter.queries == [] and runtime.transport.requests == []


def test_fanout_restores_same_job_and_exact_artifacts_without_rerun(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    assert f.runs == ["a"] and len(prior["snapshot_digests"]) == 1
    files_before = set(tmp_path.rglob("*.json"))
    adapter, runtime = replay(f)
    restored = adapter.restores()["research.fanout"](f.scope, f.arguments, prior)
    assert restored is prior and restored["job_id"] == prior["job_id"]
    assert set(tmp_path.rglob("*.json")) == files_before
    assert runtime.search_adapter.queries == [] and runtime.transport.requests == []
    snapshot = prior["snapshots"][0]
    # Restored memory continues the original full document; no second fetch.
    page = asyncio.run(runtime.read(
        f.scope.child("research"), snapshot["url"], cursor=17,
    ))
    assert "未读尾部" in page.markdown and runtime.transport.requests == []
    assert f.checked


def test_same_conversation_followup_reuses_verified_source_pool_without_network(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    consumer = replace(f.scope, run_id=uuid4())
    checked = []
    def current(actual):
        assert actual.run_id in {f.scope.run_id, consumer.run_id}
        checked.append(actual.run_id)
    f.artifacts.current = current
    adapter, runtime = replay(f)
    files_before = set(tmp_path.rglob("*.json"))
    assert adapter.admit_history(f.scope, f.arguments, prior, consumer) is prior
    page = asyncio.run(runtime.read(consumer.child("research"),
                                   prior["snapshots"][0]["url"], cursor=17))
    assert "未读尾部" in page.markdown
    assert runtime.transport.requests == [] and runtime.search_adapter.queries == []
    assert set(tmp_path.rglob("*.json")) == files_before
    assert consumer.run_id in checked


@pytest.mark.parametrize("field", ["session_id", "requester_id", "category_id"])
def test_history_pool_cannot_be_admitted_to_another_conversation_scope(tmp_path, field):
    f = fixture(tmp_path)
    prior = result(f)
    adapter, runtime = replay(f)
    with pytest.raises(DomainError) as failure:
        adapter.admit_history(f.scope, f.arguments, prior,
                              replace(f.scope, run_id=uuid4(), **{field: uuid4()}))
    assert failure.value.code == "FORBIDDEN_SCOPE"
    assert not runtime._allowlists and not runtime._snapshots
    assert runtime.transport.requests == []


@pytest.mark.parametrize("missing", ["job", "snapshot"])
def test_missing_original_artifact_is_unavailable_without_new_job(tmp_path, missing):
    f = fixture(tmp_path)
    prior = result(f)
    identity = prior["job_id"] if missing == "job" else prior["snapshots"][0]["id"]
    f.artifacts._path(f.scope, UUID(identity)).unlink()
    adapter, runtime = replay(f)
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert runtime._allowlists == {} and runtime._snapshots == {}
    assert f.runs == ["a"]


@pytest.mark.parametrize("field", ["summary", "credibility", "title", "markdown"])
def test_snapshot_full_metadata_and_unread_body_must_match_receipt(tmp_path, field):
    f = fixture(tmp_path)
    prior = result(f)
    identity = prior["snapshots"][0]["id"]
    saved = f.artifacts.get(f.scope, UUID(identity))
    saved["value"][field] += " changed"
    if field == "markdown":
        import hashlib
        saved["value"]["content_hash"] = hashlib.sha256(saved["value"][field].encode()).hexdigest()
    write_artifact(f, identity, saved)
    adapter, runtime = replay(f)
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert runtime._allowlists == {} and runtime._snapshots == {}


def test_original_job_must_match_completed_call_byte_content_digest(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    saved = f.artifacts.get(f.scope, UUID(prior["job_id"]))
    saved["value"]["ledger"][0]["quote"] += " altered"
    write_artifact(f, prior["job_id"], saved)
    adapter, _ = replay(f)
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("change", ["unread_quote", "unread_locator", "task", "reference"])
def test_fanout_receipt_citations_need_actual_read_location(tmp_path, change):
    f = fixture(tmp_path)
    prior = deepcopy(result(f))
    row = prior["ledger"][0]
    if change == "unread_quote":
        row["quote"] = "未读尾部不可引用"
    elif change == "unread_locator":
        row["locator"] = "chars:17:26"
    elif change == "task":
        row["task_key"] = "not-the-actual-task"
    else:
        row["snapshot_url"] = "https://different.example/specs"
    # Even consistent bad producer receipts cannot manufacture quote coverage.
    write_artifact(f, prior["job_id"], {"kind": "research_ledger", "value": prior})
    adapter, runtime = replay(f)
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert runtime._allowlists == {}


def test_cross_run_job_is_not_loaded_and_malformed_artifact_is_unavailable(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    adapter, _ = replay(f)
    with pytest.raises(AssertionError):
        adapter.restore_fanout(replace(f.scope, run_id=uuid4()), f.arguments, prior)
    f.artifacts._path(f.scope, UUID(prior["job_id"])).write_text("{broken")
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"


def test_changed_task_arguments_cannot_replay_prior_job(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    adapter, _ = replay(f)
    with pytest.raises(DomainError) as error:
        adapter.restore_fanout(f.scope, {"tasks": [{"key": "other", "focus": "x"}]}, prior)
    assert error.value.code == "SOURCE_UNAVAILABLE"
