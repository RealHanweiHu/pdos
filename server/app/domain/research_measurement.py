"""Participant measurements in genuine product-research scope, without a Project."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.research_measurement import (
    Consent,
    Options,
    SampleDraft,
    SampleHistory,
    SampleRead,
    SampleSave,
    StudyCreate,
    StudyHistory,
    Summary,
)
from app.contracts.value_measurement import StudyProtocol
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.research_measurement_calculations import sample_summary, study_summary
from app.domain.research_measurement_sources import (
    authorize_scope,
    participant,
    source,
    source_options,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

IDENTITY_KEYS = (
    "study_id",
    "sample_id",
    "subject_kind",
    "subject_id",
    "role_id",
    "complexity_stratum",
    "mode",
    "pair_key",
    "matching_basis",
    "first_use",
    "workflow_version",
    "started_at",
)
SUBJECT_COLUMNS = {
    "research_task": "research_task_id",
    "scoped_work_item": "scoped_work_item_id",
    "opportunity": "opportunity_id",
    "strategy": "strategy_id",
    "definition": "definition_id",
}


def scope_values(context: AuthContext, space: UUID, line: UUID | None) -> dict[str, Any]:
    return {
        "tenant_id": context.tenant.id,
        "market_space_id": space,
        "product_line_id": line,
        "scope_key": line or space,
    }


def manage(c: Connection, context: AuthContext, space: UUID, line: UUID | None) -> bool:
    try:
        authorize_scope(c, context, space, line, access="manager")
    except PermissionError:
        return False
    return True


def event(c: Connection, context: AuthContext, study_row: Any, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=None
    ).record(
        EventDraft(
            event_id=f"research-measurement:{identity}:{action}",
            event_type="RESEARCH_MEASUREMENT_RECORDED",
            source="research_measurement_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"research_measurement.{action}",
            after_snapshot={"record_id": str(identity), "action": action},
            context={
                "market_space_id": str(study_row["market_space_id"]),
                "scope_key": str(study_row["scope_key"]),
            },
        ),
    )


def study(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> Any:
    t = tables.research_measurement_studies
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
        raise ProductWorkError("未找到当前市场空间中的观察协议")
    authorize_scope(c, context, space, row["product_line_id"])
    return row


def current_consent(c: Connection, tenant: UUID, identity: UUID, user: UUID) -> Any:
    t = tables.research_measurement_consents
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
        **_plain(
            {
                k: row[k]
                for k in ("id", "market_space_id", "product_line_id", "scope_key", "created_at")
            }
        ),
        "protocol": row["protocol"],
        "protocol_digest": row["protocol_digest"],
        "my_consent": _plain(consent) if consent else None,
    }


def latest_sample(c: Connection, tenant: UUID, identity: UUID) -> Any:
    t = tables.research_measurement_samples
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


def sample_access(c: Connection, context: AuthContext, space: UUID, row: Any) -> None:
    if row["tenant_id"] != context.tenant.id or row["market_space_id"] != space:
        raise PermissionError("观察记录不在当前授权范围")
    authorize_scope(c, context, space, row["product_line_id"])
    if row["participant_user_id"] != context.user.id:
        authorize_scope(c, context, space, row["product_line_id"], access="manager")
        consent = current_consent(c, context.tenant.id, row["study_id"], row["participant_user_id"])
        if (
            consent is None
            or consent["status"] != "consented"
            or consent["id"] != row["consent_id"]
        ):
            raise PermissionError("本人已停止这批观察的范围内披露")
        actual = participant(c, context, space, row["product_line_id"], row["participant_user_id"])
        source(c, actual, space, row["product_line_id"], row["subject_kind"], row["subject_id"])


def sample_item(c: Connection, context: AuthContext, space: UUID, row: Any) -> dict[str, Any]:
    sample_access(c, context, space, row)
    current = source(
        c, context, space, row["product_line_id"], row["subject_kind"], row["subject_id"]
    )
    return {
        "id": str(row["id"]),
        "sample_id": str(row["sample_id"]),
        "version": row["version"],
        "draft": row["body"],
        "initial_source": row["initial_source_snapshot"],
        "source": row["source_snapshot"],
        "current_source": current,
        "source_changed": digest(current) != row["source_digest"] or current["source_changed"],
        "summary": sample_summary(row["body"]),
        "created_at": row["created_at"].isoformat(),
        "reason": row["reason"],
    }


def preview(
    c: Connection, context: AuthContext, space: UUID, command: SampleDraft
) -> dict[str, Any]:
    registered = study(c, context, space, command.study_id)
    line = registered["product_line_id"]
    authorize_scope(c, context, space, line, writable=True)
    participant(c, context, space, line, context.user.id)
    protocol = StudyProtocol.model_validate(registered["protocol"])
    consent = current_consent(c, context.tenant.id, command.study_id, context.user.id)
    if consent is None or consent["status"] != "consented":
        raise ProductWorkError("请先由本人明确同意本协议的活动登记与范围内披露用途")
    now = datetime.now(UTC)
    if command.as_of > now:
        raise ProductWorkError("观察截点不能晚于现在")
    if not protocol.window_start <= command.started_at < protocol.window_end:
        raise ProductWorkError("样本开始须位于原协议左闭右开观察窗口")
    if (
        command.role_id not in protocol.role_ids
        or command.complexity_stratum not in protocol.complexity_strata
    ):
        raise ProductWorkError("职责和复杂度须来自原协议已登记分层")
    if command.excluded_rule_id and command.excluded_rule_id not in {
        r.rule_id for r in protocol.exclusion_rules
    }:
        raise ProductWorkError("排除仅能对应预登记规则，失败或较慢样本不能自行删除")
    basis = source(c, context, space, line, command.subject_kind, command.subject_id)
    if protocol.evidence_kind == "real_business":
        if command.started_at < max(registered["created_at"], consent["created_at"]):
            raise ProductWorkError(
                "真实活动开始前须已有协议和本人的当前同意；历史办理请采用独立回放协议"
            )
        source_created = basis["created_at"]
        if isinstance(source_created, str):
            source_created = datetime.fromisoformat(source_created)
        if source_created > command.started_at:
            raise ProductWorkError("真实样本开始不能早于所选实际对象版本登记")
    body = command.model_dump(mode="json", exclude={"request_id", "expected_digest", "reason"})
    old = latest_sample(c, context.tenant.id, command.sample_id)
    if old:
        if (
            old["market_space_id"] != space
            or old["participant_user_id"] != context.user.id
            or old["study_id"] != command.study_id
        ):
            raise PermissionError("只能修订本人在此协议下的原记录")
        if old["version"] != command.expected_version:
            raise ProductWorkError("样本已有新版本，请重新读取")
        if any(body[key] != old["body"].get(key) for key in IDENTITY_KEYS):
            raise ProductWorkError("原对象、配对、分层和流程身份已固定，修订保留原观察口径")
        if str(old["subject_series_id"]) != str(basis["series_id"]):
            raise ProductWorkError("原对象系列发生变化，不能继续按旧身份记录")
        if command.as_of < datetime.fromisoformat(old["body"]["as_of"]):
            raise ProductWorkError("新版本观察截点不能回到原版本之前")
    elif command.expected_version != 0:
        raise ProductWorkError("首次登记版本须为零")
    t = tables.research_measurement_samples
    other = c.execute(
        select(t.c.sample_id)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.study_id == command.study_id,
            t.c.participant_user_id == context.user.id,
            t.c.subject_kind == command.subject_kind,
            t.c.subject_series_id == UUID(str(basis["series_id"])),
            t.c.sample_id != command.sample_id,
            *([] if protocol.evidence_kind == "real_business" else [t.c.mode == command.mode]),
        )
        .limit(1)
    ).scalar_one_or_none()
    if other is not None:
        raise ProductWorkError(
            "同一实际对象系列已有本人观察，请沿原样本修订；新版本或重试不能冒充独立业务样本"
        )
    body.update(
        {
            "participant_user_id": str(context.user.id),
            "subject_series_id": str(basis["series_id"]),
            "market_space_id": str(space),
            "product_line_id": str(line) if line else None,
            "scope_key": str(line or space),
            "evidence_kind": protocol.evidence_kind,
            "scenario_id": protocol.scenario_id,
        }
    )
    body["segments"] = [
        {**segment, "participant_user_id": str(context.user.id)} for segment in body["segments"]
    ]
    initial = old["initial_source_snapshot"] if old else basis
    signature = digest(
        {
            "market_space_id": str(space),
            "protocol_digest": registered["protocol_digest"],
            "consent_id": str(consent["id"]),
            "body": body,
            "source": basis,
            "initial_source": initial,
        }
    )
    return {
        "digest": signature,
        "draft": body,
        "source": basis,
        "initial_source": initial,
        "summary": sample_summary(body),
        "consent_id": str(consent["id"]),
    }


class ResearchMeasurementService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, space: UUID, command: Options) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize_scope(c, context, space, command.product_line_id)
            return {
                **source_options(
                    c,
                    context,
                    space,
                    command.product_line_id,
                    command.subject_kind,
                    query=command.query,
                    before_id=command.before_id,
                ),
                "can_manage": manage(c, context, space, command.product_line_id),
                "participant_user_id": str(context.user.id),
            }

    def create_study(
        self, context: AuthContext, space: UUID, command: StudyCreate
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            authorize_scope(
                c,
                context,
                space,
                command.product_line_id,
                access="manager",
                writable=True,
                lock=True,
            )
            t = tables.research_measurement_studies
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
                    raise ProductWorkError("同一请求不能改变观察协议")
                return study_item(c, context, old)
            now = datetime.now(UTC)
            if command.evidence_kind == "real_business" and command.window_start <= now:
                raise ProductWorkError(
                    "真实业务观察窗口须在协议登记之后开始，历史资料请单列受控回放"
                )
            protocol = command.model_dump(mode="json", exclude={"request_id", "product_line_id"})
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        **scope_values(context, space, command.product_line_id),
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
            event(c, context, row, identity, "study_registered")
            return study_item(c, context, row)

    def studies(self, context: AuthContext, space: UUID, command: StudyHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize_scope(c, context, space, command.product_line_id)
            t = tables.research_measurement_studies
            conditions = [
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.scope_key == (command.product_line_id or space),
            ]
            if command.before_id:
                conditions.append(t.c.id < command.before_id)
            rows = (
                c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [study_item(c, context, row) for row in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def consent(self, context: AuthContext, space: UUID, command: Consent) -> dict[str, Any]:
        with self.engine.begin() as c:
            registered = study(c, context, space, command.study_id)
            line = registered["product_line_id"]
            authorize_scope(
                c, context, space, line, writable=command.status == "consented", lock=True
            )
            if command.status == "consented":
                participant(c, context, space, line, context.user.id)
            t = tables.research_measurement_consents
            signature = digest(
                {"market_space_id": str(space), "command": command.model_dump(mode="json")}
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
                return study_item(c, context, registered)
            old = current_consent(c, context.tenant.id, command.study_id, context.user.id)
            version = old["version"] if old else 0
            if command.expected_version != version:
                raise ProductWorkError("本人同意状态已变化，请重新读取")
            if old and old["status"] == command.status:
                raise ProductWorkError("本人已处于此状态；变更用途须另行登记新协议")
            if old is None and command.status == "withdrawn":
                raise ProductWorkError("本人尚未同意此协议")
            identity = uuid4()
            c.execute(
                t.insert().values(
                    id=identity,
                    **scope_values(context, space, line),
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
            event(c, context, registered, identity, command.status)
            return study_item(c, context, registered)

    def preview(self, context: AuthContext, space: UUID, command: SampleDraft) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            return preview(c, context, space, command)

    def save(self, context: AuthContext, space: UUID, command: SampleSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            registered = study(c, context, space, command.study_id)
            authorize_scope(
                c, context, space, registered["product_line_id"], writable=True, lock=True
            )
            participant(c, context, space, registered["product_line_id"], context.user.id)
            t = tables.research_measurement_samples
            signature = digest(
                {"market_space_id": str(space), "command": command.model_dump(mode="json")}
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
                return sample_item(c, context, space, old)
            prepared = preview(c, context, space, command)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("协议、同意、活动或原资料已变化，请重新预览")
            identity = uuid4()
            subject_columns = {
                column: command.subject_id if kind == command.subject_kind else None
                for kind, column in SUBJECT_COLUMNS.items()
            }
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        **scope_values(context, space, registered["product_line_id"]),
                        study_id=command.study_id,
                        sample_id=command.sample_id,
                        version=command.expected_version + 1,
                        participant_user_id=context.user.id,
                        consent_id=UUID(prepared["consent_id"]),
                        subject_kind=command.subject_kind,
                        subject_id=command.subject_id,
                        subject_series_id=UUID(prepared["draft"]["subject_series_id"]),
                        **subject_columns,
                        mode=command.mode,
                        body=prepared["draft"],
                        initial_source_snapshot=prepared["initial_source"],
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
            event(c, context, registered, identity, "sample_recorded")
            return sample_item(c, context, space, row)

    @staticmethod
    def _latest(context: AuthContext, space: UUID, study_id: UUID) -> Any:
        t = tables.research_measurement_samples
        return (
            select(
                t,
                func.row_number()
                .over(partition_by=t.c.sample_id, order_by=t.c.version.desc())
                .label("ordinal"),
            )
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.study_id == study_id,
            )
            .subquery()
        )

    def history(self, context: AuthContext, space: UUID, command: SampleHistory) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            registered = study(c, context, space, command.study_id)
            t = self._latest(context, space, command.study_id)
            conditions = [t.c.ordinal == 1]
            if not manage(c, context, space, registered["product_line_id"]):
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
                    items.append(sample_item(c, context, space, row))
                except (PermissionError, ProductWorkError):
                    continue
            return {
                "items": items,
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, command: SampleRead) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            row = latest_sample(c, context.tenant.id, command.sample_id)
            if row is None:
                raise ProductWorkError("未找到观察记录")
            item = sample_item(c, context, space, row)
            t = tables.research_measurement_samples
            conditions = [
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
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
                    history.append(sample_item(c, context, space, old))
                except (PermissionError, ProductWorkError):
                    continue
            return {
                "item": item,
                "history": history,
                "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
            }

    def summary(self, context: AuthContext, space: UUID, command: Summary) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            registered = study(c, context, space, command.study_id)
            manager = manage(c, context, space, registered["product_line_id"])
            t = self._latest(context, space, command.study_id)
            conditions = [t.c.ordinal == 1]
            if not manager:
                conditions.append(t.c.participant_user_id == context.user.id)
            rows = c.execute(select(t).where(*conditions).limit(10001)).mappings().all()
            if len(rows) > 10000:
                raise ProductWorkError("本协议超过10000条观察，未输出局部总计")
            included = []
            unavailable = excluded = changed = 0
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
                    actual = participant(
                        c, context, space, row["product_line_id"], row["participant_user_id"]
                    )
                    source(
                        c,
                        actual,
                        space,
                        row["product_line_id"],
                        row["subject_kind"],
                        row["subject_id"],
                    )
                    item = sample_item(c, context, space, row)
                except (PermissionError, ProductWorkError):
                    unavailable += 1
                    continue
                if item["source_changed"]:
                    changed += 1
                if row["body"].get("excluded_rule_id"):
                    excluded += 1
                else:
                    included.append(
                        {**row["body"], "id": str(row["id"]), "version": row["version"]}
                    )
            return {
                "study": study_item(c, context, registered),
                "summary": study_summary(included),
                "excluded_count": excluded,
                "unavailable_count": unavailable,
                "source_changed_count": changed,
                "registered_latest_count": len(rows),
                "scope": "all_consenting" if manager else "own",
                "as_of": datetime.now(UTC).isoformat(),
                "limitation": (
                    "仅本人活动自报，按实际对象类型分层；来源演进与原保存值分列，"
                    "不计算完整团队净投入或独立接收率，不作收益或验收裁决。"
                ),
            }
