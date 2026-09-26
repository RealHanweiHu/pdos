"""Apply approved portfolio baselines and bookings in one auditable transaction."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Digest, Text
from app.db.schema import tables
from app.domain.baseline_change_application import (
    BaselineApplicationReady,
    BaselineApplicationService,
    BaselineApply,
)
from app.domain.portfolio_application_plan import PortfolioApplicationPreview, capture, preparation
from app.domain.portfolio_comparisons import readable
from app.domain.portfolio_selections import comparison, parts, selection
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
    _project,
    _record,
)
from app.domain.schedule_forecasts import automatic_forecast
from app.domain.task_dependency_graph import dependency_graph_has_cycle


class PortfolioApply(PortfolioApplicationPreview):
    request_id: UUID
    expected_plan_digest: Digest
    reason: Text


def existing(c: Connection, tenant: UUID, selected: UUID) -> Any:
    t = tables.portfolio_execution_applications
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.selection_id == selected))
        .mappings()
        .one_or_none()
    )


def receipt(c: Connection, saved: Any, *, project: UUID | None = None) -> dict[str, Any]:
    """Caller establishes whole-portfolio access or passes its one authorized project."""
    result: dict[str, Any] = {
        k: _plain(saved)[k]
        for k in ("id", "preparation_id", "selection_id", "actor_user_id", "created_at")
    }
    result.update(status="applied", commitments_changed=False)
    if project is None:
        result.update(reason=saved["reason"], plan_digest=saved["plan_digest"])
    for name, table in (
        ("items", tables.portfolio_execution_applied_projects),
        ("reservations", tables.portfolio_execution_applied_reservations),
    ):
        query = select(table).where(
            table.c.tenant_id == saved["tenant_id"], table.c.application_id == saved["id"]
        )
        if project is not None:
            query = query.where(table.c.project_id == project)
        result[name] = [_plain(r) for r in c.execute(query.order_by(table.c.project_id)).mappings()]
    return result


class PortfolioApplicationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def apply(self, context: AuthContext, command: PortfolioApply) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        try:
            with self.engine.begin() as c:
                package = preparation(c, context, command.preparation_id)
                selected = selection(c, context, package["selection_id"])
                readable(c, context, comparison(c, context, selected["comparison_id"])["inputs"])
                participants = parts(c, context, selected["id"])
                for part in participants:
                    _project(c, context, part["project_id"], write=True)
                selected = selection(c, context, selected["id"], lock=True)
                signature = digest(command.model_dump(mode="json"))
                root = tables.portfolio_execution_applications
                prior_request = (
                    c.execute(
                        select(root).where(
                            root.c.tenant_id == context.tenant.id,
                            root.c.actor_user_id == context.user.id,
                            root.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior_request:
                    if prior_request["request_digest"] != signature:
                        raise ProductWorkError("请求编号已用于另一项组合应用")
                    return receipt(c, prior_request)
                prior = existing(c, context.tenant.id, selected["id"])
                if prior:
                    return receipt(c, prior)
                checked = capture(
                    c,
                    context,
                    PortfolioApplicationPreview(
                        preparation_id=command.preparation_id,
                        expected_selection_digest=command.expected_selection_digest,
                    ),
                )
                plan = checked["plan"]
                if checked["payload_digest"] != command.expected_plan_digest or not plan["ready"]:
                    raise ProductWorkError("正式批准、来源或预约范围已变化，请重新核对整批应用预览")
                identity = uuid4()
                baselines = BaselineApplicationService(self.engine)
                ready: list[BaselineApplicationReady] = []
                for item in plan["items"]:
                    project = UUID(item["project_id"])
                    prepared = baselines.prepare_in_connection(
                        c,
                        context,
                        project,
                        UUID(item["change_id"]),
                        BaselineApply(
                            request_id=uuid5(identity, f"baseline:{project}"),
                            expected_digest=item["change_digest"],
                            decision_id=item["decision"]["id"],
                            reason=command.reason,
                        ),
                        preparation_id=command.preparation_id,
                    )
                    if not isinstance(prepared, BaselineApplicationReady):
                        raise ProductWorkError("项目基线已有独立应用，不能部分采用本组合")
                    ready.append(prepared)
                # This authorization exists only inside this transaction. A deferred SQL
                # constraint requires every actual project and reservation receipt at commit.
                saved = (
                    c.execute(
                        root.insert()
                        .values(
                            id=identity,
                            tenant_id=context.tenant.id,
                            preparation_id=package["id"],
                            selection_id=selected["id"],
                            plan=plan,
                            plan_digest=checked["payload_digest"],
                            reason=command.reason,
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=signature,
                        )
                        .returning(root)
                    )
                    .mappings()
                    .one()
                )
                reservations = ResourceReservationService(self.engine)
                pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
                retained: dict[str, tuple[UUID, dict[str, Any]]] = {}
                for item in plan["items"]:
                    project = UUID(item["project_id"])
                    for coverage in item["bookings"]["coverage"]:
                        for original in coverage["reservations"]:
                            row = self.reservation(c, context, project, UUID(original["id"]))
                            if row["payload_digest"] != original["payload_digest"]:
                                raise ProductWorkError("原预约覆盖已变化，请重新预览")
                            retained[f"covered:{row['id']}"] = (project, row)
                    for addition in item["bookings"]["additions"]:
                        if addition["existing_proposal_id"]:
                            row = self.reservation(
                                c, context, project, UUID(addition["existing_proposal_id"])
                            )
                            if row["payload_digest"] != addition["existing_proposal_digest"]:
                                raise ProductWorkError("原待确认预约已变化，请重新预览")
                        else:
                            row = reservations._propose_in_transaction(
                                c,
                                context,
                                project,
                                ReservationDraft.model_validate(
                                    {
                                        **addition["draft"],
                                        "request_id": str(
                                            uuid5(identity, f"propose:{addition['key']}")
                                        ),
                                    }
                                ),
                                owner_user_id=UUID(addition["owner_user_id"]),
                            )
                        pending.append((addition, row))
                confirmed: list[tuple[dict[str, Any], dict[str, Any]]] = []
                # Preserve original policy priority and equal-priority FIFO ordering.
                pending.sort(
                    key=lambda pair: (
                        int(pair[0]["priority"]["rank"]),
                        pair[1]["created_at"],
                        pair[1]["id"],
                    )
                )
                for addition, row in pending:
                    result = reservations._act_in_transaction(
                        c,
                        context,
                        UUID(addition["project_id"]),
                        UUID(row["id"]),
                        ReservationAction(
                            request_id=uuid5(identity, f"reserve:{addition['key']}"),
                            expected_digest=row["payload_digest"],
                            action="reserve",
                            reason=command.reason,
                        ),
                    )
                    confirmed.append((addition, result))
                for prepared, item in zip(ready, plan["items"], strict=True):
                    applied = baselines.write_prepared(c, context, prepared, forecast=False)
                    c.execute(
                        tables.portfolio_execution_applied_projects.insert().values(
                            tenant_id=context.tenant.id,
                            application_id=identity,
                            project_id=prepared.project_id,
                            preparation_id=package["id"],
                            baseline_application_id=UUID(applied["id"]),
                            receipt={**applied["receipt"], "project_name": item["project_name"]},
                        )
                    )
                for key, (project, row) in retained.items():
                    self.save_booking(c, context, identity, project, key, row, "preserved")
                for addition, row in confirmed:
                    self.save_booking(
                        c,
                        context,
                        identity,
                        UUID(addition["project_id"]),
                        addition["key"],
                        row,
                        "confirmed_existing" if addition["existing_proposal_id"] else "created",
                    )
                if dependency_graph_has_cycle(
                    c, tenant_id=context.tenant.id, project_id=ready[0].project_id
                ):
                    raise ProductWorkError("整批实际基线与现有依赖构成循环，本次应用已回滚")
                now = datetime.now(UTC)
                for prepared in ready:
                    automatic_forecast(
                        c,
                        context.tenant.id,
                        prepared.project_id,
                        context.user.id,
                        "组合计划整批应用",
                        now,
                    )
                return receipt(c, saved)
        except IntegrityError as error:
            raise ProductWorkError(
                "整批应用未生效：来源、批准或资源占用发生冲突，请重新核对预览"
            ) from error

    @staticmethod
    def reservation(
        c: Connection, context: AuthContext, project: UUID, identity: UUID
    ) -> dict[str, Any]:
        t = tables.resource_reservations
        row = (
            c.execute(
                select(t)
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.id == identity,
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        return _record(row)

    @staticmethod
    def save_booking(
        c: Connection,
        context: AuthContext,
        application: UUID,
        project: UUID,
        key: str,
        row: dict[str, Any],
        disposition: str,
    ) -> None:
        c.execute(
            tables.portfolio_execution_applied_reservations.insert().values(
                tenant_id=context.tenant.id,
                application_id=application,
                key=key,
                project_id=project,
                reservation_id=UUID(row["id"]),
                reservation_receipt_id=UUID(row["contract"]["reservation_receipt_id"]),
                disposition=disposition,
                snapshot={k: v for k, v in row.items() if k != "payload_digest"},
            )
        )
