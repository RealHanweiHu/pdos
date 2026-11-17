"""A closed server registry; neither model nor client can choose their write tier."""

CATEGORY_OPERATIONS = frozenset(
    {
        "work.framework.draft",
        "work.framework.publish",
        "embedding.profile.save",
        "embedding.call.reconcile",
        "field.feedback.create",
        "field.feedback.locate",
        "field.feedback.action.record",
        "field.feedback.followup.link",
        "knowledge.candidate.create",
        "ai.automation.draft.save",
        "ai.automation.activate",
        "ai.automation.pause",
        "mcp.connector.allow",
        "mcp.tool.grant",
        "model.configuration.save",
        "ai.skill.qualify",
        "ai.skill.enable",
        "ai.skill.review.record",
        "ai.skill.spot_check.record",
        "ai.skill.eval_set.register",
        "ai.budget.configure",
        "evidence.artifact.register",
        "evidence.original.withdraw",
        "evidence.source.withdraw",
        "evidence.lifecycle.upload.abandon",
        "evidence.lifecycle.quarantine",
        "evidence.lifecycle.restore",
        "evidence.lifecycle.cancel",
        "evidence.lifecycle.protection.record",
        "ai.run.revert",
        "proposal.create",
        "proposal.item.patch",
        "proposal.question.create",
        "proposal.g0.submit",
        "proposal.g0.decide",
        "category.knowledge.add",
        "category.knowledge.withdraw",
        "category.knowledge.promote",
        "category.parameter.publish",
        "evidence.claim.record",
        "research.snapshot.register",
        "evidence.link.create",
        "evidence.claim.withdraw",
        "proposal.share",
        "scope_note.save",
        "scope_note.retire",
        "scope_note.observation.record",
    }
)

T2_OPERATIONS = frozenset(
    {
        "work.framework.publish",
        "work.baseline.approve",
        "work.stage.decide",
        "knowledge.rule.publish",
        "integration.handoff.authorize",
        "release.exception.decide",
        "release.exception.withdraw",
        "release.engineering.approve",
        "release.manufacturing.approve",
        "ai.skill.qualify",
        "mcp.connector.allow",
        "change.order.approve",
        "change.verification.record",
        "change.close",
        "proposal.g0.decide",
        "change.selection.decide",
        "build.engineering.authorize",
        "build.manufacturing.authorize",
        "test.run.review",
        "test.disposition.decide",
        "npi.manufacturing_baseline.publish",
        "quality.issue.root_cause.decide",
        "quality.capa.verification.review",
        "npi.fixture.accept",
        "evidence.source.withdraw",
        "supply.alternate.approve",
        "quality.capa.effectiveness.decide",
        "customer.acceptance.record",
    }
)

