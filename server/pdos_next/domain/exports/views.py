"""The four F41 views, each built from the read function its page already uses.

Every builder runs inside the reader's own read-snapshot session and calls the
existing page read, so row filtering (grants, private audience, project
membership, retained-receipt checks) and field selection are the page's own.
This module only flattens the result and adds AI provenance.
"""

from uuid import UUID

from sqlalchemy import select

from pdos_next.errors import DomainError

from .provenance import Provenance
from .workbook import Column, ExportView, Sheet, SheetRow

TASK_STATES = {
    "proposed": "待分派",
    "assigned": "待本人承接",
    "accepted": "已承接",
    "in_progress": "实际进行中",
    "submitted": "待成果验收",
    "completed": "成果已验收",
}
RUN_STATES = {
    "planned": "已固定测试计划",
    "running": "已登记开测",
    "results_pending": "待结果复核",
    "reviewed": "已具名复核",
    "disposed": "已具名处置",
}
RESULTS = {
    "pending": "尚未形成判定",
    "pass": "固定范围数值判定通过",
    "fail": "固定范围数值判定未通过",
    "indeterminate": "缺项，不能确定",
    "invalid": "已明确记录为无效",
}
QUEUE_TITLES = {
    "decide": "待我决定",
    "receive": "待我接收",
    "verify": "待我验收",
    "external": "外部等待",
}
WORK_TITLES = {"tasks": "我的任务", "commitments": "我的承诺"}
VISIBILITY = {"private": "私有", "category": "品类内", "audience": "指定受众"}


def _uuid(value):
    return value if isinstance(value, UUID) else UUID(str(value))


def _name(people, identity):
    if identity is None:
        return None
    return people.get(str(identity), str(identity))


def _outcomes(values):
    return [f"{'必需' if v.get('required') else '可选'}：{v.get('text')}" for v in values or ()]


# Project -------------------------------------------------------------------

_TASK_COLUMNS = (
    Column("title", "任务", 28),
    Column("goal", "目标", 36),
    Column("outcomes", "交付物", 36),
    Column("state", "状态", 12),
    Column("owner", "负责人", 12),
    Column("assignee", "执行人", 12),
    Column("recipient", "验收人", 12),
    Column("npi", "NPI 模板任务", 20),
    Column("actual_start", "实际开始", 22),
    Column("submission", "提交成果", 36),
    Column("review", "验收结论", 24),
    Column("revision", "版本", 8),
    Column("task_id", "任务编号", 38),
)
# Columns a later version can change; the author of a field is the version that last changed it.
_TASK_AUTHORED = tuple(c.key for c in _TASK_COLUMNS if c.key not in {"revision", "task_id"})


def _task_values(view, people):
    npi = view.get("npi_template") or {}
    submission, review = view.get("submission"), view.get("review")
    return {
        "title": view["title"],
        "goal": view["goal"],
        "outcomes": _outcomes(view["outcomes"]),
        "state": TASK_STATES.get(view["state"], view["state"]),
        "owner": _name(people, view["owner_id"]),
        "assignee": _name(people, view["assignee_id"]),
        "recipient": _name(people, view["recipient_id"]),
        "npi": f"{npi.get('phase_name')} · {npi.get('task_id')}" if npi else None,
        "actual_start": (view.get("actual_start") or {}).get("at"),
        "submission": [f"{r['key']}：{r['text']}（{r['status']}）" for r in submission["results"]]
        if submission
        else None,
        "review": f"{review['decision']} · {review['at']}" if review else None,
        "revision": view["revision"],
        "task_id": view["task_id"],
    }


