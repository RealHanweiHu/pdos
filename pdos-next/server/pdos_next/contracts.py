from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel


class SourceRead(StrictModel):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)


class Command(StrictModel):
    command_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=160)
    operation: str = Field(min_length=1, max_length=80)
    category_id: UUID
    product_id: UUID | None = None
    expected_revision: int = Field(ge=1)
    source_read_set: list[SourceRead] = Field(default_factory=list)
    payload: dict


class ArtifactPayload(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    visibility: Literal["private", "category", "audience"] = "private"
    source_label: str = Field(min_length=1, max_length=200)

    @field_validator("content")
    @classmethod
    def safe_text(cls, value):
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("UTF-8 text required") from exc
        if "\x00" in value or size > 200_000 or not value.strip():
            raise ValueError("Nonempty UTF-8 text under 200KB required")
        return value


class ClaimPayload(StrictModel):
    artifact_id: UUID
    line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)
    statement: str = Field(min_length=1, max_length=4000)
    nature: Literal["observed", "extracted", "inferred"] = "extracted"
    availability: Literal["known", "unknown", "conflicted"] = "known"
    visibility: Literal["private", "category", "audience"] = "private"
    prepared_event_id: UUID | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class RevertPayload(StrictModel):
    receipt_id: UUID | None = None
    run_id: UUID | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def exact_target(self):
        if (self.receipt_id is None) == (self.run_id is None):
            raise ValueError("Choose exactly one receipt or entire run")
        return self


class OriginalScanInput(StrictModel):
    expected_epoch: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)


class OriginalWithdrawPayload(StrictModel):
    original_id: UUID
    expected_epoch: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class UploadAbandonPayload(StrictModel):
    object_id: UUID
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=4, max_length=2000)
    confirmation_token: str | None = Field(default=None, max_length=256)


PAYLOADS = {
    "evidence.lifecycle.upload.abandon": UploadAbandonPayload,
    "evidence.original.withdraw": OriginalWithdrawPayload,
    "evidence.artifact.register": ArtifactPayload,
    "evidence.claim.record": ClaimPayload,
    "ai.run.revert": RevertPayload,
}

from pdos_next.domain.preproject.schemas import PAYLOADS as PREPROJECT_PAYLOADS  # noqa: E402

PAYLOADS.update(PREPROJECT_PAYLOADS)

from pdos_next.domain.preproject.category_schemas import (  # noqa: E402
    PAYLOADS as CATEGORY_MATERIAL_PAYLOADS,
)

PAYLOADS.update(CATEGORY_MATERIAL_PAYLOADS)

from pdos_next.domain.preproject.evidence_schemas import (  # noqa: E402
    PAYLOADS as PREPROJECT_EVIDENCE_PAYLOADS,
)

PAYLOADS.update(PREPROJECT_EVIDENCE_PAYLOADS)
ClaimPayload = PAYLOADS["evidence.claim.record"]

from pdos_next.agent_kernel.snapshot_command import SnapshotRegister  # noqa: E402

PAYLOADS["research.snapshot.register"] = SnapshotRegister

from pdos_next.model_configuration.commands import SavePayload  # noqa: E402

PAYLOADS["model.configuration.save"] = SavePayload

from pdos_next.agent_kernel.skill_management import EnableSkill  # noqa: E402

PAYLOADS["ai.skill.enable"] = EnableSkill

from pdos_next.agent_kernel.mcp_management import AllowConnector, GrantTool  # noqa: E402
from pdos_next.agent_kernel.skill_qualification import QualifySkill, RecordReviews  # noqa: E402

PAYLOADS["mcp.connector.allow"] = AllowConnector
PAYLOADS["mcp.tool.grant"] = GrantTool

PAYLOADS["ai.skill.qualify"] = QualifySkill
PAYLOADS["ai.skill.review.record"] = RecordReviews

from pdos_next.agent_kernel.budget_management import ConfigureBudget  # noqa: E402

PAYLOADS["ai.budget.configure"] = ConfigureBudget


class ProductInput(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    purpose: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class UploadInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=200)
    source_label: str = Field(min_length=1, max_length=200)
    visibility: Literal["private", "category", "audience"] = "private"
    content_base64: str = Field(min_length=4, max_length=11_184_812)
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_revision: int = Field(ge=1)


class ResumeInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


from pdos_next.schemas.products.definitions import DefinitionDraftPayload  # noqa: E402

