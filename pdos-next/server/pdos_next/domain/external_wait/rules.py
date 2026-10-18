"""Finite waiting records; no external send, professional acceptance or actual arrival."""

from uuid import uuid4

from pdos_next.domain.work_management.rules import require
from pdos_next.engines.planning.calendar import CalendarError, WorkingTime
from pdos_next.engines.planning.dto import CalendarSnapshot

from .schemas import (
    Closure,
    CommitmentEntry,
    DeliveryEntry,
    Entry,
    Payload,
    ReplyEntry,
    Snapshot,
    Transfer,
)


def semantic(payload):
    return payload.model_dump(mode="json")


def _entry(record, payload, actor_id, requester_id, at, human_actor):
    require(
        record.at is None or record.at <= at,
        "发生时间不能晚于本次实际登记。",
        "VALIDATION_FAILED",
        422,
    )
    return dict(
        at=record.at,
        text=record.text,
        original_timezone=record.original_timezone,
        time_basis="human_recorded" if human_actor else "source_claim",
        actor_id=actor_id,
        requester_id=requester_id,
        recorded_at=at,
        sources=payload.sources,
    )


def transition(
    payload,
    *,
    current=None,
    wait_id=None,
    actor_id,
    requester_id,
    project_owner_id,
    at,
    human_actor,
):
    payload = Payload.model_validate(payload)
    r = payload.record
    action = r.action
    if action == "create":
        require(current is None and wait_id is not None, "新等待由实际owner建立身份。")
        values = r.model_dump(exclude={"action"})
        return Snapshot(
            wait_id=wait_id,
            revision=1,
            state="open",
            responsible_id=requester_id,
            created_at=at,
            **values,
        )
    old = Snapshot.model_validate(current)
    require(
        payload.wait.id == old.wait_id and payload.wait.revision == old.revision,
        "等待已续版，请核对当前版本。",
        "VERSION_CONFLICT",
    )
    if action == "transfer_accept":
        require(
            old.state == "open"
            and old.transfer is not None
            and old.transfer.to_id == requester_id
            and old.transfer.request_id == r.request_id,
            "须由当前接收请求指定的本人接受。",
            "FORBIDDEN_SCOPE",
            403,
        )
        require(
            human_actor,
            "责任接收须本人明确登记；AI不能代替本人承接。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
    else:
        require(
            requester_id in {old.responsible_id, project_owner_id},
            "只有当前责任人或本项目负责人可维护此等待。",
            "FORBIDDEN_SCOPE",
            403,
        )
    require(
        (old.state == "closed" and action == "reopen")
        or (old.state == "open" and action != "reopen"),
        "关闭的等待须先明确重开，不能暗中改写进展。",
    )
    values = old.model_dump()
    values["revision"] += 1
    if action == "details":
        values.update(r.model_dump(exclude={"action"}))
    elif action == "initiate":
        event = Entry(**_entry(r, payload, actor_id, requester_id, at, human_actor))
        if (
            event.at
            and event.time_basis == "human_recorded"
            and old.delivery
            and old.delivery.status == "effective"
        ):
            require(
                event.at <= old.delivery.at,
                "发起与已核送达时点冲突，请先登记送达冲突。",
                "VALIDATION_FAILED",
                422,
            )
        values["initiation"] = event
    elif action == "delivery":
        require(
            human_actor
            or (
                r.status != "effective"
                and not (old.delivery and old.delivery.status == "effective")
            ),
            "有效送达及其纠正须本人依据实际记录登记；AI可记录待核对材料。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
        event = DeliveryEntry(
            status=r.status, **_entry(r, payload, actor_id, requester_id, at, human_actor)
        )
        if (
            event.status == "effective"
            and old.initiation
            and old.initiation.time_basis == "human_recorded"
            and old.initiation.at
        ):
            require(
                event.at >= old.initiation.at,
                "送达不能早于已核对的发起时点。",
                "VALIDATION_FAILED",
                422,
            )
        values["delivery"] = event
    elif action == "commitment":
        values["counterparty_commitment"] = CommitmentEntry(
            promised_at=r.promised_at,
            text=r.text,
            original_timezone=r.original_timezone,
            actor_id=actor_id,
            requester_id=requester_id,
            recorded_at=at,
            sources=payload.sources,
        )
    elif action == "reply":
        values["reply"] = ReplyEntry(
            status=r.status, **_entry(r, payload, actor_id, requester_id, at, human_actor)
        )
    elif action == "close":
        values.update(
            state="closed",
            last_closure=Closure(
                result=r.result,
                actor_id=actor_id,
                requester_id=requester_id,
                recorded_at=at,
                sources=payload.sources,
            ),
        )
    elif action == "reopen":
        values["state"] = "open"
    elif action == "transfer_request":
        require(
            old.transfer is None and r.to_id != old.responsible_id,
            "请先处理原接收请求；不能向同一责任人转交。",
            "INVALID_STATE",
        )
        values["transfer"] = Transfer(
            request_id=uuid4(),
            from_id=old.responsible_id,
            to_id=r.to_id,
            actor_id=actor_id,
            requested_at=at,
            sources=payload.sources,
        )
    elif action == "transfer_accept":
        values.update(responsible_id=old.transfer.to_id, transfer=None)
    elif action == "transfer_cancel":
        require(
            old.transfer is not None and old.transfer.request_id == r.request_id,
            "接收请求已变化。",
            "VERSION_CONFLICT",
        )
        values["transfer"] = None
    else:
        require(False, "未登记的等待动作。", "VALIDATION_FAILED", 422)
    return Snapshot.model_validate(values)


def clock(snapshot, *, at, calendar=None, calendar_label=None, unavailable=False):
    """Use actual delivered time and explicitly adopted calendar; never reminder counts."""
    v = Snapshot.model_validate(snapshot)
    delivery = v.delivery
    effective = bool(
        delivery
        and delivery.status == "effective"
        and delivery.time_basis == "human_recorded"
        and delivery.at
    )
    point = v.last_closure.recorded_at if v.state == "closed" and v.last_closure else at
    response_at = delivery.at if effective else None
    reasons = []
    minutes = None
    commitment_due = None
    check_due = at >= v.next_check_at if v.next_check_at else None
    if delivery and delivery.status == "conflict":
        status = "delivery_conflict"
        reasons.append("送达材料存在冲突，不能认定对方响应时钟。")
    elif not effective:
        status = "delivery_unknown"
        reasons.append("尚无已核对的有效送达，不启动对方响应时钟。")
    elif unavailable:
        status = "calendar_unavailable"
        reasons.append("所采用日历的实际来源暂不可用，工作时长和声明时限未知。")
    elif calendar is None:
        status = "calendar_unknown"
        reasons.append("尚未显式采用实际日历，工作时长和声明时限未知。")
    else:
        status = "running"
        try:
            work = WorkingTime(CalendarSnapshot.model_validate(calendar))
            minutes = work.working_minutes(response_at, point)
            if v.counterparty_commitment and v.counterparty_commitment.promised_at:
                commitment_due = (
                    work.working_minutes(v.counterparty_commitment.promised_at, point) > 0
                )
        except (CalendarError, ValueError, OverflowError):
            minutes = None
            status = "calendar_unavailable"
            reasons.append("固定日历不能覆盖当前计算范围或时区规则已变化，未填造时长。")
    if v.state == "closed":
        status = "closed"
        check_due = False
        commitment_due = False
        escalation = "closed"
        reasons.append("内部等待已关闭；不代表外部义务取消、实际到货或正式接收。")
    elif commitment_due:
        escalation = "claimed_commitment_due"
        reasons.append("按明确采用的实际日历，对方声明的承诺时间已过；这不是正式违约判定。")
    elif check_due:
        escalation = "check_due"
        reasons.append("已到内部下次检查点；不据此认定对方已超期。")
    elif status != "running":
        escalation = "unknown"
    else:
        escalation = "none"
    return dict(
        status=status,
        response_started_at=response_at.isoformat() if response_at else None,
        working_minutes=minutes,
        calendar_label=calendar_label,
        check_due=check_due,
        claimed_commitment_due=commitment_due,
        escalation=escalation,
        reasons=reasons,
    )
