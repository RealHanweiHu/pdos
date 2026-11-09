"""Finite supplier-commitment transitions; no stock, arrival, reservation or approval."""

from datetime import timedelta

from pdos_next.domain.projects.work.rules import require

from .schemas import Closure, Payload, Snapshot

CHECK_DELAY = timedelta(days=1)


def semantic(payload):
    return payload.model_dump(mode="json")


def check_at(promised_at):
    """F25: one day after the promised date; an unknown date has no check."""
    return promised_at + CHECK_DELAY if promised_at is not None else None


def transition(
    payload,
    *,
    current=None,
    commitment_id=None,
    build=None,
    actor_id,
    requester_id,
    maintainers,
    at,
    human_actor,
):
    """Return the next immutable snapshot, or refuse; never touches supply pools."""
    payload = Payload.model_validate(payload)
    r = payload.record
    if not human_actor:
        require(
            payload.statement is None and bool(payload.sources),
            "小Pai 须引用原文登记供方承诺，不能以本人陈述代替。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
    basis = "human_recorded" if human_actor else "source_claim"
    sources = tuple(
        sorted(payload.sources, key=lambda ref: (str(ref.id), ref.revision, ref.position))
    )
    if r.action == "create":
        require(
            current is None and commitment_id is not None and build is not None,
            "新承诺由实际 owner 建立身份。",
        )
        require(
            r.expected_build_revision == build.revision,
            "试制轮次版本已变化，请重读后再登记。",
            "VERSION_CONFLICT",
        )
        return Snapshot(
            commitment_id=commitment_id,
            revision=1,
            state="open",
            build_id=build.id,
            build_revision=build.revision,
            project_id=build.project_id,
            material_id=r.material_id,
            supplier_ref=r.supplier_ref,
            quantity=r.quantity,
            unit=r.unit,
            promised_at=r.promised_at,
            check_at=check_at(r.promised_at),
            original_timezone=r.original_timezone,
            text=r.text,
            responsible_id=requester_id,
            created_at=at,
            recorded_at=at,
            time_basis=basis,
            statement=payload.statement,
            sources=sources,
        )
    old = Snapshot.model_validate(current)
    require(
        payload.commitment.id == old.commitment_id and payload.commitment.revision == old.revision,
        "承诺已续版，请核对当前版本。",
        "VERSION_CONFLICT",
    )
    require(
        requester_id in {old.responsible_id, *maintainers},
        "只有建立人、本轮负责人或项目负责人可维护此承诺。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(
        (old.state == "closed" and r.action == "reopen")
        or (old.state == "open" and r.action != "reopen"),
        "关闭的承诺须先明确重开，不能暗中改写跟进记录。",
    )
    values = old.model_dump()
    values.update(
        revision=old.revision + 1,
        recorded_at=at,
        time_basis=basis,
        statement=payload.statement,
        sources=sources,
    )
    if r.action == "revise":
        values.update(
            quantity=r.quantity,
            unit=r.unit,
            promised_at=r.promised_at,
            check_at=check_at(r.promised_at),
            original_timezone=r.original_timezone,
            text=r.text,
        )
    elif r.action == "close":
        values.update(
            state="closed",
            last_closure=Closure(
                result=r.result, actor_id=actor_id, requester_id=requester_id, recorded_at=at
            ),
        )
    elif r.action == "reopen":
        values["state"] = "open"
    else:
        require(False, "未登记的承诺动作。", "VALIDATION_FAILED", 422)
    return Snapshot.model_validate(values)


def follow_up(snapshot, *, at):
    """The internal follow-up state; never a breach, an arrival or a kit result."""
    v = Snapshot.model_validate(snapshot)
    if v.state == "closed":
        return {
            "status": "closed",
            "check_due": False,
            "reason": "内部跟进已关闭；实际到货仍以供给快照的到货记录为准。",
        }
    if v.check_at is None:
        return {
            "status": "date_unknown",
            "check_due": None,
            "reason": "供方未给出承诺日期，没有检查日。",
        }
    if at >= v.check_at:
        return {
            "status": "check_due",
            "check_due": True,
            "reason": "已过承诺日的次日检查点；这不是违约判定，也不代表未到货。",
        }
    return {"status": "pending", "check_due": False, "reason": "未到检查日。"}