PAYLOADS["product.definition.draft"] = DefinitionDraftPayload

from pdos_next.domain.projects.schemas import (  # noqa: E402
    PlanApplyPayload,
    PlanProposePayload,
)
from pdos_next.model_gateway.reconciliation_schema import ReconciliationPayload  # noqa: E402
from pdos_next.schemas.products.variants import (  # noqa: E402
    VariantDerivePayload,
    VariantRebasePayload,
)

PAYLOADS.update(
    {
        "product.variant.derive": VariantDerivePayload,
        "product.variant.rebase": VariantRebasePayload,
        "work.plan.propose": PlanProposePayload,
        "work.plan.apply": PlanApplyPayload,
        "ai.model_call.reconcile": ReconciliationPayload,
    }
)

from pdos_next.domain.builds.schemas import BuildCreatePayload, BuildReadinessPayload  # noqa: E402
from pdos_next.domain.configurations.schemas import (  # noqa: E402
    EngineeringBomRevisePayload,
    EngineeringConfigurationCreatePayload,
    NpiProcessRevisePayload,
)

PAYLOADS.update(
    {
        "engineering.bom.revise": EngineeringBomRevisePayload,
        "engineering.configuration.create": EngineeringConfigurationCreatePayload,
        "npi.process.revise": NpiProcessRevisePayload,
        "build.create": BuildCreatePayload,
        "build.readiness.compute": BuildReadinessPayload,
    }
)

from pdos_next.domain.build_execution.schemas import (  # noqa: E402
    ActualConfigurationPayload,
    OutputPayload,
    SampleAllocatePayload,
)

PAYLOADS.update(
    {
        "build.configuration.actual.record": ActualConfigurationPayload,
        "build.output.record": OutputPayload,
        "build.sample.allocate": SampleAllocatePayload,
    }
)

from pdos_next.domain.supply_execution.schemas import (  # noqa: E402
    KitComputePayload,
    SnapshotRecordPayload,
)

# Manual source snapshot confirmation is an auxiliary operation; canonical kit stays T0.
PAYLOADS.update(
    {
        "supply.snapshot.record": SnapshotRecordPayload,
        "supply.kit.compute": KitComputePayload,
    }
)

from pdos_next.domain.cost_execution.schemas import (  # noqa: E402
    EstimateComputePayload,
    InputsRecordPayload,
)

PAYLOADS.update(
    {
        "cost.inputs.record": InputsRecordPayload,
        "cost.estimate.compute": EstimateComputePayload,
    }
)

from pdos_next.domain.verification_execution.schemas import (  # noqa: E402
    PreparationRecordPayload,
)

# Human preparation records do not grant professional or canonical execution qualification.
PAYLOADS["verification.preparation.record"] = PreparationRecordPayload

from pdos_next.domain.verification_front.schemas import (  # noqa: E402
    MethodPreparePayload,
    RequestCreatePayload,
    ScheduleProposePayload,
)

PAYLOADS.update(
    {
        "verification.request.create": RequestCreatePayload,
        "verification.method.prepare": MethodPreparePayload,
        "verification.schedule.propose": ScheduleProposePayload,
    }
)

from pdos_next.domain.original_lifecycle_execution.schemas import (  # noqa: E402
    LifecycleCancelPayload,
    LifecycleCommandPayload,
    LifecycleProtectionPayload,
)

PAYLOADS.update(
    {
        "evidence.lifecycle.quarantine": LifecycleCommandPayload,
        "evidence.lifecycle.restore": LifecycleCommandPayload,
        "evidence.lifecycle.cancel": LifecycleCancelPayload,
        "evidence.lifecycle.protection.record": LifecycleProtectionPayload,
    }
)

from pdos_next.domain.build_start.schemas import (  # noqa: E402
    BuildAuthorizationPayload,
    BuildStartPayload,
)

PAYLOADS.update(
    {
        "build.engineering.authorize": BuildAuthorizationPayload,
        "build.manufacturing.authorize": BuildAuthorizationPayload,
        "build.start": BuildStartPayload,
    }
)

from pdos_next.domain.sample_handoff.schemas import SampleReadinessPayload  # noqa: E402
from pdos_next.domain.verification_handoff.schemas import (  # noqa: E402
    AcceptPayload,
    ActualMethodPreparePayload,
    OfferPayload,
    ReturnPayload,
)

