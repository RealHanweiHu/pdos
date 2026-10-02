"""Candidate admission and actual selected-source SQL boundaries, without a DB/model."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection
from sqlalchemy.sql import Executable

from app.ai import product_work_preparation as preparation
from app.ai.product_evidence_context import validate_refs
from app.auth.repository import AuthContext
from app.contracts.product_planning_ai import DefinitionCandidate
from app.contracts.product_work_ai import ProductWorkSelection
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

TENANT, ACTOR, SPACE, LINE, PRODUCT, STRATEGY, PREVIOUS, PARENT = [UUID(int=i) for i in range(1, 9)]


class Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row


class SelectedConnection:
    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.rows = rows.copy()
        self.statements: list[Executable] = []

    def execute(self, statement: Executable) -> Result:
        self.statements.append(statement)
        assert self.rows, "Unexpected SQL at source preparation boundary"
        return Result(self.rows.pop(0))


def candidate(revision: bool) -> DefinitionCandidate:
    fact = {"text": "合成待验证依据", "fact_kind": "hypothesis"}
    return DefinitionCandidate.model_validate(
        {
            "product_id": PRODUCT,
            "strategy_id": STRATEGY,
            "supersedes_id": PREVIOUS if revision else None,
            "title": "合成定义候选",
            "target_users": ["测试用户"],
            "scenarios": ["测试场景"],
            "target_cost": fact,
            "price_position": fact,
            "launch_window": fact,
            "success_criteria": [fact],
            "change_reason": "人工核对后继续办理",
            "items": [
                {
                    "item_key": "spec-001",
                    "title": "待验证规格",
                    "target_text": None,
                    "target_value": None,
                    "unit": None,
                    "tolerance": None,
                    "conditions": [],
                    "priority": "must",
                    "required_for_release": True,
                    "rationale": fact,
                    "verification_method": None,
                    "acceptance_criterion": None,
                    "verification_stage": None,
                }
            ],
        }
    )


def rows(derived: bool, revision: bool) -> list[dict[str, Any] | None]:
    product: dict[str, Any] = {
        "id": PRODUCT,
        "product_line_id": LINE,
        "code": "SYNTHETIC",
        "name": "合成产品",
        "level": "model",
        "parent_id": None,
        "lifecycle": "active",
        "regions": [],
        "channels": [],
        "version": 1,
        "derived_from": PARENT if derived else None,
    }
    strategy: dict[str, Any] = {
        key: None for key in preparation.SOURCE_FIELDS["strategy"][2].split()
    }
    strategy.update(
        id=STRATEGY, product_line_id=LINE, title="原发布策略", state="published", version=1
    )
    result: list[dict[str, Any] | None] = [product, strategy]
    if revision:
        definition: dict[str, Any] = {
            key: None for key in preparation.SOURCE_FIELDS["definition"][2].split()
        }
        definition.update(
            id=PREVIOUS,
            product_line_id=LINE,
            product_id=PRODUCT,
            strategy_id=STRATEGY,
            title="已发布原定义",
            state="published",
            version=2,
            content={"items": [{"item_key": "spec-001"}]},
            base_definition_id=PARENT if derived else None,
            base_definition_ref={"ref_id": str(PARENT), "kind": "product_definition"},
            parent_updates=[],
        )
        result.append(definition)
    return result


def prepare(
    monkeypatch: pytest.MonkeyPatch,
    selected_rows: list[dict[str, Any] | None],
    revision: bool,
    *,
    parent_denied: bool = False,
) -> tuple[dict[str, Any], SelectedConnection]:
    space = dict(
        title="合成市场", user_groups=[], regions=[], use_scenarios=[], research_questions=[]
    )
    monkeypatch.setattr(preparation, "authorize", lambda *args: space)
    monkeypatch.setattr(preparation, "_line", lambda *args: None)
    monkeypatch.setattr(preparation, "resolve_evidence", lambda *args: [])

    # These rows represent the existing inheritance expansion boundary; its
    # own merge semantics are not replaced or reimplemented in these tests.
    def expanded(_c: Connection, row: dict[str, Any]) -> dict[str, Any]:
        if parent_denied:
            raise ProductWorkAccessError("父版当前无权访问")
        return row

    monkeypatch.setattr(preparation, "expand_definition", expanded)
    context = cast(
        AuthContext,
        SimpleNamespace(
            tenant=SimpleNamespace(id=TENANT),
            user=SimpleNamespace(id=ACTOR),
        ),
    )
    sources = [{"kind": "product", "id": PRODUCT}, {"kind": "strategy", "id": STRATEGY}]
    if revision:
        sources.append({"kind": "definition", "id": PREVIOUS})
    selection = ProductWorkSelection.model_validate(
        {
            "capability": "product_definition",
            "product_line_id": LINE,
            "sources": sources,
            "question": "核对定义候选，不自动发布",
        }
    )
    connection = SelectedConnection(selected_rows)
    snapshot = preparation.source_state(cast(Connection, connection), context, SPACE, selection)
    assert not connection.rows
    return snapshot, connection


@pytest.mark.parametrize("derived", [False, True])
def test_first_version_admission_uses_actual_selected_product(
    monkeypatch: pytest.MonkeyPatch,
    derived: bool,
) -> None:
    snapshot, connection = prepare(monkeypatch, rows(derived, False), False)
    original = deepcopy(snapshot)
    value = candidate(False)
    if derived:
        with pytest.raises(ProductWorkError, match="从当前发布父定义派生"):
            validate_refs(value, snapshot, TENANT)
    else:
        validate_refs(value, snapshot, TENANT)
    assert snapshot == original  # Admission never assigns a parent or rewrites the fixed pack.
    assert len(connection.statements) == 2
    assert value.supersedes_id is None


@pytest.mark.parametrize("derived", [False, True])
def test_published_revision_preserves_stable_items_and_locked_parent(
    monkeypatch: pytest.MonkeyPatch,
    derived: bool,
) -> None:
    snapshot, connection = prepare(monkeypatch, rows(derived, True), True)
    original = deepcopy(snapshot)
    validate_refs(candidate(True), snapshot, TENANT)
    assert snapshot == original and len(connection.statements) == 3
    assert candidate(True).items[0].acceptance_criterion is None
    if derived:
        previous = snapshot["references"][-1]["fields"]
        assert previous["base_definition_ref"]["ref_id"] == str(PARENT)


@pytest.mark.parametrize("failure", ["wrong_product", "unpublished", "missing_source", "renumber"])
def test_derived_revision_cannot_bypass_original_definition_guards(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    selected_rows = rows(True, True)
    previous = selected_rows[-1]
    assert previous is not None
    if failure == "wrong_product":
        previous["product_id"] = UUID(int=99)
    elif failure == "unpublished":
        previous["state"] = "draft"
    snapshot, _ = prepare(monkeypatch, selected_rows, True)
    value = candidate(True)
    if failure == "missing_source":
        snapshot["references"] = [
            r for r in snapshot["references"] if r["reference_id"] != f"definition:{PREVIOUS}"
        ]
    if failure == "renumber":
        value = DefinitionCandidate.model_validate(
            {
                **value.model_dump(),
                "items": [{**value.items[0].model_dump(), "item_key": "spec-new"}],
            }
        )
    with pytest.raises(ProductWorkError, match="已发布原版|稳定条目标识"):
        validate_refs(value, snapshot, TENANT)


@pytest.mark.parametrize("failure", ["wrong_line", "revoked_source", "revoked_parent"])
def test_current_selection_fails_closed_before_candidate_admission(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    selected_rows = rows(True, True)
    if failure == "wrong_line":
        previous = selected_rows[-1]
        assert previous is not None
        previous["product_line_id"] = UUID(int=99)
    elif failure == "revoked_source":
        selected_rows[-1] = None
    # Parent authorization belongs to existing inheritance expansion. Its
    # current failure must propagate before any candidate can be admitted.
    with pytest.raises((ProductWorkError, ProductWorkAccessError), match="产品线不一致|无权访问"):
        prepare(monkeypatch, selected_rows, True, parent_denied=failure == "revoked_parent")
