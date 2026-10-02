from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection, Select
from sqlalchemy.dialects import postgresql

from app.ai.write_evaluation_publication import (
    PublishedWriteEvaluation,
    WriteEvaluationPublicationError,
)
from app.contracts.ai_write_qualification import (
    QualificationConfiguration,
    QualificationInput,
    evaluate_qualification,
)
from app.contracts.ai_write_trial_protocol import TrialProtocol
from app.domain import ai_write_qualification_state as state_module
from app.domain.ai_write_qualification_state import QualificationState, qualification_history_query
from app.domain.ai_write_trial_collection import TrialCollection
from tests import test_ai_write_qualification_contract as fixtures

NOW = fixtures.CUTOFF + timedelta(hours=2)
POLICY_ID = UUID(int=41)
RECEIPT_ID = UUID(int=4)


def configuration() -> QualificationConfiguration:
    original = fixtures.configuration()
    return original.model_copy(
        update={
            "configuration_digest": state_module._digest(
                original.model_dump(mode="json", exclude={"configuration_digest"})
            )
        }
    )


def protocol(number: int = 40, **changes: Any) -> TrialProtocol:
    result = TrialProtocol.model_validate(
        dict(
            id=UUID(int=number),
            tenant_id=fixtures.TENANT,
            policy_id=POLICY_ID,
            actor_user_id=UUID(int=42),
            project_ids=(UUID(int=3),),
            binding=fixtures.binding(),
            evidence_kind="real_business",
            window_start=fixtures.START,
            window_end=fixtures.END,
            configuration=configuration(),
            reason="模拟登记，仅测试纯读取器",
            created_at=configuration().fixed_at,
            protocol_digest="0" * 64,
        )
        | changes
    )
    return result.model_copy(
        update={
            "protocol_digest": state_module._digest(
                result.model_dump(mode="json", exclude={"protocol_digest"})
            )
        }
    )


def publication(**changes: Any) -> PublishedWriteEvaluation:
    return PublishedWriteEvaluation.model_validate(
        dict(
            publication_sha256="a" * 64,
            publication_id=UUID(int=70),
            published_at=fixtures.START,
            valid_from=fixtures.START,
            valid_until=NOW + timedelta(days=1),
            evaluation=fixtures.evaluation(),
        )
        | changes
    )


def collection(
    *, as_of: datetime, receipt_id: UUID = RECEIPT_ID, drafts: Any = None
) -> TrialCollection:
    cohort = fixtures.cohort(drafts, as_of=as_of, cohort_id=receipt_id)
    result = evaluate_qualification(
        QualificationInput(
            tenant_id=fixtures.TENANT,
            binding=fixtures.binding(),
            configuration=configuration(),
            evaluation=fixtures.evaluation(),
            cohort=cohort,
            as_of=as_of,
        )
    )
    return TrialCollection(
        project_ids=(UUID(int=3),),
        cohort=cohort,
        raw_counts=result.counts,
        raw_total=len(cohort.drafts),
        verified_total=len(cohort.drafts),
        unverified_total=0,
        original_draft_ids=tuple(d.draft_id for d in cohort.drafts),
        blockers=(),
    )


