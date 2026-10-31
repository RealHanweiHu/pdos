"""Four-question entries from the subscriber's ordinary Human RR/RLS reads.

This module opens no session, borrows no service identity, calls no model and
persists no business facts. Automation integration must first bind its actual
grant/Run/owner, then provide the approved ordinary owner read transaction.
"""

from datetime import UTC, datetime
from hashlib import sha256
from itertools import islice
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import load_only

from pdos_next import personal_attention, personal_project_work
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent
from pdos_next.domain.work_management.models import (
    BINDING,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.personal_views import _personal
from pdos_next.project_work_summaries import latest as latest_named_updates
from pdos_next.service import digest

from .personal_summary_schemas import (
    Baseline,
    Change,
    Coverage,
    Item,
    NextStep,
    ObjectRef,
    Person,
    Relationship,
    Selection,
    Summary,
    SummaryGroup,
)

LIMIT = 100
GROUPS = {
    "action": "需要我决定或处理的事",
    "waiting": "我在等待别人完成的事",
    "following": "我关注项目的新变化",
}


def _deny(message="摘要须在订阅者本人的普通只读快照中生成。"):
    raise DomainError("FORBIDDEN_SCOPE", message, 403)


def _time(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DomainError("INTEGRITY_MISMATCH", "摘要来源的登记时点无法核对。")
    return value.astimezone(UTC)


def _url(category_id, project_id, *, proposal_id=None):
    category_id = UUID(str(category_id))
    if proposal_id is not None:
        return f"/categories/{category_id}/proposals/{UUID(str(proposal_id))}"
    return "/?" + urlencode(
        {"area": "cockpit", "category": str(category_id), "project": str(UUID(str(project_id)))}
    )


def _selection_digest(selection):
    raw = selection.model_dump(mode="json")
    for key in ("followed_project_ids", "category_ids", "groups", "excluded_kinds"):
        raw[key].sort()
    return digest(raw)


def _selected(selection, category_id):
    return not selection.category_ids or UUID(str(category_id)) in selection.category_ids


def _same(left, right, fields):
    return and_(*(getattr(left, key) == getattr(right, key) for key in fields))


def _categories(query, category, selection, *, product=None, product_id=None):
    if selection.category_ids:
        query = query.where(category.in_(selection.category_ids))
    if product_id is not None:
        if product is None:
            _deny("摘要来源缺少固定型号范围。")
        query = query.where(product == product_id)
    return query


def _attention_page(session, ctx, queue, selection, *, product_id=None):
    # Reuse the authoritative source/DTO contracts, narrowing the subscription
    # category before paging and counts (the public reader is cross-category).
    source = personal_attention.records(ctx, queue).subquery("summary_attention")
    query = _categories(
        select(source), source.c.category_id, selection,
        product=source.c.product_id, product_id=product_id,
    )
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        session.execute(
            query.order_by(
                source.c.recorded_at.desc(),
                source.c.key.desc(),
            ).limit(LIMIT + 1)
        )
        .mappings()
        .all()
    )
    return (
        [personal_attention.entry(row, ctx, queue) for row in rows[:LIMIT]],
        total,
        len(rows) > LIMIT,
    )


def _work_page(session, ctx, queue, selection, as_of, *, product_id=None):
    query = _categories(
        personal_project_work._records(ctx, queue), WorkTaskVersion.category_id, selection,
        product=WorkTaskVersion.product_id, product_id=product_id,
    )
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    model = WorkCommitmentVersion if queue == "commitments" else WorkTaskVersion
    rows = (
        session.execute(
            query.order_by(model.created_at.desc(), model.id.desc()).limit(
                LIMIT + 1,
            )
        )
        .mappings()
        .all()
    )
    return [personal_project_work._entry(row, ctx, queue, as_of) for row in rows[:LIMIT]], (
        total,
        len(rows) > LIMIT,
    )


def _item(
    *,
    identity,
    kind,
    group,
    title,
    source,
    recorded_at,
    state,
    relationship,
    next_step,
    url,
    facts=None,
):
    return {
        "id": identity,
        "kind": kind,
        "group": group,
        "title": title,
        "object": source,
        "recorded_at": _time(recorded_at),
        "state_as_recorded": state,
        "relationship": relationship,
        "next_step": next_step,
        "continue_url": url,
        "facts": facts or {},
    }


def _attention(row):
    category, project = row["category"]["id"], row["project"]
    source = row["source"]
    return _item(
        identity="attention:" + row["queue"] + ":" + row["id"],
        kind=row["kind"],
        group="waiting" if row["queue"] == "external" else "action",
        title=row["title"],
        source=ObjectRef(
            kind=row["kind"],
            id=source["id"],
            version_id=source["version_id"],
            revision=source["revision"],
            category_id=category,
            product_id=row["product"]["id"] if row["product"] else None,
            project_id=project["id"] if project else None,
        ),
        recorded_at=row["recorded_at"],
        state=row["state"],
        relationship=Relationship(kind=row["responsibility"], text=row["reason"]),
        next_step=NextStep(
            kind="navigation",
            text="在原事项核对当前记录并按原流程继续办理。",
            responsible=Person.model_validate(row["responsible"]),
        ),
        url=_url(
            category,
            project["id"] if project else None,
            proposal_id=source["id"] if row["target"] == "proposal" else None,
        ),
        facts={
            "due_at_as_recorded": row["due_at"],
            "date_kind": "internal_check"
            if row["details"].get("next_check_is_internal") is True
            else "as_recorded",
            "blocked": row["blocked"],
            "details": row["details"],
            "source_epoch": source["epoch"],
        },
    )


def _task(row, person_id):
    task, promise = row["task"], row["commitment"]
    waiting = promise is None and task["state"] == "submitted"
    who = row["recipient"] if waiting else row["assignee"]
    return _item(
        identity=("own_promise:" if promise else "own_task:") + row["id"],
        kind="own_promise" if promise else "own_task",
        group="waiting" if waiting else "action",
        title=task["title"],
        source=ObjectRef(
            kind="work_commitment" if promise else "work_task",
            id=row["id"],
            version_id=promise["id"] if promise else task["version_id"],
            revision=promise["revision"] if promise else task["revision"],
            category_id=row["category"]["id"],
            product_id=row["product"]["id"],
            project_id=row["project"]["id"],
        ),
        recorded_at=row["recorded_at"],
        state="recorded" if promise else task["state"],
        relationship=Relationship(
            kind="named_promisor" if promise else "named_assignee",
            text="你是这条已登记承诺的承诺人；履行仍须独立核对。"
            if promise
            else "你是当前任务版本具名指定的承接人。",
        ),
        next_step=NextStep(
            kind="navigation",
            text="核对原承诺及其履行记录。"
            if promise
            else "核对已提交成果的接收情况。"
            if waiting
            else "在原任务继续办理。",
            responsible=Person(id=person_id)
            if promise
            else Person.model_validate(who)
            if who
            else None,
        ),
        url=_url(row["category"]["id"], row["project"]["id"]),
        facts={"task": task, "commitment_as_recorded": promise},
    )


def waiting_promises(ctx):
    """Actual recipient/promise heads, with exact scope and fulfillment joins."""
    p, pc, task, tc = (
        WorkCommitmentVersion,
        WorkCommitmentCurrent,
        WorkTaskVersion,
        WorkTaskCurrent,
    )
    return (
        select(
            p.id,
            p.series_id,
            p.revision,
            p.category_id,
            p.product_id,
            p.project_id,
            p.task_id,
            p.promisor_id,
            p.promised_at,
            p.outcome_keys,
            p.created_at,
            Principal.name.label("promisor_name"),
            task.body["title"].astext.label("title"),
        )
        .select_from(pc)
        .join(
            p,
            and_(
                _same(
                    p,
                    pc,
                    (*BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "revision"),
                ),
                p.id == pc.version_id,
            ),
        )
        .join(tc, _same(tc, p, (*BINDING, "task_id")))
        .join(
            task,
            and_(
                _same(task, tc, (*BINDING, "task_id", "revision", "state")),
                task.id == tc.version_id,
            ),
        )
        .outerjoin(
            Principal, and_(Principal.tenant_id == p.tenant_id, Principal.id == p.promisor_id)
        )
        .where(
            p.tenant_id == ctx.tenant_id,
            p.recipient_id == ctx.requester_id,
            p.promisor_id != ctx.requester_id,
            ~select(WorkCommitmentReviewCurrent.id)
            .where(
                _same(WorkCommitmentReviewCurrent, p, BINDING),
                WorkCommitmentReviewCurrent.commitment_id == p.id,
                WorkCommitmentReviewCurrent.state == "fulfilled",
            )
            .exists(),
        )
    )


def _waiting_promise(row):
    return _item(
        identity="waiting_promise:" + str(row["series_id"]),
        kind="waiting_promise",
        group="waiting",
        title=row["title"],
        source=ObjectRef(
            kind="work_commitment",
            id=row["series_id"],
            version_id=row["id"],
            revision=row["revision"],
            category_id=row["category_id"],
            product_id=row["product_id"],
            project_id=row["project_id"],
        ),
        recorded_at=row["created_at"],
        state="fulfillment_not_confirmed",
        relationship=Relationship(
            kind="named_promise_recipient", text="你是这条承诺的具名接收人。"
        ),
        next_step=NextStep(
            kind="navigation",
            text="在原承诺核对具名承诺人的提交和履行情况。",
            responsible=Person(id=row["promisor_id"], name=row["promisor_name"]),
        ),
        url=_url(row["category_id"], row["project_id"]),
        facts={
            "task_id": str(row["task_id"]),
            "outcome_keys": row["outcome_keys"],
            "promised_at_as_recorded": row["promised_at"].isoformat()
            if row["promised_at"]
            else None,
        },
    )


def _project(row, update):
    return _item(
        identity="project_update:" + str(row.id),
        kind="project_update",
        group="following",
        title=row.name,
        source=ObjectRef(
            kind="project_status_update" if update else "project",
            id=row.id,
            version_id=update["id"] if update else None,
            revision=update["revision"] if update else row.revision,
            category_id=row.category_id,
            product_id=row.product_id,
            project_id=row.id,
        ),
        recorded_at=update["created_at"] if update else row.created_at,
        state="named_update_recorded" if update else "no_named_update",
        relationship=Relationship(kind="subscriber", text="这是你显式选择关注的项目。"),
        next_step=NextStep(
            kind="recorded" if update else "unknown",
            text=update["next_steps"] if update else "尚无最新具名状态更新。",
            # A recorder is not automatically the next action owner.
            recorded_by=Person.model_validate(update["actor"]) if update else None,
        ),
        url=_url(row.category_id, row.id),
        facts={"latest_named_status": update, "project_status_as_recorded": row.status},
    )


def supply_sources(ctx):
    """Authoritative current native snapshots, never a purchaser-role permission."""
    from pdos_next.enterprise_search.sources import catalog

    source = catalog(["supply"])
    return select(source).where(
        source.c.tenant_id == ctx.tenant_id,
        source.c.owner_id == ctx.requester_id,
        source.c.is_current,
    )


def _supply(row):
    facts = row["structured"]["facts"]
    for commitment in facts["commitments"]:
        record_key = sha256(commitment["record_id"].encode("utf-8")).hexdigest()[:16]
        yield _item(
            identity=f"supply:{facts['build_id']}:{record_key}",
            kind="supply_commitment",
            group="waiting",
            title=row["title"],
            source=ObjectRef(
                kind="supply",
                id=row["source_id"],
                version_id=row["source_id"],
                revision=row["source_revision"],
                category_id=row["category_id"],
                product_id=row["product_id"],
                project_id=row["project_id"],
            ),
            recorded_at=row["created_at"],
            state="commitment_recorded",
            relationship=Relationship(kind="record_owner", text="你是该供应快照的登记负责人。"),
            next_step=NextStep(
                kind="navigation", text="核对原供应承诺和实际收货记录；外部责任人未单独登记。"
            ),
            url=_url(row["category_id"], row["project_id"]),
            facts={
                "commitment_as_recorded": commitment,
                "source_basis_status": row["read_basis_status"],
                "fulfillment_status": "not_assessed",
            },
        )


def compose(ctx, selection, as_of, rows, coverage, *, previous=None):
    """Only currently authorized rows enter; the baseline contains hashes, no old facts."""
    scope_digest = _selection_digest(selection)
    if previous is not None and (
        previous.tenant_id != ctx.tenant_id
        or previous.principal_id != ctx.requester_id
        or previous.selection_digest != scope_digest
    ):
        _deny("摘要比较基线不属于当前本人和同一订阅选择。")
    watermarks = previous.watermarks if previous else {}
    entries = {}
    for row in rows:
        if row["group"] not in selection.groups or row["kind"] in selection.excluded_kinds:
            continue
        if not _selected(selection, row["object"].category_id):
            continue
        fingerprint = digest(row)
        before = watermarks.get(row["id"])
        kind = "initial" if before is None else "unchanged" if before == fingerprint else "updated"
        message = {
            "initial": "本次首次列入摘要，以下是当前登记记录。",
            "unchanged": "与上次摘要的当前记录一致。",
            "updated": "记录或固定版本与上次摘要不同，以下是最新可读记录。",
        }[kind]
        entry = Item(
            **row,
            as_of=_time(as_of),
            fingerprint=fingerprint,
            change=Change(kind=kind, text=message),
        )
        old = entries.get(entry.id)
        if old is not None and old != entry:
            raise DomainError("INTEGRITY_MISMATCH", "同一摘要条目的当前事实不一致。")
        entries[entry.id] = entry
    ordered = sorted(
        entries.values(),
        key=lambda item: (
            item.change.kind == "unchanged",
            ("action", "waiting", "following").index(item.group),
            item.facts.get("details", {}).get("blocking") is not True,
            -item.recorded_at.timestamp(),
            item.id,
        ),
    )
    kept = ordered[: selection.max_items]
    omitted = len(ordered) - len(kept)
    groups = tuple(
        SummaryGroup(
            id=key,
            title=GROUPS[key],
            items=tuple(
                item for item in kept if item.group == key and item.change.kind != "unchanged"
            ),
            unchanged_items=tuple(
                item for item in kept if item.group == key and item.change.kind == "unchanged"
            ),
        )
        for key in selection.groups
    )
    return Summary(
        tenant_id=ctx.tenant_id,
        principal_id=ctx.requester_id,
        as_of=_time(as_of),
        groups=groups,
        coverage=tuple(coverage),
        omitted_current_items=omitted,
        complete=not omitted and not any(c.has_more or c.unavailable for c in coverage),
        baseline=Baseline(
            tenant_id=ctx.tenant_id,
            principal_id=ctx.requester_id,
            selection_digest=scope_digest,
            watermarks={item.id: item.fingerprint for item in kept},
        ),
    )


def read(
    session, ctx, selection: Selection, *, previous: Baseline | None = None, product_id=None,
):
    """Generate without a model in the existing authenticated personal RR snapshot."""
    _personal(session, ctx)
    if (
        session.info.get("read_snapshot") is not True
        or session.info.get("scope") != (ctx.tenant_id, ctx.requester_id, ctx.requester_id, None)
        or ctx.agent_run_id is not None
        or ctx.run_id is not None
    ):
        _deny()
    principal = session.get(Principal, ctx.requester_id)
    if not principal or not principal.active or principal.kind != "human":
        _deny()
    as_of = session.scalar(select(func.transaction_timestamp()))
    rows, coverage, attention_tasks, attention_promises = [], [], set(), set()
    for queue in ("decide", "receive", "verify", "external"):
        if ("waiting" if queue == "external" else "action") not in selection.groups:
            continue
        items, total, has_more = _attention_page(
            session, ctx, queue, selection, product_id=product_id,
        )
        rows.extend(_attention(row) for row in items)
        attention_tasks.update(row["source"]["id"] for row in items if row["kind"] == "task")
        attention_promises.update(
            row["source"]["id"] for row in items if row["kind"] == "promise_review"
        )
        coverage.append(
            Coverage(
                source="attention:" + queue, returned=len(items), available=total, has_more=has_more
            )
        )
    for queue in ("tasks", "commitments"):
        if not set(selection.groups) & {"action", "waiting"}:
            break
        items, (total, has_more) = _work_page(
            session, ctx, queue, selection, _time(as_of), product_id=product_id,
        )
        rows.extend(
            _task(row, ctx.requester_id)
            for row in items
            if queue == "commitments" or row["task"]["id"] not in attention_tasks
        )
        coverage.append(
            Coverage(
                source="own_work:" + queue, returned=len(items), available=total, has_more=has_more
            )
        )
    if "waiting" in selection.groups:
        from pdos_next.enterprise_search.sources import prepare_read

        prepare_read(session, ("supply",))
        promises = (
            session.execute(
                _categories(
                    waiting_promises(ctx), WorkCommitmentVersion.category_id, selection,
                    product=WorkCommitmentVersion.product_id, product_id=product_id,
                )
                .order_by(
                    WorkCommitmentVersion.created_at.desc(),
                    WorkCommitmentVersion.id.desc(),
                )
                .limit(LIMIT + 1)
            )
            .mappings()
            .all()
        )
        rows.extend(
            _waiting_promise(row)
            for row in promises[:LIMIT]
            if str(row["series_id"]) not in attention_promises
        )
        coverage.append(
            Coverage(
                source="waiting_promises",
                returned=min(len(promises), LIMIT),
                has_more=len(promises) > LIMIT,
            )
        )
        source = supply_sources(ctx).subquery("personal_summary_supply")
        snapshots = (
            session.execute(
                _categories(
                    select(source), source.c.category_id, selection,
                    product=source.c.product_id, product_id=product_id,
                )
                .order_by(
                    source.c.created_at.desc(),
                    source.c.source_id.desc(),
                )
                .limit(LIMIT + 1)
            )
            .mappings()
            .all()
        )
        supply_rows = list(
            islice((item for row in snapshots[:LIMIT] for item in _supply(row)), LIMIT + 1)
        )
        rows.extend(supply_rows[:LIMIT])
        coverage.append(
            Coverage(
                source="supply_commitments",
                returned=min(len(supply_rows), LIMIT),
                has_more=len(snapshots) > LIMIT or len(supply_rows) > LIMIT,
            )
        )
    if "following" in selection.groups and selection.followed_project_ids:
        projects = session.scalars(
            _categories(
                select(Project).where(
                    Project.tenant_id == ctx.tenant_id,
                    Project.id.in_(selection.followed_project_ids),
                ),
                Project.category_id,
                selection,
                product=Project.product_id, product_id=product_id,
            ).options(
                load_only(
                    Project.id,
                    Project.tenant_id,
                    Project.category_id,
                    Project.product_id,
                    Project.name,
                    Project.revision,
                    Project.status,
                    Project.created_at,
                )
            )
        ).all()
        updates = latest_named_updates(session, ctx, projects)
        rows.extend(_project(project, updates.get(project.id)) for project in projects)
        coverage.append(
            Coverage(
                source="followed_projects",
                returned=len(projects),
                unavailable=len(selection.followed_project_ids) - len(projects),
            )
        )
    from pdos_next import personal_summary_gates, personal_summary_quality

    quality_rows, quality_coverage = personal_summary_quality.read(
        session, ctx, selection, as_of, product_id=product_id,
    )
    rows.extend(quality_rows)
    coverage.extend(quality_coverage)
    gate_rows, gate_coverage = personal_summary_gates.read(
        session, ctx, selection, as_of, product_id=product_id,
    )
    rows.extend(gate_rows)
    coverage.extend(gate_coverage)
    return compose(ctx, selection, as_of, rows, coverage, previous=previous)
