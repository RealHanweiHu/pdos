"""Explicit Human focus/version/source choices, reloaded through ordinary RLS.

These selectors narrow the existing conversation. They never rebind its scope,
mint citations, reinterpret an old artifact as its head, or change old Runs.
"""

from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select, tuple_

from pdos_next.enterprise_search.schemas import SourceType
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest


class SourceChoice(StrictModel):
    source_type: SourceType
    source_id: UUID
    expected_revision: int = Field(ge=1, strict=True)


class ContextChange(StrictModel):
    kind: Literal["replace_focus", "fixed_versions", "current_only", "limit_sources", "clear"]
    sources: list[SourceChoice] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def choices(self):
        if self.kind in {"current_only", "clear"}:
            if self.sources:
                raise ValueError("解除或当前版本条件不接受固定来源。")
        elif not self.sources or self.kind == "replace_focus" and len(self.sources) != 1:
            raise ValueError("请选择实际对象或固定来源。")
        keys = {(ref.source_type, ref.source_id) for ref in self.sources}
        if len(keys) != len(self.sources):
            raise ValueError("同一固定来源不能重复选择。")
        return self


class SelectedSource(StrictModel):
    source_type: SourceType
    source_id: UUID
    object_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    category_id: UUID
    product_id: UUID | None = None
    project_id: UUID | None = None
    proposal_id: UUID | None = None
    title: str
    private: bool = Field(strict=True)
    customer_original: bool = Field(strict=True)


class ContextSelection(StrictModel):
    version: Literal[1] = 1
    status: Literal["available", "unavailable"]
    focus: SelectedSource | None
    version_mode: Literal["any", "current", "fixed"]
    versions: list[SelectedSource]
    sources: list[SelectedSource] | None = Field(min_length=1)


def validated(value):
    try:
        return ContextSelection.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError):
        raise DomainError("VERSION_CONFLICT", "已保存的显式条件无法核对，请重新选择。") from None


def _scope(query, columns, run):
    query = query.where(columns.tenant_id == run.tenant_id)
    if run.category_id is not None:
        query = query.where(columns.category_id == run.category_id)
    # An explicit source selection may discuss another readable case within
    # this category. It does not change the conversation's business target.
    return query


def _rows(session, run, choices):
    from pdos_next.enterprise_search.sources import prepare_read, retrieval_catalog

    types = {ref.source_type for ref in choices}
    prepare_read(session, types)
    source = retrieval_catalog(types)
    keys = [(ref.source_type, ref.source_id, ref.expected_revision) for ref in choices]
    fields = [column for column in source.c if column.key not in {"body", "structured"}]
    return (
        session.execute(
            _scope(select(*fields), source.c, run).where(
                tuple_(source.c.source_type, source.c.source_id, source.c.source_revision).in_(
                    keys
                ),
            )
        )
        .mappings()
        .all()
    )


def resolve(session, ctx, run, choices):
    """Browser IDs select rows; revision/hash/audience/owner come only from actual reads."""
    from pdos_next.enterprise_search.assistant_sources import current

    if run.requester_id != ctx.requester_id or run.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "只能修改本人的当前会话。", 403)
    rows = _rows(session, run, choices)
    by_key = {(row["source_type"], row["source_id"], row["source_revision"]): row for row in rows}
    selected = {}
    for index, ref in enumerate(choices):
        row = by_key.get((ref.source_type, ref.source_id, ref.expected_revision))
        if row is None:
            raise DomainError("SOURCE_UNAVAILABLE", "选定版本当前不可读，请重新选择。", 403)
        selected[str(index)] = {
            key: str(value) if isinstance(value, UUID) else value for key, value in row.items()
        }
    actual, missing = current(session, selected)
    if missing or len(actual) != len(selected):
        raise DomainError("SOURCE_UNAVAILABLE", "选定资料或其依据当前不可用。", 403)
    return [
        {
            key: selected[str(index)][key]
            for key in (
                "source_type",
                "source_id",
                "object_id",
                "source_revision",
                "content_hash",
                "category_id",
                "product_id",
                "project_id",
                "proposal_id",
                "title",
            )
        }
        | {
            "private": bool(actual[str(index)]["private"]),
            "customer_original": bool(actual[str(index)]["customer_original"]),
        }
        for index in range(len(choices))
    ]


