"""Versioned execution evidence and named independent confirmation of approved scope."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.change_execution_evidence import (
    EVIDENCE_TABLES,
    EvidenceKind,
    assess,
    performers,
    read_evidence,
    scope_changes,
)
from app.domain.change_execution_followups import (
    FollowupResponse,
    followup_allowed,
    records,
    response_gaps,
)
from app.domain.change_execution_tasks import _task
from app.domain.change_impact_scope import _ecr
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_verification_paths import _authorize


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: EvidenceKind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["verification", "comparison"]
    correspondence: str = Field(min_length=1, max_length=4000)


class ReviewerChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    previous_result_id: UUID
    expected_review_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


class ResultDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["recorded", "needs_follow_up", "ready_for_confirmation"]
    reviewer_user_id: UUID | None = None
    completed_scope: str = Field(min_length=1, max_length=10000)
    excluded_scope: str = Field(min_length=1, max_length=10000)
    criteria_response: str = Field(min_length=1, max_length=10000)
    follow_up: str = Field(min_length=1, max_length=10000)
    reason: str = Field(min_length=1, max_length=4000)
    references: list[Reference] = Field(default_factory=list, max_length=100)
    follow_up_responses: list[FollowupResponse] = Field(default_factory=list)
    reviewer_change: ReviewerChange | None = None

    @model_validator(mode="after")
    def unique_references(self) -> ResultDraft:
        if len({r.followup_id for r in self.follow_up_responses}) != len(self.follow_up_responses):
            raise ValueError("同一后续任务请合并回应")
        if len({(r.kind, r.id) for r in self.references}) != len(self.references):
            raise ValueError("同一证据请合并适用范围后引用一次")
        if self.outcome == "ready_for_confirmation" and not self.reviewer_user_id:
            raise ValueError("请指定独立结果确认人")
        if self.reviewer_change and self.outcome != "ready_for_confirmation":
            raise ValueError("确认人变更仅适用于待独立确认的结果")
        return self


class ConfirmDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["verified", "returned"]
    note: str = Field(min_length=1, max_length=4000)


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    _authorize(engine, context, project_id, edit=False)
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context, project_id=project_id, action=action
    )


def _latest(c: Connection, tenant_id: UUID, binding_id: UUID) -> dict[str, Any] | None:
    t = tables.change_execution_results
    row = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.binding_id == binding_id)
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _basis(c: Connection, tenant_id: UUID, project_id: UUID, binding_id: UUID) -> dict[str, Any]:
    t = tables.change_execution_tasks
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == binding_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原变更执行条目不存在")
    ecr = _ecr(c, tenant_id, project_id, row["ecr_id"])
    approved = ((ecr["impact_analysis"] or {}).get("impact_scope") or {}).get("basis")
    still_bound = bool(
        ecr["status"] == "approved"
        and approved
        and approved["version"]["id"] == str(row["scope_version_id"])
    )
    latest = _latest(c, tenant_id, binding_id)
    return _plain(
        {
            "binding": dict(row),
            "ecr": {
                k: ecr[k]
                for k in ("id", "code", "title", "status", "approved_at", "approval_decision_id")
            },
            "task": _task(c, tenant_id, project_id, row["task_id"]),
            "follow_ups": records(c, tenant_id, project_id, [binding_id]),
            "scope_changes": scope_changes(c, tenant_id, project_id, approved)
            if still_bound and approved is not None
            else [],
            "approved_scope_context": {
                "revision": approved["version"]["revision_number"],
                "coverage": approved["version"]["snapshot"]["coverage"],
                "exclusions": approved["version"]["snapshot"]["exclusions"],
            }
            if still_bound and approved is not None
            else None,
            "scope_bound": still_bound,
            "latest_result_id": latest["id"] if latest else None,
        }
    )


def _reviewers(c: Connection, tenant_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
    u, m = tables.users, tables.project_members
    values = c.execute(
        select(u.c.id, u.c.display_name, u.c.role)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(u.c.tenant_id == tenant_id, m.c.project_id == project_id, u.c.is_active.is_(True))
        .order_by(u.c.display_name, u.c.id)
    ).mappings()
    return [_plain(dict(v)) for v in values if is_allowed(Role(v["role"]), Action.CHANGE_APPROVE)]


def _assess_references(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    basis: dict[str, Any],
    references: list[dict[str, Any]],
    *,
    evidence_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    values = []
    for ref in references:
        try:
            key = (ref["kind"], ref["id"])
            if evidence_cache is not None and key in evidence_cache:
                current = evidence_cache[key]
                if current is None:
                    raise ProductWorkError("原证据已不可用")
            else:
                current = read_evidence(c, tenant_id, project_id, ref["kind"], UUID(ref["id"]))
                if evidence_cache is not None:
                    evidence_cache[key] = current
            assessment = assess(
                ref["kind"],
                current,
                basis["binding"]["snapshot"]["item"],
                basis["ecr"]["approved_at"],
            )
            changed = digest(current) != ref["expected_digest"]
        except ProductWorkError:
            if evidence_cache is not None:
                evidence_cache[(ref["kind"], ref["id"])] = None
            current = None
            assessment = {
                "eligible": False,
                "gaps": ["原证据已不可用"],
                "correspondence": "unavailable",
            }
            changed = True
        values.append({**ref, "current": current, "assessment": assessment, "changed": changed})
    return values


def _gaps(basis: dict[str, Any], refs: list[dict[str, Any]]) -> list[str]:
    gaps = []
    if not basis["scope_bound"]:
        gaps.append("原获批范围绑定已不可用")
    if any(change["blocking"] for change in basis["scope_changes"]):
        gaps.append("获批设计范围或关系证据内容已有变化")
    required = {
        "retest": "test_run",
        "rereview": "engineering_review",
        "recertification": "certification",
        "coordination": "document",
    }[basis["binding"]["snapshot"]["item"]["action"]]
    verifying = [r for r in refs if r["role"] == "verification"]
    if not any(r["kind"] == required for r in verifying):
        gaps.append("缺少本类执行要求的实际完成证据")
    if any(r["changed"] for r in refs):
        gaps.append("已选原证据发生变化，请重新对应")
    if any(not r["assessment"]["eligible"] for r in verifying):
        gaps.append("验证证据尚有日期、版本、结果或范围对应缺口")
    return gaps


def _confirmation(c: Connection, tenant_id: UUID, result_id: UUID) -> dict[str, Any] | None:
    t = tables.change_execution_confirmations
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant_id, t.c.result_id == result_id))
        .mappings()
        .one_or_none()
    )
    return _plain(dict(row)) if row else None


def carried_participants(result: dict[str, Any]) -> set[str]:
    snapshot = result["snapshot"]
    change = snapshot.get("reviewer_change") or {}
    return {
        str(user)
        for user in (
            result["created_by_user_id"],
            snapshot["task_at_submission"].get("assignee_user_id"),
            *(f.get("assignee_user_id") for f in snapshot.get("follow_ups_at_submission", [])),
            *change.get("carried_participant_ids", []),
            *performers(snapshot["references"]),
        )
        if user
    }


def require_reviewer_change(
    c: Connection,
    tenant: UUID,
    previous: dict[str, Any] | None,
    draft: ResultDraft,
    basis: dict[str, Any],
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    change = draft.reviewer_change
    if (
        not change
        or not previous
        or previous["id"] != change.previous_result_id
        or previous["outcome"] != "ready_for_confirmation"
        or _confirmation(c, tenant, previous["id"])
    ):
        raise ProductWorkError("仅可更换最新尚未确认结果的确认人，请刷新原记录")
    if previous["reviewer_user_id"] == draft.reviewer_user_id:
        raise ProductWorkError("请选择不同的独立确认人")
    original = previous["snapshot"]
    fields = {"completed_scope", "excluded_scope", "criteria_response", "follow_up", "reason"}
    expected = {key: original[key] for key in fields}
    expected["follow_up_responses"] = original.get("follow_up_responses", [])
    expected["references"] = [
        {key: r[key] for key in Reference.model_fields} for r in original["references"]
    ]
    if (
        draft.model_dump(mode="json", include=fields | {"references", "follow_up_responses"})
        != expected
    ):
        raise ProductWorkError(
            "确认人变更须沿用原范围、判据、后续回应与固定证据；内容修订请另存完整结果"
        )
    review_refs = [
        {**original_ref, **current_ref}
        for original_ref, current_ref in zip(original["references"], refs, strict=True)
    ]
    review_basis = {"basis": basis, "result": _plain(previous), "references": review_refs}
    if digest(review_basis) != change.expected_review_digest:
        raise ProductWorkError("原结果或证据已变化，请重新核对确认人变更")
    return {
        **change.model_dump(mode="json"),
        "previous_reviewer_user_id": str(previous["reviewer_user_id"]),
        "previous_revision": previous["revision_number"],
        "carried_participant_ids": sorted(carried_participants(previous)),
    }


def read(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    before_revision: int | None = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        t = tables.change_execution_results
        q = select(t).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project_id,
            t.c.binding_id == binding_id,
        )
        if before_revision is not None:
            q = q.where(t.c.revision_number < before_revision)
        rows = c.execute(q.order_by(t.c.revision_number.desc()).limit(21)).mappings().all()
        history = []
        reviewers = _reviewers(c, context.tenant.id, project_id)
        for row in rows[:20]:
            refs = _assess_references(
                c, context.tenant.id, project_id, basis, row["snapshot"]["references"]
            )
            gaps = _gaps(basis, refs) + response_gaps(basis, row["snapshot"])
            review_basis = {"basis": basis, "result": _plain(dict(row)), "references": refs}
            confirmation = _confirmation(c, context.tenant.id, row["id"])
            is_latest = str(row["id"]) == basis["latest_result_id"]
            participants = (
                carried_participants(dict(row))
                | {str(context.user.id)}
                | {basis["task"]["assignee_user_id"]}
                | {f["task"]["assignee_user_id"] for f in basis["follow_ups"]}
                | performers(refs)
            )
            history.append(
                {
                    **_plain(dict(row)),
                    "current_references": refs,
                    "gaps": gaps,
                    "confirmation": confirmation,
                    "can_arrange_followup": is_latest
                    and followup_allowed(dict(row), confirmation, gaps),
                    "review_digest": digest(review_basis),
                    "is_latest": is_latest,
                    "can_change_reviewer": is_latest
                    and not confirmation
                    and not gaps
                    and row["outcome"] == "ready_for_confirmation"
                    and is_allowed(context.user.role, Action.CHANGE_EDIT)
                    and is_allowed(context.user.role, Action.TEST_RUN_RECORD),
                    "replacement_reviewers": [
                        r
                        for r in reviewers
                        if r["id"] not in participants and r["id"] != str(row["reviewer_user_id"])
                    ],
                    "effective_verified": is_latest
                    and not gaps
                    and confirmation is not None
                    and confirmation["outcome"] == "verified",
                }
            )
        actor_ids = {r["created_by_user_id"] for r in rows[:20]} | {
            r["reviewer_user_id"] for r in rows[:20] if r["reviewer_user_id"]
        }
        actor_ids.update(
            UUID(f["task"]["assignee_user_id"])
            for f in basis["follow_ups"]
            if f["task"]["assignee_user_id"]
        )
        u = tables.users
        people = (
            [
                _plain(dict(r))
                for r in c.execute(
                    select(u.c.id, u.c.display_name, u.c.is_active).where(
                        u.c.tenant_id == context.tenant.id, u.c.id.in_(actor_ids)
                    )
                ).mappings()
            ]
            if actor_ids
            else []
        )
    return {
        "basis": basis,
        "digest": digest(basis),
        "history": history,
        "next_before_revision": rows[19]["revision_number"] if len(rows) > 20 else None,
        "reviewers": reviewers,
        "people": people,
        "current_user_id": str(context.user.id),
        "can_arrange_followup": is_allowed(context.user.role, Action.CHANGE_EDIT)
        and is_allowed(context.user.role, Action.WORK_ITEM_EDIT),
        "can_record": is_allowed(context.user.role, Action.TEST_RUN_RECORD),
        "can_manage_reviewers": is_allowed(context.user.role, Action.CHANGE_EDIT)
        and is_allowed(context.user.role, Action.TEST_RUN_RECORD),
        "can_confirm": is_allowed(context.user.role, Action.CHANGE_APPROVE),
    }


def choices(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    kind: EvidenceKind,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        t = EVIDENCE_TABLES[kind]
        q = select(t.c.id).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
        if after_id:
            q = q.where(t.c.id > after_id)
        ids = list(c.execute(q.order_by(t.c.id).limit(31)).scalars())
        refs = []
        for id in ids[:30]:
            value = read_evidence(c, context.tenant.id, project_id, kind, id)
            refs.append(
                {
                    "kind": kind,
                    "id": str(id),
                    "snapshot": value,
                    "digest": digest(value),
                    "assessment": assess(
                        kind,
                        value,
                        basis["binding"]["snapshot"]["item"],
                        basis["ecr"]["approved_at"],
                    ),
                }
            )
        return {"items": refs, "next_after_id": str(ids[29]) if len(ids) > 30 else None}


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, binding_id: UUID, draft: ResultDraft
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.TEST_RUN_RECORD)
    signing = draft.model_dump(mode="json")
    if "reviewer_change" not in draft.model_fields_set:
        signing.pop("reviewer_change")
    fingerprint = digest({"project_id": str(project_id), "binding_id": str(binding_id), **signing})
    t = tables.change_execution_results
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _access(engine, context, project_id, Action.TEST_RUN_RECORD)
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("同一结果请求不能改写内容")
            return _plain(dict(prior))
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        if draft.expected_digest != digest(basis):
            raise ProductWorkError("任务、范围或结果已有变化，请刷新后核对")
        if not {str(r.followup_id) for r in draft.follow_up_responses}.issubset(
            {f["id"] for f in basis["follow_ups"]}
        ):
            raise ProductWorkError("补齐回应须对应本条要求实际已安排的后续任务")
        refs = _assess_references(
            c,
            context.tenant.id,
            project_id,
            basis,
            [r.model_dump(mode="json") for r in draft.references],
        )
        if any(r["changed"] for r in refs):
            raise ProductWorkError("已选证据已有变化或不可用，请重新选择")
        stored_refs = [{**r, "snapshot": r["current"]} for r in refs]
        previous = _latest(c, context.tenant.id, binding_id)
        reviewer_change = None
        if draft.reviewer_change:
            _access(engine, context, project_id, Action.CHANGE_EDIT)
            reviewer_change = require_reviewer_change(
                c, context.tenant.id, previous, draft, basis, refs
            )
        if draft.outcome == "ready_for_confirmation":
            gaps = _gaps(basis, refs) + response_gaps(basis, draft.model_dump(mode="json"))
            if gaps:
                raise ProductWorkError("；".join(gaps))
            excluded = (
                {str(context.user.id), basis["task"]["assignee_user_id"]}
                | {f["task"]["assignee_user_id"] for f in basis["follow_ups"]}
                | performers(stored_refs)
                | set(reviewer_change["carried_participant_ids"] if reviewer_change else [])
            )
            reviewers = {r["id"] for r in _reviewers(c, context.tenant.id, project_id)}
            if (
                str(draft.reviewer_user_id) in excluded
                or str(draft.reviewer_user_id) not in reviewers
            ):
                raise ProductWorkError("请选择具备变更确认权限且未执行/提交本次工作的独立确认人")
        snapshot = {
            **draft.model_dump(
                mode="json",
                exclude={
                    "request_id",
                    "expected_digest",
                    "references",
                    "reviewer_user_id",
                    "outcome",
                },
            ),
            "reviewer_change": reviewer_change,
            "references": [
                {k: v for k, v in ref.items() if k not in {"current", "changed"}}
                for ref in stored_refs
            ],
            "binding": basis["binding"],
            "task_at_submission": basis["task"],
            "follow_ups_at_submission": [
                {
                    "id": f["id"],
                    "task_id": f["task_id"],
                    "assignee_user_id": f["task"]["assignee_user_id"],
                }
                for f in basis["follow_ups"]
            ],
            "scope_changes_at_submission": basis["scope_changes"],
        }
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    binding_id=binding_id,
                    revision_number=previous["revision_number"] + 1 if previous else 1,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    reviewer_user_id=draft.reviewer_user_id,
                    created_at=datetime.now(UTC),
                    outcome=draft.outcome,
                    snapshot=snapshot,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=row["id"],
            record_type="change_execution_result",
            action="submitted",
            before=_snapshot(previous) if previous else None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))


def confirm(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    result_id: UUID,
    draft: ConfirmDraft,
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    fingerprint = digest(
        {
            "binding_id": str(binding_id),
            "project_id": str(project_id),
            "result_id": str(result_id),
            **draft.model_dump(mode="json"),
        }
    )
    t = tables.change_execution_confirmations
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _access(engine, context, project_id, Action.CHANGE_APPROVE)
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("同一确认请求不能改写结论")
            return _plain(dict(prior))
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        result = _latest(c, context.tenant.id, binding_id)
        if (
            not result
            or result["id"] != result_id
            or result["outcome"] != "ready_for_confirmation"
            or result["reviewer_user_id"] != context.user.id
            or _confirmation(c, context.tenant.id, result_id)
        ):
            raise ProductWorkError("请由本版具名确认人处理最新待确认结果")
        refs = _assess_references(
            c, context.tenant.id, project_id, basis, result["snapshot"]["references"]
        )
        review_basis = {"basis": basis, "result": _plain(result), "references": refs}
        if digest(review_basis) != draft.expected_digest:
            raise ProductWorkError("待确认结果、任务或证据已有变化，请刷新核对")
        excluded = (
            {
                str(result["created_by_user_id"]),
                basis["task"]["assignee_user_id"],
                result["snapshot"]["task_at_submission"]["assignee_user_id"],
            }
            | {f["task"]["assignee_user_id"] for f in basis["follow_ups"]}
            | {
                f["assignee_user_id"]
                for f in result["snapshot"].get("follow_ups_at_submission", [])
            }
            | performers(result["snapshot"]["references"])
            | carried_participants(result)
        )
        if str(context.user.id) in excluded:
            raise ProductWorkError("执行人和提交人不能独立确认自己的结果")
        if draft.outcome == "verified":
            gaps = _gaps(basis, refs) + response_gaps(basis, result["snapshot"])
            if gaps:
                raise ProductWorkError("；".join(gaps))
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    result_id=result_id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    outcome=draft.outcome,
                    note=draft.note,
                    snapshot=review_basis,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=row["id"],
            record_type="change_execution_confirmation",
            action=draft.outcome,
            before=None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))
