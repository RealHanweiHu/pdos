"""Database-only Issue event dispatch with immutable per-event completion receipts.

A receipt, never a cursor high-water mark, proves that an event was handled. Each
attempt owns a top-level transaction because application budget freezing binds
that transaction's xmin. Model execution belongs to execute_queued, not dispatch.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, Select, and_, func, or_, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.issue_event_proposal import KEY, OPERATION, IssueEventProposalError, source_snapshot
from app.ai.issue_event_runs import RUN_VERSION, IssueEventRuns, _access
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.write_policy import POLICY_VERSION
from app.db.schema import tables
from app.domain.ai_issue_event_sources import read_event_source
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.ai_write_policy import WritePolicyError
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope

CONSUMER_KEY = "issue_creation_events_v1"
REASONS = {
    "queued": "已按原事件、当前资料和授权排队。",
    "reused": "相同原资料和授权已有运行，已保留原运行引用。",
    "event_source_invalid": "原事件或具名办理依据不能完整核对。",
    "source_unavailable": "原资料不可用或已有变化，不替换成当前版本。",
    "actor_unauthorized": "原事件办理人当前没有读取或办理该资料的权限。",
    "project_unavailable": "当前租户或项目已不可办理。",
    "automatic_not_enabled": "当前政策未开放事件问题的自动处理。",
    "scope_not_enabled": "当前项目没有匹配的独立 AI 范围授权。",
    "event_before_authorization": "事件早于当前政策或授权，不补触发历史事件。",
    "capability_unavailable": "当前能力尚未开放实际运行。",
    "budget_unavailable": "当前预算或运行授权不足，未排入模型调用。",
}


class IssueDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanned_event_count: int = 0
    queued_count: int = 0
    reused_count: int = 0
    skipped_count: int = 0


class SkipIssueEvent(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def pending_events_query() -> Select[Any]:
    e, r = tables.events, tables.ai_issue_event_receipts
    completed = (
        select(r.c.id)
        .where(
            r.c.tenant_id == e.c.tenant_id,
            r.c.event_row_id == e.c.id,
            r.c.operation_key == OPERATION,
        )
        .correlate(e)
        .exists()
    )
    return select(e).where(
        e.c.project_id.is_not(None),
        or_(
            e.c.event_type == "TEST_FAILED",
            and_(
                e.c.event_type == "NPI_RECORD_CHANGED",
                e.c.payload["record_type"].as_string() == "material_exception",
                e.c.payload["action"].as_string().in_(("confirmed", "reviewed")),
            ),
        ),
        ~completed,
    )


def original_actor(event: Mapping[str, Any], source: dict[str, Any]) -> UUID:
    """The reader already binds actual test/review originals; require its exact event."""
    raw = source.get("source") or {}
    audit = raw.get("audit") or {}
    test = event["event_type"] == "TEST_FAILED"
    payload = event["payload"]
    original_event = _plain(dict(event))
    expected_action = (
        "npi.test_case.failed" if test else f"npi.material_exception.{payload.get('action')}"
    )
    if (
        raw.get("event") != original_event
        or source.get("event_row_id") != event["id"]
        or source.get("event_id") != event["event_id"]
        or source.get("event_type") != event["event_type"]
        or audit.get("action") != expected_action
        or any(
            audit.get(key) != original_event[key]
            for key in ("tenant_id", "project_id", "event_id", "entity", "entity_id", "timestamp")
        )
        or event["source"] != ("quality_service" if test else "npi_service")
        or event["entity"] != ("test" if test else "npi_record")
        or (
            not test
            and not (
                event["event_type"] == "NPI_RECORD_CHANGED"
                and payload.get("record_type") == "material_exception"
                and payload.get("action") in {"confirmed", "reviewed"}
            )
        )
    ):
        raise SkipIssueEvent("event_source_invalid")
    try:
        return UUID(audit["actor_user_id"])
    except (ValueError, TypeError, KeyError) as error:
        raise SkipIssueEvent("event_source_invalid") from error


class IssueEventQueue:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @staticmethod
    def _lock(c: Connection, event: Mapping[str, Any]) -> bool:
        status = c.execute(
            select(tables.tenants.c.status)
            .where(tables.tenants.c.id == event["tenant_id"])
            .with_for_update()
        ).scalar_one_or_none()
        available = lock_project_write_scope(
            c, tenant_id=event["tenant_id"], project_id=event["project_id"]
        )
        return status == "active" and available

    @staticmethod
    def _receipt_exists(c: Connection, event: Mapping[str, Any]) -> bool:
        r = tables.ai_issue_event_receipts
        return (
            c.execute(
                select(r.c.id).where(
                    r.c.tenant_id == event["tenant_id"],
                    r.c.event_row_id == event["id"],
                    r.c.operation_key == OPERATION,
                )
            ).scalar_one_or_none()
            is not None
        )

    def _enqueue(
        self, c: Connection, event: Mapping[str, Any], evidence: dict[str, Any]
    ) -> dict[str, Any]:
        tenant, project = event["tenant_id"], event["project_id"]
        settings = policy(c, tenant)
        if (
            settings is None
            or settings["contract_version"] != POLICY_VERSION
            or settings["mode"] != "tiered"
            or settings["operation_settings"].get(OPERATION, {}).get("mode") != "automatic"
        ):
            raise SkipIssueEvent("automatic_not_enabled")
        evidence["policy_id"] = settings["id"]
        grant = latest_scope(c, tenant, project, OPERATION)
        if not grant or not grant["enabled"] or grant["principal_id"] != settings["principal_id"]:
            raise SkipIssueEvent("scope_not_enabled")
        evidence.update(scope_revision_id=grant["id"], principal_id=grant["principal_id"])
        if event["timestamp"] < max(settings["created_at"], grant["created_at"]):
            raise SkipIssueEvent("event_before_authorization")
        p = tables.ai_principals
        if (
            c.execute(
                select(p.c.id).where(
                    p.c.tenant_id == tenant,
                    p.c.id == grant["principal_id"],
                    p.c.principal_kind == "ai",
                    p.c.principal_key == "pdos-agent",
                )
            ).scalar_one_or_none()
            is None
        ):
            raise SkipIssueEvent("scope_not_enabled")
        require_live_key(KEY)
        source = read_event_source(c, tenant, project, event["id"])
        evidence["source_reason"] = source.get("reason_code")
        if source.get("source_status") != "current":
            raise SkipIssueEvent("source_unavailable")
        actor = original_actor(event, source)
        evidence.update(actor_user_id=actor, audit_row_id=source["source"]["audit"]["id"])
        _access(c, tenant, actor, project, write=True)
        original = source_snapshot(source)
        evidence["source_digest"] = original["source_digest"]
        return dict(
            IssueEventRuns(self.engine, gateway=self.gateway).enqueue_event(
                c,
                event={**dict(event), "actor_user_id": actor},
                source=source,
                policy_id=settings["id"],
                scope_revision_id=grant["id"],
                principal_id=grant["principal_id"],
            )
        )

    @staticmethod
    def _record(
        c: Connection,
        event: Mapping[str, Any],
        status: str,
        reason: str,
        evidence: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        c.execute(
            tables.ai_issue_event_receipts.insert().values(
                id=uuid4(),
                tenant_id=event["tenant_id"],
                project_id=event["project_id"],
                event_row_id=event["id"],
                operation_key=OPERATION,
                source_digest=result.get("source_digest", evidence.get("source_digest")),
                run_id=UUID(str(result["run_id"])) if result else None,
                principal_id=evidence.get("principal_id"),
                status=status,
                reason=reason,
                receipt=_plain(
                    {
                        "version": "issue-event-receipt.v1",
                        "consumer_key": CONSUMER_KEY,
                        "event_row_id": event["id"],
                        "event_id": event["event_id"],
                        "operation_key": OPERATION,
                        "status": status,
                        "reason": reason,
                        "message": REASONS[reason],
                        "source": evidence,
                        "run": result,
                        "created_at": now,
                    }
                ),
                created_at=now,
            )
        )

    def _project_event(self, event: Mapping[str, Any]) -> str | None:
        evidence: dict[str, Any] = {}
        try:
            with self.engine.begin() as c:
                available = self._lock(c, event)
                if self._receipt_exists(c, event):
                    return None
                if not available:
                    raise SkipIssueEvent("project_unavailable")
                result = self._enqueue(c, event, evidence)
                status = "reused" if result["reused"] else "queued"
                self._record(c, event, status, status, evidence, result)
                return status
        except SkipIssueEvent as error:
            reason = error.reason
        except CapabilityUnavailableError as error:
            reason = "capability_unavailable"
            evidence["error_code"] = error.code
        except BudgetLedgerError as error:
            reason = "budget_unavailable"
            evidence["error_code"] = error.code
        except WritePolicyError as error:
            reason = "scope_not_enabled"
            evidence["error_code"] = error.code
        except PermissionError:
            reason = "actor_unauthorized"
        except (LookupError, IssueEventProposalError):
            reason = "source_unavailable"
        # Failed creation/freezing rolls back before a separate immutable skip.
        # Unknown errors propagate; they must not hide behind a completed receipt.
        with self.engine.begin() as c:
            self._lock(c, event)
            if self._receipt_exists(c, event):
                return None
            self._record(c, event, "skipped", reason, evidence, {})
        return "skipped"

    def dispatch_once(self, batch_size: int = 100) -> IssueDispatchResult:
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("issue event batch size must be between 1 and 1000")
        with self.engine.connect() as c:
            events = (
                c.execute(pending_events_query().order_by(tables.events.c.id).limit(batch_size))
                .mappings()
                .all()
            )
        counts = {"queued": 0, "reused": 0, "skipped": 0}
        for event in events:
            status = self._project_event(dict(event))
            if status is not None:
                counts[status] += 1
        return IssueDispatchResult(
            scanned_event_count=len(events),
            queued_count=counts["queued"],
            reused_count=counts["reused"],
            skipped_count=counts["skipped"],
        )

    def execute_next(self) -> bool:
        run, receipt = tables.agent_runs, tables.ai_issue_event_receipts
        with self.engine.connect() as c:
            identity = c.execute(
                select(run.c.id)
                .where(
                    run.c.status == "queued",
                    run.c.context_version == RUN_VERSION,
                    select(receipt.c.id)
                    .where(
                        receipt.c.tenant_id == run.c.tenant_id,
                        receipt.c.project_id == run.c.project_id,
                        receipt.c.run_id == run.c.id,
                        receipt.c.operation_key == OPERATION,
                        receipt.c.status.in_(("queued", "reused")),
                    )
                    .correlate(run)
                    .exists(),
                )
                .order_by(run.c.created_at, run.c.id)
                .limit(1)
            ).scalar_one_or_none()
        if identity is None:
            return False
        IssueEventRuns(self.engine, gateway=self.gateway).execute_queued(identity)
        return True
