from uuid import UUID

from pdos_next.database import tenant_session
from pdos_next.service import Context, require_access

from .service import events, gate, release_evidence, state, view


def register_routes(app, engine, auth_dependency):
    def session(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        )

    @app.get("/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/governance")
    def governance(product_id: UUID, project_id: UUID, ctx: Context = auth_dependency):
        with session(ctx) as s:
            product = require_access(s, ctx, product_id)
            result = view(s, ctx, product_id, project_id)
            from pdos_next.domain.release.service import list_packages

            result["product_revision"] = product.revision
            packages = list_packages(s, ctx, product_id, project_id=project_id)
            result["release_packages"] = packages["items"]
            result["release_packages_cursor"] = packages["next_cursor"]
            return result

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/governance/review-inputs"
    )
    def review_inputs(
        product_id: UUID,
        project_id: UUID,
        package_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.projects.service import _project
        from pdos_next.domain.release.models import ReleasePackage

        with session(ctx) as s:
            require_access(s, ctx, product_id)
            project, _, _ = _project(s, ctx, product_id, project_id)
            reference = None
            if package_id:
                row = s.get(ReleasePackage, package_id)
                from pdos_next.domain.work_management.rules import require

                require(
                    row and row.project_id == project_id and row.product_id == product_id,
                    "发布包不在当前范围。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                reference = {"id": str(row.id), "revision": row.revision}
                release_evidence(s, ctx, product_id, project_id, reference)
            return gate(
                s, ctx, product_id, project, state(events(s, ctx, project_id)), reference=reference
            )