def values(condition):
    if not condition:
        return []
    return (
        ([condition["focus"]] if condition.get("focus") else [])
        + list(condition.get("versions") or [])
        + list(condition.get("sources") or [])
    )


def _owner_recheck(session, ctx, run, condition):
    """Only a stored Run may project its frozen pins under its actual Human requester."""
    from pdos_next.database import require_context
    from pdos_next.enterprise_search.assistant_sources import human_snapshot
    from pdos_next.service import Context

    from .execution import check_run_binding, scope_for_run
    from .models import AgentRun

    require_context(session, ctx)
    actual = session.get(AgentRun, run.id)
    if (
        actual is None
        or actual.tenant_id != ctx.tenant_id
        or actual.requester_id != ctx.requester_id
        or actual.writer_id != ctx.actor_id
        or actual.category_id != ctx.category_id
        or ctx.agent_run_id != actual.id
        or ctx.run_id is not None
        or ctx.cancel_epoch != actual.cancel_epoch
        or digest(condition) != digest(frozen_condition(actual))
    ):
        raise DomainError("FORBIDDEN_SCOPE", "固定资料未绑定当前实际本人运行。", 403)
    scope = scope_for_run(actual)
    check_run_binding(run, scope, for_write=False)
    with human_snapshot(session.get_bind(), scope) as reading:
        # Ordinary RLS must still expose the exact stored Run to this requester.
        retained = reading.get(AgentRun, actual.id)
        check_run_binding(retained, scope, for_write=False)
        owner = Context(actual.tenant_id, actual.requester_id, actual.requester_id,
                        category_id=actual.category_id)
        from pdos_next.domain.preproject.access import human

        human(reading, owner)
        return recheck(reading, owner, retained, condition)


def recheck(session, ctx, run, condition):
    if not condition:
        return None
    condition = validated(condition)
    if run is None:
        raise DomainError("FORBIDDEN_SCOPE", "原会话已不可读。", 403)
    if getattr(ctx, "actor_id", ctx.requester_id) != ctx.requester_id:
        return _owner_recheck(session, ctx, run, condition)
    if condition.get("status") == "unavailable":
        raise DomainError("SOURCE_UNAVAILABLE", "选定条件已不可用，请重新选择或解除限定。")
    choices, old = [], {}
    for ref in values(condition):
        choice = SourceChoice(
            source_type=ref["source_type"],
            source_id=ref["source_id"],
            expected_revision=ref["source_revision"],
        )
        key = (choice.source_type, str(choice.source_id), choice.expected_revision)
        if key not in old:
            choices.append(choice)
            old[key] = ref
    for row in resolve(session, ctx, run, choices) if choices else []:
        prior = old[(row["source_type"], row["source_id"], row["source_revision"])]
        if row["content_hash"] != prior["content_hash"] or row["object_id"] != prior["object_id"]:
            raise DomainError("SOURCE_STALE", "选定资料内容已变化，请重新选择固定版本。")
        if (
            row["private"]
            and not prior["private"]
            or row["customer_original"]
            and not prior["customer_original"]
        ):
            raise DomainError("SOURCE_STALE", "资料分类已变化，请重新选择以更新本次绑定。")
    return deepcopy(condition)


def _current_focus(session, ctx, run, focus):
    from pdos_next.enterprise_search.sources import prepare_read, retrieval_catalog

    prepare_read(session, [focus["source_type"]])
    source = retrieval_catalog([focus["source_type"]])
    row = session.execute(
        _scope(select(source.c.source_id, source.c.source_revision), source.c, run).where(
            source.c.object_id == UUID(focus["object_id"]),
            source.c.is_current,
        )
    ).one_or_none()
    if row is None:
        raise DomainError("SOURCE_UNAVAILABLE", "这个对象当前没有可选的有效版本。")
    return resolve(
        session,
        ctx,
        run,
        [
            SourceChoice(
                source_type=focus["source_type"],
                source_id=row.source_id,
                expected_revision=row.source_revision,
            )
        ],
    )[0]


