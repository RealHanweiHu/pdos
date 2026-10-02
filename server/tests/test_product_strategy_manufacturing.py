"""Pure publication-readiness regression; no database or formal review proof."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import Connection

from app.auth.repository import AuthContext
from app.domain.product_strategies import publication_readiness


class WorkState:
    def __init__(self, state: str) -> None:
        self.state = state

    def scalar_one(self) -> str:
        return self.state


class ReadinessConnection:
    def __init__(self, state: str | None = None) -> None:
        self.state = state
        self.queries: list[Any] = []

    def execute(self, statement: Any) -> WorkState:
        assert self.state is not None, "No database lookup is expected for explicit dispositions"
        self.queries.append(statement)
        return WorkState(self.state)


def candidate(disciplines: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    solutions = [
        {"id": str(uuid4()), "approach": approach}
        for approach in ("new_development", "platform_reuse", "upgrade")
    ]
    return (
        {
            "route_comparisons": [
                {"solution_id": solution["id"], "modules": [{"key": "motor"}]}
                for solution in solutions
            ],
            "selected_solution_id": solutions[0]["id"],
            "professional_constraints": [
                {
                    "discipline": discipline,
                    "work_item_id": None,
                    "disposition": {"outcome": "deferred", "reason": "假设待具名评审核对"},
                }
                for discipline in disciplines
            ],
        },
        {"solutions": solutions},
    )


def context() -> AuthContext:
    return cast(AuthContext, SimpleNamespace(tenant=SimpleNamespace(id=uuid4())))


@pytest.mark.parametrize("manufacturing", ["ie", "pie", "PIE"])
def test_pie_and_existing_ie_satisfy_manufacturing_without_rewriting_constraints(
    manufacturing: str,
) -> None:
    row, opportunity = candidate(("dqe", "sqe", manufacturing))
    before = deepcopy(row)
    connection = ReadinessConnection()
    assert publication_readiness(cast(Connection, connection), context(), row, opportunity) == []
    assert row == before
    assert connection.queries == []


@pytest.mark.parametrize(
    ("disciplines", "missing"),
    [
        (("dqe", "sqe"), "PIE"),
        (("sqe", "pie"), "DQE"),
        (("dqe", "pie"), "SQE"),
        (("dqe", "sqe", "product"), "PIE"),
    ],
)
def test_pie_compatibility_does_not_remove_required_professional_checks(
    disciplines: tuple[str, ...], missing: str
) -> None:
    row, opportunity = candidate(disciplines)
    issues = publication_readiness(
        cast(Connection, ReadinessConnection()), context(), row, opportunity
    )
    assert len(issues) == 1
    assert missing in issues[0] and "约束或明确适用性处置" in issues[0]


def test_pie_without_work_or_explicit_disposition_remains_blocked() -> None:
    row, opportunity = candidate(("dqe", "sqe", "pie"))
    row["professional_constraints"][-1]["disposition"] = None
    assert publication_readiness(
        cast(Connection, ReadinessConnection()), context(), row, opportunity
    ) == ["专业约束 pie 尚无评审任务或明确处置"]


@pytest.mark.parametrize("manufacturing", ["ie", "pie"])
def test_cancelled_manufacturing_review_work_is_still_checked_in_current_tenant(
    manufacturing: str,
) -> None:
    row, opportunity = candidate(("dqe", "sqe", manufacturing))
    work_id = uuid4()
    row["professional_constraints"][-1].update(work_item_id=str(work_id), disposition=None)
    actor = context()
    connection = ReadinessConnection("cancelled")
    assert publication_readiness(cast(Connection, connection), actor, row, opportunity) == [
        f"专业约束 {manufacturing} 关联工作已取消，须重新安排或明确处置"
    ]
    assert len(connection.queries) == 1
    query = connection.queries[0]
    assert "scoped_work_items" in str(query)
    assert set(query.compile().params.values()) == {actor.tenant.id, work_id}
