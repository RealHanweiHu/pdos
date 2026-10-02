"""Real research/work result methods with SQL boundary doubles; no database fixtures."""

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection as SQLConnection
from sqlalchemy import Engine as SQLEngine
from sqlalchemy.sql import Executable, Update

from app.auth.repository import AuthContext
from app.contracts.common_objects import SourceRef
from app.contracts.object_operations import ResearchConcludeRequest
from app.domain import product_workspace as workspace

TENANT, SPACE, TASK, OWNER, OTHER, SNAPSHOT = [UUID(int=i) for i in range(1, 7)]
STAMP = datetime(2026, 9, 30, tzinfo=UTC)
DIGEST = "a" * 64


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> Any:
        return self.value

    def one(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def first(self) -> tuple[Any] | None:
        return None if self.value is None else (self.value,)


class Connection:
    def __init__(self, row: dict[str, Any], values: list[Any]) -> None:
        self.row = row
        self.values = values
        self.writes = 0

    def execute(self, statement: Executable) -> Result:
        if isinstance(statement, Update):
            self.writes += 1
            changed = {**self.row, **statement.compile().params}
            return Result(changed)
        assert self.values, "Unexpected SQL read"
        return Result(self.values.pop(0))


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @contextmanager
    def begin(self) -> Iterator[SQLConnection]:
        yield cast(SQLConnection, self.connection)


def prepare(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["research", "work"],
    *,
    body: str | None = "Synthetic captured body",
    metadata_only: bool = False,
    actor: UUID = OWNER,
    deny_range: bool = False,
    replay: bool = False,
) -> tuple[
    workspace.ProductWorkspaceService,
    AuthContext,
    Connection,
    ResearchConcludeRequest | workspace.WorkAction,
]:
    row: dict[str, Any] = dict(
        id=TASK,
        tenant_id=TENANT,
        market_space_id=SPACE,
        product_line_id=None,
        owner_user_id=OWNER,
        version=2,
        state="active" if kind == "research" else "in_progress",
        acceptance_required=False,
        receiver_user_id=OTHER,
        evidence=[],
        sources=[],
    )
    ref = SourceRef(
        tenant_id=TENANT, kind="evidence_snapshot", ref_id=SNAPSHOT, digest=DIGEST, as_of=STAMP
    )
    common: dict[str, Any] = dict(
        expected_version=2,
        payload_digest=workspace.digest(workspace._plain(row)),
        idempotency_key="synthetic-submit",
    )
    command: ResearchConcludeRequest | workspace.WorkAction
    if kind == "research":
        command = ResearchConcludeRequest(
            **common,
            research_task_id=TASK,
            conclusion="Synthetic conclusion",
            findings=("Synthetic fact",),
            unresolved=(),
            source_refs=(ref,),
        )
    else:
        command = workspace.WorkAction(
            **common, action="submit", note="Synthetic output", evidence=(ref,)
        )
    receipt = (
        {"command_digest": workspace.digest(command.model_dump(mode="json"))} if replay else None
    )
    if replay:
        row.update(state="completed", version=3)
    evidence_row = dict(id=SNAPSHOT, content_digest=DIGEST, captured_at=STAMP)
    values: list[Any] = [row, receipt]
    if not replay:
        values += [evidence_row, None if metadata_only else DIGEST]
        if not metadata_only:
            values.append(body)
    c = Connection(row, values)
    context = cast(
        AuthContext,
        SimpleNamespace(
            tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=actor, role="owner")
        ),
    )

    def line(*args: Any, **kwargs: Any) -> None:
        if deny_range:
            raise workspace.ProductWorkAccessError("range revoked")

    monkeypatch.setattr(workspace, "_space", lambda *a, **kw: None)
    monkeypatch.setattr(workspace, "_line", line)
    # These projections require unrelated complete research schemas; the actual mutation and
    # precondition/evidence SQL paths remain live and their write counts are asserted below.
    monkeypatch.setattr(workspace, "_research", lambda value: deepcopy(value))
    monkeypatch.setattr(workspace, "_record", lambda value: deepcopy(value))
    monkeypatch.setattr(workspace, "_emit", lambda *a, **kw: None)
    return workspace.ProductWorkspaceService(cast(SQLEngine, Engine(c))), context, c, command


def submit(
    service: workspace.ProductWorkspaceService,
    context: AuthContext,
    command: ResearchConcludeRequest | workspace.WorkAction,
) -> dict[str, Any]:
    if isinstance(command, ResearchConcludeRequest):
        return service.research_action(context, SPACE, TASK, command)
    return service.work_action(context, SPACE, TASK, command)


@pytest.mark.parametrize("kind", ["research", "work"])
def test_readable_captured_body_allows_real_result_submission(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["research", "work"],
) -> None:
    service, context, c, command = prepare(monkeypatch, kind)
    result = submit(service, context, command)
    assert result["state"] == "completed" and result["version"] == 3
    assert c.writes == 1 and not c.values
    refs = result["sources" if kind == "research" else "evidence"]
    assert refs[0]["ref_id"] == str(SNAPSHOT) and refs[0]["digest"] == DIGEST


@pytest.mark.parametrize("kind", ["research", "work"])
@pytest.mark.parametrize("options", [{"metadata_only": True}, {"body": ""}, {"body": " \n\t "}])
def test_metadata_or_empty_content_rejects_before_any_business_write(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["research", "work"],
    options: dict[str, Any],
) -> None:
    service, context, c, command = prepare(monkeypatch, kind, **options)
    before = deepcopy(c.row)
    with pytest.raises(workspace.ProductWorkError, match="正文"):
        submit(service, context, command)
    assert c.writes == 0 and c.row == before and not c.values


@pytest.mark.parametrize("kind", ["research", "work"])
@pytest.mark.parametrize(
    "options,error",
    [
        ({"actor": OTHER}, "负责人"),
        ({"deny_range": True}, "range revoked"),
    ],
)
def test_original_receipt_cannot_bypass_current_actor_or_range(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["research", "work"],
    options: dict[str, Any],
    error: str,
) -> None:
    service, context, c, command = prepare(monkeypatch, kind, replay=True, **options)
    with pytest.raises(workspace.ProductWorkAccessError, match=error):
        submit(service, context, command)
    assert c.writes == 0
    assert len(c.values) == 1, "Rejection must precede checking the historical receipt"


@pytest.mark.parametrize("kind", ["research", "work"])
def test_authorized_original_receipt_does_not_resubmit_or_write(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["research", "work"],
) -> None:
    service, context, c, command = prepare(monkeypatch, kind, replay=True)
    assert submit(service, context, command) == c.row
    assert c.writes == 0 and not c.values
