"""Turn project facts into the validation basis for NPI plan commands."""

import json
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from pdos_next.core.models import Grant, Principal
from pdos_next.domain.categories.preproject.baseline import validate_sources
from pdos_next.domain.categories.preproject.category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ParameterCurrent,
    ParameterVersion,
)
from pdos_next.domain.categories.preproject.models import ProjectOpenItem, ProposalDecision
from pdos_next.domain.categories.preproject.schemas import Reference
from pdos_next.domain.categories.products.definitions import definition_view
from pdos_next.domain.categories.products.models import DefinitionRevision
from pdos_next.domain.projects.planning.engine.dto import WorkInterval
from pdos_next.domain.projects.team import roles
from pdos_next.domain.projects.team.models import MemberRole, ProjectMember
from pdos_next.domain.work_calendar import rules as calendar_rules
from pdos_next.domain.work_calendar.service import factory
from pdos_next.errors import DomainError
from pdos_next.schemas.planning import Calendar

from .catalog import difference, effective, project_type, view
from .models import FrameworkRevision
from .rules import Framework, Source, applicable, attributes, check, path_for


def current_definition(s, ctx, product_id, variant_id):
    row = s.scalar(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.category_id == ctx.category_id,
            DefinitionRevision.product_id == product_id,
            DefinitionRevision.variant_id == variant_id,
        )
        .order_by(DefinitionRevision.revision.desc())
        .limit(1)
    )
    if row is None:
        raise DomainError("SOURCE_UNAVAILABLE", "当前型号定义不可读。", 403)
    return row, definition_view(s, ctx, row)


def material(s, ctx, project, definition, *, framework_id=None):
    row = s.get(FrameworkRevision, framework_id or project.framework_id)
    if (
        row is None or row.state != "published" or row.project_type != project_type(project)
        or row.tenant_id != ctx.tenant_id or row.category_id != ctx.category_id
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "项目尚未绑定可核对的框架版本。")
    decision = s.get(ProposalDecision, project.g0_decision_id)
    risk = attributes(definition)
    path = path_for(
        risk, force_full=bool(decision and decision.creation.get("force_full_npi_path"))
    )
    stages, outcomes, metrics = applicable(Framework.model_validate(row.document), risk, path)
    return row, path, risk, stages, outcomes, metrics


