"""Private project conversations with persistent requests and live domain receipts."""

from __future__ import annotations

from builtins import list as BuiltinList
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, func, or_, select

from app.ai.application_gateway import ApplicationModelGateway
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversation_focus import (
    FocusRef,
)
from app.domain.conversation_focus import (
    current as current_focus,
)
from app.domain.conversation_focus import (
    snapshot as focus_snapshot,
)
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meetings import MeetingService
from app.domain.product_workspace import _plain, digest

ACTIONS = {
    "note",
    "project_query",
    "change_work_package",
    "quality_work_package",
    "meeting_planning",
    "meeting_reading",
    "minutes",
    "actions",
    "decisions",
    "business",
}


class ConversationError(ValueError):
    pass


class ConversationAccessError(PermissionError):
    pass


class ConversationService:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway | None = None):
        self.engine, self.gateway = engine, gateway

    def _authorize(
        self, c: Connection, context: AuthContext, project_id: UUID, meeting_id: UUID | None = None
    ) -> None:
        current = AuthRepository(self.engine).find_user_context(context.user.id)
        if (
            current is None
            or current.tenant.id != context.tenant.id
            or not current.user.is_active
            or current.tenant.status != "active"
            or current.user.auth_version != context.user.auth_version
        ):
            raise ConversationAccessError("当前身份已变化，请重新登录")
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project_id, Action.PROJECT_VIEW
        )
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project_id, Action.WORK_ITEM_VIEW
        )
        if meeting_id is not None:
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.MEETING_VIEW
            )
            MeetingService._get(
                c, tenant_id=context.tenant.id, project_id=project_id, meeting_id=meeting_id
            )

    @staticmethod
    def _change_access(
        c: Connection, context: AuthContext, project_id: UUID, *, edit: bool
    ) -> None:
        for action in (
            Action.PRODUCT_ENGINEERING_VIEW,
            Action.QUALITY_VIEW,
            Action.CHANGE_EDIT if edit else Action.CHANGE_VIEW,
        ):
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, action
            )

    @staticmethod
    def _quality_access(
        c: Connection, context: AuthContext, project_id: UUID, *, edit: bool
    ) -> None:
        from app.domain.quality_operations import authorize

        for action in (Action.QUALITY_VIEW, Action.WORK_ITEM_VIEW):
            authorize(c, context, project_id, action)
        if edit:
            authorize(c, context, project_id, Action.CAPA_EXECUTE)

    def _conversation(
        self, c: Connection, context: AuthContext, conversation_id: UUID, *, lock: bool = False
    ) -> Any:
        query = select(tables.conversations).where(
            tables.conversations.c.tenant_id == context.tenant.id,
            or_(
                tables.conversations.c.created_by_user_id == context.user.id,
                tables.conversations.c.visibility == "project",
            ),
            tables.conversations.c.id == conversation_id,
        )
        row = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
        if row is None:
            raise ConversationAccessError("会话不存在或当前无权访问")
        if row["scope_kind"] == "project":
            self._authorize(c, context, row["project_id"], row["meeting_id"])
        else:
            from app.domain.conversation_product_work import authorize_private

            if row["created_by_user_id"] != context.user.id or row["visibility"] != "private":
                raise ConversationAccessError("私人工作会话仅供创建者读取")
            authorize_private(c, context, row)
        return row

    def create(
        self,
        *,
        context: AuthContext,
        request_id: UUID,
        project_id: UUID | None = None,
        meeting_id: UUID | None = None,
        visibility: str = "private",
        scope_kind: str = "project",
        market_space_id: UUID | None = None,
        product_line_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.domain.conversation_product_work import ConversationScope, authorize_private

        scope = ConversationScope.model_validate(
            dict(
                scope_kind=scope_kind,
                project_id=project_id,
                meeting_id=meeting_id,
                market_space_id=market_space_id,
                product_line_id=product_line_id,
                visibility=visibility,
            )
        ).model_dump()
        if visibility == "project" and meeting_id is not None:
            raise ConversationError("项目共享会话请从项目入口创建")
        with self.engine.begin() as c:
            if scope_kind == "project":
                assert project_id is not None
                self._authorize(c, context, project_id, meeting_id)
            else:
                authorize_private(c, context, scope)
            conversation_id = uuid5(context.user.id, "conversation:" + str(request_id))
            existing = (
                c.execute(
                    select(tables.conversations).where(
                        tables.conversations.c.id == conversation_id,
                        tables.conversations.c.tenant_id == context.tenant.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if any(existing[k] != v for k, v in scope.items()):
                    raise ConversationError("本请求已用于其他会话范围")
                return _plain(dict(existing))
            from sqlalchemy.dialects.postgresql import insert

            c.execute(
                insert(tables.conversations)
                .values(
                    id=conversation_id,
                    tenant_id=context.tenant.id,
                    **scope,
                    created_by_user_id=context.user.id,
                    title=("会议会话" if meeting_id else "项目会话")
                    if scope_kind == "project"
                    else "个人工作会话",
                    context_version=1,
                    next_sequence=1,
                )
                .on_conflict_do_nothing(index_elements=[tables.conversations.c.id])
            )
            row = self._conversation(c, context, conversation_id)
            if any(row[k] != v for k, v in scope.items()):
                raise ConversationError("本请求已用于其他会话范围")
            return _plain(dict(row))

    def list(
        self,
        *,
        context: AuthContext,
        project_id: UUID | None = None,
        meeting_id: UUID | None = None,
        scope_kind: str = "project",
        market_space_id: UUID | None = None,
        product_line_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        from app.domain.conversation_product_work import ConversationScope, authorize_private

        scope = ConversationScope.model_validate(
            dict(
                scope_kind=scope_kind,
                project_id=project_id,
                meeting_id=meeting_id,
                market_space_id=market_space_id,
                product_line_id=product_line_id,
            )
        ).model_dump()
        with self.engine.connect() as c:
            if scope_kind == "project":
                assert project_id is not None
                self._authorize(c, context, project_id, meeting_id)
            else:
                authorize_private(c, context, scope)
            query = (
                select(tables.conversations)
                .where(
                    tables.conversations.c.tenant_id == context.tenant.id,
                    or_(
                        tables.conversations.c.created_by_user_id == context.user.id,
                        tables.conversations.c.visibility == "project",
                    )
                    if scope_kind == "project"
                    else tables.conversations.c.created_by_user_id == context.user.id,
                    *[
                        tables.conversations.c[k] == scope[k]
                        for k in (
                            "scope_kind",
                            "project_id",
                            "meeting_id",
                            "market_space_id",
                            "product_line_id",
                        )
                    ],
                )
                .order_by(
                    tables.conversations.c.updated_at.desc(), tables.conversations.c.id.desc()
                )
                .limit(50)
            )
            return [_plain(dict(row)) for row in c.execute(query).mappings()]

    def save_message(
        self,
        *,
        context: AuthContext,
        conversation_id: UUID,
        request_id: UUID,
        expected_context_version: int,
        body: str,
        action: str = "note",
        transcript_id: UUID | None = None,
        expected_digest: str | None = None,
        expected_minutes_version: int | None = None,
        attachment_ids: tuple[UUID, ...] = (),
        attachment_selections: BuiltinList[dict[str, Any]] | None = None,
        ecr_id: UUID | None = None,
        impact_depth: int | None = None,
        allow_discussion: bool = False,
        include_supplier_notices: bool = False,
        ncr_id: UUID | None = None,
        quality_selections: BuiltinList[dict[str, Any]] | None = None,
        object_focus: dict[str, Any] | None = None,
        meeting_planning_brief_id: UUID | None = None,
        product_sources: BuiltinList[dict[str, Any]] | None = None,
        matrix_selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = body.strip()
        if action not in ACTIONS or not 1 <= len(body) <= 2000:
            raise ConversationError("请填写1至2000字说明并选择已接通的办理方式")
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            conversation = self._conversation(c, context, conversation_id, lock=True)
            if conversation["scope_kind"] != "project":
                from app.domain.conversation_product_work import save

                if (
                    action != "note"
                    or any(
                        v is not None
                        for v in (
                            transcript_id,
                            expected_digest,
                            expected_minutes_version,
                            ecr_id,
                            impact_depth,
                            ncr_id,
                            quality_selections,
                            object_focus,
                            meeting_planning_brief_id,
                        )
                    )
                    or allow_discussion
                    or include_supplier_notices
                ):
                    raise ConversationError("私人产品会话不使用项目或会议办理参数")
                return save(
                    c,
                    context,
                    conversation,
                    request_id=request_id,
                    expected_context_version=expected_context_version,
                    body=body,
                    attachment_ids=attachment_ids,
                    attachment_selections=attachment_selections,
                    product_sources=product_sources or [],
                    matrix_selection=matrix_selection,
                )
            if product_sources or matrix_selection is not None or attachment_selections is not None:
                raise ConversationError("项目会话不混用产品研究来源")
            if conversation["visibility"] == "project" and action not in {"note", "project_query"}:
                raise ConversationError(
                    "专业办理请从原业务页面继续；共享会话支持项目问答和补充资料"
                )
            signature = digest(
                _plain(
                    dict(
                        body=body,
                        action=action,
                        **(
                            {"meeting_planning_brief_id": meeting_planning_brief_id}
                            if meeting_planning_brief_id is not None
                            else {}
                        ),
                        **({"object_focus": object_focus} if object_focus is not None else {}),
                        transcript_id=transcript_id,
                        expected_digest=expected_digest,
                        expected_minutes_version=expected_minutes_version,
                        context_version=expected_context_version,
                        **({"attachment_ids": attachment_ids} if attachment_ids else {}),
                        **({"allow_discussion": True} if allow_discussion else {}),
                        **({"include_supplier_notices": True} if include_supplier_notices else {}),
                        **(
                            {"ncr_id": ncr_id, "quality_selections": quality_selections}
                            if ncr_id is not None or quality_selections is not None
                            else {}
                        ),
                        **(
                            {"ecr_id": ecr_id, "impact_depth": impact_depth}
                            if ecr_id is not None or impact_depth is not None
                            else {}
                        ),
                    )
                )
            )
            old = (
                c.execute(
                    select(tables.conversation_messages).where(
                        tables.conversation_messages.c.tenant_id == context.tenant.id,
                        tables.conversation_messages.c.conversation_id == conversation_id,
                        tables.conversation_messages.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                if old["request_digest"] != signature or old["author_user_id"] != context.user.id:
                    raise ConversationError("本消息号已提交不同内容，请核对原回执")
                if old.get("object_focus"):
                    fixed = old["object_focus"]
                    focus_snapshot(
                        c,
                        context.tenant.id,
                        conversation["project_id"],
                        context.user.id,
                        fixed["kind"],
                        UUID(fixed["id"]),
                    )
                return _plain(dict(old))
            if (
                conversation["archived_at"] is not None
                or conversation["context_version"] != expected_context_version
            ):
                raise ConversationError("会话已归档或范围版本变化，请刷新")
            frozen_focus = None
            if object_focus is not None:
                if (
                    action not in {"note", "project_query"}
                    or attachment_ids
                    or conversation["meeting_id"] is not None
                ):
                    raise ConversationError(
                        "工作卡范围仅用于对象问答或补充说明，请分开办理附件和会议"
                    )
                ref = FocusRef.model_validate(object_focus)
                frozen_focus = current_focus(
                    c,
                    context.tenant.id,
                    conversation["project_id"],
                    context.user.id,
                    ref.model_dump(mode="json"),
                )
            if action != "meeting_planning" and meeting_planning_brief_id is not None:
                raise ConversationError("只有会议起草使用起草资料版本")
            if action != "minutes" and expected_minutes_version is not None:
                raise ConversationError("只有纪要候选使用正式纪要版本")
            if action != "change_work_package" and (
                ecr_id is not None
                or impact_depth is not None
                or allow_discussion
                or include_supplier_notices
            ):
                raise ConversationError("只有工程变更建议使用变更来源参数")
            if action != "quality_work_package" and (
                ncr_id is not None or quality_selections is not None
            ):
                raise ConversationError("只有品质工作包使用 NCR 与品质证据参数")
            if action == "meeting_planning":
                if (
                    meeting_planning_brief_id is None
                    or expected_digest is None
                    or transcript_id is not None
                    or attachment_ids
                    or conversation["meeting_id"] is not None
                ):
                    raise ConversationError(
                        "请在项目会话选择已核对会议要求；附件或已建会议请分开办理"
                    )
                from app.domain.conversation_meeting_planning import (
                    label,
                )
                from app.domain.conversation_meeting_planning import (
                    source as planning_source,
                )

                selected_brief = planning_source(
                    c,
                    context,
                    conversation["project_id"],
                    meeting_planning_brief_id,
                    expected_digest,
                )
                if body != label(selected_brief):
                    raise ConversationError(
                        "起草请求须对应已核对要求；补充或修改请先保存新的起草资料版本"
                    )
            elif action == "quality_work_package":
                if (
                    ncr_id is None
                    or quality_selections is None
                    or expected_digest is None
                    or transcript_id is not None
                    or attachment_ids
                ):
                    raise ConversationError("请选择原 NCR 并核对实际资料；本项使用原质量证据")
                from app.ai.quality_preparation import source_state as quality_source_state
                from app.domain.quality_operations import Evidence

                self._quality_access(c, context, conversation["project_id"], edit=True)
                quality_snapshot = quality_source_state(
                    c,
                    context.tenant.id,
                    conversation["project_id"],
                    ncr_id,
                    [Evidence.model_validate(v) for v in quality_selections],
                )
                if quality_snapshot["digest"] != expected_digest:
                    raise ConversationError("原质量资料已变化，请重新核对并保存新消息")
            elif action == "change_work_package":
                if (
                    ecr_id is None
                    or impact_depth is None
                    or not 1 <= impact_depth <= 5
                    or expected_digest is None
                    or transcript_id is not None
                    or attachment_ids
                ):
                    raise ConversationError(
                        "请选择实际变更并重新读取1至5层资料；本项使用原业务来源"
                    )
                from app.ai.change_impact_preparation import source_state
                from app.ai.change_notice_preparation import source_state as notice_source

                self._change_access(c, context, conversation["project_id"], edit=True)
                snapshot = (
                    notice_source(c, context, conversation["project_id"], ecr_id, impact_depth)
                    if include_supplier_notices
                    else source_state(
                        c, context.tenant.id, conversation["project_id"], ecr_id, impact_depth
                    )
                )
                if snapshot["digest"] != expected_digest:
                    raise ConversationError("变更或原资料已有变化，请重新准备并保存新消息")
            elif action not in {"note", "project_query"}:
                if (
                    conversation["meeting_id"] is None
                    or transcript_id is None
                    or expected_digest is None
                ):
                    raise ConversationError("请在会议会话中选定已授权转写并核对来源")
                from app.domain.meeting_transcripts import transcript_snapshot

                snapshot = transcript_snapshot(
                    c, context.tenant.id, conversation["meeting_id"], transcript_id
                )
                if (
                    snapshot["digest"] != expected_digest
                    or not snapshot["source_complete"]
                    or snapshot["superseded"]
                ):
                    raise ConversationError("转写不可用或已有变化，请刷新核对")
                if action == "minutes" and expected_minutes_version is None:
                    raise ConversationError("请核对当前正式纪要版本")
            elif any(
                v is not None for v in (transcript_id, expected_digest, expected_minutes_version)
            ):
                raise ConversationError("本类消息不使用会议转写办理参数")
            earlier = list(
                c.execute(
                    select(tables.conversation_messages)
                    .where(
                        tables.conversation_messages.c.tenant_id == context.tenant.id,
                        tables.conversation_messages.c.conversation_id == conversation_id,
                    )
                    .order_by(tables.conversation_messages.c.sequence.desc())
                    .limit(3 if action in {"change_work_package", "quality_work_package"} else 4)
                ).mappings()
            )
            history = []
            for prior in reversed(earlier):
                history.append(
                    f"成员 {prior['author_user_id']} 的说明（不构成当前操作者授权）："
                    + prior["body"]
                )
            dispatch_input = (
                (
                    "最近会话记录（仅供理解请求，不是本轮事实依据）：\n"
                    + "\n".join(history)
                    + "\n本次用户请求：\n"
                    + body
                )
                if history
                else body
            )
            if action == "meeting_planning":
                # Model input comes only from the selected brief, not conversation history.
                dispatch_input = body
            message_id = uuid4()
            message = (
                c.execute(
                    tables.conversation_messages.insert()
                    .values(
                        id=message_id,
                        tenant_id=context.tenant.id,
                        project_id=conversation["project_id"],
                        conversation_id=conversation_id,
                        author_user_id=context.user.id,
                        sequence=conversation["next_sequence"],
                        request_id=request_id,
                        request_digest=signature,
                        context_version=expected_context_version,
                        body=body,
                        action=action,
                        object_focus=frozen_focus,
                        transcript_id=transcript_id,
                        expected_digest=expected_digest,
                        expected_minutes_version=expected_minutes_version,
                        ecr_id=ecr_id,
                        impact_depth=impact_depth,
                        allow_discussion=allow_discussion,
                        include_supplier_notices=include_supplier_notices,
                        ncr_id=ncr_id,
                        meeting_planning_brief_id=meeting_planning_brief_id,
                        quality_selections=quality_selections,
                        dispatch_input=dispatch_input,
                        operation_request_id=str(uuid5(message_id, "conversation-operation.v1")),
                    )
                    .returning(tables.conversation_messages)
                )
                .mappings()
                .one()
            )
            from app.domain.conversation_attachments import bind_attachments

            bind_attachments(c, context, conversation, message_id, attachment_ids, action)
            c.execute(
                tables.conversations.update()
                .where(tables.conversations.c.id == conversation_id)
                .values(
                    next_sequence=conversation["next_sequence"] + 1,
                    updated_at=func.clock_timestamp(),
                )
            )
            return _plain(dict(message))

    @staticmethod
    def _attachment_ids(c: Connection, context: AuthContext, message_id: UUID) -> tuple[UUID, ...]:
        from app.domain.conversation_attachments import message_attachment_ids

        return message_attachment_ids(c, context.tenant.id, message_id)

    def _run(self, c: Connection, context: AuthContext, message: Any) -> Any:
        if message["action"] == "note":
            return None
        run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.project_id == message["project_id"],
                    tables.agent_runs.c.requested_by_user_id == message["author_user_id"],
                    tables.agent_runs.c.agent_key
                    == (
                        "ai_chat"
                        if message["action"] == "project_query"
                        else "engineering_intelligence"
                        if message["action"] == "change_work_package"
                        else "quality_intelligence"
                        if message["action"] == "quality_work_package"
                        else "knowledge_lite"
                    ),
                    tables.agent_runs.c.request_id == message["operation_request_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if run is not None:
            rc = run["run_context"]
            if message["action"] == "project_query":
                matches = (
                    run["context_version"]
                    == (
                        "chat-request-object-v1"
                        if message.get("object_focus")
                        else "chat-request-v1"
                    )
                    and rc.get("chat_object_focus") == message.get("object_focus")
                    and rc.get("chat_question") == message["dispatch_input"]
                    and rc.get("chat_attachment_ids", [])
                    == [str(a) for a in self._attachment_ids(c, context, message["id"])]
                )
            elif message["action"] == "meeting_planning":
                matches = (
                    run["context_version"] == "meeting-planning-request-v1"
                    and rc.get("meeting_planning_brief_id")
                    == str(message["meeting_planning_brief_id"])
                    and rc.get("meeting_planning_source_digest") == message["expected_digest"]
                )
            elif message["action"] == "quality_work_package":
                matches = (
                    run["context_version"] == "quality-work-package-request-v1"
                    and rc.get("quality_ncr_id") == str(message["ncr_id"])
                    and rc.get("quality_selections") == message["quality_selections"]
                    and rc.get("quality_expected_digest") == message["expected_digest"]
                    and rc.get("quality_user_instruction") == message["dispatch_input"]
                )
            elif message["action"] == "change_work_package":
                matches = (
                    run["context_version"] == "change-work-package-request-v1"
                    and rc.get("impact_ecr_id") == str(message["ecr_id"])
                    and rc.get("impact_depth") == message["impact_depth"]
                    and rc.get("impact_allow_discussion", False) == message["allow_discussion"]
                    and rc.get("impact_include_supplier_notices", False)
                    == message["include_supplier_notices"]
                    and rc.get("impact_expected_digest") == message["expected_digest"]
                    and rc.get("impact_user_instruction") == message["dispatch_input"]
                )
            else:
                versions = {
                    "meeting_reading": "meeting-reading-request-v1",
                    "minutes": "meeting-minutes-request-v1",
                    "actions": "meeting-actions-request-v1",
                    "decisions": "meeting-decisions-request-v1",
                    "business": "meeting-business-request-v1",
                }
                matches = (
                    run["context_version"] == versions[message["action"]]
                    and rc.get("reading_transcript_id") == str(message["transcript_id"])
                    and rc.get("reading_expected_digest") == message["expected_digest"]
                    and rc.get("reading_user_instruction", "") == message["dispatch_input"]
                )
            if not matches:
                raise ConversationError("原请求与保存消息不一致，请核对回执")
        return run

    def _dispatch_inputs(
        self, *, context: AuthContext, conversation_id: UUID, message_id: UUID
    ) -> tuple[Any, Any, tuple[UUID, ...]]:
        with self.engine.connect() as c:
            conversation = self._conversation(c, context, conversation_id)
            message = (
                c.execute(
                    select(tables.conversation_messages).where(
                        tables.conversation_messages.c.tenant_id == context.tenant.id,
                        tables.conversation_messages.c.conversation_id == conversation_id,
                        tables.conversation_messages.c.id == message_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if message is None or message["author_user_id"] != context.user.id:
                raise ConversationAccessError("只能运行本人提交的消息")
            attachment_ids = self._attachment_ids(c, context, message_id)
            if conversation["archived_at"] is not None:
                raise ConversationError("已归档会话不能继续运行")
        return conversation, message, attachment_ids

    @staticmethod
    def _saved_note(
        conversation: Any, message: Any, attachment_ids: tuple[UUID, ...]
    ) -> dict[str, Any] | None:
        if message["action"] == "note":
            if conversation["scope_kind"] != "project":
                from app.domain.conversation_product_work import guidance_for

                return {
                    "status": "saved",
                    "guidance": guidance_for(
                        message["body"], conversation, attachment_ids=attachment_ids
                    ),
                }
            return {"status": "saved"}
        return None

    def saved_note_for_dispatch(
        self, *, context: AuthContext, conversation_id: UUID, message_id: UUID
    ) -> dict[str, Any] | None:
        return self._saved_note(
            *self._dispatch_inputs(
                context=context, conversation_id=conversation_id, message_id=message_id
            )
        )

    def dispatch(
        self, *, context: AuthContext, conversation_id: UUID, message_id: UUID
    ) -> dict[str, Any]:
        conversation, message, attachment_ids = self._dispatch_inputs(
            context=context, conversation_id=conversation_id, message_id=message_id
        )
        saved_note = self._saved_note(conversation, message, attachment_ids)
        if saved_note is not None:
            return saved_note
        if self.gateway is None:
            raise ConversationError("本次未配置运行服务")
        if conversation["scope_kind"] != "project":
            from app.ai.product_matrix_runs import ProductMatrixRuns
            from app.ai.product_work_runs import ProductWorkRuns
            from app.domain.conversation_product_work import (
                is_matrix,
                product_run,
                run_request,
            )

            with self.engine.connect() as c:
                self._conversation(c, context, conversation_id)
                product_run(c, context, conversation, message)
            if is_matrix(message["product_work_request"]):
                return ProductMatrixRuns(self.engine, gateway=self.gateway).create(
                    context=context,
                    space_id=conversation["market_space_id"],
                    request=run_request(message),
                ) | {"runtime": "product_matrix"}
            return ProductWorkRuns(self.engine, gateway=self.gateway).create(
                context=context,
                space_id=conversation["market_space_id"],
                request=run_request(message),
            ) | {"runtime": "product_work"}
        if message["action"] == "project_query":
            from app.ai.chat_queue import ChatQueue
            from app.domain.conversation_attachments import attachment_evidence

            attachment_evidence(
                self.engine,
                tenant_id=context.tenant.id,
                project_id=conversation["project_id"],
                actor_user_id=context.user.id,
                attachment_ids=attachment_ids,
                question=message["dispatch_input"],
            )

            return (
                ChatQueue(self.engine, gateway=self.gateway)
                .submit(
                    context=context,
                    project_id=conversation["project_id"],
                    question=message["dispatch_input"],
                    request_id=message["operation_request_id"],
                    attachment_ids=attachment_ids,
                    object_focus=message.get("object_focus"),
                )
                .model_dump(mode="json")
            )
        if message["action"] == "meeting_planning":
            from app.ai.meeting_planning_runs import MeetingPlanningRequest, MeetingPlanningRuns

            return MeetingPlanningRuns(self.engine, self.gateway).create(
                context,
                conversation["project_id"],
                message["meeting_planning_brief_id"],
                MeetingPlanningRequest(
                    request_id=UUID(message["operation_request_id"]),
                    expected_source_digest=message["expected_digest"],
                ),
            )
        if message["action"] == "quality_work_package":
            from app.ai.quality_work_package_runs import QualityWorkPackageRuns
            from app.ai.quality_work_package_runs import Request as QualityRequest
            from app.domain.quality_operations import Evidence

            return QualityWorkPackageRuns(self.engine, gateway=self.gateway).create(
                context=context,
                project_id=conversation["project_id"],
                ncr_id=message["ncr_id"],
                request=QualityRequest(
                    request_id=UUID(message["operation_request_id"]),
                    expected_digest=message["expected_digest"],
                    selections=[Evidence.model_validate(v) for v in message["quality_selections"]],
                    user_instruction=message["dispatch_input"],
                ),
            )
        if message["action"] == "change_work_package":
            from app.ai.change_work_package_runs import ChangeWorkPackageRuns, Request

            return ChangeWorkPackageRuns(self.engine, gateway=self.gateway).create(
                context=context,
                project_id=conversation["project_id"],
                ecr_id=message["ecr_id"],
                request=Request(
                    request_id=UUID(message["operation_request_id"]),
                    expected_digest=message["expected_digest"],
                    depth=message["impact_depth"],
                    allow_discussion=message["allow_discussion"],
                    include_supplier_notices=message["include_supplier_notices"],
                    user_instruction=message["dispatch_input"],
                ),
            )
        from app.ai.meeting_reading import MeetingReadingService

        return MeetingReadingService(self.engine, gateway=self.gateway).create(
            tenant_id=context.tenant.id,
            project_id=conversation["project_id"],
            meeting_id=conversation["meeting_id"],
            transcript_id=message["transcript_id"],
            actor_id=context.user.id,
            auth_version=context.user.auth_version,
            request_id=UUID(message["operation_request_id"]),
            expected_digest=message["expected_digest"],
            expected_minutes_version=message["expected_minutes_version"],
            propose_minutes=message["action"] == "minutes",
            propose_actions=message["action"] == "actions",
            propose_decisions=message["action"] == "decisions",
            propose_business=message["action"] == "business",
            user_instruction=message["dispatch_input"],
        )

    def get(
        self, *, context: AuthContext, conversation_id: UUID, before_sequence: int | None = None
    ) -> dict[str, Any]:
        change_receipts: dict[UUID, dict[str, Any]] = {}
        quality_receipts: dict[UUID, dict[str, Any]] = {}
        planning_receipts: dict[UUID, dict[str, Any]] = {}
        focus_views: dict[UUID, dict[str, Any]] = {}
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            conversation = self._conversation(c, context, conversation_id)
            if conversation["scope_kind"] != "project":
                from app.domain.conversation_product_work import get

                return get(c, context, conversation, before_sequence)
            query = select(tables.conversation_messages).where(
                tables.conversation_messages.c.tenant_id == context.tenant.id,
                tables.conversation_messages.c.conversation_id == conversation_id,
            )
            if before_sequence is not None:
                query = query.where(tables.conversation_messages.c.sequence < before_sequence)
            fetched = list(
                c.execute(
                    query.order_by(tables.conversation_messages.c.sequence.desc()).limit(31)
                ).mappings()
            )
            messages = fetched[:30]
            rows = [
                (dict(m), self._run(c, context, m), self._attachment_ids(c, context, m["id"]))
                for m in reversed(messages)
            ]
            for message, run, _ in rows:
                if message.get("object_focus"):
                    from app.auth.errors import ObjectPermissionDeniedError
                    from app.domain.knowledge_push import KnowledgeAccessError
                    from app.domain.product_workspace import (
                        ProductWorkAccessError,
                        ProductWorkError,
                    )

                    try:
                        fixed = message["object_focus"]
                        latest = focus_snapshot(
                            c,
                            context.tenant.id,
                            conversation["project_id"],
                            context.user.id,
                            fixed["kind"],
                            UUID(fixed["id"]),
                        )
                        focus_views[message["id"]] = {
                            **fixed,
                            "available": True,
                            "current": latest["digest"] == fixed["digest"],
                        }
                    except (
                        ObjectPermissionDeniedError,
                        KnowledgeAccessError,
                        ProductWorkAccessError,
                        ProductWorkError,
                    ):
                        focus_views[message["id"]] = {"available": False, "current": False}
                if message["action"] == "meeting_planning":
                    from app.ai.meeting_planning_runs import run_view
                    from app.domain.conversation_meeting_planning import source as planning_source

                    planning_source(
                        c,
                        context,
                        conversation["project_id"],
                        message["meeting_planning_brief_id"],
                        message["expected_digest"],
                        current=False,
                    )
                    if run is not None:
                        planning_receipts[message["id"]] = {
                            **run_view(c, context, run),
                            "run_id": str(run["id"]),
                        }
                    continue
                if message["action"] == "quality_work_package":
                    from app.ai.quality_preparation import source_state as quality_source_state
                    from app.ai.quality_work_package_runs import receipt as quality_receipt
                    from app.domain.product_workspace import ProductWorkError
                    from app.domain.quality_operations import Evidence

                    self._quality_access(c, context, conversation["project_id"], edit=False)
                    if run is not None:
                        try:
                            current_quality = quality_source_state(
                                c,
                                context.tenant.id,
                                conversation["project_id"],
                                message["ncr_id"],
                                [Evidence.model_validate(v) for v in message["quality_selections"]],
                            )["digest"]
                        except ProductWorkError:
                            current_quality = None
                        quality_receipts[message["id"]] = {
                            **quality_receipt(run),
                            "current": current_quality == message["expected_digest"],
                        }
                    continue
                if message["action"] != "change_work_package":
                    continue
                self._change_access(c, context, conversation["project_id"], edit=False)
                if run is not None:
                    from app.ai.change_notice_preparation import rebuild, require_disclosure
                    from app.ai.change_work_package_runs import receipt as change_receipt
                    from app.domain.product_workspace import ProductWorkError

                    fixed_source = run["run_context"]["impact_source"]
                    try:
                        require_disclosure(c, context, fixed_source)
                    except (ProductWorkError, PermissionError):
                        change_receipts[message["id"]] = {
                            "run_id": str(run["id"]),
                            "status": run["status"],
                            "source_unavailable": True,
                            "current": False,
                        }
                        continue
                    try:
                        current_digest = rebuild(
                            c,
                            context.tenant.id,
                            conversation["project_id"],
                            fixed_source,
                            context.user.id,
                        )["digest"]
                    except (ProductWorkError, PermissionError):
                        current_digest = None
                    from app.ai.change_discussion_receipts import linked

                    change_receipts[message["id"]] = {
                        **linked(c, run, context.user.id),
                        **change_receipt(run),
                        "current": current_digest == message["expected_digest"],
                    }

        items = []
        for message, run, attachment_ids in rows:
            receipt: dict[str, Any] = {
                "status": "saved" if message["action"] == "note" else "pending"
            }
            if run is not None:
                receipt = {
                    "run_id": str(run["id"]),
                    "status": run["status"],
                    "error_code": run["error_code"],
                }
                if message["action"] == "project_query" and run["status"] not in {
                    "queued",
                    "running",
                }:
                    from app.ai.chat import read_chat_result

                    receipt["result"] = read_chat_result(
                        self.engine,
                        context=context,
                        row=run,
                        shared_message_id=message["id"]
                        if conversation["visibility"] == "project"
                        else None,
                    ).model_dump(mode="json")
                elif message["action"] == "meeting_planning":
                    receipt = planning_receipts[message["id"]]
                elif message["action"] == "quality_work_package":
                    receipt = quality_receipts[message["id"]]
                elif message["action"] == "change_work_package":
                    receipt = change_receipts[message["id"]]
                elif message["action"] != "project_query":
                    from app.ai.meeting_reading import MeetingReadingService

                    reading = MeetingReadingService.list_results(
                        self.engine,
                        tenant_id=context.tenant.id,
                        project_id=conversation["project_id"],
                        meeting_id=conversation["meeting_id"],
                        transcript_id=message["transcript_id"],
                        actor_id=context.user.id,
                        run_id=run["id"],
                    )
                    receipt = next(
                        (r for r in reading["items"] if r["run_id"] == str(run["id"])), receipt
                    )
                if run["error_code"] == "APPLICATION_REQUEST_CANCELLED":
                    receipt["status"] = "cancelled"
            items.append(
                {
                    "id": str(message["id"]),
                    "sequence": message["sequence"],
                    "author_user_id": str(message["author_user_id"]),
                    "body": message["body"],
                    "action": message["action"],
                    "created_at": message["created_at"],
                    "receipt": receipt,
                    "object_focus": focus_views.get(message["id"]),
                    "attachment_ids": [str(a) for a in attachment_ids],
                    **(
                        {
                            "meeting_planning_source": {
                                "brief_id": str(message["meeting_planning_brief_id"]),
                                "source_digest": message["expected_digest"],
                            }
                        }
                        if message["action"] == "meeting_planning"
                        else {}
                    ),
                    **(
                        {
                            "quality_source": {
                                "ncr_id": str(message["ncr_id"]),
                                "source_digest": message["expected_digest"],
                                "selection_count": len(message["quality_selections"]),
                            }
                        }
                        if message["action"] == "quality_work_package"
                        else {}
                    ),
                    **(
                        {
                            "change_source": {
                                "ecr_id": str(message["ecr_id"]),
                                "depth": message["impact_depth"],
                                "allow_discussion": message["allow_discussion"],
                                "include_supplier_notices": message["include_supplier_notices"],
                                "source_digest": message["expected_digest"],
                            }
                        }
                        if message["action"] == "change_work_package"
                        else {}
                    ),
                }
            )
        return _plain(
            {
                "conversation": dict(conversation),
                "items": items,
                "next_before": messages[-1]["sequence"] if len(fetched) > 30 else None,
            }
        )

    def archive(
        self, *, context: AuthContext, conversation_id: UUID, archived: bool
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = self._conversation(c, context, conversation_id, lock=True)
            if row["created_by_user_id"] != context.user.id:
                raise ConversationAccessError("仅会话创建者可归档或恢复")
            c.execute(
                tables.conversations.update()
                .where(tables.conversations.c.id == row["id"])
                .values(
                    archived_at=func.clock_timestamp() if archived else None,
                    updated_at=func.clock_timestamp(),
                )
            )
        return {"archived": archived}
