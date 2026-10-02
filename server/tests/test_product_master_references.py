"""Actual reference service at SQL boundaries; no PostgreSQL/API qualification."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine as SQLEngine
from sqlalchemy.sql import Executable, Insert

from app.auth.repository import AuthContext
from app.contracts.common_objects import SourceRef
from app.domain import product_master_references as master
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _result_sources

TENANT, ACTOR, SPACE, PRODUCT, LINE, DEFINITION, RELEASE, SOURCE = (
    UUID(int=i) for i in range(1, 9)
)
STAMP = datetime(2026, 1, 1, tzinfo=UTC)
REF = SourceRef(
    tenant_id=TENANT, kind="evidence_snapshot", ref_id=SOURCE, as_of=STAMP, digest="a" * 64
)


class Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> "Result":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one(self) -> dict[str, Any]:
        assert len(self.rows) == 1
        return self.rows[0]


class EvidenceResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> "EvidenceResult":
        return self

    def one_or_none(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def first(self) -> tuple[Any] | None:
        return None if self.value is None else (self.value,)


class Connection:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.writes = 0
        self.evidence_body: str | None = "真实采集正文"

    def execute(self, statement: Executable) -> Result:
        if isinstance(statement, Insert):
            row = dict(statement.compile().params)
            row["created_at"] = STAMP
            self.rows.append(row)
            self.writes += 1
            return Result([row])
        sql = str(statement)
        if "evidence_snapshots" in sql:
            return cast(
                Result, EvidenceResult(dict(id=SOURCE, captured_at=STAMP, content_digest="a" * 64))
            )
        if "evidence_contents.body" in sql:
            return cast(Result, EvidenceResult(self.evidence_body))
        if "evidence_contents.content_digest" in sql:
            return cast(Result, EvidenceResult(None if self.evidence_body is None else "a" * 64))
        return Result(self.rows)


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        yield self.connection

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        yield self.connection


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.connection = Connection()
        self.context = cast(
            AuthContext,
            SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=ACTOR)),
        )
        self.node: dict[str, Any] = dict(
            id=PRODUCT,
            version=1,
            code="M1",
            name="型号",
            level="model",
            lifecycle="available",
            product_line_id=LINE,
        )
        self.release: dict[str, Any] | None = dict(
            id=RELEASE, action="publish", definition_id=DEFINITION
        )
        self.definition: dict[str, Any] = dict(
            id=DEFINITION, product_id=PRODUCT, version=2, revision_number=1, state="published"
        )
        self.denied: str | None = None
        self.events = 0
        self.locked = False
        self.sources_checked = 0
        monkeypatch.setattr(master, "_role", self.role)
        monkeypatch.setattr(master, "_space", self.space)
        monkeypatch.setattr(master, "_line", self.line)
        monkeypatch.setattr(master, "_node_row", lambda *args: self.node)
        monkeypatch.setattr(master, "_release", lambda *args: self.release)
        monkeypatch.setattr(master, "_row", lambda *args: self.definition)
        monkeypatch.setattr(master, "definition_digest", lambda row: "b" * 64)
        monkeypatch.setattr(master, "_result_sources", self.sources)
        monkeypatch.setattr(master, "_emit", self.emit)
        self.service = master.ProductMasterReferenceService(
            cast(SQLEngine, Engine(self.connection))
        )

    def role(self, *args: Any) -> None:
        self.guard("role")

    def space(self, *args: Any, **kwargs: Any) -> None:
        self.guard("space")
        self.locked = bool(kwargs.get("lock"))

    def line(self, *args: Any, **kwargs: Any) -> None:
        self.guard("line")

    def sources(self, *args: Any) -> list[dict[str, Any]]:
        self.sources_checked += 1
        self.guard("source")
        if self.denied == "body":
            raise ProductWorkError("所选来源正文为空")
        return [REF.model_dump(mode="json")]

    def guard(self, kind: str) -> None:
        if self.denied == kind:
            raise ProductWorkAccessError(kind)

    def emit(self, *args: Any) -> None:
        self.events += 1

    def command(self, **changes: Any) -> master.MasterReferenceSave:
        current = self.service.read(self.context, SPACE, PRODUCT)
        values = dict(
            request_id=UUID(int=20 + self.connection.writes),
            expected_context_digest=current["context_digest"],
            action="register",
            system_kind="erp",
            source_system="ERP_A",
            master_kind="material",
            external_id="M-1",
            external_revision="A",
            external_as_of=STAMP,
            sources=(REF,),
            reason="内部登记",
        )
        values.update(changes)
        return master.MasterReferenceSave.model_validate(values)

    def save(self, command: master.MasterReferenceSave) -> dict[str, Any]:
        return self.service.save(self.context, SPACE, PRODUCT, command)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


def test_registration_freezes_context_and_replay_has_no_new_event(harness: Harness) -> None:
    command = harness.command()
    saved = harness.save(command)
    frozen = deepcopy(harness.connection.rows[0])
    assert harness.locked and harness.connection.writes == harness.events == 1
    assert saved["items"][0]["is_head"] is True
    harness.definition["version"] = 3
    result = harness.save(command)
    assert result["items"][0]["context_status"] == "stale"
    assert harness.connection.rows[0] == frozen
    assert harness.connection.writes == harness.events == 1


@pytest.mark.parametrize("denied", ["role", "space", "line", "source", "body"])
def test_current_authority_and_content_before_replay_or_read(harness: Harness, denied: str) -> None:
    command = harness.command()
    harness.save(command)
    harness.denied = denied
    operations: tuple[Callable[[], dict[str, Any]], ...] = (
        lambda: harness.save(command),
        lambda: harness.service.read(harness.context, SPACE, PRODUCT),
    )
    for operation in operations:
        with pytest.raises((ProductWorkError, ProductWorkAccessError)):
            operation()
    assert harness.connection.writes == harness.events == 1


@pytest.mark.parametrize("denied", ["source", "body"])
def test_unreadable_or_missing_body_rejected_before_first_insert(
    harness: Harness, denied: str
) -> None:
    command = harness.command()
    harness.denied = denied
    with pytest.raises((ProductWorkError, ProductWorkAccessError)):
        harness.save(command)
    assert harness.connection.writes == harness.events == 0


def test_replay_actor_and_request_content_guard(harness: Harness) -> None:
    command = harness.command()
    harness.save(command)
    with pytest.raises(ProductWorkError, match="不同内容"):
        harness.save(command.model_copy(update={"reason": "不同"}))
    harness.context = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=UUID(int=99))),
    )
    with pytest.raises(ProductWorkAccessError, match="操作者"):
        harness.save(command)
    assert harness.connection.writes == harness.events == 1


@pytest.mark.parametrize(
    "state", ["no_release", "withdrawn", "retired", "wrong_product", "family", "changed"]
)
def test_registration_context_rejections_before_write(harness: Harness, state: str) -> None:
    command = harness.command()
    if state == "no_release":
        harness.release = None
    elif state == "withdrawn":
        assert harness.release is not None
        harness.release["action"] = "withdraw"
    elif state == "retired":
        harness.node["lifecycle"] = "retired"
    elif state == "wrong_product":
        harness.definition["product_id"] = UUID(int=99)
    elif state == "family":
        harness.node["level"] = "family"
    else:
        harness.definition["version"] = 3
    with pytest.raises(ProductWorkError):
        harness.save(command)
    assert harness.connection.writes == harness.events == 0


def test_correction_and_withdrawal_keep_history_and_frozen_identity(harness: Harness) -> None:
    harness.save(harness.command())
    first = deepcopy(harness.connection.rows[0])
    correction = harness.command(action="correct", previous_id=first["id"], external_revision="B")
    harness.save(correction)
    second = deepcopy(harness.connection.rows[1])
    harness.release = None
    harness.node["lifecycle"] = "retired"
    withdrawal = harness.command(action="withdraw", previous_id=second["id"], external_revision="B")
    harness.save(withdrawal)
    third = harness.connection.rows[2]
    assert harness.connection.rows[:2] == [first, second]
    for key in (*master.FROZEN_FIELDS, "definition_ref", "product_snapshot", "context_digest"):
        assert third[key] == second[key]
    result = harness.service.read(harness.context, SPACE, PRODUCT)
    assert [row["is_head"] for row in result["items"]] == [False, False, True]
    assert result["items"][-1]["context_status"] == "no_current_release"
    with pytest.raises(ProductWorkError, match="替代|撤回"):
        harness.save(harness.command(action="correct", previous_id=second["id"]))
    assert harness.connection.writes == harness.events == 3


def test_duplicate_locator_and_correction_collision_rejected(harness: Harness) -> None:
    harness.save(harness.command())
    first = harness.connection.rows[0]
    with pytest.raises(ProductWorkError, match="活动引用"):
        harness.save(harness.command())
    harness.save(harness.command(external_id="M-2"))
    with pytest.raises(ProductWorkError, match="活动引用"):
        harness.save(harness.command(action="correct", previous_id=first["id"], external_id="M-2"))
    assert harness.connection.writes == harness.events == 2


def test_withdrawal_fields_cannot_change(harness: Harness) -> None:
    harness.save(harness.command())
    with pytest.raises(ProductWorkError, match="保留"):
        harness.save(
            harness.command(
                action="withdraw",
                previous_id=harness.connection.rows[0]["id"],
                external_revision="B",
            )
        )
    assert harness.connection.writes == harness.events == 1


@pytest.mark.parametrize(
    "changes",
    [
        dict(master_kind="cad_revision"),
        dict(external_revision=" "),
        dict(external_as_of=datetime.now(UTC) + timedelta(days=1)),
        dict(external_as_of=datetime(2026, 1, 1)),
        dict(sources=()),
        dict(action="withdraw"),
    ],
)
def test_contract_rejects_unknown_identity_or_invalid_sources_time(
    harness: Harness, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        harness.command(**changes)


@pytest.mark.parametrize("body", [None, "", " \n\t ", "真实采集正文"])
def test_real_evidence_resolution_controls_insert(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, body: str | None
) -> None:
    monkeypatch.setattr(master, "_result_sources", _result_sources)
    harness.connection.evidence_body = body
    command = harness.command()
    if body is None or not body.strip():
        with pytest.raises(ProductWorkError, match="正文"):
            harness.save(command)
        assert harness.connection.writes == harness.events == 0
    else:
        harness.save(command)
        assert harness.connection.writes == harness.events == 1


def test_real_source_scope_rejects_foreign_tenant_before_insert(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(master, "_result_sources", _result_sources)
    foreign = REF.model_copy(update={"tenant_id": UUID(int=99)})
    with pytest.raises(ProductWorkError, match="共享证据"):
        harness.save(harness.command(sources=(foreign,)))
    assert harness.connection.writes == harness.events == 0
