from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pdos_next.contracts import Command, OriginalScanInput, ProductInput, ResumeInput, UploadInput
from pdos_next.database import configured_engines, tenant_session
from pdos_next.domain.build_start.schemas import BuildAssessmentPayload
from pdos_next.domain.cost_execution.schemas import CostCaptureInput
from pdos_next.domain.products.definitions import list_definitions
from pdos_next.domain.supply_execution.schemas import SupplyCaptureInput
from pdos_next.domain.verification_results.schemas import CaptureInput
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    BudgetReservation,
    Claim,
    Grant,
    LoginSession,
    Principal,
    Product,
    Receipt,
    RequestKey,
    Run,
    UploadAttempt,
    UploadedOriginal,
    WorkRequest,
    now,
)
from pdos_next.object_storage import StorageFailure
from pdos_next.originals import object_reference, original_view, require_original, upload
from pdos_next.runtime import resume
from pdos_next.service import (
    Context,
    append_receipt,
    digest,
    execute,
    preview_command,
    preview_confirmation,
    receipt_view,
    require_access,
)


def create_app(
    engine=None,
    auth_engine=None,
    *,
    provider=None,
    synthetic_mode=False,
    object_store=None,
    workflow_enabled=None,
    security_runtime=None,
    security_runtime_factory=None,
    lifecycle_policy=None,
    lifecycle_enabled=False,
    professional_synthetic_scope=None,
    professional_synthetic_profiles=None,
    operational_synthetic_profile=None,
    operational_synthetic_profiles=None,
    test_resource_synthetic_profile=None,
    test_resource_synthetic_profiles=None,
    quality_synthetic_profile=None,
    quality_synthetic_profiles=None,
    quality_followup_synthetic_profile=None,
    quality_followup_synthetic_profiles=None,
    capa_facts_synthetic_profile=None,
    capa_facts_synthetic_profiles=None,
    capa_fact_material_owner=None,
):
    # Host startup choices are explicit; reject ambiguous choices before touching
    # any engine, issuer registry or other integration configuration.
    for name, single, profiles in (
        ("professional", professional_synthetic_scope, professional_synthetic_profiles),
        ("operational", operational_synthetic_profile, operational_synthetic_profiles),
        ("test_resource", test_resource_synthetic_profile, test_resource_synthetic_profiles),
        ("quality", quality_synthetic_profile, quality_synthetic_profiles),
        (
            "quality_followup",
            quality_followup_synthetic_profile,
            quality_followup_synthetic_profiles,
        ),
        ("capa_facts", capa_facts_synthetic_profile, capa_facts_synthetic_profiles),
    ):
        if single is not None and profiles is not None:
            raise ValueError(f"Use one explicit {name} host configuration")
        if profiles is not None and (type(profiles) is not list or not 1 <= len(profiles) <= 20):
            raise ValueError(f"Use a finite nonempty {name} host profile list")
    if capa_fact_material_owner is not None and (
        capa_facts_synthetic_profile is not None or capa_facts_synthetic_profiles is not None
    ):
        raise ValueError("Use one explicit fact host configuration")
    if engine is None:
        engine, auth_engine = configured_engines()
    if object_store is not None:
        from pdos_next.domain.verification_results.service import configure_store

        configure_store(engine, object_store)
        from pdos_next.domain.change_execution.service import (
            configure_store as configure_change_store,
        )
        from pdos_next.domain.quality_execution.service import configure_result_bridge
        from pdos_next.quality_result_bridge import (
            fixed_failure_result,
            recheck_fixed_failure_result,
        )

        configure_change_store(engine, object_store)
        configure_result_bridge(engine, fixed_failure_result, refresh=recheck_fixed_failure_result)
        from pdos_next.lifecycle_worker import configure_lifecycle

        configure_lifecycle(
            engine, object_store, policy=lifecycle_policy, allow_local_profile=lifecycle_enabled
        )
    if security_runtime is not None:
        from pdos_next.original_security import configure

        configure(engine, security_runtime)
    if workflow_enabled is None:
        workflow_enabled = not synthetic_mode
    if provider is not None and not synthetic_mode:
        raise RuntimeError(
            "Only synthetic providers may be injected into the API; "
            "production models must use the Temporal worker's trusted host ports"
        )
    if synthetic_mode:
        from pdos_next.safety import verify_test_target

        verify_test_target(engine)
    if professional_synthetic_scope is not None:
        from pdos_next.domain.professional_authority.service import configure_local_synthetic
        from pdos_next.safety import verify_test_target

        verify_test_target(engine)
        if set(professional_synthetic_scope) != {"tenant_id", "product_id"}:
            raise ValueError("Local professional profile needs an exact server-owned scope")
        configure_local_synthetic(
            engine,
            tenant_id=UUID(str(professional_synthetic_scope["tenant_id"])),
            product_id=UUID(str(professional_synthetic_scope["product_id"])),
            enabled=True,
        )
    if professional_synthetic_profiles is not None:
        from pdos_next.domain.professional_authority.service import (
            configure_local_synthetic_profiles,
        )
        from pdos_next.safety import verify_test_target

        verify_test_target(engine)
        configure_local_synthetic_profiles(engine, professional_synthetic_profiles, enabled=True)

    if operational_synthetic_profile is not None:
        from pdos_next.operational_bootstrap import configure_local_profile

        configure_local_profile(engine, operational_synthetic_profile)
    elif operational_synthetic_profiles is not None:
        from pdos_next.operational_bootstrap import configure_local_profiles

        configure_local_profiles(engine, operational_synthetic_profiles)

    if test_resource_synthetic_profile is not None:
        from pdos_next.test_resource_bootstrap import configure_local_profile

        configure_local_profile(engine, test_resource_synthetic_profile)
    elif test_resource_synthetic_profiles is not None:
        from pdos_next.test_resource_bootstrap import configure_local_profiles

        configure_local_profiles(engine, test_resource_synthetic_profiles)

    if quality_synthetic_profile is not None:
        from pdos_next.quality_bootstrap import configure_local_profile

        configure_local_profile(engine, quality_synthetic_profile)
    elif quality_synthetic_profiles is not None:
        from pdos_next.quality_bootstrap import configure_local_profiles

        configure_local_profiles(engine, quality_synthetic_profiles)

    from pdos_next.domain.manufacturing_baseline.service import configure as configure_manufacturing

    configure_manufacturing(engine)
    from pdos_next.quality_followup_integration import configure_integration

    configure_integration(
        engine,
        synthetic_completion_profile=quality_followup_synthetic_profile,
        synthetic_completion_profiles=quality_followup_synthetic_profiles,
    )

    from pdos_next.domain.capa_effectiveness.service import configure as configure_capa_candidate

    configure_capa_candidate(engine)

    from pdos_next.capa_fact_owner import ActualFactOwner
    from pdos_next.domain.capa_effectiveness.fact_service import configure as configure_capa_facts

    if capa_facts_synthetic_profile is not None:
        from pdos_next.capa_rule_publisher import configure_local_profile as configure_rule_profile

        capa_fact_material_owner = ActualFactOwner(
            publisher=configure_rule_profile(engine, capa_facts_synthetic_profile)
        )
    elif capa_facts_synthetic_profiles is not None:
        from pdos_next.capa_rule_publisher import (
            configure_local_profiles as configure_rule_profiles,
        )

        capa_fact_material_owner = ActualFactOwner(
            publisher=configure_rule_profiles(engine, capa_facts_synthetic_profiles)
        )
    fact_owner = capa_fact_material_owner or ActualFactOwner()
    from pdos_next.paired_followup_adapter import configure as configure_paired_followup
    from pdos_next.paired_output_bridge import LivePairedOwner

    paired_owner = LivePairedOwner()
    if type(fact_owner) is ActualFactOwner and fact_owner.review_owner is None:
        from pdos_next.capa_applicability_owner import ActualApplicabilityOwner
        from pdos_next.domain.capa_effectiveness.candidate_commands import semantic_owner
        from pdos_next.domain.capa_effectiveness.named_review_owner import ActualNamedReviewOwner

        fact_owner.review_owner = ActualNamedReviewOwner(
            fact_owner,
            candidate_semantic_owner=semantic_owner(),
            paired_owner=paired_owner,
            applicability_owner=ActualApplicabilityOwner(fact_owner, paired_owner=paired_owner),
        )
    configure_capa_facts(engine, fact_owner)
    configure_paired_followup(engine, paired_owner)

    @asynccontextmanager
    async def lifespan(_app):
        if security_runtime_factory is not None:
            from pdos_next.original_security import configure

            configure(engine, await security_runtime_factory())
        try:
            yield
        finally:
            installed = getattr(engine, "_pdos_security_runtime", None)
            if security_runtime_factory is not None and installed:
                close = getattr(installed.scanner, "close", None)
                if close:
                    await close()

    app = FastAPI(title="PDOS Next · trusted source work", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError):
        content = {"code": exc.code, "message": exc.message}
        if exc.recovery is not None:
            content["recovery"] = exc.recovery
        return JSONResponse(status_code=exc.status, content=content)

    from pdos_next.original_lifecycle.types import LifecycleFailure

    @app.exception_handler(LifecycleFailure)
    async def lifecycle_error(_request: Request, exc: LifecycleFailure):
        return JSONResponse(status_code=409, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_payload(_request: Request, _exc):
        return JSONResponse(
            status_code=422,
            content={"code": "INVALID_PAYLOAD", "message": "内容不符合此操作的专用格式。"},
        )

    @app.exception_handler(IntegrityError)
    async def conflict(_request: Request, _exc):
        return JSONResponse(
            status_code=409,
            content={
                "code": "DUPLICATE_INTENT_CONFLICT",
                "message": "请求意图或关联对象发生冲突，未提交此操作。",
            },
        )

    def authenticated(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise DomainError("UNAUTHENTICATED", "需要有效会话。", 401)
        token = authorization[7:]
        with Session(auth_engine) as s:
            login = s.get(LoginSession, digest(token))
            if not login or login.revoked or login.expires_at <= now():
                raise DomainError("UNAUTHENTICATED", "会话已失效，请重新登录。", 401)
            ctx = Context(login.tenant_id, login.principal_id, login.principal_id)
        with tenant_session(engine, ctx.tenant_id) as s:
            actor = s.get(Principal, ctx.actor_id)
            if not actor or not actor.active or actor.kind != "human":
                raise DomainError("UNAUTHENTICATED", "当前会话身份不可用。", 401)
        return ctx

    auth_dependency = Depends(authenticated)
    from pdos_next.domain.change_execution.api import register_routes as register_change_routes
    from pdos_next.domain.quality_execution.api import register_routes as register_quality_routes

    register_quality_routes(app, engine, auth_dependency)
    from pdos_next.change_public_integration import configure as configure_change_owners

    configure_change_owners(engine)
    register_change_routes(app, engine, auth_dependency)
    from pdos_next.quality_followup_api import register_routes as register_followup_routes

    register_followup_routes(app, engine, auth_dependency)

    from pdos_next.capa_candidate_api import register_routes as register_candidate_routes

    register_candidate_routes(app, engine, auth_dependency)

    from pdos_next.capa_fact_api import register_routes as register_fact_routes

    register_fact_routes(app, engine, auth_dependency)

    from pdos_next.domain.manufacturing_resource_owner.api import (
        register_routes as register_resource_read_routes,
    )

    register_resource_read_routes(app, engine, auth_dependency)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model_available": False,
            "slice": "wave1-source-definition",
            "durable_queue_enabled": workflow_enabled,
        }

    @app.get("/v1/session")
    def session_info(ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            p = s.get(Principal, ctx.actor_id)
            return {"name": p.name, "principal_id": str(p.id), "model_available": False}

    @app.get("/v1/products")
    def products(ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            rows = s.scalars(
                select(Product)
                .join(Grant, Grant.product_id == Product.id)
                .where(
                    Grant.principal_id == ctx.actor_id,
                    Grant.expires_at > now(),
                )
                .order_by(Product.created_at)
            )
            return [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "purpose": p.purpose,
                    "revision": p.revision,
                    "status": p.status,
                }
                for p in rows
            ]

    @app.post("/v1/products", status_code=201)
    def create_product(data: ProductInput, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            s.scalar(select(Principal).where(Principal.id == ctx.actor_id).with_for_update())
            d = digest(data.model_dump())
            key = s.scalar(
                select(RequestKey).where(
                    RequestKey.actor_id == ctx.actor_id,
                    RequestKey.key == data.idempotency_key,
                )
            )
            if key:
                if key.digest != d:
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同请求编号对应不同产品。")
                return receipt_view(s.get(Receipt, key.receipt_id))
            product = Product(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                name=data.name,
                purpose=data.purpose,
                owner_id=ctx.actor_id,
            )
            s.add(product)
            s.flush()
            s.add(
                Grant(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    principal_id=ctx.actor_id,
                    can_write=True,
                    expires_at=now() + timedelta(days=30),
                )
            )
            cmd = Command(
                command_id=uuid4(),
                idempotency_key=data.idempotency_key,
                operation="product.create",
                product_id=product.id,
                expected_revision=1,
                payload={"name": data.name, "purpose": data.purpose},
            )
            r = append_receipt(
                s,
                ctx,
                cmd,
                "product",
                product,
                d,
                digest(["product.create", ctx.actor_id, data.idempotency_key]),
                "product",
            )
            s.add(
                RequestKey(
                    tenant_id=ctx.tenant_id,
                    actor_id=ctx.actor_id,
                    key=data.idempotency_key,
                    digest=d,
                    receipt_id=r.id,
                )
            )
            return receipt_view(r)

    @app.post("/v1/commands")
    def command(data: Command, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            result = execute(s, ctx, data, synthetic_mode=synthetic_mode)
        if data.operation == "evidence.lifecycle.upload.abandon" and object_store is not None:
            from pdos_next.upload_lifecycle import reconcile_terminal

            try:
                with tenant_session(engine, ctx.tenant_id) as s:
                    reconcile_terminal(
                        s, ctx, data.product_id, UUID(result["subject_id"]), object_store
                    )
            except (StorageFailure, DomainError):
                # The named terminal decision committed. Its secondary journal may be unknown.
                pass
        return result

    @app.post("/v1/commands/preview")
    def material_preview(data: Command, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            return preview_command(s, ctx, data)

    @app.get("/v1/products/{product_id}/workspace")
    def workspace(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.original_security import source_status

        with tenant_session(engine, ctx.tenant_id) as s:
            s.scalar(select(Product).where(Product.id == product_id).with_for_update())
            require_access(s, ctx, product_id)
            p = s.get(Product, product_id)
            sources = list(
                s.scalars(
                    select(Artifact)
                    .where(
                        Artifact.product_id == product_id,
                        or_(Artifact.visibility == "product", Artifact.owner_id == ctx.actor_id),
                    )
                    .order_by(Artifact.created_at)
                )
            )
            source_ids = {a.id for a in sources}
            claims = list(
                s.scalars(
                    select(Claim)
                    .where(
                        Claim.product_id == product_id,
                        or_(Claim.visibility == "product", Claim.human_owner_id == ctx.actor_id),
                    )
                    .order_by(Claim.created_at)
                )
            )
            works = list(
                s.scalars(
                    select(WorkRequest)
                    .where(
                        WorkRequest.product_id == product_id,
                        WorkRequest.accountable_owner_id == ctx.actor_id,
                    )
                    .order_by(WorkRequest.created_at)
                )
            )
            receipts = list(
                s.scalars(
                    select(Receipt)
                    .where(
                        Receipt.product_id == product_id,
                        or_(Receipt.visibility == "product", Receipt.requester_id == ctx.actor_id),
                    )
                    .order_by(Receipt.created_at.desc())
                    .limit(60)
                )
            )
            return {
                "product": {
                    "id": str(p.id),
                    "name": p.name,
                    "purpose": p.purpose,
                    "revision": p.revision,
                },
                "originals": [
                    original_view(s, row, ctx, object_store)
                    for row in s.scalars(
                        select(UploadedOriginal)
                        .where(
                            UploadedOriginal.product_id == product_id,
                            or_(
                                UploadedOriginal.visibility == "product",
                                UploadedOriginal.owner_id == ctx.actor_id,
                            ),
                        )
                        .order_by(UploadedOriginal.created_at)
                    )
                ],
                "sources": [
                    {
                        "id": str(a.id),
                        "title": a.title,
                        "source_label": a.source_label,
                        "original_id": str(a.original_id) if a.original_id else None,
                        "locator_map": s.get(UploadedOriginal, a.original_id).locator_map
                        if a.original_id
                        else [],
                        "content": a.content,
                        "content_hash": a.content_hash,
                        "visibility": a.visibility,
                        "status": source_status(s, a),
                        "revision": a.revision,
                    }
                    for a in sources
                ],
                "claims": [
                    {
                        "id": str(c.id),
                        "artifact_id": str(c.artifact_id),
                        "line": c.line,
                        "quote": c.quote,
                        "statement": c.statement,
                        "nature": c.nature,
                        "availability": c.availability,
                        "status": c.status,
                        "revision": c.revision,
                        "visibility": c.visibility,
                        "source_status": next(
                            source_status(s, a) for a in sources if a.id == c.artifact_id
                        ),
                    }
                    for c in claims
                    if c.artifact_id in source_ids
                ],
                "works": [
                    {
                        "id": str(w.id),
                        "goal": w.goal,
                        "artifact_id": str(w.artifact_id),
                        "source_revision": w.source_revision,
                        "status": w.status,
                        "error_code": w.error_code,
                        "result_id": str(w.result_id) if w.result_id else None,
                        "revision": w.revision,
                    }
                    for w in works
                    if w.artifact_id in source_ids
                ],
                "receipts": [receipt_view(r) for r in receipts],
                "as_of": now().isoformat(),
                "model_available": False,
            }

    @app.post("/v1/products/{product_id}/receipts/{receipt_id}/revert-preview")
    def revert_preview(product_id: UUID, receipt_id: UUID, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            return preview_confirmation(s, ctx, product_id, "ai.run.revert", receipt_id)

    @app.post("/v1/products/{product_id}/works/{work_id}/cancel-preview")
    def cancel_preview(product_id: UUID, work_id: UUID, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            return preview_confirmation(s, ctx, product_id, "ai.run.cancel", work_id)

    @app.get("/v1/products/{product_id}/definitions")
    def definitions(product_id: UUID, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id) as s:
            require_access(s, ctx, product_id)
            return list_definitions(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/variants")
    def variants(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.products.variants import list_variants

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_variants(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/variants/{variant_id}/compare")
    def compare_variant(
        product_id: UUID,
        variant_id: UUID,
        parent_definition_id: UUID,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.products.variants import compare_variant as compare

        with tenant_session(engine, ctx.tenant_id) as s:
            return compare(s, ctx, product_id, variant_id, parent_definition_id)

    @app.get("/v1/products/{product_id}/projects")
    def projects(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.projects.service import list_projects

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_projects(s, ctx, product_id)

    from pdos_next.domain.manufacturing_baseline.api import (
        register_routes as register_manufacturing,
    )

    register_manufacturing(app, engine, auth_dependency)

    @app.get("/v1/products/{product_id}/configurations")
    def configurations(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.configurations.service import list_configurations

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_configurations(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/builds")
    def builds(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.builds.service import list_builds

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_builds(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/build-execution")
    def build_execution(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.build_execution.service import list_execution

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_execution(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/build-execution/compare")
    def compare_actual_configuration(
        product_id: UUID,
        build_id: UUID,
        engineering_configuration_id: UUID,
        manufacturing_configuration_id: UUID,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.build_execution.service import compare

        with tenant_session(engine, ctx.tenant_id) as s:
            return compare(
                s,
                ctx,
                product_id,
                build_id,
                engineering_configuration_id,
                manufacturing_configuration_id,
            )

    @app.post("/v1/products/{product_id}/supply-captures")
    def supply_capture(
        product_id: UUID,
        data: SupplyCaptureInput,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.supply_execution.service import prepare_capture

        with tenant_session(engine, ctx.tenant_id) as s:
            return prepare_capture(s, ctx, product_id, data)

    @app.get("/v1/products/{product_id}/supply")
    def supply(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.supply_execution.service import list_supply

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_supply(s, ctx, product_id)

    @app.post("/v1/products/{product_id}/cost-captures")
    def cost_capture(
        product_id: UUID,
        data: CostCaptureInput,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.cost_execution.service import prepare_capture

        with tenant_session(engine, ctx.tenant_id) as s:
            return prepare_capture(s, ctx, product_id, data)

    @app.get("/v1/products/{product_id}/costs")
    def costs(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.cost_execution.service import list_costs

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_costs(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/verification")
    def verification(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.verification_execution.service import list_verification

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_verification(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/verification-professional")
    def verification_professional(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.verification_front.service import list_verification

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_verification(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/build-start")
    def build_start(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.domain.build_start.service import list_build_start

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_build_start(s, ctx, product_id)

    @app.get("/v1/products/{product_id}/sample-handoff")
    def sample_handoff(
        product_id: UUID,
        purpose: str | None = Query(default=None, min_length=1, max_length=160),
        build_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.sample_handoff.service import list_sample_handoff

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_sample_handoff(s, ctx, product_id, purpose=purpose, build_id=build_id)

    @app.get("/v1/products/{product_id}/verification-handoff")
    def verification_handoff(
        product_id: UUID, build_id: UUID | None = None, ctx: Context = auth_dependency
    ):
        from pdos_next.domain.verification_handoff.service import list_verification_handoff

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_verification_handoff(s, ctx, product_id, build_id=build_id)

    @app.post("/v1/products/{product_id}/build-start/assessment-inputs")
    def build_assessment_inputs(
        product_id: UUID, data: BuildAssessmentPayload, ctx: Context = auth_dependency
    ):
        from pdos_next.domain.build_start.service import assessment_inputs

        with tenant_session(engine, ctx.tenant_id) as s:
            return assessment_inputs(s, ctx, product_id, data)

    @app.get("/v1/products/{product_id}/verification-launch")
    def verification_launch(
        product_id: UUID, build_id: UUID | None = None, ctx: Context = auth_dependency
    ):
        from pdos_next.domain.verification_launch.service import list_launch

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_launch(s, ctx, product_id, build_id=build_id)

    @app.post("/v1/products/{product_id}/verification-launch/inputs")
    def verification_launch_inputs(product_id: UUID, data: Command, ctx: Context = auth_dependency):
        from pdos_next.domain.verification_launch.service import inputs

        with tenant_session(engine, ctx.tenant_id) as s:
            return inputs(s, ctx, product_id, data)

    @app.get("/v1/products/{product_id}/model-calls")
    def model_calls(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.model_gateway.reconciliation import preview

        with tenant_session(engine, ctx.tenant_id) as s:
            require_access(s, ctx, product_id, write=True, lock=True)
            rows = s.scalars(
                select(BudgetReservation)
                .join(
                    Run,
                    Run.id == BudgetReservation.run_id,
                )
                .where(Run.product_id == product_id, Run.requester_id == ctx.requester_id)
                .order_by(BudgetReservation.created_at.desc())
                .limit(101)
            ).all()
            return {
                "items": [preview(s, ctx, product_id, row.call_id) for row in rows[:100]],
                "has_more": len(rows) > 100,
            }

    @app.get("/v1/products/{product_id}/verification-results")
    def verification_results(
        product_id: UUID,
        build_id: UUID | None = None,
        run_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.verification_results.service import list_results

        with tenant_session(engine, ctx.tenant_id) as s:
            return list_results(s, ctx, product_id, build_id=build_id, run_id=run_id)

    @app.post("/v1/products/{product_id}/verification-results/inputs")
    def verification_result_inputs(product_id: UUID, data: Command, ctx: Context = auth_dependency):
        from pdos_next.domain.verification_results.service import inputs

        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在当前产品范围。", 403)
        with tenant_session(engine, ctx.tenant_id) as s:
            return inputs(s, ctx, product_id, data)

    @app.post("/v1/products/{product_id}/verification-results/captures")
    def verification_result_capture(
        product_id: UUID, data: CaptureInput, ctx: Context = auth_dependency
    ):
        from pdos_next.domain.verification_results.service import (
            extract_capture,
            prepare_capture,
            read_capture_report,
        )

        if object_store is None:
            raise DomainError("STORAGE_UNAVAILABLE", "原报告存储尚未配置。", 503)
        with tenant_session(engine, ctx.tenant_id) as s:
            report = read_capture_report(s, ctx, product_id, data, object_store)
        prepared = extract_capture(data, report)
        with tenant_session(engine, ctx.tenant_id) as s:
            return prepare_capture(s, ctx, product_id, data, prepared)

    @app.post("/v1/products/{product_id}/originals")
    def original_upload(product_id: UUID, data: UploadInput, ctx: Context = auth_dependency):
        if object_store is None:
            raise DomainError("STORAGE_UNAVAILABLE", "原件存储尚未配置。", 503)
        attempt_id = None
        if hasattr(object_store, "put_scoped"):
            from pdos_next.upload_lifecycle import reserve

            with tenant_session(engine, ctx.tenant_id) as s:
                attempt_id = reserve(s, ctx, product_id, data)
        with tenant_session(engine, ctx.tenant_id) as s:
            attempt = s.get(UploadAttempt, attempt_id) if attempt_id else None
            result = upload(s, ctx, product_id, data, object_store, attempt=attempt)
        if hasattr(object_store, "mark_registered"):
            # Only a completed domain transaction can declare registration. If the
            # secondary journal acknowledgement fails, retain its honest unknown state.
            with tenant_session(engine, ctx.tenant_id) as s:
                s.scalar(select(Product).where(Product.id == product_id).with_for_update())
                row = require_original(s, ctx, product_id, UUID(result["subject_id"]))
                reference = object_reference(row)
                try:
                    object_store.mark_registered(reference.id, reference)
                except StorageFailure:
                    pass
        return result

    class LifecycleCandidateInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        action: str

    @app.get("/v1/products/{product_id}/original-lifecycle")
    def lifecycle_inventory(product_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.lifecycle_access import inventory

        if object_store is None:
            raise DomainError("STORAGE_UNAVAILABLE", "原件存储尚未配置。", 503)
        with tenant_session(engine, ctx.tenant_id) as s:
            return inventory(s, ctx, product_id, object_store)

    @app.post("/v1/products/{product_id}/original-lifecycle/{object_id}/candidate")
    def lifecycle_candidate(
        product_id: UUID,
        object_id: UUID,
        data: LifecycleCandidateInput,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.domain.original_lifecycle_execution.service import preview

        with tenant_session(engine, ctx.tenant_id) as s:
            return preview(s, ctx, product_id, object_id, data.action)

    @app.post("/v1/products/{product_id}/original-lifecycle/intents/{intent_id}/reconcile")
    def lifecycle_reconcile(product_id: UUID, intent_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.lifecycle_access import product_gate
        from pdos_next.lifecycle_worker import process
        from pdos_next.models import LifecycleIntentRecord

        with tenant_session(engine, ctx.tenant_id) as s:
            product_gate(s, ctx, product_id)
            row = s.get(LifecycleIntentRecord, intent_id)
            if not row or row.product_id != product_id or row.actor_id != ctx.requester_id:
                raise DomainError("SOURCE_UNAVAILABLE", "生命周期意图不在当前本人范围。", 403)
        return process(
            engine,
            {
                "tenant_id": str(ctx.tenant_id),
                "product_id": str(product_id),
                "subject_id": str(intent_id),
            },
            observe_only=True,
        )

    @app.post("/v1/products/{product_id}/originals/{original_id}/scan")
    def original_scan(
        product_id: UUID, original_id: UUID, data: OriginalScanInput, ctx: Context = auth_dependency
    ):
        from pdos_next.original_security import request_scan

        with tenant_session(engine, ctx.tenant_id) as s:
            return request_scan(
                s,
                ctx,
                product_id,
                original_id,
                expected_epoch=data.expected_epoch,
                idempotency_key=data.idempotency_key,
            )

    @app.get("/v1/products/{product_id}/originals/{original_id}/download")
    def original_download(product_id: UUID, original_id: UUID, ctx: Context = auth_dependency):
        if object_store is None:
            raise DomainError("STORAGE_UNAVAILABLE", "原件存储尚未配置。", 503)
        with tenant_session(engine, ctx.tenant_id) as s:
            from pdos_next.original_security import require_safe

            s.scalar(select(Product).where(Product.id == product_id).with_for_update())
            row = require_original(s, ctx, product_id, original_id, lock=True)
            require_safe(s, ctx, row)
            reference, filename = object_reference(row), row.filename
            # Current ACL and object integrity are both checked before bytes leave this service.
            try:
                from pdos_next.originals import read_registered_bytes

                content = read_registered_bytes(object_store, reference, ctx.tenant_id, product_id)
                require_safe(s, ctx, row)
            except StorageFailure:
                raise DomainError(
                    "STORAGE_UNAVAILABLE", "原件读取失败，未返回内容。", 503
                ) from None
        from urllib.parse import quote

        return Response(
            content,
            media_type=reference.media_type,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/v1/work-requests/{work_id}/resume")
    def resume_work(work_id: UUID, data: ResumeInput | None = None, ctx: Context = auth_dependency):
        if not workflow_enabled:
            if not synthetic_mode:
                raise DomainError("AGENT_TEMPORAL_REQUIRED", "Agent 工作必须经持久执行队列办理。")
            from pdos_agent_runtime.graph import execute_graph

            return execute_graph(
                lambda _: {"value": resume(engine, ctx, work_id, provider, synthetic_mode=True)},
                {},
                thread_id=f"injected-next:{ctx.tenant_id}:{work_id}",
            )["value"]
        if data is None:
            raise DomainError("INVALID_PAYLOAD", "请使用原请求编号继续工作。", 422)
        with tenant_session(engine, ctx.tenant_id) as s:
            work = s.get(WorkRequest, work_id)
            if not work or work.accountable_owner_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "工作不在当前范围。", 403)
            s.scalar(select(Product).where(Product.id == work.product_id).with_for_update())
            require_access(s, ctx, work.product_id, write=True, lock=True)
            fingerprint = digest(["resume", work_id])
            key = s.scalar(
                select(RequestKey).where(
                    RequestKey.actor_id == ctx.actor_id,
                    RequestKey.key == data.idempotency_key,
                )
            )
            if key:
                if key.digest != fingerprint:
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求编号对应了不同工作。")
                return receipt_view(s.get(Receipt, key.receipt_id))
            if work.status in {"completed", "cancelled"}:
                return {"work_id": str(work.id), "status": work.status}
            work.signal_epoch += 1
            work.revision += 1
            cmd = Command(
                command_id=uuid4(),
                idempotency_key=data.idempotency_key,
                operation="ai.work.resume",
                product_id=work.product_id,
                expected_revision=work.revision,
                payload={"work_id": str(work_id)},
            )
            r = append_receipt(
                s,
                ctx,
                cmd,
                "work_request",
                work,
                fingerprint,
                digest(["resume", work_id, work.signal_epoch]),
                "private",
            )
            s.add(
                RequestKey(
                    tenant_id=ctx.tenant_id,
                    actor_id=ctx.actor_id,
                    key=data.idempotency_key,
                    digest=fingerprint,
                    receipt_id=r.id,
                )
            )
            return receipt_view(r)

    return app
