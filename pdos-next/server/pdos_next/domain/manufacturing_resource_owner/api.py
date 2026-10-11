"""Host-authenticated read-only route; the concrete owner owns every fact guard."""

from uuid import UUID

from fastapi import FastAPI, Request

from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_resource_owner import owner
from pdos_next.domain.manufacturing_resource_owner.schemas import (
    ResourceRequest,
    ResourceView,
    VersionRef,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context

from .api_schemas import ResourceInspectInput


def register_routes(app: FastAPI, engine, auth_dependency):
    """Use the host's existing human authentication dependency and tenant UOW."""

    @app.post(
        "/v1/categories/{category_id}/products/{product_id}/builds/{build_id}/resources/inspect",
        response_model=ResourceView,
    )
    def inspect_build_resource(
        request: Request,
        product_id: UUID,
        build_id: UUID,
        data: ResourceInspectInput,
        ctx: Context = auth_dependency,
    ):
        if request.query_params:
            raise DomainError("INVALID_PAYLOAD", "请在专用正文中固定唯一试制资源范围。", 422)
        selection = ResourceRequest(
            scope=Scope(
                tenant_id=ctx.tenant_id,
                product_id=product_id,
                project_id=data.project_id,
            ),
            build=VersionRef(id=build_id, revision=data.expected_build_revision),
            process=data.process,
            execution=data.execution,
            operation_key=data.operation_key,
            resource=data.resource,
            fact=data.fact,
        )
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            result = owner.inspect_resource(session, ctx, product_id, request=selection)
            # Never serialize ResourceRead: its token, Source basis and UOW
            # stamps stay inside the server. Do not recalculate/drop read sets.
            return ResourceView.model_validate(result.view).model_dump(mode="json")
