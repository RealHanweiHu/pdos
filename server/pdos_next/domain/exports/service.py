"""Permission-filtered Excel export (D56): read as the page does, label AI, audit, deliver.

Export is a READ by the named human reader (`export.workbook.download`). The AI
identity, a run context or a delegated requester never starts one. The file is
returned only after its audit row is committed; an audit failure returns no file.
"""

import hashlib
import re
from datetime import UTC
from uuid import uuid4

from pdos_next.core.database import tenant_session
from pdos_next.core.models import Principal, now
from pdos_next.errors import DomainError

from . import views
from .models import ExportAudit
from .workbook import MARKER_VERSION, render

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OPERATION = "export.workbook.download"
_TITLES = {
    "project": "项目",
    "my_work": "我的工作",
    "bom_diff": "BOM差异",
    "test_summary": "测试汇总",
}


def _refuse():
    raise DomainError(
        "FORBIDDEN_SCOPE",
        "导出只能由具名本人发起；小Pai 与运行身份不能导出。",
        403,
        detail={"operation": OPERATION},
    )


def _guard(ctx):
    if (
        ctx.run_id is not None
        or ctx.agent_run_id is not None
        or ctx.agent_call_id is not None
        or ctx.actor_id != ctx.requester_id
    ):
        _refuse()


def _filename(view, title, at):
    stem = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", title).strip(" ._")[:80] or _TITLES[view]
    return f"{_TITLES[view]}-{stem}-{at:%Y%m%d-%H%M}.xlsx"


def export(engine, ctx, view, *, product_id=None, project_id=None, bom_id=None, build_id=None):
    _guard(ctx)
    personal = view == "my_work"
    if personal != (ctx.category_id is None):
        raise DomainError("VALIDATION_FAILED", "导出范围与入口不一致。", 422)
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
        read_snapshot=True,
    ) as s:
        person = s.get(Principal, ctx.actor_id)
        if person is None or not person.active or person.kind != "human":
            _refuse()
        if view == "project":
            data = views.project(s, ctx, product_id, project_id)
        elif view == "my_work":
            data = views.my_work(s, ctx)
        elif view == "bom_diff":
            data = views.bom_diff(s, ctx, product_id, bom_id)
        elif view == "test_summary":
            data = views.test_summary(s, ctx, product_id, build_id)
        else:
            raise DomainError("VALIDATION_FAILED", "不支持的导出视图。", 422)
        exporter = person.name
    exported_at = now().astimezone(UTC)
    export_id = uuid4()
    rendered = render(data, export_id=str(export_id), exporter=exporter, exported_at=exported_at)
    filename = _filename(view, data.title.split("：", 1)[-1], exported_at)
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        s.add(
            ExportAudit(
                id=export_id,
                tenant_id=ctx.tenant_id,
                created_at=exported_at,
                actor_id=ctx.actor_id,
                category_id=ctx.category_id,
                product_id=product_id,
                project_id=project_id,
                view=view,
                scope={k: v for k, v in data.scope.items()},
                row_count=rendered.row_count,
                ai_row_count=rendered.ai_row_count,
                ai_cell_count=rendered.ai_cell_count,
                contains_ai=rendered.contains_ai,
                sheet_rows=rendered.sheet_rows,
                file_format="xlsx",
                filename=filename,
                content_sha256=hashlib.sha256(rendered.content).hexdigest(),
                byte_size=len(rendered.content),
                marker_version=MARKER_VERSION,
            )
        )
        s.flush()
    return export_id, filename, rendered