def apply(session, ctx, run, body, change):
    if change.kind == "clear":
        body.pop("context_selection", None)
        body["focus_objects"] = [ref for ref in body["focus_objects"] if ref["kind"] != "source"]
        return
    selected = resolve(session, ctx, run, change.sources) if change.sources else []
    condition = deepcopy(
        body.get("context_selection")
        or {
            "version": 1,
            "status": "available",
            "focus": None,
            "version_mode": "any",
            "versions": [],
            "sources": None,
        }
    )
    if condition.get("status") != "available":
        raise DomainError("SOURCE_UNAVAILABLE", "请先解除失效的资料条件，再重新选择。")
    if change.kind == "replace_focus":
        condition["focus"] = selected[0]
        # Keep the actual selected version until a Human explicitly selects
        # another version/current head. The business scope and literals survive.
        condition.update(version_mode="fixed", versions=selected, sources=None)
        body["focus_objects"] = [
            ref for ref in body["focus_objects"] if ref["kind"] not in {"artifact", "source"}
        ]
        body["focus_objects"].append(
            {
                "kind": "source",
                "id": selected[0]["object_id"],
                "version": selected[0]["source_revision"],
                "run_id": str(run.id),
                "title": selected[0]["title"],
            }
        )
    elif change.kind == "fixed_versions":
        condition.update(version_mode="fixed", versions=selected, sources=None)
        if condition.get("focus") and any(
            (row["source_type"], row["object_id"])
            != (
                condition["focus"]["source_type"],
                condition["focus"]["object_id"],
            )
            for row in selected
        ):
            condition["focus"] = None
        elif condition.get("focus"):
            condition["focus"] = selected[0]
    elif change.kind == "current_only":
        if condition.get("focus"):
            condition["focus"] = _current_focus(session, ctx, run, condition["focus"])
        condition.update(
            version_mode="current", versions=[],
            sources=[condition["focus"]] if condition.get("focus") else None,
        )
    else:
        condition.update(sources=selected, focus=None, version_mode="any", versions=[])
    body["focus_objects"] = [
        ref for ref in body["focus_objects"] if ref["kind"] not in {"artifact", "source"}
    ]
    body["context_selection"] = condition


def public(session, ctx, run, condition):
    try:
        return recheck(session, ctx, run, condition)
    except DomainError as error:
        if error.code not in {
            "FORBIDDEN_SCOPE",
            "NOT_FOUND",
            "SOURCE_UNAVAILABLE",
            "SOURCE_STALE",
            "VERSION_CONFLICT",
        }:
            raise
        return {
            "version": 1,
            "status": "unavailable",
            "focus": None,
            "version_mode": "any",
            "versions": [],
            "sources": None,
        }


def selected_reads(session, ctx, parent, state, incoming):
    """Replace an artifact version only after an explicit verified Human choice."""
    from pdos_next.contracts import SourceRead

    condition = (
        recheck(session, ctx, parent, state.body.get("context_selection")) if state else None
    )
    refs = {} if condition else {ref["artifact_id"]: dict(ref) for ref in parent.read_sources}
    fixed = {row["source_id"]: row for row in values(condition) if row["source_type"] == "artifact"}
    for identity, row in fixed.items():
        if (
            parent.category_id is None
            or parent.product_id is not None
            and row.get("product_id") not in {None, str(parent.product_id)}
        ):
            continue  # A discussion pin is not a business Run read-set.
        refs[identity] = {"artifact_id": identity, "expected_revision": row["source_revision"]}
    for ref in incoming:
        identity = str(ref.artifact_id)
        if identity in refs and refs[identity]["expected_revision"] != ref.expected_revision:
            raise DomainError("VERSION_CONFLICT", "新增来源不能替换原固定版本，请明确选择版本。")
        refs.setdefault(identity, ref.model_dump(mode="json"))
    # Keep every original Run unchanged. Superseded mutable artifact rows can
    # remain dated history, but cannot be rebound as a readable old version.
    return [
        SourceRead.model_validate({key: value for key, value in ref.items() if key != "product_id"})
        for ref in refs.values()
    ], condition


