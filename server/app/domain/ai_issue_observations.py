"""Complete fixed-window Issue run observations; descriptive, never qualification."""

from datetime import timedelta
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator
from sqlalchemy import Connection, Engine, func, select, tuple_

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.ai_issue_trial_summary import IssueTrialItem, aggregate
from app.domain.ai_issue_write_access import authorize
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

VERSION = "event-issue-observation-v1"
MAX_RUNS = 5000
NOTICE = (
    "固定窗口内全部原运行，按本次读取时状态留存；同源多次运行分别保留，"
    "跨运行已办理不重复计为本次确认。比例仅描述具名办理，不表示建议正确率、"
    "真实模型成绩或自动写入资格；不同版本与未具备试运行条件的记录未被剔除。"
)


class ObservationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime

    @model_validator(mode="after")
    def window(self) -> Self:
        if not timedelta(0) < self.window_end - self.window_start <= timedelta(days=366):
            raise ValueError("请选择不超过366天的完整观察窗口")
        return self


def _rows(
    c: Connection, table: Any, tenant: UUID, project: UUID, column: str, ids: list[Any], as_of: Any
) -> list[Any]:
    if not ids:
        return []
    return list(
        c.execute(
            select(table).where(
                table.c.tenant_id == tenant,
                table.c.project_id == project,
                table.c[column].in_(ids),
                table.c.created_at <= as_of,
            )
        ).mappings()
    )


