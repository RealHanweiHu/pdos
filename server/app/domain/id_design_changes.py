"""Frozen ID feedback disposition and atomic handoff into existing ECR governance."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.change_governance import ChangeGovernanceService
from app.domain.id_design import _event, _get, _prior
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class IdChangeDisposition(Contract):
    request_id: UUID
    expected_candidate_digest: Digest
    action: Literal["reject", "route_ecr"]
    existing_ecr_id: UUID | None = None
    ecr_title: Text | None = Field(default=None, max_length=512)
    reason: Text

    @model_validator(mode="after")
    def route(self) -> Self:
        if self.action == "reject" and (self.existing_ecr_id or self.ecr_title):
            raise ValueError("不采纳意见不能同时发起工程变更")
        if self.action == "route_ecr" and (self.existing_ecr_id is None) == (
            self.ecr_title is None
        ):
            raise ValueError("请选择已有待分析ECR或填写新ECR标题")
        return self


def candidate_basis(
    connection: Connection, context: AuthContext, project_id: UUID, candidate: Any
) -> dict[str, Any]:
    from app.domain.id_design_activation import current_freeze_lineage

    original_freeze = _get(
        connection, context, project_id, tables.id_design_freezes, candidate["freeze_id"]
    )
    current_id, lineage = current_freeze_lineage(
        connection, context.tenant.id, project_id, candidate["freeze_id"]
    )
    freeze = _get(connection, context, project_id, tables.id_design_freezes, current_id)
    feedback = _get(
        connection, context, project_id, tables.id_design_feedback, candidate["feedback_id"]
    )
    revision = _get(
        connection, context, project_id, tables.id_design_revisions, freeze["revision_id"]
    )
    source_revision = _get(
        connection, context, project_id, tables.id_design_revisions, feedback["revision_id"]
    )
    return {
        "candidate": _plain(candidate),
        "original_freeze": _plain(original_freeze),
        "activation_lineage": lineage,
        "freeze": _plain(freeze),
        "frozen_revision": _plain(revision),
        "feedback": _plain(feedback),
        "feedback_revision": _plain(source_revision),
    }


def decorate_changes(
    connection: Connection, context: AuthContext, project_id: UUID, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    t = tables.id_design_change_decisions
    decisions = {
        str(row["candidate_id"]): row
        for row in connection.execute(
            select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
        ).mappings()
    }
    e = tables.engineering_change_requests
    ecrs = {
        row["id"]: row
        for row in connection.execute(
            select(e).where(e.c.tenant_id == context.tenant.id, e.c.project_id == project_id)
        ).mappings()
    }
    project = _project(connection, context, project_id)
    branches = list(
        connection.execute(
            select(tables.id_design_change_branches).where(
                tables.id_design_change_branches.c.tenant_id == context.tenant.id,
                tables.id_design_change_branches.c.project_id == project_id,
            )
        ).mappings()
    )
    for change in changes:
        raw = _get(
            connection, context, project_id, tables.id_design_change_candidates, UUID(change["id"])
        )
        decision = decisions.get(change["id"])
        basis = (
            decision["snapshot"]
            if decision
            else candidate_basis(connection, context, project_id, raw)
        )
        change["original_freeze_id"] = str(raw["freeze_id"])
        change["freeze_id"] = basis["freeze"]["id"]
        change["follows_replacement"] = change["freeze_id"] != str(raw["freeze_id"])

        change["candidate_digest"] = digest(basis)
        change["frozen_variant_id"] = basis["frozen_revision"]["variant_id"]
        change["frozen_version"] = basis["frozen_revision"]["version"]
        change["feedback_version"] = basis["feedback_revision"]["version"]
        from app.domain.id_design_activation import active_freeze_ids

        active = UUID(change["freeze_id"]) in active_freeze_ids(
            connection, context.tenant.id, project_id
        )
        change["can_triage"] = (
            active
            and is_allowed(context.user.role, Action.CHANGE_EDIT)
            and project["status"] in ("approved", "active", "on_hold")
            and (
                basis["frozen_revision"]["owner_user_id"] == str(context.user.id)
                or is_allowed(context.user.role, Action.PROJECT_EDIT)
            )
        )
        decision = decisions.get(change["id"])
        change["decision"] = _plain(decision) if decision else None
        ecr = ecrs.get(decision["ecr_id"]) if decision and decision["ecr_id"] else None
        change["ecr"] = (
            {key: str(ecr[key]) for key in ("id", "code", "title", "status")} if ecr else None
        )
        from app.domain.id_design_revision_branch import approval_basis

        change["approval_digest"] = (
            digest(approval_basis(ecr)) if ecr and ecr["status"] == "approved" else None
        )
        change["can_branch"] = change["can_triage"] and is_allowed(
            context.user.role, Action.PRODUCT_ENGINEERING_EDIT
        )
        change["branch"] = next(
            (
                _plain(row)
                for row in branches
                if ecr
                and row["ecr_id"] == ecr["id"]
                and str(row["source_freeze_id"]) == change["freeze_id"]
            ),
            None,
        )
        change["status"] = (
            "routed_to_ecr"
            if decision and decision["action"] == "route_ecr"
            else "rejected"
            if decision
            else "pending_review"
        )
    return {
        "can_edit_ecr": is_allowed(context.user.role, Action.CHANGE_EDIT),
        "can_approve_ecr": is_allowed(context.user.role, Action.CHANGE_APPROVE),
        "ecr_choices": [
            {key: str(row[key]) for key in ("id", "code", "title", "status")}
            for row in ecrs.values()
            if row["status"] in ("request", "impact_analysis")
        ],
    }


class IdDesignChangeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def decide(
        self,
        context: AuthContext,
        project_id: UUID,
        candidate_id: UUID,
        command: IdChangeDisposition,
    ) -> dict[str, Any]:
        try:
            return self._decide(context, project_id, candidate_id, command)
        except IntegrityError as error:
            raise ProductWorkError("候选已有办理结果或ECR编号冲突，请刷新后继续") from error

    def _decide(
        self,
        context: AuthContext,
        project_id: UUID,
        candidate_id: UUID,
        command: IdChangeDisposition,
    ) -> dict[str, Any]:
        _role(context, Action.CHANGE_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "candidate_id": str(candidate_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_change_decisions
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能办理设计变更候选")
            candidate = _get(
                connection, context, project_id, tables.id_design_change_candidates, candidate_id
            )
            basis = candidate_basis(connection, context, project_id, candidate)
            from app.domain.id_design_activation import active_freeze_ids

            if UUID(basis["freeze"]["id"]) not in active_freeze_ids(
                connection, context.tenant.id, project_id
            ):
                raise ProductWorkError("该修订版本尚未正式启用，请先完成启用后评估新增要求")
            if basis["frozen_revision"]["owner_user_id"] != str(context.user.id) and not is_allowed(
                context.user.role, Action.PROJECT_EDIT
            ):
                raise ProductWorkAccessError("仅冻结设计负责人或项目管理人员可办理此候选")
            if digest(basis) != command.expected_candidate_digest:
                raise ProductWorkError("候选来源或冻结版本与当前办理依据不一致")
            if connection.execute(
                select(table.c.id).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.project_id == project_id,
                    table.c.candidate_id == candidate_id,
                )
            ).first():
                raise ProductWorkError("候选已办理，请查看原结果")
            ecr_id = None
            if command.action == "route_ecr":
                if command.existing_ecr_id:
                    ecr = _get(
                        connection,
                        context,
                        project_id,
                        tables.engineering_change_requests,
                        command.existing_ecr_id,
                    )
                    if ecr["status"] not in ("request", "impact_analysis"):
                        raise ProductWorkError("仅可归入尚未提交批准的ECR，已有批准不能覆盖新要求")
                else:
                    if command.ecr_title is None:
                        raise ProductWorkError("请填写变更申请标题")
                    ecr = ChangeGovernanceService(self.engine).create_ecr_in_transaction(
                        connection,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        actor_user_id=context.user.id,
                        code=f"ID-{candidate_id.hex}",
                        title=command.ecr_title,
                        reason=(
                            f"{command.reason}\n\n"
                            f"ID冻结版本 v{basis['frozen_revision']['version']}，"
                            f"反馈对应版本 v{basis['feedback_revision']['version']}。\n"
                            f"来源：{basis['feedback']['source_reference']}\n"
                            f"原始反馈：{basis['feedback']['content']}"
                        ),
                    )
                ecr_id = ecr["id"]
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        candidate_id=candidate_id,
                        action=command.action,
                        ecr_id=ecr_id,
                        snapshot=basis,
                        candidate_digest=command.expected_candidate_digest,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                row["id"],
                "change_routed_to_ecr" if ecr_id else "change_rejected",
                _plain(row),
            )
            return _plain(row)