def assignments(s, ctx, project):
    from pdos_next.core.models import now

    keys = {role["key"] for role in roles.current(s, ctx.tenant_id)["roles"] if role["active"]}
    people = {key: [] for key in sorted(keys)}
    query = (
        select(MemberRole.role_key, ProjectMember.principal_id)
        .join(
            ProjectMember,
            (ProjectMember.tenant_id == MemberRole.tenant_id)
            & (ProjectMember.id == MemberRole.member_id),
        )
        .join(
            Principal,
            (Principal.tenant_id == ProjectMember.tenant_id)
            & (Principal.id == ProjectMember.principal_id),
        )
        .join(
            Grant,
            (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
        )
        .where(
            ProjectMember.tenant_id == ctx.tenant_id,
            ProjectMember.project_id == project.id,
            ProjectMember.left_at.is_(None),
            Principal.active.is_(True),
            Principal.kind == "human",
            Grant.category_id == ctx.category_id,
            Grant.can_write.is_(True),
            Grant.expires_at.is_(None) | (Grant.expires_at > now()),
            MemberRole.role_key.in_(keys),
        )
        .order_by(MemberRole.role_key, ProjectMember.principal_id)
    )
    for key, person in s.execute(query):
        people[key].append(str(person))
    return people


def _sources(s, ctx, project, definition, framework, outcomes):
    def reference(kind, identity, revision, key=None):
        return Source(kind=kind, id=str(identity), revision=revision, key=key)

    pairs = [
        (
            reference("framework_outcome", framework.id, framework.revision, outcome.key),
            outcome.model_dump(mode="json"),
        )
        for outcome in outcomes
    ]
    pairs.append(
        (
            reference("definition", definition["id"], definition["revision"]),
            {
                "title": definition["title"],
                "specs": definition["specs"],
                "item_versions": definition["item_versions"],
            },
        )
    )
    for row in s.scalars(
        select(KnowledgeEntry)
        .join(
            KnowledgeCurrent,
            KnowledgeCurrent.current_entry_id == KnowledgeEntry.id,
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeCurrent.status == "active",
        )
        .order_by(KnowledgeEntry.kind, KnowledgeEntry.id)
    ):
        pairs.append(
            (
                reference("category_knowledge", row.id, row.version),
                {"kind": row.kind, "content": row.content},
            )
        )
    for row in s.scalars(
        select(ParameterVersion)
        .join(
            ParameterCurrent,
            (ParameterCurrent.tenant_id == ParameterVersion.tenant_id)
            & (ParameterCurrent.parameter_id == ParameterVersion.parameter_id)
            & (ParameterCurrent.current_version == ParameterVersion.version),
        )
        .where(
            ParameterVersion.tenant_id == ctx.tenant_id,
            ParameterVersion.category_id == ctx.category_id,
        )
        .order_by(ParameterVersion.key)
    ):
        pairs.append(
            (
                reference("parameter", row.parameter_id, row.version),
                {
                    "key": row.key,
                    "name": row.name,
                    "value_type": row.value_type,
                    "unit": row.unit,
                    "method": row.method,
                    "standard_condition": row.standard_condition,
                    "acceptance_criterion": row.acceptance_criterion,
                },
            )
        )
    for row in s.scalars(
        select(ProjectOpenItem)
        .where(
            ProjectOpenItem.tenant_id == ctx.tenant_id,
            ProjectOpenItem.project_id == project.id,
            ProjectOpenItem.g0_decision_id == project.g0_decision_id,
        )
        .order_by(ProjectOpenItem.id)
    ):
        pairs.append(
            (
                reference("g0_open_item", row.id, 1),
                {
                    "g0_decision_id": str(row.g0_decision_id),
                    "title": row.title,
                    "note": row.note,
                    "kind": row.kind,
                    "due_date": row.due_date.isoformat(),
                },
            )
        )
    return pairs


def read(s, ctx, project, link):
    result = {
        "project_id": str(project.id),
        "project_revision": project.revision,
        "framework": None,
        "new_framework": None,
        "differences": [],
    }
    from .continuation import run_view

    result["generation"] = run_view(s, ctx, project)
    if project.framework_id is None:
        return result | {"state": "framework_unavailable"}
    _, definition = current_definition(s, ctx, project.product_id, link.variant_id)
    row, path, risk, stages, outcomes, metrics = material(s, ctx, project, definition)
    latest = effective(s, ctx, row.project_type)
    if latest and latest.id != row.id:
        result.update(
            new_framework=view(latest), differences=difference(row.document, latest.document)
        )
    return result | {
        "state": "ready",
        "framework": view(row),
        "path": path,
        "attributes": risk,
        "stages": [item.model_dump(mode="json") for item in stages],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "sources": [
            {"ref": ref.model_dump(mode="json"), "value": value}
            for ref, value in _sources(s, ctx, project, definition, row, outcomes)
        ],
        "roles": assignments(s, ctx, project),
    }


def validate_plan(s, ctx, project, link, plan_basis, schedule, reads, *, allow_upgrade=False):
    from pdos_next.core.service import digest, source_for

    if project.framework_id is None and plan_basis is None:
        return None
    if plan_basis is None or project.framework_id is None:
        raise DomainError("VALIDATION_FAILED", "计划必须使用项目固定的框架版本。", 422)
    upgrade = None
    if plan_basis.framework_id != project.framework_id:
        if not allow_upgrade:
            raise DomainError("CONFIRMATION_REQUIRED", "框架升级须由项目负责人确认。")
        pinned = s.get(FrameworkRevision, project.framework_id)
        latest = effective(s, ctx, project_type(project))
        if not pinned or not latest or latest.id != plan_basis.framework_id:
            raise DomainError("VERSION_CONFLICT", "框架升级须采用当前发布版本。")
        upgrade = {
            "from": {"id": str(pinned.id), "revision": pinned.revision},
            "to": {"id": str(latest.id), "revision": latest.revision},
            "differences": difference(pinned.document, latest.document),
        }
    _, definition = current_definition(s, ctx, project.product_id, link.variant_id)
    row, path, _, stages, outcomes, metrics = material(
        s, ctx, project, definition, framework_id=plan_basis.framework_id
    )
    if row.revision != plan_basis.framework_revision:
        raise DomainError("VERSION_CONFLICT", "框架版本不匹配。")
    pairs = _sources(s, ctx, project, definition, row, outcomes)
    authorized = {ref.ref for ref, _ in pairs}
    claimed = {ref.ref for task in plan_basis.tasks.values() for ref in task.sources}
    estimates = {}
    read_versions = {str(source.artifact_id): source.expected_revision for source in reads}
    for kind, identity, revision, key in sorted(claimed, key=str):
        if kind != "artifact" or key is not None or read_versions.get(identity) != revision:
            continue
        artifact = source_for(s, ctx, project.product_id, UUID(identity), revision)
        if artifact.visibility == "private" and project.visibility != "private":
            continue
        ref = (kind, identity, revision, key)
        authorized.add(ref)
        try:
            facts = json.loads(artifact.content)
        except (TypeError, ValueError):
            continue
        bounds = facts.get("duration_minutes") if isinstance(facts, dict) else None
        if (
            isinstance(bounds, list)
            and len(bounds) == 2
            and all(type(n) is int and 0 < n <= 525600 for n in bounds)
            and bounds[0] <= bounds[1]
        ):
            task_key = facts.get("task_key")
            if isinstance(task_key, str):
                estimates[ref, task_key] = tuple(bounds)
    people = assignments(s, ctx, project)
    issues = check(
        stages=stages,
        outcomes=outcomes,
        tasks=schedule.tasks,
        basis=plan_basis,
        sources=authorized,
        role_keys=people.keys(),
        estimates=estimates,
    )
    if issues:
        raise DomainError(
            "VALIDATION_FAILED",
            "计划未通过框架检查。",
            422,
            detail={
                "framework_id": str(row.id),
                "framework_revision": row.revision,
                "issues": issues,
            },
        )
    extra = [
        Reference(
            type="knowledge" if kind == "category_knowledge" else "parameter",
            id=UUID(identity),
            version=revision,
        )
        for kind, identity, revision, _ in sorted(claimed, key=str)
        if kind in {"category_knowledge", "parameter"}
    ]
    validate_sources(s, ctx, definition, extra_refs=extra)
    for source in definition["sources"]:
        identity, revision = source["artifact_id"], source["expected_revision"]
        if read_versions.get(identity) != revision:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "须固定当前定义引用的来源版本。")
    definition_basis = digest(
        {
            "id": definition["id"],
            "revision": definition["revision"],
            "item_versions": definition["item_versions"],
        }
    )
    return {
        "framework": {"id": str(row.id), "revision": row.revision},
        **({"framework_upgrade": upgrade} if upgrade else {}),
        "path": path,
        "definition_basis": definition_basis,
        "source_read_set": [
            {"artifact_id": identity, "expected_revision": revision}
            for identity, revision in sorted(read_versions.items())
        ],
        "definition_id": definition["id"],
        "stages": [item.model_dump(mode="json") for item in stages],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "assignments": {
            key: people[entry.role][0] if len(people[entry.role]) == 1 else None
            for key, entry in plan_basis.tasks.items()
        },
        "role_exceptions": [
            {
                "task_key": key,
                "role": entry.role,
                "reason": "role_missing" if not people[entry.role] else "role_ambiguous",
            }
            for key, entry in sorted(plan_basis.tasks.items())
            if len(people[entry.role]) != 1
        ],
    }


def scheduling_calendar(s, ctx, schedule):
    selected = factory(s, ctx.tenant_id)
    basis = {**calendar_rules.basis(selected), "shift_basis": "按当地 09:00–17:00 估算"}
    start = schedule.start.astimezone(ZoneInfo(basis["timezone"])).date()
    intervals = (WorkInterval(start_minute=9 * 60, end_minute=17 * 60),)
    entries = selected.definition.entries if selected else ()
    first = min((entry.start for entry in entries), default=start)
    last = max((entry.end for entry in entries), default=start)
    snapshot = calendar_rules.planning_snapshot(selected, intervals, first, last)
    calendar = Calendar(
        key=snapshot.calendar_id,
        version=snapshot.version,
        timezone=snapshot.timezone,
        working_weekdays=tuple(item.weekday for item in snapshot.weekly),
        intervals=tuple(interval.model_dump() for interval in intervals),
        holidays=tuple(item.day for item in snapshot.exceptions if not item.intervals),
        makeup_workdays=tuple(item.day for item in snapshot.exceptions if item.intervals),
    )
    return schedule.model_copy(update={"calendar": calendar}), basis
