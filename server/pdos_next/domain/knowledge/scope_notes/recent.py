"""范围近况 (P87 第 7 项): a read-only view computed when read, never stored.

For a project it reuses the cockpit activity feed's own query (same sources,
same row-level security); for every scope it adds the latest changes to the
scope's team notes. All of it is deterministic SQL: no model, no embedding, and
the same reader at the same watermark gets the same lines. Proposal, product
and category scopes have no activity feed of their own yet, so they carry note
changes only (registered remainder).
"""

from datetime import UTC, datetime

from sqlalchemy import select

from . import reads
from .models import ScopeNoteVersion

VERSION = "scope-recent/v1"
ACTIVITY_LINES = 8
NOTE_LINES = 5
ACTION_LABELS = {"create": "新增", "backfill": "补录", "revise": "修改", "add_evidence": "补充证据",
                 "supersede": "被替代", "retire": "停用", "withdraw": "撤回"}
LABEL = ("范围近况：这个范围最近的业务动态和团队备忘变更，按时间由新到旧。"
         "不是业务事实的依据，涉及事实须重新读取业务对象。")


def _short(value, limit=60):
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def activity(s, ctx, anchor, *, as_of):
    """Latest project activity lines up to the watermark; [] for other scopes."""
    if anchor["kind"] != "project":
        return []
    from pdos_next.domain.projects.activity import activity_item, activity_records

    records = activity_records(ctx, anchor["product_id"], anchor["id"], include_runs=False)
    rows = s.execute(
        select(records).where(records.c.recorded_at <= as_of)
        .order_by(records.c.recorded_at.desc(), records.c.id.desc()).limit(ACTIVITY_LINES)
    ).mappings().all()
    lines = []
    for row in rows:
        item = activity_item(row)
        lines.append({"at": item["recorded_at"][:10], "who": item["actor"]["name"],
                      "what": _short(item["summary"]),
                      "subject": _short(item["subject"]["title"], 40)})
    return lines


def note_changes(s, ctx, anchor, *, as_of):
    rows = s.scalars(
        select(ScopeNoteVersion).where(
            ScopeNoteVersion.tenant_id == ctx.tenant_id,
            ScopeNoteVersion.category_id == anchor["category_id"],
            ScopeNoteVersion.anchor_kind == anchor["kind"],
            {"category": ScopeNoteVersion.category_id, "product": ScopeNoteVersion.product_id,
             "proposal": ScopeNoteVersion.proposal_id,
             "project": ScopeNoteVersion.project_id}[anchor["kind"]] == anchor["id"],
            ScopeNoteVersion.created_at <= as_of,
        ).order_by(ScopeNoteVersion.created_at.desc(), ScopeNoteVersion.id.desc())
        .limit(NOTE_LINES * 3)
    ).all()
    lines = []
    for row in rows:
        if reads.flags(s, row, now=as_of) is None:
            continue
        who = reads.person(s, ctx.tenant_id, row.writer_id) or {}
        lines.append({"at": row.created_at.date().isoformat(), "who": who.get("name"),
                      "what": f"{ACTION_LABELS[row.action]}{reads.KIND_LABELS[row.kind]}",
                      "note_id": str(row.note_id), "revision": row.revision})
        if len(lines) >= NOTE_LINES:
            break
    return lines


def build(s, ctx, anchor, *, as_of=None):
    as_of = as_of or datetime.now(UTC)
    return {"zone": "background", "label": LABEL, "as_of": as_of.isoformat(),
            "scope": {"kind": anchor["kind"], "title": anchor["title"]},
            "activity": activity(s, ctx, anchor, as_of=as_of),
            "note_changes": note_changes(s, ctx, anchor, as_of=as_of)}


def view(s, ctx, kind, identity):
    anchor = reads.resolve(s, ctx.tenant_id, kind, identity)
    if anchor is None:
        reads.deny("FORBIDDEN_SCOPE", "scope_note_anchor_unreadable", "所选范围当前不可读。", 403)
    return {"version": VERSION, **build(s, ctx, anchor)}
