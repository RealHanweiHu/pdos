"""Durable private summary delivery, derived only from the original admitted Run."""

from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.policy import egress
from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.domain.automations.service_models import AutomationServiceAttempt as Attempt
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.personal_summary_runtime import _bound, _check_sources
from pdos_next.personal_summary_schemas import Summary
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context, digest, require_access

from .accounts import credential
from .models import Application
from .projection import run_link
from .runtime import ChannelService, configured
from .summary_models import SummaryDelivery


class SummaryReference(StrictModel):
    tenant_id: UUID
    run_id: UUID


class ReceiptPage(StrictModel):
    page_size: int = Field(default=25, ge=1, le=100)


def source_ids(summary):
    """Actual fixed ObjectRefs from the server summary, never arbitrary payload UUIDs."""
    return sorted(
        {
            identity
            for group in summary.groups
            for item in (*group.items, *group.unchanged_items)
            for identity in (item.object.id, item.object.version_id)
            if identity is not None
        },
        key=str,
    )


def compose(summary, *, binding, public_base_url, run_id, category_id):
    if summary.principal_id != binding.owner_id:
        raise DomainError("FORBIDDEN_SCOPE", "摘要与本人绑定不一致。", 403)
    # The existing authenticated Run page rereads this original category-bound Run.
    link = run_link(public_base_url, run_id) + "?category=" + str(category_id)
    lines = ["本人的工作摘要", "读取时点：" + summary.as_of.isoformat()]
    total = sum(len(group.items) for group in summary.groups)
    shown, unchanged = 0, sum(len(group.unchanged_items) for group in summary.groups)
    for group in summary.groups:
        for item in group.items:
            entry = (
                f"\n{group.title} · {item.title}\n"
                f"变化：{item.change.text}\n与我有关：{item.relationship.text}\n"
                f"下一步：{item.next_step.text}\n"
                f"责任人：{item.next_step.responsible.name or item.next_step.responsible.id}"
                if item.next_step.responsible
                else f"\n{group.title} · {item.title}\n变化：{item.change.text}\n"
                f"与我有关：{item.relationship.text}\n下一步：{item.next_step.text}\n"
                "责任人：未单独登记"
            )
            entry += "\n继续：" + public_base_url.rstrip("/") + item.continue_url
            if sum(map(len, lines)) + len(entry) > 17500:
                break
            lines.append(entry)
            shown += 1
    if total == 0:
        lines.append("本次已读取范围没有新的变化条目。")
    if shown < total:
        lines.append(f"另有 {total - shown} 条变化，请在 PDOS 查看完整摘要。")
    if unchanged:
        lines.append(f"{unchanged} 条未变化事项已折叠，原记录保留在 PDOS。")
    if not summary.complete:
        lines.append("部分来源仍待核对，详见 PDOS 覆盖说明。")
    return {
        "target_kind": "direct",
        "target_id": binding.external_user_id,
        "text": "\n".join(lines),
        "url": link,
    }


