"""Human-requested offline extraction queue; extracted words never apply business changes."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, false, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.field_captures import CaptureError, FieldCaptureService
from app.domain.product_workspace import _plain
from app.settings import get_settings

ERRORS = {
    "expired": "等待或处理已超时，请明确重试。原件与已有草稿仍保留。",
    "cancelled": "已停止识别，原件与已有草稿仍保留。",
    "access_changed": "原发起人、项目权限或记录状态已变化，识别已停止。",
    "profile_changed": "识别配置已变化，请重新发起。",
    "model_changed": "本地模型与固定版本不一致，需管理员核对。",
    "model_unavailable": "本地模型不完整或不可读取。",
    "engine_version": "照片识别需要 Tesseract 5。",
    "image_limit": "照片须为单张图像，且不超过2400万像素。",
    "audio_limit": "现场录音仅支持不超过5分钟，请拆分后上传。",
    "audio_streams": "请选择仅含一条音轨的录音。",
    "output_limit": "识别文字过长，请拆分资料后重试；未保存截断的结果。",
    "invalid_audio": "无法读取此录音，请核对原件。",
    "invalid_output": "识别未返回可用结果。",
    "engine_failed": "识别未完成，请核对原件或联系管理员检查本地引擎。",
}


def profile(kind: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.capture_recognition_enabled:
        return None
    if kind == "ocr":
        root, fingerprint = settings.capture_tessdata_dir, settings.capture_tessdata_sha256
        executable = settings.capture_tesseract_path
        if (
            not executable
            or not Path(executable).is_absolute()
            or not os.access(executable, os.X_OK)
            or importlib.util.find_spec("PIL") is None
        ):
            return None
    else:
        root, fingerprint = settings.capture_whisper_dir, settings.capture_whisper_sha256
        executable = None
        if importlib.util.find_spec("faster_whisper") is None:
            return None
    if not root or not Path(root).is_absolute() or not Path(root).is_dir() or not fingerprint:
        return None
    return {
        "kind": kind,
        "model_dir": root,
        "model_sha256": fingerprint,
        "executable": executable,
        "policy_version": "field-extraction-1",
    }


def public(row: Any, *, include_result: bool = True) -> dict[str, Any]:
    return _plain(
        {k: v for k, v in row.items() if k != "profile" and (include_result or k != "result")}
    ) | {"message": ERRORS.get(row["error_code"], "")}


def expire(c: Connection, tenant: UUID | None = None, capture: UUID | None = None) -> None:
    t = tables.field_capture_recognitions
    statement = t.update().where(
        t.c.status.in_(("queued", "running")), t.c.expires_at <= func.now()
    )
    if tenant is not None:
        statement = statement.where(t.c.tenant_id == tenant)
    if capture is not None:
        statement = statement.where(t.c.capture_id == capture)
    c.execute(statement.values(status="failed", error_code="expired", completed_at=func.now()))


def require_source(c: Connection, ctx: AuthContext, capture: UUID, identity: UUID | None) -> None:
    if identity is None:
        return
    t = tables.field_capture_recognitions
    if (
        c.execute(
            select(t.c.id).where(
                t.c.id == identity,
                t.c.tenant_id == ctx.tenant.id,
                t.c.capture_id == capture,
                t.c.created_by_user_id == ctx.user.id,
                t.c.status == "succeeded",
            )
        ).first()
        is None
    ):
        raise CaptureError("识别来源不是此记录已完成的结果，请重新核对")


class FieldRecognitionService:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.captures = FieldCaptureService(engine)

    def list(self, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.begin() as c:
            source = self.captures.row(c, ctx, project, identity)
            t = tables.field_capture_recognitions
            q = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.capture_id == identity)
            own = source["created_by_user_id"] == ctx.user.id
            if not own:
                adopted = (source["review"] or {}).get("recognition_id")
                q = q.where(t.c.id == UUID(adopted)) if adopted else q.where(false())
            expire(c, ctx.tenant.id, identity)
            items = [
                public(r, include_result=False)
                for r in c.execute(
                    q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(20)
                ).mappings()
            ]
            return {
                "items": items,
                "available": {k: own and profile(k) is not None for k in ("ocr", "speech")},
                "availability_note": "需配置本地引擎、固定模型和识别工作进程；暂可人工填写。",
            }

    def get(
        self, ctx: AuthContext, project: UUID, identity: UUID, recognition: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            source = self.captures.row(c, ctx, project, identity)
            if source["created_by_user_id"] != ctx.user.id and (source["review"] or {}).get(
                "recognition_id"
            ) != str(recognition):
                raise CaptureError("只能读取已明确采用的识别结果")
            t = tables.field_capture_recognitions
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.capture_id == identity,
                        t.c.id == recognition,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise CaptureError("识别记录不存在")
            return public(row)

    def request(
        self, ctx: AuthContext, project: UUID, identity: UUID, request_id: UUID, language: str
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"field-recognition:{ctx.tenant.id}:{ctx.user.id}"},
            )
            source = self.captures.row(c, ctx, project, identity, write=True)
            t = tables.field_capture_recognitions
            prior = c.execute(select(t).where(t.c.id == request_id)).mappings().one_or_none()
            if prior is not None:
                if (
                    prior["tenant_id"] != ctx.tenant.id
                    or prior["capture_id"] != identity
                    or prior["created_by_user_id"] != ctx.user.id
                    or prior["language"] != language
                ):
                    raise CaptureError("此请求编号已使用，请刷新核对")
                return public(prior)
            if source["submitted_at"] or not source["uploaded_at"]:
                raise CaptureError("只能识别尚未提交且原件已上传的现场记录")
            kind = "ocr" if source["media_type"].startswith("image/") else "speech"
            if kind == "ocr" and language == "auto":
                raise CaptureError("照片请选择中文与英文或仅英文")
            config = profile(kind)
            if config is None:
                raise CaptureError("本地识别引擎或模型尚未配置，可继续人工填写")
            expire(c, ctx.tenant.id, identity)
            active = c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.capture_id == identity,
                    t.c.status.in_(("queued", "running")),
                )
            ).first()
            if active:
                raise CaptureError("此原件正在识别，请等待或先停止当前识别")
            outstanding = c.execute(
                select(func.count())
                .select_from(t)
                .where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.created_by_user_id == ctx.user.id,
                    t.c.status.in_(("queued", "running")),
                )
            ).scalar_one()
            if outstanding >= 3:
                raise CaptureError("已有3份资料等待识别，请先完成或停止后继续")
            row = (
                c.execute(
                    insert(t)
                    .values(
                        id=request_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        capture_id=identity,
                        created_by_user_id=ctx.user.id,
                        kind=kind,
                        language=language,
                        source_sha256=source["sha256"],
                        profile=config,
                        status="queued",
                        expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return public(row)

    def cancel(
        self, ctx: AuthContext, project: UUID, identity: UUID, recognition: UUID
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            self.captures.row(c, ctx, project, identity, write=True)
            t = tables.field_capture_recognitions
            row = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.capture_id == identity,
                        t.c.id == recognition,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise CaptureError("识别记录不存在")
            if row["status"] in {"queued", "running"}:
                row = (
                    c.execute(
                        t.update()
                        .where(t.c.id == recognition)
                        .values(status="cancelled", error_code="cancelled", completed_at=func.now())
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
            return public(row)
