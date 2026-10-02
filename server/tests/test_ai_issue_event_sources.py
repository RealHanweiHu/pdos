"""Pure read-only source contracts. No database, HTTP or model calls."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection, Select
from sqlalchemy.dialects import postgresql

from app.domain import ai_issue_event_sources as s
from app.domain.material_coverage import MaterialCoverageService
from app.domain.material_exceptions import _assessment
from app.domain.product_workspace import _plain

NOW = datetime(2026, 9, 27, tzinfo=UTC)
TENANT, PROJECT, ACTOR, CASE, ISSUE, RUN, PLAN, BATCH, DOCUMENT, EXCEPTION, BUILD, REVIEW = (
    UUID(int=i) for i in range(1, 13)
)


class Rows:
    def __init__(self, values: Any):
        self.values = values

    def mappings(self) -> "Rows":
        return self

    def one_or_none(self) -> Any:
        return self.values

    def __iter__(self) -> Any:
        return iter(self.values)


class ReadConnection:
    def __init__(self, *rows: Any):
        self.rows = list(rows)
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> Rows:
        assert isinstance(statement, Select), "source reader must never write"
        statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        self.statements.append(statement)
        assert self.rows, f"unexpected query: {statement}"
        return Rows(self.rows.pop(0))

    def read(self) -> dict[str, Any]:
        result = s.read_event_source(cast(Connection, self), TENANT, PROJECT, 101)
        assert not self.rows
        return result


def event(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=101,
            tenant_id=TENANT,
            project_id=PROJECT,
            event_type="TEST_FAILED",
            source="quality_service",
            entity="test",
            entity_id=CASE,
            event_id=f"test:{CASE}:failed:{UUID(int=100)}",
            schema_version=1,
            timestamp=NOW,
            payload=dict(test_record_id=str(CASE), severity="major"),
        )
        | changes
    )


def audit(e: dict[str, Any], after: Any, **changes: Any) -> dict[str, Any]:
    return (
        {
            key: e[key]
            for key in ("tenant_id", "project_id", "event_id", "entity", "entity_id", "timestamp")
        }
        | dict(
            id=102,
            actor_user_id=ACTOR,
            action="npi.test_case.failed",
            before_snapshot={"status": "planned"},
            after_snapshot=after,
            context={},
        )
        | changes
    )


def human() -> dict[str, Any]:
    return dict(
        id=ACTOR,
        tenant_id=TENANT,
        username="fixture",
        display_name="具名模拟品质",
        role="owner",
        auth_version=1,
        is_active=True,
    )


def case(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=CASE,
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN,
            title="耐久测试",
            acceptance_criteria="温升不超过判据",
            status="failed",
            result_notes="原失败说明",
            related_issue_id=None,
            updated_at=NOW,
            created_at=NOW - timedelta(days=1),
        )
        | changes
    )


def issue(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=ISSUE,
            tenant_id=TENANT,
            project_id=PROJECT,
            title="原问题",
            status="closed",
            reported_by_user_id=ACTOR,
            updated_at=NOW,
        )
        | changes
    )


def legacy(c: dict[str, Any]) -> dict[str, Any]:
    return _plain(
        {key: value for key, value in c.items() if key not in {"created_at", "updated_at"}}
    )


def run(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=RUN,
            tenant_id=TENANT,
            project_id=PROJECT,
            test_case_id=CASE,
            status="failed",
            draft_state="confirmed",
            result_notes="当次失败原文",
            evidence_document_id=DOCUMENT,
            run_number=2,
            updated_at=NOW,
        )
        | changes
    )


def run_event(**changes: Any) -> dict[str, Any]:
    return (
        event(
            id=103,
            event_type="NPI_RECORD_CHANGED",
            source="npi_service",
            entity="npi_record",
            entity_id=RUN,
            event_id=f"npi:test_run:{RUN}:recorded:{UUID(int=104)}",
            payload=dict(record_type="test_run", action="recorded_failed"),
        )
        | changes
    )


def run_audit(e: dict[str, Any]) -> dict[str, Any]:
    return audit(
        e,
        dict(
            test_case_id=str(CASE),
            project_id=str(PROJECT),
            status="failed",
            result_notes="当次失败原文",
        ),
        action="test_run.record",
    )


def test_legacy_fixed_original_and_current_are_separate() -> None:
    e, before = event(), case()
    original = audit(e, legacy(before))
    result = ReadConnection(e, [original], human(), before).read()
    assert result["source_status"] == "current"
    assert result["existing_issue"] is None
    assert result["source"]["origin_kind"] == "legacy_test_case"
    assert result["source"]["original_result"]["result_notes"] == "原失败说明"
    changed = ReadConnection(
        e, [original], human(), case(status="passed", result_notes="复测通过")
    ).read()
    assert changed["source_status"] == "changed"
    assert changed["source_digest"] != result["source_digest"]
    assert changed["source"]["original_result"]["result_notes"] == "原失败说明"
    assert changed["event_row_id"] == e["id"]
    assert changed["event_id"] == e["event_id"]
    assert changed["event_type"] == "TEST_FAILED"
    assert changed["event_at"] == NOW.isoformat()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "untrusted"),
        ("entity", "issue"),
        ("event_id", "arbitrary"),
        ("payload", {"test_record_id": str(ISSUE)}),
    ],
)
def test_event_identity_mismatch_never_follows_payload(field: str, value: Any) -> None:
    e = event(**{field: value})
    result = ReadConnection(e, [audit(e, legacy(case()))]).read()
    assert result["reason_code"] == "event_unverified"
    assert result["source_href"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", UUID(int=999)),
        ("entity_id", ISSUE),
        ("timestamp", NOW - timedelta(seconds=1)),
        ("actor_user_id", None),
        ("action", "issue.create"),
    ],
)
def test_audit_binding_required(field: str, value: Any) -> None:
    e = event()
    result = ReadConnection(e, [audit(e, legacy(case()), **{field: value})]).read()
    assert result["reason_code"] == "event_unverified"


def test_duplicate_audit_is_not_implicitly_picked() -> None:
    e = event()
    a = audit(e, legacy(case()))
    assert ReadConnection(e, [a, a]).read()["source_status"] == "unavailable"


def test_scope_not_found_raises_and_sql_binds_all_scope_fields() -> None:
    c = ReadConnection(None)
    with pytest.raises(LookupError):
        c.read()
    params = c.statements[0].compile().params
    assert set(params.values()) == {TENANT, PROJECT, 101}


def test_supply_snapshot_cannot_become_shortage_source() -> None:
    e = event(event_type="SUPPLY_SNAPSHOT_CAPTURED", payload={"shortage": True})
    assert ReadConnection(e).read()["reason_code"] == "unsupported_event"


def test_same_case_existing_closed_issue_is_retained_and_never_reopened() -> None:
    e = event()
    current = case(related_issue_id=ISSUE)
    result = ReadConnection(e, [audit(e, legacy(current))], human(), current, issue()).read()
    assert result["source_status"] == "current"
    assert result["existing_issue"]["status"] == "closed"
    assert result["existing_issue"]["snapshot"]["reported_by_user_id"] == str(ACTOR)
    assert result["source"]["source_key"] == f"test_case:{CASE}"


def test_run_has_actual_fk_original_audit_and_existing_issue() -> None:
    e, re = event(), run_event()
    current = case(related_issue_id=ISSUE)
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=str(ISSUE)))],
        human(),
        current,
        issue(),
        [re],
        [run_audit(re)],
        run(),
    ).read()
    assert result["source_status"] == "current"
    assert result["source"]["origin_kind"] == "test_run"
    assert result["source"]["original_result"]["result_notes"] == "当次失败原文"
    assert f"test_run_id={RUN}" in result["source_href"]


@pytest.mark.parametrize(
    "changes",
    [
        dict(status="passed"),
        dict(draft_state="draft"),
        dict(result_notes="修订说明"),
    ],
)
def test_changed_run_cannot_reuse_historical_failure(changes: dict[str, Any]) -> None:
    e, re = event(), run_event()
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=None))],
        human(),
        case(),
        [re],
        [run_audit(re)],
        run(**changes),
    ).read()
    assert result["source_status"] == "changed"
    assert result["source"]["original_result"]["result_notes"] == "当次失败原文"


def test_missing_original_run_does_not_select_current_latest() -> None:
    e = event()
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=None))],
        human(),
        case(),
        [],
        [],
    ).read()
    assert result["reason_code"] == "test_origin_unverified"


def import_fixture(**changes: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    e = event(
        id=105,
        event_type="NPI_RECORD_CHANGED",
        source="npi_service",
        entity="npi_record",
        entity_id=BATCH,
        event_id=f"npi:import_batch:{BATCH}:confirmed",
        payload=dict(record_type="test_report_import", action="confirmed"),
    )
    b = (
        dict(
            id=BATCH,
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN,
            document_id=DOCUMENT,
            created_run_ids=[str(RUN), str(UUID(int=900))],
            confirmed_at=NOW,
            confirmed_by_user_id=ACTOR,
            status="confirmed",
            superseded_by_batch_id=None,
        )
        | changes
    )
    a = audit(
        e,
        dict(batch_id=str(BATCH), confirmed_run_ids=b["created_run_ids"]),
        action="test_report_import.confirm",
    )
    return e, a, b


def test_report_confirmation_uses_max_run_inside_fixed_batch_only() -> None:
    e = event()
    ie, ia, batch = import_fixture()
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=None))],
        human(),
        case(),
        [],
        [ie],
        [ia],
        batch,
        [run(id=UUID(int=900), run_number=1, status="passed"), run()],
    ).read()
    assert result["source_status"] == "current"
    assert result["source"]["origin_kind"] == "test_report_import"
    assert result["source"]["current_run"]["id"] == str(RUN)
    assert result["source"]["import_audit"]["after_snapshot"]["batch_id"] == str(BATCH)


def test_report_later_changes_do_not_invent_original_prose() -> None:
    e = event()
    ie, ia, batch = import_fixture()
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=None))],
        human(),
        case(),
        [],
        [ie],
        [ia],
        batch,
        [
            run(id=UUID(int=900), run_number=1),
            run(updated_at=NOW + timedelta(hours=1), result_notes="新内容"),
        ],
    ).read()
    assert result["source_status"] == "changed"
    assert result["source"]["original_result"]["result_notes"] is None
    assert result["source"]["current_run"]["result_notes"] == "新内容"


def coverage() -> dict[str, Any]:
    return dict(
        policy="supply.observed_gap.date_comparison.v1",
        selection={},
        revision_id=str(PLAN),
        revision_digest="a" * 64,
        build=dict(id=str(BUILD), status="planned"),
        schedule={},
        need_date=None,
        need_date_passed=False,
        pool_limit_reached=False,
        materials=[
            dict(
                material_key="b" * 64,
                material_reference="PUMP-01",
                unit="件",
                pool_ids=[],
                lines=[],
                observed_on_hand_gap="2",
                required="3",
            )
        ],
        pools=[],
        allocations=[],
        as_of=NOW.isoformat(),
    )


def material_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    e = event(
        event_type="NPI_RECORD_CHANGED",
        source="npi_service",
        entity="npi_record",
        entity_id=EXCEPTION,
        event_id=f"npi:material_exception:{EXCEPTION}:confirmed:{UUID(int=800)}",
        payload=dict(record_type="material_exception", action="confirmed"),
    )
    exception = dict(
        id=EXCEPTION,
        tenant_id=TENANT,
        project_id=PROJECT,
        build_id=BUILD,
        issue_id=ISSUE,
        material_key="b" * 64,
        material_reference="PUMP-01",
    )
    assessment = _assessment(coverage(), "b" * 64)
    review = dict(
        id=REVIEW,
        tenant_id=TENANT,
        project_id=PROJECT,
        exception_id=EXCEPTION,
        version=1,
        created_by_user_id=ACTOR,
        disposition="follow_up",
        basis_digest=assessment["digest"],
        snapshot=assessment,
    )
    a = audit(
        e,
        dict(exception_id=str(EXCEPTION), issue_id=str(ISSUE), review=_plain(review)),
        action="npi.material_exception.confirmed",
    )
    return e, a, exception, review


def read_material(
    monkeypatch: pytest.MonkeyPatch, current: dict[str, Any], *, later: bool = False
) -> dict[str, Any]:
    e, a, exception, review = material_fixture()
    reviews = [dict(review, id=UUID(int=999), version=2), review] if later else [review]
    monkeypatch.setattr(MaterialCoverageService, "read", lambda *args: current)
    return ReadConnection(
        e,
        [a],
        human(),
        exception,
        issue(),
        reviews,
        dict(id=TENANT, slug="fixture", name="模拟", status="active"),
    ).read()


def test_material_is_confirmed_current_gap_and_actual_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = read_material(monkeypatch, coverage())
    assert result["source_status"] == "current"
    assert result["existing_issue"]["id"] == str(ISSUE)
    assert result["source"]["original_review"]["id"] == str(REVIEW)
    assert result["source"]["source_key"] == f"material_exception:{EXCEPTION}"


def test_read_clock_does_not_change_material_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    first = read_material(monkeypatch, coverage())
    current = coverage() | {"as_of": (NOW + timedelta(hours=1)).isoformat()}
    second = read_material(monkeypatch, current)
    assert first["source_digest"] == second["source_digest"]


@pytest.mark.parametrize("change", ["gap", "build", "expiry", "later_review"])
def test_material_business_changes_are_not_silently_current(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    current = coverage()
    if change == "gap":
        current["materials"][0]["observed_on_hand_gap"] = "0"
    elif change == "build":
        current["build"]["status"] = "completed"
    elif change == "expiry":
        current["need_date_passed"] = True
    result = read_material(monkeypatch, current, later=change == "later_review")
    assert result["source_status"] == "changed"
    assert result["existing_issue"]["status"] == "closed"


def test_material_audit_cannot_substitute_another_review() -> None:
    e, a, exception, review = material_fixture()
    a = deepcopy(a)
    a["after_snapshot"]["review"]["basis_digest"] = "wrong"
    result = ReadConnection(e, [a], human(), exception, issue(), [review]).read()
    assert result["reason_code"] == "material_review_unverified"


def test_unknown_database_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    e, a, exception, review = material_fixture()

    def fail(*args: Any) -> Any:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(MaterialCoverageService, "read", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        ReadConnection(
            e,
            [a],
            human(),
            exception,
            issue(),
            [review],
            dict(id=TENANT, slug="fixture", name="模拟", status="active"),
        ).read()


@pytest.mark.parametrize("gap,expected", [(None, "unavailable"), ("0", "changed")])
def test_confirmed_material_still_requires_known_positive_gap(
    monkeypatch: pytest.MonkeyPatch, gap: str | None, expected: str
) -> None:
    e, a, exception, review = material_fixture()
    current = coverage()
    current["materials"][0]["observed_on_hand_gap"] = gap
    assessment = _assessment(current, "b" * 64)
    review.update(snapshot=assessment, basis_digest=assessment["digest"])
    a["after_snapshot"]["review"] = _plain(review)
    monkeypatch.setattr(MaterialCoverageService, "read", lambda *args: current)
    result = ReadConnection(
        e,
        [a],
        human(),
        exception,
        issue(),
        [review],
        dict(id=TENANT, slug="fixture", name="模拟", status="active"),
    ).read()
    assert result["source_status"] == expected
    assert result["existing_issue"]["id"] == str(ISSUE)


def test_report_batch_cannot_substitute_a_different_confirmed_set() -> None:
    e = event()
    ie, ia, batch = import_fixture()
    batch["created_run_ids"] = [str(UUID(int=999))]
    result = ReadConnection(
        e,
        [audit(e, dict(status="failed", related_issue_id=None))],
        human(),
        case(),
        [],
        [ie],
        [ia],
        batch,
    ).read()
    assert result["reason_code"] == "test_origin_unverified"
