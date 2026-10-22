"""Personal G0 metadata projection checks without opening a database connection."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest

from pdos_next import personal_g0_reviews as service
from pdos_next.errors import DomainError
from pdos_next.service import Context


def head(ctx, *, ordinal=1, owner_name="Readable owner"):
    return {
        "proposal_id": uuid4(),
        "title": f"Current proposal title {ordinal}",
        "proposal_revision": 11,
        "status": "in_review",
        "category_id": uuid4(),
        "category_name": f"Readable category {ordinal}",
        "owner_id": uuid4(),
        "owner_name": owner_name,
        "reviewer_id": ctx.requester_id,
        "submission_id": UUID(int=100 - ordinal),
        "submission_revision": 8,
        "submitted_at": datetime(2026, 10, 17, 8, tzinfo=UTC),
        "document_digest": str(ordinal) * 64,
    }


@pytest.fixture
def world():
    tenant, requester = uuid4(), uuid4()
    ctx = Context(tenant, requester, requester)
    state = NS(
        ctx=ctx,
        at=datetime(2026, 10, 17, 9, tzinfo=UTC),
        rows=[head(ctx)],
        total=1,
        anchor=None,
        queries=[],
    )

    class Session:
        info = {"scope": (tenant, requester, requester, None), "read_snapshot": True}

        def check(self, query, operation):
            assert query.is_select
            assert query._for_update_arg is None
            state.queries.append((operation, query))

        def execute(self, query):
            self.check(query, "execute")
            if list(query.selected_columns.keys()) == ["id", "created_at"]:
                return NS(first=lambda: state.anchor)
            return NS(mappings=lambda: NS(all=lambda: deepcopy(state.rows)))

        def scalar(self, query):
            self.check(query, "scalar")
            if "transaction_timestamp" in str(query):
                return state.at
            assert "count(" in str(query)
            return state.total

    state.session = Session()
    return state


def read(world, **kwargs):
    return service.read(world.session, world.ctx, **kwargs)


def query_for(world, contains):
    return next(query for _, query in world.queries if contains in str(query))


def assert_pending_predicate(query, ctx):
    sql = str(query)
    assert "proposals.tenant_id =" in sql
    assert ctx.tenant_id in query.compile().params.values()
    assert "proposals.status =" in sql
    assert "in_review" in query.compile().params.values()
    assert "proposal_submissions.reviewer_id =" in sql
    assert ctx.requester_id in query.compile().params.values()
    assert "proposal_submissions.tenant_id = proposals.tenant_id" in sql
    assert "proposal_submissions.category_id = proposals.category_id" in sql
    assert "proposal_submissions.proposal_id = proposals.id" in sql
    assert "proposal_submissions.id = proposals.current_submission_id" in sql
    assert "m3_reviewer(proposals.tenant_id, proposals.category_id, proposals.id)" in sql
    assert "NOT (EXISTS" in sql
    assert "proposal_decisions.tenant_id = proposals.tenant_id" in sql
    assert "proposal_decisions.category_id = proposals.category_id" in sql
    assert "proposal_decisions.proposal_id = proposals.id" in sql
    assert "proposal_decisions.submission_id = proposal_submissions.id" in sql


def test_returns_current_head_and_fixed_submission_metadata_with_snapshot_total(world):
    result = read(world)
    row = world.rows[0]
    assert result == {
        "version": "personal-g0-reviews/v1",
        "principal_id": str(world.ctx.requester_id),
        "as_of": world.at.isoformat(),
        "total_pending": 1,
        "items": [
            {
                "proposal_id": str(row["proposal_id"]),
                "title": "Current proposal title 1",
                "proposal_revision": 11,
                "status": "in_review",
                "category": {"id": str(row["category_id"]), "name": "Readable category 1"},
                "owner": {"id": str(row["owner_id"]), "name": "Readable owner"},
                "reviewer_id": str(world.ctx.requester_id),
                "submission": {
                    "id": str(row["submission_id"]),
                    "revision": 8,
                    "submitted_at": row["submitted_at"].isoformat(),
                    "document_digest": "1" * 64,
                },
            }
        ],
        "next_cursor": None,
    }
    assert result["items"][0]["proposal_revision"] != result["items"][0]["submission"]["revision"]


def test_count_and_page_share_full_rls_visible_pending_predicate(world):
    read(world)
    count = query_for(world, "count(")
    page = next(query for op, query in world.queries if op == "execute")
    assert_pending_predicate(count, world.ctx)
    assert_pending_predicate(page, world.ctx)
    full = count.get_final_froms()[0].element
    assert len(full._where_criteria) == len(page._where_criteria)
    assert all(
        left.compare(right)
        for left, right in zip(full._where_criteria, page._where_criteria, strict=True)
    )
    assert full._limit_clause is None and full._order_by_clauses == ()


def test_selects_only_metadata_with_ordinary_category_and_nullable_owner_joins(world):
    read(world)
    for _, query in world.queries:
        sql = str(query)
        for forbidden in (
            "frozen_document",
            "brief",
            "source_refs",
            "context_refs",
            "customer_identities",
            "option_count",
            "no_alternative_reason",
            "rationale",
            "dispositions",
        ):
            assert forbidden not in sql
        assert "set_config" not in sql and "SET ROLE" not in sql
    page = next(query for op, query in world.queries if op == "execute")
    sql = str(page)
    assert "JOIN categories ON categories.tenant_id = proposals.tenant_id" in sql
    assert "categories.id = proposals.category_id" in sql
    assert "LEFT OUTER JOIN principals ON principals.tenant_id = proposals.tenant_id" in sql
    assert "principals.id = proposals.owner_id" in sql
    assert all(
        description["expr"] is not description["entity"] for description in page.column_descriptions
    )


def test_unreadable_owner_name_does_not_drop_review_action(world):
    world.rows[0]["owner_name"] = None
    result = read(world)
    assert result["total_pending"] == 1
    assert result["items"][0]["owner"] == {"id": str(world.rows[0]["owner_id"]), "name": None}


def test_empty_pending_set_returns_zero_without_unknown_or_inferred_counts(world):
    world.rows, world.total = [], 0
    result = read(world)
    assert result["items"] == [] and result["total_pending"] == 0
    assert result["next_cursor"] is None
    assert set(result) == {
        "version",
        "principal_id",
        "as_of",
        "total_pending",
        "items",
        "next_cursor",
    }


@pytest.mark.parametrize("page_size", [0, -1, 101, True, False, 1.5, "2", None])
def test_invalid_page_size_rejected_without_queries(world, page_size):
    with pytest.raises(DomainError) as error:
        read(world, page_size=page_size)
    assert error.value.code == "VALIDATION_FAILED" and error.value.status == 422
    assert world.queries == []


@pytest.mark.parametrize("cursor", ["", "not-a-uuid", "1234", 42, True, object()])
def test_malformed_submission_cursor_rejected_without_queries(world, cursor):
    with pytest.raises(DomainError) as error:
        read(world, cursor=cursor)
    assert error.value.code == "VALIDATION_FAILED" and error.value.status == 422
    assert world.queries == []


@pytest.mark.parametrize("page_size,limit", [(1, 2), (50, 51), (100, 101)])
def test_page_bounds_use_one_extra_head_not_a_partial_total(world, page_size, limit):
    world.total = 123
    result = read(world, page_size=page_size)
    page = next(query for op, query in world.queries if op == "execute")
    assert page._limit_clause.value == limit
    assert result["total_pending"] == 123
    assert "ORDER BY proposal_submissions.created_at DESC, proposal_submissions.id DESC" in str(
        page
    )


def test_next_cursor_is_last_returned_submission_not_proposal_or_extra_row(world):
    world.rows = [head(world.ctx, ordinal=1), head(world.ctx, ordinal=2)]
    world.total = 7
    result = read(world, page_size=1)
    assert len(result["items"]) == 1 and result["total_pending"] == 7
    assert result["next_cursor"] == str(world.rows[0]["submission_id"])
    assert result["next_cursor"] != str(world.rows[0]["proposal_id"])
    assert result["next_cursor"] != str(world.rows[1]["submission_id"])


@pytest.mark.parametrize("as_text", [False, True])
def test_cursor_keyset_uses_submission_time_and_uuid_tie_breaker(world, as_text):
    anchor = head(world.ctx, ordinal=1)
    world.anchor = NS(id=anchor["submission_id"], created_at=anchor["submitted_at"])
    world.rows = [head(world.ctx, ordinal=2)]
    world.total = 2
    cursor = str(world.anchor.id) if as_text else world.anchor.id
    result = read(world, cursor=cursor, page_size=1)
    anchor_query = world.queries[0][1]
    assert_pending_predicate(anchor_query, world.ctx)
    assert list(anchor_query.selected_columns.keys()) == ["id", "created_at"]
    assert world.anchor.id in anchor_query.compile().params.values()
    page = next(
        query for op, query in world.queries if op == "execute" and query is not anchor_query
    )
    sql = str(page)
    assert "proposal_submissions.created_at <" in sql
    assert "proposal_submissions.created_at =" in sql
    assert "proposal_submissions.id <" in sql
    assert world.anchor.created_at in page.compile().params.values()
    assert world.anchor.id in page.compile().params.values()
    count = query_for(world, "count(")
    assert "created_at <" not in str(count) and "proposal_submissions.id <" not in str(count)
    assert result["total_pending"] == 2 and result["next_cursor"] is None


def test_semantically_invalid_or_no_longer_pending_cursor_requires_refresh_without_partial_page(
    world,
):
    world.anchor = None
    world.rows = [head(world.ctx)]
    with pytest.raises(DomainError) as error:
        read(world, cursor=uuid4())
    assert error.value.code == "FORBIDDEN_SCOPE" and error.value.status == 403
    assert "刷新" in error.value.message
    assert len(world.queries) == 1
    assert_pending_predicate(world.queries[0][1], world.ctx)


@pytest.mark.parametrize(
    "mode", ["category", "delegated", "wrong_tenant", "wrong_actor", "wrong_category"]
)
def test_personal_scope_cannot_borrow_category_or_other_identity_transaction(world, mode):
    if mode == "category":
        world.ctx = replace(world.ctx, category_id=uuid4())
    elif mode == "delegated":
        world.ctx = replace(world.ctx, actor_id=uuid4())
        world.session.info = {}
    else:
        tenant, actor, requester, category = world.session.info["scope"]
        world.session.info = {
            "scope": (
                uuid4() if mode == "wrong_tenant" else tenant,
                uuid4() if mode == "wrong_actor" else actor,
                requester,
                uuid4() if mode == "wrong_category" else category,
            )
        }
    with pytest.raises(DomainError) as error:
        read(world)
    assert error.value.code == "FORBIDDEN_SCOPE" and error.value.status == 403
    assert world.queries == []


def test_read_keeps_the_same_rr_rls_session_without_mutating_scope_or_rows(world):
    original_info = deepcopy(world.session.info)
    original_rows = deepcopy(world.rows)
    read(world)
    assert world.session.info == original_info
    assert world.rows == original_rows
    assert len(world.queries) == 3
    assert all(query.is_select and query._for_update_arg is None for _, query in world.queries)
    assert query_for(world, "transaction_timestamp") is world.queries[-1][1]


def test_cursor_time_can_differ_from_proposal_head_revision_and_submission_revision(world):
    row = world.rows[0]
    world.anchor = NS(id=uuid4(), created_at=row["submitted_at"] + timedelta(days=1))
    read(world, cursor=world.anchor.id)
    page = world.queries[-2][1]
    assert world.anchor.created_at in page.compile().params.values()
    assert "proposals.created_at" not in str(page)
    assert "proposals.revision <" not in str(page)
    assert "proposal_submissions.revision <" not in str(page)
