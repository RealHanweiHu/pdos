"""Real human metadata writes and filtered proposal reads, on explicit pdos_test."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.models import Audit, Category, Grant, Outbox, Receipt


def body(**changes):
    return {
        "name": "新的合成品类",
        "purpose": "合成主要场景",
        "expected_revision": 1,
        "idempotency_key": str(uuid4()),
        **changes,
    }


def test_metadata_save_receipt_replay_stale_and_immutable_scope(setup):
    path = f"/v1/categories/{setup.category}/metadata"
    original = setup.client.get(path, headers=setup.headers)
    assert original.status_code == 200 and original.json()["can_edit"]
    request = body()
    saved = setup.client.post(path, headers=setup.headers, json=request)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert (
        setup.client.post(path, headers=setup.headers, json=request).json()["id"] == receipt["id"]
    )
    assert setup.client.post(path, headers=setup.headers, json=body()).status_code == 409
    assert (
        setup.client.post(
            path, headers=setup.headers, json={**request, "name": "不能复用原请求"}
        ).status_code
        == 409
    )
    assert (
        setup.client.post(
            path, headers=setup.headers, json=body(owner_id=str(setup.peer))
        ).status_code
        == 422
    )
    result = setup.client.get(path, headers=setup.headers).json()
    assert (
        result["name"] == request["name"]
        and result["purpose"] == request["purpose"]
        and result["revision"] == 2
    )
    with Session(setup.admin) as session:
        category = session.get(Category, setup.category)
        assert category.owner_id == setup.human
        record = session.scalar(
            select(Receipt).where(
                Receipt.operation == "category.metadata.update",
                Receipt.category_id == setup.category,
            )
        )
        assert record.result["before"]["revision"] == 1
        assert session.scalar(select(Audit).where(Audit.receipt_id == record.id))
        assert session.scalar(select(Outbox).where(Outbox.receipt_id == record.id))


def test_metadata_rechecks_write_permission_before_replay(setup):
    path = f"/v1/categories/{setup.category}/metadata"
    request = body()
    assert setup.client.post(path, headers=setup.headers, json=request).status_code == 200
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.can_write = False
    assert setup.client.get(path, headers=setup.headers).json()["can_edit"] is False
    assert setup.client.post(path, headers=setup.headers, json=request).status_code == 403


def test_metadata_rejects_empty_content_and_unreadable_category(setup):
    path = f"/v1/categories/{setup.category}/metadata"
    assert setup.client.post(path, headers=setup.headers, json=body(name="   ")).status_code == 422
    assert (
        setup.client.post(
            f"/v1/categories/{uuid4()}/metadata", headers=setup.headers, json=body()
        ).status_code
        == 403
    )


def test_candidate_name_and_scene_edits_preserve_original_and_confirmation(setup, tmp_path):
    from copy import deepcopy
    from uuid import UUID

    from pdos_next.agent_kernel.models import AgentEvent
    from tests.agent_kernel.test_category_candidate_transactions import personal_fixture

    fixture = personal_fixture(setup, tmp_path)
    request = deepcopy(fixture.candidate["payload"])
    request.update(
        deidentified_confirmed=True,
        human_edits={"name": "人工完善品类名称", "purpose": "人工完善主要场景"},
    )
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["payload"]["name"] == request["human_edits"]["name"]
    request["confirmation_token"] = preview.json()["confirmation_token"]
    altered = {**request, "human_edits": {"name": "另一名称", "purpose": "另一场景"}}
    assert (
        setup.client.post("/v1/categories", headers=setup.headers, json=altered).status_code == 409
    )
    from sqlalchemy import event

    diagnostics = []

    def capture(context):
        diagnostics.append(str(context.original_exception))

    event.listen(setup.engine, "handle_error", capture)
    try:
        saved = setup.client.post("/v1/categories", headers=setup.headers, json=request)
    finally:
        event.remove(setup.engine, "handle_error", capture)
    assert saved.status_code == 201, (saved.text, diagnostics)
    with Session(setup.admin) as session:
        category = session.get(Category, UUID(saved.json()["subject_id"]))
        assert category.name == request["human_edits"]["name"]
        assert category.purpose == request["human_edits"]["purpose"]
        assert category.created_by_run_id == fixture.run.id
        event = session.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == fixture.run.id,
                AgentEvent.body["type"].astext == "category_candidate",
            )
        )
        assert event.body["input"]["name"] == request["name"]
        receipt = session.get(Receipt, UUID(saved.json()["id"]))
        assert receipt.result["human_edits"] == request["human_edits"]


def test_proposal_search_and_pagination_preserve_scope_and_literal_query(setup):
    from tests.preproject.test_g0 import payload, request
    from tests.products.test_definition_item_commands_pg import confirmed

    for title in ("便携 100% 方案", "便携备选方案", "其他方案"):
        data = payload(setup)
        data["title"] = title
        confirmed(setup, request(setup, "proposal.create", data))
    path = f"/v1/categories/{setup.category}/proposals"
    first = setup.client.get(
        path, headers=setup.headers, params={"q": "便携", "status": "draft", "page_size": 1}
    ).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = setup.client.get(
        path,
        headers=setup.headers,
        params={"q": "便携", "status": "draft", "page_size": 1, "cursor": first["next_cursor"]},
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert second["items"][0]["id"] != first["items"][0]["id"]
    literal = setup.client.get(path, headers=setup.headers, params={"q": "%"}).json()
    assert [row["title"] for row in literal["items"]] == ["便携 100% 方案"]
    assert (
        setup.client.get(path, headers=setup.headers, params={"status": "approved"}).json()["items"]
        == []
    )
    assert (
        setup.client.get(path, headers=setup.headers, params={"status": "unknown"}).status_code
        == 422
    )
    members = setup.client.get(
        f"/v1/categories/{setup.category}/participants", headers=setup.headers
    )
    assert members.status_code == 200
    assert str(setup.human) in {person["id"] for person in members.json()["items"]}
    assert (
        setup.client.get(
            f"/v1/categories/{uuid4()}/participants", headers=setup.headers
        ).status_code
        == 403
    )


def test_category_list_projects_real_owner_visible_models_and_own_drafts(setup):
    from tests.preproject.test_g0 import payload, request
    from tests.products.test_definition_item_commands_pg import confirmed

    confirmed(setup, request(setup, "proposal.create", payload(setup)))
    mine = setup.client.get("/v1/categories", headers=setup.headers)
    assert mine.status_code == 200
    row = next(row for row in mine.json() if row["id"] == str(setup.category))
    assert row["owner_name"] == "Synthetic owner"
    assert row["readable_product_count"] == 1
    assert row["my_draft_count"] == 1
    peer = setup.client.get(
        "/v1/categories", headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    )
    assert peer.status_code == 200
    assert (
        next(row for row in peer.json() if row["id"] == str(setup.category))["my_draft_count"] == 0
    )
    # A valid account in another tenant must not learn these aggregate counts.
    other = setup.client.get(
        "/v1/categories", headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    )
    assert other.status_code == 200
    assert all(row["id"] != str(setup.category) for row in other.json())
