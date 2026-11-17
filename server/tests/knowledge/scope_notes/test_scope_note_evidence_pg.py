"""D509: the page links evidence and other formal objects; history shows what each link is.

The page offers what ``scope-note-sources`` lists (read under the reader's own
row-level security); the command checks every link again. Real commands, real
roles; no model call.
"""

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun
from pdos_next.core.models import Artifact
from tests.agent.kernel.test_run_continuation import synthetic_artifact
from tests.agent.memory.support import start
from tests.g0_fixture import create_g0_project
from tests.knowledge.scope_notes.support import (
    OBSERVE,
    anchor,
    commit,
    headers,
    item,
    preview,
    save,
)


def sources(setup, kind, identity, *, person=None, status=200):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/scope-note-sources/{kind}/{identity}",
        headers=headers(setup, person))
    assert response.status_code == status, response.text
    return response.json()


def link(option, **extra):
    return {"source_type": option["source_type"], "source_id": option["source_id"],
            **({"source_kind": option["source_kind"]} if option["source_kind"] else {}), **extra}


def test_sources_link_and_history_show_each_link_as_the_reader_may_see_it(setup):
    project = create_g0_project(setup, visibility="category", name="Synthetic pump project")
    at = anchor(setup, "project", project.project_id)
    run_id, _ = start(setup, goal="整理样件约定", product_id=project.product_id,
                      project_id=project.project_id)
    with Session(setup.admin) as session, session.begin():
        row = session.get(AgentRun, run_id)
        row.state, row.result = "completed", {"summary": "合成结果", "unfinished": []}
    material = synthetic_artifact(setup, "样件编号规则说明")
    listed = sources(setup, "project", project.project_id)
    assert listed["version"] == "scope-note-sources/v1"
    by_type = {}
    for option in listed["sources"]:
        by_type.setdefault(option["source_type"], []).append(option)
    kinds = {option["source_kind"] for option in listed["formal"]}
    assert kinds == {"project", "product", "category", "proposal_decision"}
    decision = next(o for o in listed["formal"] if o["source_kind"] == "proposal_decision")
    assert decision["title"].endswith("的 G0 决定") and decision["type_label"] == "G0 决定"
    assert [o["source_id"] for o in by_type["run"]] == [str(run_id)]
    assert by_type["run"][0]["title"].endswith("整理样件约定")
    assert str(material) in {o["source_id"] for o in by_type["original"]}
    assert by_type["receipt"], "the G0 decision's own receipt is offered"
    # Titles only: no material text and no Run answer.
    assert "真实固定原文" not in json.dumps(listed, ensure_ascii=False)
    assert "合成结果" not in json.dumps(listed, ensure_ascii=False)
    # 挂别的正式对象: a 决策背景 hangs on the G0 decision instead of the project itself.
    saved = save(setup, "样件编号按 项目-批次-序号，是 G0 评审时定的", kind="decision_context",
                 at=at, product=project.product_id,
                 formal={"kind": "proposal_decision", "id": decision["source_id"]})
    note = item(setup, saved["subject_id"])["note"]
    assert note["formal"]["kind"] == "proposal_decision"
    assert note["formal"]["title"] == decision["title"]
    assert note["confirmation"] == "formal_linked" and "no_formal_decision" not in note["flags"]
    # 加证据链接: four kinds of source in one command, previewed then confirmed once.
    receipt = by_type["receipt"][0]
    original = next(o for o in by_type["original"] if o["source_id"] == str(material))
    payload = {"mode": "evidence", "note": {"id": saved["subject_id"], "revision": 1},
               "evidence": [link(by_type["run"][0], locator={"where": "第 2 轮"}),
                            link(original, quote="样件编号按项目-批次-序号", stance="supports"),
                            link(receipt, stance="context"),
                            link(decision, stance="supports")]}
    prepared = preview(setup, OBSERVE, payload, product=project.product_id)
    assert prepared["review"]["evidence_added"] == 4
    commit(setup, OBSERVE, payload, product=project.product_id)
    history = item(setup, saved["subject_id"])
    links = {entry["source_type"]: entry for entry in history["note"]["evidence"]}
    assert set(links) == {"run", "original", "receipt", "business_object"}
    assert links["run"]["title"].endswith("整理样件约定")
    assert links["run"]["locator"] == {"where": "第 2 轮"}
    assert links["original"]["title"] == "样件编号规则说明" and links["original"]["has_quote"]
    assert links["original"]["stance_label"] == "支持" and links["receipt"]["stance_label"] == "背景"
    assert links["business_object"]["type_label"] == "G0 决定"
    assert "样件编号按项目-批次-序号" not in json.dumps(history["note"]["evidence"],
                                                     ensure_ascii=False)
    assert [v["action"] for v in history["versions"]] == ["add_evidence", "create"]
    # The peer reads the note (category audience) but not the owner's Run or private
    # material: those links show as 当前不可读, and the peer is never offered them.
    peer_view = item(setup, saved["subject_id"], person=setup.peer)["note"]["evidence"]
    titles = {entry["source_type"]: entry["title"] for entry in peer_view}
    assert titles["run"] is None and titles["original"] is None
    assert titles["business_object"] == decision["title"]
    offered = sources(setup, "project", project.project_id, person=setup.peer)["sources"]
    assert str(run_id) not in {o["source_id"] for o in offered}
    assert str(material) not in {o["source_id"] for o in offered}
    # The page makes no permission decision: a link the peer cannot read is refused
    # by the command itself.
    refused = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=headers(setup, setup.peer),
        json={"category_id": str(setup.category), "command_id": str(uuid4()),
              "idempotency_key": str(uuid4()), "operation": OBSERVE,
              "product_id": project.product_id, "expected_revision": 1,
              "source_read_set": [],
              "payload": {**payload, "note": {"id": saved["subject_id"], "revision": 2},
                          "evidence": [link(original)]}})
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason_key"] == "scope_note_evidence_unreadable"


def test_an_unreadable_scope_lists_nothing(setup):
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        from pdos_next.core.models import Product

        session.add(Product(id=identity, tenant_id=setup.tenant, category_id=setup.category,
                            name="Synthetic private product", purpose="Owner only",
                            owner_id=setup.human, visibility="private"))
    assert sources(setup, "product", identity)["formal"][0]["source_kind"] == "product"
    refused = sources(setup, "product", identity, person=setup.peer, status=403)
    assert refused["detail"]["reason_key"] == "scope_note_anchor_unreadable"
    assert Artifact  # imported for the synthetic material registry
