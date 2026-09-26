"""Preregistered pre-project teams and independent actual-version reception."""

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.research_workpacks import (
    Close,
    ClosePreview,
    DeliveryPreview,
    DeliverySave,
    History,
    Options,
    Read,
    ReceptionPreview,
    ReceptionSave,
    WorkpackCreate,
)
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.research_measurement import (
    SUBJECT_COLUMNS,
    ResearchMeasurementService,
    current_consent,
    manage,
    sample_item,
    scope_values,
    study,
)
from app.domain.research_measurement_sources import (
    authorize_scope,
    participant,
    source,
    source_options,
)
from app.domain.research_workpack_calculations import workpack_study_summary, workpack_summary
from app.domain.research_workpack_sources import delivery_options, delivery_source
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def event(c: Connection, context: AuthContext, pack: Any, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=None
    ).record(
        EventDraft(
            event_id=f"research-workpack:{identity}:{action}",
            event_type="RESEARCH_WORKPACK_RECORDED",
            source="research_workpack_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"research_workpack.{action}",
            after_snapshot={"record_id": str(identity), "action": action},
            context={
                "market_space_id": str(pack["market_space_id"]),
                "scope_key": str(pack["scope_key"]),
            },
        ),
    )


def is_manager(c: Connection, context: AuthContext, pack: Any) -> bool:
    return manage(c, context, pack["market_space_id"], pack["product_line_id"])


def grant(
    c: Connection,
    context: AuthContext,
    pack: Any,
    user: UUID,
    *,
    expected: UUID | None = None,
    delivered_subject: UUID | None = None,
) -> Any:
    actual = participant(c, context, pack["market_space_id"], pack["product_line_id"], user)
    if delivered_subject is not None:
        delivery_source(
            c,
            actual,
            pack["market_space_id"],
            pack["product_line_id"],
            pack["subject_kind"],
            delivered_subject,
        )
    else:
        source(
            c,
            actual,
            pack["market_space_id"],
            pack["product_line_id"],
            pack["subject_kind"],
            pack["subject_id"],
        )
    row = current_consent(c, context.tenant.id, pack["study_id"], user)
    if (
        row is None
        or row["status"] != "consented"
        or expected is not None
        and row["id"] != expected
    ):
        raise PermissionError("本人尚未同意或已撤回这批资料的测量披露")
    return row


def get_pack(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> Any:
    t = tables.research_measurement_workpacks
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.market_space_id == space, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("未找到当前市场空间中的团队工作包")
    authorize_scope(c, context, space, row["product_line_id"])
    if not is_manager(c, context, row):
        m = tables.research_measurement_workpack_members
        if (
            c.execute(
                select(m.c.id).where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.workpack_id == identity,
                    m.c.user_id == context.user.id,
                )
            ).scalar_one_or_none()
            is None
        ):
            raise PermissionError("仅登记参与者或原范围管理人员可读取工作包")
    source(c, context, space, row["product_line_id"], row["subject_kind"], row["subject_id"])
    return row


def members(c: Connection, pack: Any) -> list[dict[str, Any]]:
    m, u = tables.research_measurement_workpack_members, tables.users
    rows = (
        c.execute(
            select(m.c.user_id, m.c.role_id, m.c.first_use, u.c.display_name)
            .select_from(m.join(u, (u.c.tenant_id == m.c.tenant_id) & (u.c.id == m.c.user_id)))
            .where(m.c.tenant_id == pack["tenant_id"], m.c.workpack_id == pack["id"])
            .order_by(m.c.user_id)
        )
        .mappings()
        .all()
    )
    return [_plain(row) for row in rows]


