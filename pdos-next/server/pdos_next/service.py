import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from pdos_next.command_handlers import (
    LIVE_CONSUMPTION_OPERATIONS,
    PHASED_MATERIAL_OPERATIONS,
    T1_OPERATIONS,
    T2_OPERATIONS,
    handler,
    reviewed_view,
    tier_of,
)
from pdos_next.contracts import (
    PAYLOADS,
    ArtifactPayload,
    ClaimPayload,
    Command,
    RevertPayload,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Claim,
    Confirmation,
    Consumption,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.schemas.products.definitions import DefinitionDraftPayload


def digest(value) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        )
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class Context:
    tenant_id: UUID
    actor_id: UUID
    requester_id: UUID
    run_id: UUID | None = None
    cancel_epoch: int | None = None
    category_id: UUID | None = None
    agent_run_id: UUID | None = None
    agent_call_id: UUID | None = None

    def __post_init__(self):
        if (self.run_id and self.agent_run_id) or (self.agent_call_id and not self.agent_run_id):
            raise DomainError("FORBIDDEN_SCOPE", "执行身份须绑定唯一的服务器运行。", 403)


def command_digest(command: Command) -> str:
    """One normalized fingerprint for the command owner and its trusted adapters."""
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    return digest(
        {
            "operation": command.operation,
            "category_id": command.category_id,
            "product_id": command.product_id,
            "expected_revision": command.expected_revision,
            "source_read_set": [r.model_dump(mode="json") for r in command.source_read_set],
            "payload": payload.model_dump(mode="json"),
        }
    )


EVENTS = {
    "field.feedback.create": "field.feedback_created",
    "field.feedback.locate": "field.feedback_located",
    "field.feedback.action.record": "field.feedback_action_recorded",
    "field.feedback.followup.link": "field.feedback_followup_linked",
    "knowledge.candidate.create": "knowledge.candidate_created",
    "knowledge.rule.publish": "knowledge.rule_published",
    "work.commitment.review": "commitment.reviewed",
    "ai.automation.draft.save": "ai.automation_draft_saved",
    "ai.automation.activate": "ai.automation_activated",
    "ai.automation.pause": "ai.automation_paused",
    "platform.link.create": "platform.linked",
    "research.snapshot.register": "research.snapshot_registered",
    "category.knowledge.add": "category.knowledge_added",
    "category.knowledge.withdraw": "category.knowledge_withdrawn",
    "category.knowledge.promote": "category.knowledge_promoted",
    "category.parameter.publish": "category.parameter_published",
    "model.configuration.save": "model.configuration_saved",
    "mcp.connector.allow": "mcp.connector_allowed",
    "mcp.tool.grant": "mcp.tool_granted",
    "ai.skill.enable": "ai.skill_enabled",
    "ai.skill.qualify": "ai.skill_qualified",
    "ai.skill.review.record": "ai.skill_review_recorded",
    "ai.budget.configure": "ai.budget_configured",
    "proposal.create": "proposal.created",
    "proposal.item.patch": "proposal.item_patched",
    "proposal.question.create": "proposal.question_created",
    "proposal.g0.submit": "proposal.g0_submitted",
    "proposal.g0.decide": "proposal.g0_decided",
    "evidence.lifecycle.upload.abandon": "original.upload_abandoned",
    "evidence.lifecycle.quarantine": "original.lifecycle_requested",
    "evidence.lifecycle.restore": "original.lifecycle_requested",
    "evidence.lifecycle.cancel": "original.lifecycle_cancelled",
    "evidence.lifecycle.protection.record": "original.protection_recorded",
    "evidence.lifecycle.effect": "original.lifecycle_observed",
    "product.create": "product.created",
    "evidence.artifact.register": "artifact.registered",
    "evidence.claim.record": "claim.recorded",
    "evidence.link.create": "evidence.linked",
    "evidence.claim.withdraw": "claim.withdrawn",
    "proposal.share": "proposal.shared",
    "ai.run.revert": "ai.run_reverted",
    "evidence.original.upload": "original.uploaded",
    "evidence.original.parse": "original.parsed",
    "evidence.original.scan.request": "original.scan_requested",
    "evidence.original.scan.record": "original.scan_recorded",
    "evidence.original.withdraw": "original.withdrawn",
    "product.definition.draft": "definition.draft_created",
    "product.definition.item.patch": "definition.item_patched",
    "product.variant.derive": "variant.derived",
    "product.variant.rebase": "variant.rebased",
    "work.task.create": "task.created",
    "work.external_wait.record": "external_wait.recorded",
    "work.risk.followup.record": "risk.followup_recorded",
    "work.task.assign": "task.assigned",
    "work.task.accept": "task.accepted",
    "work.commitment.accept": "commitment.accepted",
    "work.task.start": "task.started",
    "work.task.submit": "task.submitted",
    "work.task.review": "task.reviewed",
    "work.status_update.create": "project.status_updated",
    "work.plan.propose": "plan.proposed",
    "work.plan.apply": "plan.applied",
    "ai.model_call.reconcile": "ai.model_call_reconciled",
    "engineering.bom.revise": "bom.revised",
    "engineering.configuration.create": "configuration.created",
    "npi.process.revise": "process.revised",
    "npi.work_instruction.record": "work_instruction.recorded",
    "npi.control_plan.record": "control_plan.recorded",
    "npi.manufacturing_baseline.record": "manufacturing_baseline.recorded",
    "npi.manufacturing_baseline.publish": "manufacturing_baseline.published",
    "release.package.assemble": "release.package_assembled",
    "integration.handoff.authorize": "external_handoff.authorized",
    "release.exception.decide": "release.exception_decided",
    "release.exception.withdraw": "release.exception_withdrawn",
    "integration.receipt.record": "external_receipt.recorded",
    "release.engineering.approve": "release.engineering_approved",
    "release.manufacturing.approve": "release.manufacturing_approved",
    "npi.pilot.create": "pilot.created",
    "npi.pilot.result.record": "pilot.results_recorded",
    "build.create": "build.created",
    "build.readiness.compute": "readiness.computed",
    "build.engineering.authorize": "build.engineering_authorization_decided",
    "build.manufacturing.authorize": "build.manufacturing_authorization_decided",
    "build.start": "build.started",
    "build.operational_facts.import": "build.operational_facts_imported",
    "build.configuration.actual.record": "actual_configuration.recorded",
    "build.output.record": "build.output_recorded",
    "build.sample.allocate": "sample.allocated",
    "build.sample.readiness.record": "sample.readiness_recorded",
    "supply.snapshot.record": "supply.snapshot_recorded",
    "supply.kit.compute": "kit.computed",
    "cost.inputs.record": "cost.inputs_recorded",
    "cost.estimate.compute": "cost.estimated",
    "verification.preparation.record": "verification.preparation_recorded",
    "verification.request.create": "verification.requested",
    "verification.method.prepare": "verification.method_prepared",
    "verification.schedule.propose": "verification.schedule_proposed",
    "verification.actual_method.prepare": "verification.actual_method_prepared",
    "verification.handoff.offer": "handoff.offered",
    "verification.handoff.accept": "handoff.accepted",
    "verification.handoff.return": "handoff.returned",
    "test.run.plan": "test.run_planned",
    "verification.schedule.promise": "verification.start_promised",
    "test.run.start": "test.run_started",
    "test.results.import": "test.results_imported",
    "test.result.compute": "test.result_computed",
    "test.run.review": "test.run_reviewed",
    "test.disposition.decide": "test.disposition_decided",
    "test.resources.import": "test.resources_imported",
    "professional.authority.import": "professional.authority_imported",
    "quality.issue.create": "issue.created",
    "quality.issue.merge": "issues.merged",
    "quality.issue.triage": "issue.triaged",
    "quality.issue.containment.record": "issue.contained",
    "quality.capa.draft": "capa.drafted",
    "quality.issue.root_cause.decide": "issue.root_cause_decided",
    "quality.capa.actions.complete": "capa.actions_completed",
    "quality.capa.followup.link": "capa.followup_linked",
    "quality.capa.verification.candidate.record": "CapaVerificationCandidateRecorded",
    "quality.capa.verification.rule.import": "CapaVerificationRulePublished",
    "change.order.prepare": "change.order_prepared",
    "change.order.approve": "change.approved",
    "change.implementation.record": "change.implementation_recorded",
    "change.effectivity.record": "change.effectivity_recorded",
    "change.verification.record": "change.verification_recorded",
    "change.close": "change.closed",
    "change.policy.import": "change.policy_imported",
    "release.policy.import": "release.policy_imported",
    "change.coverage.import": "change.coverage_imported",
    "change.selection.decide": "change.selection_decided",
    "quality.capa.observation.record": "CapaObservationRecorded",
    "quality.capa.verification.review": "CapaVerificationReviewed",
    "quality.policy.import": "quality.policy_imported",
    "change.request.create": "change.requested",
    "change.impact.compute": "change.impact_created",
}


