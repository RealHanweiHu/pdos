"""Signed promise metadata, clock and pagination checks without database access."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next import personal_test_start_promises as service
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 17, 12, tzinfo=UTC)


def clock(at, *, actual=False):
    value = {
        "occurred_at": at.isoformat(),
        "original_timezone": "Asia/Shanghai",
        "effective_at": None,
        "source": {
            "id": str(uuid4()),
            "revision": 1,
            "kind": "domain",
            "position": "Private source position must never leave this projection",
        },
    }
    if actual:
        value.update(received_at=(at + timedelta(minutes=2)).isoformat(), actor_id=str(uuid4()))
    return value


def head(ctx, *, ordinal=1, status="planned"):
    scope = {key: uuid4() for key in service.SCOPE}
    scope["tenant_id"] = ctx.tenant_id
    original_id = uuid4()
    current_id = original_id if status == "planned" else uuid4()
    revision = 1 if status == "planned" else 2
    row = {f"fact_{key}": value for key, value in scope.items()}
    row.update(
        fact_id=UUID(int=100 - ordinal),
        fact_created_at=AT - timedelta(days=1),
        fact_owner_id=ctx.requester_id,
        fact_run_version_id=original_id,
        fact_run_revision=1,
        pointer_id=uuid4(),
        pointer_run_version_id=current_id,
        pointer_run_revision=revision,
        promised_id=original_id,
        promised_revision=1,
        promised_status="planned",
        current_id=current_id,
        current_revision=revision,
        current_status=status,
        promise_at=clock(AT + timedelta(hours=1)),
        actual_start=None if status == "planned" else clock(AT, actual=True),
        coverage=[
            {"sample_id": str(UUID(int=11)), "item_id": "pressure"},
            {"sample_id": str(UUID(int=11)), "item_id": "noise"},
            {"sample_id": str(UUID(int=12)), "item_id": "pressure"},
        ],
    )
    for prefix in ("pointer", "promised", "current"):
        for key in service.SCOPE:
            if prefix != "pointer" or key not in {"project_id", "build_id"}:
                row[f"{prefix}_{key}"] = scope[key]
    for prefix in ("product", "category", "project", "build"):
        row.update(
            {
                f"{prefix}_id": scope[f"{prefix}_id"],
                f"{prefix}_name": f"Readable {prefix} {ordinal}",
                f"{prefix}_tenant_id": ctx.tenant_id,
            }
        )
        if prefix != "category":
            row[f"{prefix}_category_id"] = scope["category_id"]
        if prefix in {"project", "build"}:
            row[f"{prefix}_product_id"] = scope["product_id"]
        if prefix == "build":
            row["build_project_id"] = scope["project_id"]
    return row


@pytest.fixture
def world():
    tenant, person = uuid4(), uuid4()
    state = NS(
        ctx=Context(tenant, person, person), at=AT, total=1, rows=[], anchor=None, queries=[]
    )
    state.rows = [head(state.ctx)]

    class Session:
        info = {"scope": (tenant, person, person, None), "read_snapshot": True}

        def check(self, query, operation):
            assert query.is_select and query._for_update_arg is None
            state.queries.append((operation, query))

        def scalar(self, query):
            self.check(query, "scalar")
            if "transaction_timestamp" in str(query):
                return state.at
            assert "count(" in str(query)
            return state.total

        def execute(self, query):
            self.check(query, "execute")
            return NS(
                mappings=lambda: NS(
                    first=lambda: deepcopy(state.anchor), all=lambda: deepcopy(state.rows)
                )
            )

    state.session = Session()
    return state


def read(world, **kwargs):
    return service.read(world.session, world.ctx, **kwargs)


def sql(query):
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def assert_invalid(world, **kwargs):
    with pytest.raises(DomainError) as error:
        read(world, **kwargs)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert "Private source position" not in str(error.value.payload())


def test_contract_preserves_historical_promise_and_current_scope_without_receiver_inference(world):
    result = read(world)
    row = world.rows[0]
    assert result == {
        "version": "personal-test-start-promises/v1",
        "principal_id": str(world.ctx.requester_id),
        "as_of": AT.isoformat(),
        "total_records": 1,
        "items": [
            {
                "id": str(row["fact_id"]),
                "recorded_at": row["fact_created_at"].isoformat(),
                **{
                    prefix: {"id": str(row[f"{prefix}_id"]), "name": row[f"{prefix}_name"]}
                    for prefix in ("category", "product", "project", "build")
                },
                "request": {"id": str(row["fact_request_id"])},
                "run": {"id": str(row["fact_run_id"]), "revision": 1, "status": "planned"},
                "promise": {
                    "occurred_at": "2026-10-17T13:00:00Z",
                    "original_timezone": "Asia/Shanghai",
                    "effective_at": None,
                },
                "actual_start": None,
                "recipient": None,
                "recipient_status": "not_recorded",
                "timing": "awaiting_start",
                "coverage": {"sample_count": 2, "item_count": 2, "pair_count": 3},
            }
        ],
        "next_cursor": None,
    }
    assert "source" not in result["items"][0]["promise"]


@pytest.mark.parametrize(
    "offset,expected",
    [(1, "awaiting_start"), (0, "awaiting_start"), (-1, "past_due_no_start_record")],
)
def test_no_start_uses_snapshot_clock_and_never_declares_breach(world, offset, expected):
    world.rows[0]["promise_at"] = clock(AT + timedelta(seconds=offset))
    assert read(world)["items"][0]["timing"] == expected


@pytest.mark.parametrize("status", ["running", "results_pending", "reviewed", "disposed"])
@pytest.mark.parametrize(
    "offset,expected",
    [(-1, "started_on_or_before"), (0, "started_on_or_before"), (1, "started_late")],
)
def test_actual_start_uses_current_run_but_keeps_promise_original_planned_version(
    world, status, offset, expected
):
    row = world.rows[0] = head(world.ctx, status=status)
    row["actual_start"] = clock(AT + timedelta(seconds=offset), actual=True)
    row["promise_at"] = clock(AT)
    result = read(world)["items"][0]
    assert row["fact_run_version_id"] != row["current_id"]
    assert result["run"]["status"] == status and result["run"]["revision"] == 2
    assert result["timing"] == expected
    assert set(result["actual_start"]) == {
        "occurred_at",
        "original_timezone",
        "effective_at",
        "received_at",
    }
    assert "Private source position" not in str(result) and "actor_id" not in str(result)


def test_time_normalization_preserves_original_timezone_and_effective_at_whitelist(world):
    row = world.rows[0]
    row["promise_at"]["occurred_at"] = "2026-10-17T21:00:00+08:00"
    row["promise_at"]["effective_at"] = "2026-10-17T21:01:00+08:00"
    result = read(world)["items"][0]["promise"]
    assert result == {
        "occurred_at": "2026-10-17T13:00:00Z",
        "original_timezone": "Asia/Shanghai",
        "effective_at": "2026-10-17T13:01:00Z",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("promise_at", None),
        ("promise_at", {"occurred_at": "2026-10-17T13:00:00"}),
        ("coverage", []),
        ("coverage", None),
        ("coverage", {}),
        ("coverage", [{"sample_id": "bad", "item_id": "test"}]),
        ("coverage", [{"sample_id": str(UUID(int=11)), "item_id": "test", "quote": "secret"}]),
        ("current_status", "invented"),
        ("current_revision", 0),
        ("promised_status", "running"),
        ("fact_created_at", datetime(2026, 10, 17)),
    ],
)
def test_corrupt_clock_coverage_or_state_is_explicit_error_not_empty_projection(
    world, field, value
):
    world.rows[0][field] = value
    assert_invalid(world)


@pytest.mark.parametrize(
    "prefix,field",
    [
        ("promise_at", "occurred_at"),
        ("promise_at", "effective_at"),
        ("promise_at", "original_timezone"),
        ("actual_start", "occurred_at"),
        ("actual_start", "received_at"),
        ("actual_start", "original_timezone"),
    ],
)
def test_each_time_component_is_validated_with_existing_dto(world, prefix, field):
    row = world.rows[0] = head(world.ctx, status="running")
    row[prefix][field] = "Invalid/Zone" if field == "original_timezone" else "2026-10-17T13:00:00"
    assert_invalid(world)


def test_coverage_duplicates_are_not_silently_deduplicated(world):
    world.rows[0]["coverage"].append(deepcopy(world.rows[0]["coverage"][0]))
    assert_invalid(world)


@pytest.mark.parametrize("status,actual", [("planned", True), ("running", False)])
def test_start_presence_matches_current_status(world, status, actual):
    row = world.rows[0] = head(world.ctx, status=status)
    row["actual_start"] = clock(AT, actual=True) if actual else None
    assert_invalid(world)


@pytest.mark.parametrize(
    "field",
    [
        "fact_tenant_id",
        "fact_owner_id",
        "product_id",
        "product_category_id",
        "category_id",
        "project_product_id",
        "project_category_id",
        "build_project_id",
        "build_product_id",
        "pointer_product_id",
        "pointer_request_id",
        "pointer_run_id",
        "pointer_run_version_id",
        "promised_id",
        "promised_request_id",
        "promised_project_id",
        "promised_build_id",
        "promised_category_id",
        "current_id",
        "current_run_id",
        "current_product_id",
        "current_request_id",
        "current_project_id",
        "current_build_id",
        "current_tenant_id",
        "current_category_id",
    ],
)
def test_every_selected_identity_chain_is_checked_before_return(world, field):
    world.rows[0][field] = uuid4()
    assert_invalid(world)


@pytest.mark.parametrize("prefix", ["pointer", "promised", "current"])
def test_missing_or_rls_hidden_run_link_is_unavailable_not_fake_empty_queue(world, prefix):
    world.rows[0][f"{prefix}_id"] = None
    with pytest.raises(DomainError) as error:
        read(world)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert "刷新" in error.value.message


def test_metadata_query_never_loads_full_snapshots_sources_or_rechecks_current_roles(world):
    read(world)
    page = next(query for op, query in world.queries if op == "execute")
    text = sql(page)
    assert "verification_launch_facts.input_snapshot['at'] AS promise_at" in text
    assert "current_run.run_snapshot['actual_start'] AS actual_start" in text
    assert "current_run.run_snapshot['coverage'] AS coverage" in text
    for forbidden in (
        "execution_plan",
        "source_basis",
        "authority_snapshot",
        "required_source_read_set",
        "kernel_event",
        ".sources",
        "reason",
        "grants",
        "professional_authority",
        "SET ROLE",
        "set_config",
    ):
        assert forbidden not in text
    assert "verification.schedule.promise" in text
    assert str(world.ctx.tenant_id) in text and str(world.ctx.requester_id) in text
    assert "verification_launch_facts.owner_id =" in text
    assert "LEFT OUTER JOIN verification_current_runs" in text
    assert "LEFT OUTER JOIN verification_run_versions AS promised_run" in text
    assert "LEFT OUTER JOIN verification_run_versions AS current_run" in text
    assert "promised_run.id = verification_launch_facts.run_version_id" in text
    assert "current_run.id = verification_current_runs.run_version_id" in text
    assert (
        "verification_launch_facts.run_version_id = verification_current_runs.run_version_id"
        not in text
    )
    assert all(
        description["expr"] is not description["entity"] for description in page.column_descriptions
    )
    assert page._limit_clause.value == 21


def test_count_cursor_and_page_share_same_filtered_candidate_set(world):
    world.anchor = head(world.ctx, ordinal=0)
    read(world, cursor=world.anchor["fact_id"])
    count = next(query for _, query in world.queries if "count(" in str(query))
    full = count.get_final_froms()[0].element
    anchor, page = [query for op, query in world.queries if op == "execute"]
    assert len(full._where_criteria) == 3
    for query in (anchor, page):
        assert all(
            left.compare(right)
            for left, right in zip(full._where_criteria, query._where_criteria[:3], strict=True)
        )
    assert full._limit_clause is None
    assert "verification_launch_facts.created_at <" not in str(count)
    assert (
        "ORDER BY verification_launch_facts.created_at DESC, verification_launch_facts.id DESC"
        in str(page)
    )
    assert "verification_launch_facts.created_at <" in str(page)
    assert "verification_launch_facts.created_at =" in str(page)
    assert "verification_launch_facts.id <" in str(page)
    assert world.anchor["fact_created_at"] in page.compile().params.values()
    assert world.anchor["fact_id"] in page.compile().params.values()


def test_page_uses_extra_head_cursor_and_full_candidate_total(world):
    world.rows = [head(world.ctx), head(world.ctx, ordinal=2)]
    world.total = 8
    result = read(world, page_size=1)
    assert result["total_records"] == 8 and len(result["items"]) == 1
    assert result["next_cursor"] == str(world.rows[0]["fact_id"])
    assert result["next_cursor"] != str(world.rows[1]["fact_id"])


def test_broken_lookahead_head_fails_entire_get_instead_of_partial_page(world):
    bad = head(world.ctx, ordinal=2)
    bad["current_id"] = None
    world.rows.append(bad)
    with pytest.raises(DomainError) as error:
        read(world, page_size=1)
    assert error.value.code == "SOURCE_UNAVAILABLE"


def test_cursor_is_revalidated_including_its_run_dependencies(world):
    world.anchor = head(world.ctx)
    world.anchor["pointer_id"] = None
    with pytest.raises(DomainError) as error:
        read(world, cursor=str(world.anchor["fact_id"]))
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert len(world.queries) == 2


def test_missing_cursor_rejects_without_partial_page_or_count(world):
    with pytest.raises(DomainError) as error:
        read(world, cursor=uuid4())
    assert error.value.code == "FORBIDDEN_SCOPE" and error.value.status == 403
    assert "刷新" in error.value.message and len(world.queries) == 2


def test_no_readable_facts_returns_real_zero_in_same_transaction_clock(world):
    world.rows, world.total = [], 0
    result = read(world)
    assert result["total_records"] == 0 and result["items"] == [] and result["next_cursor"] is None
    assert result["as_of"] == AT.isoformat()


@pytest.mark.parametrize("page_size", [0, 101, True, "2"])
def test_bad_page_size_never_issues_sql(world, page_size):
    with pytest.raises(DomainError) as error:
        read(world, page_size=page_size)
    assert error.value.code == "VALIDATION_FAILED" and world.queries == []


@pytest.mark.parametrize("cursor", ["", "bad", 17])
def test_malformed_cursor_never_issues_sql(world, cursor):
    with pytest.raises(DomainError) as error:
        read(world, cursor=cursor)
    assert error.value.code == "VALIDATION_FAILED" and world.queries == []


@pytest.mark.parametrize("mode", ["category", "delegated", "other_transaction"])
def test_ordinary_personal_scope_is_enforced_before_any_sql(world, mode):
    if mode == "category":
        world.ctx = replace(world.ctx, category_id=uuid4())
    elif mode == "delegated":
        world.ctx = replace(world.ctx, actor_id=uuid4())
        world.session.info = {}
    else:
        world.session.info = {"scope": (uuid4(), world.ctx.actor_id, world.ctx.requester_id, None)}
    with pytest.raises(DomainError) as error:
        read(world)
    assert error.value.code == "FORBIDDEN_SCOPE" and world.queries == []


def test_transaction_clock_is_aware_and_read_does_not_mutate_session_or_facts(world):
    before_info, before_rows = deepcopy(world.session.info), deepcopy(world.rows)
    read(world)
    assert world.session.info == before_info and world.rows == before_rows
    assert len(world.queries) == 3
    world.at = datetime(2026, 10, 17)
    assert_invalid(world)
