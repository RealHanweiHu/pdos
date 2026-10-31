"""Common T1/T2 commands for adopted stages and frozen, named gate reviews."""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.domain.preproject.access import human
from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.domain.projects.service import _project
from pdos_next.domain.work_management.rules import require
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.service import digest, source_for

from .models import GovernanceEvent
from .rules import LABELS, aggregate, health, stable, templates
from .schemas import AdoptPayload, BaselinePayload, DecidePayload, MilestonePayload, ReviewPayload

category_lifecycle_fence = True


def events(s, ctx, project_id):
    return list(
        s.scalars(
            select(GovernanceEvent)
            .where(
                GovernanceEvent.tenant_id == ctx.tenant_id, GovernanceEvent.project_id == project_id
            )
            .order_by(GovernanceEvent.revision)
        )
    )


def state(rows):
    return (
        deepcopy(rows[-1].body)
        if rows
        else {
            "template": None,
            "stages": [],
            "position": 0,
            "baseline": None,
            "review": None,
            "bindings": {},
        }
    )


def release_evidence(s, ctx, pid, project_id, reference):
    if not reference:
        return None, []
    from pdos_next.domain.release.service import get_package

    row, view = get_package(s, ctx, pid, UUID(reference["id"]))
    require(
        row.project_id == project_id and row.revision == reference["revision"],
        "发布包须对应本项目及固定版本。",
        "FORBIDDEN_SCOPE",
        403,
    )
    # A stage is visible to its project's audience. A private release packet
    # cannot be copied into a wider stage review or directory projection.
    from pdos_next.domain.projects.models import Project
    from pdos_next.models import ObjectAudience

    project = s.get(Project, project_id)
    safe = project.visibility == "private" or row.visibility == "category"
    if not safe and project.visibility == row.visibility == "audience":

        def audience(table, identity, owner):
            return {
                owner,
                *s.scalars(
                    select(ObjectAudience.principal_id).where(
                        ObjectAudience.tenant_id == ctx.tenant_id,
                        ObjectAudience.category_id == ctx.category_id,
                        ObjectAudience.object_type == table,
                        ObjectAudience.subject_id == identity,
                    )
                ),
            }

        safe = audience("projects", project.id, project.owner_id) <= audience(
            "release_packages", row.id, row.owner_id
        )
    require(safe, "发布包受众比项目更窄，不能将私有评审材料带入共享阶段。", "FORBIDDEN_SCOPE", 403)
    current = view.get("current")
    valid = view["applicability"] == "current" and current and current["version"] == reference
    view["current_for_stage"] = bool(valid)
    return stable(view), row.required_source_read_set