class SummaryDeliveryService:
    def __init__(self, engine, metadata_engine, *, runtime=None):
        self.engine, self.metadata_engine = engine, metadata_engine
        self.runtime = runtime if runtime is not None else configured(engine)

    def reference(self, ref, *, owner=None):
        ref = SummaryReference.model_validate(ref)
        with tenant_session(
            self.metadata_engine, ref.tenant_id, actor_id=owner, requester_id=owner
        ) as session:
            row = (
                session.execute(
                    text("SELECT * FROM dingtalk_summary_reference(:tenant,:run)"),
                    {"tenant": ref.tenant_id, "run": ref.run_id},
                )
                .mappings()
                .first()
            )
        if not row:
            raise DomainError("FORBIDDEN_SCOPE", "摘要没有实际本人激活及入站独立的投递选择。", 403)
        return dict(row)

    @contextmanager
    def transaction(self, meta):
        with tenant_session(
            self.engine,
            meta["tenant_id"],
            actor_id=meta["service_id"],
            requester_id=meta["service_id"],
        ) as session:
            yield session

    def snapshot(self, meta, row=None):
        owner = meta["owner_id"]
        with tenant_session(
            self.engine,
            meta["tenant_id"],
            actor_id=owner,
            requester_id=owner,
            category_id=meta["category_id"],
            # Current unique-writer validation uses FOR SHARE; keep RR with row locks.
            repeatable_read=True,
        ) as session:
            run = session.get(AgentRun, meta["run_id"])
            if (
                not run
                or run.requester_id != owner
                or run.category_id != meta["category_id"]
                or run.state not in {"completed", "partial"}
                or run.reverted_at
                or row is not None
                and run.cancel_epoch != row.cancel_epoch
            ):
                raise DomainError("CANCELLED_RUN", "原摘要已取消或不可读取。")
            spec, choice = _bound(session, run)
            ctx = Context(run.tenant_id, owner, owner, category_id=run.category_id)
            require_access(session, ctx, spec.product_id)
            writer = session.get(Principal, run.writer_id)
            if (
                not writer
                or not writer.active
                or writer.kind != "agent"
                or Bootstrap.writer_for(session, ctx) != run.writer_id
                or choice.dingtalk_binding_id != meta["binding_id"]
            ):
                raise DomainError("CANCELLED_RUN", "摘要服务授权或本人投递选择已失效。")
            from pdos_next.personal_summary_channels import selected

            app, binding = selected(session, ctx, choice.dingtalk_binding_id)
            if row is not None and (
                binding.id != row.binding_id
                or binding.epoch != row.binding_epoch
                or app.id != row.application_id
                or app.revision != row.application_revision
            ):
                raise DomainError("CANCELLED_RUN", "原绑定或应用配置已变化。")
            summary = Summary.model_validate(run.result["result"]["personal_summary"])
            _check_sources(session, run, summary)
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run.id))
            if not attempt or (
                attempt.id,
                attempt.published_version_id,
                attempt.service_grant_id,
            ) != (
                meta["attempt_id"],
                meta["published_version_id"],
                meta["service_grant_id"],
            ):
                raise DomainError("FORBIDDEN_SCOPE", "摘要投递须使用原实际服务受理。", 403)
            value = summary.model_dump(mode="json")
            payload = compose(
                summary,
                binding=binding,
                public_base_url=self.runtime.public_base_url,
                run_id=run.id,
                category_id=run.category_id,
            )
            fixed = dict(
                tenant_id=run.tenant_id,
                category_id=run.category_id,
                owner_id=owner,
                run_id=run.id,
                attempt_id=attempt.id,
                service_grant_id=attempt.service_grant_id,
                published_version_id=attempt.published_version_id,
                application_id=app.id,
                application_revision=app.revision,
                binding_id=binding.id,
                binding_epoch=binding.epoch,
                cancel_epoch=run.cancel_epoch,
                summary_sha256=digest(value),
                source_ids=source_ids(summary),
                payload=payload,
                payload_sha256=digest(payload),
            )
            if row is not None and any(getattr(row, key) != value for key, value in fixed.items()):
                raise DomainError("SOURCE_STALE", "原固定摘要或来源依据已变化。")
            return fixed

    def plan(self, meta):
        with self.transaction(meta) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "summary-delivery:" + str(meta["run_id"])},
            )
            old = session.scalar(
                select(SummaryDelivery).where(SummaryDelivery.run_id == meta["run_id"])
            )
            if old:
                return old.id
            try:
                fixed = self.snapshot(meta)
                state, error_code = "planned", None
            except DomainError as error:
                # Retain a bounded failed delivery fact, without copying inaccessible facts.
                fixed = {
                    key: meta[key]
                    for key in (
                        "tenant_id",
                        "category_id",
                        "owner_id",
                        "run_id",
                        "attempt_id",
                        "service_grant_id",
                        "published_version_id",
                        "application_id",
                        "application_revision",
                        "binding_id",
                        "binding_epoch",
                        "cancel_epoch",
                    )
                }
                payload = {
                    "target_kind": "direct",
                    "target_id": "withheld",
                    "text": "摘要当前不可投递，请在 PDOS 重新核对。",
                    "url": run_link(self.runtime.public_base_url, meta["run_id"]),
                }
                fixed.update(
                    summary_sha256=digest(None),
                    source_ids=[],
                    payload=payload,
                    payload_sha256=digest(payload),
                )
                state = "cancelled" if error.reason == "CANCELLED_RUN" else "blocked"
                error_code = error.reason
            row = SummaryDelivery(
                id=uuid4(),
                **fixed,
                state=state,
                error_code=error_code,
                attempts=0,
                request_key=uuid5(NAMESPACE_URL, "pdos:summary-dingtalk:" + str(meta["run_id"])),
            )
            session.add(row)
            session.flush()
            return row.id

    def lock(self, session, meta, identity):
        # Same app→binding order as the existing channel revoke/configuration fence.
        session.execute(
            text("SELECT dingtalk_lock_summary_binding(:tenant,:delivery)"),
            {"tenant": meta["tenant_id"], "delivery": identity},
        )
        row = session.scalar(
            select(SummaryDelivery)
            .where(SummaryDelivery.id == identity)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row or row.run_id != meta["run_id"]:
            raise DomainError("FORBIDDEN_SCOPE", "投递不属于原摘要。", 403)
        app = session.get(Application, row.application_id, populate_existing=True)
        return row, app

    def reserve(self, meta, identity):
        with self.transaction(meta) as session:
            row, _app = self.lock(session, meta, identity)
            if row.state != "planned":
                return None
            try:
                self.snapshot(meta, row)
                decision = egress(
                    session,
                    SimpleNamespace(tenant_id=row.tenant_id, data_categories=("internal",)),
                    "dingtalk",
                    data_categories=("internal",),
                )
                row.p26 = {**asdict(decision), "checked_at": decision.checked_at.isoformat()}
                row.state, row.send_attempt_id, row.send_started_at = "sending", uuid4(), now()
                row.attempts += 1
                return row.send_attempt_id
            except DomainError as error:
                row.state = "cancelled" if error.reason == "CANCELLED_RUN" else "blocked"
                row.error_code = error.reason
                return None

    def send_reserved(self, meta, identity, send_attempt_id):
        with self.transaction(meta) as session:
            row, app = self.lock(session, meta, identity)
            if row.state != "sending" or row.send_attempt_id != send_attempt_id:
                return self.status(row)
            try:
                self.snapshot(meta, row)
                decision = egress(
                    session,
                    SimpleNamespace(tenant_id=row.tenant_id, data_categories=("internal",)),
                    "dingtalk",
                    data_categories=("internal",),
                )
                row.p26 = {**asdict(decision), "checked_at": decision.checked_at.isoformat()}
                key = credential(self.runtime, app)
            except DomainError as error:
                row.state = "cancelled" if error.reason == "CANCELLED_RUN" else "blocked"
                row.error_code = error.reason
                return self.status(row)
            try:
                receipt = self.runtime.adapter.send(app, key, row.request_key, row.payload)
            except Exception:
                row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            else:
                ChannelService.accept_receipt(row, receipt)
            return self.status(row)

    @staticmethod
    def status(row):
        return {
            "delivery_id": str(row.id),
            "run_id": str(row.run_id),
            "state": row.state,
            "attempts": row.attempts,
            "error_code": row.error_code,
        }

    def reconcile(self, meta, identity):
        # No source body or send: retained metadata lookup remains possible after revoke.
        with self.transaction(meta) as session:
            row = session.scalar(
                select(SummaryDelivery).where(SummaryDelivery.id == identity).with_for_update()
            )
            if not row or row.run_id != meta["run_id"]:
                raise DomainError("FORBIDDEN_SCOPE", "原摘要投递不可读取。", 403)
            if row.state not in {"sending", "unknown"}:
                return self.status(row)
            app = session.get(Application, row.application_id)
            try:
                key = credential(self.runtime, app)
                lookup = getattr(self.runtime.adapter, "lookup_receipt", None)
                receipt = (
                    lookup(app, key, row.request_key, row.provider_receipt)
                    if lookup
                    else self.runtime.adapter.lookup(app, key, row.request_key)
                )
            except Exception:
                receipt = None
            if receipt is not None:
                ChannelService.accept_receipt(row, receipt)
            else:
                row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            return self.status(row)

    def deliver(self, reference):
        ref = SummaryReference.model_validate(reference)
        with tenant_session(self.metadata_engine, ref.tenant_id) as session:
            lost = session.scalar(
                text("SELECT dingtalk_summary_cancel_lost(:tenant,:run)"),
                {"tenant": ref.tenant_id, "run": ref.run_id},
            )
        if lost:
            return {"state": "cancelled", "error_code": "CANCELLED_RUN"}
        meta = self.reference(reference)
        identity = self.plan(meta)
        attempt = self.reserve(meta, identity)
        return (
            self.send_reserved(meta, identity, attempt)
            if attempt is not None
            else self.reconcile(meta, identity)
        )