def frozen_condition(run):
    state = run.versions.get("work_state", {})
    if not state:
        return requested(run)[0]
    if state and digest(state) != run.versions.get("work_state_digest"):
        raise DomainError("VERSION_CONFLICT", "本轮已保存的携带条件无法核对。")
    condition = state.get("context_selection")
    condition = validated(condition) if condition else None
    if condition and condition.get("status") != "available":
        raise DomainError("SOURCE_UNAVAILABLE", "选定条件已不可用，请重新选择或解除限定。")
    return condition


def accepts(item, condition, *, actual=None):
    if not condition:
        return True
    focus = condition.get("focus")
    if focus and (item.get("source_type"), item.get("object_id")) != (
        focus["source_type"],
        focus["object_id"],
    ):
        return False
    for rows in (
        condition.get("sources"),
        condition.get("versions") if condition["version_mode"] == "fixed" else None,
    ):
        if rows is not None and not any(
            all(
                str(item.get(key)) == str(ref[key])
                for key in (
                    "source_type",
                    "source_id",
                    "source_revision",
                    "content_hash",
                )
            )
            for ref in rows
        ):
            return False
    # Actual currentness is a retrieval condition, never applicability proof.
    return condition["version_mode"] != "current" or actual is None or bool(actual["is_current"])


def options(session, ctx, run, query, *, object_id=None):
    """Bounded metadata chooser; ordinary RLS and dependencies precede paging."""
    from pdos_next.enterprise_search.assistant_sources import current
    from pdos_next.enterprise_search.context_option_safety import before_paging
    from pdos_next.enterprise_search.schemas import SOURCE_TYPES
    from pdos_next.enterprise_search.sources import prepare_read, retrieval_catalog

    prepare_read(session, SOURCE_TYPES)
    source = retrieval_catalog(SOURCE_TYPES)
    fields = [column for column in source.c if column.key not in {"body", "structured"}]
    statement = _scope(select(*fields), source.c, run)
    if object_id is not None:
        statement = statement.where(source.c.object_id == object_id)
    elif query.strip():
        # Literal title search, not a model-produced broad query or SQL fragment.
        statement = statement.where(source.c.title.icontains(query.strip(), autoescape=True))
    else:
        return {"items": [], "has_more": False}
    statement = before_paging(session, source, statement)
    rows = (
        session.execute(
            statement.order_by(source.c.title, source.c.source_type, source.c.source_id).limit(41)
        )
        .mappings()
        .all()
    )
    candidates = {
        str(index): {
            key: str(value) if isinstance(value, UUID) else value for key, value in row.items()
        }
        for index, row in enumerate(rows)
    }
    actual, _missing = current(session, candidates)
    items = [
        {
            field: row[field]
            for field in (
                "source_type",
                "source_id",
                "object_id",
                "source_revision",
                "title",
                "is_current",
            )
        }
        for key, row in candidates.items()
        if key in actual
    ]
    return {"items": items[:40], "has_more": len(items) > 40, "artifact_history": "unavailable"}


def configure_start(session, ctx, run, original_start, effective_start, parent):
    """Public API hook in the create/dispatch UOW; only original Human input limits sources."""
    from .work_state import latest

    state = latest(session, parent.session_id) if parent is not None else None
    condition = recheck(session, ctx, run, state.body.get("context_selection")) if state else None
    if original_start.sources:
        choices = [
            SourceChoice(
                source_type="artifact",
                source_id=ref.artifact_id,
                expected_revision=ref.expected_revision,
            )
            for ref in original_start.sources
        ]
        selected = resolve(session, ctx, run, choices)
        condition = condition or {
            "version": 1,
            "status": "available",
            "focus": None,
            "version_mode": "any",
            "versions": [],
            "sources": None,
        }
        condition.update(sources=selected, focus=None, version_mode="any", versions=[])
    condition = validated(condition) if condition else None
    run.versions = {
        **run.versions,
        "requested_context_selection": condition,
        "requested_context_selection_digest": digest(condition),
        "context_selection_start_revision": state.revision if state else 0,
    }


def requested(run):
    if "requested_context_selection" not in run.versions:
        return None, False
    condition = run.versions["requested_context_selection"]
    if digest(condition) != run.versions.get("requested_context_selection_digest"):
        raise DomainError("VERSION_CONFLICT", "本轮显式选择无法核对。")
    return validated(condition) if condition else None, True
