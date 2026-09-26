"""Human confirmation of a fixed ID design package and independent freeze receipt."""

from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.id_design import _event, _get, _latest, _prior
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class IdFreezeResponsibilityRenewal(Contract):
    previous_request_id: UUID
    expected_digest: Digest


class IdFreezeRequest(Contract):
    request_id: UUID
    revision_id: UUID
    expected_revision_digest: Digest
    product_user_id: UUID
    me_user_id: UUID
    hw_user_id: UUID
    authority_basis: Text
    confirmation_document_id: UUID
    reason: Text
    responsibility_renewal: IdFreezeResponsibilityRenewal | None = None


class IdFreezeDecision(Contract):
    request_id: UUID
    expected_digest: Digest
    slot: Literal["product", "me", "hw"]
    action: Literal["approve", "reject"]
    reason: Text


class IdFreezeApply(Contract):
    request_id: UUID
    expected_digest: Digest
    reason: Text


def frozen_variant(
    connection: Connection, context: AuthContext, project_id: UUID, variant_id: UUID
) -> Any:
    t = tables.id_design_freezes
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


def feedback_basis(
    connection: Connection, context: AuthContext, project_id: UUID, variant_id: UUID
) -> dict[str, Any]:
    f, r, d = (
        tables.id_design_feedback,
        tables.id_design_revisions,
        tables.id_design_feedback_decisions,
    )
    feedback = list(
        connection.execute(
            select(f)
            .join(
                r,
                (r.c.id == f.c.revision_id)
                & (r.c.tenant_id == f.c.tenant_id)
                & (r.c.project_id == f.c.project_id),
            )
            .where(
                f.c.tenant_id == context.tenant.id,
                f.c.project_id == project_id,
                r.c.variant_id == variant_id,
            )
            .order_by(f.c.created_at, f.c.id)
        ).mappings()
    )
    decisions = list(
        connection.execute(
            select(d)
            .where(
                d.c.tenant_id == context.tenant.id,
                d.c.project_id == project_id,
                d.c.feedback_id.in_([row["id"] for row in feedback]),
            )
            .order_by(d.c.feedback_id, d.c.version)
        ).mappings()
    )
    return {
        "feedback": [_plain(row) for row in feedback],
        "decisions": [_plain(row) for row in decisions],
    }


def replacement_request(
    connection: Connection, context: AuthContext, project_id: UUID, id: UUID
) -> Any:
    t = tables.id_design_freeze_requests
    return connection.execute(
        select(t.c.id).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project_id,
            t.c.previous_request_id == id,
        )
    ).scalar_one_or_none()


def _current(connection: Connection, context: AuthContext, project_id: UUID, request: Any) -> Any:
    if replacement_request(connection, context, project_id, request["id"]):
        raise ProductWorkError("此申请已由新的具名确认申请替代，请打开后续申请")
    revision = _get(
        connection, context, project_id, tables.id_design_revisions, request["revision_id"]
    )
    if _latest(connection, context, project_id, revision["variant_id"])["id"] != revision["id"]:
        raise ProductWorkError("方案已修订，请按新版本重新申请冻结")
    if frozen_variant(connection, context, project_id, revision["variant_id"]):
        raise ProductWorkError("该方案已冻结，新增要求须进入变更候选")
    if (
        digest(feedback_basis(connection, context, project_id, revision["variant_id"]))
        != request["snapshot"]["feedback_digest"]
    ):
        raise ProductWorkError("反馈或处理意见已变化，请重新准备冻结申请")
    for slot in ("product", "me", "hw"):
        _person(connection, context, project_id, request[f"{slot}_user_id"])
    from app.domain.id_design_revision_branch import revision_origin

    if revision_origin(connection, context, project_id, revision) != request["snapshot"].get(
        "change_origin"
    ):
        raise ProductWorkError("修订方案的批准来源已变化，请重新申请冻结")
    return revision


class IdDesignFreezeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_VIEW)
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            result = {}
            for key, table in [
                ("requests", tables.id_design_freeze_requests),
                ("decisions", tables.id_design_freeze_decisions),
                ("freezes", tables.id_design_freezes),
                ("changes", tables.id_design_change_candidates),
            ]:
                result[key] = [
                    _plain(row)
                    for row in connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
                        )
                        .order_by(table.c.created_at.desc(), table.c.id)
                    ).mappings()
                ]
            replacements = {
                row["previous_request_id"]: row["id"]
                for row in result["requests"]
                if row.get("previous_request_id")
            }
            for request in result["requests"]:
                request["replacement_request_id"] = replacements.get(request["id"])

                raw = {
                    **request,
                    **{
                        key: UUID(request[key])
                        for key in (
                            "id",
                            "revision_id",
                            "product_user_id",
                            "me_user_id",
                            "hw_user_id",
                        )
                    },
                }
                try:
                    _current(connection, context, project_id, raw)
                    if project["status"] not in ("approved", "active", "on_hold"):
                        raise ProductWorkError("当前项目状态不能确认冻结")
                    request["current"] = True
                    request["blocked_reason"] = None
                except (ProductWorkError, ProductWorkAccessError) as error:
                    request["current"] = False
                    request["blocked_reason"] = str(error)
            feedback_ids = [UUID(row["feedback_id"]) for row in result["changes"]]
            f = tables.id_design_feedback
            feedback = {
                str(row["id"]): row
                for row in connection.execute(
                    select(f).where(
                        f.c.tenant_id == context.tenant.id,
                        f.c.project_id == project_id,
                        f.c.id.in_(feedback_ids),
                    )
                ).mappings()
            }
            for row in result["changes"]:
                original = feedback[row["feedback_id"]]
                row["feedback_content"] = original["content"]
                row["source_reference"] = original["source_reference"]
            from app.domain.id_design_changes import decorate_changes

            result.update(decorate_changes(connection, context, project_id, result["changes"]))
            from app.domain.id_design_activation import decorate_activations

            decorate_activations(connection, context, project_id, result["freezes"])
            return result

    def prepare(
        self, context: AuthContext, project_id: UUID, command: IdFreezeRequest
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        signing = command.model_dump(mode="json")
        if "responsibility_renewal" not in command.model_fields_set:
            signing.pop("responsibility_renewal")
        fingerprint = digest({"project_id": str(project_id), **signing})
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_freeze_requests
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能申请设计冻结")
            revision = _get(
                connection, context, project_id, tables.id_design_revisions, command.revision_id
            )
            if (
                revision["payload_digest"] != command.expected_revision_digest
                or _latest(connection, context, project_id, revision["variant_id"])["id"]
                != revision["id"]
            ):
                raise ProductWorkError("冻结必须依据当前完整方案版本")
            if frozen_variant(connection, context, project_id, revision["variant_id"]):
                raise ProductWorkError("该方案已经冻结")
            if (
                not all(revision[name] for name in ("envelope", "cmf", "layout", "interfaces"))
                or not revision["artifact_snapshot"]
            ):
                raise ProductWorkError(
                    "冻结须具备主图档、关键尺寸/包络、CMF、布局版本和结构/硬件接口说明"
                )
            for slot in ("product", "me", "hw"):
                _person(connection, context, project_id, getattr(command, f"{slot}_user_id"))
            evidence = _get(
                connection, context, project_id, tables.documents, command.confirmation_document_id
            )
            basis = feedback_basis(connection, context, project_id, revision["variant_id"])
            from app.domain.id_design_revision_branch import revision_origin

            origin = revision_origin(connection, context, project_id, revision)
            snapshot = {
                "change_origin": origin,
                "revision": _plain(revision),
                "feedback_basis": basis,
                "feedback_digest": digest(basis),
                "confirmation_evidence": {
                    key: str(evidence[key]) for key in ("id", "filename", "sha256")
                },
                "authority": {
                    slot: str(getattr(command, f"{slot}_user_id"))
                    for slot in ("product", "me", "hw")
                },
                "authority_basis": command.authority_basis,
            }
            previous_id = None
            if command.responsibility_renewal:
                renewal = command.responsibility_renewal
                previous = _get(connection, context, project_id, table, renewal.previous_request_id)
                if previous["payload_digest"] != renewal.expected_digest or replacement_request(
                    connection, context, project_id, previous["id"]
                ):
                    raise ProductWorkError("原冻结申请已变化或已有后续申请，请刷新")
                if previous["revision_id"] != revision["id"] or any(
                    digest(previous["snapshot"].get(key)) != digest(snapshot.get(key))
                    for key in (
                        "revision",
                        "feedback_basis",
                        "feedback_digest",
                        "confirmation_evidence",
                        "change_origin",
                    )
                ):
                    raise ProductWorkError(
                        "原设计、证据或反馈已有变化，请完整核对后重新准备冻结申请"
                    )
                if all(
                    previous[f"{slot}_user_id"] == getattr(command, f"{slot}_user_id")
                    for slot in ("product", "me", "hw")
                ):
                    raise ProductWorkError("须至少调整一位实际确认人")
                d = tables.id_design_freeze_decisions
                if connection.execute(
                    select(d.c.id).where(
                        d.c.tenant_id == context.tenant.id,
                        d.c.project_id == project_id,
                        d.c.freeze_request_id == previous["id"],
                        d.c.action == "reject",
                    )
                ).first():
                    raise ProductWorkError("原申请已退回，请按反馈完整重新准备")
                u = tables.users
                names = {
                    str(row.id): row.display_name
                    for row in connection.execute(
                        select(u.c.id, u.c.display_name).where(
                            u.c.tenant_id == context.tenant.id,
                            u.c.id.in_(
                                [
                                    context.user.id,
                                    *(
                                        previous[f"{slot}_user_id"]
                                        for slot in ("product", "me", "hw")
                                    ),
                                    *(
                                        getattr(command, f"{slot}_user_id")
                                        for slot in ("product", "me", "hw")
                                    ),
                                ]
                            ),
                        )
                    )
                }
                previous_id = previous["id"]
                snapshot["responsibility_renewal"] = {
                    "previous_request_id": str(previous_id),
                    "previous_digest": previous["payload_digest"],
                    "previous_authority": previous["snapshot"]["authority"],
                    "previous_authority_basis": previous["authority_basis"],
                    "people": names,
                    "actor_user_id": str(context.user.id),
                    "reason": command.reason,
                }
            values = {
                **command.model_dump(
                    exclude={"expected_revision_digest", "responsibility_renewal"}
                ),
                "id": uuid4(),
                "tenant_id": context.tenant.id,
                "project_id": project_id,
                "previous_request_id": previous_id,
                "snapshot": snapshot,
                "payload_digest": digest(snapshot),
                "created_by_user_id": context.user.id,
                "request_digest": fingerprint,
            }
            row = (
                connection.execute(table.insert().values(**values).returning(table))
                .mappings()
                .one()
            )
            _event(connection, context, project_id, row["id"], "freeze_requested", _plain(row))
            return _plain(row)

    def decide(
        self,
        context: AuthContext,
        project_id: UUID,
        freeze_request_id: UUID,
        command: IdFreezeDecision,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "freeze_request_id": str(freeze_request_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_freeze_decisions
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能确认冻结")
            request = _get(
                connection, context, project_id, tables.id_design_freeze_requests, freeze_request_id
            )
            if replacement_request(connection, context, project_id, request["id"]):
                raise ProductWorkError("原申请已有后续具名确认申请，历史意见保留")
            if request[f"{command.slot}_user_id"] != context.user.id:
                raise ProductWorkAccessError("仅申请中该专业的具名确认人可办理")
            if request["payload_digest"] != command.expected_digest:
                raise ProductWorkError("批准依据与冻结申请不一致")
            if command.action == "approve":
                _current(connection, context, project_id, request)
            existing = list(
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.freeze_request_id == freeze_request_id,
                    )
                ).mappings()
            )
            if any(row["slot"] == command.slot or row["action"] == "reject" for row in existing):
                raise ProductWorkError("该项已有决定或申请已被退回，请重新准备申请")
            values = {
                **command.model_dump(exclude={"expected_digest"}),
                "id": uuid4(),
                "tenant_id": context.tenant.id,
                "project_id": project_id,
                "freeze_request_id": freeze_request_id,
                "approved_digest": command.expected_digest,
                "created_by_user_id": context.user.id,
                "request_digest": fingerprint,
            }
            row = (
                connection.execute(table.insert().values(**values).returning(table))
                .mappings()
                .one()
            )
            _event(connection, context, project_id, row["id"], "freeze_decided", _plain(row))
            return _plain(row)

    def apply(
        self,
        context: AuthContext,
        project_id: UUID,
        freeze_request_id: UUID,
        command: IdFreezeApply,
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "freeze_request_id": str(freeze_request_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_freezes
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能冻结设计")
            request = _get(
                connection, context, project_id, tables.id_design_freeze_requests, freeze_request_id
            )
            if request["payload_digest"] != command.expected_digest:
                raise ProductWorkError("冻结依据与批准版本不一致")
            revision = _current(connection, context, project_id, request)
            d = tables.id_design_freeze_decisions
            decisions = list(
                connection.execute(
                    select(d).where(
                        d.c.tenant_id == context.tenant.id,
                        d.c.project_id == project_id,
                        d.c.freeze_request_id == freeze_request_id,
                    )
                ).mappings()
            )
            if {
                row["slot"]
                for row in decisions
                if row["action"] == "approve"
                and row["approved_digest"] == request["payload_digest"]
            } != {"product", "me", "hw"}:
                raise ProductWorkError("须先取得产品/客户确认及结构、硬件共同接口可行性确认")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        freeze_request_id=freeze_request_id,
                        variant_id=revision["variant_id"],
                        revision_id=revision["id"],
                        approved_digest=command.expected_digest,
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
            _event(connection, context, project_id, row["id"], "frozen", _plain(row))
            from datetime import UTC, datetime

            from app.domain.formal_schedule import current_plan
            from app.domain.schedule_forecasts import automatic_forecast

            if current_plan(connection, context.tenant.id, project_id) is not None:
                automatic_forecast(
                    connection,
                    context.tenant.id,
                    project_id,
                    context.user.id,
                    "ID设计冻结后更新正式检查点依据",
                    datetime.now(UTC),
                )
            return _plain(row)