def gate(s, ctx, pid, project, body, *, stage=None, reference=None):
    _, _, definition = _project(s, ctx, pid, project.id)
    stage = stage or (
        body["stages"][body["position"]] if body["position"] < len(body["stages"]) else None
    )
    evidence, reads = None, []
    if reference:
        try:
            evidence, reads = release_evidence(s, ctx, pid, project.id, reference)
        except DomainError as error:
            if error.code not in {
                "FORBIDDEN_SCOPE",
                "SOURCE_STALE",
                "SOURCE_UNAVAILABLE",
                "RECHECK_REQUIRED",
                "VERSION_CONFLICT",
            }:
                raise
    g0 = {
        "state": "READY"
        if project.g0_decision_id and definition["source_status"] == "current"
        else "UNKNOWN",
        "detail": "固定 G0 决定与定义来源",
        "ref": str(project.g0_decision_id) if project.g0_decision_id else None,
    }
    baseline = body["baseline"]
    baseline_current = baseline and baseline["plan"]["id"] == str(project.current_plan_id)
    values = {
        "g0": g0,
        "baseline": {
            "state": "READY" if baseline_current else "UNKNOWN",
            "detail": "当前计划已具名批准" if baseline_current else "当前计划尚无适用的批准基线",
            "ref": baseline,
        },
    }
    for discipline in ("engineering", "manufacturing"):
        assessment = evidence["assessments"][discipline] if evidence else None
        valid = bool(evidence and evidence["current_for_stage"])
        approvals = (
            [
                d
                for d in evidence["decisions"]
                if d["discipline"] == discipline
                and d["applicability"] == "current"
                and (
                    not d["decision"].get("expiry")
                    or now()
                    < __import__("datetime").datetime.fromisoformat(
                        d["decision"]["expiry"].replace("Z", "+00:00")
                    )
                )
            ]
            if valid
            else []
        )
        computed = assessment["state"] if valid else "UNKNOWN"
        if computed != "BLOCKED" and not approvals:
            computed = "UNKNOWN"
        values[discipline] = {
            "state": computed,
            "detail": "规则结果与专业签核分别核对",
            "assessment": assessment,
            "decisions": approvals,
            "ref": reference,
        }
    declaration = (
        evidence["package"]["declaration"] if evidence and evidence["current_for_stage"] else None
    )
    scope = declaration["release_scope"] if declaration else None
    # Applicability is an explicit scope, not customer acceptance or external delivery.
    delivery_known = bool(
        scope
        and scope.get("quantity")
        and scope.get("unit")
        and (scope.get("site") or scope.get("regions"))
    )
    values["delivery"] = {
        "state": aggregate([values["engineering"]["state"], values["manufacturing"]["state"]])
        if delivery_known
        else "UNKNOWN",
        "detail": "固定用途、数量及地点/地区；客户承认和真实外发仍独立办理",
        "scope": scope,
        "purpose": declaration["purpose"] if declaration else None,
        "limits": declaration.get("limits", []) if declaration else [],
    }
    checks = (
        [{"key": key, "label": LABELS[key], **values[key]} for key in stage["rules"]]
        if stage
        else []
    )
    required_reads = {r["artifact_id"]: r for r in reads}
    for ref in definition["sources"]:
        required_reads[ref["artifact_id"]] = {
            "artifact_id": ref["artifact_id"],
            "expected_revision": ref["expected_revision"],
        }
    return {
        "stage_id": stage["id"] if stage else None,
        "state": aggregate([c["state"] for c in checks]),
        "checks": checks,
        "maturity": {k: values[k] for k in ("engineering", "manufacturing", "delivery")},
        "release": evidence,
        "required_source_read_set": list(required_reads.values()),
    }


def promise_facts(s, ctx, pid, project_id):
    from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent
    from pdos_next.domain.work_management.models import (
        WorkCommitmentCurrent,
        WorkCommitmentVersion,
        WorkTaskVersion,
    )

    rows = s.execute(
        select(WorkCommitmentVersion, WorkTaskVersion)
        .join(WorkCommitmentCurrent, WorkCommitmentCurrent.version_id == WorkCommitmentVersion.id)
        .join(
            WorkTaskVersion,
            (WorkTaskVersion.task_id == WorkCommitmentVersion.task_id)
            & (WorkTaskVersion.revision == WorkCommitmentVersion.task_revision),
        )
        .where(
            WorkCommitmentVersion.tenant_id == ctx.tenant_id,
            WorkCommitmentVersion.product_id == pid,
            WorkCommitmentVersion.project_id == project_id,
        )
    ).all()
    fulfilled = set(
        s.scalars(
            select(WorkCommitmentReviewCurrent.commitment_id).where(
                WorkCommitmentReviewCurrent.tenant_id == ctx.tenant_id,
                WorkCommitmentReviewCurrent.product_id == pid,
                WorkCommitmentReviewCurrent.state == "fulfilled",
            )
        )
    )
    results = []
    for promise, task in rows:
        b = promise.body
        results.append(
            {
                "id": str(promise.id),
                "task_id": str(promise.task_id),
                "plan_task": task.body.get("plan_task"),
                "promisor_id": str(promise.promisor_id),
                "recipient_id": str(promise.recipient_id),
                "promised_at": b.get("promised_at"),
                "fulfilled": promise.id in fulfilled,
            }
        )
    return results


