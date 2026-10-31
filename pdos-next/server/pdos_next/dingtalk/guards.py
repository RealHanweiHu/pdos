"""Only actual native Run→Message→Binding edges authorize channel work."""

from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.models import Principal

from .models import Application, Binding, Message


def message_binding(session, message, run=None, *, lock=False):
    # A service actor has metadata SELECT, never Human/admin UPDATE policy.
    # The bounded internal helper locks the actual Message's app then binding;
    # the following ordinary RLS reads still decide current validity.
    if lock:
        session.execute(
            text("SELECT dingtalk_lock_message_binding(:tenant,:message)"),
            {"tenant": message.tenant_id, "message": message.id},
        )
    query = select(Binding).where(Binding.id == message.binding_id)
    app_query = select(Application).where(Application.id == message.application_id)
    if lock:
        query = query.execution_options(populate_existing=True)
        app_query = app_query.execution_options(populate_existing=True)
    binding = session.scalar(query)
    app = session.scalar(app_query)
    person = session.get(Principal, message.owner_id)
    service = session.get(Principal, app.service_principal_id) if app else None
    if (
        not app
        or not app.active
        or not service
        or not service.active
        or service.kind != "agent"
        or not binding
        or not binding.active
        or binding.application_id != app.id
        or binding.owner_id != message.owner_id
        or binding.epoch != message.binding_epoch
        or not person
        or not person.active
        or person.kind != "human"
        or message.tenant_id != binding.tenant_id
        or (
            run is not None
            and (
                run.id != message.run_id
                or run.requester_id != message.owner_id
                or run.tenant_id != message.tenant_id
            )
        )
    ):
        raise DomainError("CANCELLED_RUN", "钉钉绑定、应用或本人身份已失效。")
    return app, binding


def run_guard(session, run):
    if run is None or not getattr(run, "versions", {}).get("dingtalk"):
        return None
    message = session.scalar(select(Message).where(Message.run_id == run.id))
    if message is not None:
        message_binding(session, message, run)
    elif run.versions.get("dingtalk"):
        raise DomainError("FORBIDDEN_SCOPE", "钉钉运行缺少实际入站记录。", 403)
    return message


def read_only(session, run):
    if not getattr(run, "versions", {}).get("dingtalk"):
        return
    if session.scalar(select(Message.id).where(Message.run_id == run.id)):
        raise DomainError("FORBIDDEN_SCOPE", "钉钉入口只读；业务动作请回 PDOS 本人确认。", 403)


def guard_writing(store, scope):
    with store.transaction(scope) as (session, run):
        read_only(session, run)
