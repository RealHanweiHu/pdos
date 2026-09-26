"""Independent, default-off conference queue. Unknown mutations are never replayed."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import httpx2
from sqlalchemy import Engine, select, text

from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.domain.meeting_conference_requests import (
    Draft,
    T,
    apply_booking,
    emit,
    enabled,
    lock_key,
    meeting_snapshot,
    remote_key,
    request_snapshot,
)
from app.domain.meeting_rescheduling import external_signature
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import digest
from app.domain.project_write_lock import lock_project_write_scope
from app.integrations.dingtalk_conference import DingTalkConferenceClient
from app.integrations.dingtalk_delivery import DingTalkDeliveryClient, DingTalkDeliveryError
from app.integrations.tencent_conference import TencentConferenceClient
from app.settings import Settings


class ConferenceWorker:
    def __init__(self, engine: Engine, client: httpx2.Client, settings: Settings) -> None:
        self.engine, self.settings = engine, settings
        self.tencent = TencentConferenceClient(client, settings)
        self.tokens, self.conferences = (
            DingTalkDeliveryClient(client),
            DingTalkConferenceClient(client),
        )

    def run_next(self) -> bool:
        providers = [p for p in ("dingtalk", "tencent_meeting") if enabled(self.settings, p)]
        if not providers:
            return False
        now = datetime.now(UTC)
        with self.engine.connect() as c:
            candidates = list(
                c.execute(
                    select(T.c.id)
                    .where(
                        (T.c.status == "pending")
                        | (
                            (T.c.status == "sending")
                            & (T.c.dispatched_at < now - timedelta(minutes=2))
                        )
                    )
                    .where(T.c.provider.in_(providers))
                    .order_by(T.c.sequence)
                    .limit(20)
                ).scalars()
            )
        for id in candidates:
            # A session lock survives the dispatch transaction and protects manual reconciliation.
            # One physical connection is held until the receipt has committed.
            with self.engine.connect() as guard:
                acquired = guard.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key(id)}
                ).scalar_one()
                guard.commit()
                if not acquired:
                    continue
                try:
                    with self.engine.connect() as c:
                        row = c.execute(select(T).where(T.c.id == id)).mappings().one()
                    if row["status"] == "sending":
                        self.finish(row, "uncertain", None, "CONFERENCE_WORKER_INTERRUPTED")
                        return True
                    if row["status"] != "pending":
                        continue
                    self.dispatch(row)
                    return True
                finally:
                    guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key(id)})
                    guard.commit()
        return False

    def dispatch(self, row: Any) -> None:
        token = ""
        if row["provider"] == "dingtalk":
            client_id, secret = (
                self.settings.dingtalk_client_id,
                self.settings.dingtalk_client_secret,
            )
            if not client_id or secret is None:
                self.finish(row, "failed", None, "CONFERENCE_CONFIGURATION_MISSING")
                return
            try:
                token = self.tokens.app_token(
                    client_id=client_id, client_secret=secret.get_secret_value()
                )
            except DingTalkDeliveryError:
                self.finish(row, "failed", None, "CONFERENCE_TOKEN_UNAVAILABLE")
                return
        ctx = AuthRepository(self.engine).find_user_context(row["actor_user_id"])
        try:
            if (
                ctx is None
                or ctx.tenant.id != row["tenant_id"]
                or ctx.user.auth_version != row["actor_auth_version"]
            ):
                raise MeetingStateError("authorization changed")
            with self.engine.begin() as c:
                if not lock_project_write_scope(
                    c, tenant_id=row["tenant_id"], project_id=row["project_id"]
                ):
                    raise MeetingStateError("project unavailable")
                snap = row["snapshot"]
                current = request_snapshot(
                    c,
                    ctx,
                    row["project_id"],
                    row["meeting_id"],
                    Draft(
                        request_id=row["id"],
                        provider=row["provider"],
                        operation=row["operation"],
                        expected_digest=digest(snap["meeting"]),
                        reason=snap["reason"],
                    ),
                    self.settings,
                )
                if "standing_authority" in snap:
                    from app.domain.meeting_recurring_conferences import validate_dispatch

                    current["standing_authority"] = validate_dispatch(c, row, datetime.now(UTC))
                if current != snap:
                    raise MeetingStateError("conference request changed")
                c.execute(
                    T.update()
                    .where(T.c.id == row["id"], T.c.status == "pending")
                    .values(status="sending", dispatched_at=datetime.now(UTC))
                )
                emit(c, row, "dispatched", {"status": "sending"}, None)
        except Exception:
            self.finish(row, "failed", None, "CONFERENCE_REVIEW_REQUIRED")
            return
        operation = cast(Literal["create", "update", "cancel", "query"], row["operation"])
        try:
            result = (
                self.tencent.perform(operation, row["snapshot"]["payload"])
                if row["provider"] == "tencent_meeting"
                else self.conferences.perform(token, operation, row["snapshot"]["payload"])
            )
        except DingTalkDeliveryError as error:
            self.finish(row, "uncertain" if error.uncertain else "failed", None, error.code)
            return
        # Database errors here leave 'sending'; recovery quarantines without another external call.
        self.finish(row, "succeeded", result, None)

    def finish(
        self, row: Any, status: str, result: dict[str, Any] | None, code: str | None
    ) -> None:
        now = datetime.now(UTC)
        ctx = AuthRepository(self.engine).find_user_context(row["actor_user_id"])
        with self.engine.begin() as c:
            lock_project_write_scope(c, tenant_id=row["tenant_id"], project_id=row["project_id"])
            if result is not None:
                result = {**result, "method": "provider_response"}
                if row["operation"] != "query":
                    try:
                        with c.begin_nested():
                            result["matches_current_meeting"] = apply_booking(c, row, result, now)
                    except Exception:
                        # Preserve the real booking even if the local binding cannot be applied.
                        result["matches_current_meeting"] = False
                        result["local_binding_error"] = "CONFERENCE_LOCAL_BINDING_REQUIRES_REVIEW"
                    current = (
                        c.execute(
                            select(tables.meetings).where(
                                tables.meetings.c.id == row["meeting_id"],
                                tables.meetings.c.tenant_id == row["tenant_id"],
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if result["matches_current_meeting"]:
                        result["current_signature"] = external_signature(current)
                        result["current_meeting_digest"] = digest(meeting_snapshot(current))
                else:
                    meeting = row["snapshot"]["meeting"]
                    result["observed_matches_requested_schedule"] = (
                        (
                            row["provider"] != "tencent_meeting"
                            or (
                                result.get("provider_state") == "MEETING_STATE_CANCELLED"
                                if meeting["status"] == "cancelled"
                                else result.get("provider_state")
                                in (
                                    "MEETING_STATE_INIT",
                                    "MEETING_STATE_STARTED",
                                    "MEETING_STATE_NULL",
                                )
                            )
                        )
                        and result["external_meeting_id"]
                        == row["snapshot"]["payload"][remote_key(row["provider"])]
                        and result.get("title") == meeting["title"]
                        and result.get("startTime")
                        == int(
                            datetime.fromisoformat(meeting["scheduled_start_at"]).timestamp() * 1000
                        )
                        and result.get("endTime")
                        == int(
                            datetime.fromisoformat(meeting["scheduled_end_at"]).timestamp() * 1000
                        )
                    )
            if status == "succeeded" and result is not None:
                from app.domain.meeting_recurring_notifications import after_booking

                after_booking(c, ctx, row, result, self.settings, now)
            c.execute(
                T.update()
                .where(T.c.id == row["id"])
                .values(
                    status=status,
                    result=result,
                    error_code=code,
                    completed_at=now if status in ("succeeded", "failed") else None,
                )
            )
            emit(c, row, "finished", {"status": status, "result": result, "error_code": code}, None)
