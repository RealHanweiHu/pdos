"""Atomic human replacement of one reserved resource allocation; failure preserves the old hold."""

from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Quantity, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
    _project,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ReservationReplacement(Contract):
    request_id: UUID
    expected_digest: Digest
    capacity_version_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime
    parallel_units: Quantity = Field(gt=0, le=1000)
    occupancy_policy: Literal["working_only", "through_waiting"]
    reason: Text


class ReservationReplacementService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def replace(
        self,
        context: AuthContext,
        project_id: UUID,
        reservation_id: UUID,
        command: ReservationReplacement,
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        try:
            return self._replace(context, project_id, reservation_id, command)
        except IntegrityError as error:
            raise ProductWorkError(
                "预约调整未生效，旧预约仍保留；请核对新容量版本、时段和并发占用"
            ) from error

    def _replace(
        self,
        context: AuthContext,
        project_id: UUID,
        reservation_id: UUID,
        command: ReservationReplacement,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            table = tables.resource_reservation_replacements
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "reservation_id": str(reservation_id),
                    **command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项预约调整")
                return _plain(prior)
            connection.execute(
                select(func.cehub_project.lock_resource_inventory(context.tenant.id))
            )
            reservations = tables.resource_reservations
            old = (
                connection.execute(
                    select(reservations).where(
                        reservations.c.tenant_id == context.tenant.id,
                        reservations.c.project_id == project_id,
                        reservations.c.id == reservation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is None:
                raise ProductWorkAccessError("原预约不存在或不属于当前项目")
            if old["state"] != "reserved" or digest(_plain(old)) != command.expected_digest:
                raise ProductWorkError("原预约已变化，请刷新后调整")
            capacity = (
                connection.execute(
                    select(tables.resource_capacity_versions).where(
                        tables.resource_capacity_versions.c.tenant_id == context.tenant.id,
                        tables.resource_capacity_versions.c.id == command.capacity_version_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if capacity is None:
                raise ProductWorkError("新容量版本不存在")
            # Match the common inventory -> resource ordering before either old or new mutation.
            list(
                connection.execute(
                    select(tables.planning_resources.c.id)
                    .where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id.in_(
                            {old["resource_id"], capacity["resource_id"]}
                        ),
                    )
                    .order_by(tables.planning_resources.c.id)
                    .with_for_update()
                ).scalars()
            )
            proposal = ReservationDraft(
                request_id=uuid5(command.request_id, "replacement-proposal"),
                node_id=old["node_id"],
                capacity_version_id=command.capacity_version_id,
                window_start=command.window_start,
                window_end=command.window_end,
                parallel_units=command.parallel_units,
                occupancy_policy=command.occupancy_policy,
                basis=command.reason,
            )
            service = ResourceReservationService(self.engine)
            released = service._act_in_transaction(
                connection,
                context,
                project_id,
                reservation_id,
                ReservationAction(
                    request_id=uuid5(command.request_id, "release-previous"),
                    expected_digest=command.expected_digest,
                    action="release",
                    reason=command.reason,
                ),
            )
            proposed = service._propose_in_transaction(
                connection, context, project_id, proposal, owner_user_id=old["owner_user_id"]
            )
            reserved = service._act_in_transaction(
                connection,
                context,
                project_id,
                UUID(proposed["id"]),
                ReservationAction(
                    request_id=uuid5(command.request_id, "confirm-replacement"),
                    expected_digest=proposed["payload_digest"],
                    action="reserve",
                    reason=command.reason,
                ),
            )
            replacement_id = uuid4()
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=replacement_id,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        previous_reservation_id=reservation_id,
                        replacement_reservation_id=UUID(reserved["id"]),
                        reason=command.reason,
                        snapshot={"previous": released, "replacement": reserved},
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                connection,
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"reservation-replaced:{replacement_id}",
                    event_type="RESOURCE_RESERVATION_REPLACED",
                    source="planning_service",
                    entity_id=replacement_id,
                    payload={
                        "previous_reservation_id": str(reservation_id),
                        "replacement_reservation_id": reserved["id"],
                    },
                ),
                AuditDraft(
                    action="resource_reservation.replace",
                    after_snapshot=_plain(row),
                    context={"reason": command.reason},
                ),
            )
            return _plain(row)
