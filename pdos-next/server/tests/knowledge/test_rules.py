from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.command_handlers import CATEGORY_OPERATIONS, tier_of
from pdos_next.domain.knowledge import rules
from pdos_next.domain.knowledge.schemas import CANDIDATE_OP, RULE_OP, RulePublishPayload
from pdos_next.errors import DomainError


def payload(**changes):
    at = datetime(2026, 10, 18, tzinfo=UTC)
    return {
        "project_id": str(uuid4()),
        "candidate": {"id": str(uuid4()), "revision": 1},
        "title": "实际配置内的经验规则",
        "rule_text": "仅按所列条件适用。",
        "applicability": {
            "target": {"kind": "engineering_configuration", "id": str(uuid4()), "revision": 1},
            "purpose": "评估当前配置的试样过程",
            "differences": [],
            "conditions": [],
            "adopted_rule": "采用具名评估确定的边界。",
            "decision": "applicable",
            "rationale": "固定实际证据并说明差异。",
            "valid_from": at.isoformat(),
            "valid_until": None,
        },
        "sources": [
            {
                "kind": "artifact",
                "id": str(uuid4()),
                "revision": 1,
                "position": "line:1;quote_sha256:" + "a" * 64,
            }
        ],
        "reason": "保存本次固定的适用性决定。",
        **changes,
    }


def test_draft_is_category_capable_and_publication_is_named_t2():
    assert CANDIDATE_OP in CATEGORY_OPERATIONS and RULE_OP not in CATEGORY_OPERATIONS
    assert tier_of(CANDIDATE_OP) == "T0" and tier_of(RULE_OP) == "T2"


@pytest.mark.parametrize("decision", ["unknown", "conflicted", "not_applicable"])
def test_negative_or_unknown_assessment_never_publishes(decision):
    raw = payload()
    raw["applicability"]["decision"] = decision
    data = RulePublishPayload.model_validate(raw)
    with pytest.raises(DomainError) as caught:
        rules.assessment_body(data, SimpleNamespace(id=uuid4(), revision=1), uuid4())
    assert caught.value.code == "MISSING_REQUIRED_EVIDENCE"


@pytest.mark.parametrize("authority", ["actor_id", "tier", "qualified", "visibility"])
def test_payload_cannot_supply_publication_identity_or_authority(authority):
    with pytest.raises(ValidationError):
        RulePublishPayload.model_validate(payload(**{authority: "injected"}))


def test_validity_is_half_open_and_unusable_dependencies_take_precedence():
    at = datetime(2026, 10, 18, tzinfo=UTC)
    end = at + timedelta(days=1)
    assert rules.usability(at, at, end, [])["state"] == "current"
    assert rules.usability(end, at, end, [])["state"] == "expired"
    assert rules.usability(at - timedelta(seconds=1), at, None, [])["state"] == "not_yet_effective"
    assert rules.usability(at, at, None, ["SOURCE_STALE"])["state"] == "needs_recheck"


def test_named_credential_is_not_saved_in_business_semantics():
    raw = payload(approval_token="secret-server-token-for-confirmation")
    data = RulePublishPayload.model_validate(raw)
    assert "approval_token" not in rules.semantic(data)
    assert rules.semantic(data)["applicability"]["conditions"] == []


def test_same_id_with_conflicting_retained_content_is_refused():
    with pytest.raises(DomainError) as caught:
        rules.merge_artifacts([{"id": "fixed", "revision": 1}], [{"id": "fixed", "revision": 2}])
    assert caught.value.code == "SOURCE_STALE"
