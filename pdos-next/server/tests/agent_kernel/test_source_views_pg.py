"""Real registered sources and fixed Run bindings; root alone executes isolated PG.

The injected scanner is an explicit synthetic test port, never scanner qualification.
No model executes and no existing acceptance account or permission is changed.
"""

import json
import os
from copy import copy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from security_fixture import secured_parse, synthetic_runtime
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input

from pdos_next.api import create_app
from pdos_next.clock import using_clock
from pdos_next.models import (
    Artifact,
    Audit,
    Category,
    Confirmation,
    Grant,
    ObjectAudience,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
)
from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.original_security import configure

# Register the common model registry before the kernel's child tables.
# isort: split
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentInput,
    AgentRun,
    AgentSession,
    AgentToolCall,
)
from tests.agent_kernel.test_session_views_pg import actor
from tests.preproject.test_evidence_commands_pg import share_request
from tests.preproject.test_g0 import create, post, request, save
from tests.test_personal_views import second_category

GOAL = "本地合成：按选定附件固定版本核对未知项，不调用模型。"
PRIVATE_ROOT = (Path(__file__).resolve().parents[3] / ".local").resolve()


def private_path(value):
    path = Path(value)
    assert path.is_absolute(), "Private QA destination must be absolute"
    path = path.resolve()
    assert path.is_relative_to(PRIVATE_ROOT), "Private QA material must stay in pdos-next/.local"
    return path


@pytest.fixture
def source_work(setup, tmp_path):
    private = os.environ.get("PDOS_AGENT_SOURCES_QA_SESSION_PATH")
    if private:
        private_path(private)
        store_path = PRIVATE_ROOT / f"agent-sources-qa-originals-{setup.category}"
    else:
        store_path = tmp_path / "registered-synthetic-originals"
    store = JournaledLocalObjectStore(store_path.resolve())
    runtime = synthetic_runtime()
    prior_runtime = getattr(setup.engine, "_pdos_security_runtime", None)
    prior_results = getattr(setup.engine, "_pdos_results_store", None)
    work = copy(setup)
    work.store, work.runtime = store, runtime
    work.client = TestClient(
        create_app(
            setup.engine,
            setup.auth,
            object_store=store,
            security_runtime=runtime,
            workflow_enabled=False,
        )
    )
    try:
        yield work
    finally:
        work.client.close()
        configure(setup.engine, prior_runtime)
        setup.engine._pdos_results_store = prior_results
        store.close()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def base(work):
    return f"/v1/categories/{work.category}"


def listing(work, **params):
    return work.client.get(base(work) + "/agent-input-sources", headers=work.headers, params=params)


def bindings(work, run_id, **params):
    return work.client.get(
        base(work) + f"/agent-runs/{run_id}/source-bindings", headers=work.headers, params=params
    )


def registered(work, *, product_id=None, title="合成已登记文本", visibility="private"):
    with Session(work.admin) as session:
        revision = (
            session.get(Product, product_id).revision
            if product_id
            else session.get(Category, work.category).revision
        )
    command = request(
        work,
        "evidence.artifact.register",
        {
            "title": title,
            "source_label": "明确合成资料，未作业务确认",
            "content": "SYNTHETIC_SOURCE_BODY_DO_NOT_EXPOSE\nUnverified condition only.",
            "visibility": visibility,
        },
        revision=revision,
    )
    command["product_id"] = str(product_id) if product_id else None
    receipt = ok(post(work, command))
    return {"artifact_id": receipt["subject_id"], "expected_revision": 1}


def uploaded(work, *, product_id=None, parse=True, title="合成已解析原件"):
    path = base(work) + (f"/products/{product_id}" if product_id else "") + "/originals"
    response = work.client.post(
        path,
        headers=work.headers,
        json=upload_input(
            f"SYNTHETIC_ORIGINAL_BODY_DO_NOT_EXPOSE\n{title}\nCondition unknown.\n".encode(),
            title=title,
            filename="synthetic-original.txt",
        ).model_dump(mode="json"),
    )
    original_id = UUID(ok(response)["subject_id"])
    if not parse:
        return original_id, None
    result = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": str(product_id) if product_id else None,
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": str(original_id),
        },
        work.store,
    )
    assert result["status"] == "parsed", result
    with Session(work.admin) as session:
        source = session.scalar(select(Artifact).where(Artifact.original_id == original_id))
        original = session.get(UploadedOriginal, original_id)
        assert source.revision == 1 and original.revision == 2
        return original_id, {"artifact_id": str(source.id), "expected_revision": source.revision}


def start(work, sources, **scope):
    body = {"goal": GOAL, "idempotency_key": str(uuid4()), "sources": sources, **scope}
    response = work.client.post(base(work) + "/agent-runs", headers=work.headers, json=body)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    return response.json(), body


def counts(work):
    with Session(work.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (
                Artifact,
                UploadedOriginal,
                OriginalSecurity,
                OriginalScanRequest,
                OriginalScanResult,
                AgentSession,
                AgentRun,
                AgentEvent,
                AgentInput,
                AgentToolCall,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
                Confirmation,
            )
        }


