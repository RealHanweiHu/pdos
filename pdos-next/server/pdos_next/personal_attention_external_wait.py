"""Current external waiting responsibility and pending transfer, without writes.

An internal check time never proves delivery, a counterparty commitment or an
external overdue result. Actual clock computation remains with the wait owner.
"""

from sqlalchemy import DateTime, String, and_, cast, func, literal, select

from pdos_next import models as registered_models  # noqa: F401 -- ordinary native registry
from pdos_next.domain.external_wait.models import ExternalWaitCurrent, ExternalWaitVersion
from pdos_next.domain.work_management.models import BINDING
from pdos_next.personal_attention_common import columns


def queries(ctx, queue=None):
    """Return only this caller's current native sources in the requested queue."""
    current, row = ExternalWaitCurrent, ExternalWaitVersion
    exact = and_(
        *(
            getattr(current, key) == getattr(row, key)
            for key in (*BINDING, "wait_id", "revision", "state")
        ),
        current.version_id == row.id,
    )
    result = []
    for name in ("external", "receive"):
        if queue is not None and queue != name:
            continue
        transferring = name == "receive"
        kind = "external_wait_transfer" if transferring else "external_wait"
        person = row.body["transfer"]["to_id"] if transferring else row.body["responsible_id"]
        reason = (
            "这条等待有待你接收的责任转交请求；接受后才转移责任。内部检查不代表对方承诺或外部超期。"
            if transferring
            else "你是当前内部跟进责任人；下次检查仅为内部安排，不表示已有效送达或对方已超期。"
        )
        query = (
            select(
                *columns(
                    key=literal(kind + ":") + cast(row.wait_id, String),
                    kind=kind,
                    queue=name,
                    tenant_id=row.tenant_id,
                    source_id=row.wait_id,
                    version_id=row.id,
                    revision=row.revision,
                    category_id=row.category_id,
                    product_id=row.product_id,
                    project_id=row.project_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    recorded_at=row.created_at,
                    title=row.body["title"].astext,
                    reason=reason,
                    state=row.state,
                    responsible_id=ctx.requester_id,
                    responsibility="external_wait_transfer_recipient"
                    if transferring
                    else "external_wait_responsible",
                    target="project",
                    due_at=None
                    if transferring
                    else cast(row.body["next_check_at"].astext, DateTime(timezone=True)),
                    details=func.jsonb_build_object(
                        "view",
                        "work",
                        "blocking",
                        row.body["blocking"].as_boolean(),
                        "next_check_at",
                        row.body["next_check_at"].astext,
                        "next_check_is_internal",
                        True,
                        "original_timezone",
                        row.body["original_timezone"].astext,
                        "delivery_state",
                        row.body["delivery"]["status"].astext,
                        "delivery_time_basis",
                        row.body["delivery"]["time_basis"].astext,
                        "reply_state",
                        row.body["reply"]["status"].astext,
                        "transfer_request_id",
                        row.body["transfer"]["request_id"].astext,
                        "transfer_from_id",
                        row.body["transfer"]["from_id"].astext,
                        "transfer_to_id",
                        row.body["transfer"]["to_id"].astext,
                    ),
                )
            )
            .select_from(current)
            .join(row, exact)
            .where(
                row.tenant_id == ctx.tenant_id,
                row.state == "open",
                person.astext == str(ctx.requester_id),
            )
        )
        if transferring:
            query = query.where(row.body["transfer"]["request_id"].astext.is_not(None))
        result.append(query)
    return tuple(result)
