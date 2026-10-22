"""Personal current work DTO and query contracts without database execution."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from pdos_next import personal_project_work as projection
from pdos_next.domain.work_management.models import WorkCommitmentVersion, WorkTaskVersion
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 18, 9, tzinfo=UTC)


def head(ctx, queue="receive", ordinal=1, **changes):
    binding = {key: uuid4() for key in projection.BINDING}
    binding.update(tenant_id=ctx.tenant_id, visibility="category")
    stable, version = UUID(int=100 - ordinal), uuid4()
    state = {
        "receive": "assigned",
        "verify": "submitted",
        "tasks": "accepted",
        "commitments": "in_progress",
    }[queue]
    assignee = uuid4() if queue == "verify" else ctx.requester_id
    recipient = ctx.requester_id if queue == "verify" else uuid4()
    row = {f"task_{key}": value for key, value in binding.items()}
    row.update(
        task_id=version,
        task_task_id=stable,
        task_revision=5,
        task_state=state,
        task_created_at=AT - timedelta(days=1),
        pointer_id=uuid4(),
        snapshot_task_id=str(stable),
        snapshot_revision="5",
        snapshot_state=state,
        task_title=f"实际任务 {ordinal}",
        assignee_id=str(assignee),
        assignee_name="可读承接人",
        recipient_id=str(recipient),
        recipient_name="可读接收人",
    )
    for key, value in {
        **binding,
        "task_id": stable,
        "version_id": version,
        "revision": 5,
        "state": state,
    }.items():
        row[f"pointer_{key}"] = value
    for prefix in ("category", "product", "project"):
        row.update(
            {
                f"{prefix}_id": binding[f"{prefix}_id"],
                f"{prefix}_name": f"实际{prefix}",
                f"{prefix}_tenant_id": ctx.tenant_id,
            }
        )
        if prefix in {"product", "project"}:
            row[f"{prefix}_category_id"] = binding["category_id"]
        if prefix == "project":
            for key in ("product_id", "owner_id", "visibility"):
                row[f"project_{key}"] = binding[key]
    if queue == "commitments":
        commitment_id, series = UUID(int=200 - ordinal), uuid4()
        for key, value in binding.items():
            row[f"commitment_{key}"] = row[f"commitment_pointer_{key}"] = value
        row.update(
            commitment_id=commitment_id,
            commitment_series_id=series,
            commitment_revision=2,
            commitment_task_id=stable,
            commitment_task_revision=3,
            commitment_promisor_id=ctx.requester_id,
            commitment_recipient_id=recipient,
            commitment_outcome_keys=["report"],
            commitment_promised_at=AT + timedelta(hours=1),
            commitment_original_timezone="Asia/Shanghai",
            commitment_calendar_id=None,
            commitment_created_at=AT - timedelta(hours=1),
            commitment_pointer_id=uuid4(),
        )
        for key, value in {
            "task_id": stable,
            "promisor_id": ctx.requester_id,
            "recipient_id": recipient,
            "series_id": series,
            "version_id": commitment_id,
            "revision": 2,
        }.items():
            row[f"commitment_pointer_{key}"] = value
    row.update(changes)
    return row


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Personal work pure checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def world():
    tenant, person = uuid4(), uuid4()
    state = NS(
        ctx=Context(tenant, person, person), at=AT, total=1, rows=[], anchor=None, queries=[]
    )
    state.rows = [head(state.ctx)]

    class Session:
        info = {"scope": (tenant, person, person, None), "read_snapshot": True}

        def check(self, query):
            assert query.is_select and query._for_update_arg is None
            state.queries.append(query)

        def scalar(self, query):
            self.check(query)
            if "transaction_timestamp" in str(query):
                return state.at
            assert "count(" in str(query)
            return state.total

        def execute(self, query):
            self.check(query)
            return NS(
                mappings=lambda: NS(
                    first=lambda: deepcopy(state.anchor), all=lambda: deepcopy(state.rows)
                )
            )

    state.session = Session()
    return state


def read(world, queue="receive", **options):
    return projection.read(world.session, world.ctx, queue, **options)


def query_sql(query):
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def assert_invalid(world, queue="receive"):
    with pytest.raises(DomainError) as error:
        read(world, queue)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_exact_dto_uses_stable_task_and_current_fact_refs(world):
    result, row = read(world), world.rows[0]
    assert result == {
        "version": "personal-project-work/v1",
        "principal_id": str(world.ctx.requester_id),
        "as_of": AT.isoformat(),
        "queue": "receive",
        "total_records": 1,
        "next_cursor": None,
        "items": [
            {
                "id": str(row["task_task_id"]),
                **{
                    prefix: {"id": str(row[f"{prefix}_id"]), "name": row[f"{prefix}_name"]}
                    for prefix in ("category", "product", "project")
                },
                "task": {
                    "id": str(row["task_task_id"]),
                    "version_id": str(row["task_id"]),
                    "revision": 5,
                    "state": "assigned",
                    "title": row["task_title"],
                },
                "assignee": {"id": row["assignee_id"], "name": row["assignee_name"]},
                "recipient": {"id": row["recipient_id"], "name": row["recipient_name"]},
                "recorded_at": row["task_created_at"].isoformat(),
                "commitment": None,
                "timing": None,
            }
        ],
    }


@pytest.mark.parametrize("queue", ["receive", "verify", "tasks", "commitments"])
def test_each_queue_has_its_actual_current_state_and_person_predicate(world, queue):
    world.rows = [head(world.ctx, queue)]
    result = read(world, queue)
    assert result["queue"] == queue and len(result["items"]) == 1
    records = projection._records(world.ctx, queue)
    sql = query_sql(records)
    assert str(world.ctx.requester_id) in sql
    if queue == "commitments":
        assert "work_commitment_versions.promisor_id =" in sql
        assert "work_task_versions.state != 'completed'" not in sql
        assert result["items"][0]["id"] == str(world.rows[0]["commitment_id"])
        assert result["items"][0]["commitment"]["task_revision"] == 3
        assert result["items"][0]["task"]["revision"] == 5
    else:
        assert "work_task_versions.state IN" in sql
        for state in projection.TASK_STATES[queue]:
            assert f"'{state}'" in sql


def test_tasks_excludes_assigned_and_verify_tracks_actual_recipient(world):
    world.rows = [head(world.ctx, "tasks", task_state="assigned", snapshot_state="assigned")]
    assert_invalid(world, "tasks")
    world.rows = [head(world.ctx, "verify", recipient_id=str(uuid4()))]
    assert_invalid(world, "verify")


@pytest.mark.parametrize(
    "minutes,timing", [(None, "unknown"), (-1, "overdue"), (0, "pending"), (1, "pending")]
)
def test_commitment_preserves_unknown_date_original_timezone_and_each_receiver(
    world, minutes, timing
):
    promised = None if minutes is None else AT + timedelta(minutes=minutes)
    world.rows = [
        head(world.ctx, "commitments", ordinal=index, commitment_promised_at=promised)
        for index in (1, 2)
    ]
    world.total = 2
    result = read(world, "commitments")
    assert len(result["items"]) == 2
    assert result["items"][0]["recipient"]["id"] != result["items"][1]["recipient"]["id"]
    for item in result["items"]:
        assert item["timing"] == timing
        assert item["commitment"]["original_timezone"] == "Asia/Shanghai"
        assert item["commitment"]["calendar_id"] is None
        assert item["commitment"]["promised_at"] == (promised.isoformat() if promised else None)


def test_name_visibility_never_removes_actual_action_or_receiver(world):
    world.rows[0].update(assignee_name=None, recipient_name=None)
    item = read(world)["items"][0]
    assert item["assignee"] == {"id": str(world.ctx.requester_id), "name": None}
    assert item["recipient"] == {"id": world.rows[0]["recipient_id"], "name": None}


def test_cross_category_records_are_kept_in_same_personal_snapshot(world):
    world.rows = [head(world.ctx, ordinal=index) for index in (1, 2)]
    world.total = 2
    result = read(world)
    assert len({item["category"]["id"] for item in result["items"]}) == 2
    assert result["total_records"] == 2
    records = projection._records(world.ctx, "receive")
    assert all(value is not None for value in records.compile().params.values())


def test_page_lookahead_is_not_silently_truncated_and_count_is_whole_queue(world):
    world.rows = [head(world.ctx, ordinal=index) for index in (1, 2)]
    world.total = 6
    result = read(world, page_size=1)
    assert len(result["items"]) == 1 and result["total_records"] == 6
    assert result["next_cursor"] == str(world.rows[0]["task_task_id"])
    count = next(query for query in world.queries if "count(" in str(query))
    page = world.queries[-1]
    full = count.get_final_froms()[0].element
    assert all(
        a.compare(b) for a, b in zip(full._where_criteria, page._where_criteria, strict=True)
    )
    assert full._limit_clause is None and page._limit_clause.value == 2
    sql = query_sql(page)
    assert "ORDER BY work_task_versions.created_at DESC, work_task_versions.task_id DESC" in sql


@pytest.mark.parametrize("queue", ["receive", "commitments"])
def test_cursor_rechecks_same_queue_current_visibility_and_exact_identity(world, queue):
    world.rows = [head(world.ctx, queue)]
    world.anchor = head(world.ctx, queue, ordinal=0)
    identity = world.anchor["commitment_id" if queue == "commitments" else "task_task_id"]
    read(world, queue, cursor=str(identity))
    anchor = world.queries[1]
    assert identity in anchor.compile().params.values()
    assert anchor._limit_clause is None
    sql = query_sql(world.queries[-1])
    assert " < " in sql
    world.anchor = None
    with pytest.raises(DomainError) as error:
        read(world, queue, cursor=str(identity))
    assert error.value.status == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"pointer_revision": 4},
        {"project_product_id": uuid4()},
        {"snapshot_revision": "4"},
        {"snapshot_task_id": str(uuid4())},
        {"snapshot_state": "proposed"},
        {"task_title": ""},
    ],
)
def test_broken_current_or_scope_metadata_fails_whole_page(world, changes):
    world.rows[0].update(changes)
    assert_invalid(world)


def test_commitment_current_chain_and_actual_promisor_cannot_drift(world):
    world.rows = [head(world.ctx, "commitments", commitment_pointer_recipient_id=uuid4())]
    assert_invalid(world, "commitments")
    world.rows = [head(world.ctx, "commitments", commitment_promisor_id=uuid4())]
    assert_invalid(world, "commitments")
    world.rows = [
        head(
            world.ctx,
            "commitments",
            task_state="completed",
            pointer_state="completed",
            snapshot_state="completed",
        )
    ]
    item = read(world, "commitments")["items"][0]
    assert item["task"]["state"] == "completed"
    assert item["commitment"]["id"] == str(world.rows[0]["commitment_id"])
    assert item["commitment"]["task_revision"] == 3
    assert item["timing"] == "pending"
    assert not {"fulfilled", "completed", "closed", "status"} & set(item["commitment"])


def test_empty_queue_has_real_zero_without_losing_contract(world):
    world.rows, world.total = [], 0
    result = read(world)
    assert result["items"] == [] and result["total_records"] == 0 and result["next_cursor"] is None


@pytest.mark.parametrize("change", [{"category_id": uuid4()}, {"actor_id": uuid4()}])
def test_only_ordinary_personal_caller_can_read(world, change):
    with pytest.raises(DomainError):
        projection.read(world.session, replace(world.ctx, **change), "receive")
    assert not world.queries


def test_read_only_snapshot_is_required_and_inputs_are_closed(world):
    for queue, options in [
        ("nope", {}),
        ([], {}),
        ("receive", {"page_size": True}),
        ("receive", {"page_size": 0}),
        ("receive", {"page_size": 101}),
        ("receive", {"cursor": "not-uuid"}),
    ]:
        with pytest.raises(DomainError) as error:
            projection.read(world.session, world.ctx, queue, **options)
        assert error.value.status == 422
    world.session.info = {**world.session.info, "read_snapshot": False}
    with pytest.raises(DomainError):
        read(world)
    assert not world.queries


def test_projection_is_column_only_joins_current_exact_scope_and_never_loads_history_or_proof():
    person, tenant = uuid4(), uuid4()
    ctx = Context(tenant, person, person)
    for queue in projection.QUEUES:
        query = projection._records(ctx, queue)
        sql = query_sql(query)
        for forbidden in (
            "source_basis",
            "command",
            "sources",
            "outcomes",
            "submission",
            "content",
            "request_keys",
            "confirmations",
            "audit_entries",
            "outbox_events",
            "FOR UPDATE",
            "SET ROLE",
            "set_config",
        ):
            assert forbidden not in sql
        assert "LEFT OUTER JOIN principals AS assignee" in sql
        assert "LEFT OUTER JOIN principals AS recipient" in sql
        for key in (*projection.BINDING, "task_id", "revision", "state"):
            assert f"work_task_versions.{key} = work_task_currents.{key}" in sql
        assert "work_task_versions.id = work_task_currents.version_id" in sql
        for value in query.selected_columns:
            original = getattr(value, "element", value)
            assert not original.compare(WorkTaskVersion.body)
            assert not original.compare(WorkCommitmentVersion.body)
        assert all(item["expr"] is not item["entity"] for item in query.column_descriptions)