def view(s, ctx, pid, project_id):
    project, _, _ = _project(s, ctx, pid, project_id)
    rows = events(s, ctx, project.id)
    body = state(rows)
    stages, position = body["stages"], body["position"]
    current = stages[position] if position < len(stages) else None
    # After completion, retain the final stage's actual evidence and dates.
    displayed = current or (stages[-1] if stages else None)
    binding = body["bindings"].get(displayed["id"], {}) if displayed else {}
    review = body.get("review")
    result = gate(
        s, ctx, pid, project, body, stage=displayed, reference=binding.get("release_package")
    )
    next_stage = stages[position + 1] if position + 1 < len(stages) else None
    next_result = (
        gate(
            s,
            ctx,
            pid,
            project,
            body,
            stage={**next_stage, "rules": next_stage.get("entry_rules", [])},
            reference=body["bindings"].get(next_stage["id"], {}).get("release_package"),
        )
        if next_stage
        else None
    )
    promises = promise_facts(s, ctx, pid, project.id)
    from datetime import datetime

    overdue = sum(
        bool(
            p["promised_at"]
            and datetime.fromisoformat(p["promised_at"].replace("Z", "+00:00")) < now()
            and not p["fulfilled"]
        )
        for p in promises
    )
    valid_review = bool(
        review
        and review["stage_id"] == result["stage_id"]
        and review["gate_digest"] == digest(result)
    )
    result["review_current"] = valid_review
    history = [
        {
            "id": str(r.id),
            "revision": r.revision,
            "operation": r.operation,
            "actor_id": str(r.actor_id),
            "at": r.created_at.isoformat(),
            "receipt_id": str(r.receipt_id),
            "reason": r.review.get("reason"),
            "outcome": r.review.get("outcome"),
            "stage_name": r.review.get("stage_name"),
        }
        for r in rows
    ]
    plan = s.get(PlanRevision, project.current_plan_id) if project.current_plan_id else None
    task_key = binding.get("task_key")
    planned = (
        next((t for t in plan.forecast["tasks"] if t["key"] == task_key), None) if plan else None
    )
    baseline_task = next(
        (
            t
            for t in (body["baseline"] or {}).get("forecast", {}).get("tasks", [])
            if t["key"] == task_key
        ),
        None,
    )
    matching_ids = (
        {
            str(t.id)
            for t in s.scalars(
                select(ProjectTask).where(
                    ProjectTask.project_id == project.id, ProjectTask.key == task_key
                )
            )
        }
        if task_key
        else set()
    )
    gate_promises = [p for p in promises if p["plan_task"] and p["plan_task"]["id"] in matching_ids]
    timeline = {
        "task_key": task_key,
        "baseline": baseline_task,
        "forecast": planned,
        "commitments": gate_promises,
        "actual": None,
    }
    if displayed:
        latest_decision = next(
            (
                r
                for r in reversed(rows)
                if r.operation == "work.stage.decide"
                and r.review.get("stage_id") == displayed["id"]
                and r.review.get("outcome") == "approved"
            ),
            None,
        )
        timeline["actual"] = latest_decision.created_at.isoformat() if latest_decision else None
    plan_tasks = (
        [{"key": t["key"], "title": t["title"]} for t in plan.forecast["tasks"]] if plan else []
    )
    return {
        "project_id": str(project.id),
        "project_revision": project.revision,
        "revision": rows[-1].revision if rows else 0,
        "timeline": timeline,
        "plan_tasks": plan_tasks,
        "plan": {"id": str(plan.id), "revision": plan.revision} if plan else None,
        "bindings": body["bindings"],
        "template": body["template"],
        "stages": [
            {
                **stage,
                "status": "passed" if i < position else "current" if i == position else "upcoming",
                "actual": next(
                    (
                        r.created_at.isoformat()
                        for r in reversed(rows)
                        if r.operation == "work.stage.decide"
                        and r.review.get("stage_id") == stage["id"]
                        and r.review.get("outcome") == "approved"
                    ),
                    None,
                ),
            }
            for i, stage in enumerate(stages)
        ],
        "current_stage": current,
        "completed": bool(stages and position >= len(stages)),
        "gate": result,
        "next_gate": next_result,
        "baseline": body["baseline"],
        "review": review,
        "health": health(
            gate_state=result["state"], overdue=overdue, pending=valid_review, adopted=bool(stages)
        ),
        "commitments": promises,
        "history": history,
        "can_manage": project.owner_id == ctx.requester_id,
        "templates": templates(),
    }