def pack_item(c: Connection, pack: Any) -> dict[str, Any]:
    return {
        **_plain(
            {
                k: pack[k]
                for k in (
                    "id",
                    "market_space_id",
                    "product_line_id",
                    "scope_key",
                    "study_id",
                    "subject_kind",
                    "subject_id",
                    "subject_series_id",
                    "mode",
                    "creator_user_id",
                    "deliverer_user_id",
                    "receiver_user_id",
                    "created_at",
                )
            }
        ),
        "body": pack["body"],
        "members": members(c, pack),
        "source": pack["source_snapshot"],
    }


def rows(c: Connection, table: Any, pack: Any) -> list[Any]:
    return list(
        c.execute(
            select(table)
            .where(table.c.tenant_id == pack["tenant_id"], table.c.workpack_id == pack["id"])
            .order_by(table.c.created_at, table.c.id)
        )
        .mappings()
        .all()
    )


def state(c: Connection, pack: Any) -> tuple[list[Any], list[Any], Any]:
    ds = rows(c, tables.research_measurement_deliveries, pack)
    rs = rows(c, tables.research_measurement_receptions, pack)
    cs = rows(c, tables.research_measurement_closures, pack)
    return ds, rs, cs[0] if cs else None


def active_window(c: Connection, context: AuthContext, pack: Any) -> None:
    authorize_scope(c, context, pack["market_space_id"], pack["product_line_id"], writable=True)
    protocol = study(c, context, pack["market_space_id"], pack["study_id"])
    if not protocol["window_start"] <= datetime.now(UTC) < protocol["window_end"]:
        raise ProductWorkError("实际交付、接收或终止须发生在原观察窗口内，不能倒填历史回执")


def delivery_item(
    c: Connection, context: AuthContext, pack: Any, row: Any, *, strict: bool = False
) -> dict[str, Any]:
    if strict or context.user.id not in {row["actor_user_id"], row["receiver_user_id"]}:
        grant(
            c,
            context,
            pack,
            row["actor_user_id"],
            expected=row["deliverer_consent_id"],
            delivered_subject=row["subject_id"],
        )
        grant(
            c,
            context,
            pack,
            row["receiver_user_id"],
            expected=row["receiver_consent_id"],
            delivered_subject=row["subject_id"],
        )
    elif context.user.id == row["receiver_user_id"]:
        grant(
            c,
            context,
            pack,
            row["actor_user_id"],
            expected=row["deliverer_consent_id"],
            delivered_subject=row["subject_id"],
        )
    current = delivery_source(
        c,
        context,
        pack["market_space_id"],
        pack["product_line_id"],
        row["subject_kind"],
        row["subject_id"],
    )
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "round",
                    "subject_kind",
                    "subject_id",
                    "subject_series_id",
                    "locator",
                    "description",
                    "actor_user_id",
                    "receiver_user_id",
                    "source_snapshot",
                    "created_at",
                )
            }
        ),
        "delivered_at": row["created_at"].isoformat(),
        "source_changed": digest(current) != row["source_digest"],
        "record_changed": digest(current["record"]) != digest(row["source_snapshot"]["record"]),
        "current_source": current,
    }


def reception_item(
    c: Connection, context: AuthContext, pack: Any, row: Any, delivery: Any, *, strict: bool = False
) -> dict[str, Any]:
    if strict or context.user.id != row["actor_user_id"]:
        grant(
            c,
            context,
            pack,
            row["actor_user_id"],
            expected=row["receiver_consent_id"],
            delivered_subject=delivery["subject_id"],
        )
        grant(
            c,
            context,
            pack,
            delivery["actor_user_id"],
            expected=delivery["deliverer_consent_id"],
            delivered_subject=delivery["subject_id"],
        )
    current = delivery_source(
        c,
        context,
        pack["market_space_id"],
        pack["product_line_id"],
        delivery["subject_kind"],
        delivery["subject_id"],
    )
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "delivery_id",
                    "decision",
                    "criteria_checked",
                    "reason",
                    "actor_user_id",
                    "source_snapshot",
                    "created_at",
                )
            }
        ),
        "round": delivery["round"],
        "received_at": row["created_at"].isoformat(),
        "original_delivery_source": delivery["source_snapshot"],
        "source_changed": digest(current) != row["source_digest"],
        "record_changed": digest(current["record"])
        != digest(delivery["source_snapshot"]["record"]),
        "current_source": current,
    }