T1_OPERATIONS = frozenset(
    {
        "work.framework.draft",
        "embedding.profile.save",
        "embedding.call.reconcile",
        "field.feedback.locate",
        "field.feedback.action.record",
        "field.feedback.followup.link",
        "work.risk.followup.record",
        "ai.automation.activate",
        "ai.automation.pause",
        "work.stage.milestone.bind",
        "work.stage.adopt",
        "work.stage.review.submit",
        "work.task.assign",
        "work.task.accept",
        "work.commitment.accept",
        "work.commitment.review",
        "work.task.start",
        "work.task.submit",
        "work.task.review",
        "work.status_update.create",
        "platform.link.create",
        "mcp.tool.grant",
        "ai.skill.enable",
        "ai.skill.review.record",
        "ai.skill.spot_check.record",
        "ai.skill.eval_set.register",
        "ai.budget.configure",
        "model.configuration.save",
        "ai.run.revert",
        "proposal.create",
        "proposal.question.create",
        "proposal.g0.submit",
        "proposal.share",
        "evidence.claim.withdraw",
        "category.knowledge.withdraw",
        "category.knowledge.promote",
        "category.parameter.publish",
        "change.order.prepare",
        "change.implementation.record",
        "change.effectivity.record",
        "evidence.original.withdraw",
        "evidence.lifecycle.upload.abandon",
        "evidence.lifecycle.quarantine",
        "evidence.lifecycle.restore",
        "evidence.lifecycle.cancel",
        "evidence.lifecycle.protection.record",
        "product.variant.derive",
        "product.variant.rebase",
        "work.plan.apply",
        "ai.model_call.reconcile",
        "engineering.bom.revise",
        "engineering.configuration.create",
        "npi.process.revise",
        "npi.work_instruction.record",
        "npi.control_plan.record",
        "npi.manufacturing_baseline.record",
        "npi.pilot.create",
        "npi.pilot.result.record",
        "build.create",
        "build.configuration.actual.record",
        "build.output.record",
        "build.sample.allocate",
        "supply.snapshot.record",
        "cost.inputs.record",
        "verification.preparation.record",
        "verification.method.prepare",
        "build.start",
        "build.sample.readiness.record",
        "verification.actual_method.prepare",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "verification.handoff.return",
        "test.run.plan",
        "verification.schedule.promise",
        "test.run.start",
        "test.results.import",
        "quality.issue.merge",
        "quality.issue.triage",
        "quality.issue.containment.record",
        "quality.capa.actions.complete",
        "quality.capa.followup.link",
        "quality.capa.verification.candidate.record",
        "quality.capa.observation.record",
        "product.definition.update",
        "engineering.interface.update",
        "npi.tooltrial.create",
        "scope_note.save",
        "scope_note.retire",
    }
)

# T0 is registered explicitly, exactly like T1 and T2: the three sets partition
# PAYLOADS. An unclassified command is refused by tier_of, never treated as T0.
T0_OPERATIONS = frozenset(
    {
        "field.feedback.create",
        "knowledge.candidate.create",
        "ai.automation.draft.save",
        "work.task.create",
        "work.external_wait.record",
        "work.forecast.refresh",
        "supply.commitment.record",
        "integration.receipt.record",
        "build.readiness.compute",
        "category.knowledge.add",
        "change.impact.compute",
        "change.request.create",
        "cost.estimate.compute",
        "evidence.artifact.register",
        "evidence.claim.record",
        "evidence.link.create",
        "product.definition.draft",
        "product.definition.item.patch",
        "proposal.item.patch",
        "quality.capa.draft",
        "quality.issue.create",
        "research.snapshot.register",
        "supply.kit.compute",
        "test.result.compute",
        "verification.request.create",
        "verification.schedule.propose",
        "release.package.assemble",
        "work.plan.propose",
        # P121 第 4 项: only an unverified observation or an evidence link; without a
        # qualification the registered graph prepares it for a person (T1 handling).
        "scope_note.observation.record",
    }
)


def tier_of(operation):
    """Resolve the registered write tier; an unregistered command never defaults to T0."""
    if operation in T2_OPERATIONS:
        return "T2"
    if operation in T1_OPERATIONS:
        return "T1"
    if operation in T0_OPERATIONS:
        return "T0"
    from pdos_next.errors import DomainError

    raise DomainError(
        "WRITE_TIER_UNREGISTERED",
        "该命令未登记写入档位。",
        403,
        detail={"operation": operation},
    )


# These adapters prepare once in each call and bind the actual common proof.
# No handler/client can opt itself into these hooks through a payload flag.
PHASED_MATERIAL_OPERATIONS = frozenset(
    {
        "integration.handoff.authorize",
        "release.exception.decide",
        "release.exception.withdraw",
        "npi.work_instruction.record",
        "npi.control_plan.record",
        "npi.manufacturing_baseline.record",
        "npi.manufacturing_baseline.publish",
        "change.order.prepare",
        "release.engineering.approve",
        "release.manufacturing.approve",
        "npi.pilot.create",
        "npi.pilot.result.record",
        "change.order.approve",
        "change.verification.record",
        "change.close",
        "change.implementation.record",
        "change.effectivity.record",
        "change.selection.decide",
        "quality.capa.followup.link",
        "quality.capa.verification.candidate.record",
        "quality.capa.observation.record",
        "quality.capa.verification.review",
    }
)
LIVE_CONSUMPTION_OPERATIONS = PHASED_MATERIAL_OPERATIONS - {"quality.capa.followup.link"}


