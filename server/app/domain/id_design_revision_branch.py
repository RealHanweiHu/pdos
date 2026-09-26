"""New draft ID design lineage originating in an approved ECR and frozen revision."""

from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.id_design import DesignRevisionDraft, IdDesignService, _event, _get, _prior
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class IdChangeBranchDraft(Contract):
    request_id: UUID
    expected_approval_digest: Digest
    title: Text = Field(max_length=512)
    owner_user_id: UUID
    reason: Text


def approval_basis(ecr: Any) -> dict[str, Any]:
    return {
        key: _plain({key: ecr[key]})[key]
        for key in (
            "id",
            "status",
            "approval_decision_id",
            "approved_by_user_id",
            "approved_at",
            "impact_analysis",
        )
    }


def branch_for_variant(
    connection: Connection, context: AuthContext, project_id: UUID, variant_id: UUID
) -> Any:
    t = tables.id_design_change_branches
    return (
        connection.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.variant_id == variant_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def revision_origin(
    connection: Connection, context: AuthContext, project_id: UUID, revision: Any
) -> dict[str, Any] | None:
    branch = branch_for_variant(connection, context, project_id, revision["variant_id"])
    if not branch:
        return None
    ecr = _get(
        connection, context, project_id, tables.engineering_change_requests, branch["ecr_id"]
    )
    if ecr["status"] != "approved" or digest(approval_basis(ecr)) != branch["approval_digest"]:
        raise ProductWorkError("设计修订所依据的ECR批准已不一致，不能继续冻结")
    source = branch["snapshot"]["frozen_revision"]
    fields = ("brief", "envelope", "cmf", "layout", "interfaces", "artifact_snapshot")
    if all(_plain({key: revision[key]})[key] == source[key] for key in fields):
        raise ProductWorkError("当前仍是原冻结版本的副本，请落实获批设计变更后再申请冻结")
    return _plain(branch)


class IdDesignRevisionBranchService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def prepare(
        self,
        context: AuthContext,
        project_id: UUID,
        candidate_id: UUID,
        command: IdChangeBranchDraft,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_EDIT)
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
            _person(connection, context, project_id, command.owner_user_id)
            t = tables.id_design_change_branches
            prior = _prior(connection, context, t, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能编制变更修订")
            _get(connection, context, project_id, tables.id_design_change_candidates, candidate_id)
            links = tables.id_design_change_decisions
            decision = (
                connection.execute(
                    select(links).where(
                        links.c.tenant_id == context.tenant.id,
                        links.c.project_id == project_id,
                        links.c.candidate_id == candidate_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not decision or decision["action"] != "route_ecr":
                raise ProductWorkError("须先将新要求转入工程变更并获批")
            freeze = _get(
                connection,
                context,
                project_id,
                tables.id_design_freezes,
                UUID(decision["snapshot"]["freeze"]["id"]),
            )
            revision = _get(
                connection, context, project_id, tables.id_design_revisions, freeze["revision_id"]
            )
            if revision["owner_user_id"] != context.user.id and not is_allowed(
                context.user.role, Action.PROJECT_EDIT
            ):
                raise ProductWorkAccessError("仅冻结设计负责人或项目管理人员可编制修订")
            from app.domain.id_design_activation import active_freeze_ids

            if freeze["id"] not in active_freeze_ids(connection, context.tenant.id, project_id):
                raise ProductWorkError("此批准对应的冻结版本已被替代，需按当前版本重新评估变更")
            ecr = _get(
                connection,
                context,
                project_id,
                tables.engineering_change_requests,
                decision["ecr_id"],
            )
            approval = approval_basis(ecr)
            if ecr["status"] != "approved" or digest(approval) != command.expected_approval_digest:
                raise ProductWorkError("须依据当前已批准ECR创建修订")
            approved_links = (
                (ecr["impact_analysis"] or {})
                .get("id_design", {})
                .get("basis", {})
                .get("links", [])
            )
            covered = [
                row
                for row in approved_links
                if row["snapshot"]["freeze"]["id"] == str(freeze["id"])
            ]
            if not any(
                row["id"] == str(decision["id"])
                and row["candidate_digest"] == decision["candidate_digest"]
                for row in covered
            ):
                raise ProductWorkError("当前ECR批准未覆盖这条冻结后反馈")
            if connection.execute(
                select(t.c.id).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.source_freeze_id == freeze["id"],
                    t.c.ecr_id == ecr["id"],
                )
            ).first():
                raise ProductWorkError("此ECR已有设计修订方案，请打开现有方案继续")
            draft = DesignRevisionDraft(
                request_id=uuid5(command.request_id, "id-revision"),
                variant_id=None,
                expected_version=0,
                title=command.title,
                owner_user_id=command.owner_user_id,
                reason=command.reason,
                **{
                    key: revision[key]
                    for key in (
                        "brief",
                        "envelope",
                        "cmf",
                        "layout",
                        "interfaces",
                        "document_id",
                        "external_file_reference_id",
                    )
                },
            )
            created = IdDesignService(self.engine).revise_in_transaction(
                connection, context, project_id, draft
            )
            snapshot = {
                "source_freeze": _plain(freeze),
                "frozen_revision": _plain(revision),
                "approval": approval,
                "approved_feedback": covered,
            }
            row = (
                connection.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        source_freeze_id=freeze["id"],
                        ecr_id=ecr["id"],
                        variant_id=UUID(created["variant_id"]),
                        initial_revision_id=UUID(created["id"]),
                        approval_digest=command.expected_approval_digest,
                        snapshot=snapshot,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                row["id"],
                "approved_change_draft_created",
                _plain(row),
            )
            return _plain(row)