def forbidden_cursor(response):
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE" and "刷新" in response.text


def export_qa(work, sources, run):
    public = os.environ.get("PDOS_AGENT_SOURCES_QA_RESPONSE_PATH")
    private = os.environ.get("PDOS_AGENT_SOURCES_QA_SESSION_PATH")
    if not (public or private):
        return
    bundle = {
        "session": ok(work.client.get("/v1/session", headers=work.headers)),
        "categories": ok(work.client.get("/v1/categories", headers=work.headers)),
        "list": ok(listing(work)),
        "product_list": ok(listing(work, product_id=work.product)),
        "bindings": ok(bindings(work, run["run_id"])),
        "selected_sources": sources,
        "goal": GOAL,
        "model_calls": 0,
        "scanner": "explicit synthetic test port; no qualification claim",
    }
    if public:
        output = Path(public)
        assert output.is_absolute(), "QA response destination must be absolute"
        output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
        assert work.tokens[work.human] not in encoded
        assert (
            "storage_key" not in encoded and "SYNTHETIC_ORIGINAL_BODY_DO_NOT_EXPOSE" not in encoded
        )
        output.write_text(encoded + "\n", encoding="utf-8")
    if private:
        output = private_path(private)
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(
                {
                    "tenant_id": str(work.tenant),
                    "principal_id": str(work.human),
                    "category_id": str(work.category),
                    "product_id": str(work.product),
                    "token": work.tokens[work.human],
                    "store_path": str(work.store.root),
                    "selected_sources": sources,
                    "goal": GOAL,
                    "run_id": run["run_id"],
                },
                stream,
            )
            stream.write("\n")


def test_registered_and_parsed_sources_bind_exact_artifact_versions_and_replay(source_work):
    work = source_work
    original_id, parsed = uploaded(work)
    manual = registered(work)
    pending_id, _ = uploaded(work, parse=False, title="合成未解析，不补伪资料")
    product = registered(work, product_id=work.product, title="合成型号资料")
    page = ok(listing(work))
    assert page["version"] == "agent-input-sources/v1"
    assert page["principal_id"] == str(work.human)
    assert page["scope"] == {
        "category_id": str(work.category),
        "product_id": None,
        "proposal_id": None,
    }
    by_id = {row["artifact_id"]: row for row in page["items"]}
    assert set(by_id) == {parsed["artifact_id"], manual["artifact_id"]}
    assert str(pending_id) not in json.dumps(page)
    assert by_id[parsed["artifact_id"]]["artifact_revision"] == 1
    assert by_id[parsed["artifact_id"]]["original"]["id"] == str(original_id)
    assert by_id[parsed["artifact_id"]]["original"]["revision"] == 2
    assert by_id[manual["artifact_id"]]["original"] is None
    assert all(row["availability"] == {"available": True, "code": None} for row in by_id.values())
    assert {row["artifact_id"] for row in ok(listing(work, product_id=work.product))["items"]} == {
        *by_id,
        product["artifact_id"],
    }
    sources = [parsed, manual]
    run, body = start(work, sources)
    before = counts(work)
    bound = ok(bindings(work, run["run_id"]))
    assert bound["version"] == "agent-run-source-bindings/v1"
    assert bound["scope"] == page["scope"] and bound["session_id"] == run["session_id"]
    assert [row["artifact_id"] for row in bound["items"]] == sorted(by_id)
    for item in bound["items"]:
        assert item["expected_revision"] == item["current"]["artifact_revision"] == 1
        assert item["product_id"] is None
    replay = work.client.post(base(work) + "/agent-runs", headers=work.headers, json=body)
    assert replay.status_code == 202 and replay.json()["run_id"] == run["run_id"]
    export_qa(work, sources, run)
    assert counts(work) == before
    assert before[AgentToolCall.__tablename__] == 0


def test_original_revision_is_not_artifact_revision_and_actual_withdrawal_blocks_new_run(
    source_work,
):
    work = source_work
    original_id, source = uploaded(work)
    run, _ = start(work, [source])
    before = counts(work)
    for ref in (
        {**source, "expected_revision": 2},
        {"artifact_id": str(original_id), "expected_revision": 2},
    ):
        response = work.client.post(
            base(work) + "/agent-runs",
            headers=work.headers,
            json={"goal": GOAL, "idempotency_key": str(uuid4()), "sources": [ref]},
        )
        assert response.status_code in (403, 409), response.text
        assert response.json()["detail"]["reason"] in {"SOURCE_STALE", "SOURCE_UNAVAILABLE"}
    assert counts(work) == before
    with Session(work.admin) as session:
        epoch = session.scalar(
            select(OriginalSecurity.epoch).where(OriginalSecurity.original_id == original_id)
        )
        revision = session.get(Category, work.category).revision
    save(
        work,
        request(
            work,
            "evidence.original.withdraw",
            {
                "original_id": str(original_id),
                "expected_epoch": epoch,
                "reason": "合成来源正式撤回；保留原件和历史。",
            },
            revision=revision,
        ),
    )
    current = ok(bindings(work, run["run_id"]))["items"][0]
    assert current["expected_revision"] == 1
    if current["current"] is not None:
        assert current["current"]["availability"]["available"] is False
    after = counts(work)
    response = work.client.post(
        base(work) + "/agent-runs",
        headers=work.headers,
        json={"goal": GOAL, "idempotency_key": str(uuid4()), "sources": [source]},
    )
    assert response.status_code in (403, 409), response.text
    assert response.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE"
    assert counts(work) == after