def row(
    *,
    number: int = 4,
    proto: TrialProtocol | None = None,
    as_of: datetime = fixtures.CUTOFF,
    created_at: datetime | None = None,
    drafts: Any = None,
) -> dict[str, Any]:
    proto = proto or protocol()
    collected = collection(as_of=as_of, receipt_id=UUID(int=number), drafts=drafts)
    candidate = QualificationInput(
        tenant_id=fixtures.TENANT,
        binding=proto.binding,
        configuration=proto.configuration,
        evaluation=fixtures.evaluation(),
        cohort=collected.cohort,
        as_of=as_of,
    )
    created_at = created_at or as_of + timedelta(seconds=1)
    pub = publication()
    body = dict(
        id=str(UUID(int=number)),
        protocol_id=str(proto.id),
        protocol_digest=proto.protocol_digest,
        actor_user_id=str(UUID(int=42)),
        created_at=created_at.isoformat(),
        as_of=as_of.isoformat(),
        collection=collected.model_dump(mode="json"),
        qualification=evaluate_qualification(candidate).model_dump(mode="json"),
        evaluation=fixtures.evaluation().model_dump(mode="json"),
        evaluation_publication=dict(
            status="verified",
            publication_id=str(pub.publication_id),
            publication_sha256=pub.publication_sha256,
            published_at=pub.published_at.isoformat(),
            valid_until=pub.valid_until.isoformat(),
        ),
        current_policy_matches=True,
    )
    body["receipt_digest"] = state_module._digest(body)
    return dict(
        protocol_record_id=proto.id,
        tenant_id=fixtures.TENANT,
        policy_id=proto.policy_id,
        protocol_created_at=proto.created_at,
        protocol=proto.model_dump(mode="json"),
        receipt_record_id=UUID(int=number),
        receipt_created_at=created_at,
        receipt_as_of=as_of,
        receipt=body,
    )


class ReadConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[Select[Any]] = []

    def execute(self, query: Select[Any]) -> ReadConnection:
        assert query.is_select
        self.queries.append(query)
        return self

    def mappings(self) -> ReadConnection:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Any:
    policy = dict(
        id=POLICY_ID,
        mode="tiered",
        revision=1,
        contract_version="dc11-write-policy.v1",
        operation_settings={
            "meeting.minutes.draft": dict(
                mode="automatic",
                minimum_confirmation_basis_points=9000,
                maximum_retraction_basis_points=500,
            )
        },
    )
    context: dict[str, Any] = dict(
        policy=policy,
        publication=publication(),
        rows=[row()],
        fresh=collection(as_of=NOW),
        fresh_calls=[],
    )
    monkeypatch.setattr(state_module, "_current", lambda *args: context["policy"])

    def published(*args: Any, **kwargs: Any) -> PublishedWriteEvaluation | None:
        assert kwargs["as_of"] == NOW
        value = context["publication"]
        if isinstance(value, Exception):
            raise value
        return cast(PublishedWriteEvaluation | None, value)

    def fresh(*args: Any, **kwargs: Any) -> TrialCollection:
        context["fresh_calls"].append(kwargs)
        value = context["fresh"]
        if isinstance(value, Exception):
            raise value
        return cast(TrialCollection, value)

    monkeypatch.setattr(state_module, "configured_write_evaluation", published)
    monkeypatch.setattr(state_module, "collect_trial", fresh)

    def read(**changes: Any) -> QualificationState:
        connection = ReadConnection(context["rows"])
        arguments: dict[str, Any] = (
            dict(
                tenant_id=fixtures.TENANT,
                project_id=UUID(int=3),
                operation_key="meeting.minutes.draft",
                binding=fixtures.binding(),
                as_of=NOW,
            )
            | changes
        )
        return state_module.read_qualification_state(cast(Connection, connection), **arguments)

    return context, read


def codes(result: QualificationState) -> set[str]:
    return {reason.code for reason in result.reasons}


def test_current_requires_old_receipt_current_publication_and_fresh_read(reader: Any) -> None:
    context, read = reader
    before = deepcopy(context["rows"])
    result = read()
    assert result.state == "current"
    assert not result.qualification_granted
    assert result.reasons == ()
    assert result.protocol_id == protocol().id and result.receipt_id == UUID(int=4)
    assert result.configuration == configuration()
    assert result.configuration.sampling_basis_points == 1000
    assert (
        result.publication is not None
        and result.publication.evaluation_id == fixtures.evaluation().evaluation_id
    )
    assert result.fresh_check is not None and result.fresh_check.raw_total == 20
    assert context["fresh_calls"][0]["as_of"] == NOW
    assert context["fresh_calls"][0]["window_start"] == fixtures.START
    assert context["fresh_calls"][0]["project_ids"] == protocol().project_ids
    assert context["rows"] == before


