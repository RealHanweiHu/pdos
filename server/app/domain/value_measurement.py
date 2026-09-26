"""Preregistered studies and explicit, append-only participant-owned capture."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.value_measurement import (
    Consent,
    Options,
    SampleDraft,
    SampleHistory,
    SampleRead,
    SampleSave,
    StudyCreate,
    StudyHistory,
    StudyProtocol,
    Summary,
)
from app.db.schema import tables
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_operations import authorize
from app.domain.value_measurement_calculations import sample_summary, study_summary
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

IDENTITY_KEYS = (
    "study_id",
    "sample_id",
    "task_id",
    "role_id",
    "complexity_stratum",
    "mode",
    "pair_key",
    "matching_basis",
    "first_use",
    "workflow_version",
    "started_at",
)


def permitted(c: Connection, context: AuthContext, project: UUID, action: Action) -> bool:
    try:
        authorize(c, context, project, action)
    except PermissionError:
        return False
    return True


def member(c: Connection, context: AuthContext, project: UUID) -> None:
    """Even tenant administrators must join a project before recording own activity."""
    authorize(c, context, project, Action.PROJECT_VIEW)
    t = tables.project_members
    if (
        c.execute(
            select(t.c.id).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.user_id == context.user.id,
            )
        ).scalar_one_or_none()
        is None
    ):
        raise ProductWorkError("须先成为项目实际成员，才能登记本人同意或活动")


def lock(c: Connection, context: AuthContext, project: UUID) -> None:
    if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
        raise ProductWorkError("项目不可用")


def event(c: Connection, context: AuthContext, project: UUID, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"value-measurement:{identity}:{action}",
            event_type="VALUE_MEASUREMENT_RECORDED",
            source="value_measurement_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"value_measurement.{action}",
            after_snapshot={"record_id": str(identity), "action": action},
        ),
    )


def study(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> Any:
    authorize(c, context, project, Action.PROJECT_VIEW)
    t = tables.value_measurement_studies
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
        raise ProductWorkError("观察协议不存在或不属于此项目")
    return row


def current_consent(c: Connection, tenant: UUID, identity: UUID, user: UUID) -> Any:
    t = tables.value_measurement_consents
    return (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant, t.c.study_id == identity, t.c.participant_user_id == user
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def study_item(c: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    consent = current_consent(c, context.tenant.id, row["id"], context.user.id)
    return {
        "id": str(row["id"]),
        "protocol": row["protocol"],
        "protocol_digest": row["protocol_digest"],
        "created_at": row["created_at"].isoformat(),
        "my_consent": _plain(consent) if consent else None,
    }


def source(
    c: Connection, context: AuthContext, project: UUID, task_id: UUID, document_id: UUID | None
) -> dict[str, Any]:
    authorize(c, context, project, Action.WORK_ITEM_VIEW)
    t = tables.tasks
    task = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == task_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if task is None:
        raise ProductWorkError("所选任务不属于本项目或已经不可用")
    document = None
    if document_id:
        authorize(c, context, project, Action.DOCUMENT_ANALYZE)
        d = tables.documents
        row = (
            c.execute(
                select(d).where(
                    d.c.tenant_id == context.tenant.id,
                    d.c.project_id == project,
                    d.c.id == document_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("证据文件不存在或不属于本项目")
        document = _plain(
            {
                k: row[k]
                for k in ("id", "filename", "sha256", "classification", "size_bytes", "created_at")
            }
        )
    return {
        "task": _plain(
            {
                k: task[k]
                for k in (
                    "id",
                    "title",
                    "status",
                    "assignee_user_id",
                    "expected_output",
                    "completion_evidence_ref",
                    "created_at",
                    "updated_at",
                )
            }
        ),
        "document": document,
    }


def latest_sample(c: Connection, tenant: UUID, identity: UUID) -> Any:
    t = tables.value_measurement_samples
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.sample_id == identity)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def sample_access(c: Connection, context: AuthContext, project: UUID, row: Any) -> None:
    authorize(c, context, project, Action.PROJECT_VIEW)
    if row["tenant_id"] != context.tenant.id or row["project_id"] != project:
        raise PermissionError("观察记录不在当前项目")
    if row["participant_user_id"] != context.user.id:
        authorize(c, context, project, Action.PROJECT_EDIT)
        consent = current_consent(c, context.tenant.id, row["study_id"], row["participant_user_id"])
        if (
            consent is None
            or consent["status"] != "consented"
            or consent["id"] != row["consent_id"]
        ):
            raise PermissionError("本人已停止这批记录的项目内披露")
        FindingService._authorize_user(
            c,
            tenant_id=context.tenant.id,
            project_id=project,
            user_id=row["participant_user_id"],
            action=Action.WORK_ITEM_VIEW,
        )
        if row["evidence_document_id"]:
            FindingService._authorize_user(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                user_id=row["participant_user_id"],
                action=Action.DOCUMENT_ANALYZE,
            )
        pm = tables.project_members
        if (
            c.execute(
                select(pm.c.id).where(
                    pm.c.tenant_id == context.tenant.id,
                    pm.c.project_id == project,
                    pm.c.user_id == row["participant_user_id"],
                )
            ).scalar_one_or_none()
            is None
        ):
            raise PermissionError("参与者已不属于项目")


def sample_item(c: Connection, context: AuthContext, project: UUID, row: Any) -> dict[str, Any]:
    sample_access(c, context, project, row)
    now = source(c, context, project, row["task_id"], row["evidence_document_id"])
    return {
        "id": str(row["id"]),
        "sample_id": str(row["sample_id"]),
        "version": row["version"],
        "draft": row["body"],
        "source": row["source_snapshot"],
        "current_source": now,
        "source_changed": digest(now) != row["source_digest"],
        "summary": sample_summary(row["body"]),
        "created_at": row["created_at"].isoformat(),
        "reason": row["reason"],
    }


def draft_body(command: SampleDraft) -> dict[str, Any]:
    return command.model_dump(mode="json", exclude={"request_id", "expected_digest", "reason"})


def preview(
    c: Connection, context: AuthContext, project: UUID, command: SampleDraft
) -> dict[str, Any]:
    member(c, context, project)
    protocol_row = study(c, context, project, command.study_id)
    protocol = StudyProtocol.model_validate(protocol_row["protocol"])
    consent = current_consent(c, context.tenant.id, command.study_id, context.user.id)
    if consent is None or consent["status"] != "consented":
        raise ProductWorkError("请先由本人明确同意本协议的活动登记及项目内汇总用途")
    now = datetime.now(UTC)
    if command.as_of > now:
        raise ProductWorkError("观察截点不能晚于现在")
    if not protocol.window_start <= command.started_at < protocol.window_end:
        raise ProductWorkError("样本开始须位于已登记的左闭右开观察窗口")
    if (
        command.role_id not in protocol.role_ids
        or command.complexity_stratum not in protocol.complexity_strata
    ):
        raise ProductWorkError("职责和复杂度须采用原协议已登记分层")
    if command.excluded_rule_id and command.excluded_rule_id not in {
        r.rule_id for r in protocol.exclusion_rules
    }:
        raise ProductWorkError("排除仅能使用原协议预登记规则，失败或耗时较长不能自行删除")
    basis = source(c, context, project, command.task_id, command.evidence_document_id)
    if protocol.evidence_kind == "real_business":
        if command.started_at < max(protocol_row["created_at"], consent["created_at"]):
            raise ProductWorkError(
                "真实活动开始前须已有协议及本人的当前同意；历史办理请使用独立回放协议"
            )
        if datetime.fromisoformat(basis["task"]["created_at"]) > command.started_at:
            raise ProductWorkError("真实样本开始不能早于原任务登记")
    old = latest_sample(c, context.tenant.id, command.sample_id)
    body = draft_body(command)
    if old:
        if (
            old["project_id"] != project
            or old["participant_user_id"] != context.user.id
            or old["study_id"] != command.study_id
        ):
            raise PermissionError("只能修订本人在此协议下的记录")
        if old["version"] != command.expected_version:
            raise ProductWorkError("样本已有新版本，请重新读取")
        if any(body[key] != old["body"].get(key) for key in IDENTITY_KEYS):
            raise ProductWorkError("原任务、配对、分层和流程身份固定；修订保留原观察口径")
        if command.as_of < datetime.fromisoformat(old["body"]["as_of"]):
            raise ProductWorkError("新版本观察截点不能回到原版本之前")
    elif command.expected_version != 0:
        raise ProductWorkError("未找到原样本，首次登记版本须为零")
    t = tables.value_measurement_samples
    other = c.execute(
        select(t.c.sample_id)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.study_id == command.study_id,
            t.c.participant_user_id == context.user.id,
            t.c.task_id == command.task_id,
            t.c.sample_id != command.sample_id,
            *([] if protocol.evidence_kind == "real_business" else [t.c.mode == command.mode]),
        )
        .limit(1)
    ).scalar_one_or_none()
    if other is not None:
        raise ProductWorkError("同一任务的已有观察请继续修订，不能把重试登记为新的独立任务")
    body.update(
        {
            "participant_user_id": str(context.user.id),
            "evidence_kind": protocol.evidence_kind,
            "scenario_id": protocol.scenario_id,
        }
    )
    body["segments"] = [
        {**s, "participant_user_id": str(context.user.id)} for s in body["segments"]
    ]
    signature = digest(
        {
            "project_id": str(project),
            "protocol_digest": protocol_row["protocol_digest"],
            "consent_id": str(consent["id"]),
            "body": body,
            "source": basis,
        }
    )
    return {
        "digest": signature,
        "draft": body,
        "source": basis,
        "summary": sample_summary(body),
        "consent_id": str(consent["id"]),
    }


class ValueMeasurementService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project: UUID, command: Options) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, context, project, Action.PROJECT_VIEW)
            result: dict[str, Any] = {
                "can_manage": permitted(c, context, project, Action.PROJECT_EDIT),
                "participant_user_id": str(context.user.id),
            }
            for name, t, label, action, before in (
                ("tasks", tables.tasks, "title", Action.WORK_ITEM_VIEW, command.task_before_id),
                (
                    "documents",
                    tables.documents,
                    "filename",
                    Action.DOCUMENT_ANALYZE,
                    command.document_before_id,
                ),
            ):
                singular = "task" if name == "tasks" else "document"
                if not permitted(c, context, project, action):
                    result[name], result[f"next_{singular}_before_id"] = [], None
                    continue
                columns = (
                    [t.c.id, t.c[label], t.c.status]
                    if name == "tasks"
                    else [t.c.id, t.c[label], t.c.sha256]
                )
                conditions = [t.c.tenant_id == context.tenant.id, t.c.project_id == project]
                if before:
                    conditions.append(t.c.id < before)
                if command.query:
                    conditions.append(t.c[label].icontains(command.query, autoescape=True))
                rows = (
                    c.execute(select(*columns).where(*conditions).order_by(t.c.id.desc()).limit(31))
                    .mappings()
                    .all()
                )
                result[name] = [_plain(r) for r in rows[:30]]
                result[f"next_{singular}_before_id"] = (
                    str(rows[29]["id"]) if len(rows) > 30 else None
                )
            return result

    def create_study(
        self, context: AuthContext, project: UUID, command: StudyCreate
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            authorize(c, context, project, Action.PROJECT_EDIT)
            lock(c, context, project)
            t = tables.value_measurement_studies
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
                    raise ProductWorkError("同一请求不能改写观察协议")
                return study_item(c, context, old)
            now = datetime.now(UTC)
            if command.evidence_kind == "real_business" and command.window_start <= now:
                raise ProductWorkError(
                    "真实业务观察窗口须在协议登记之后开始，历史资料请另建受控回放协议"
                )
            protocol = command.model_dump(mode="json", exclude={"request_id"})
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        creator_user_id=context.user.id,
                        title=command.title,
                        protocol=protocol,
                        protocol_digest=digest(protocol),
                        evidence_kind=command.evidence_kind,
                        window_start=command.window_start,
                        window_end=command.window_end,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, context, project, identity, "study_registered")
            return study_item(c, context, row)

    def studies(self, context: AuthContext, project: UUID, command: StudyHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, context, project, Action.PROJECT_VIEW)
            t = tables.value_measurement_studies
            conditions = [t.c.tenant_id == context.tenant.id, t.c.project_id == project]
            if command.before_id:
                conditions.append(t.c.id < command.before_id)
            rows = (
                c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [study_item(c, context, r) for r in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def consent(self, context: AuthContext, project: UUID, command: Consent) -> dict[str, Any]:
        with self.engine.begin() as c:
            member(c, context, project)
            lock(c, context, project)
            row = study(c, context, project, command.study_id)
            t = tables.value_measurement_consents
            signature = digest(
                {"project_id": str(project), "command": command.model_dump(mode="json")}
            )
            repeated = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.participant_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if repeated:
                if repeated["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变本人同意记录")
                return study_item(c, context, row)
            old = current_consent(c, context.tenant.id, command.study_id, context.user.id)
            version = old["version"] if old else 0
            if command.expected_version != version:
                raise ProductWorkError("本人同意状态已变化，请重新读取")
            if old and old["status"] == command.status:
                raise ProductWorkError("本人已处于此状态；变更用途须另行登记新协议")
            if old is None and command.status == "withdrawn":
                raise ProductWorkError("尚未同意此协议")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    study_id=command.study_id,
                    participant_user_id=context.user.id,
                    version=version + 1,
                    status=command.status,
                    activity_and_aggregate_use_confirmed=command.activity_and_aggregate_use_confirmed,
                    reason=command.reason,
                    request_id=command.request_id,
                    request_digest=signature,
                    created_at=datetime.now(UTC),
                )
            )
            event(c, context, project, identity, command.status)
            return study_item(c, context, row)

    def preview(self, context: AuthContext, project: UUID, command: SampleDraft) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            return preview(c, context, project, command)

    def save(self, context: AuthContext, project: UUID, command: SampleSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            member(c, context, project)
            lock(c, context, project)
            t = tables.value_measurement_samples
            signature = digest(
                {"project_id": str(project), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.participant_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变观察记录")
                return sample_item(c, context, project, old)
            prepared = preview(c, context, project, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("协议、同意、活动或原资料已变化，请重新预览")
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        study_id=command.study_id,
                        sample_id=command.sample_id,
                        version=command.expected_version + 1,
                        participant_user_id=context.user.id,
                        consent_id=UUID(prepared["consent_id"]),
                        task_id=command.task_id,
                        evidence_document_id=command.evidence_document_id,
                        mode=command.mode,
                        body=prepared["draft"],
                        source_snapshot=prepared["source"],
                        source_digest=digest(prepared["source"]),
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, context, project, identity, "sample_recorded")
            return sample_item(c, context, project, row)

    @staticmethod
    def _latest_query(context: AuthContext, project: UUID, study_id: UUID) -> Any:
        t = tables.value_measurement_samples
        ranked = (
            select(
                t,
                func.row_number()
                .over(partition_by=t.c.sample_id, order_by=t.c.version.desc())
                .label("ordinal"),
            )
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.study_id == study_id,
            )
            .subquery()
        )
        return ranked

    def history(
        self, context: AuthContext, project: UUID, command: SampleHistory
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            study(c, context, project, command.study_id)
            t = self._latest_query(context, project, command.study_id)
            conditions = [t.c.ordinal == 1]
            if not permitted(c, context, project, Action.PROJECT_EDIT):
                conditions.append(t.c.participant_user_id == context.user.id)
            if command.before_id:
                conditions.append(t.c.id < command.before_id)
            rows = (
                c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for row in rows[:20]:
                try:
                    items.append(sample_item(c, context, project, row))
                except (PermissionError, ProductWorkError):
                    continue
            return {
                "items": items,
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def read(self, context: AuthContext, project: UUID, command: SampleRead) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            row = latest_sample(c, context.tenant.id, command.sample_id)
            if row is None:
                raise ProductWorkError("未找到观察记录")
            item = sample_item(c, context, project, row)
            t = tables.value_measurement_samples
            conditions = [
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.sample_id == command.sample_id,
            ]
            if command.before_version:
                conditions.append(t.c.version < command.before_version)
            rows = (
                c.execute(select(t).where(*conditions).order_by(t.c.version.desc()).limit(21))
                .mappings()
                .all()
            )
            history = []
            for old in rows[:20]:
                try:
                    history.append(sample_item(c, context, project, old))
                except (PermissionError, ProductWorkError):
                    continue
            return {
                "item": item,
                "history": history,
                "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
            }

    def summary(self, context: AuthContext, project: UUID, command: Summary) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            protocol = study(c, context, project, command.study_id)
            manager = permitted(c, context, project, Action.PROJECT_EDIT)
            t = self._latest_query(context, project, command.study_id)
            conditions = [t.c.ordinal == 1]
            if not manager:
                conditions.append(t.c.participant_user_id == context.user.id)
            rows = c.execute(select(t).where(*conditions).limit(10001)).mappings().all()
            if len(rows) > 10000:
                raise ProductWorkError(
                    "本协议超过一次可核对的10000条观察，请使用更小预登记观察窗口；未输出局部总计"
                )
            included = []
            unavailable = excluded = source_changed = 0
            for row in rows:
                consent = current_consent(
                    c, context.tenant.id, row["study_id"], row["participant_user_id"]
                )
                if (
                    consent is None
                    or consent["status"] != "consented"
                    or consent["id"] != row["consent_id"]
                ):
                    unavailable += 1
                    continue
                try:
                    item = sample_item(c, context, project, row)
                except (PermissionError, ProductWorkError):
                    unavailable += 1
                    continue
                if item["source_changed"]:
                    source_changed += 1
                if row["body"].get("excluded_rule_id"):
                    excluded += 1
                else:
                    included.append(row["body"])
            return {
                "study": study_item(c, context, protocol),
                "summary": study_summary(included),
                "excluded_count": excluded,
                "unavailable_count": unavailable,
                "source_changed_count": source_changed,
                "registered_latest_count": len(rows),
                "scope": "all_consenting" if manager else "own",
                "as_of": datetime.now(UTC).isoformat(),
                "limitation": (
                    "本人活动自报；未计算完整多人流程净投入、独立下游接收率或验收收益。"
                    "撤回或原资料权限收回的记录不进入当前汇总；原任务后续进展单列，"
                    "历史投入仍按当时保存值计算。"
                ),
            }
