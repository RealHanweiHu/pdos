"""D56 export over real HTTP and PostgreSQL: same reads as the pages, audit, AI refusal.

Every business row is created by the existing command fixtures; nothing here
inserts a task, BOM or result directly. Only the isolated pdos_test is used.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import hashlib
import json
import os
import secrets
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
from openpyxl import load_workbook
from originals.test_original_security import security_work as original_security_work  # noqa: F401
from projects.work_pg.test_workflow import ASSIGN, CREATE, execute, payload, task
from projects.work_pg.test_workflow import work as work  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.core.database import tenant_session
from pdos_next.core.models import Grant, LoginSession, Principal, now
from pdos_next.core.service import Context, digest
from pdos_next.domain.exports import service
from pdos_next.domain.exports.models import ExportAudit
from pdos_next.domain.exports.workbook import AI_LABEL, HUMAN_LABEL
from pdos_next.errors import DomainError


def reader(setup, *, name="Synthetic read-only member", write=False):
    """A real member with a read-only category Grant and a login."""
    principal, token = uuid4(), secrets.token_urlsafe(32)
    with Session(setup.admin) as s, s.begin():
        s.add(Principal(id=principal, tenant_id=setup.tenant, name=name, kind="human"))
        s.flush()
        s.add_all(
            [
                Grant(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    principal_id=principal,
                    can_write=write,
                    expires_at=now() + timedelta(hours=1),
                ),
                LoginSession(
                    tenant_id=setup.tenant,
                    principal_id=principal,
                    token_hash=digest(token),
                    expires_at=now() + timedelta(hours=1),
                ),
            ]
        )
    setup.tokens[principal] = token
    return principal


def auth(setup, actor):
    return {"Authorization": f"Bearer {setup.tokens[actor]}"}


def audits(setup):
    with Session(setup.admin) as s:
        return list(
            s.scalars(
                select(ExportAudit)
                .where(ExportAudit.tenant_id == setup.tenant)
                .order_by(ExportAudit.created_at)
            )
        )


def book(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(service.XLSX)
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    return load_workbook(BytesIO(response.content))


def data_rows(sheet):
    return [[c.value for c in row] for row in sheet.iter_rows(min_row=2) if row[0].value]


def checked_audit(setup, response, *, actor, view, rows):
    [last] = audits(setup)[-1:]
    assert str(last.id) == response.headers["x-pdos-export-id"]
    assert last.actor_id == actor and last.view == view and last.row_count == rows
    assert last.content_sha256 == hashlib.sha256(response.content).hexdigest()
    assert last.byte_size == len(response.content) and last.file_format == "xlsx"
    assert last.contains_ai is (last.ai_row_count + last.ai_cell_count > 0)
    assert int(response.headers["x-pdos-export-rows"]) == rows
    return last


def test_project_export_matches_page_for_two_roles_and_hides_private_project(work):
    setup = work.setup
    root = f"/v1/categories/{setup.category}/products/{setup.product}"
    created = execute(
        work,
        CREATE,
        payload(
            work,
            title='=HYPERLINK("http://x","合成图纸交付")',
            goal="分别交付图纸与检验结果",
            outcomes=[{"key": "drawing", "text": "固定图纸", "required": True}],
            plan_task=None,
        ),
    )[1]
    work.task_id = UUID(created["result"]["task_id"])
    execute(
        work,
        ASSIGN,
        payload(
            work,
            task=task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )
    readonly = reader(setup)
    product = setup.product
    private = create_g0_project(
        setup, visibility="private", name="Synthetic private project", purpose="Private audience"
    )
    setup.product = product  # create_g0_project moves setup to its new product.
    private_root = f"/v1/categories/{setup.category}/products/{private.product_id}"
    for actor in (setup.human, readonly):
        page = setup.client.get(
            root + f"/project-work?project_id={work.project_id}", headers=auth(setup, actor)
        )
        assert page.status_code == 200, page.text
        before = len(audits(setup))
        response = setup.client.get(
            root + f"/exports/project?project_id={work.project_id}", headers=auth(setup, actor)
        )
        workbook = book(response)
        assert len(audits(setup)) == before + 1
        assert workbook.sheetnames == ["说明", "任务", "风险与待决项", "承诺", "状态更新"]
        tasks = data_rows(workbook["任务"])
        assert len(tasks) == len(page.json()["tasks"]) == 1
        assert tasks[0][0] == HUMAN_LABEL and tasks[0][1] == '=HYPERLINK("http://x","合成图纸交付")'
        assert workbook["任务"].cell(2, 2).data_type == "s"
        assert len(data_rows(workbook["风险与待决项"])) == len(page.json()["g0_open_items"])
        rows = sum(len(data_rows(workbook[n])) for n in workbook.sheetnames[1:])
        audit = checked_audit(setup, response, actor=actor, view="project", rows=rows)
        assert audit.category_id == setup.category and audit.project_id == work.project_id
        assert audit.contains_ai is False and audit.ai_row_count == 0
        props = {p.name: p.value for p in workbook.custom_doc_props.props}
        assert json.loads(props["AIGC"])["Label"] == "0"
        assert props["PDOS.ExportId"] == str(audit.id)

    # Private audience: the owner exports; category members outside the audience (one
    # writer, one read-only) get exactly what the page gives, and no audit row or file.
    owner = setup.client.get(
        private_root + f"/exports/project?project_id={private.project_id}",
        headers=auth(setup, setup.human),
    )
    assert owner.status_code == 200, owner.text
    outsider = reader(setup, name="Synthetic writer outside audience", write=True)
    for actor in (outsider, readonly):
        page = setup.client.get(
            private_root + f"/project-work?project_id={private.project_id}",
            headers=auth(setup, actor),
        )
        before = len(audits(setup))
        refused = setup.client.get(
            private_root + f"/exports/project?project_id={private.project_id}",
            headers=auth(setup, actor),
        )
        assert page.status_code in {403, 404}
        assert refused.status_code == page.status_code, refused.text
        assert refused.headers["content-type"].startswith("application/json")
        assert len(audits(setup)) == before
    # Another tenant's login and an unknown parameter never export.
    before = len(audits(setup))
    other = setup.client.get(
        root + f"/exports/project?project_id={work.project_id}",
        headers=auth(setup, setup.other_human),
    )
    assert other.status_code in {401, 403, 404}
    extra = setup.client.get(
        root + f"/exports/project?project_id={work.project_id}&view=all",
        headers=auth(setup, setup.human),
    )
    assert extra.status_code == 422 and len(audits(setup)) == before


def test_my_work_export_reads_personal_queues_and_audit_is_private(work):
    setup = work.setup
    created = execute(
        work,
        CREATE,
        payload(
            work,
            title="合成待接收任务",
            goal="待承接",
            outcomes=[{"key": "drawing", "text": "固定图纸", "required": True}],
            plan_task=None,
        ),
    )[1]
    work.task_id = UUID(created["result"]["task_id"])
    execute(
        work,
        ASSIGN,
        payload(
            work,
            task=task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )
    page = setup.client.get(
        "/v1/personal/attention?queue=receive&page_size=100", headers=auth(setup, setup.peer)
    )
    assert page.status_code == 200, page.text
    response = setup.client.get("/v1/personal/exports/my-work", headers=auth(setup, setup.peer))
    workbook = book(response)
    assert workbook.sheetnames == [
        "说明",
        "待我决定",
        "待我接收",
        "待我验收",
        "外部等待",
        "我的任务",
        "我的承诺",
    ]
    received = data_rows(workbook["待我接收"])
    assert len(received) == page.json()["total_records"] >= 1
    assert all(row[0] == HUMAN_LABEL for row in received)
    assert any(row[1] and "合成待接收任务" in row[1] for row in received)
    rows = sum(len(data_rows(workbook[n])) for n in workbook.sheetnames[1:])
    audit = checked_audit(setup, response, actor=setup.peer, view="my_work", rows=rows)
    assert audit.category_id is None and audit.product_id is None
    # The exporter reads their own audit row; another member does not.
    for actor, expected in ((setup.peer, 1), (setup.human, 0)):
        with tenant_session(setup.engine, setup.tenant, actor_id=actor, requester_id=actor) as s:
            assert (
                s.scalar(
                    select(func.count()).select_from(ExportAudit).where(ExportAudit.id == audit.id)
                )
                == expected
            )


def test_ai_identity_and_delegated_contexts_never_export_or_audit(work):
    setup = work.setup
    before = len(audits(setup))
    for ctx in (
        Context(setup.tenant, setup.agent, setup.human, category_id=setup.category),
        Context(setup.tenant, setup.agent, setup.agent, category_id=setup.category),
        Context(
            setup.tenant, setup.human, setup.human, category_id=setup.category, agent_run_id=uuid4()
        ),
        Context(setup.tenant, setup.human, setup.human, category_id=setup.category, run_id=uuid4()),
    ):
        with pytest.raises(DomainError) as error:
            service.export(
                setup.engine, ctx, "project", product_id=setup.product, project_id=work.project_id
            )
        assert error.value.code == "FORBIDDEN_SCOPE"
    assert len(audits(setup)) == before
    # Database boundary: even a direct insert under the AI identity is refused.
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.agent,
            category_id=setup.category,
        ) as s:
            s.add(
                ExportAudit(
                    tenant_id=setup.tenant,
                    actor_id=setup.agent,
                    category_id=setup.category,
                    product_id=setup.product,
                    project_id=work.project_id,
                    view="project",
                    scope={},
                    row_count=0,
                    ai_row_count=0,
                    ai_cell_count=0,
                    contains_ai=False,
                    sheet_rows={},
                    file_format="xlsx",
                    filename="x.xlsx",
                    content_sha256="0" * 64,
                    byte_size=1,
                    marker_version="pdos-ai-label/v1",
                )
            )
            s.flush()
    # Audit rows are append-only for the application role.
    ok = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}"
        f"/exports/project?project_id={work.project_id}",
        headers=auth(setup, setup.human),
    )
    assert ok.status_code == 200, ok.text
    audit_id = UUID(ok.headers["x-pdos-export-id"])
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as s:
            row = s.get(ExportAudit, audit_id)
            row.row_count = 999
            s.flush()


def test_ai_drafted_rows_and_fields_reach_the_workbook(work, monkeypatch):
    """Provenance over real version rows: which receipts count as AI is the only stub.

    One task's creation receipt and another task's assignment receipt are treated as
    AI-written; the real agent principal is checked separately without any stub.
    """
    from pdos_next.domain.exports import views

    setup = work.setup

    def create(title):
        return execute(
            work,
            CREATE,
            payload(
                work,
                title=title,
                goal="核对来源标识",
                outcomes=[{"key": "drawing", "text": "固定图纸", "required": True}],
                plan_task=None,
            ),
        )[1]

    drafted = create("合成 AI 起草任务")
    human = create("合成人工任务，AI 分派")
    work.task_id = UUID(human["result"]["task_id"])
    assigned = execute(
        work,
        ASSIGN,
        payload(
            work,
            task=task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )[1]
    marked = {drafted["id"], assigned["id"]}
    real = views.Provenance

    class AgentWrote(real):
        def ai(self, *, actor=None, receipt=None, subject=None):
            return (receipt is not None and str(receipt) in marked) or super().ai(
                actor=actor, receipt=receipt, subject=subject
            )

    monkeypatch.setattr(views, "Provenance", AgentWrote)
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}"
        f"/exports/project?project_id={work.project_id}",
        headers=auth(setup, setup.human),
    )
    workbook = book(response)
    if target := os.environ.get("D56_EVIDENCE_XLSX"):  # Optional evidence copy only.
        Path(target).write_bytes(response.content)
    sheet = workbook["任务"]
    header = [c.value for c in sheet[1]]
    rows = {
        r[header.index("任务编号")]: dict(zip(header, r, strict=True)) for r in data_rows(sheet)
    }
    whole = rows[drafted["result"]["task_id"]]
    part = rows[human["result"]["task_id"]]
    assert whole["来源"] == AI_LABEL and whole["AI 起草字段"] is None
    assert part["来源"] == "部分 AI 起草"
    assert set(part["AI 起草字段"].split("、")) == {"状态", "执行人", "验收人"}
    column = header.index("执行人") + 1
    row = 2 + [r[header.index("任务编号")] for r in data_rows(sheet)].index(
        human["result"]["task_id"]
    )
    assert sheet.cell(row, column).comment.text == AI_LABEL
    assert sheet.cell(row, header.index("任务") + 1).comment is None
    total = sum(len(data_rows(workbook[n])) for n in workbook.sheetnames[1:])
    audit = checked_audit(setup, response, actor=setup.human, view="project", rows=total)
    assert audit.contains_ai is True and audit.ai_row_count == 1 and audit.ai_cell_count == 3
    props = {p.name: p.value for p in workbook.custom_doc_props.props}
    assert json.loads(props["AIGC"])["Label"] == "1" and props["PDOS.AIDraftCells"] == 3
    assert workbook["说明"].cell(1, 1).value.startswith("本文件含 AI 生成内容")
    # Unstubbed: the real agent principal of this tenant is recognised; a human is not.
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        prov = real(s, setup.ctx, actors=[setup.agent, setup.human], receipts=[drafted["id"]])
        assert prov.ai(actor=setup.agent) and not prov.ai(actor=setup.human)
        assert not prov.ai(receipt=drafted["id"])