def project(s, ctx, product_id, project_id) -> ExportView:
    from pdos_next.domain.projects.risk.models import ProjectRiskFollowup
    from pdos_next.domain.projects.work.models import WorkCommitmentVersion, WorkTaskVersion
    from pdos_next.domain.projects.work.service import workspace
    from pdos_next.domain.projects.work.views import task_view

    data = workspace(s, ctx, product_id, project_id)
    people = {m["id"]: m["name"] for m in data["members"]}
    task_ids = [_uuid(t["task_id"]) for t in data["tasks"]]
    versions = {}
    if task_ids:
        for row in s.scalars(
            select(WorkTaskVersion)
            .where(
                WorkTaskVersion.tenant_id == ctx.tenant_id,
                WorkTaskVersion.product_id == product_id,
                WorkTaskVersion.project_id == project_id,
                WorkTaskVersion.task_id.in_(task_ids),
            )
            .order_by(WorkTaskVersion.task_id, WorkTaskVersion.revision)
        ):
            versions.setdefault(str(row.task_id), []).append(row)
    commitment_rows = {
        str(row.id): row
        for row in s.scalars(
            select(WorkCommitmentVersion).where(
                WorkCommitmentVersion.tenant_id == ctx.tenant_id,
                WorkCommitmentVersion.id.in_(
                    [_uuid(c["id"]) for c in data["commitments"]] or [UUID(int=0)]
                ),
            )
        )
    }
    risk_ids = [
        _uuid(item["risk_followup"]["current"]["id"])
        for item in data["g0_open_items"]
        if (item.get("risk_followup") or {}).get("current")
    ]
    risk_rows = {
        str(row.id): row
        for row in s.scalars(
            select(ProjectRiskFollowup).where(
                ProjectRiskFollowup.tenant_id == ctx.tenant_id,
                ProjectRiskFollowup.id.in_(risk_ids or [UUID(int=0)]),
            )
        )
    }
    every = [v for rows in versions.values() for v in rows]
    prov = Provenance(
        s,
        ctx,
        actors=[
            *(v.actor_id for v in every),
            *(r.actor_id for r in commitment_rows.values()),
            *(r.actor_id for r in risk_rows.values()),
            *(u["actor_id"] for u in data["updates"]),
        ],
        receipts=[
            *(v.receipt_id for v in every),
            *(r.receipt_id for r in commitment_rows.values()),
            *(r.receipt_id for r in risk_rows.values()),
            *(u["receipt_id"] for u in data["updates"]),
        ],
    )

    task_rows = []
    for task in data["tasks"]:
        values = _task_values(task, people)
        authors, previous = {}, None
        for version in versions.get(task["task_id"], ()):
            current = _task_values(task_view(version, []), people)
            ai = prov.ai(actor=version.actor_id, receipt=version.receipt_id)
            for key in _TASK_AUTHORED:
                if previous is None or current[key] != previous[key]:
                    authors[key] = ai
            previous = current
        authored = [k for k in _TASK_AUTHORED if values[k] not in (None, "", [])]
        ai_fields = frozenset(k for k in authored if authors.get(k))
        task_rows.append(
            SheetRow(
                values, ai_row=bool(authored) and ai_fields == set(authored), ai_fields=ai_fields
            )
        )

    risk_sheet = []
    for item in data["g0_open_items"]:
        follow = item.get("risk_followup") or {}
        current = risk_rows.get((follow.get("current") or {}).get("id", ""))
        ai_summary = bool(current) and prov.ai(actor=current.actor_id, receipt=current.receipt_id)
        risk_sheet.append(
            SheetRow(
                {
                    "kind": {"risk": "风险", "question": "待决问题"}.get(
                        item["kind"], item["kind"]
                    ),
                    "title": item["title"],
                    "note": item.get("note"),
                    "owner": _name(people, item.get("owner_id")),
                    "due": item.get("due_date"),
                    "task": TASK_STATES.get((item.get("task") or {}).get("state"), None),
                    "follow_state": follow.get("state"),
                    "follow_summary": follow.get("summary"),
                },
                ai_fields=frozenset({"follow_summary"}) if ai_summary else frozenset(),
            )
        )

    commitments = []
    for value in data["commitments"]:
        row = commitment_rows.get(value["id"])
        commitments.append(
            SheetRow(
                {
                    "task": value["task_id"],
                    "promisor": _name(people, value["promisor_id"]),
                    "recipient": _name(people, value["recipient_id"]),
                    "outcomes": value["outcome_keys"],
                    "promised_at": value["promised_at"],
                    "status": "当前" if value["status"] == "current" else "已被取代",
                    "recorded_at": value["recorded_at"],
                },
                ai_row=bool(row) and prov.ai(actor=row.actor_id, receipt=row.receipt_id),
            )
        )
    updates = [
        SheetRow(
            {
                "created_at": u["created_at"],
                "author": _name(people, u["actor_id"]),
                "fact_summary": u["fact_summary"],
                "next_steps": u["next_steps"],
                "revision": u["revision"],
            },
            ai_row=prov.ai(actor=u["actor_id"], receipt=u["receipt_id"]),
        )
        for u in data["updates"]
    ]
    from pdos_next.domain.projects.discussions.service import export_rows

    # D279: project discussions and object comments, filtered by the reader's access.
    discussions = export_rows(s, ctx, _uuid(project_id))
    head = data["project"]
    return ExportView(
        view="project",
        title=f"项目：{head['name']}",
        scope={
            "product_id": str(product_id),
            "project_id": head["id"],
            "project_revision": head["revision"],
            "visibility": VISIBILITY.get(head["visibility"], head["visibility"]),
        },
        as_of=None,
        sheets=(
            Sheet("任务", _TASK_COLUMNS, tuple(task_rows)),
            Sheet(
                "风险与待决项",
                (
                    Column("kind", "类型", 10),
                    Column("title", "事项", 28),
                    Column("note", "说明", 36),
                    Column("owner", "跟进人", 12),
                    Column("due", "期限", 14),
                    Column("task", "跟进任务状态", 14),
                    Column("follow_state", "风险跟进", 12),
                    Column("follow_summary", "跟进摘要", 36),
                ),
                tuple(risk_sheet),
            ),
            Sheet(
                "承诺",
                (
                    Column("task", "任务编号", 38),
                    Column("promisor", "承诺人", 12),
                    Column("recipient", "接收人", 12),
                    Column("outcomes", "承诺交付物", 24),
                    Column("promised_at", "承诺日期", 24),
                    Column("status", "状态", 10),
                    Column("recorded_at", "记录时间", 24),
                ),
                tuple(commitments),
            ),
            Sheet(
                "状态更新",
                (
                    Column("created_at", "时间", 24),
                    Column("author", "发布人", 12),
                    Column("fact_summary", "事实摘要", 48),
                    Column("next_steps", "下一步", 36),
                    Column("revision", "版本", 8),
                ),
                tuple(updates),
            ),
            Sheet(
                "讨论与评论",
                (
                    Column("thread", "讨论或对象", 32),
                    Column("sequence", "序号", 8),
                    Column("author", "发言人", 12),
                    Column("body", "内容", 60),
                    Column("state", "状态", 10),
                    Column("subject_revision", "对象版本", 10),
                    Column("created_at", "发表时间", 24),
                    Column("updated_at", "最后修改", 24),
                ),
                tuple(SheetRow(row) for row in discussions),
            ),
        ),
        notes=(
            "任务、风险、承诺与状态更新取自项目工作页同一读取；无权查看的项目或记录不会出现。",
            "讨论与评论按读者当前受众过滤：看不到的对象下的评论不导出；撤回的内容只导出“已撤回”；"
            "讨论不构成决定、承诺或批准（P34、P41 第 7 项）。",
        ),
    )


