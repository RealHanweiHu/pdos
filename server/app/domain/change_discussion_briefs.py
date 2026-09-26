"""Deterministic, source-bound discussion briefs and named human comparison receipts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    tradeoff: str = Field(min_length=1, max_length=4000)
    turn_ids: list[UUID] = Field(min_length=1, max_length=32)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["validated", "rejected"]
    manual_conclusion: str = Field(min_length=1, max_length=4000)
    comparison: str = Field(min_length=1, max_length=4000)
    recommendation: str = Field(min_length=1, max_length=4000)
    evidence_checked: bool
    disagreements_complete: bool
    alternatives: list[Alternative] = Field(max_length=8)

    @model_validator(mode="after")
    def checked(self) -> Review:
        if self.outcome == "validated" and (
            not self.evidence_checked
            or not self.disagreements_complete
            or len(self.alternatives) < 2
        ):
            raise ValueError("核对通过须检查依据、确认分歧覆盖并比较至少两个备选方案")
        if len({v.title for v in self.alternatives}) != len(self.alternatives):
            raise ValueError("备选方案名称不能重复")
        return self


def assemble(run: dict[str, Any]) -> dict[str, Any]:
    """Preserve actual claims; an explicit response is not inferred consensus."""
    turns = {t["id"]: t for t in run["turns"]}
    receipts = {r["turn_id"]: r for r in run["receipts"]}
    seats = run["config"]["seats"]
    positions, responses, missing, coverage = [], [], [], []
    source_coverage = run["source_coverage"]
    contribution = run.get("contributions", {})
    stable_stop = (
        run["status"] == "succeeded"
        and run["session"]["stop_reason"] == "unchanged_full_round"
        and contribution.get("can_stop_unchanged") is True
    )
    for gap in [*source_coverage.get("unresolved", []), *source_coverage.get("gaps", [])]:
        missing.append({"seat_id": None, "turn_id": None, "message": gap["message"]})
    for gap in [*source_coverage.get("graph_limits", []), *source_coverage.get("scope_gaps", [])]:
        missing.append({"seat_id": None, "turn_id": None, "message": gap})
    if source_coverage.get("omitted_reference_count") or source_coverage.get(
        "partial_reference_count"
    ):
        missing.append(
            {
                "seat_id": None,
                "turn_id": None,
                "message": "原准备资料有未纳入引用或省略字段，不能据此判断完整影响范围",
            }
        )
    for seat in seats:
        actual = [t for t in turns.values() if t["seat_id"] == seat["id"] and t["id"] in receipts]
        missing_rounds = [
            n
            for n in range(1, run["config"]["request"]["rounds"] + 1)
            if not any(t["round_number"] == n for t in actual)
        ]
        coverage.append(
            {
                "seat_id": seat["id"],
                "label": seat["label"],
                "saved_turns": len(actual),
                "missing_rounds": missing_rounds,
                "repeated_turns": sum(bool(t["repetition_of_turn_id"]) for t in actual),
            }
        )
        if run["config"].get("discussion_policy"):
            coverage[-1]["not_needed_rounds"] = missing_rounds if stable_stop else []
            if stable_stop:
                coverage[-1]["missing_rounds"] = []
        for message in seat.get("missing", []):
            missing.append({"seat_id": seat["id"], "turn_id": None, "message": message})
    for turn in turns.values():
        receipt = receipts.get(turn["id"])
        if receipt is None:
            continue
        output = receipt["output"]
        anchor = {
            "turn_id": turn["id"],
            "seat_id": turn["seat_id"],
            "sequence": turn["sequence"],
            "round_number": turn["round_number"],
            "checkpoint_id": receipt["checkpoint_id"],
        }
        for i, statement in enumerate(output["statements"]):
            positions.append({**anchor, "statement_index": i, "statement": statement})
        for response in output["responses"]:
            target = turns[response["turn_id"]]
            responses.append(
                {
                    **anchor,
                    "target_turn_id": response["turn_id"],
                    "target_sequence": target["sequence"],
                    "cross_seat": target["seat_id"] is not None
                    and target["seat_id"] != turn["seat_id"],
                    "position": response["position"],
                    "basis": response["basis"],
                }
            )
        for message in output["missing"]:
            missing.append({"seat_id": turn["seat_id"], "turn_id": turn["id"], "message": message})
    body = {
        "version": "change-discussion-brief-v1",
        "run_id": run["run_id"],
        "source_digest": run["source_digest"],
        "question": run["session"]["question"],
        "status": run["effective_status"],
        "run_status": run["status"],
        "error_code": run["error_code"],
        "stop_reason": run["session"]["stop_reason"],
        "recovery_requested": run["recovery_requested"],
        "complete": run["status"] == "succeeded"
        and run["effective_status"] == "completed"
        and all(not s["missing_rounds"] for s in coverage),
        "coverage": coverage,
        "positions": positions,
        "responses": responses,
        "missing": missing,
        "human_inputs": [
            {"turn_id": t["id"], "author_user_id": t["author_user_id"], "content": t["content"]}
            for t in turns.values()
            if t["speaker_kind"] == "human"
        ],
        "turn_ids": list(turns),
        "recorded_turn_tokens": sum(t["input_tokens"] + t["output_tokens"] for t in turns.values()),
        "budget_profile": run["config"].get("budget_profile"),
    }
    if run["config"].get("discussion_policy"):
        body["version"] = "change-discussion-brief-v2"
        body["contributions"] = contribution
        body["ended_without_new_content"] = stable_stop
    if run["config"].get("initiation"):
        body["initiation"] = run.get("initiation")
        body["discussion_convened"] = bool(
            run.get("initiation") and run["initiation"]["output"]["action"] == "convene"
        )
        body["complete"] = body["complete"] and body["discussion_convened"]
    if run.get("origin_choice"):
        body["origin"] = {"run_id": run["origin_run_id"], "choice": run["origin_choice"]}
    if run.get("research_choices"):
        body["research_choices"] = run["research_choices"]
        body["research_tools"] = run["research_tools"]
    if run.get("research_inputs"):
        body["research_inputs"] = run["research_inputs"]
    return {"body": body, "digest": digest(body)}


def history(c: Connection, tenant: UUID, run: UUID) -> list[dict[str, Any]]:
    t, u = tables.debate_brief_reviews, tables.users
    return [
        _plain(dict(r))
        for r in c.execute(
            select(t, u.c.display_name.label("author_name"))
            .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
            .where(t.c.tenant_id == tenant, t.c.run_id == run)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
        ).mappings()
    ]


def review(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ecr_id: UUID | None,
    run_id: UUID,
    command: Review,
) -> dict[str, Any]:
    from app.ai.change_discussion_contract import RUN_VERSION
    from app.ai.change_discussion_runs import authorize, binding, event, result
    from app.ai.discussion_sources import current as current_source
    from app.ai.discussion_sources import require_disclosure

    authorize(engine, context, project, edit=True)
    tenant = context.tenant.id
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
            raise ProductWorkError("项目不可用")
        runs, reviews = tables.agent_runs, tables.debate_brief_reviews
        row = (
            c.execute(
                select(runs)
                .where(
                    runs.c.tenant_id == tenant,
                    runs.c.project_id == project,
                    runs.c.id == run_id,
                    runs.c.context_version == RUN_VERSION,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原讨论不存在")
        bound = binding(c, tenant, run_id)
        require_disclosure(c, tenant, context.user.id, bound)
        if bound["ecr_id"] != ecr_id:
            raise ProductWorkError("讨论不属于此变更")
        payload = command.model_dump(mode="json")
        previous = (
            c.execute(
                select(reviews).where(
                    reviews.c.tenant_id == tenant,
                    reviews.c.created_by_user_id == context.user.id,
                    reviews.c.request_id == command.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous:
            if previous["run_id"] != run_id or previous["body"] != payload:
                raise ProductWorkError("原核对请求已有不同内容")
            return result(c, row)
        run = result(c, row)
        if command.outcome == "validated" and not run.get("research_current", True):
            raise ProductWorkError("追加研究资料已变化，请先核对原快照与当前有效性")
        preview = run["brief"]
        if row["status"] in {"queued", "running"} or (
            run["recovery_requested"] and row["status"] == "degraded"
        ):
            raise ProductWorkError("请等待本次讨论停止后再核对摘要")
        if not run["receipts"]:
            raise ProductWorkError("本次没有已保存的真实专业发言可供核对")
        if preview["digest"] != command.expected_digest:
            raise ProductWorkError("讨论已有变化，请刷新摘要后重新核对")
        current = current_source(c, tenant, project, bound)
        if command.outcome == "validated" and current["digest"] != bound["source"]["digest"]:
            raise ProductWorkError("原依据已变化；请保留历史或退回，并按当前资料重新分析")
        actual_turns = {r["turn_id"] for r in run["receipts"]}
        for alternative in command.alternatives:
            if not {str(v) for v in alternative.turn_ids} <= actual_turns:
                raise ProductWorkError("备选方案必须引用本次真实专业发言")
        c.execute(
            reviews.insert().values(
                id=uuid4(),
                tenant_id=tenant,
                run_id=run_id,
                request_id=command.request_id,
                created_by_user_id=context.user.id,
                brief_digest=preview["digest"],
                source_digest=current["digest"],
                snapshot=preview["body"],
                body=payload,
            )
        )
        event(c, tenant, bound["session_id"], "brief_" + command.outcome, context.user.id)
        return result(c, row)


def comparison_summaries(
    c: Connection, tenant: UUID, project: UUID, ecr_id: UUID
) -> list[dict[str, Any]]:
    """Historical comparison receipts; current source validity is checked in the discussion."""
    r, b, u = tables.debate_brief_reviews, tables.debate_run_bindings, tables.users
    return [
        _plain(dict(v))
        for v in c.execute(
            select(
                r.c.id,
                r.c.run_id,
                r.c.created_at,
                r.c.body,
                r.c.snapshot["question"].astext.label("question"),
                u.c.display_name.label("author_name"),
            )
            .join(b, (b.c.tenant_id == r.c.tenant_id) & (b.c.run_id == r.c.run_id))
            .join(u, (u.c.tenant_id == r.c.tenant_id) & (u.c.id == r.c.created_by_user_id))
            .where(b.c.tenant_id == tenant, b.c.project_id == project, b.c.ecr_id == ecr_id)
            .order_by(r.c.created_at.desc(), r.c.id.desc())
            .limit(20)
        ).mappings()
    ]
