"""A closed server registry; neither model nor client can choose their write tier."""

CATEGORY_OPERATIONS = frozenset(
    {
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
        "ai.budget.configure",
        "evidence.artifact.register",
        "evidence.original.withdraw",
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
    }
)

T2_OPERATIONS = frozenset(
    {
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
    }
)

T1_OPERATIONS = frozenset(
    {
        "field.feedback.locate",
        "field.feedback.action.record",
        "field.feedback.followup.link",
        "work.risk.followup.record",
        "ai.automation.activate",
        "ai.automation.pause",
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
    if operation in {
        "field.feedback.create",
        "field.feedback.locate",
        "field.feedback.action.record",
        "field.feedback.followup.link",
    }:
        from pdos_next.domain.field_feedback import service as field_service

        return field_service
    if operation in {"knowledge.candidate.create", "knowledge.rule.publish"}:
        from pdos_next.domain.knowledge import service as knowledge_service

        return knowledge_service
    if operation == "work.risk.followup.record":
        from pdos_next.domain.project_risk import service as risk_followup_service

        return risk_followup_service
    if operation == "work.external_wait.record":
        from pdos_next.domain.external_wait import service as external_wait_service

        return external_wait_service
    if operation == "work.commitment.review":
        from pdos_next.domain.work_fulfillment import service as fulfillment_service

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
        from pdos_next.domain.work_management import service as work_service

        return work_service
    if operation in {"release.exception.decide", "release.exception.withdraw"}:
        from pdos_next.domain.release_exceptions import service as release_exception_service

        return release_exception_service
    if operation in {"integration.handoff.authorize", "integration.receipt.record"}:
        from pdos_next.domain.external_handoff import service as external_handoff_service

        return external_handoff_service
    if operation in {
        "release.package.assemble",
        "release.engineering.approve",
        "release.manufacturing.approve",
    }:
        from pdos_next.domain.release import service as release_service

        return release_service
    if operation in {"npi.pilot.create", "npi.pilot.result.record"}:
        from pdos_next.domain.manufacturing_trials import native_service

        return native_service
    if operation in {"mcp.connector.allow", "mcp.tool.grant"}:
        from pdos_next.agent_kernel import mcp_management

        return mcp_management
    if operation in {"ai.skill.qualify", "ai.skill.review.record"}:
        from pdos_next.agent_kernel import skill_qualification

        return skill_qualification
    if operation == "ai.budget.configure":
        from pdos_next.agent_kernel import budget_management

        return budget_management
    if operation == "ai.skill.enable":
        from pdos_next.agent_kernel import skill_management

        return skill_management
    if operation == "platform.link.create":
        from pdos_next.domain.products import platforms

        return platforms
    if operation == "product.definition.item.patch":
        from pdos_next.domain.products import definition_items

        return definition_items
    if operation == "research.snapshot.register":
        from pdos_next.agent_kernel import snapshot_command

        return snapshot_command
    if operation in {"evidence.link.create", "evidence.claim.withdraw", "proposal.share"}:
        from pdos_next.domain.preproject import evidence_service

        return evidence_service
    if operation in {
        "category.knowledge.add",
        "category.knowledge.withdraw",
        "category.knowledge.promote",
        "category.parameter.publish",
    }:
        from pdos_next.domain.preproject import category_service

        return category_service
    if operation == "evidence.claim.record":
        from pdos_next.agent_kernel import claim_candidate

        return claim_candidate
    if operation == "model.configuration.save":
        from pdos_next.model_configuration import commands

        return commands
    if operation.startswith("proposal."):
        from pdos_next.domain.preproject import service

        return service
    if operation == "ai.run.revert":
        from pdos_next import run_revert

        return run_revert
    if operation in {
        "change.order.prepare",
        "change.order.approve",
        "change.verification.record",
        "change.close",
        "change.implementation.record",
        "change.effectivity.record",
    }:
        from pdos_next import change_order_integration

        return change_order_integration
    if operation == "change.selection.decide":
        from pdos_next import change_selection_integration

        return change_selection_integration
    if operation == "npi.manufacturing_baseline.publish":
        from pdos_next.domain.manufacturing_baseline import publication_service

        return publication_service
    if operation in {
        "npi.work_instruction.record",
        "npi.control_plan.record",
        "npi.manufacturing_baseline.record",
    }:
        from pdos_next.domain.manufacturing_baseline import service

        return service
    if operation in {"quality.capa.observation.record", "quality.capa.verification.review"}:
        from pdos_next.domain.capa_effectiveness import fact_service

        return fact_service
    if operation == "quality.capa.verification.candidate.record":
        from pdos_next.domain.capa_effectiveness import service

        return service
    if operation in {"quality.issue.root_cause.decide", "quality.capa.actions.complete"}:
        from pdos_next.domain.quality_followup import service

        return service
    if operation == "quality.capa.followup.link":
        from pdos_next.domain.capa_verification import commands

        return commands
    if operation in {
        "quality.issue.create",
        "quality.issue.merge",
        "quality.issue.triage",
        "quality.issue.containment.record",
        "quality.capa.draft",
    }:
        from pdos_next.domain.quality_execution import service

        return service
    if operation in {"change.request.create", "change.impact.compute"}:
        from pdos_next.domain.change_execution import service

        return service
    if operation in {
        "test.results.import",
        "test.result.compute",
        "test.run.review",
        "test.disposition.decide",
    }:
        from pdos_next.domain.verification_results import service

        return service
    if operation in {"test.run.plan", "verification.schedule.promise", "test.run.start"}:
        from pdos_next.domain.verification_launch import service

        return service
    if operation == "build.sample.readiness.record":
        from pdos_next.domain.sample_handoff import service

        return service
    if operation in {
        "verification.actual_method.prepare",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "verification.handoff.return",
    }:
        from pdos_next.domain.verification_handoff import service

        return service
    if operation in T2_OPERATIONS or operation == "build.start":
        from pdos_next.domain.build_start import service

        return service
    if operation in {
        "verification.request.create",
        "verification.method.prepare",
        "verification.schedule.propose",
    }:
        from pdos_next.domain.verification_front import service

        return service
    if operation == "evidence.lifecycle.upload.abandon":
        from pdos_next import upload_lifecycle

        return upload_lifecycle
    if operation.startswith("evidence.lifecycle."):
        from pdos_next.domain.original_lifecycle_execution import service

        return service
    if operation == "evidence.original.withdraw":
        from pdos_next import original_actions

        return original_actions
    if operation == "verification.preparation.record":
        from pdos_next.domain.verification_execution import service

        return service
    if operation in {"cost.inputs.record", "cost.estimate.compute"}:
        from pdos_next.domain.cost_execution import service

        return service
    if operation in {"supply.snapshot.record", "supply.kit.compute"}:
        from pdos_next.domain.supply_execution import service

        return service
    if operation in {
        "build.configuration.actual.record",
        "build.output.record",
        "build.sample.allocate",
    }:
        from pdos_next.domain.build_execution import service

        return service
    if operation in {
        "engineering.bom.revise",
        "engineering.configuration.create",
        "npi.process.revise",
    }:
        from pdos_next.domain.configurations import service

        return service
    if operation in {"build.create", "build.readiness.compute"}:
        from pdos_next.domain.builds import service

        return service
    if operation in {"product.variant.derive", "product.variant.rebase"}:
        from pdos_next.domain.products import variants

        return variants
    if operation in {"work.plan.propose", "work.plan.apply"}:
        from pdos_next.domain.projects import service

        return service
    if operation == "ai.model_call.reconcile":
        from pdos_next.model_gateway import reconciliation

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