def close_item(row: Any) -> dict[str, Any] | None:
    return (
        {
            **_plain(
                {k: row[k] for k in ("id", "actor_user_id", "outcome", "reason", "created_at")}
            ),
            "closed_at": row["created_at"].isoformat(),
        }
        if row
        else None
    )


def sample_rows(c: Connection, context: AuthContext, pack: Any) -> list[Any]:
    t = ResearchMeasurementService._latest(context, pack["market_space_id"], pack["study_id"])
    return list(
        c.execute(
            select(t).where(
                t.c.ordinal == 1,
                t.c.subject_kind == pack["subject_kind"],
                t.c.subject_series_id == pack["subject_series_id"],
                t.c.mode == pack["mode"],
            )
        )
        .mappings()
        .all()
    )


def matches(pack: Any, body: dict[str, Any], roster: list[dict[str, Any]]) -> bool:
    matched = next((m for m in roster if m["user_id"] == body.get("participant_user_id")), None)
    return (
        matched is not None
        and all(
            body.get(k) == pack["body"].get(k)
            for k in ("complexity_stratum", "workflow_version", "pair_key", "matching_basis")
        )
        and body.get("role_id") == matched["role_id"]
        and body.get("first_use") == matched["first_use"]
    )


def detail(c: Connection, context: AuthContext, pack: Any) -> dict[str, Any]:
    ds, rs, closed = state(c, pack)
    delivered, received, own = [], [], []
    unavailable = 0
    roster = members(c, pack)
    manager = is_manager(c, context, pack)
    receipts_allowed = manager or context.user.id in {
        pack["deliverer_user_id"],
        pack["receiver_user_id"],
    }
    for row in ds:
        if not receipts_allowed:
            continue
        try:
            delivered.append(delivery_item(c, context, pack, row))
        except (PermissionError, ProductWorkError):
            unavailable += 1
    by_id = {d["id"]: d for d in ds}
    for row in rs:
        if not receipts_allowed:
            continue
        try:
            received.append(reception_item(c, context, pack, row, by_id[row["delivery_id"]]))
        except (PermissionError, ProductWorkError):
            unavailable += 1
    for row in sample_rows(c, context, pack):
        if row["participant_user_id"] == context.user.id and matches(pack, row["body"], roster):
            with suppress(PermissionError, ProductWorkError):
                own.append(sample_item(c, context, pack["market_space_id"], row))
    last = ds[-1] if ds else None
    decision = next((r for r in rs if last and r["delivery_id"] == last["id"]), None)
    return {
        "workpack": pack_item(c, pack),
        "deliveries": delivered,
        "receptions": received,
        "closure": close_item(closed),
        "own_samples": own,
        "can_manage": manager,
        "can_deliver": context.user.id == pack["deliverer_user_id"]
        and not closed
        and (last is None or decision is not None and decision["decision"] == "returned"),
        "can_receive": context.user.id == pack["receiver_user_id"]
        and not closed
        and last is not None
        and decision is None,
        "can_close": not closed
        and not any(r["decision"] == "accepted" for r in rs)
        and (manager or context.user.id == pack["deliverer_user_id"]),
        "unavailable_receipt_count": unavailable,
    }