@pytest.mark.parametrize("action", ["withdrawn_at", "edited_at"])
def test_later_handling_cannot_reuse_old_pass(reader: Any, action: str) -> None:
    context, read = reader
    drafts = tuple(fixtures.draft(i, **{action: NOW if i < 3 else None}) for i in range(20))
    context["fresh"] = collection(as_of=NOW, drafts=drafts)
    result = read()
    assert result.state == "blocked"
    assert "fresh_criteria_not_met" in codes(result)
    assert result.receipt_id == UUID(int=4)
    assert context["rows"][0]["receipt"]["qualification"]["status"] == "meets_candidate_criteria"


def test_later_failure_across_protocols_supersedes_old_pass(reader: Any) -> None:
    context, read = reader
    newer = row(
        number=5,
        proto=protocol(44),
        created_at=fixtures.CUTOFF + timedelta(seconds=2),
        drafts=tuple(fixtures.draft(i) for i in range(19)),
    )
    context["rows"] = [newer, row()]
    result = read()
    assert result.receipt_id == UUID(int=5) and result.protocol_id == UUID(int=44)
    assert result.checked_receipt_count == 2
    assert "latest_receipt_not_met" in codes(result)
    assert result.state == "blocked"


def test_fresh_pass_does_not_rewrite_latest_failed_receipt(reader: Any) -> None:
    context, read = reader
    context["rows"] = [row(drafts=tuple(fixtures.draft(i) for i in range(19)))]
    result = read()
    assert "latest_receipt_not_met" in codes(result)
    assert result.fresh_check.qualification.status == "meets_candidate_criteria"
    assert result.state == "blocked"


def test_new_historical_cutoff_cannot_hide_more_recent_failed_observation(reader: Any) -> None:
    context, read = reader
    older_cutoff_new_receipt = row(number=5, created_at=NOW - timedelta(seconds=1))
    later_cutoff = row(
        number=4,
        as_of=fixtures.CUTOFF + timedelta(minutes=1),
        drafts=tuple(fixtures.draft(i) for i in range(19)),
    )
    context["rows"] = [older_cutoff_new_receipt, later_cutoff]
    assert "receipt_cutoff_regressed" in codes(read())


def test_uncollected_declaration_does_not_revoke_existing_material(reader: Any) -> None:
    context, read = reader
    uncollected = row(number=5, proto=protocol(44)) | {"receipt_record_id": None, "receipt": None}
    context["rows"] = [row(), uncollected]
    result = read()
    assert result.state == "current"
    assert result.checked_receipt_count == 1


def test_missing_real_business_receipt_returns_unavailable(reader: Any) -> None:
    context, read = reader
    context["rows"] = []
    result = read()
    assert result.state == "unavailable"
    assert codes(result) == {"real_business_trial_missing"}
    assert context["fresh_calls"] == []


@pytest.mark.parametrize(
    "status", [None, WriteEvaluationPublicationError("publication_outside_validity_window")]
)
def test_publication_missing_or_expired_never_uses_saved_pass(reader: Any, status: Any) -> None:
    context, read = reader
    context["publication"] = status
    result = read()
    assert result.state != "current" and "evaluation_unavailable" in codes(result)
    assert result.publication is None


@pytest.mark.parametrize("change", ["publication_sha256", "publication_id", "evaluation"])
def test_changed_publication_or_evaluation_requires_new_fixed_collection(
    reader: Any, change: str
) -> None:
    context, read = reader
    replacement: Any = (
        "b" * 64
        if change == "publication_sha256"
        else UUID(int=71)
        if change == "publication_id"
        else fixtures.evaluation(evaluation_id=UUID(int=9))
    )
    context["publication"] = publication(**{change: replacement})
    result = read()
    assert result.state == "blocked"
    assert "evaluation_publication_changed" in codes(result)


@pytest.mark.parametrize(
    "field", ["minimum_confirmation_basis_points", "maximum_retraction_basis_points"]
)
def test_current_stricter_threshold_cannot_reuse_wider_config(reader: Any, field: str) -> None:
    context, read = reader
    context["policy"]["operation_settings"]["meeting.minutes.draft"][field] = (
        9500 if field == "minimum_confirmation_basis_points" else 100
    )
    result = read()
    assert result.state == "blocked" and "thresholds_changed" in codes(result)


