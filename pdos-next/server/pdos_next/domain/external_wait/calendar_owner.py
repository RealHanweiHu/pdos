"""Explicit adoption of real project/Build calendars under ordinary source RLS.

These are adopted project or resource calendars, never an inferred supplier
calendar. A later version does not rewrite the selected calendar; current source
withdrawal, loss of access or resource withdrawal still prevents further use.
"""

from collections.abc import Mapping
from copy import deepcopy
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import and_, select

from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.build_operational_facts.schemas import ResourceInput
from pdos_next.domain.builds.models import Build
from pdos_next.domain.planning.calendar import ScheduleError, WorkingCalendar
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.domain.projects import service as projects
from pdos_next.domain.projects.models import PlanProposal, PlanRevision
from pdos_next.domain.quality_execution.evidence import refs_from_exact
from pdos_next.domain.work_management import owner as work_owner
from pdos_next.engines.planning.calendar import CalendarError, WorkingTime
from pdos_next.engines.planning.dto import CalendarSnapshot
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.schemas.planning import Calendar
from pdos_next.service import digest
from pdos_next.source_current import direct_source_basis

_SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
_UNSET = object()


class Ref(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    id: UUID
    revision: int = Field(strict=True, ge=1)
    calendar_key: str = Field(min_length=1)
    calendar_version: str = Field(min_length=1)
    resource_id: str | None = None

    @model_validator(mode="after")
    def precise(self):
        if self.kind not in {"project_plan", "build_resource"}:
            raise ValueError("Only native project/Build calendars may be adopted")
        if self.kind == "project_plan" and self.resource_id is not None:
            raise ValueError("Project calendars have no resource selection")
        if self.kind == "build_resource":
            if self.resource_id is None or str(UUID(self.resource_id)) != self.resource_id:
                raise ValueError("A resource calendar needs its exact native UUID")
        return self


def _require(ok, message="所选日历来源已变化或不再适用。", *, unavailable=False):
    if not ok:
        raise DomainError(
            "SOURCE_UNAVAILABLE" if unavailable else "SOURCE_STALE",
            message,
            403 if unavailable else 409,
        )


def _ref(value):
    try:
        return Ref.model_validate(value.model_dump() if isinstance(value, BaseModel) else value)
    except (ValidationError, ValueError, TypeError):
        raise DomainError("VALIDATION_FAILED", "须显式选择真实日历的完整固定引用。", 422) from None


def _project(s, ctx, pid, project_id):
    try:
        project = work_owner.project(s, ctx, pid, project_id)
    except DomainError as error:
        if error.status == 403:
            _require(False, "项目或其日历当前不可读。", unavailable=True)
        raise
    _require(
        project is not None
        and (project.tenant_id, project.category_id, project.product_id, project.id)
        == (ctx.tenant_id, ctx.category_id, pid, project_id),
        "项目或其日历当前不可读。",
        unavailable=True,
    )
    return project


def _scoped(row, ctx, pid, project_id):
    _require(row is not None, "所选日历来源当前不可读。", unavailable=True)
    _require(
        tuple(getattr(row, key) for key in _SCOPE)
        == (ctx.tenant_id, ctx.category_id, pid, project_id),
        "日历来源不属于当前实际项目范围。",
        unavailable=True,
    )


def _scope(ctx, pid, project_id):
    return {
        "tenant_id": str(ctx.tenant_id),
        "category_id": str(ctx.category_id),
        "product_id": str(pid),
        "project_id": str(project_id),
    }


def _plan_query(ctx, pid, project_id):
    plan, proposal = PlanRevision, PlanProposal
    return (
        select(plan, proposal)
        .join(
            proposal,
            and_(
                *(getattr(plan, key) == getattr(proposal, key) for key in _SCOPE),
                plan.proposal_id == proposal.id,
            ),
        )
        .where(
            plan.tenant_id == ctx.tenant_id,
            plan.category_id == ctx.category_id,
            plan.product_id == pid,
            plan.project_id == project_id,
            plan.status == "applied",
        )
    )


def _calendar(value):
    calendar = CalendarSnapshot.model_validate(value)
    clock = WorkingTime(calendar)
    return calendar.model_copy(
        update={"timezone_rules_sha256": clock.timezone_rules_sha256}
    ).model_dump(mode="json")


def _finish(ctx, pid, project_id, ref, calendar, source_calendar, material, *, current=None):
    fixed = {
        "scope": _scope(ctx, pid, project_id),
        "ref": ref.model_dump(mode="json"),
        "source_calendar": deepcopy(source_calendar),
        "calendar_sha256": digest(calendar),
        "material": material,
    }
    basis = {**fixed, "digest": digest(fixed)}
    if current is not None:
        basis["current"] = current
    return {"ref": fixed["ref"], "calendar": calendar, "basis": basis}


def _plan_result(s, ctx, pid, project_id, plan, proposal, ref=None, expected=None):
    _scoped(plan, ctx, pid, project_id)
    _scoped(proposal, ctx, pid, project_id)
    _require(plan.status == "applied" and plan.proposal_id == proposal.id)
    raw = Calendar.model_validate(proposal.input_snapshot["calendar"])
    # This is the existing planning adapter's real CalendarSnapshot conversion.
    clock = WorkingCalendar(raw)
    calendar = _calendar(clock._engine.definition)
    actual = Ref(
        kind="project_plan",
        id=plan.id,
        revision=plan.revision,
        calendar_key=raw.key,
        calendar_version=raw.version,
    )
    _require(ref is None or actual == ref)
    recorded = plan.forecast.get("calendar_ref", {})
    _require(
        recorded.get("key") == raw.key
        and recorded.get("version") == raw.version
        and recorded.get("timezone") == raw.timezone
        and recorded.get("timezone_rules_sha256") == clock.timezone_rules_sha256
    )
    _, link, definition = projects._project(s, ctx, pid, project_id)
    _require(definition["source_status"] == "current", "计划原始来源已撤回或不可读。")
    references = [
        {key: value[key] for key in ("artifact_id", "expected_revision", "line", "quote")}
        for value in definition["sources"]
    ]
    source_basis = _sources(
        s,
        ctx,
        pid,
        references,
        expected["material"]["source_basis"] if expected else None,
    )
    return _finish(
        ctx,
        pid,
        project_id,
        actual,
        calendar,
        proposal.input_snapshot["calendar"],
        {
            "plan_id": str(plan.id),
            "plan_revision": plan.revision,
            "proposal_id": str(proposal.id),
            "proposal_revision": proposal.revision,
            "input_calendar_sha256": digest(raw.model_dump(mode="json")),
            "definition_ref": {"id": str(link.definition_id), "revision": link.definition_revision},
            "source_basis": source_basis,
        },
    )


def _current_query(ctx, pid, project_id):
    pointer, fact = BuildOperationalCurrent, BuildOperationalFact
    return (
        select(pointer, fact, Build)
        .select_from(pointer)
        .join(
            fact,
            and_(
                *(getattr(pointer, key) == getattr(fact, key) for key in _SCOPE),
                pointer.build_id == fact.build_id,
                pointer.fact_id == fact.id,
                pointer.fact_revision == fact.revision,
            ),
        )
        .join(
            Build,
            and_(
                *(getattr(fact, key) == getattr(Build, key) for key in _SCOPE),
                fact.build_id == Build.id,
            ),
        )
        .where(
            pointer.tenant_id == ctx.tenant_id,
            pointer.category_id == ctx.category_id,
            pointer.product_id == pid,
            pointer.project_id == project_id,
        )
    )


def _fact(s, ctx, pid, project_id, fact):
    _scoped(fact, ctx, pid, project_id)
    at = now()
    _require(
        fact.state == "active"
        and fact.valid_from <= at
        and (fact.valid_until is None or at < fact.valid_until)
        and operational._fact_hash(fact) == fact.fact_sha256
    )
    issuer = getattr(s.get_bind(), "_pdos_operational_issuers", {}).get(fact.issuer_key)
    _require(issuer is not None, "日历原事实签发端已失效。")
    try:
        operational._issuer(s, ctx, pid, project_id, issuer)
    except DomainError:
        _require(False, "日历原事实签发端已失效。")
    _require(
        (issuer.version, issuer.epoch, issuer.nature)
        == (fact.issuer_version, fact.issuer_epoch, fact.nature)
    )
    return [ResourceInput.model_validate(value) for value in fact.data["resources"]]


def _sources(s, ctx, pid, references, expected=None):
    raw = [
        value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        for value in references
    ]
    reads = [
        {"artifact_id": value["artifact_id"], "expected_revision": value["expected_revision"]}
        for value in raw
    ]
    if expected is not None:
        _require(expected["references_sha256"] == digest(raw))
        _require(
            {(str(value["artifact_id"]), value["expected_revision"]) for value in raw}
            == {(value["id"], value["revision"]) for value in expected["artifacts"]}
        )
        work_owner.sources_current(s, ctx, pid, {"artifacts": expected["artifacts"]})
        return deepcopy(expected)
    refs = refs_from_exact(
        s, ctx, pid, tuple(DefinitionReference.model_validate(value) for value in raw)
    )
    basis, _private = direct_source_basis(s, ctx, pid, refs, reads)
    return {"references_sha256": digest(raw), "artifacts": basis}


def _resource_result(
    s,
    ctx,
    pid,
    project_id,
    fixed,
    pointer,
    current,
    build,
    resource,
    *,
    ref=None,
    expected=None,
    asset=_UNSET,
):
    resources = _fact(s, ctx, pid, project_id, fixed)
    live_resources = (
        resources if current.id == fixed.id else _fact(s, ctx, pid, project_id, current)
    )
    _scoped(build, ctx, pid, project_id)
    _scoped(pointer, ctx, pid, project_id)
    _require(
        current.series_id == fixed.series_id
        and current.build_id == fixed.build_id == build.id == pointer.build_id
        and (pointer.fact_id, pointer.fact_revision) == (current.id, current.revision)
    )
    actual = next((value for value in resources if value.resource.id == resource), None)
    live = next((value for value in live_resources if value.resource.id == resource), None)
    _require(
        actual is not None
        and actual.lifecycle == "active"
        and actual.calendar is not None
        and live is not None
        and live.lifecycle == "active"
        and live.calendar is not None
        and live.calendar.calendar_id == actual.calendar.calendar_id,
        "所选资源日历已撤回或当前资源不再适用。",
    )
    if asset is _UNSET:
        asset = s.scalar(
            select(OperationalAsset).where(
                OperationalAsset.tenant_id == ctx.tenant_id, OperationalAsset.id == resource
            )
        )
    _require(asset is not None, "资源当前物理记录不可读。", unavailable=True)
    _require(
        asset.kind == "resource"
        and asset.revision == live.resource.revision
        and asset.data
        == {"value": operational._physical(live.model_dump(mode="json")), "state": "active"}
        and asset.data_sha256 == operational.digest(asset.data["value"])
    )
    calendar = _calendar(actual.calendar)
    actual_ref = Ref(
        kind="build_resource",
        id=fixed.id,
        revision=fixed.revision,
        calendar_key=calendar["calendar_id"],
        calendar_version=calendar["version"],
        resource_id=str(resource),
    )
    _require(ref is None or actual_ref == ref)
    references = [
        *fixed.sources,
        *(value.model_dump(mode="json") for value in actual.calendar_sources),
    ]
    selected = {digest(value): value for value in references}
    sources = _sources(
        s,
        ctx,
        pid,
        [selected[key] for key in sorted(selected)],
        expected["material"]["source_basis"] if expected else None,
    )
    if current.id != fixed.id:
        live_refs = [
            *current.sources,
            *(value.model_dump(mode="json") for value in live.calendar_sources),
        ]
        selected = {digest(value): value for value in live_refs}
        _sources(s, ctx, pid, [selected[key] for key in sorted(selected)])
    return _finish(
        ctx,
        pid,
        project_id,
        actual_ref,
        calendar,
        next(
            value["calendar"]
            for value in fixed.data["resources"]
            if value["resource"]["id"] == str(resource)
        ),
        {
            "build_id": str(build.id),
            "fact_id": str(fixed.id),
            "fact_revision": fixed.revision,
            "fact_sha256": fixed.fact_sha256,
            "resource_id": str(resource),
            "resource_revision": actual.resource.revision,
            "source_basis": sources,
        },
        current={"fact_id": str(current.id), "revision": current.revision, "epoch": pointer.epoch},
    )


def _resolve(s, ctx, pid, project_id, ref, expected=None):
    _project(s, ctx, pid, project_id)
    if ref.kind == "project_plan":
        rows = s.execute(
            _plan_query(ctx, pid, project_id).where(PlanRevision.id == ref.id)
        ).one_or_none()
        _require(rows is not None, "已采纳计划日历当前不可读。", unavailable=True)
        return _plan_result(s, ctx, pid, project_id, *rows, ref, expected)
    fixed = s.scalar(
        select(BuildOperationalFact).where(
            BuildOperationalFact.tenant_id == ctx.tenant_id,
            BuildOperationalFact.category_id == ctx.category_id,
            BuildOperationalFact.product_id == pid,
            BuildOperationalFact.project_id == project_id,
            BuildOperationalFact.id == ref.id,
        )
    )
    _require(fixed is not None, "所选资源日历原事实当前不可读。", unavailable=True)
    _require(fixed.revision == ref.revision)
    rows = s.execute(
        _current_query(ctx, pid, project_id).where(Build.id == fixed.build_id)
    ).one_or_none()
    _require(rows is not None, "所选资源的当前事实不可读。", unavailable=True)
    return _resource_result(
        s, ctx, pid, project_id, fixed, *rows, UUID(ref.resource_id), ref=ref, expected=expected
    )


def resolve(s, ctx, pid, project_id, ref):
    """Return {ref, calendar: CalendarSnapshot JSON, basis}; no inline calendars."""
    try:
        return _resolve(s, ctx, pid, project_id, _ref(ref))
    except (ValidationError, CalendarError, ScheduleError, KeyError, TypeError, ValueError):
        _require(False, "已登记日历的内容、版本或时区规则无法核对。")


def recheck(s, ctx, pid, project_id, expected_basis):
    """Retain the fixed version; re-evaluate any new Current's applicability."""
    _require(isinstance(expected_basis, Mapping))
    try:
        expected = deepcopy(dict(expected_basis))
        ref = _ref(expected["ref"])
        actual = _resolve(s, ctx, pid, project_id, ref, expected)["basis"]
        # Current advancement alone is not withdrawal of an adopted calendar.
        actual.pop("current", None)
        expected.pop("current", None)
        _require(actual == expected)
        return True
    except (ValidationError, CalendarError, ScheduleError, KeyError, TypeError, ValueError):
        _require(False)


def available(s, ctx, pid, project_id, build_ref=None):
    """Offer only the current applied plan and current same-project resource facts."""
    project = _project(s, ctx, pid, project_id)
    results = []
    if project.current_plan_id is not None:
        rows = s.execute(
            _plan_query(ctx, pid, project_id).where(PlanRevision.id == project.current_plan_id)
        ).one_or_none()
        if rows is not None:
            result = _plan_result(s, ctx, pid, project_id, *rows)
            results.append(
                {
                    "ref": result["ref"],
                    "label": "采用的项目工作日历",
                    "calendar": result["calendar"],
                }
            )
    query = _current_query(ctx, pid, project_id)
    if build_ref is not None:
        value = build_ref.model_dump() if isinstance(build_ref, BaseModel) else build_ref
        query = query.where(Build.id == UUID(str(value["id"])), Build.revision == value["revision"])
    candidates = []
    for pointer, fact, build in s.execute(query):
        try:
            resources = _fact(s, ctx, pid, project_id, fact)
            candidates.extend(
                (pointer, fact, build, resource)
                for resource in resources
                if resource.calendar is not None and resource.lifecycle == "active"
            )
        except DomainError as error:
            if error.reason not in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}:
                raise
    identities = {resource.resource.id for _, _, _, resource in candidates}
    assets = (
        {
            value.id: value
            for value in s.scalars(
                select(OperationalAsset).where(
                    OperationalAsset.tenant_id == ctx.tenant_id, OperationalAsset.id.in_(identities)
                )
            )
        }
        if identities
        else {}
    )
    for pointer, fact, build, resource in candidates:
        try:
            # Assets were loaded once for the complete candidate set.
            result = _resource_result(
                s,
                ctx,
                pid,
                project_id,
                fact,
                pointer,
                fact,
                build,
                resource.resource.id,
                asset=assets.get(resource.resource.id),
            )
            results.append(
                {
                    "ref": result["ref"],
                    "label": "采用的资源工作日历 · "
                    f"{resource.resource.kind} · {resource.resource.id}",
                    "calendar": result["calendar"],
                }
            )
        except DomainError as error:
            if error.reason not in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}:
                raise
    return results