def collect(
    c: Connection, tenant: UUID, project: UUID, body: CaptureRequest, as_of: Any
) -> list[dict[str, Any]]:
    r = tables.agent_runs
    runs = list(
        c.execute(
            select(r)
            .where(
                r.c.tenant_id == tenant,
                r.c.project_id == project,
                r.c.agent_key == "quality_intelligence",
                r.c.context_version == "event-issue-request-v1",
                r.c.created_at >= body.window_start,
                r.c.created_at < body.window_end,
            )
            .order_by(r.c.created_at, r.c.id)
            .limit(MAX_RUNS + 1)
        ).mappings()
    )
    if len(runs) > MAX_RUNS:
        raise ObservationError(
            "WINDOW_TOO_LARGE", "此窗口超过5000次原运行，请缩短窗口；本次未保存部分统计。"
        )
    ids = [r["id"] for r in runs]
    results = {
        v["run_id"]: v
        for v in _rows(c, tables.ai_issue_event_results, tenant, project, "run_id", ids, as_of)
    }
    bindings = {
        v["run_id"]: v
        for v in _rows(
            c, tables.ai_issue_generation_bindings, tenant, project, "run_id", ids, as_of
        )
    }
    reviews: dict[Any, Any] = {}
    for v in _rows(c, tables.ai_issue_proposal_reviews, tenant, project, "run_id", ids, as_of):
        if v["result_id"] not in reviews or reviews[v["result_id"]]["version"] < v["version"]:
            reviews[v["result_id"]] = v
    keys = list(
        {r["run_context"].get("issue_event_source", {}).get("source_key") for r in runs} - {None}
    )
    apps = {
        v["source_key"]: v
        for v in _rows(c, tables.ai_issue_applications, tenant, project, "source_key", keys, as_of)
    }
    issue_ids = [v["issue_id"] for v in apps.values()]
    issues = {v["id"]: v for v in _rows(c, tables.issues, tenant, project, "id", issue_ids, as_of)}
    withdrawal_ids = [v["ai_withdrawal_id"] for v in issues.values() if v["ai_withdrawal_id"]]
    withdrawals = {
        v["id"]: v
        for v in _rows(
            c, tables.ai_issue_withdrawal_receipts, tenant, project, "id", withdrawal_ids, as_of
        )
    }
    a, e = tables.audit_log, tables.events
    edits = (
        list(
            c.execute(
                select(a.c.entity_id, a.c.timestamp, a.c.id)
                .join(
                    e,
                    (e.c.tenant_id == a.c.tenant_id)
                    & (e.c.project_id == a.c.project_id)
                    & (e.c.event_id == a.c.event_id)
                    & (e.c.entity_id == a.c.entity_id)
                    & (e.c.timestamp == a.c.timestamp),
                )
                .where(
                    a.c.tenant_id == tenant,
                    a.c.project_id == project,
                    a.c.entity == "issue",
                    a.c.entity_id.in_(issue_ids),
                    a.c.actor_user_id.is_not(None),
                    a.c.timestamp <= as_of,
                    ((a.c.action == "issue.update") & (e.c.event_type == "ISSUE_UPDATED"))
                    | (
                        (a.c.action == "issue.transition")
                        & (e.c.event_type == "ISSUE_STATUS_CHANGED")
                    ),
                )
            ).mappings()
        )
        if issue_ids
        else []
    )
    edits_by_issue: dict[Any, list[Any]] = {}
    for edit in edits:
        edits_by_issue.setdefault(edit["entity_id"], []).append(edit)
    calls: dict[Any, list[Any]] = {}
    for call in _rows(c, tables.model_invocations, tenant, project, "run_id", ids, as_of):
        calls.setdefault(call["run_id"], []).append(
            {
                k: call[k]
                for k in (
                    "id",
                    "status",
                    "provider",
                    "model",
                    "model_version",
                    "usage_status",
                    "created_at",
                )
            }
        )
    items = []
    for run in runs:
        source = run["run_context"].get("issue_event_source", {})
        result, binding = results.get(run["id"]), bindings.get(run["id"])
        app = apps.get(source.get("source_key"))
        own = app is not None and app["run_id"] == run["id"]
        review = reviews.get(result["id"]) if result else None
        issue = issues.get(app["issue_id"]) if app else None
        withdrawal = withdrawals.get(issue["ai_withdrawal_id"]) if issue else None
        withdrawn = bool(
            own
            and app is not None
            and app["disposition"] == "created"
            and issue
            and issue["withdrawn_at"]
            and issue["withdrawn_at"] <= as_of
            and withdrawal
            and any(
                v.get("application_id") == str(app["id"])
                and v.get("issue_id") == str(app["issue_id"])
                and v.get("status") == "withdrawn"
                for v in withdrawal["items"]
            )
        )
        human_edits = [
            v["id"]
            for v in (edits_by_issue.get(app["issue_id"], []) if app else [])
            if own
            and app is not None
            and app["disposition"] == "created"
            and v["entity_id"] == app["issue_id"]
            and v["timestamp"] > app["created_at"]
        ]
        key = source.get("source_key", "")
        source_href = None
        if key.startswith("test_case:"):
            case_id = UUID(key.split(":", 1)[1])
            source_href = f"/projects?project={project}&tab=quality&test_case_id={case_id}"
        item = {
            "run_id": run["id"],
            "created_at": run["created_at"],
            "status": run["status"],
            "error_code": run["error_code"],
            "event_row_id": source.get("event_row_id"),
            "source_key": source.get("source_key"),
            "source_digest": source.get("source_digest"),
            "source_title": run["run_context"].get("issue_event_source_title", "原事件建议"),
            "source_href": source_href,
            "result_id": result["id"] if result else None,
            "disposition": result["proposal"]["disposition"] if result else None,
            "binding_kind": binding["capture_kind"] if binding else "not_recorded",
            "generation_binding_id": binding["id"] if binding else None,
            "generation_binding": binding["snapshot"] if binding else None,
            "review_state": "declined"
            if review and review["action"] == "decline"
            else "reopened"
            if review
            else "unreviewed",
            "review_id": review["id"] if review else None,
            "review_version": review["version"] if review else 0,
            "application_kind": app["disposition"] if own and app is not None else None,
            "application_id": app["id"] if app else None,
            "application_run_id": app["run_id"] if app else None,
            "same_source_applied": app is not None and not own,
            "issue_id": app["issue_id"] if app else None,
            "withdrawn": withdrawn,
            "withdrawal_id": withdrawal["id"] if withdrawn and withdrawal else None,
            "human_edited": bool(human_edits),
            "human_edit_audit_ids": human_edits,
            "model_calls": sorted(calls.get(run["id"], []), key=lambda v: str(v["id"])),
            "provider_verified": False,
        }
        items.append(_plain(item))
    return items