def require_access(s, ctx: Context, product_id: UUID | None, write=False, lock=False):
    if product_id is None:
        from pdos_next.category_scope import category_scope

        return category_scope(s, ctx, write=write, lock=lock)
    from pdos_next.database import require_context
    from pdos_next.request_proof import authority_current, request_proof

    require_context(s, ctx)
    proof = request_proof(s)
    product = proof.read_rows.get((Product, product_id)) or s.get(Product, product_id)
    if not product or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "型号不在当前授权范围。", 403)
    proof.read_rows[(Product, product_id)] = product
    if ctx.category_id is not None and product.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "型号与当前品类不匹配。", 403)
    key = (ctx.tenant_id, product.category_id, ctx.actor_id, ctx.requester_id)
    previous = proof.authority.get(key)
    if previous and (not lock or previous["locked"]):
        if not authority_current(previous["rows"], now()):
            raise DomainError("FORBIDDEN_SCOPE", "当前身份的品类授权已失效。", 403)
        if write and not previous["can_write"]:
            raise DomainError("FORBIDDEN_SCOPE", "当前身份没有品类写入权限。", 403)
        return product
    principals = sorted({ctx.actor_id, ctx.requester_id}, key=str)
    query = (
        select(Principal, Grant)
        .join(
            Grant, (Grant.principal_id == Principal.id) & (Grant.tenant_id == Principal.tenant_id)
        )
        .where(
            Principal.id.in_(principals),
            Principal.tenant_id == ctx.tenant_id,
            Grant.category_id == product.category_id,
        )
        .order_by(Principal.id)
        .execution_options(populate_existing=True)
    )
    # Hold authority rows for a writing request; revocation cannot race its effects.
    rows = s.execute(query.with_for_update(read=True) if lock else query).all()
    if len(rows) != len(principals) or any(
        not principal.active or (grant.expires_at is not None and grant.expires_at <= now())
        for principal, grant in rows
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前身份没有这个品类的操作权限。", 403)
    writable = all(grant.can_write for _, grant in rows)
    proof.authority[key] = {
        "locked": lock,
        "can_write": writable,
        "epochs": tuple((p.id, p.access_epoch, g.access_epoch) for p, g in rows),
        "rows": rows,
    }
    if write and not writable:
        raise DomainError("FORBIDDEN_SCOPE", "当前身份没有品类写入权限。", 403)
    return product


def command_scope(s, ctx, command, *, lock=False):
    """Only registered category owners can operate without a model."""
    from pdos_next.command_handlers import CATEGORY_OPERATIONS

    if command.product_id is None and command.operation not in CATEGORY_OPERATIONS:
        raise DomainError("FORBIDDEN_SCOPE", "此操作须绑定型号。", 403)
    module = handler(command.operation)
    write = lock and (
        module.requires_category_write(command)
        if hasattr(module, "requires_category_write")
        else True
    )
    scope = require_access(s, ctx, command.product_id, write=write, lock=lock)
    if lock and scope.id is None:
        from pdos_next.models import Category
        from pdos_next.request_proof import request_proof

        category = s.scalar(
            select(Category)
            .where(Category.id == scope.category_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if category is None:
            raise DomainError("FORBIDDEN_SCOPE", "品类的保护范围不可用。", 403)
        request_proof(s).scope_locks.add((Category, category.id))
        # Use the actual root read under the gate, including a concurrent version advance.
        from dataclasses import replace

        scope = replace(
            scope,
            revision=category.revision,
            lifecycle_epoch=category.lifecycle_epoch,
            owner_id=category.owner_id,
            name=category.name,
        )
    if lock and scope.id is not None:
        from pdos_next.models import Category
        from pdos_next.request_proof import request_proof, scoped_rows

        # Evidence rows can connect product originals to category consumers.
        # Acquire Category before Product, including an empty evidence read set.
        if (
            getattr(module, "category_lifecycle_fence", False)
            or command.operation
            in {"product.definition.draft", "product.variant.derive", "product.variant.rebase"}
        ) or (
            command.source_read_set
            and s.scalar(
                select(Artifact.id)
                .where(
                    Artifact.tenant_id == ctx.tenant_id,
                    Artifact.category_id == scope.category_id,
                    Artifact.product_id.is_(None),
                    Artifact.id.in_([ref.artifact_id for ref in command.source_read_set]),
                )
                .limit(1)
            )
            is not None
        ):
            roots = scoped_rows(
                s,
                (Category, scope.category_id),
                select(Category).where(
                    Category.id == scope.category_id, Category.tenant_id == ctx.tenant_id
                ),
                lock=True,
            )
            if not roots:
                raise DomainError("FORBIDDEN_SCOPE", "品类来源的保护范围不可用。", 403)
            request_proof(s).scope_locks.add((Category, scope.category_id))
        scope = s.scalar(
            select(Product)
            .where(Product.id == scope.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        request_proof(s).scope_locks.add(scope.id)
    return scope


def confirmation_subject(s, ctx, command, scope, payload, module):
    """A registered owner resolves the actual category/model/proposal to confirm."""
    if hasattr(module, "confirmation_subject"):
        kind, row = module.confirmation_subject(s, ctx, command, scope, payload)
        if kind in {"parameter", "category_knowledge"}:
            from pdos_next.domain.preproject.category_models import (
                KnowledgeCurrent,
                ParameterCurrent,
            )

            model = ParameterCurrent if kind == "parameter" else KnowledgeCurrent
            key = row.parameter_id if kind == "parameter" else row.lineage_id
            if not isinstance(row, model) or scope.id is not None:
                raise DomainError("INTEGRATION_REQUIRED", "品类资料确认主体未注册。", 503)
            actual = s.get(model, (ctx.tenant_id, key))
            if not actual or actual.category_id != ctx.category_id:
                raise DomainError("FORBIDDEN_SCOPE", "确认主体不在当前品类。", 403)
            return kind, key, actual.current_version
        if kind not in {
            "category",
            "product",
            "proposal",
            "claim",
            "agent_run",
            "definition_revision",
        }:
            raise DomainError("INTEGRATION_REQUIRED", "确认主体未注册。", 503)
        # RLS-read the owner-selected stored object; a payload cannot supply policy facts.
        actual = s.get(type(row), row.id)
        if (
            actual is None
            or actual.tenant_id != ctx.tenant_id
            or (actual.id if kind == "category" else actual.category_id) != ctx.category_id
            or getattr(actual, "product_id", scope.id) != scope.id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "确认主体不在当前范围。", 403)
        revision = actual.cancel_epoch + 1 if kind == "agent_run" else actual.revision
        return kind, actual.id, revision
    if scope.id is None:
        return "category", scope.category_id, scope.revision
    return "product", scope.id, scope.revision


def _signed_product_source(s, ctx, product_id, artifact_id, revision=None):
    """A stored sealed G0 citation can carry its actual source into that Product.

    Both rows use ordinary caller RLS. The source policy proves the immutable
    signed citation and current source audience; a caller-provided ID or scope
    alone cannot establish this exception to the native product source fence.
    """
    if product_id is None:
        return False
    from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource

    query = (
        select(DefinitionSource.id)
        .join(
            DefinitionRevision,
            (DefinitionRevision.id == DefinitionSource.definition_id)
            & (DefinitionRevision.tenant_id == DefinitionSource.tenant_id),
        )
        .where(
            DefinitionSource.tenant_id == ctx.tenant_id,
            DefinitionSource.category_id == ctx.category_id,
            DefinitionSource.product_id == product_id,
            DefinitionSource.artifact_id == artifact_id,
            DefinitionRevision.product_id == product_id,
            DefinitionRevision.category_id == ctx.category_id,
            DefinitionRevision.sealed.is_(True),
            DefinitionRevision.g0_decision_id.is_not(None),
        )
        .limit(1)
    )
    if revision is not None:
        query = query.where(DefinitionSource.source_revision == revision)
    return s.scalar(query) is not None


def source_for(s, ctx, product_id, artifact_id, revision=None):
    from pdos_next.request_proof import request_proof

    category_id = ctx.category_id or require_access(s, ctx, product_id).category_id
    proof = request_proof(s)
    key = (
        ctx.tenant_id,
        ctx.actor_id,
        ctx.requester_id,
        ctx.category_id,
        product_id,
        artifact_id,
    )
    writing = any(entry["locked"] for entry in proof.authority.values())
    locked_key = (Artifact, ("locked", artifact_id))
    held = s.info.get("read_snapshot") or (writing and proof.read_rows.get(locked_key))
    source = (
        (
            proof.sources.get(key)
            or proof.source_rows.get(key)
            or proof.read_rows.get((Artifact, artifact_id))
        )
        if held
        else None
    )
    if source is None or (writing and not proof.read_rows.get(locked_key)):
        query = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.category_id == category_id,
        )
        if product_id is not None:
            query = query.where(Artifact.product_id.is_(None) | (Artifact.product_id == product_id))
        source = s.scalar(
            (query.with_for_update(read=True) if writing else query).execution_options(
                populate_existing=True
            )
        )
        if source is None and _signed_product_source(s, ctx, product_id, artifact_id, revision):
            query = select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == category_id,
            )
            source = s.scalar(
                (query.with_for_update(read=True) if writing else query).execution_options(
                    populate_existing=True
                )
            )
        proof.read_rows[locked_key] = writing
    # Database RLS applies the model audience and named reviewers as well as category membership.
    if (
        not source
        or source.tenant_id != ctx.tenant_id
        or source.category_id != category_id
        or (
            product_id is not None
            and source.product_id not in (None, product_id)
            and not _signed_product_source(s, ctx, product_id, artifact_id, revision)
        )
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "来源不在当前授权范围。", 403)
    if product_id is None and source.product_id is not None:
        # A category consumer retains the source's actual model audience. The
        # source ID/version comes from the command or the immutable Run read-set.
        require_access(s, ctx, source.product_id)
    if source.status != "active":
        raise DomainError("SOURCE_UNAVAILABLE", "来源已撤回，不能继续使用。")
    if revision is not None and source.revision != revision:
        raise DomainError("SOURCE_STALE", "来源版本已经变化。")
    if source.original_id and (not held or key not in proof.sources):
        from pdos_next.original_security import require_safe
        from pdos_next.originals import require_original

        original = require_original(
            s,
            ctx,
            source.product_id if source.product_id not in (None, product_id) else product_id,
            source.original_id,
            lock=writing,
        )
        require_safe(s, ctx, original, lock=writing)
    proof.sources[key] = source
    return source


def prove_sources(s, ctx, product_id, reads):
    from pdos_next.request_proof import request_proof

    if not reads:
        return
    expected = {}
    for read in reads:
        if read.artifact_id in expected and expected[read.artifact_id] != read.expected_revision:
            raise DomainError("VALIDATION_FAILED", "同一来源不能同时声明两个版本。", 422)
        expected[read.artifact_id] = read.expected_revision
    proof = request_proof(s)
    prefix = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id, product_id)
    missing = [
        artifact_id for artifact_id in expected if (*prefix, artifact_id) not in proof.sources
    ]
    if missing:
        category_id = ctx.category_id or require_access(s, ctx, product_id).category_id
        query = select(Artifact).where(
            Artifact.category_id == category_id,
            Artifact.id.in_(missing),
        )
        if product_id is not None:
            query = query.where(Artifact.product_id.is_(None) | (Artifact.product_id == product_id))
        rows = s.scalars(query.order_by(Artifact.id).with_for_update(read=True))
        for row in rows:
            proof.source_rows[(*prefix, row.id)] = row
            proof.read_rows[(Artifact, ("locked", row.id))] = True
    for artifact_id, revision in expected.items():
        source_for(s, ctx, product_id, artifact_id, revision)


def receipt_view(r):
    return {
        "id": str(r.id),
        "category_id": str(r.category_id),
        "product_id": str(r.product_id) if r.product_id is not None else None,
        "operation": r.operation,
        "subject_type": r.subject_type,
        "subject_id": str(r.subject_id),
        "subject_revision": r.subject_revision,
        "writer_id": str(r.actor_id),
        "requester_id": str(r.requester_id),
        "created_at": r.created_at.isoformat(),
        "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None,
        "result": r.result,
    }


def remember_key(s, ctx, key, request_digest, receipt):
    """Atomic metadata alias; simultaneous replays cannot duplicate a request key."""
    s.execute(
        insert(RequestKey)
        .values(
            tenant_id=ctx.tenant_id,
            category_id=receipt.category_id,
            actor_id=ctx.actor_id,
            key=key,
            digest=request_digest,
            receipt_id=receipt.id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "actor_id", "key"])
    )
    bound = s.scalar(
        select(RequestKey).where(RequestKey.actor_id == ctx.actor_id, RequestKey.key == key)
    )
    if bound is None or bound.digest != request_digest or bound.receipt_id != receipt.id:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同请求编号对应了不同内容。")


def append_receipt(s, ctx, command, subject_type, subject, request_digest, intent, visibility):
    r = Receipt(
        id=getattr(subject, "prepared_receipt_id", None) or uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=command.category_id,
        product_id=command.product_id,
        command_id=command.command_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=command.operation,
        subject_type=subject_type,
        subject_id=subject.id,
        subject_revision=subject.revision,
        visibility=visibility,
        request_digest=request_digest,
        intent_digest=intent,
        run_id=ctx.run_id,
        agent_run_id=ctx.agent_run_id or getattr(subject, "prepared_by_run_id", None),
        confirmation_id=getattr(subject, "confirmation_id", None),
        result={
            "id": str(subject.id),
            "revision": subject.revision,
            "status": subject.status,
            **getattr(subject, "action_result", {}),
        },
    )
    s.add(r)
    s.flush()
    s.add_all(
        [
            Audit(
                tenant_id=ctx.tenant_id,
                receipt_id=r.id,
                actor_id=ctx.actor_id,
                operation=command.operation,
            ),
            Outbox(
                tenant_id=ctx.tenant_id,
                receipt_id=r.id,
                type=EVENTS[command.operation],
                subject_id=subject.id,
                subject_revision=subject.revision,
                actor_id=ctx.actor_id,
                correlation_id=ctx.agent_run_id or ctx.run_id or command.command_id,
            ),
        ]
    )
    return r


def check_run(s, ctx, product_id):
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.execution import command_run

        return command_run(s, ctx, product_id)
    if ctx.run_id is None:
        return None
    raise DomainError("SOURCE_UNAVAILABLE", "旧运行已停止执行，请从小Pai运行入口委派。")


def check_qualification(s, ctx, operation, run, synthetic_mode):
    actor = s.get(Principal, ctx.actor_id)
    if operation in T2_OPERATIONS and (
        actor.kind != "human"
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or ctx.agent_run_id is not None
        or ctx.agent_call_id is not None
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "专业批准只由当前有权的具名本人办理。", 403)
    if actor.kind != "agent":
        return
    if not run:
        raise DomainError("FORBIDDEN_SCOPE", "AI 必须使用服务器绑定的运行身份。", 403)
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.execution import qualify_command

        qualify_command(s, ctx, operation, run)
        return
    raise DomainError("SOURCE_UNAVAILABLE", "AI 写入须绑定注册小Pai运行与实际工具调用。")


def confirmation_for(
    s, ctx, product_id, operation, subject_id, revision, token, *, subject_type="product"
):
    c = s.scalar(
        select(Confirmation)
        .where(
            Confirmation.token_hash == digest(token),
            Confirmation.product_id == product_id,
            Confirmation.category_id == ctx.category_id,
            Confirmation.subject_type == subject_type,
            Confirmation.actor_id == ctx.actor_id,
            Confirmation.operation == operation,
            Confirmation.subject_id == subject_id,
        )
        .with_for_update()
    )
    from pdos_next.clock import proof_deadline_current

    tier = "T2" if operation in T2_OPERATIONS else "T1"
    if not c or c.consumed or not proof_deadline_current(tier, c.expires_at, now()):
        raise DomainError("CONFIRMATION_REQUIRED", "请重新查看此次操作的实际范围。")
    if c.revision != revision:
        raise DomainError("VERSION_CONFLICT", "预览后对象已发生变化，请核对差异。")
    return c


def reversible_claim(s, ctx, receipt_id, product_id):
    r = s.get(Receipt, receipt_id)
    if (
        not r
        or r.product_id != product_id
        or r.operation != "evidence.claim.record"
        or r.requester_id != ctx.requester_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "只能撤回自己登记或委派登记的来源事实。", 403)
    claim = s.scalar(select(Claim).where(Claim.id == r.subject_id).with_for_update())
    if not claim or claim.status != "active" or claim.revision != r.subject_revision:
        raise DomainError("UNDO_BLOCKED_BY_DEPENDENCY", "记录已改变或已经撤回，不能覆盖后续工作。")
    if s.scalar(select(Consumption.id).where(Consumption.claim_id == claim.id).limit(1)):
        raise DomainError("UNDO_BLOCKED_BY_DEPENDENCY", "记录已被下游使用，必须保留并另行处置。")
    return r, claim


def preview_confirmation(s, ctx, product_id, operation, subject_id):
    if operation == "ai.run.revert":
        _, claim = reversible_claim(s, ctx, subject_id, product_id)
        command = Command(
            category_id=ctx.category_id,
            product_id=product_id,
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation=operation,
            expected_revision=claim.revision,
            payload={"receipt_id": str(subject_id)},
        )
        result = preview_command(s, ctx, command)
        return {
            **result,
            "expected_revision": claim.revision,
            "statement": claim.statement,
            "effect": "撤回此条事实，原文与历史回执保留。",
        }
    raise DomainError("FORBIDDEN_SCOPE", "不支持的确认范围。", 403)


def material_digest(ctx, command, payload, module):
    return digest(
        {
            "tenant": ctx.tenant_id,
            "actor": ctx.actor_id,
            "requester": ctx.requester_id,
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "expected_revision": command.expected_revision,
            "read_set": sorted(
                [r.model_dump(mode="json") for r in command.source_read_set],
                key=lambda r: (r["artifact_id"], r["expected_revision"]),
            ),
            "payload": module.semantic(payload),
        }
    )


MINIMAL_CURRENT_OPERATIONS = frozenset(
    {"quality.issue.triage", "quality.issue.containment.record", "test.run.start"}
)


def preview_command(s, ctx, command):
    from pdos_next.category_scope import require_command_category

    require_command_category(s, ctx, command)
    module = handler(command.operation)
    if command.operation not in T1_OPERATIONS | T2_OPERATIONS and not (
        hasattr(module, "supports_confirmation") and module.supports_confirmation(command)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "这个操作没有开放人工办理预览。", 403)
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    product = command_scope(s, ctx, command, lock=True)
    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id or ctx.agent_run_id or actor.kind != "human" or ctx.actor_id != ctx.requester_id:
        raise DomainError("NAMED_DECISION_REQUIRED", "此确认只由具名本人执行。", 403)
    prove_sources(s, ctx, product.id, command.source_read_set)
    module = handler(command.operation)
    if command.operation in MINIMAL_CURRENT_OPERATIONS:
        phase = module.prepare_preview(s, ctx, command, product, payload)
        snapshot = module.preview_prepared(s, ctx, command, product, payload, phase)
        stored_snapshot = {
            "contract": "s0.direct-confirmation.v1",
            "review": snapshot,
            "owner_material": module.encode_prepared(phase),
        }
    elif command.operation in PHASED_MATERIAL_OPERATIONS:
        phase = module.prepare_preview(s, ctx, command, product, payload)
        snapshot = module.preview_prepared(s, ctx, command, product, payload, phase)
    elif command.operation == "test.run.plan":
        from pdos_next.launch_plan_preview import preview_once

        snapshot = preview_once(s, ctx, command, product, payload)
    else:
        module.validate(s, ctx, command, product, payload)
        snapshot = reviewed_view(module, s, ctx, command, product, payload)
    kind, subject_id, revision = confirmation_subject(s, ctx, command, product, payload, module)
    token = secrets.token_urlsafe(32)
    expires = None if command.operation in T2_OPERATIONS else now() + timedelta(minutes=10)
    s.add(
        Confirmation(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            actor_id=ctx.actor_id,
            operation=command.operation,
            category_id=ctx.category_id,
            subject_type=kind,
            subject_id=subject_id,
            revision=revision,
            token_hash=digest(token),
            payload_digest=material_digest(ctx, command, payload, module),
            snapshot=stored_snapshot
            if command.operation in MINIMAL_CURRENT_OPERATIONS
            else snapshot,
            expires_at=expires,
        )
    )
    prepared = command.model_dump(mode="json")
    named_decision = command.operation in T2_OPERATIONS
    token_field = "approval_token" if named_decision else "confirmation_token"
    prepared["payload"] = {
        **payload.model_dump(mode="json", exclude_unset=True),
        token_field: token,
    }
    return {
        "command": prepared,
        token_field: token,
        "expires_at": expires.isoformat() if expires is not None else None,
        "review": snapshot,
        **({"write_tier": "T2", "named_decision": True} if named_decision else {}),
    }


def consume_direct_confirmation(s, ctx, command, product, payload, module):
    """Consume the saved server proof after direct Current/source watermark checks."""
    token = getattr(payload, "confirmation_token", None)
    if not token:
        raise DomainError("CONFIRMATION_REQUIRED", "请先查看实际变更并确认一次。")
    kind, identity, revision = confirmation_subject(s, ctx, command, product, payload, module)
    confirmation = confirmation_for(
        s, ctx, product.id, command.operation, identity, revision, token, subject_type=kind
    )
    saved = confirmation.snapshot
    if (
        confirmation.payload_digest != material_digest(ctx, command, payload, module)
        or not isinstance(saved, dict)
        or saved.get("contract") != "s0.direct-confirmation.v1"
        or not isinstance(saved.get("owner_material"), dict)
    ):
        raise DomainError("CONFIRMATION_SCOPE_CHANGED", "预览载荷或对象已改变，请重新核对。")
    phase = module.prepare_confirmed(s, ctx, command, product, payload, saved["owner_material"])
    confirmation.consumed = True
    return phase


def material_confirmation_for(s, ctx, command, product, payload, module):
    named_decision = command.operation in T2_OPERATIONS
    token = getattr(payload, "approval_token" if named_decision else "confirmation_token", None)
    if not token:
        raise DomainError(
            "NAMED_APPROVAL_REQUIRED" if named_decision else "CONFIRMATION_REQUIRED",
            "请先核对固定范围，由有权本人具名办理决定。"
            if named_decision
            else "请先查看实际变更并确认一次。",
        )
    try:
        kind, subject_id, revision = confirmation_subject(s, ctx, command, product, payload, module)
        confirmation = confirmation_for(
            s, ctx, product.id, command.operation, subject_id, revision, token, subject_type=kind
        )
    except DomainError as failure:
        if failure.reason == "CONFIRMATION_REQUIRED" and command.operation in {
            "quality.issue.root_cause.decide",
            "quality.capa.actions.complete",
            "quality.capa.followup.link",
        }:
            from pdos_next.quality_followup_host import expired_confirmation_recovery

            recovery = expired_confirmation_recovery(s, ctx, command, product, payload, module)
            if recovery is not None:
                raise DomainError(
                    "FOLLOWUP_CONFIRMATION_EXPIRED",
                    "原操作尚未保存，未消费的确认已过期；请重新核对原操作的当前范围。",
                    recovery=recovery,
                ) from failure
        raise
    return confirmation


def consume_material_confirmation(
    s,
    ctx,
    command,
    product,
    payload,
    module,
    *,
    prepared_review=None,
    write_phase=None,
    prepared_confirmation=None,
):
    confirmation = prepared_confirmation
    if confirmation is None:
        confirmation = material_confirmation_for(s, ctx, command, product, payload, module)
    if prepared_review is not None and command.operation not in PHASED_MATERIAL_OPERATIONS:
        raise DomainError("INTEGRATION_REQUIRED", "此操作未接入本调用内实质准备。", 503)
    if confirmation.payload_digest != material_digest(ctx, command, payload, module) or digest(
        confirmation.snapshot
    ) != digest(
        prepared_review
        if prepared_review is not None
        else reviewed_view(module, s, ctx, command, product, payload)
    ):
        raise DomainError("CONFIRMATION_SCOPE_CHANGED", "预览内容或对象已改变，请重新核对。")
    live_material = command.operation in LIVE_CONSUMPTION_OPERATIONS
    if live_material:
        if write_phase is None or prepared_review is None:
            raise DomainError("INTEGRATION_REQUIRED", "缺本次候选材料核对。", 503)
        binding = module.bind_consumption(
            s, ctx, command, product, payload, write_phase, confirmation
        )
    confirmation.consumed = True
    if live_material:
        marker = module.record_consumption(
            s, ctx, command, product, payload, write_phase, confirmation, binding
        )
        return binding, marker
    if command.operation in {
        "quality.issue.root_cause.decide",
        "quality.capa.actions.complete",
        "quality.capa.followup.link",
    }:
        from pdos_next.quality_followup_host import record_consumed_confirmation

        record_consumed_confirmation(s, ctx, command, payload, module, confirmation)
    return confirmation


def execute(s, ctx: Context, command: Command, *, synthetic_mode=False):
    from pdos_next.category_scope import require_command_category

    require_command_category(s, ctx, command)
    if command.operation in {
        "ai.work.start",
        "ai.work.state.update",
        "ai.work.resume",
        "ai.run.cancel",
    }:
        raise DomainError("SOURCE_UNAVAILABLE", "请通过小Pai运行入口委派或取消运行。")
    payload_cls = PAYLOADS.get(command.operation)
    if not payload_cls:
        code = (
            "NAMED_DECISION_REQUIRED"
            if command.operation.endswith(".publish")
            else "FORBIDDEN_SCOPE"
        )
        raise DomainError(code, "该命令未在当前可执行能力中开放。", 403)
    # A registered payload still needs a registered tier; nothing falls through to T0.
    tier_of(command.operation)
    payload = payload_cls.model_validate(command.payload)
    request_digest = command_digest(command)
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == command.idempotency_key,
        )
    )
    if key:
        if key.digest != request_digest:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同请求编号对应了不同内容。")
        receipt = s.get(Receipt, key.receipt_id)
        if receipt is None:
            raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
        return receipt_view(receipt)

    module = handler(command.operation)
    reads = {r.artifact_id: r.expected_revision for r in command.source_read_set}
    # The semantic fingerprint is server-derived. A different model/client key cannot bypass it.
    semantic = payload.model_dump(mode="json")
    if module:
        semantic = module.semantic(payload)
    if isinstance(payload, DefinitionDraftPayload):
        from pdos_next.domain.products.definitions import semantic as definition_semantic

        semantic = definition_semantic(payload)
    if isinstance(payload, RevertPayload):
        semantic.pop("confirmation_token", None)
    intent = digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "payload": semantic,
            **({"named_actor": ctx.requester_id} if module else {}),
            "source_revision": reads.get(payload.artifact_id)
            if isinstance(payload, ClaimPayload)
            else None,
            "private_owner": ctx.requester_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )
    prior = s.scalar(
        select(Receipt).where(
            Receipt.category_id == command.category_id,
            Receipt.product_id == command.product_id,
            Receipt.intent_digest == intent,
        )
    )
    if prior:
        remember_key(s, ctx, command.idempotency_key, request_digest, prior)
        return receipt_view(prior)

    product = command_scope(s, ctx, command, lock=True)
    if product.category_id != command.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "命令与型号品类不匹配。", 403)
    # A concurrent request may have committed while this request waited for the object lock.
    concurrent_key = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id, RequestKey.key == command.idempotency_key
        )
    )
    if concurrent_key:
        if concurrent_key.digest != request_digest:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同请求编号对应了不同内容。")
        receipt = s.get(Receipt, concurrent_key.receipt_id)
        if receipt is None:
            raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
        return receipt_view(receipt)
    old = s.scalar(
        select(Receipt).where(
            Receipt.category_id == ctx.category_id,
            Receipt.product_id == product.id,
            Receipt.intent_digest == intent,
        )
    )
    if old:
        remember_key(s, ctx, command.idempotency_key, request_digest, old)
        return receipt_view(old)

    require_access(
        s,
        ctx,
        product.id,
        write=module.requires_category_write(command)
        if hasattr(module, "requires_category_write")
        else True,
        lock=True,
    )
    run = check_run(s, ctx, product.id)
    check_qualification(s, ctx, command.operation, run, synthetic_mode)
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.execution import check_command_digest

        check_command_digest(s, ctx, command.operation, request_digest)
    prove_sources(s, ctx, product.id, command.source_read_set)
    if isinstance(payload, DefinitionDraftPayload):
        from pdos_next.domain.products.definitions import validate

        validate(s, ctx, command, product, payload)
    module = handler(command.operation)
    # New effects receive owner checks. Historical recovery above uses current read access.
    deferred_candidate_validation = command.operation in (
        LIVE_CONSUMPTION_OPERATIONS | MINIMAL_CURRENT_OPERATIONS
    )
    validated_write = None
    if module and not deferred_candidate_validation:
        validated_write = module.validate(s, ctx, command, product, payload)

    if (
        module
        and hasattr(module, "replay_subject")
        and command.operation not in MINIMAL_CURRENT_OPERATIONS
    ):
        replay = module.replay_subject(s, ctx, command, product, payload)
        if replay is not None:
            replay_type = (
                module.replay_subject_type(payload)
                if hasattr(module, "replay_subject_type")
                else "original_lifecycle_intent"
            )
            previous = s.scalar(
                select(Receipt).where(
                    Receipt.product_id == product.id,
                    Receipt.operation == command.operation,
                    Receipt.subject_type == replay_type,
                    Receipt.subject_id == replay.id,
                )
            )
            if previous:
                remember_key(s, ctx, command.idempotency_key, request_digest, previous)
                return receipt_view(previous)
    if isinstance(payload, ArtifactPayload):
        if command.expected_revision != product.revision:
            raise DomainError("VERSION_CONFLICT", "型号范围版本已变化。")
    visibility = getattr(payload, "visibility", "private")
    if module:
        write_phase, prepared_review, consumption = None, None, None
        material_confirmation = None
        prepared_confirmation = None
        direct_confirmation = command.operation in MINIMAL_CURRENT_OPERATIONS
        if direct_confirmation:
            write_phase = consume_direct_confirmation(s, ctx, command, product, payload, module)
        elif command.operation in PHASED_MATERIAL_OPERATIONS:
            if getattr(module, "confirmation_watermarks", False):
                prepared_confirmation = material_confirmation_for(
                    s, ctx, command, product, payload, module
                )
                write_phase, prepared_review = module.prepare_write_review(
                    s, ctx, command, product, payload, proof=prepared_confirmation
                )
            else:
                write_phase, prepared_review = module.prepare_write_review(
                    s, ctx, command, product, payload
                )
        if not direct_confirmation and (
            command.operation in T1_OPERATIONS | T2_OPERATIONS
            or (hasattr(module, "needs_confirmation") and module.needs_confirmation(payload))
        ):
            if write_phase is not None:
                consumption = consume_material_confirmation(
                    s,
                    ctx,
                    command,
                    product,
                    payload,
                    module,
                    prepared_review=prepared_review,
                    write_phase=write_phase,
                    prepared_confirmation=prepared_confirmation,
                )
            else:
                material_confirmation = consume_material_confirmation(
                    s, ctx, command, product, payload, module
                )
                if hasattr(validated_write, "confirmation_id"):
                    validated_write.confirmation_id = material_confirmation.id
        if direct_confirmation:
            subject, subject_type, visibility = module.apply_confirmed(
                s, ctx, command, product, payload, write_phase
            )
        elif write_phase is not None:
            if command.operation in LIVE_CONSUMPTION_OPERATIONS:
                subject, subject_type, visibility = module.apply_prepared_write(
                    s, ctx, command, product, payload, write_phase, consumption=consumption
                )
            else:
                subject, subject_type, visibility = module.apply_prepared_write(
                    s, ctx, command, product, payload, write_phase
                )
        elif hasattr(module, "apply_validated"):
            subject, subject_type, visibility = module.apply_validated(
                s, ctx, command, product, payload, validated_write
            )
        else:
            subject, subject_type, visibility = module.apply(s, ctx, command, product, payload)
        if material_confirmation is not None and command.operation in {
            "proposal.create",
            "proposal.item.patch",
            "proposal.question.create",
            "category.knowledge.add",
            "category.knowledge.withdraw",
            "category.knowledge.promote",
            "category.parameter.publish",
            "evidence.claim.record",
            "research.snapshot.register",
            "evidence.claim.withdraw",
            "proposal.share",
            "product.definition.item.patch",
            "platform.link.create",
            "ai.run.revert",
        }:
            subject.confirmation_id = material_confirmation.id
        if hasattr(subject, "budget_exceeded"):
            subject.action_result = {"budget_exceeded": subject.budget_exceeded}
    elif isinstance(payload, DefinitionDraftPayload):
        from pdos_next.domain.products.definitions import apply_draft

        subject, subject_type, visibility = apply_draft(s, ctx, command, product, payload)
    elif isinstance(payload, ArtifactPayload):
        subject = Artifact(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product.id,
            owner_id=ctx.requester_id,
            **payload.model_dump(),
            content_hash=digest(payload.content),
        )
        subject_type = "artifact"
    elif isinstance(payload, RevertPayload):
        _, subject = reversible_claim(s, ctx, payload.receipt_id, product.id)
        c = confirmation_for(
            s,
            ctx,
            product.id,
            command.operation,
            payload.receipt_id,
            subject.revision,
            payload.confirmation_token,
        )
        if command.expected_revision != subject.revision:
            raise DomainError("VERSION_CONFLICT", "事实记录版本已变化。")
        subject.status = "reverted"
        subject.revision += 1
        c.consumed = True
        subject_type = "claim"
        visibility = subject.visibility
    try:
        from sqlalchemy import inspect

        if inspect(subject, raiseerr=False) is not None:
            s.add(subject)
        if command.operation in {
            "quality.capa.observation.record",
            "quality.capa.verification.review",
            "change.selection.decide",
        }:
            # These handlers stage an immutable fact and (for Observation) a Current
            # pointer. The immediate pointer guard must read the fact in this UOW.
            s.flush([subject])
        s.flush()
        # Locks on the product, grant, source, qualification and run are held until commit.
        check_run(s, ctx, product.id)
        if module and subject_type in getattr(module, "deduplicate_subject", ()):
            prior = s.scalar(
                select(Receipt).where(
                    Receipt.product_id == product.id,
                    Receipt.operation == command.operation,
                    Receipt.subject_type == subject_type,
                    Receipt.subject_id == subject.id,
                )
            )
            if prior:
                remember_key(s, ctx, command.idempotency_key, request_digest, prior)
                return receipt_view(prior)
        r = append_receipt(
            s, ctx, command, subject_type, subject, request_digest, intent, visibility
        )
        remember_key(s, ctx, command.idempotency_key, request_digest, r)
        s.flush()
        if module and hasattr(module, "finalize_receipt"):
            module.finalize_receipt(s, ctx, command, product, payload, subject, r)
        if isinstance(payload, DefinitionDraftPayload) and payload.mode == "inherit_parent":
            from pdos_next.domain.products.definition_inherit import finalize_draft_receipt

            finalize_draft_receipt(s, ctx, command, product, payload, subject, r)
        if command.operation in {
            "change.impact.compute",
            "change.order.prepare",
            "change.order.approve",
            "change.implementation.record",
            "change.effectivity.record",
            "change.verification.record",
            "change.close",
        }:
            from pdos_next.change_publication_finalization import finalize

            finalize(s, ctx, command, subject)
        return receipt_view(r)
    finally:
        if command.operation in {
            "change.impact.compute",
            "change.order.prepare",
            "change.order.approve",
            "change.implementation.record",
            "change.effectivity.record",
            "change.verification.record",
            "change.close",
        }:
            from pdos_next.change_publication_finalization import discard

            discard(subject)