def delivery_preview(
    c: Connection, context: AuthContext, pack: Any, command: DeliveryPreview
) -> dict[str, Any]:
    active_window(c, context, pack)
    if context.user.id != pack["deliverer_user_id"]:
        raise PermissionError("仅登记的实际交付人可提交原工作成果")
    sender = grant(
        c, context, pack, pack["deliverer_user_id"], delivered_subject=command.subject_id
    )
    receiver = grant(
        c, context, pack, pack["receiver_user_id"], delivered_subject=command.subject_id
    )
    ds, rs, closed = state(c, pack)
    if closed:
        raise ProductWorkError("工作包已具名终止")
    latest = ds[-1] if ds else None
    response = next((r for r in rs if latest and r["delivery_id"] == latest["id"]), None)
    if latest and (response is None or response["decision"] != "returned"):
        raise ProductWorkError("须原接收人退回后才可交付新轮次；待接收或已接受不能重复提交")
    if len(ds) >= 100:
        raise ProductWorkError("同一工作包已达到100轮记录上限，原记录保留")
    basis = delivery_source(
        c,
        context,
        pack["market_space_id"],
        pack["product_line_id"],
        pack["subject_kind"],
        command.subject_id,
    )
    if str(basis["series_id"]) != str(pack["subject_series_id"]):
        raise ProductWorkError("只能交付原固定对象系列的实际版本")
    proposed = {
        "round": latest["round"] + 1 if latest else 1,
        "subject_kind": pack["subject_kind"],
        "subject_id": str(command.subject_id),
        "subject_series_id": str(pack["subject_series_id"]),
        "locator": command.locator,
        "description": command.description,
        "source_snapshot": basis,
    }
    signature = digest(
        {
            "workpack_id": str(pack["id"]),
            "delivery": proposed,
            "sender_consent": str(sender["id"]),
            "receiver_consent": str(receiver["id"]),
        }
    )
    return {
        "digest": signature,
        "workpack": pack_item(c, pack),
        "delivery": proposed,
        "source": basis,
        "record_changed": False,
        "deliverer_consent_id": str(sender["id"]),
        "receiver_consent_id": str(receiver["id"]),
    }


def reception_preview(
    c: Connection, context: AuthContext, pack: Any, command: ReceptionPreview
) -> dict[str, Any]:
    active_window(c, context, pack)
    if context.user.id != pack["receiver_user_id"]:
        raise PermissionError("仅登记的独立接收人可记录接受或退回")
    ds, rs, closed = state(c, pack)
    if (
        closed
        or not ds
        or ds[-1]["id"] != command.delivery_id
        or any(r["delivery_id"] == command.delivery_id for r in rs)
    ):
        raise ProductWorkError("须办理当前未裁决轮次，已结束或已有裁决不能改写")
    delivery = ds[-1]
    grant(
        c,
        context,
        pack,
        delivery["actor_user_id"],
        expected=delivery["deliverer_consent_id"],
        delivered_subject=delivery["subject_id"],
    )
    receiver = grant(
        c,
        context,
        pack,
        context.user.id,
        expected=delivery["receiver_consent_id"],
        delivered_subject=delivery["subject_id"],
    )
    basis = delivery_source(
        c,
        context,
        pack["market_space_id"],
        pack["product_line_id"],
        delivery["subject_kind"],
        delivery["subject_id"],
    )
    changed = digest(basis["record"]) != digest(delivery["source_snapshot"]["record"])
    if changed and command.decision == "accepted":
        raise ProductWorkError(
            "原交付版本内容已有变化，须明确退回后重新交付，不能静默接受另一份内容"
        )
    proposed = command.model_dump(mode="json", exclude={"request_id", "expected_digest"})
    return {
        "digest": digest(
            {
                "workpack": str(pack["id"]),
                "reception": proposed,
                "delivery": str(delivery["id"]),
                "source": basis,
                "receiver_consent": str(receiver["id"]),
            }
        ),
        "workpack": pack_item(c, pack),
        "delivery": delivery_item(c, context, pack, delivery, strict=True),
        "reception": proposed,
        "source": basis,
        "record_changed": changed,
        "receiver_consent_id": str(receiver["id"]),
    }


