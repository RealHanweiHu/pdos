"""Run-bound structural reads for S2/S3 objects, without source or snapshot bodies.

These ports discover command identities and current revisions. A current pointer
is not a currentness/applicability assessment of its evidence. Free text, raw
measurements and customer originals remain behind their dedicated source ports.
"""

# The common model registry initializes before its domain children.
# ruff: noqa: I001
from functools import partial
from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import load_only

from pdos_next.database import tenant_session
from pdos_next.models import Product
from pdos_next.domain.build_execution.models import BuildLot, SampleUnit
from pdos_next.domain.builds.models import Build
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .execution import check_run_binding
from .models import AgentRun
from .project_scope import require_run_project


class PageInput(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=50, ge=1, le=100)


class BuildInput(PageInput):
    build_id: UUID | None = None


class LotInput(BuildInput):
    lot_id: UUID | None = None


class SampleInput(LotInput):
    sample_id: UUID | None = None


class IssueInput(PageInput):
    issue_id: UUID | None = None


class RunInput(BuildInput):
    # "run_id" is reserved for the kernel's execution identity, never a selector.
    test_run_id: UUID | None = None
    request_id: UUID | None = None


SCHEMAS = {
    "build.read": BuildInput,
    "build.lot.read": LotInput,
    "build.sample.read": SampleInput,
    "quality.issue.read": IssueInput,
    "test.run.read": RunInput,
}
CONTEXT_KEY = "project_metadata_context"
PROJECTION = "structural_metadata/v1"

# Deliberate column allowlists: adding an ORM field cannot expose new model data.
COMMON = ("revision", "project_id", "owner_id", "visibility", "status", "created_at")
FIELDS = {
    Build: (
        *COMMON,
        "type",
        "project_revision",
        "engineering_configuration_id",
        "manufacturing_configuration_id",
        "previous_build_id",
    ),
    BuildLot: (
        *COMMON,
        "build_id",
        "build_revision",
        "actual_configuration_id",
        "actual_configuration_revision",
        "observation_nature",
    ),
    SampleUnit: (
        *COMMON,
        "build_id",
        "build_revision",
        "lot_id",
        "allocation_id",
        "actual_configuration_id",
    ),
    QualityIssueVersion: (*COMMON, "issue_id", "snapshot_sha256"),
    VerificationRunVersion: (
        *COMMON,
        "run_id",
        "build_id",
        "build_revision",
        "request_id",
        "request_version_id",
        "request_revision",
        "plan_sha256",
        "snapshot_sha256",
    ),
}


def bind_project_metadata(session, ctx, project, product):
    """Server-only admission for readable project metadata, before model egress.

    A shared project can contain a private Issue. Classify that fact under the
    requester's ordinary RLS without reading any body or granting new ACLs.
    """
    private = project.visibility != "category" or product.visibility != "category"
    if not private:
        private = bool(
            session.scalar(
                select(
                    or_(
                        *(
                            select(model.id)
                            .where(
                                model.tenant_id == ctx.tenant_id,
                                model.product_id == product.id,
                                model.project_id == project.id,
                                model.visibility != "category",
                            )
                            .exists()
                            for model in FIELDS
                        )
                    )
                )
            )
        )
    return {
        "projection": PROJECTION,
        "project_id": str(project.id),
        "product_id": str(product.id),
        "private_objects": private,
    }


def _private_binding(run):
    binding = getattr(run, "versions", {}).get(CONTEXT_KEY)
    return bool(
        run.private_context
        and binding
        == {
            "projection": PROJECTION,
            "project_id": str(run.project_id),
            "product_id": str(run.product_id),
            "private_objects": True,
        }
    )


def _visible(model, private):
    # RLS still determines ordinary reading. Private model egress additionally
    # requires server-bound project metadata admission, not just a readable row.
    return model.visibility.in_(("category", "private", "audience") if private else ("category",))


