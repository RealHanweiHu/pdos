"""Named disposition of actual-result feedback against a real definition revision."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.experiment_feedback import field_values
from app.domain.product_definitions import _row as definition_row
from app.domain.product_result_feedback import (
    ResultRead,
    conditions,
    prepared,
    project_access,
    target,
)
from app.domain.product_workspace import ProductWorkError, _emit, _line, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class FollowupInbox(Contract):
    revision_id: UUID
    before_id: UUID | None = None


class FollowupOptions(Contract):
    feedback_id: UUID
    before_revision: int | None = Field(default=None, ge=1)


class FollowupRead(Contract):
    feedback_id: UUID
    revision_id: UUID | None = None
    before_version: int | None = Field(default=None, ge=1)


class FieldResponse(Contract):
    original_path: str = Field(min_length=1, max_length=1024)
    revision_path: str | None = Field(default=None, min_length=1, max_length=1024)
    treatment: Literal["changed", "retained", "removed", "needs_evidence"]
    explanation: Text

    @model_validator(mode="after")
    def removed(self) -> Self:
        if self.treatment == "removed" and self.revision_path is not None:
            raise ValueError("移除条目不能同时关联现有字段，请说明移除依据")
        return self


class FollowupPreview(Contract):
    feedback_id: UUID
    revision_id: UUID | None = None
    expected_digest: Digest
    action: Literal["link_revision", "no_change", "needs_evidence", "withdrawn"]
    responses: tuple[FieldResponse, ...] = Field(min_length=1, max_length=20)
    reason: Text
    limitations: Text

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (self.action == "link_revision") != (self.revision_id is not None):
            raise ValueError("关联后续修订须明确选择实际版本；其他处置不同时关联修订")
        if len({r.original_path for r in self.responses}) != len(self.responses):
            raise ValueError("每项原反馈字段须单独回应且不能重复")
        if self.action != "link_revision" and any(r.revision_path for r in self.responses):
            raise ValueError("未关联修订时不能指定修订字段")
        return self


class FollowupSave(FollowupPreview):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_preview_digest: Digest


def feedback(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> Any:
    t = tables.product_result_feedback
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
        raise ProductWorkError("原反馈不存在或不可读取")
    project_access(c, context, row["project_id"])
    target(c, context, space, row["definition_id"])
    return row


def original_query(row: Any) -> ResultRead:
    return ResultRead(
        definition_id=row["definition_id"],
        project_id=row["project_id"],
        source_kind=row["source_kind"],
        source_id=row["source_id"],
    )


def basis(
    c: Connection, context: AuthContext, space: UUID, query: FollowupRead, *, write: bool = False
) -> dict[str, Any]:
    row = feedback(c, context, space, query.feedback_id)
    definition = target(c, context, space, row["definition_id"], write=write)
    current = prepared(c, context, space, original_query(row))
    f = tables.product_result_feedback
    latest = c.execute(
        select(func.max(f.c.version)).where(*conditions(context, original_query(row)))
    ).scalar_one()
    revision = None
    if query.revision_id:
        candidate = definition_row(c, context, space, query.revision_id)
        if (
            candidate["series_id"] != definition["series_id"]
            or candidate["revision_number"] <= definition["revision_number"]
        ):
            raise ProductWorkError("请选择同一定义系列的真实后续修订")
        if write:
            _line(c, context, space, candidate["product_line_id"], access="manager", writable=True)
        revision = _plain(candidate)
    body = {
        "feedback": _plain(row),
        "current_source": current,
        "feedback_is_latest": row["version"] == latest,
        "sources_current": current["digest"] == row["source_digest"],
        "revision": revision,
        "revision_fields": field_values("definition", revision) if revision else [],
        "policy_version": "actual-result-followup.v1",
    }
    return {**body, "digest": digest(body)}


def preview(
    c: Connection,
    context: AuthContext,
    space: UUID,
    command: FollowupPreview,
    *,
    write: bool = False,
) -> dict[str, Any]:
    current = basis(
        c,
        context,
        space,
        FollowupRead(feedback_id=command.feedback_id, revision_id=command.revision_id),
        write=write,
    )
    if current["digest"] != command.expected_digest:
        raise ProductWorkError("反馈、实际依据或修订已变化，请重新读取核对")
    if not current["feedback_is_latest"] and command.action != "withdrawn":
        raise ProductWorkError("原反馈已被后续回应替代，请从最新回应继续；原处置仍可撤回")
    f = current["feedback"]
    if f["verdict"] == "withdrawn" and command.action != "withdrawn":
        raise ProductWorkError("已撤回反馈不能继续采用")
    if command.action == "link_revision" and (
        f["verdict"] != "adopt_for_followup"
        or not current["sources_current"]
        or not current["current_source"]["inheritance_current"]
    ):
        raise ProductWorkError("关联修订须为当前采用的反馈且原依据仍有效，请先沿原反馈重新核对")
    originals = {v["path"]: v for v in f["selected_fields"]}
    fields = {v["path"]: v for v in current["revision_fields"]}
    if set(originals) != {r.original_path for r in command.responses}:
        raise ProductWorkError("请逐项回应原反馈全部字段，不能增加未反馈项或漏项")
    outcomes = []
    for response in command.responses:
        new = fields.get(response.revision_path) if response.revision_path else None
        if response.revision_path and new is None:
            raise ProductWorkError("修订字段已不存在，请重新选择实际字段")
        if (
            command.action == "link_revision"
            and response.treatment in {"changed", "retained"}
            and new is None
        ):
            raise ProductWorkError("调整或保留须明确对应修订中的实际字段；移除/待补证须说明依据")
        if command.action != "link_revision" and response.treatment in {"changed", "removed"}:
            raise ProductWorkError("尚未关联实际修订，不能声明字段已调整或移除")
        outcomes.append(
            {
                "response": response.model_dump(mode="json"),
                "original": originals[response.original_path],
                "revision_field": new,
                "values_equal": originals[response.original_path]["value"] == new["value"]
                if new
                else None,
            }
        )
    body = {
        "basis": current,
        "action": command.action,
        "responses": outcomes,
        "reason": command.reason,
        "limitations": command.limitations,
    }
    return {**body, "digest": digest(body)}


def followup_scope(context: AuthContext, identity: UUID) -> tuple[Any, ...]:
    t = tables.product_result_followups
    return t.c.tenant_id == context.tenant.id, t.c.feedback_id == identity


class ProductResultFollowupService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def inbox(self, context: AuthContext, space: UUID, query: FollowupInbox) -> dict[str, Any]:
        from app.domain.product_workspace import _space

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _space(c, context, space, allow_archived=True)
            definition_row(c, context, space, query.revision_id)
            t = tables.product_result_followups
            q = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.revision_id == query.revision_id,
            )
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            items = []
            for value in values[:20]:
                try:
                    f = feedback(c, context, space, value["feedback_id"])
                except (ValueError, PermissionError):
                    continue
                last = c.execute(
                    select(func.max(t.c.version)).where(*followup_scope(context, f["id"]))
                ).scalar_one()
                originals = tables.product_result_feedback
                latest = c.execute(
                    select(func.max(originals.c.version)).where(
                        *conditions(context, original_query(f))
                    )
                ).scalar_one()
                items.append(
                    {
                        "id": str(value["id"]),
                        "feedback_id": str(f["id"]),
                        "version": value["version"],
                        "is_latest": value["version"] == last,
                        "feedback_is_latest": f["version"] == latest,
                        "definition_id": str(f["definition_id"]),
                        "project_id": str(f["project_id"]),
                        "source_kind": f["source_kind"],
                        "finding": f["finding"],
                        "reason": value["snapshot"]["reason"],
                        "created_at": value["created_at"].isoformat(),
                    }
                )
            return {
                "items": items,
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def options(self, context: AuthContext, space: UUID, query: FollowupOptions) -> dict[str, Any]:
        with self.engine.connect() as c:
            f = feedback(c, context, space, query.feedback_id)
            original = definition_row(c, context, space, f["definition_id"])
            t = tables.product_definitions
            q = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.series_id == original["series_id"],
                t.c.revision_number > original["revision_number"],
            )
            if query.before_revision:
                q = q.where(t.c.revision_number < query.before_revision)
            values = c.execute(q.order_by(t.c.revision_number.desc()).limit(21)).mappings().all()
            items = []
            for row in values[:20]:
                try:
                    definition_row(c, context, space, row["id"])
                except PermissionError:
                    continue
                items.append(
                    {
                        k: _plain(row)[k]
                        for k in (
                            "id",
                            "title",
                            "revision_number",
                            "version",
                            "state",
                            "published_at",
                        )
                    }
                )
            return {
                "items": items,
                "next_before_revision": values[19]["revision_number"] if len(values) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, query: FollowupRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            current = basis(c, context, space, query)
            can_manage = True
            try:
                target(c, context, space, UUID(current["feedback"]["definition_id"]), write=True)
            except (ValueError, PermissionError):
                can_manage = False
            t = tables.product_result_followups
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(
                    *followup_scope(context, query.feedback_id)
                )
            ).scalar_one()
            q = select(t).where(*followup_scope(context, query.feedback_id))
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            items = []
            for value in values[:20]:
                revision = None
                if value["revision_id"]:
                    try:
                        revision = _plain(definition_row(c, context, space, value["revision_id"]))
                    except PermissionError:
                        # An old snapshot must not bypass a subsequently restricted product line.
                        continue
                items.append(
                    {
                        **_plain(value),
                        "current_revision": revision,
                        "revision_unchanged": revision == value["snapshot"]["basis"]["revision"],
                        "sources_current": current["current_source"]["digest"]
                        == value["snapshot"]["basis"]["current_source"]["digest"],
                    }
                )
            return {
                "basis": current,
                "version": version,
                "can_manage": can_manage,
                "items": items,
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def preview(
        self, context: AuthContext, space: UUID, command: FollowupPreview
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, space, command)

    def save(self, context: AuthContext, space: UUID, command: FollowupSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            f = feedback(c, context, space, command.feedback_id)
            if not lock_project_write_scope(
                c, tenant_id=context.tenant.id, project_id=f["project_id"]
            ):
                raise ProductWorkError("原项目不可用")
            target(c, context, space, f["definition_id"], write=True)
            t = tables.product_result_followups
            signature = digest({"space": str(space), "command": command.model_dump(mode="json")})
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写反馈落实")
                if old["revision_id"]:
                    definition_row(c, context, space, old["revision_id"])
                return _plain(old)
            current = preview(c, context, space, command, write=True)
            previous = (
                c.execute(
                    select(t)
                    .where(*followup_scope(context, command.feedback_id))
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            version = previous["version"] if previous else 0
            if (
                version != command.expected_version
                or current["digest"] != command.expected_preview_digest
            ):
                raise ProductWorkError("处置版本或预览已变化，请重新读取")
            if command.action == "withdrawn" and previous is None:
                raise ProductWorkError("尚无处置可撤回")
            value = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        project_id=f["project_id"],
                        definition_id=f["definition_id"],
                        feedback_id=f["id"],
                        revision_id=command.revision_id,
                        version=version + 1,
                        previous_id=previous["id"] if previous else None,
                        action=command.action,
                        snapshot=current,
                        preview_digest=current["digest"],
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _emit(
                c,
                context,
                space,
                "product_result_followup",
                "recorded",
                {"id": value["id"], "feedback_id": f["id"], "version": value["version"]},
            )
            return _plain(value)