def closure_preview(
    c: Connection, context: AuthContext, pack: Any, command: ClosePreview
) -> dict[str, Any]:
    active_window(c, context, pack)
    if not is_manager(c, context, pack):
        if context.user.id != pack["deliverer_user_id"]:
            raise PermissionError("仅原交付人或该观察范围管理人员可登记失败或取消")
        participant(c, context, pack["market_space_id"], pack["product_line_id"], context.user.id)
    ds, rs, closed = state(c, pack)
    if closed or any(r["decision"] == "accepted" for r in rs):
        raise ProductWorkError("已结束或已被独立接受的工作包不能再登记失败或取消")
    proposed = command.model_dump(mode="json", exclude={"request_id", "expected_digest"})
    return {
        "digest": digest(
            {
                "workpack": str(pack["id"]),
                "closure": proposed,
                "deliveries": [str(d["id"]) for d in ds],
                "receptions": [str(r["id"]) for r in rs],
            }
        ),
        "workpack": pack_item(c, pack),
        "closure": proposed,
    }


def repeated(c: Connection, context: AuthContext, table: Any, command: Any, space: UUID) -> bool:
    row = (
        c.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.actor_user_id == context.user.id,
                table.c.request_id == command.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row:
        if row["request_digest"] != digest(
            {"market_space_id": str(space), "command": command.model_dump(mode="json")}
        ):
            raise ProductWorkError("同一请求不能改变原具名回执")
        return True
    return False


def summary_entry(c: Connection, context: AuthContext, pack: Any) -> dict[str, Any]:
    authorize_scope(c, context, pack["market_space_id"], pack["product_line_id"], access="manager")
    source(
        c,
        context,
        pack["market_space_id"],
        pack["product_line_id"],
        pack["subject_kind"],
        pack["subject_id"],
    )
    roster = members(c, pack)
    samples, delivered, received = [], [], []
    ds, rs, closed = state(c, pack)
    unavailable = 0
    for row in sample_rows(c, context, pack):
        if not matches(pack, row["body"], roster):
            continue
        try:
            grant(c, context, pack, row["participant_user_id"], expected=row["consent_id"])
            observed = sample_item(c, context, pack["market_space_id"], row)
            samples.append(
                {
                    **row["body"],
                    "id": str(row["id"]),
                    "version": row["version"],
                    "sample_version": row["version"],
                    "source_changed": observed["source_changed"],
                    "consent_id": str(row["consent_id"]),
                }
            )
        except (PermissionError, ProductWorkError):
            continue
    for row in ds:
        try:
            delivered.append(delivery_item(c, context, pack, row, strict=True))
        except (PermissionError, ProductWorkError):
            unavailable += 1
    by_id = {r["id"]: r for r in ds}
    for row in rs:
        try:
            received.append(
                reception_item(c, context, pack, row, by_id[row["delivery_id"]], strict=True)
            )
        except (PermissionError, ProductWorkError):
            unavailable += 1
    workpack = {
        **pack["body"],
        "id": str(pack["id"]),
        "created_at": pack["created_at"].isoformat(),
        "members": roster,
        "data_availability_complete": unavailable == 0,
        "unavailable_receipt_count": unavailable,
    }
    return {
        "workpack": workpack,
        "samples": samples,
        "deliveries": delivered,
        "receptions": received,
        "closure": close_item(closed),
    }


class ResearchWorkpackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, space: UUID, command: Options) -> dict[str, Any]:
        with self.engine.connect() as c:
            registered = study(c, context, space, command.study_id)
            line = registered["product_line_id"]
            if command.workpack_id:
                pack = get_pack(c, context, space, command.workpack_id)
                if (
                    pack["study_id"] != command.study_id
                    or pack["subject_kind"] != command.subject_kind
                ):
                    raise ProductWorkError("交付选项须沿原观察协议和工作对象类型")
                result = delivery_options(
                    c,
                    context,
                    space,
                    line,
                    pack["subject_kind"],
                    pack["subject_series_id"],
                    before_id=command.before_id,
                )
            else:
                result = source_options(
                    c,
                    context,
                    space,
                    line,
                    command.subject_kind,
                    query=command.query,
                    before_id=command.before_id,
                )
            result.update(
                {
                    "can_manage": manage(c, context, space, line),
                    "participant_user_id": str(context.user.id),
                    "users": [],
                    "next_user_before_id": None,
                }
            )
            if result["can_manage"]:
                m, u, lm = tables.market_space_members, tables.users, tables.product_line_members
                conditions = [
                    m.c.tenant_id == context.tenant.id,
                    m.c.market_space_id == space,
                    m.c.access.in_(("contributor", "manager")),
                    u.c.is_active.is_(True),
                    u.c.role.in_(("owner", "admin", "project_manager", "engineer", "quality")),
                ]
                if line:
                    conditions.append(
                        select(lm.c.user_id)
                        .where(
                            lm.c.tenant_id == context.tenant.id,
                            lm.c.product_line_id == line,
                            lm.c.user_id == u.c.id,
                            lm.c.access.in_(("contributor", "manager")),
                        )
                        .exists()
                    )
                if command.user_before_id:
                    conditions.append(u.c.id < command.user_before_id)
                if command.query:
                    conditions.append(u.c.display_name.icontains(command.query, autoescape=True))
                found = (
                    c.execute(
                        select(u.c.id, u.c.display_name)
                        .select_from(
                            m.join(u, (u.c.tenant_id == m.c.tenant_id) & (u.c.id == m.c.user_id))
                        )
                        .where(*conditions)
                        .order_by(u.c.id.desc())
                        .limit(31)
                    )
                    .mappings()
                    .all()
                )
                result["users"] = [_plain(row) for row in found[:30]]
                result["next_user_before_id"] = str(found[29]["id"]) if len(found) > 30 else None
            return result

    def create(self, context: AuthContext, space: UUID, command: WorkpackCreate) -> dict[str, Any]:
        with self.engine.begin() as c:
            registered = study(c, context, space, command.study_id)
            line = registered["product_line_id"]
            authorize_scope(c, context, space, line, access="manager", writable=True, lock=True)
            t = tables.research_measurement_workpacks
            signature = digest(
                {"market_space_id": str(space), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.creator_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变原固定工作包")
                return detail(c, context, old)
            now = datetime.now(UTC)
            if now >= registered["window_end"]:
                raise ProductWorkError("观察窗口已结束，不能补登记事前团队范围")
            protocol = registered["protocol"]
            if command.complexity_stratum not in protocol["complexity_strata"] or any(
                p.role_id not in protocol["role_ids"] for p in command.members
            ):
                raise ProductWorkError("主职责和复杂度须来自原观察协议已登记分层")
            for person in command.members:
                participant(c, context, space, line, person.user_id)
            basis = source(c, context, space, line, command.subject_kind, command.subject_id)
            series_id = UUID(str(basis["series_id"]))
            same = c.execute(
                select(t.c.id)
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.study_id == command.study_id,
                    t.c.subject_kind == command.subject_kind,
                    t.c.subject_series_id == series_id,
                    *(
                        []
                        if registered["evidence_kind"] == "real_business"
                        else [t.c.mode == command.mode]
                    ),
                )
                .limit(1)
            ).scalar_one_or_none()
            if same:
                raise ProductWorkError("该实际对象系列已有工作包，真实工作不能为比较重复提交")
            if registered["evidence_kind"] == "real_business":
                samples = tables.research_measurement_samples
                prior = c.execute(
                    select(samples.c.id)
                    .where(
                        samples.c.tenant_id == context.tenant.id,
                        samples.c.study_id == command.study_id,
                        samples.c.subject_kind == command.subject_kind,
                        samples.c.subject_series_id == series_id,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if prior:
                    raise ProductWorkError(
                        "原对象系列已有活动观察，不能事后转为预登记团队证明；个人历史继续保留"
                    )
            identity = uuid4()
            body = command.model_dump(mode="json", exclude={"request_id"})
            body.update(
                {
                    "subject_series_id": str(series_id),
                    "market_space_id": str(space),
                    "product_line_id": str(line) if line else None,
                    "scope_key": str(line or space),
                    "evidence_kind": registered["evidence_kind"],
                    "scenario_id": protocol["scenario_id"],
                }
            )
            foreign_keys = {
                column: command.subject_id if kind == command.subject_kind else None
                for kind, column in SUBJECT_COLUMNS.items()
            }
            pack = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        **scope_values(context, space, line),
                        study_id=command.study_id,
                        subject_kind=command.subject_kind,
                        subject_id=command.subject_id,
                        subject_series_id=series_id,
                        **foreign_keys,
                        mode=command.mode,
                        creator_user_id=context.user.id,
                        deliverer_user_id=command.deliverer_user_id,
                        receiver_user_id=command.receiver_user_id,
                        body=body,
                        source_snapshot=basis,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            for person in command.members:
                c.execute(
                    tables.research_measurement_workpack_members.insert().values(
                        id=uuid4(),
                        **scope_values(context, space, line),
                        workpack_id=identity,
                        user_id=person.user_id,
                        role_id=person.role_id,
                        first_use=person.first_use,
                    )
                )
            event(c, context, pack, identity, "workpack_registered")
            return detail(c, context, pack)

    def history(self, context: AuthContext, space: UUID, command: History) -> dict[str, Any]:
        with self.engine.connect() as c:
            registered = study(c, context, space, command.study_id)
            t, m = (
                tables.research_measurement_workpacks,
                tables.research_measurement_workpack_members,
            )
            conditions = [
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.study_id == command.study_id,
            ]
            if not manage(c, context, space, registered["product_line_id"]):
                conditions.append(
                    select(m.c.id)
                    .where(
                        m.c.tenant_id == t.c.tenant_id,
                        m.c.workpack_id == t.c.id,
                        m.c.user_id == context.user.id,
                    )
                    .exists()
                )
            if command.before_id:
                conditions.append(t.c.id < command.before_id)
            found = (
                c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for pack in found[:20]:
                try:
                    source(
                        c,
                        context,
                        space,
                        pack["product_line_id"],
                        pack["subject_kind"],
                        pack["subject_id"],
                    )
                    items.append(pack_item(c, pack))
                except (PermissionError, ProductWorkError):
                    continue
            return {
                "items": items,
                "next_before_id": str(found[19]["id"]) if len(found) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, command: Read) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            return detail(c, context, get_pack(c, context, space, command.workpack_id))

    def preview(
        self,
        context: AuthContext,
        space: UUID,
        command: DeliveryPreview | ReceptionPreview | ClosePreview,
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            pack = get_pack(c, context, space, command.workpack_id)
            if isinstance(command, DeliveryPreview):
                return delivery_preview(c, context, pack, command)
            if isinstance(command, ReceptionPreview):
                return reception_preview(c, context, pack, command)
            return closure_preview(c, context, pack, command)

    def deliver(self, context: AuthContext, space: UUID, command: DeliverySave) -> dict[str, Any]:
        with self.engine.begin() as c:
            pack = get_pack(c, context, space, command.workpack_id)
            authorize_scope(c, context, space, pack["product_line_id"], writable=True, lock=True)
            t = tables.research_measurement_deliveries
            if repeated(c, context, t, command, space):
                return detail(c, context, pack)
            prepared = delivery_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("原资料、同意或轮次已变化，请重新预览")
            identity = uuid4()
            foreign_keys = {
                column: command.subject_id if kind == pack["subject_kind"] else None
                for kind, column in SUBJECT_COLUMNS.items()
            }
            c.execute(
                t.insert().values(
                    id=identity,
                    **scope_values(context, space, pack["product_line_id"]),
                    study_id=pack["study_id"],
                    workpack_id=pack["id"],
                    round=prepared["delivery"]["round"],
                    actor_user_id=context.user.id,
                    receiver_user_id=pack["receiver_user_id"],
                    deliverer_consent_id=UUID(prepared["deliverer_consent_id"]),
                    receiver_consent_id=UUID(prepared["receiver_consent_id"]),
                    subject_kind=pack["subject_kind"],
                    subject_id=command.subject_id,
                    subject_series_id=pack["subject_series_id"],
                    **foreign_keys,
                    locator=command.locator,
                    description=command.description,
                    source_snapshot=prepared["source"],
                    source_digest=digest(prepared["source"]),
                    request_id=command.request_id,
                    request_digest=digest(
                        {"market_space_id": str(space), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, pack, identity, "delivered")
            return detail(c, context, pack)

    def receive(self, context: AuthContext, space: UUID, command: ReceptionSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            pack = get_pack(c, context, space, command.workpack_id)
            authorize_scope(c, context, space, pack["product_line_id"], writable=True, lock=True)
            t = tables.research_measurement_receptions
            if repeated(c, context, t, command, space):
                return detail(c, context, pack)
            prepared = reception_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("原交付、同意或资料已变化，请重新核对")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    **scope_values(context, space, pack["product_line_id"]),
                    study_id=pack["study_id"],
                    workpack_id=pack["id"],
                    delivery_id=command.delivery_id,
                    actor_user_id=context.user.id,
                    receiver_consent_id=UUID(prepared["receiver_consent_id"]),
                    decision=command.decision,
                    criteria_checked=command.criteria_checked,
                    reason=command.reason,
                    source_snapshot=prepared["source"],
                    source_digest=digest(prepared["source"]),
                    request_id=command.request_id,
                    request_digest=digest(
                        {"market_space_id": str(space), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, pack, identity, command.decision)
            return detail(c, context, pack)

    def close(self, context: AuthContext, space: UUID, command: Close) -> dict[str, Any]:
        with self.engine.begin() as c:
            pack = get_pack(c, context, space, command.workpack_id)
            authorize_scope(c, context, space, pack["product_line_id"], writable=True, lock=True)
            t = tables.research_measurement_closures
            if repeated(c, context, t, command, space):
                return detail(c, context, pack)
            prepared = closure_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("交付或接收已有变化，请重新预览")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    **scope_values(context, space, pack["product_line_id"]),
                    workpack_id=pack["id"],
                    actor_user_id=context.user.id,
                    outcome=command.outcome,
                    reason=command.reason,
                    request_id=command.request_id,
                    request_digest=digest(
                        {"market_space_id": str(space), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, pack, identity, command.outcome)
            return detail(c, context, pack)

    def summary(self, context: AuthContext, space: UUID, command: Read) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            pack = get_pack(c, context, space, command.workpack_id)
            return {
                "workpack": pack_item(c, pack),
                "summary": workpack_summary(**summary_entry(c, context, pack)),
            }

    def study_summary(self, context: AuthContext, space: UUID, command: History) -> dict[str, Any]:
        if command.before_id:
            raise ProductWorkError("协议汇总不能使用局部分页作为全量结果")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            registered = study(c, context, space, command.study_id)
            authorize_scope(c, context, space, registered["product_line_id"], access="manager")
            t = tables.research_measurement_workpacks
            found = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space,
                        t.c.study_id == command.study_id,
                    )
                    .order_by(t.c.id)
                    .limit(1001)
                )
                .mappings()
                .all()
            )
            if len(found) > 1000:
                raise ProductWorkError("本协议超过1000个团队工作包，未输出局部汇总")
            return {
                "study_id": str(command.study_id),
                "summary": workpack_study_summary(
                    [summary_entry(c, context, pack) for pack in found]
                ),
                "as_of": datetime.now(UTC).isoformat(),
            }