PAYLOADS.update(
    {
        "build.sample.readiness.record": SampleReadinessPayload,
        "verification.actual_method.prepare": ActualMethodPreparePayload,
        "verification.handoff.offer": OfferPayload,
        "verification.handoff.accept": AcceptPayload,
        "verification.handoff.return": ReturnPayload,
    }
)

from pdos_next.domain.verification_launch.schemas import (  # noqa: E402
    PlanPayload as TestPlanPayload,
)
from pdos_next.domain.verification_launch.schemas import (  # noqa: E402
    PromisePayload as TestPromisePayload,
)
from pdos_next.domain.verification_launch.schemas import (  # noqa: E402
    StartPayload as TestStartPayload,
)

PAYLOADS.update(
    {
        "test.run.plan": TestPlanPayload,
        "verification.schedule.promise": TestPromisePayload,
        "test.run.start": TestStartPayload,
    }
)

from pdos_next.domain.verification_results.schemas import (  # noqa: E402
    ComputePayload as TestComputePayload,
)
from pdos_next.domain.verification_results.schemas import (  # noqa: E402
    DispositionPayload as TestDispositionPayload,
)
from pdos_next.domain.verification_results.schemas import (  # noqa: E402
    ImportPayload as TestImportPayload,
)
from pdos_next.domain.verification_results.schemas import (  # noqa: E402
    ReviewPayload as TestReviewPayload,
)

PAYLOADS.update(
    {
        "test.results.import": TestImportPayload,
        "test.result.compute": TestComputePayload,
        "test.run.review": TestReviewPayload,
        "test.disposition.decide": TestDispositionPayload,
    }
)

from pdos_next.domain.change_execution.schemas import (  # noqa: E402
    ChangeCreatePayload,
    ImpactComputePayload,
)
from pdos_next.domain.quality_execution.schemas import (  # noqa: E402
    CapaDraftPayload,
    ContainmentPayload,
    IssueCreatePayload,
    IssueMergePayload,
    IssueTriagePayload,
)

PAYLOADS.update(
    {
        "quality.issue.create": IssueCreatePayload,
        "quality.issue.merge": IssueMergePayload,
        "quality.issue.triage": IssueTriagePayload,
        "quality.issue.containment.record": ContainmentPayload,
        "quality.capa.draft": CapaDraftPayload,
        "change.request.create": ChangeCreatePayload,
        "change.impact.compute": ImpactComputePayload,
    }
)


from pdos_next.domain.capa_verification.schemas import FollowupLinkPayload  # noqa: E402
from pdos_next.domain.quality_followup.schemas import (  # noqa: E402
    ActionsCompletePayload,
    RootCausePayload,
)

PAYLOADS.update(
    {
        "quality.issue.root_cause.decide": RootCausePayload,
        "quality.capa.actions.complete": ActionsCompletePayload,
        "quality.capa.followup.link": FollowupLinkPayload,
    }
)

from pdos_next.domain.capa_effectiveness.candidate_commands import (  # noqa: E402
    CandidateRecordPayload,
)

PAYLOADS["quality.capa.verification.candidate.record"] = CandidateRecordPayload

from pdos_next.domain.capa_effectiveness.fact_commands import (  # noqa: E402
    NamedReviewPayload,
    ObservationPayload,
)

PAYLOADS.update(
    {
        "quality.capa.observation.record": ObservationPayload,
        "quality.capa.verification.review": NamedReviewPayload,
    }
)


# Canonical Change operations; selection is an explicit auxiliary proposal.
# The host-only policy publisher is deliberately absent from PAYLOADS.
from pdos_next.change_command_schemas import (  # noqa: E402
    ImplementationPayload,
    OrderApprovePayload,
    OrderPreparePayload,
)
from pdos_next.change_completion_schemas import (  # noqa: E402
    ClosePayload,
    EffectivityPayload,
    VerificationPayload,
)
from pdos_next.change_controlled_schemas import SelectionPayload  # noqa: E402

PAYLOADS.update(
    {
        "change.order.prepare": OrderPreparePayload,
        "change.order.approve": OrderApprovePayload,
        "change.implementation.record": ImplementationPayload,
        "change.effectivity.record": EffectivityPayload,
        "change.verification.record": VerificationPayload,
        "change.close": ClosePayload,
        "change.selection.decide": SelectionPayload,
    }
)

from pdos_next.domain.manufacturing_baseline.schemas import (  # noqa: E402
    BaselinePayload,
    ControlPlanPayload,
    InstructionPayload,
)