def test_scope_rls_peer_tenant_and_current_product_parent_rechecked(source_work):
    work, peer = source_work, actor(source_work, source_work.peer)
    secret = registered(work, title="SYNTHETIC_PRIVATE_SOURCE_TITLE")
    shared = registered(work, product_id=work.product, visibility="category")
    owner_run, _ = start(work, [secret])
    assert ok(listing(peer))["items"] == []
    denied = bindings(peer, owner_run["run_id"])
    assert denied.status_code == 403 and "SYNTHETIC_PRIVATE_SOURCE_TITLE" not in denied.text
    foreign = actor(work, work.other_human)
    assert listing(foreign).status_code == 403
    assert bindings(foreign, owner_run["run_id"]).status_code == 403
    peer_run, _ = start(peer, [shared], product_id=str(work.product))
    assert ok(bindings(peer, peer_run["run_id"]))["items"][0]["current"] is not None
    with Session(work.admin) as session, session.begin():
        session.get(Product, work.product).visibility = "private"
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == work.tenant,
                ObjectAudience.object_type == "products",
                ObjectAudience.subject_id == work.product,
                ObjectAudience.principal_id == peer.human,
            )
        )
    assert listing(peer, product_id=work.product).status_code == 403
    assert bindings(peer, peer_run["run_id"]).status_code == 403
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.category,
                Grant.principal_id == peer.human,
            )
        )
        grant.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    assert listing(peer).status_code == 403


def test_proposal_filter_requires_actual_current_access_on_list_and_binding(source_work):
    work, owner = source_work, actor(source_work, source_work.peer)
    proposal_id, _ = create(owner, {"title": "合成附件范围", "entry_kind": "new_product"})
    save(owner, share_request(owner, proposal_id, visibility="audience", audience_ids=[work.human]))
    source = registered(work)
    assert ok(listing(work, proposal_id=proposal_id))["scope"]["proposal_id"] == proposal_id
    run, _ = start(work, [source], proposal_id=proposal_id)
    assert ok(bindings(work, run["run_id"]))["scope"]["proposal_id"] == proposal_id
    save(
        owner, share_request(owner, proposal_id, visibility="audience", audience_ids=[owner.human])
    )
    assert listing(work, proposal_id=proposal_id).status_code == 404
    assert bindings(work, run["run_id"]).status_code == 404


def test_source_keyset_cursor_stays_inside_exact_scope_and_rejects_extra_queries(source_work):
    work = source_work
    instant = datetime.now(UTC)
    with using_clock(lambda: instant):
        sources = [registered(work, title=f"合成分页 {index}") for index in range(3)]
    expected = sorted((ref["artifact_id"] for ref in sources), reverse=True)
    current, collected = None, []
    for _ in sources:
        page = ok(listing(work, page_size=1, **({"cursor": current} if current else {})))
        collected.extend(row["artifact_id"] for row in page["items"])
        current = page["next_cursor"]
    assert collected == expected and current is None
    product = registered(work, product_id=work.product)
    forbidden_cursor(listing(work, cursor=product["artifact_id"]))
    other = second_category(work)
    different = registered(other)
    forbidden_cursor(listing(work, cursor=different["artifact_id"]))
    assert ok(listing(work, cursor=expected[-1]))["items"] == []
    for params in ({"cursor": "bad"}, {"page_size": 0}, {"page_size": 51}, {"q": "x"}):
        assert listing(work, **params).status_code == 422
    run, _ = start(work, [sources[0]])
    assert bindings(work, run["run_id"], product_id=work.product).status_code == 422


def test_get_only_metadata_projections_never_select_body_and_do_not_write(source_work):
    work = source_work
    _, source = uploaded(work)
    run, _ = start(work, [source])
    before, statements = counts(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.engine, "before_cursor_execute", capture)
    try:
        page = ok(listing(work))
        bound = ok(bindings(work, run["run_id"]))
    finally:
        event.remove(work.engine, "before_cursor_execute", capture)
    for sql in statements:
        assert "FOR UPDATE" not in sql and "FOR SHARE" not in sql
        for name in (
            "artifact_versions.content",
            "artifact_versions.content_hash",
            "uploaded_originals.locator_map",
            "uploaded_originals.parse_manifest",
            "agent_runs.result",
            "agent_runs.versions",
            "agent_runs.customer_identities",
        ):
            assert name not in sql
    encoded = json.dumps([page, bound])
    for secret in (
        "storage_key",
        "content_hash",
        "locator_map",
        "SYNTHETIC_ORIGINAL_BODY_DO_NOT_EXPOSE",
    ):
        assert secret not in encoded
    assert counts(work) == before