def _read(c: Connection, tenant: UUID, project: UUID, identity: UUID) -> dict[str, Any]:
    t = tables.ai_issue_observations
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("未找到此项目的观察原件")
    if digest(row["observation"]) != row["observation_digest"]:
        raise ObservationError("OBSERVATION_INVALID", "观察原件摘要不一致，请核对留存记录")
    return dict(row["observation"])


class IssueObservations:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, context, project, write=False)
            return _read(c, context.tenant.id, project, identity)

    def history(
        self, context: AuthContext, project: UUID, before_id: UUID | None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project, write=False)
            may_write = True
            try:
                authorize(c, context, project, write=True)
            except PermissionError:
                may_write = False
            t = tables.ai_issue_observations
            query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise ObservationError("CURSOR_INVALID", "请从本项目观察历史继续读取")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            return _plain(
                {
                    "items": [
                        {
                            k: r["observation"][k]
                            for k in (
                                "id",
                                "created_at",
                                "actor_name",
                                "window_start",
                                "window_end",
                                "total_runs",
                            )
                        }
                        for r in rows[:20]
                    ],
                    "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
                    "can_capture": may_write,
                }
            )

    def capture(self, context: AuthContext, project: UUID, body: CaptureRequest) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project, write=True)
            # A transaction-scoped lock serializes same-actor retries; REPEATABLE READ
            # conflicts return a retryable response rather than replacing a prior snapshot.
            c.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == context.tenant.id)
                .with_for_update()
            )
            signature = digest(
                {"project_id": str(project), **body.model_dump(mode="json", exclude={"request_id"})}
            )
            t = tables.ai_issue_observations
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ObservationError("REQUEST_ID_REUSED", "此请求已用于其他观察窗口")
                return _read(c, context.tenant.id, project, old["id"])
            as_of = c.execute(select(func.transaction_timestamp())).scalar_one()
            if body.window_end > as_of:
                raise ObservationError("WINDOW_NOT_CLOSED", "请等待所选窗口结束后再留存观察")
            items = collect(c, context.tenant.id, project, body, as_of)
            try:
                totals = aggregate(
                    [{k: item[k] for k in IssueTrialItem.model_fields} for item in items]
                )
            except ValueError as error:
                raise ObservationError(
                    "ORIGINALS_INCONSISTENT", "原运行与办理证据不一致，本次未保存部分统计"
                ) from error
            identity, now = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()
            value = _plain(
                {
                    "version": VERSION,
                    "id": identity,
                    "tenant_id": context.tenant.id,
                    "project_id": project,
                    "created_at": now,
                    "actor_name": context.user.display_name,
                    "actor_user_id": context.user.id,
                    "window_start": body.window_start,
                    "window_end": body.window_end,
                    "as_of": as_of,
                    "total_runs": len(items),
                    "items": items,
                    **totals,
                    "notice": NOTICE,
                }
            )
            signature_data = digest(value)
            event = EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"ai-issue-observation:{identity}",
                    event_type="AI_ISSUE_OBSERVATION_SAVED",
                    source="ai_issue_observation_service",
                    entity_id=identity,
                    payload={
                        "observation_id": str(identity),
                        "observation_digest": signature_data,
                        "total_runs": len(items),
                    },
                ),
                AuditDraft(
                    action="ai_issue.observation_saved",
                    after_snapshot={
                        "observation_id": str(identity),
                        "observation_digest": signature_data,
                        "total_runs": len(items),
                    },
                ),
            )
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    actor_user_id=context.user.id,
                    request_id=body.request_id,
                    request_digest=signature,
                    window_start=body.window_start,
                    window_end=body.window_end,
                    as_of=as_of,
                    created_at=now,
                    observation=value,
                    observation_digest=signature_data,
                    output_event_row_id=event.event_row_id,
                )
            )
            return value