@pytest.mark.parametrize(
    "field,value", [("revision", 2), ("mode", "legacy"), ("contract_version", "other.v2")]
)
def test_old_binding_does_not_match_current_policy(reader: Any, field: str, value: Any) -> None:
    context, read = reader
    context["policy"][field] = value
    assert codes(read()) == {"current_policy_mismatch"}
    assert context["fresh_calls"] == []


def test_disabled_operation_and_absent_policy_stop_before_collection(reader: Any) -> None:
    context, read = reader
    context["policy"]["operation_settings"]["meeting.minutes.draft"]["mode"] = "disabled"
    assert codes(read()) == {"operation_disabled"}
    context["policy"] = None
    assert codes(read()) == {"current_policy_mismatch"}


@pytest.mark.parametrize("target", ["protocol", "configuration", "receipt", "qualification"])
def test_original_digests_and_calculation_are_rechecked(reader: Any, target: str) -> None:
    context, read = reader
    source = context["rows"][0]
    if target == "protocol":
        source["protocol"]["reason"] = "changed"
    elif target == "configuration":
        source["protocol"]["configuration"]["sampling_basis_points"] = 2000
        source["protocol"]["protocol_digest"] = state_module._digest(
            {k: v for k, v in source["protocol"].items() if k != "protocol_digest"}
        )
    elif target == "receipt":
        source["receipt"]["as_of"] = NOW.isoformat()
    else:
        source["receipt"]["qualification"]["input_digest"] = "0" * 64
        source["receipt"]["receipt_digest"] = state_module._digest(
            {k: v for k, v in source["receipt"].items() if k != "receipt_digest"}
        )
    result = read()
    assert result.state == "blocked"
    assert (
        "protocol_invalid" if target in {"protocol", "configuration"} else "receipt_invalid"
    ) in codes(result)
    assert context["fresh_calls"] == []


@pytest.mark.parametrize("kind", ["synthetic", "controlled_replay"])
def test_non_real_fresh_collection_cannot_be_promoted(reader: Any, kind: str) -> None:
    context, read = reader
    context["fresh"] = collection(
        as_of=NOW, drafts=tuple(fixtures.draft(i, evidence_kind=kind) for i in range(20))
    )
    result = read()
    assert {"fresh_collection_incomplete", "fresh_criteria_not_met"} <= codes(result)


def test_fresh_source_failure_or_partial_counts_never_pass(reader: Any) -> None:
    context, read = reader
    context["fresh"] = ValueError("source metadata unavailable")
    assert "fresh_collection_unavailable" in codes(read())
    context["fresh"] = collection(as_of=NOW).model_copy(update={"raw_total": 21})
    assert "fresh_collection_incomplete" in codes(read())


def test_invalid_actual_operation_is_not_treated_as_registered_binding(reader: Any) -> None:
    _, read = reader
    assert codes(read(operation_key="meeting.actions.draft")) == {"operation_binding_mismatch"}
    with pytest.raises(ValueError):
        read(operation_key="formal_action.execute")


def test_history_query_never_filters_passing_or_limits_matching_receipts() -> None:
    query = qualification_history_query(
        tenant_id=fixtures.TENANT, project_id=UUID(int=3), binding=fixtures.binding(), as_of=NOW
    )
    compiled = query.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    sql = str(compiled)
    assert "LEFT OUTER JOIN" in sql and "LIMIT" not in sql and "OFFSET" not in sql
    assert "meets_candidate_criteria" not in sql and "qualification" not in sql
    assert "ORDER BY cehub_ai.ai_write_trial_receipts.created_at DESC NULLS LAST" in sql
    selectors = [value for value in compiled.params.values() if isinstance(value, dict)]
    assert selectors == [
        {
            "project_ids": [str(UUID(int=3))],
            "binding": fixtures.binding().model_dump(mode="json"),
            "evidence_kind": "real_business",
        }
    ]