def _query(scope, payload, name, *, private):
    model, identity, selector = {
        "build.read": (Build, Build.id, getattr(payload, "build_id", None)),
        "build.lot.read": (BuildLot, BuildLot.id, getattr(payload, "lot_id", None)),
        "build.sample.read": (SampleUnit, SampleUnit.id, getattr(payload, "sample_id", None)),
        "quality.issue.read": (
            QualityIssueVersion,
            QualityIssueVersion.issue_id,
            getattr(payload, "issue_id", None),
        ),
        "test.run.read": (
            VerificationRunVersion,
            VerificationRunVersion.run_id,
            getattr(payload, "test_run_id", None),
        ),
    }[name]
    fields = ("id", "tenant_id", "product_id", *FIELDS[model])
    query = select(model).options(load_only(*(getattr(model, f) for f in fields), raiseload=True))
    query = query.where(
        model.tenant_id == scope.tenant_id,
        model.product_id == scope.product_id,
        model.project_id == scope.project_id,
        _visible(model, private),
    )
    if model is QualityIssueVersion:
        pointer = QualityIssueCurrent
        query = query.join(
            pointer,
            (
                (pointer.tenant_id == model.tenant_id)
                & (pointer.product_id == model.product_id)
                & (pointer.project_id == model.project_id)
                & (pointer.issue_id == model.issue_id)
                & (pointer.issue_version_id == model.id)
                & (pointer.issue_revision == model.revision)
            ),
        )
    if model is VerificationRunVersion:
        pointer = VerificationRunCurrent
        query = query.join(
            pointer,
            (
                (pointer.tenant_id == model.tenant_id)
                & (pointer.product_id == model.product_id)
                & (pointer.request_id == model.request_id)
                & (pointer.run_id == model.run_id)
                & (pointer.run_version_id == model.id)
                & (pointer.run_revision == model.revision)
            ),
        )
    if model in {BuildLot, SampleUnit, VerificationRunVersion}:
        query = query.join(
            Build,
            (
                (Build.tenant_id == model.tenant_id)
                & (Build.product_id == model.product_id)
                & (Build.project_id == model.project_id)
                & (Build.id == model.build_id)
            ),
        ).where(_visible(Build, private))
        if payload.build_id is not None:
            query = query.where(model.build_id == payload.build_id)
    if model is SampleUnit and payload.lot_id is not None:
        query = query.where(model.lot_id == payload.lot_id)
    if model is VerificationRunVersion and payload.request_id is not None:
        query = query.where(model.request_id == payload.request_id)
    if selector is not None:
        query = query.where(identity == selector)
    if payload.cursor is not None:
        query = query.where(identity > payload.cursor)
    return query.order_by(identity).limit(payload.page_size + 1), selector


def _view(row):
    value = {field: getattr(row, field) for field in FIELDS[type(row)]}
    value["id"] = value.pop("issue_id", value.pop("run_id", row.id))
    if isinstance(row, (QualityIssueVersion, VerificationRunVersion)):
        value["version_id"] = row.id
    # Status describes the persisted record only, not readiness or permission to act.
    value["record_status"] = value.pop("status")
    return {
        key: str(v) if isinstance(v, UUID) else v.isoformat() if key == "created_at" else v
        for key, v in value.items()
    }


class ProjectObjectReads:
    def __init__(self, store, commands):
        self.store, self.commands = store, commands

    def call(self, scope, arguments, *, name):
        payload = SCHEMAS[name].model_validate(arguments)
        if (
            scope.category_id is None
            or scope.product_id is None
            or scope.project_id is None
            or scope.isolation != "main"
        ):
            raise DomainError("FORBIDDEN_SCOPE", "领域读取须绑定当前项目、型号和品类。", 403)
        with tenant_session(
            self.store.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
            read_snapshot=True,
        ) as session:
            run = session.get(AgentRun, scope.run_id)
            check_run_binding(run, scope, for_write=False)
            self.store.authority(session, scope)
            ctx = self.commands.context(scope)
            project = require_run_project(session, ctx, run)
            product: Product = require_access(session, ctx, scope.product_id)
            # Only these server-classified structural fields are returned. The
            # gateway rechecks the actual provider agreement before every send.
            if "internal" not in run.data_categories:
                raise DomainError("FORBIDDEN_SCOPE", "本运行未绑定内部业务资料出站类别。", 403)
            private = project.visibility != "category" or product.visibility != "category"
            if private and not run.private_context:
                raise DomainError("FORBIDDEN_SCOPE", "私有项目资料未绑定本次运行。", 403)
            query, selector = _query(
                scope,
                payload,
                name,
                private=(private and run.private_context) or _private_binding(run),
            )
            rows = list(session.scalars(query))
            if selector is not None and not rows:
                raise DomainError("FORBIDDEN_SCOPE", "对象不在本次运行的可读出站范围。", 403)
            items = [_view(row) for row in rows[: payload.page_size]]
            self.store.authority(session, scope)
            check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
            return {
                "project_id": str(project.id),
                "product_id": str(scope.product_id),
                "projection": PROJECTION,
                "basis_status": "not_assessed",
                "items": items,
                "has_more": len(rows) > payload.page_size,
                "next_cursor": items[-1]["id"] if len(rows) > payload.page_size else None,
            }

    def restore(self, scope, arguments, previous, *, name):
        result = self.call(scope, arguments, name=name)
        if digest(result) != digest(previous):
            raise DomainError("SOURCE_STALE", "对象当前版本或读取范围已变化，请重新读取。")
        return result

    def handlers(self):
        return {name: partial(self.call, name=name) for name in SCHEMAS}

    def restores(self):
        return {name: partial(self.restore, name=name) for name in SCHEMAS}