def handler(operation):
    if operation in {"work.framework.draft", "work.framework.publish"}:
        from pdos_next.domain.projects.npi import catalog

        return catalog
    if operation.startswith("scope_note."):
        from pdos_next.domain.knowledge.scope_notes import service as scope_notes

        return scope_notes
    if operation in {"embedding.profile.save", "embedding.call.reconcile"}:
        from pdos_next.agent.enterprise_search import embedding_profiles

        return embedding_profiles
    if operation in {"work.stage.milestone.bind", "work.stage.adopt", "work.baseline.approve", "work.stage.review.submit", "work.stage.decide"}:
        from pdos_next.domain.projects.governance import service
        return service
    if operation in {
        "field.feedback.create",
        "field.feedback.locate",
        "field.feedback.action.record",
        "field.feedback.followup.link",
    }:
        from pdos_next.domain.quality.field_feedback import service as field_service

        return field_service
    if operation in {"knowledge.candidate.create", "knowledge.rule.publish"}:
        from pdos_next.domain.knowledge import service as knowledge_service

        return knowledge_service
    if operation == "work.risk.followup.record":
        from pdos_next.domain.projects.risk import service as risk_followup_service

        return risk_followup_service
    if operation == "work.external_wait.record":
        from pdos_next.domain.projects.external_wait import service as external_wait_service

        return external_wait_service
    if operation == "work.forecast.refresh":
        from pdos_next.domain.projects.forecast_refresh import service as forecast_service

        return forecast_service
    if operation == "supply.commitment.record":
        from pdos_next.domain.manufacturing.supply_commitments import (
            service as supply_commitment_service,
        )

        return supply_commitment_service
    if operation == "work.commitment.review":
        from pdos_next.domain.projects.fulfillment import service as fulfillment_service

        return fulfillment_service
    if operation in {"ai.automation.draft.save", "ai.automation.activate", "ai.automation.pause"}:
        from pdos_next.domain.automations import service as automation_service

        return automation_service
    if operation in {
        "work.task.create",
        "work.task.assign",
        "work.task.accept",
        "work.commitment.accept",
        "work.task.start",
        "work.task.submit",
        "work.task.review",
        "work.status_update.create",
    }:
        from pdos_next.domain.projects.work import service as work_service

        return work_service
    if operation in {"release.exception.decide", "release.exception.withdraw"}:
        from pdos_next.domain.manufacturing.release.exceptions import (
            service as release_exception_service,
        )

        return release_exception_service
    if operation in {"integration.handoff.authorize", "integration.receipt.record"}:
        from pdos_next.domain.manufacturing.external_handoff import (
            service as external_handoff_service,
        )

        return external_handoff_service
    if operation in {
        "release.package.assemble",
        "release.engineering.approve",
        "release.manufacturing.approve",
    }:
        from pdos_next.domain.manufacturing.release import service as release_service

        return release_service
    if operation in {"npi.pilot.create", "npi.pilot.result.record"}:
        from pdos_next.domain.manufacturing.trials import native_service

        return native_service
    if operation in {"mcp.connector.allow", "mcp.tool.grant"}:
        from pdos_next.agent.kernel import mcp_management

        return mcp_management
    if operation in {"ai.skill.qualify", "ai.skill.review.record"}:
        from pdos_next.agent.kernel import skill_qualification

        return skill_qualification
    if operation in {"ai.skill.spot_check.record", "ai.skill.eval_set.register"}:
        from pdos_next.agent.kernel import skill_quality_records

        return skill_quality_records
    if operation == "ai.budget.configure":
        from pdos_next.agent.kernel import budget_management

        return budget_management
    if operation == "ai.skill.enable":
        from pdos_next.agent.kernel import skill_management

        return skill_management
    if operation == "platform.link.create":
        from pdos_next.domain.categories.products import platforms

        return platforms
    if operation == "quality.capa.effectiveness.decide":
        from pdos_next.domain.quality.capa_effectiveness import service as effectiveness

        return effectiveness
    if operation == "evidence.source.withdraw":
        from pdos_next.originals import source_withdraw

        return source_withdraw
    if operation == "npi.fixture.accept":
        from pdos_next.domain.manufacturing.fixture_acceptance import service as fixture_service

        return fixture_service
    if operation == "supply.alternate.approve":
        from pdos_next.domain.manufacturing.alternate_approvals import service as alternate_approval

        return alternate_approval
    if operation == "customer.acceptance.record":
        from pdos_next.domain.delivery.customer_acceptance import service as customer_acceptance

        return customer_acceptance
    if operation == "npi.tooltrial.create":
        from pdos_next.domain.manufacturing.tool_trials import service as tool_trial

        return tool_trial
    if operation == "engineering.interface.update":
        from pdos_next.domain.engineering.interfaces import service as interface_service

        return interface_service
    if operation == "product.definition.update":
        from pdos_next.domain.categories.products import definition_update

        return definition_update
    if operation == "product.definition.item.patch":
        from pdos_next.domain.categories.products import definition_items

        return definition_items
    if operation == "research.snapshot.register":
        from pdos_next.agent.kernel import snapshot_command

        return snapshot_command
    if operation in {"evidence.link.create", "evidence.claim.withdraw", "proposal.share"}:
        from pdos_next.domain.categories.preproject import evidence_service

        return evidence_service
    if operation in {
        "category.knowledge.add",
        "category.knowledge.withdraw",
        "category.knowledge.promote",
        "category.parameter.publish",
    }:
        from pdos_next.domain.categories.preproject import category_service

        return category_service
    if operation == "evidence.claim.record":
        from pdos_next.agent.kernel import claim_candidate

        return claim_candidate
    if operation == "model.configuration.save":
        from pdos_next.agent.model_configuration import commands

        return commands
    if operation.startswith("proposal."):
        from pdos_next.domain.categories.preproject import service

        return service
    if operation == "ai.run.revert":
        from pdos_next.core import run_revert

        return run_revert
    if operation in {
        "change.order.prepare",
        "change.order.approve",
        "change.verification.record",
        "change.close",
        "change.implementation.record",
        "change.effectivity.record",
    }:
        from pdos_next.domain.change import order_integration as change_order_integration

        return change_order_integration
    if operation == "change.selection.decide":
        from pdos_next.domain.change import selection_integration as change_selection_integration

        return change_selection_integration
    if operation == "npi.manufacturing_baseline.publish":
        from pdos_next.domain.manufacturing.baseline import publication_service

        return publication_service
    if operation in {
        "npi.work_instruction.record",
        "npi.control_plan.record",
        "npi.manufacturing_baseline.record",
    }:
        from pdos_next.domain.manufacturing.baseline import service

        return service
    if operation in {"quality.capa.observation.record", "quality.capa.verification.review"}:
        from pdos_next.domain.quality.capa import fact_service

        return fact_service
    if operation == "quality.capa.verification.candidate.record":
        from pdos_next.domain.quality.capa import service

        return service
    if operation in {"quality.issue.root_cause.decide", "quality.capa.actions.complete"}:
        from pdos_next.domain.quality.followup import service

        return service
    if operation == "quality.capa.followup.link":
        from pdos_next.domain.quality.capa.verification import commands

        return commands
    if operation in {
        "quality.issue.create",
        "quality.issue.merge",
        "quality.issue.triage",
        "quality.issue.containment.record",
        "quality.capa.draft",
    }:
        from pdos_next.domain.quality.execution import service

        return service
    if operation in {"change.request.create", "change.impact.compute"}:
        from pdos_next.domain.change.execution import service

        return service
    if operation in {
        "test.results.import",
        "test.result.compute",
        "test.run.review",
        "test.disposition.decide",
    }:
        from pdos_next.domain.verification.results import service

        return service
    if operation in {"test.run.plan", "verification.schedule.promise", "test.run.start"}:
        from pdos_next.domain.verification.launch import service

        return service
    if operation == "build.sample.readiness.record":
        from pdos_next.domain.builds.sample_handoff import service

        return service
    if operation in {
        "verification.actual_method.prepare",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "verification.handoff.return",
    }:
        from pdos_next.domain.verification.handoff import service

        return service
    if operation in T2_OPERATIONS or operation == "build.start":
        from pdos_next.domain.builds.start import service

        return service
    if operation in {
        "verification.request.create",
        "verification.method.prepare",
        "verification.schedule.propose",
    }:
        from pdos_next.domain.verification.preparation import service

        return service
    if operation == "evidence.lifecycle.upload.abandon":
        from pdos_next.originals import upload_lifecycle

        return upload_lifecycle
    if operation.startswith("evidence.lifecycle."):
        from pdos_next.originals.lifecycle.execution import service

        return service
    if operation == "evidence.original.withdraw":
        from pdos_next.originals import actions as original_actions

        return original_actions
    if operation == "verification.preparation.record":
        from pdos_next.domain.verification.execution import service

        return service
    if operation in {"cost.inputs.record", "cost.estimate.compute"}:
        from pdos_next.domain.manufacturing.cost_execution import service

        return service
    if operation in {"supply.snapshot.record", "supply.kit.compute"}:
        from pdos_next.domain.manufacturing.supply_execution import service

        return service
    if operation in {
        "build.configuration.actual.record",
        "build.output.record",
        "build.sample.allocate",
    }:
        from pdos_next.domain.builds.execution import service

        return service
    if operation in {
        "engineering.bom.revise",
        "engineering.configuration.create",
        "npi.process.revise",
    }:
        from pdos_next.domain.builds.configurations import service

        return service
    if operation in {"build.create", "build.readiness.compute"}:
        from pdos_next.domain.builds import service

        return service
    if operation in {"product.variant.derive", "product.variant.rebase"}:
        from pdos_next.domain.categories.products import variants

        return variants
    if operation in {"work.plan.propose", "work.plan.apply"}:
        from pdos_next.domain.projects import service

        return service
    if operation == "ai.model_call.reconcile":
        from pdos_next.agent.model_gateway import reconciliation

        return reconciliation
    return None


def reviewed_view(module, s, ctx, command, product, payload):
    if command.operation in LIVE_CONSUMPTION_OPERATIONS:
        return module.preview_view(s, ctx, command, product, payload)
    if command.operation == "ai.model_call.reconcile":
        before = module.preview(s, ctx, product.id, payload.call_id)
        usage = payload.usage.model_dump(mode="json") if payload.usage else None
        return {
            "before": before,
            "after": {
                "resolution": payload.resolution,
                "usage": usage,
                "charged_tokens": usage["input_tokens"] + usage["output_tokens"]
                if usage
                else before["charged_tokens"],
                "held_tokens": 0 if usage else before["held_tokens"],
                "request_id": payload.request_id or before["request_id"],
                "reason_code": payload.reason_code,
                "evidence_ref": payload.evidence_ref,
            },
            "effect": "只核对原调用费用；保留模型结果未知，不重发、不恢复运行或授予资格。",
        }
    return module.preview_view(s, ctx, command, product, payload)
