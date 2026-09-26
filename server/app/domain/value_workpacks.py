"""Registered team scope with personal observations and independent reception receipts."""

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.value_measurement import Options as SampleOptions
from app.contracts.value_workpacks import (
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
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize
from app.domain.value_measurement import (
    ValueMeasurementService,
    current_consent,
    lock,
    permitted,
    sample_item,
    source,
    study,
)
from app.domain.value_workpack_calculations import workpack_study_summary, workpack_summary
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def event(c: Connection, context: AuthContext, project: UUID, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"value-workpack:{identity}:{action}",
            event_type="VALUE_WORKPACK_RECORDED",
            source="value_workpack_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"value_workpack.{action}",
            after_snapshot={"record_id": str(identity), "action": action},
        ),
    )


def person(
    c: Connection, context: AuthContext, project: UUID, user: UUID, *, documents: bool = False
) -> Any:
    for action in (
        Action.PROJECT_VIEW,
        Action.WORK_ITEM_VIEW,
        *([Action.DOCUMENT_ANALYZE] if documents else []),
    ):
        FindingService._authorize_user(
            c, tenant_id=context.tenant.id, project_id=project, user_id=user, action=action
        )
    m, u = tables.project_members, tables.users
    row = (
        c.execute(
            select(u.c.id, u.c.display_name)
            .select_from(m.join(u, (u.c.tenant_id == m.c.tenant_id) & (u.c.id == m.c.user_id)))
            .where(
                m.c.tenant_id == context.tenant.id,
                m.c.project_id == project,
                m.c.user_id == user,
                u.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise PermissionError("参与者须为当前项目实际有效成员")
    return row


def grant(
    c: Connection,
    context: AuthContext,
    pack: Any,
    user: UUID,
    *,
    expected: UUID | None = None,
    documents: bool = False,
) -> Any:
    person(c, context, pack["project_id"], user, documents=documents)
    row = current_consent(c, context.tenant.id, pack["study_id"], user)
    if (
        row is None
        or row["status"] != "consented"
        or expected is not None
        and row["id"] != expected
    ):
        raise PermissionError("本人尚未同意或已撤回这批资料的测量披露")
    return row


def get_pack(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> Any:
    authorize(c, context, project, Action.WORK_ITEM_VIEW)
    t = tables.value_measurement_workpacks
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("未找到本项目工作包")
    if not permitted(c, context, project, Action.PROJECT_EDIT):
        m = tables.value_measurement_workpack_members
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
            raise PermissionError("仅登记的参与者或项目管理人员可读取工作包")
    return row


def members(c: Connection, pack: Any) -> list[dict[str, Any]]:
    m, u = tables.value_measurement_workpack_members, tables.users
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
    return [_plain(r) for r in rows]


def pack_item(c: Connection, pack: Any) -> dict[str, Any]:
    return {
        **_plain(
            {
                k: pack[k]
                for k in (
                    "id",
                    "study_id",
                    "task_id",
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
    ds = rows(c, tables.value_measurement_deliveries, pack)
    rs = rows(c, tables.value_measurement_receptions, pack)
    cs = rows(c, tables.value_measurement_closures, pack)
    return ds, rs, cs[0] if cs else None


def active_window(c: Connection, context: AuthContext, pack: Any) -> Any:
    protocol = study(c, context, pack["project_id"], pack["study_id"])
    now = datetime.now(UTC)
    if not protocol["window_start"] <= now < protocol["window_end"]:
        raise ProductWorkError("具名交付、接收或终止须发生在原观察窗口内；不能倒填历史事件")
    return protocol


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
            documents=True,
        )
        grant(
            c,
            context,
            pack,
            row["receiver_user_id"],
            expected=row["receiver_consent_id"],
            documents=True,
        )
    elif context.user.id == row["receiver_user_id"]:
        grant(
            c,
            context,
            pack,
            row["actor_user_id"],
            expected=row["deliverer_consent_id"],
            documents=True,
        )
    current = source(c, context, pack["project_id"], pack["task_id"], row["document_id"])
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "round",
                    "document_id",
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
            documents=True,
        )
        grant(
            c,
            context,
            pack,
            delivery["actor_user_id"],
            expected=delivery["deliverer_consent_id"],
            documents=True,
        )
    current = source(c, context, pack["project_id"], pack["task_id"], delivery["document_id"])
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
        "source_changed": digest(current) != row["source_digest"],
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
    t = ValueMeasurementService._latest_query(context, pack["project_id"], pack["study_id"])
    return list(
        c.execute(
            select(t).where(
                t.c.ordinal == 1, t.c.task_id == pack["task_id"], t.c.mode == pack["mode"]
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
    manager = permitted(c, context, pack["project_id"], Action.PROJECT_EDIT)
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
                own.append(sample_item(c, context, pack["project_id"], row))
    last = ds[-1] if ds else None
    decision = next((r for r in rs if last and r["delivery_id"] == last["id"]), None)
    manager = permitted(c, context, pack["project_id"], Action.PROJECT_EDIT)
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
        raise PermissionError("只能由登记的实际交付人提交")
    sender = grant(c, context, pack, pack["deliverer_user_id"], documents=True)
    receiver = grant(c, context, pack, pack["receiver_user_id"], documents=True)
    ds, rs, closed = state(c, pack)
    if closed:
        raise ProductWorkError("工作包已具名终止")
    latest = ds[-1] if ds else None
    latest_response = next((r for r in rs if latest and r["delivery_id"] == latest["id"]), None)
    if latest and (latest_response is None or latest_response["decision"] != "returned"):
        raise ProductWorkError("上一轮须由接收人退回后才能提交新轮次，待接收或已接受不能重复交付")
    if len(ds) >= 100:
        raise ProductWorkError("同一工作包已达到100轮记录上限；原记录保留")
    basis = source(c, context, pack["project_id"], pack["task_id"], command.document_id)
    proposed = {
        "round": (latest["round"] + 1) if latest else 1,
        "document_id": str(command.document_id),
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
        "deliverer_consent_id": str(sender["id"]),
        "receiver_consent_id": str(receiver["id"]),
    }


def reception_preview(
    c: Connection, context: AuthContext, pack: Any, command: ReceptionPreview
) -> dict[str, Any]:
    active_window(c, context, pack)
    if context.user.id != pack["receiver_user_id"]:
        raise PermissionError("只能由登记的独立下游接收人记录裁决")
    ds, rs, closed = state(c, pack)
    if (
        closed
        or not ds
        or ds[-1]["id"] != command.delivery_id
        or any(r["delivery_id"] == command.delivery_id for r in rs)
    ):
        raise ProductWorkError("须办理当前未接收轮次，已结束或已有裁决的回执不能改写")
    delivery = ds[-1]
    grant(
        c,
        context,
        pack,
        delivery["actor_user_id"],
        expected=delivery["deliverer_consent_id"],
        documents=True,
    )
    receiver = grant(
        c, context, pack, context.user.id, expected=delivery["receiver_consent_id"], documents=True
    )
    basis = source(c, context, pack["project_id"], pack["task_id"], delivery["document_id"])
    if any(
        basis["document"][k] != delivery["source_snapshot"]["document"][k]
        for k in ("id", "sha256", "size_bytes")
    ):
        raise ProductWorkError("实际交付文件内容已变化，不能对其他版本补记接收")
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
        "receiver_consent_id": str(receiver["id"]),
    }


def closure_preview(
    c: Connection, context: AuthContext, pack: Any, command: ClosePreview
) -> dict[str, Any]:
    active_window(c, context, pack)
    if context.user.id != pack["deliverer_user_id"] and not permitted(
        c, context, pack["project_id"], Action.PROJECT_EDIT
    ):
        raise PermissionError("仅原交付人或项目管理人员可登记失败或取消")
    ds, rs, closed = state(c, pack)
    if closed or any(r["decision"] == "accepted" for r in rs):
        raise ProductWorkError("已结束或已被独立接受的工作包不能另行登记失败或取消")
    proposed = command.model_dump(mode="json", exclude={"request_id", "expected_digest"})
    return {
        "digest": digest(
            {
                "workpack": str(pack["id"]),
                "closure": proposed,
                "deliveries": [str(r["id"]) for r in ds],
                "receptions": [str(r["id"]) for r in rs],
            }
        ),
        "workpack": pack_item(c, pack),
        "closure": proposed,
    }


def repeated(c: Connection, context: AuthContext, table: Any, command: Any, project: UUID) -> bool:
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
            {"project_id": str(project), "command": command.model_dump(mode="json")}
        ):
            raise ProductWorkError("同一请求不能改变原具名记录")
        return True
    return False


def summary_entry(c: Connection, context: AuthContext, pack: Any) -> dict[str, Any]:
    authorize(c, context, pack["project_id"], Action.PROJECT_EDIT)
    roster = members(c, pack)
    samples, delivered, received = [], [], []
    ds, rs, closed = state(c, pack)
    unavailable = 0
    for row in sample_rows(c, context, pack):
        if not matches(pack, row["body"], roster):
            continue
        try:
            grant(
                c,
                context,
                pack,
                row["participant_user_id"],
                expected=row["consent_id"],
                documents=bool(row["evidence_document_id"]),
            )
            observed = sample_item(c, context, pack["project_id"], row)
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


class ValueWorkpackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project: UUID, command: Options) -> dict[str, Any]:
        result = ValueMeasurementService(self.engine).options(
            context,
            project,
            SampleOptions.model_validate(
                command.model_dump(exclude={"study_id", "user_before_id"})
            ),
        )
        with self.engine.connect() as c:
            study(c, context, project, command.study_id)
            result.update({"users": [], "next_user_before_id": None})
            if result["can_manage"]:
                m, u = tables.project_members, tables.users
                conditions = [
                    m.c.tenant_id == context.tenant.id,
                    m.c.project_id == project,
                    u.c.is_active.is_(True),
                ]
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
                result["users"] = [_plain(r) for r in found[:30]]
                result["next_user_before_id"] = str(found[29]["id"]) if len(found) > 30 else None
        return result

    def create(
        self, context: AuthContext, project: UUID, command: WorkpackCreate
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            authorize(c, context, project, Action.PROJECT_EDIT)
            lock(c, context, project)
            protocol = study(c, context, project, command.study_id)
            t = tables.value_measurement_workpacks
            signature = digest(
                {"project_id": str(project), "command": command.model_dump(mode="json")}
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
            if now >= protocol["window_end"]:
                raise ProductWorkError("观察窗口已结束，不能补登记事前团队范围")
            if command.complexity_stratum not in protocol["protocol"]["complexity_strata"] or any(
                p.role_id not in protocol["protocol"]["role_ids"] for p in command.members
            ):
                raise ProductWorkError("团队职责和复杂度须来自原观察协议分层")
            for participant in command.members:
                person(c, context, project, participant.user_id)
            basis = source(c, context, project, command.task_id, None)
            same = c.execute(
                select(t.c.id)
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.study_id == command.study_id,
                    t.c.task_id == command.task_id,
                    *(
                        []
                        if protocol["evidence_kind"] == "real_business"
                        else [t.c.mode == command.mode]
                    ),
                )
                .limit(1)
            ).scalar_one_or_none()
            if same:
                raise ProductWorkError("原任务已有固定工作包，真实业务任务不能为比较重复提交")
            if protocol["evidence_kind"] == "real_business":
                s = tables.value_measurement_samples
                prior = c.execute(
                    select(s.c.id)
                    .where(
                        s.c.tenant_id == context.tenant.id,
                        s.c.study_id == command.study_id,
                        s.c.task_id == command.task_id,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if prior:
                    raise ProductWorkError(
                        "原任务已有活动观察，不能事后变成预登记团队证明；个人历史继续保留"
                    )
            identity = uuid4()
            body = command.model_dump(mode="json", exclude={"request_id"})
            body.update(
                {
                    "evidence_kind": protocol["evidence_kind"],
                    "scenario_id": protocol["protocol"]["scenario_id"],
                }
            )
            pack = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        study_id=command.study_id,
                        task_id=command.task_id,
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
            for participant in command.members:
                c.execute(
                    tables.value_measurement_workpack_members.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        workpack_id=identity,
                        user_id=participant.user_id,
                        role_id=participant.role_id,
                        first_use=participant.first_use,
                    )
                )
            event(c, context, project, identity, "workpack_registered")
            return detail(c, context, pack)

    def history(self, context: AuthContext, project: UUID, command: History) -> dict[str, Any]:
        with self.engine.connect() as c:
            study(c, context, project, command.study_id)
            authorize(c, context, project, Action.WORK_ITEM_VIEW)
            t, m = tables.value_measurement_workpacks, tables.value_measurement_workpack_members
            conditions = [
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.study_id == command.study_id,
            ]
            if not permitted(c, context, project, Action.PROJECT_EDIT):
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
            return {
                "items": [pack_item(c, p) for p in found[:20]],
                "next_before_id": str(found[19]["id"]) if len(found) > 20 else None,
            }

    def read(self, context: AuthContext, project: UUID, command: Read) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            return detail(c, context, get_pack(c, context, project, command.workpack_id))

    def preview(
        self,
        context: AuthContext,
        project: UUID,
        command: DeliveryPreview | ReceptionPreview | ClosePreview,
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            pack = get_pack(c, context, project, command.workpack_id)
            if isinstance(command, DeliveryPreview):
                return delivery_preview(c, context, pack, command)
            if isinstance(command, ReceptionPreview):
                return reception_preview(c, context, pack, command)
            return closure_preview(c, context, pack, command)

    def deliver(self, context: AuthContext, project: UUID, command: DeliverySave) -> dict[str, Any]:
        with self.engine.begin() as c:
            lock(c, context, project)
            pack = get_pack(c, context, project, command.workpack_id)
            t = tables.value_measurement_deliveries
            if repeated(c, context, t, command, project):
                return detail(c, context, pack)
            prepared = delivery_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("原资料、同意或轮次已变化，请重新预览")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    study_id=pack["study_id"],
                    workpack_id=pack["id"],
                    round=prepared["delivery"]["round"],
                    actor_user_id=context.user.id,
                    receiver_user_id=pack["receiver_user_id"],
                    deliverer_consent_id=UUID(prepared["deliverer_consent_id"]),
                    receiver_consent_id=UUID(prepared["receiver_consent_id"]),
                    document_id=command.document_id,
                    locator=command.locator,
                    description=command.description,
                    source_snapshot=prepared["source"],
                    source_digest=digest(prepared["source"]),
                    request_id=command.request_id,
                    request_digest=digest(
                        {"project_id": str(project), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, project, identity, "delivered")
            return detail(c, context, pack)

    def receive(
        self, context: AuthContext, project: UUID, command: ReceptionSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            lock(c, context, project)
            pack = get_pack(c, context, project, command.workpack_id)
            t = tables.value_measurement_receptions
            if repeated(c, context, t, command, project):
                return detail(c, context, pack)
            prepared = reception_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("原交付、同意或资料已变化，请重新核对")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
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
                        {"project_id": str(project), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, project, identity, command.decision)
            return detail(c, context, pack)

    def close(self, context: AuthContext, project: UUID, command: Close) -> dict[str, Any]:
        with self.engine.begin() as c:
            lock(c, context, project)
            pack = get_pack(c, context, project, command.workpack_id)
            t = tables.value_measurement_closures
            if repeated(c, context, t, command, project):
                return detail(c, context, pack)
            prepared = closure_preview(c, context, pack, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("交付或接收已有变化，请重新预览")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    workpack_id=pack["id"],
                    actor_user_id=context.user.id,
                    outcome=command.outcome,
                    reason=command.reason,
                    request_id=command.request_id,
                    request_digest=digest(
                        {"project_id": str(project), "command": command.model_dump(mode="json")}
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, project, identity, command.outcome)
            return detail(c, context, pack)

    def summary(self, context: AuthContext, project: UUID, command: Read) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            pack = get_pack(c, context, project, command.workpack_id)
            entry = summary_entry(c, context, pack)
            return {"workpack": pack_item(c, pack), "summary": workpack_summary(**entry)}

    def study_summary(
        self, context: AuthContext, project: UUID, command: History
    ) -> dict[str, Any]:
        if command.before_id:
            raise ProductWorkError("协议汇总不能使用局部分页作为全量结果")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            authorize(c, context, project, Action.PROJECT_EDIT)
            study(c, context, project, command.study_id)
            t = tables.value_measurement_workpacks
            found = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
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
            entries = [summary_entry(c, context, p) for p in found]
            return {
                "study_id": str(command.study_id),
                "summary": workpack_study_summary(entries),
                "as_of": datetime.now(UTC).isoformat(),
            }