@dataclass
class Validated:
    project: object
    rows: list
    body: dict
    review: dict
    confirmation_id: object = None


def validate(s, ctx, command, product, payload):
    human(s, ctx)
    require(command.expected_revision == product.revision, "型号范围已变化。", "VERSION_CONFLICT")
    project, _, _ = _project(s, ctx, product.id, payload.project_id, write=True)
    require(
        project.revision == payload.expected_project_revision,
        "项目已变化，请刷新。",
        "VERSION_CONFLICT",
    )
    rows = events(s, ctx, project.id)
    require(
        (rows[-1].revision if rows else 0) == payload.expected_governance_revision,
        "阶段记录已变化，请重新核对。",
        "VERSION_CONFLICT",
    )
    body = state(rows)
    material = gate(s, ctx, product.id, project, body)
    review = {
        "operation": command.operation,
        "project_id": str(project.id),
        "project_revision": project.revision,
        "governance_revision": len(rows),
        "name": project.name,
        "reason": payload.reason,
        "effect": "保留固定记录、具名办理人与回执；不代替专业批准、实际预约、个人承诺或外发。",
    }
    if isinstance(payload, AdoptPayload):
        require(
            not body["stages"],
            "本项目已经采用阶段模板；不能替换已生效的阶段历史。",
            "VERSION_CONFLICT",
        )
        review["template"] = next(t for t in templates() if t["id"] == payload.template)
    elif isinstance(payload, BaselinePayload):
        plan = s.get(PlanRevision, payload.plan.id)
        require(
            plan
            and plan.project_id == project.id
            and plan.id == project.current_plan_id
            and plan.revision == payload.plan.revision,
            "请批准当前项目的实际计划版本。",
            "VERSION_CONFLICT",
        )
        require(
            plan.forecast["earliest_finish"] and plan.forecast["latest_finish"],
            "计划仍有未知工时，请补齐后批准基线。",
            "MISSING_REQUIRED_EVIDENCE",
        )
        require(
            not body["baseline"]
            or body["baseline"]["plan"] != payload.plan.model_dump(mode="json"),
            "本版计划已有批准基线。",
            "VERSION_CONFLICT",
        )
        review["plan"] = payload.plan.model_dump(mode="json")
        review["forecast"] = plan.forecast
        review["previous_baseline"] = body["baseline"]
    elif isinstance(payload, MilestonePayload):
        stage = next((v for v in body["stages"] if v["id"] == str(payload.stage_id)), None)
        task = s.scalar(
            select(ProjectTask).where(
                ProjectTask.project_id == project.id,
                ProjectTask.plan_id == project.current_plan_id,
                ProjectTask.key == payload.task_key,
            )
        )
        require(stage and task, "请选择本项目实际阶段和当前计划任务。", "SOURCE_UNAVAILABLE")
        require(
            body["stages"].index(stage) >= body["position"],
            "已通过阶段的里程碑保持原记录。",
            "VERSION_CONFLICT",
        )
        review.update(
            stage_id=stage["id"], stage_name=stage["name"], task_key=task.key, task_title=task.title
        )
    elif isinstance(payload, ReviewPayload):
        require(
            body["position"] < len(body["stages"])
            and body["stages"][body["position"]]["id"] == str(payload.stage_id),
            "请选择当前阶段。",
            "VERSION_CONFLICT",
        )
        reference = (
            payload.release_package.model_dump(mode="json") if payload.release_package else None
        )
        if reference:
            release_evidence(s, ctx, product.id, project.id, reference)
        material = gate(s, ctx, product.id, project, body, reference=reference)
        review.update(
            stage_id=str(payload.stage_id),
            stage_name=body["stages"][body["position"]]["name"],
            release_package=reference,
            gate=material,
        )
    elif isinstance(payload, DecidePayload):
        submitted = body["review"]
        require(
            submitted
            and submitted["id"] == str(payload.review.id)
            and submitted["revision"] == payload.review.revision,
            "评审材料已改变，请重新提交。",
            "VERSION_CONFLICT",
        )
        stage = body["stages"][body["position"]]
        binding = body["bindings"].get(stage["id"], {})
        material = gate(s, ctx, product.id, project, body, reference=binding.get("release_package"))
        require(
            submitted["gate_digest"] == digest(material),
            "评审依据已变化或失效，请重新提交固定材料。",
            "SOURCE_STALE",
        )
        if payload.outcome == "approved":
            require(
                material["state"] in {"READY", "READY_WITH_CONDITIONS"},
                "当前出口仍有阻塞或未知，须补齐后再批准。",
                "MISSING_REQUIRED_EVIDENCE",
            )
        review.update(
            stage_id=stage["id"],
            stage_name=stage["name"],
            outcome=payload.outcome,
            gate=material,
            submitted_review=submitted,
        )
    reads = {str(r.artifact_id): r.expected_revision for r in command.source_read_set}
    for r in material["required_source_read_set"]:
        require(
            reads.get(r["artifact_id"]) == r["expected_revision"],
            "须固定阶段依据的完整来源版本。",
            "MISSING_REQUIRED_EVIDENCE",
        )
        source_for(s, ctx, product.id, UUID(r["artifact_id"]), r["expected_revision"])
    return Validated(project, rows, body, review)


