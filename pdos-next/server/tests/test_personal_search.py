"""Actual object lookup with current personal RLS, metadata-only reads and stable paging."""

import json
from copy import copy
from datetime import timedelta
from time import perf_counter
from uuid import UUID, uuid4

from g0_fixture import create_g0_project
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.models import Category, Grant, Product, Receipt, now
from tests.preproject.test_g0 import create, payload
from tests.test_personal_views import second_category


def search(setup, q, *, actor=None, **kwargs):
    return setup.client.get(
        "/v1/personal/search",
        params={"q": q, **kwargs},
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )


def seed(setup):
    first = create_g0_project(copy(setup), name="便携充气泵研发")
    other = second_category(setup)
    with Session(setup.admin) as session, session.begin():
        session.get(Category, other.category).name = "自行车充气泵"
    second = create_g0_project(other, name="自行车充气泵开发")
    return first, other, second


def test_cross_category_actual_objects_are_metadata_only_and_read_only(setup):
    first, other, second = seed(setup)
    with Session(setup.admin) as session:
        before = session.scalar(
            select(func.count())
            .select_from(Receipt)
            .where(
                Receipt.tenant_id == setup.tenant,
            )
        )
    statements = []

    def capture(_c, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", capture)
    started = perf_counter()
    try:
        response = search(setup, "充气")
    finally:
        event.remove(setup.engine, "before_cursor_execute", capture)
    elapsed = round((perf_counter() - started) * 1000, 2)
    assert response.status_code == 200, response.text
    value = response.json()
    assert {row["kind"] for row in value["items"]} == {
        "category",
        "project",
        "product",
        "proposal",
    }
    assert {row["category_id"] for row in value["items"]} == {
        str(setup.category),
        str(other.category),
    }
    assert {row["id"] for row in value["items"] if row["kind"] == "project"} == {
        first.project_id,
        second.project_id,
    }
    assert value["as_of"] and value["next_cursor"] is None
    assert all(
        set(row)
        == {
            "kind",
            "id",
            "title",
            "category_id",
            "category_name",
            "product_id",
        }
        for row in value["items"]
    )
    assert not any(
        "proposals.brief" in sql
        or "proposal_item_versions" in sql
        or "artifact_versions.content" in sql
        for sql in statements
    )
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(
                    Receipt.tenant_id == setup.tenant,
                )
            )
            == before
        )
    print(
        json.dumps(
            dict(
                search_ms=elapsed,
                sql_count=len(statements),
                model_calls=0,
                browser_fixture=dict(
                    tenant_id=str(setup.tenant),
                    actor_id=str(setup.human),
                    category_ids=[str(setup.category), str(other.category)],
                    project_id=first.project_id,
                    product_id=first.product_id,
                    proposal_id=first.proposal_id,
                ),
            )
        )
    )


def test_paging_covers_all_kinds_and_binds_original_query_and_filter(setup):
    seed(setup)
    expected = search(setup, "充气").json()["items"]
    rows, cursor = [], None
    while True:
        page = search(setup, "充气", page_size=2, **({"cursor": cursor} if cursor else {}))
        assert page.status_code == 200, page.text
        value = page.json()
        rows.extend(value["items"])
        cursor = value["next_cursor"]
        if not cursor:
            break
        assert search(setup, "泵", cursor=cursor).status_code == 409
        assert search(setup, "充气", kind="project", cursor=cursor).status_code == 409
    assert rows == expected
    assert len({(row["kind"], row["id"]) for row in rows}) == len(rows)


def test_private_draft_and_other_tenant_are_filtered_before_search_output(setup):
    data = payload(setup)
    data.update(title="合成私有提案", brief="Only-Body-Sentinel")
    identity, _ = create(setup, data)
    assert search(setup, identity).json()["items"][0]["id"] == identity
    assert search(setup, "Only-Body-Sentinel").json()["items"] == []
    assert search(setup, identity, actor=setup.peer).json()["items"] == []
    assert search(setup, identity, actor=setup.other_human).json()["items"] == []


def test_current_grant_revocation_hides_results_and_invalidates_cursor(setup):
    other = second_category(setup)
    response = search(setup, "", kind="category")
    assert response.status_code == 422
    with Session(setup.admin) as session, session.begin():
        session.get(Category, other.category).name = "汽车合成充气品类"
    first = search(setup, "汽车", kind="category", page_size=1).json()
    assert first["next_cursor"]
    hidden = UUID(first["items"][0]["category_id"])
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(Grant).where(
                Grant.category_id == hidden,
                Grant.principal_id == setup.human,
            )
        ).expires_at = now() - timedelta(seconds=1)
    assert all(
        row["category_id"] != str(hidden)
        for row in search(setup, "汽车", kind="category").json()["items"]
    )
    assert search(setup, "汽车", kind="category", cursor=first["next_cursor"]).status_code == 409


def test_literal_wildcards_exact_identity_and_exact_title_priority(setup):
    with Session(setup.admin) as session, session.begin():
        session.get(Product, setup.product).name = "100%_READY"
        older, newer = uuid4(), uuid4()
        session.add_all(
            [
                Product(
                    id=identity,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    owner_id=setup.human,
                    name=name,
                    purpose="Synthetic search fixture",
                    created_at=now() - timedelta(minutes=offset),
                )
                for identity, name, offset in ((older, "Needle", 2), (newer, "Needle extra", 1))
            ]
        )
    for q in ("%", "_READY", str(setup.product)):
        result = search(setup, q)
        assert result.status_code == 200, result.text
        assert [row["id"] for row in result.json()["items"]] == [str(setup.product)]
    assert search(setup, str(setup.product), kind="project").json()["items"] == []
    assert search(setup, "Needle").json()["items"][0]["id"] == str(older)


def test_search_rejects_forged_scopes_and_malformed_query(setup):
    for query in (
        {"q": " "},
        {"q": "x" * 201},
        {"q": "x", "kind": "claim"},
        {"q": "x", "page_size": 101},
        {"q": "x", "cursor": "bad"},
        {"q": "x", "category_id": str(setup.category)},
        {"q": "x", "tenant_id": str(setup.other_tenant)},
    ):
        response = setup.client.get("/v1/personal/search", params=query, headers=setup.headers)
        assert response.status_code == 422, response.text
