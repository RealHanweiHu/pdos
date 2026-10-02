"""Descriptive, per-run Issue observations; no qualification thresholds or authority."""

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import StrictBool, model_validator

from app.contracts.common_objects import Contract


class IssueTrialItem(Contract):
    """Normalized original facts; the collector owns provenance and complete selection."""

    run_id: UUID
    status: Literal[
        "debouncing", "queued", "running", "waiting_input", "succeeded", "degraded", "failed"
    ]
    result_id: UUID | None
    disposition: Literal["create_issue", "reuse_issue", "insufficient_evidence"] | None
    binding_kind: Literal["trial_candidate", "evidence_only", "not_recorded"]
    review_state: Literal["unreviewed", "declined", "reopened"]
    application_kind: Literal["created", "reused"] | None
    same_source_applied: StrictBool
    withdrawn: StrictBool
    human_edited: StrictBool

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.result_id is None) != (self.disposition is None):
            raise ValueError("原生成结果与建议处置须同时存在或同时为空")
        if self.result_id is not None and self.status != "succeeded":
            raise ValueError("原建议结果须对应成功运行，不能过滤异常运行后统计")
        if self.review_state != "unreviewed" and self.result_id is None:
            raise ValueError("不采纳或重新考虑须对应原建议结果")
        if self.application_kind is not None:
            expected = {"created": "create_issue", "reused": "reuse_issue"}[self.application_kind]
            if self.result_id is None or self.disposition != expected:
                raise ValueError("本运行应用须对应原建议及其处置")
            if self.review_state == "declined":
                raise ValueError("当前不采纳的建议不能同时已由本运行应用")
            if self.same_source_applied:
                raise ValueError("本运行应用不能同时记为其他运行的同源应用")
        if (self.withdrawn or self.human_edited) and self.application_kind != "created":
            raise ValueError("撤回或后续人工办理仅统计本运行实际创建的问题")
        if self.withdrawn and self.human_edited:
            raise ValueError("后续人工编辑或办理的问题不得同时标为已撤回")
        return self


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Count the supplied full run population, preserving pending/failed/old bindings.

    Ratios describe runs, not unique sources. Another run's same-source application
    neither adopts this run nor prevents its current declined opinion being counted.
    A reopened opinion is no longer a decline; only a later own application handles it.
    """
    rows = [IssueTrialItem.model_validate(item) for item in items]
    if len({row.run_id for row in rows}) != len(rows):
        raise ValueError("同一运行只能统计一次，请核对完整观察范围")
    counts = {
        "total_runs": len(rows),
        "succeeded_runs": sum(r.status == "succeeded" for r in rows),
        "failed_runs": sum(r.status in {"failed", "degraded"} for r in rows),
        "pending_runs": sum(r.status not in {"succeeded", "failed", "degraded"} for r in rows),
        "proposal_runs": sum(r.result_id is not None for r in rows),
        "insufficient_runs": sum(r.disposition == "insufficient_evidence" for r in rows),
        "created_issues": sum(r.application_kind == "created" for r in rows),
        "reused_issues": sum(r.application_kind == "reused" for r in rows),
        "same_source_applied_runs": sum(r.same_source_applied for r in rows),
        "declined_runs": sum(r.review_state == "declined" for r in rows),
        "reopened_runs": sum(r.review_state == "reopened" for r in rows),
        "unhandled_proposals": sum(
            r.result_id is not None
            and r.application_kind is None
            and r.review_state != "declined"
            and not r.same_source_applied
            for r in rows
        ),
        "withdrawn_issues": sum(r.withdrawn for r in rows),
        "human_edited_issues": sum(r.human_edited for r in rows),
        "trial_candidates": sum(r.binding_kind == "trial_candidate" for r in rows),
        "evidence_only_runs": sum(r.binding_kind == "evidence_only" for r in rows),
        "unrecorded_bindings": sum(r.binding_kind == "not_recorded" for r in rows),
    }
    handled = sum(r.application_kind is not None or r.review_state == "declined" for r in rows)
    confirmed = counts["created_issues"] + counts["reused_issues"]
    created = counts["created_issues"]
    return {
        "counts": counts,
        "ratios": {
            "handled_proposals": handled,
            "confirmed_proposals": confirmed,
            "confirmation_basis_points": confirmed * 10_000 // handled if handled else None,
            "withdrawal_basis_points": counts["withdrawn_issues"] * 10_000 // created
            if created
            else None,
            "descriptive_only": True,
        },
        "qualification_granted": False,
    }