# My work -------------------------------------------------------------------


def _pages(read, s, ctx, queue):
    items, cursor = [], None
    while True:
        page = read(s, ctx, queue, cursor, 100)
        items.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            return items, page.get("as_of")


def my_work(s, ctx) -> ExportView:
    from pdos_next.domain.my_work import attention, project_work
    from pdos_next.domain.projects.external_wait.models import ExternalWaitVersion
    from pdos_next.domain.projects.risk.models import ProjectRiskFollowup
    from pdos_next.domain.projects.work.models import WorkCommitmentVersion, WorkTaskVersion

    queues, as_of = {}, None
    for queue in QUEUE_TITLES:
        queues[queue], as_of = _pages(attention.read, s, ctx, queue)
    work = {}
    for queue in WORK_TITLES:
        work[queue], _ = _pages(project_work.read, s, ctx, queue)

    # The attention row is a deterministic projection; its source record may be AI-drafted.
    task_ids, versions = set(), {}
    for items in queues.values():
        for item in items:
            if item["kind"] == "task":
                task_ids.add(_uuid(item["source"]["id"]))
            elif item["source"]["version_id"]:
                versions[item["source"]["version_id"]] = item["kind"]
    for item in work["tasks"]:
        task_ids.add(_uuid(item["task"]["id"]))
    for item in work["commitments"]:
        task_ids.add(_uuid(item["task"]["id"]))
        versions[item["commitment"]["id"]] = "commitment"
    writers = {}
    if task_ids:
        for row in s.scalars(
            select(WorkTaskVersion).where(
                WorkTaskVersion.tenant_id == ctx.tenant_id,
                WorkTaskVersion.task_id.in_(task_ids),
                WorkTaskVersion.revision == 1,
            )
        ):
            writers[("task", str(row.task_id))] = (row.actor_id, row.receipt_id)
    for model, kinds in (
        (WorkCommitmentVersion, {"promise_review", "commitment"}),
        (ExternalWaitVersion, {"external_wait", "external_wait_transfer"}),
        (ProjectRiskFollowup, {"project_risk"}),
    ):
        ids = [_uuid(v) for v, kind in versions.items() if kind in kinds]
        if ids:
            for row in s.scalars(
                select(model).where(model.tenant_id == ctx.tenant_id, model.id.in_(ids))
            ):
                writers[("version", str(row.id))] = (row.actor_id, row.receipt_id)
    prov = Provenance(
        s,
        ctx,
        actors=[a for a, _ in writers.values()],
        receipts=[r for _, r in writers.values()],
        subjects=list(versions),
    )

    def drafted(key, subject=None):
        actor, receipt = writers.get(key, (None, None))
        return prov.ai(actor=actor, receipt=receipt, subject=subject)

    attention_columns = (
        Column("title", "事项", 32),
        Column("reason", "原因", 40),
        Column("state", "状态", 14),
        Column("responsibility", "我的责任", 14),
        Column("due_at", "期限", 24),
        Column("blocked", "受阻", 24),
        Column("category", "品类", 14),
        Column("product", "型号", 14),
        Column("project", "项目", 18),
        Column("recorded_at", "记录时间", 24),
    )
    sheets = []
    for queue, title in QUEUE_TITLES.items():
        rows = []
        for item in queues[queue]:
            source = item["source"]
            ai = (
                drafted(("task", source["id"]))
                if item["kind"] == "task"
                else drafted(("version", source["version_id"] or ""), subject=source["version_id"])
            )
            rows.append(
                SheetRow(
                    {
                        "title": item["title"],
                        "reason": item["reason"],
                        "state": item["state"],
                        "responsibility": item["responsibility"],
                        "due_at": item["due_at"],
                        "blocked": (item.get("blocked") or {}).get("message"),
                        **{
                            k: (item.get(k) or {}).get("name")
                            for k in ("category", "product", "project")
                        },
                        "recorded_at": item["recorded_at"],
                    },
                    ai_row=ai,
                )
            )
        sheets.append(Sheet(title, attention_columns, tuple(rows)))
    for queue, title in WORK_TITLES.items():
        rows = []
        for item in work[queue]:
            commitment = item.get("commitment") or {}
            ai = drafted(("task", item["task"]["id"]))
            if queue == "commitments":
                ai = drafted(("version", commitment["id"]), subject=commitment["id"])
            rows.append(
                SheetRow(
                    {
                        "task": item["task"]["title"],
                        "state": TASK_STATES.get(item["task"]["state"], item["task"]["state"]),
                        "assignee": (item.get("assignee") or {}).get("name"),
                        "recipient": (item.get("recipient") or {}).get("name"),
                        "promised_at": commitment.get("promised_at"),
                        "timing": {
                            "overdue": "已过承诺日期",
                            "pending": "未到承诺日期",
                            "unknown": "未定日期",
                        }.get(item.get("timing")),
                        **{
                            k: (item.get(k) or {}).get("name")
                            for k in ("category", "product", "project")
                        },
                        "recorded_at": item["recorded_at"],
                    },
                    ai_row=ai,
                )
            )
        columns = [
            Column("task", "任务", 32),
            Column("state", "状态", 14),
            Column("assignee", "执行人", 12),
            Column("recipient", "验收人", 12),
            Column("category", "品类", 14),
            Column("product", "型号", 14),
            Column("project", "项目", 18),
            Column("recorded_at", "记录时间", 24),
        ]
        if queue == "commitments":
            columns[4:4] = [Column("promised_at", "承诺日期", 24), Column("timing", "日期状态", 14)]
        sheets.append(Sheet(title, tuple(columns), tuple(rows)))
    return ExportView(
        view="my_work",
        title="我的工作",
        scope={"principal_id": str(ctx.requester_id), "queues": [*QUEUE_TITLES, *WORK_TITLES]},
        as_of=None if as_of is None else _parse(as_of),
        sheets=tuple(sheets),
        notes=("注意项与本人任务取自“我的工作”页同一读取；跨品类按你当前的授权逐条过滤。",),
    )


