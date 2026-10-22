"""G0-native project results, read under the actual project's ordinary audience.

ProjectOpenItem already belongs to the original G0 transaction. Resolving it does
not require access to the private proposal or decision and never copies their
source material. Its legacy status is deliberately outside this fixed basis.
"""

from collections.abc import Mapping
from datetime import date
from uuid import UUID

from sqlalchemy import and_, select

from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import owner
from .models import WorkTaskCurrent, WorkTaskVersion

_SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
_FIXED = (
    "id",
    "decision_id",
    "kind",
    "title",
    "note",
    "owner_id",
    "due_date",
    "source_question_id",
    "source_spec_item_id",
    "category_id",
    "product_id",
    "project_id",
)


def _unavailable():
    raise DomainError("SOURCE_UNAVAILABLE", "G0 原生项目事项不在当前实际可读范围。", 403)


def _stale():
    raise DomainError("SOURCE_STALE", "G0 原生项目事项的固定字段已变化，请重新核对。", 409)


def _uuid(value):
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise DomainError("VALIDATION_FAILED", "G0 事项与决定须使用实际 UUID 引用。", 422)


def _reference(ref):
    try:
        if isinstance(ref, Mapping):
            return _uuid(ref["id"]), _uuid(ref["decision_id"])
        return _uuid(ref.id), _uuid(ref.decision_id)
    except (KeyError, AttributeError, TypeError):
        raise DomainError("VALIDATION_FAILED", "须提供完整的 G0 事项和原决定引用。", 422) from None


def _project(s, ctx, pid, project_id, *, lock=False):
    try:
        project = owner.project(s, ctx, pid, project_id, lock=lock)
    except DomainError as error:
        if error.status == 403:
            _unavailable()
        raise
    if project is None or (
        project.tenant_id,
        project.category_id,
        project.product_id,
        project.id,
    ) != (ctx.tenant_id, ctx.category_id, pid, project_id):
        _unavailable()
    return project


def _columns():
    item = ProjectOpenItem
    return (
        item.tenant_id,
        item.id,
        item.g0_decision_id.label("decision_id"),
        item.kind,
        item.title,
        item.note,
        item.owner_id,
        item.due_date,
        item.source_question_id,
        item.source_spec_item_id,
        item.category_id,
        item.product_id,
        item.project_id,
    )


def _scope(ctx, pid, project_id):
    item = ProjectOpenItem
    return (
        item.tenant_id == ctx.tenant_id,
        item.category_id == ctx.category_id,
        item.product_id == pid,
        item.project_id == project_id,
    )


def _basis(row, ctx, pid, project_id):
    if row is None or tuple(row[field] for field in _SCOPE) != (
        ctx.tenant_id,
        ctx.category_id,
        pid,
        project_id,
    ):
        _unavailable()
    if (
        row["kind"] not in {"task", "risk"}
        or not isinstance(row["due_date"], date)
        or (row["source_question_id"] is None) == (row["source_spec_item_id"] is None)
    ):
        _stale()
    data = {field: row[field] for field in _FIXED}
    for field in (
        "id",
        "decision_id",
        "owner_id",
        "source_question_id",
        "source_spec_item_id",
        "category_id",
        "product_id",
        "project_id",
    ):
        data[field] = str(data[field]) if data[field] is not None else None
    data["due_date"] = data["due_date"].isoformat()
    return {**data, "digest": digest(data)}


def resolve(s, ctx, pid, project_id, ref, lock=False):
    """Return one JSON basis; ref accepts a mapping or typed id/decision_id DTO."""
    pid, project_id = _uuid(pid), _uuid(project_id)
    identity, decision_id = _reference(ref)
    _project(s, ctx, pid, project_id, lock=lock)
    query = select(*_columns()).where(
        *_scope(ctx, pid, project_id),
        ProjectOpenItem.id == identity,
        ProjectOpenItem.g0_decision_id == decision_id,
    )
    # The project scope lock serializes admission. Native G0 fields are immutable;
    # locking this untouched row would also require its legacy UPDATE policy.
    row = s.execute(query).mappings().one_or_none()
    data = _basis(row, ctx, pid, project_id)
    if (data["id"], data["decision_id"]) != (str(identity), str(decision_id)):
        _unavailable()
    return data


def sources_current(s, ctx, pid, basis):
    """Recheck the direct resolve() basis, not a whole source_basis wrapper.

    Current ordinary Project/OpenItem visibility still applies. A changed title,
    due date, responsibility, native source or digest requires a new basis; a
    legacy status update has no effect on the immutable task's G0 provenance.
    """
    if not isinstance(basis, Mapping) or not set(_FIXED) | {"digest"} <= basis.keys():
        _stale()
    try:
        project_id = _uuid(basis["project_id"])
        identity, decision_id = _reference(basis)
    except DomainError:
        _stale()
    current = resolve(s, ctx, pid, project_id, {"id": identity, "decision_id": decision_id})
    if dict(basis) != current:
        _stale()
    return True


def _current_tasks(ctx, pid, project):
    current, version = WorkTaskCurrent, WorkTaskVersion
    binding = (*_SCOPE, "owner_id", "visibility")
    return (
        select(
            *(getattr(current, field) for field in _SCOPE),
            version.g0_open_item_id,
            version.g0_decision_id,
            current.task_id,
            current.revision.label("task_revision"),
            current.state.label("task_state"),
        )
        .select_from(current)
        .join(
            version,
            and_(
                *(getattr(current, field) == getattr(version, field) for field in binding),
                current.version_id == version.id,
                current.task_id == version.task_id,
                current.revision == version.revision,
                current.state == version.state,
            ),
        )
        .where(
            current.tenant_id == ctx.tenant_id,
            current.category_id == ctx.category_id,
            current.product_id == pid,
            current.project_id == project.id,
            current.owner_id == project.owner_id,
            current.visibility == project.visibility,
            version.g0_open_item_id.is_not(None),
            version.g0_decision_id.is_not(None),
        )
        .subquery("g0_current_task")
    )


def workspace_items(s, ctx, pid, project_id):
    """Read native items and exact current task links in one column-only query."""
    pid, project_id = _uuid(pid), _uuid(project_id)
    project = _project(s, ctx, pid, project_id)
    tasks = _current_tasks(ctx, pid, project)
    query = (
        select(*_columns(), tasks.c.task_id, tasks.c.task_revision, tasks.c.task_state)
        .select_from(ProjectOpenItem)
        .outerjoin(
            tasks,
            and_(
                *(tasks.c[field] == getattr(ProjectOpenItem, field) for field in _SCOPE),
                tasks.c.g0_open_item_id == ProjectOpenItem.id,
                tasks.c.g0_decision_id == ProjectOpenItem.g0_decision_id,
            ),
        )
        .where(*_scope(ctx, pid, project_id))
        .order_by(ProjectOpenItem.due_date, ProjectOpenItem.id)
    )
    result, seen = [], set()
    for row in s.execute(query).mappings():
        basis = _basis(row, ctx, pid, project_id)
        if basis["id"] in seen:
            _stale()
        seen.add(basis["id"])
        question = basis["source_question_id"] is not None
        task = None
        if row["task_id"] is not None:
            task = {
                "id": str(row["task_id"]),
                "revision": row["task_revision"],
                "state": row["task_state"],
            }
        result.append(
            {
                **{field: basis[field] for field in _FIXED[:7]},
                "source": {
                    "kind": "question" if question else "spec",
                    "id": basis["source_question_id"] if question else basis["source_spec_item_id"],
                },
                "task": task,
            }
        )
    return result
