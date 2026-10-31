"""Pure finite contracts, exact structural fields and private explicit feedback."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.enterprise_search import similar_history as history
from pdos_next.enterprise_search.similar_history_schemas import SimilarHistoryFeedback
from pdos_next.errors import DomainError
from pdos_next.service import Context


def test_structured_quality_fields_do_not_promote_hypotheses_or_action_completion():
    data = history.quality_fields({"capa": {"hypotheses": [{"text": "猜测接口磨损"}],
        "actions": [{"text": "更换接口", "completion": {"text": "已经执行"}}]}})
    assert data["root_cause"] == "未记录"
    assert data["capa_actions"] == ["更换接口"]
    assert "待复验" in data["verification"]
    assert "猜测" not in str(data)
    actual = history.quality_fields({"root_cause": {"text": "具名判定密封失效"},
        "containment": [{"text": "隔离当前批次"}],
        "capa": {"effectiveness": {"result": "ineffective"}}, "needs_recheck": True})
    assert actual["root_cause"] == "具名判定密封失效"
    assert actual["containment"] == ["隔离当前批次"]
    assert "待重核" in actual["verification"] and "无效" in actual["verification"]


def test_change_cards_read_actual_plan_implementation_verification_and_effectivity():
    value = history.change_fields({"orders": [{
        "plan": {"items": [{"intent": {"description": "更换密封设计"}}]},
        "implementations": [{"note": "新件已装配", "outcome": "completed"}],
        "verifications": [{"text": "复验仍漏气", "fact": {"result": "ineffective"}}],
        "effectivity": [{"stage": "manufacturing", "outcome": "recorded"}],
    }]})
    assert any("更换密封设计" in text for text in value["capa_actions"])
    assert any("新件已装配" in text for text in value["capa_actions"])
    assert "复验仍漏气" in value["verification"] and "manufacturing" in value["verification"]
    assert "待复验" not in value["verification"]


def test_differences_compare_only_read_structural_values_and_label_unknowns():
    product, other_product, anchor_id, other_id, project = map(str, [uuid4() for _ in range(5)])
    anchor = SimpleNamespace(id=anchor_id, product_id=product, project_id=project)
    candidate = {"source_id": other_id, "product_id": other_product, "project_id": project}
    context = {"parts": {anchor_id: ["内部:P-16"], other_id: ["内部:P-17"]},
               "builds": {anchor_id: ["D16-01"], other_id: ["D16-02"]},
               "stages": {project: "DVT"}}
    rows = history.differences(anchor, candidate, {("product", product): "型号A",
                               ("product", other_product): "型号B"}, context)
    assert [row["status"] for row in rows] == ["different", "different", "different", "same"]
    assert "P-16" in rows[1]["current"] and "D16-02" in rows[2]["candidate"]
    assert "非历史发生阶段" in rows[3]["field"]
    context["parts"] = {}
    assert history.differences(anchor, candidate, {}, context)[1]["status"] == "unknown"


@pytest.mark.parametrize("patch", [
    {"candidate_kind": "artifact"}, {"action": "approve"}, {"candidate_revision": True},
    {"tenant_id": str(uuid4())}, {"viewer_id": str(uuid4())}, {"query": "私人问题"},
])
def test_feedback_rejects_authority_private_text_and_unregistered_actions(patch):
    body = {"version_id": uuid4(), "candidate_kind": "issue", "candidate_source_id": uuid4(),
            "candidate_revision": 1, "action": "not_relevant", "request_key": uuid4()}
    with pytest.raises(ValidationError):
        SimilarHistoryFeedback.model_validate({**body, **patch})


def test_explicit_feedback_uses_server_versions_and_replays_original_key(monkeypatch):
    tenant, human, category, product, issue, version, candidate = [uuid4() for _ in range(7)]
    ctx = Context(tenant, human, human, category_id=category)
    view = {"anchor": {"project_id": str(uuid4()), "revision": 3},
            "ranking_version": "server-ranking-v1", "items": [{"kind": "issue",
                "source_id": str(candidate), "source_revision": 2, "can_prepare_merge": False}]}
    monkeypatch.setattr(history, "_human", lambda *_: None)
    monkeypatch.setattr(history, "read", lambda *_: view)
    stored = []
    session = SimpleNamespace(execute=lambda *_: None,
        scalar=lambda *_: stored[0] if stored else None,
        add=stored.append, flush=lambda: setattr(stored[-1], "id", uuid4()))
    data = SimilarHistoryFeedback(version_id=version, candidate_kind="issue",
        candidate_source_id=candidate, candidate_revision=2,
        action="not_relevant", request_key=uuid4())
    first = history.feedback(session, ctx, product, issue, data)
    assert len(stored) == 1 and stored[0].ranking_version == "server-ranking-v1"
    assert stored[0].issue_revision == 3 and stored[0].owner_id == human
    assert history.feedback(session, ctx, product, issue, data) == first
    with pytest.raises(DomainError) as conflict:
        history.feedback(session, ctx, product, issue, data.model_copy(update={"action": "opened"}))
    assert conflict.value.code == "VERSION_CONFLICT"


def test_page_service_rejects_agent_and_borrowed_scope_before_source_reads():
    tenant, human, agent, category = [uuid4() for _ in range(4)]
    ctx = Context(tenant, human, human, category_id=category)
    session = SimpleNamespace(info={"scope": (tenant, human, human, category)})
    for other in (replace(ctx, actor_id=agent), replace(ctx, category_id=None),
                  replace(ctx, agent_run_id=uuid4())):
        with pytest.raises(DomainError) as refused:
            history._human(session, other)
        assert refused.value.code == "FORBIDDEN_SCOPE"