def _parse(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


# BOM diff ------------------------------------------------------------------
# The difference itself is the configuration domain's (D282); this view only
# flattens it into cells. Lists (designators) are joined for one cell.


def _cell(field, value):
    if field == "reference_designators":
        return "、".join(value) if value else None
    return value


def bom_diff(s, ctx, product_id, bom_id) -> ExportView:
    from pdos_next.domain.builds.configurations.bom_diff import FIELDS, TITLES, compare
    from pdos_next.domain.builds.configurations.service import get_bom

    row, after = get_bom(s, ctx, product_id, bom_id)
    before = get_bom(s, ctx, product_id, row.previous_id)[1] if row.previous_id else None
    prov = Provenance(s, ctx, subjects=[row.id, *([row.previous_id] if row.previous_id else [])])
    ai_after = prov.ai(subject=row.id)
    rows = []
    for line in compare((before or {}).get("lines", ()), after["lines"])["lines"]:
        change = {"added": "新增", "removed": "删除", "changed": "修改"}[line["change"]]
        values = {
            "key": line["key"],
            "change": change,
            "fields": [TITLES[field] for field in line["fields"]] if line["fields"] else None,
        }
        for field, _ in FIELDS:
            values[f"before_{field}"] = _cell(field, (line["before"] or {}).get(field))
            values[f"after_{field}"] = _cell(field, (line["after"] or {}).get(field))
        rows.append(SheetRow(values, ai_row=ai_after))
    columns = [
        Column("key", "行号", 10),
        Column("change", "变化", 8),
        Column("fields", "变化字段", 18),
    ]
    for field, title in FIELDS:
        columns += [
            Column(f"before_{field}", f"上一版{title}", 16),
            Column(f"after_{field}", f"本版{title}", 16),
        ]
    revisions = []
    for label, view, ai in (
        ("上一版", before, before is not None and prov.ai(subject=row.previous_id)),
        ("本版", after, ai_after),
    ):
        if view is None:
            continue
        revisions.append(
            SheetRow(
                {
                    "which": label,
                    "name": view["name"],
                    "revision": view["revision"],
                    "reason": view.get("reason"),
                    "lines": len(view["lines"]),
                    "visibility": VISIBILITY.get(view["visibility"], view["visibility"]),
                    "source_status": view["source_status"],
                    "created_at": view["created_at"],
                },
                ai_row=ai,
            )
        )
    return ExportView(
        view="bom_diff",
        title=f"BOM 差异：{after['name']} 第 {after['revision']} 版",
        scope={
            "product_id": str(product_id),
            "bom_id": after["id"],
            "revision": after["revision"],
            "previous_id": str(row.previous_id) if row.previous_id else None,
        },
        sheets=(
            Sheet("BOM 差异", tuple(columns), tuple(rows)),
            Sheet(
                "修订信息",
                (
                    Column("which", "版本", 8),
                    Column("name", "名称", 24),
                    Column("revision", "版次", 8),
                    Column("reason", "修订原因", 36),
                    Column("lines", "行数", 8),
                    Column("visibility", "可见范围", 10),
                    Column("source_status", "来源状态", 12),
                    Column("created_at", "创建时间", 24),
                ),
                tuple(revisions),
            ),
        ),
        notes=(
            "两侧 BOM 均经配置页同一读取 get_bom（含具名本人与型号授权核对）。"
            if before
            else "这是该 BOM 系列的首版，没有上一版可比，差异按全部新增列出。",
        ),
    )


# Test summary ----------------------------------------------------------------


def test_summary(s, ctx, product_id, build_id) -> ExportView:
    from pdos_next.domain.verification.launch.models import VerificationRunVersion
    from pdos_next.domain.verification.results.service import list_results

    data = list_results(s, ctx, product_id, build_id=build_id)
    requests = {r["request_id"]: r for r in data["requests"] if r.get("is_current")}
    runs = [r for r in data["runs"] if r.get("is_current")]
    projections = {p["id"]: p for p in data["projections"]}
    writers = {
        str(row.id): row.writer_id
        for row in s.scalars(
            select(VerificationRunVersion).where(
                VerificationRunVersion.tenant_id == ctx.tenant_id,
                VerificationRunVersion.id.in_([_uuid(r["id"]) for r in runs] or [UUID(int=0)]),
            )
        )
    }
    prov = Provenance(
        s,
        ctx,
        actors=writers.values(),
        subjects=[*(r["id"] for r in runs), *(r["run_id"] for r in runs)],
    )
    run_rows, measurement_rows = [], []
    for run in runs:
        request = requests.get(run["request_id"])
        if request is None:
            raise DomainError("SOURCE_STALE", "测试请求当前版本无法核对，请刷新后重新导出。")
        snapshot = run["run_snapshot"]
        coverage = snapshot.get("coverage") or []
        measurements = snapshot.get("measurements") or []
        pointer = run.get("current_projection") or {}
        projection = projections.get(pointer.get("id")) if pointer else None
        ai = prov.ai(actor=writers.get(run["id"]), subject=run["id"]) or prov.ai(
            subject=run["run_id"]
        )
        run_rows.append(
            SheetRow(
                {
                    "request": request["title"],
                    "run_id": run["run_id"],
                    "revision": run["revision"],
                    "status": RUN_STATES.get(run["status"], run["status"]),
                    "result": RESULTS.get(run["result"], run["result"]),
                    "projection": RESULTS.get(projection["result"], projection["result"])
                    if projection
                    else None,
                    "samples": len({p["sample_id"] for p in coverage}),
                    "items": len({p["item_id"] for p in coverage}),
                    "pairs": len(coverage),
                    "measured": len(measurements),
                    "missing": len(coverage) - len(measurements),
                    "source_status": run["source_status"],
                    "created_at": run["created_at"],
                },
                ai_row=ai,
            )
        )
        for value in measurements:
            pair = value.get("coverage") or {}
            measurement_rows.append(
                SheetRow(
                    {
                        "request": request["title"],
                        "run_id": run["run_id"],
                        "sample": pair.get("sample_id"),
                        "item": pair.get("item_id"),
                        "raw_value": value.get("raw_value"),
                        "unit": value.get("unit"),
                        "observed_at": value.get("observed_at"),
                    },
                    ai_row=ai,
                )
            )
    return ExportView(
        view="test_summary",
        title="测试汇总",
        scope={"product_id": str(product_id), "build_id": str(build_id)},
        sheets=(
            Sheet(
                "测试运行",
                (
                    Column("request", "测试请求", 28),
                    Column("run_id", "运行编号", 38),
                    Column("revision", "版本", 8),
                    Column("status", "状态", 16),
                    Column("result", "结果", 20),
                    Column("projection", "当前判定", 20),
                    Column("samples", "样件数", 8),
                    Column("items", "测试项数", 8),
                    Column("pairs", "覆盖组合", 8),
                    Column("measured", "已测", 8),
                    Column("missing", "缺测", 8),
                    Column("source_status", "来源状态", 12),
                    Column("created_at", "创建时间", 24),
                ),
                tuple(run_rows),
            ),
            Sheet(
                "测量值",
                (
                    Column("request", "测试请求", 28),
                    Column("run_id", "运行编号", 38),
                    Column("sample", "样件", 38),
                    Column("item", "测试项", 38),
                    Column("raw_value", "原值", 14),
                    Column("unit", "单位", 10),
                    Column("observed_at", "观测时间", 24),
                ),
                tuple(measurement_rows),
            ),
        ),
        notes=(
            "取自项目测试汇总同一读取（当前测试运行）；"
            f"另有 {data.get('unavailable_count', 0)} 条因权限或来源不可读未导出。",
        ),
    )
