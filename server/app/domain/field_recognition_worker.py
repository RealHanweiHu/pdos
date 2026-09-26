"""Bounded offline recognition worker; recheck source, actor and project before publication."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext, AuthRepository
from app.db.schema import tables
from app.domain.field_captures import CaptureError, FieldCaptureService
from app.domain.field_recognitions import ERRORS, expire, profile
from app.storage.documents import DocumentObjectStore


class RecognitionWorker:
    def __init__(self, engine: Engine, store: DocumentObjectStore):
        self.engine, self.store = engine, store

    def authorized(self, row: Any, connection: Connection | None = None) -> AuthContext:
        actor = AuthRepository(self.engine).find_user_context(row["created_by_user_id"])
        if (
            actor is None
            or actor.tenant.id != row["tenant_id"]
            or not actor.user.is_active
            or actor.tenant.status != "active"
        ):
            raise CaptureError("access_changed")
        with nullcontext(connection) if connection is not None else self.engine.connect() as c:
            source = FieldCaptureService(self.engine).row(
                c, actor, row["project_id"], row["capture_id"], write=True
            )
            if source["submitted_at"] or source["sha256"] != row["source_sha256"]:
                raise CaptureError("access_changed")
        return actor

    def current(self, row: Any) -> bool:
        with self.engine.connect() as c:
            t = tables.field_capture_recognitions
            return (
                c.execute(
                    select(t.c.id).where(
                        t.c.id == row["id"], t.c.status == "running", t.c.expires_at > func.now()
                    )
                ).first()
                is not None
            )

    def run_next(self) -> bool:
        t = tables.field_capture_recognitions
        with self.engine.begin() as c:
            expire(c)
            row = (
                c.execute(
                    select(t)
                    .where(t.c.status == "queued")
                    .order_by(t.c.created_at, t.c.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return False
            row = (
                c.execute(
                    t.update()
                    .where(t.c.id == row["id"])
                    .values(
                        status="running",
                        started_at=func.now(),
                        expires_at=datetime.now(UTC) + timedelta(seconds=330),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
        result: dict[str, Any] | None = None
        error = "engine_failed"
        try:
            actor = self.authorized(row)
            if profile(row["kind"]) != row["profile"]:
                raise CaptureError("profile_changed")
            content, _ = FieldCaptureService(self.engine, self.store).original(
                actor, row["project_id"], row["capture_id"]
            )
            output = self.extract(row, content)
            if output.get("error"):
                error = output["error"] if output["error"] in ERRORS else "engine_failed"
            else:
                result = output["result"]
                if not isinstance(result, dict) or len(result.get("text", "")) > 16000:
                    raise CaptureError("invalid_output")
                self.authorized(row)
        except CaptureError as failure:
            error = str(failure) if str(failure) in ERRORS else "access_changed"
            result = None
        except Exception:
            # Original content and decoder exception text are deliberately not normal log output.
            result = None
        with self.engine.begin() as c:
            # Same lock order as human draft submission: original, then extraction.
            c.execute(
                select(tables.field_captures.c.id)
                .where(tables.field_captures.c.id == row["capture_id"])
                .with_for_update()
            )
            if result is not None:
                try:
                    actor = self.authorized(row, c)
                    FieldCaptureService.authorize(c, actor, row["project_id"], write=True)
                except Exception:
                    result, error = None, "access_changed"
            c.execute(
                t.update()
                .where(t.c.id == row["id"], t.c.status == "running", t.c.expires_at > func.now())
                .values(
                    status="succeeded" if result is not None else "failed",
                    result=result,
                    error_code=None if result is not None else error,
                    completed_at=func.now(),
                )
            )
        return True

    def extract(self, row: Any, content: bytes) -> dict[str, Any]:
        timeout = 120 if row["kind"] == "ocr" else 300
        with tempfile.TemporaryDirectory(prefix="pdos-capture-") as directory:
            root = Path(directory)
            source, config, target = root / "original", root / "config.json", root / "result.json"
            source.write_bytes(content)
            config.write_text(json.dumps(row["profile"] | {"language": row["language"]}))
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": directory,
                "TMPDIR": directory,
                "LANG": "C.UTF-8",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "OMP_NUM_THREADS": "2",
                "OPENBLAS_NUM_THREADS": "2",
            }
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.domain.field_recognition_engine",
                    str(source),
                    str(config),
                    str(target),
                ],
                cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            try:
                while child.poll() is None:
                    if time.monotonic() >= deadline:
                        raise CaptureError("expired")
                    if not self.current(row):
                        raise CaptureError("cancelled")
                    self.authorized(row)
                    time.sleep(1)
                if child.returncode or not target.is_file() or target.stat().st_size > 2 * 1024**2:
                    raise CaptureError("engine_failed")
                value: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
                return value
            finally:
                # Includes an OCR subprocess if the owning Python worker was cancelled.
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
