from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.domain import test_templates as templates
from app.domain.test_templates import TemplateSelection, catalog, coverage, template_snapshot


def pilot_selection() -> TemplateSelection:
    path = Path(__file__).resolve().parents[2] / "assets/pilots/d14-04-test-template-v1.json"
    return TemplateSelection.model_validate(json.loads(path.read_text())["selection"])


def test_pilot_has_29_required_and_light_excluded_without_copying_results() -> None:
    baseline = template_snapshot(pilot_selection(), uuid4())
    result = coverage(baseline, [], [])
    assert result["required"] == 29
    assert result["not_applicable"] == 1
    assert result["covered"] == 0 and result["missing"] == 29
    assert (
        next(item for item in result["items"] if item["state"] == "not_applicable")["title"]
        == "手电筒功能"
    )
    assert all(
        set(item)
        == {"key", "title", "category", "required", "method", "acceptance_criteria", "source"}
        for item in catalog()[0]["items"]
    )
    assert coverage(None, [], [])["coverage_percent"] is None


def test_template_version_and_type_are_not_inferred_and_snapshot_does_not_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = pilot_selection()
    baseline = template_snapshot(selection, uuid4())
    changes: list[dict[str, Any]] = [
        {"product_type": "锂电汽车泵"},
        {"version": 2},
        {"exclusions": [{"key": "unknown", "reason": "unknown"}]},
    ]
    for changed in changes:
        with pytest.raises(templates.TemplateError):
            template_snapshot(
                TemplateSelection.model_validate({**selection.model_dump(), **changed}), uuid4()
            )
    other = json.loads(json.dumps(catalog()[0]))
    other.update(id="synthetic-car-fixture", product_type="测试用汽车泵", version=2)
    other["items"] = other["items"][:2]
    monkeypatch.setattr(templates, "catalog", lambda: [other])
    second = template_snapshot(
        TemplateSelection(template_id=other["id"], version=2, product_type=other["product_type"]),
        uuid4(),
    )
    assert len(second["items"]) == 2
    assert coverage(baseline, [], [])["required"] == 29
    assert coverage(second, [], [])["required"] == 2


def test_only_latest_confirmed_evidence_counts_and_failure_is_not_pass() -> None:
    baseline = template_snapshot(pilot_selection(), uuid4())
    key = baseline["items"][0]["key"]
    now = datetime.now(UTC)
    case_id = uuid4()
    case = {"id": case_id, "template_item_key": key, "status": "passed", "updated_at": now}
    run = {
        "test_case_id": case_id,
        "run_number": 1,
        "draft_state": "draft",
        "status": "passed",
        "evidence_document_id": uuid4(),
        "updated_at": now,
    }
    assert coverage(baseline, [case], [run])["covered"] == 0
    run["draft_state"] = "confirmed"
    assert coverage(baseline, [case], [run])["covered"] == 1
    failed = {**run, "run_number": 2, "status": "failed"}
    case["status"] = "failed"
    result = coverage(baseline, [case], [run, failed])
    assert result["covered"] == 1 and result["passed"] == 0 and result["failed"] == 1
    assert coverage(baseline, [case], [{**failed, "evidence_document_id": None}])["covered"] == 0
    case["updated_at"] = now + timedelta(seconds=1)
    assert coverage(baseline, [case], [failed])["covered"] == 0