def confirmation_subject(s, ctx, command, product, payload):
    return "product", product


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token", "approval_token"})


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def apply_validated(s, ctx, command, product, payload, value):
    require(
        value.confirmation_id is not None, "须消费本次固定材料的确认。", "CONFIRMATION_REQUIRED"
    )
    body, review = deepcopy(value.body), value.review
    identity, receipt_id = uuid4(), uuid4()
    revision = payload.expected_governance_revision + 1
    if isinstance(payload, AdoptPayload):
        body["template"] = {"id": review["template"]["id"], "name": review["template"]["name"]}
        body["stages"] = [{**stage, "id": str(uuid4())} for stage in review["template"]["stages"]]
    elif isinstance(payload, BaselinePayload):
        body["baseline"] = {
            "id": str(identity),
            "revision": revision,
            "plan": review["plan"],
            "forecast": review["forecast"],
            "approved_by": str(ctx.requester_id),
            "at": now().isoformat(),
        }
    elif isinstance(payload, MilestonePayload):
        body["bindings"].setdefault(str(payload.stage_id), {})["task_key"] = payload.task_key
        body["review"] = None
    elif isinstance(payload, ReviewPayload):
        body["bindings"].setdefault(str(payload.stage_id), {})["release_package"] = review[
            "release_package"
        ]
        body["review"] = {
            "id": str(identity),
            "revision": revision,
            "stage_id": str(payload.stage_id),
            "gate_digest": digest(review["gate"]),
            "submitted_at": now().isoformat(),
        }
    elif isinstance(payload, DecidePayload):
        if payload.outcome == "approved":
            body["position"] += 1
        body["review"] = None
    row = GovernanceEvent(
        id=identity,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=value.project.id,
        owner_id=value.project.owner_id,
        actor_id=ctx.requester_id,
        visibility=value.project.visibility,
        revision=revision,
        previous_id=value.rows[-1].id if value.rows else None,
        operation=command.operation,
        body=body,
        review=review,
        command_id=command.command_id,
        receipt_id=receipt_id,
        confirmation_id=value.confirmation_id,
    )
    row.prepared_receipt_id = receipt_id
    return row, "project_governance", row.visibility