PAYLOADS.update(
    {
        "npi.work_instruction.record": InstructionPayload,
        "npi.control_plan.record": ControlPlanPayload,
        "npi.manufacturing_baseline.record": BaselinePayload,
    }
)

from pdos_next.domain.manufacturing_baseline.publication_schemas import (  # noqa: E402
    OPERATION as MANUFACTURING_PUBLICATION_OPERATION,
)
from pdos_next.domain.manufacturing_baseline.publication_schemas import (  # noqa: E402
    PublishPayload as ManufacturingPublicationPayload,
)

PAYLOADS[MANUFACTURING_PUBLICATION_OPERATION] = ManufacturingPublicationPayload

from pdos_next.domain.manufacturing_trials.native_schemas import (  # noqa: E402
    PilotCreatePayload as NativePilotCreatePayload,
)
from pdos_next.domain.manufacturing_trials.native_schemas import (  # noqa: E402
    PilotResultPayload as NativePilotResultPayload,
)

PAYLOADS.update(
    {
        "npi.pilot.create": NativePilotCreatePayload,
        "npi.pilot.result.record": NativePilotResultPayload,
    }
)

from pdos_next.schemas.products.definition_items import DefinitionItemPatch  # noqa: E402

PAYLOADS["product.definition.item.patch"] = DefinitionItemPatch

from pdos_next.domain.products.platform_schemas import PlatformLinkInput  # noqa: E402

PAYLOADS["platform.link.create"] = PlatformLinkInput

from pdos_next.domain.release.schemas import PAYLOADS as RELEASE_PAYLOADS  # noqa: E402

PAYLOADS.update(RELEASE_PAYLOADS)

from pdos_next.domain.external_handoff.schemas import (  # noqa: E402
    AuthorizePayload as ExternalHandoffAuthorizePayload,
)
from pdos_next.domain.external_handoff.schemas import (  # noqa: E402
    ReceiptRecordPayload as ExternalReceiptRecordPayload,
)

PAYLOADS.update(
    {
        "integration.handoff.authorize": ExternalHandoffAuthorizePayload,
        "integration.receipt.record": ExternalReceiptRecordPayload,
    }
)

from pdos_next.domain.release_exceptions.schemas import (  # noqa: E402
    PAYLOADS as RELEASE_EXCEPTION_PAYLOADS,
)

PAYLOADS.update(RELEASE_EXCEPTION_PAYLOADS)

from pdos_next.domain.work_management.schemas import PAYLOADS as WORK_PAYLOADS  # noqa: E402

PAYLOADS.update(WORK_PAYLOADS)

from pdos_next.domain.external_wait.schemas import PAYLOADS as EXTERNAL_WAIT_PAYLOADS  # noqa: E402

PAYLOADS.update(EXTERNAL_WAIT_PAYLOADS)

from pdos_next.domain.automations.schemas import PAYLOADS as AUTOMATION_PAYLOADS  # noqa: E402

PAYLOADS.update(AUTOMATION_PAYLOADS)

from pdos_next.domain.work_fulfillment.schemas import PAYLOADS as FULFILLMENT_PAYLOADS  # noqa: E402

PAYLOADS.update(FULFILLMENT_PAYLOADS)

from pdos_next.domain.project_risk.schemas import PAYLOADS as RISK_FOLLOWUP_PAYLOADS  # noqa: E402

PAYLOADS.update(RISK_FOLLOWUP_PAYLOADS)

from pdos_next.domain.knowledge.schemas import PAYLOADS as KNOWLEDGE_PAYLOADS  # noqa: E402

PAYLOADS.update(KNOWLEDGE_PAYLOADS)

from pdos_next.domain.field_feedback.schemas import PAYLOADS as FIELD_PAYLOADS  # noqa: E402

PAYLOADS.update(FIELD_PAYLOADS)

from pdos_next.domain.project_governance.schemas import OPERATIONS as GOVERNANCE_OPERATIONS
PAYLOADS.update({op: value[0] for op, value in GOVERNANCE_OPERATIONS.items()})

from pdos_next.enterprise_search.embedding_schemas import (  # noqa: E402
    ReconcileEmbeddingCall,
    SaveEmbeddingProfile,
)

PAYLOADS.update({
    "embedding.profile.save": SaveEmbeddingProfile,
    "embedding.call.reconcile": ReconcileEmbeddingCall,
})
