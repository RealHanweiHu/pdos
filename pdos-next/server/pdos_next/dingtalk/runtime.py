"""Durable synthetic-capable channel service; no live transport or credentials fallback."""

from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select, text

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.policy import egress
from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest

from .accounts import credential, human
from .admission import native_reference
from .guards import message_binding
from .models import Application, Binding, Delivery, Message, ShareConsent
from .projection import Answer, group_citations, owner_answer, payload, run_link


def configure(engine, runtime):
    engine._pdos_dingtalk = runtime


def configured(engine):
    value = getattr(engine, "_pdos_dingtalk", None)
    if value is None:
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉适配器尚未配置；未发生外发。")
    return value


def delivery_key(message_id, phase, consent_id=None):
    return uuid5(NAMESPACE_URL, f"pdos:dingtalk:{message_id}:{phase}:{consent_id or ''}")


class ChannelService:
    def __init__(self, engine, metadata_engine, *, runtime=None):
        self.engine, self.metadata_engine = engine, metadata_engine
        self.runtime = runtime if runtime is not None else configured(engine)

    @contextmanager
    def metadata(self, ref):
        # Dispatcher receives only this exact channel message's service identity.
        # The function checks bound tenant and returns no goal, sources or output.
        with tenant_session(self.metadata_engine, ref.tenant_id) as session:
            service_id = session.scalar(
                text("SELECT dingtalk_message_service(:tenant,:message)"),
                {"tenant": ref.tenant_id, "message": ref.message_id},
            )
        if service_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "入站记录不在当前调度范围。", 403)
        with tenant_session(
            self.engine, ref.tenant_id, actor_id=service_id, requester_id=service_id
        ) as session:
            message = session.get(Message, ref.message_id)
            app = session.get(Application, message.application_id) if message else None
            if not message or not app or app.service_principal_id != service_id:
                raise DomainError("FORBIDDEN_SCOPE", "通道元数据与实际应用不一致。", 403)
            yield session, message, app

    def owner_snapshot(self, message, *, include_citations=False):
        # No arbitrary owner API: owner comes ONLY from this persisted inbound mapping.
        # Native result/source reads remain actual Human ordinary RLS, read-only RR.
        with tenant_session(
            self.engine,
            message.tenant_id,
            actor_id=message.owner_id,
            requester_id=message.owner_id,
            read_snapshot=True,
        ) as session:
            actual_message = session.get(Message, message.id)
            run = session.get(AgentRun, message.run_id)
            if not actual_message or not run or run.requester_id != actual_message.owner_id:
                raise DomainError("FORBIDDEN_SCOPE", "原运行当前已不可读。", 403)
            app, binding = message_binding(session, actual_message, run)
            if run.state not in {"completed", "partial", "failed", "cancelled"}:
                return {"status": run.state, "reference": native_reference(run)}
            answer = owner_answer(session, run)
            members, allowed = None, False
            if include_citations and message.conversation_kind == "group":
                members = self.runtime.adapter.members(
                    app,
                    credential(self.runtime, app),
                    message.conversation_id,
                )
                allowed = group_citations(
                    self.engine,
                    Context(message.tenant_id, message.owner_id, message.owner_id),
                    app,
                    members,
                    answer,
                )
            return {
                "status": run.state,
                "scope": scope_for_run(run),
                "answer": answer,
                "members": members,
                "citations_allowed": allowed,
                "reference": native_reference(run),
            }

    def compose(self, message, binding, phase, *, include_citations=False):
        link = run_link(self.runtime.public_base_url, message.run_id)
        if phase in {"received", "group_notice"}:
            answer, members, allowed = Answer("", (), {}, ("internal",)), None, False
        else:
            view = self.owner_snapshot(message, include_citations=include_citations)
            if "answer" not in view:
                raise DomainError("VERSION_CONFLICT", "原工作尚未完成。")
            answer, members, allowed = view["answer"], view["members"], view["citations_allowed"]
        return payload(
            phase=phase,
            message=message,
            binding=binding,
            answer=answer,
            link=link,
            include_citations=include_citations,
            members=members,
            citations_allowed=allowed,
        ), answer

    def plan(self, ref):
        with self.metadata(ref) as (session, message, _app):
            key = delivery_key(message.id, ref.phase, ref.consent_id)
            old = session.scalar(select(Delivery).where(Delivery.request_key == key))
            if old:
                return old.id
            _app, binding = message_binding(session, message)
            consent = session.get(ShareConsent, ref.consent_id) if ref.consent_id else None
            if ref.phase == "share" and (
                not consent
                or consent.message_id != message.id
                or consent.owner_id != message.owner_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "群分享缺少实际本人确认。", 403)
            if ref.phase != "share" and ref.consent_id is not None:
                raise DomainError("FORBIDDEN_SCOPE", "投递类型与本人确认不一致。", 403)
            if ref.phase in {"share", "group_notice"} and message.conversation_kind != "group":
                raise DomainError("FORBIDDEN_SCOPE", "原消息不是群内提问。", 403)
            if ref.phase == "group_notice":
                sent = session.scalar(
                    select(Delivery).where(
                        Delivery.message_id == message.id,
                        Delivery.phase == "answer",
                        Delivery.state == "delivered",
                    )
                )
                if not sent:
                    raise DomainError("VERSION_CONFLICT", "尚无答案已私发的真实投递回执。")
            key = delivery_key(message.id, ref.phase, ref.consent_id)
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "dingtalk-delivery:" + str(key)},
            )
            old = session.scalar(select(Delivery).where(Delivery.request_key == key))
            if old:
                return old.id
            body, answer = self.compose(
                message,
                binding,
                ref.phase,
                include_citations=bool(consent and consent.include_citations),
            )
            if consent and consent.payload_sha256 != digest(body):
                raise DomainError("VERSION_CONFLICT", "分享正文或依据已变化，请重新预览确认。")
            from .lifecycle import capture

            content_kind = (
                "control"
                if ref.phase in {"received", "group_notice"}
                else "local_link"
                if answer.withheld_reason
                else "answer"
            )
            dependencies = capture(answer) if content_kind == "answer" else []
            row = Delivery(
                id=uuid4(),
                tenant_id=message.tenant_id,
                message_id=message.id,
                owner_id=message.owner_id,
                consent_id=ref.consent_id,
                request_key=key,
                phase=ref.phase,
                payload=body,
                payload_sha256=digest(body),
                content_kind=content_kind,
                source_dependencies=dependencies,
                state="planned",
            )
            session.add(row)
            session.flush()
            return row.id

    def reserve(self, ref, delivery_id):
        """P26 + sending journal COMMIT before any external side effect."""
        with self.metadata(ref) as (session, message, app):
            row = session.scalar(
                select(Delivery).where(Delivery.id == delivery_id).with_for_update()
            )
            if not row or row.message_id != message.id:
                raise DomainError("FORBIDDEN_SCOPE", "投递不属于当前入站记录。", 403)
            if row.state != "planned":
                return None
            try:
                message_binding(session, message, lock=True)
                consent = session.get(ShareConsent, row.consent_id) if row.consent_id else None
                body, answer = self.compose(
                    message,
                    session.get(Binding, message.binding_id),
                    row.phase,
                    include_citations=bool(consent and consent.include_citations),
                )
                if digest(body) != row.payload_sha256:
                    raise DomainError("SOURCE_STALE", "投递正文、依据或群受众已变化。")
                # Host supplies actual projected categories; models cannot name these.
                decision = egress(
                    session,
                    SimpleNamespace(
                        tenant_id=message.tenant_id, data_categories=answer.data_categories
                    ),
                    "dingtalk",
                    data_categories=answer.data_categories,
                )
                row.p26 = {**asdict(decision), "checked_at": decision.checked_at.isoformat()}
                row.attempt_id, row.send_started_at = uuid4(), now()
                row.attempts, row.state = row.attempts + 1, "sending"
                return row.attempt_id
            except DomainError as error:
                row.state = "cancelled" if error.reason == "CANCELLED_RUN" else "blocked"
                row.error_code = error.reason
                return None

    def send_reserved(self, ref, delivery_id, attempt_id):
        with self.metadata(ref) as (session, message, _app):
            row = session.scalar(
                select(Delivery).where(Delivery.id == delivery_id).with_for_update()
            )
            if (
                not row
                or row.message_id != message.id
                or row.state != "sending"
                or row.attempt_id != attempt_id
            ):
                return self.status(row)
            try:
                app, binding = message_binding(session, message, lock=True)
                consent = session.get(ShareConsent, row.consent_id) if row.consent_id else None
                body, answer = self.compose(
                    message,
                    binding,
                    row.phase,
                    include_citations=bool(consent and consent.include_citations),
                )
                if digest(body) != row.payload_sha256:
                    raise DomainError("SOURCE_STALE", "发送前依据或受众已变化。")
                decision = egress(
                    session,
                    SimpleNamespace(
                        tenant_id=message.tenant_id, data_categories=answer.data_categories
                    ),
                    "dingtalk",
                    data_categories=answer.data_categories,
                )
                row.p26 = {**asdict(decision), "checked_at": decision.checked_at.isoformat()}
                secret = credential(self.runtime, app)
            except DomainError as error:
                row.state = "cancelled" if error.reason == "CANCELLED_RUN" else "blocked"
                row.error_code = error.reason
                return self.status(row)
            # Binding/app locks fence an already committed revoke or config disable.
            # A transport timeout/worker loss may have sent: never send again automatically.
            try:
                receipt = self.runtime.adapter.send(app, secret, row.request_key, body)
            except Exception:
                row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            else:
                self.accept_receipt(row, receipt)
            return self.status(row)

    @staticmethod
    def accept_receipt(row, receipt):
        if (
            not isinstance(receipt, dict)
            or receipt.get("provider") != "dingtalk"
            or receipt.get("payload_sha256") != row.payload_sha256
            or not isinstance(receipt.get("message_id"), str)
            or not 1 <= len(receipt["message_id"]) <= 200
        ):
            row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            return
        metadata = {key: receipt[key] for key in ("provider", "message_id", "payload_sha256")}
        if type(receipt.get("synthetic")) is bool:
            metadata["synthetic"] = receipt["synthetic"]
        status = receipt.get("status", "delivered")
        if status not in {"pending", "delivered", "failed"}:
            row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            return
        if "status" in receipt:
            metadata["status"] = status
            target = receipt.get("target_kind")
            if target not in {"direct", "group"}:
                row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
                return
            metadata["target_kind"] = target
            if target == "group":
                conversation = receipt.get("conversation_id")
                if not isinstance(conversation, str) or not 1 <= len(conversation) <= 200:
                    row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
                    return
                metadata["conversation_id"] = conversation
        row.provider_receipt = metadata
        row.state = {"pending": "unknown", "delivered": "delivered", "failed": "blocked"}[status]
        row.error_code = {
            "pending": "EXTERNAL_OUTCOME_UNKNOWN",
            "delivered": None,
            "failed": "EXTERNAL_DELIVERY_REJECTED",
        }[status]

    @staticmethod
    def status(row):
        if row is None:
            raise DomainError("FORBIDDEN_SCOPE", "投递回执不可读取。", 403)
        return {
            "delivery_id": str(row.id),
            "state": row.state,
            "phase": row.phase,
            "error_code": row.error_code,
            "attempts": row.attempts,
        }

    def reconcile(self, ref, delivery_id):
        with self.metadata(ref) as (session, message, app):
            row = session.scalar(
                select(Delivery).where(Delivery.id == delivery_id).with_for_update()
            )
            if not row or row.message_id != message.id:
                raise DomainError("FORBIDDEN_SCOPE", "投递不属于当前入站记录。", 403)
            if row.state not in {"sending", "unknown"}:
                return self.status(row)
            # Receipt lookup is not another body delivery and does not need business READ.
            # Revocation still permits metadata reconciliation; it never permits send().
            try:
                lookup_receipt = getattr(self.runtime.adapter, "lookup_receipt", None)
                secret = credential(self.runtime, app)
                receipt = (
                    lookup_receipt(app, secret, row.request_key, row.provider_receipt)
                    if lookup_receipt is not None
                    else self.runtime.adapter.lookup(app, secret, row.request_key)
                )
            except Exception:
                receipt = None
            if receipt is not None:
                self.accept_receipt(row, receipt)
            else:
                row.state, row.error_code = "unknown", "EXTERNAL_OUTCOME_UNKNOWN"
            return self.status(row)

    def deliver(self, ref):
        delivery_id = self.plan(ref)
        attempt = self.reserve(ref, delivery_id)
        if attempt is not None:
            return self.send_reserved(ref, delivery_id, attempt)
        return self.reconcile(ref, delivery_id)

    def preview_share(self, session, ctx, data):
        human(session, ctx)
        message = session.scalar(
            select(Message).where(Message.run_id == data.run_id, Message.owner_id == ctx.actor_id)
        )
        if not message or message.conversation_kind != "group":
            raise DomainError("FORBIDDEN_SCOPE", "此运行没有本人群提问记录。", 403)
        _app, binding = message_binding(session, message)
        body, answer = self.compose(
            message, binding, "share", include_citations=data.include_citations
        )
        return {
            "run_id": str(message.run_id),
            "payload": body,
            "preview_digest": digest(body),
            "withheld_reason": answer.withheld_reason,
            "citations_included": bool(body.get("citations")),
        }

    def confirm_share(self, session, ctx, data):
        human(session, ctx)
        old = session.scalar(
            select(ShareConsent).where(
                ShareConsent.owner_id == ctx.actor_id, ShareConsent.request_key == data.request_key
            )
        )
        if old:
            message = session.get(Message, old.message_id)
            if (
                not message
                or message.run_id != data.run_id
                or old.payload_sha256 != data.preview_digest
                or old.include_citations != data.include_citations
            ):
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "原分享确认对应不同内容。")
            return {"consent_id": str(old.id), "state": old.state}
        view = self.preview_share(session, ctx, data)
        if view["preview_digest"] != data.preview_digest:
            raise DomainError("VERSION_CONFLICT", "实际答案、来源或受众已变化，请重新预览。")
        message = session.scalar(select(Message).where(Message.run_id == data.run_id))
        row = ShareConsent(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            message_id=message.id,
            owner_id=ctx.actor_id,
            request_key=data.request_key,
            payload_sha256=data.preview_digest,
            include_citations=data.include_citations,
        )
        session.add(row)
        session.flush()
        return {"consent_id": str(row.id), "state": row.state}

    def cancel_lost(self, ref):
        with tenant_session(self.metadata_engine, ref.tenant_id) as session:
            return session.scalar(
                text("SELECT dingtalk_cancel_lost_run(:tenant,:message)"),
                {"tenant": ref.tenant_id, "message": ref.message_id},
            )

    def tick(self, ref):
        from .schemas import DeliveryReference

        if self.cancel_lost(ref):
            return {"state": "cancelled"}
        if isinstance(ref, DeliveryReference) and ref.phase == "share":
            try:
                result = self.deliver(ref)
            except DomainError as error:
                result = {"state": "blocked", "error_code": error.reason}
            with self.metadata(ref) as (session, message, _app):
                consent = session.get(ShareConsent, ref.consent_id)
                if consent is None or consent.message_id != message.id:
                    raise DomainError("FORBIDDEN_SCOPE", "分享确认不属于这条实际群消息。", 403)
                consent.state, consent.error_code = result["state"], result.get("error_code")
            return (
                {"state": "waiting", "delivery_state": "unknown"}
                if result["state"] == "unknown"
                else result
            )
        received = self.deliver(DeliveryReference(**ref.model_dump(), phase="received"))
        if received["state"] in {"blocked", "cancelled"}:
            return received
        if received["state"] == "unknown":
            return {"state": "waiting", "delivery_state": "unknown"}
        with self.metadata(ref) as (session, message, _app):
            group = message.conversation_kind == "group"
            previous = session.scalar(
                select(Delivery).where(
                    Delivery.message_id == message.id, Delivery.phase == "answer"
                )
            )
            prior_id = previous.id if previous else None
            if prior_id is None:
                snapshot = self.owner_snapshot(message)
        if prior_id is not None:
            known = self.reconcile(ref, prior_id)
            if known["state"] == "unknown":
                return {"state": "waiting", "delivery_state": "unknown"}
            if group and known["state"] == "delivered":
                known = self.deliver(DeliveryReference(**ref.model_dump(), phase="group_notice"))
            if known["state"] == "unknown":
                return {"state": "waiting", "delivery_state": "unknown"}
            with self.metadata(ref) as (_session, message, _app):
                message.state = "completed" if known["state"] == "delivered" else "unknown"
            return known
        if snapshot["status"] not in {"completed", "partial", "failed", "cancelled"}:
            return {"state": "waiting", "run_status": snapshot["status"]}
        answer = self.deliver(DeliveryReference(**ref.model_dump(), phase="answer"))
        if group and answer["state"] == "delivered":
            answer = self.deliver(DeliveryReference(**ref.model_dump(), phase="group_notice"))
        with self.metadata(ref) as (_session, message, _app):
            message.state = "completed" if answer["state"] == "delivered" else "unknown"
        return (
            {"state": "waiting", "delivery_state": "unknown"}
            if answer["state"] == "unknown"
            else answer
        )
