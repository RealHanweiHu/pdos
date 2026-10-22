"""Explicit project activity subjects and minimal display projections.

This is a read catalogue, not an ACL or a writer. The query owner must retain
ordinary subject RLS and verify the actual Receipt/Outbox group. Each command's
primary receipt subject appears once; Current, capture and child rows do not.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from sqlalchemy import SQLColumnExpression, and_, case, exists, literal, or_, select

from pdos_next import (  # initialize the shared model registry before domain imports
    models as registered_models,  # noqa: F401
)
from pdos_next.change_controlled_store import ChangePolicyFact, ChangeSelectionFact
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot, SampleAllocation
from pdos_next.domain.build_operational_facts.models import BuildOperationalFact
from pdos_next.domain.build_start.models import BuildAuthorizationDecision, BuildStart
from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.domain.capa_effectiveness.fact_storage_models import (
    NamedReviewRecord,
    ObservationFact,
    RuleFact,
)
from pdos_next.domain.capa_verification.models import (
    CapaVerificationEvidence,
    RemediationLinkRecord,
)
from pdos_next.domain.change_coverage_owner.models import ChangeCoverageFact
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
from pdos_next.domain.cost_execution.models import CostEstimate, CostInputSnapshot
from pdos_next.domain.external_handoff.models import ExternalHandoffAuthorization, ExternalReceipt
from pdos_next.domain.external_wait.models import ExternalWaitVersion
from pdos_next.domain.manufacturing_baseline.models import PreparationVersion
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication,
)
from pdos_next.domain.manufacturing_trials.native_models import (
    NativePilotObservation,
    NativePilotRun,
)
from pdos_next.domain.preproject.models import ProposalDecision
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.project_risk.models import ProjectRiskFollowup
from pdos_next.domain.projects.models import PlanProposal, PlanRevision
from pdos_next.domain.quality_execution.models import QualityIssueVersion, QualityPolicyFact
from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage
from pdos_next.domain.release.policy_models import ReleasePolicyFact
from pdos_next.domain.release_exceptions.models import ReleaseExceptionDecision
from pdos_next.domain.sample_handoff.models import SampleReadinessFact
from pdos_next.domain.supply_execution.models import KitProjection, SupplySnapshot
from pdos_next.domain.test_resources.models import TestResourceFact
from pdos_next.domain.verification_execution.models import VerificationPreparation
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import ActualMethodBatch
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import TestResultProjection
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReview
from pdos_next.domain.work_management.models import (
    ProjectStatusUpdate,
    WorkCommitmentVersion,
    WorkTaskVersion,
)

SQLExpr = SQLColumnExpression[Any]


@dataclass(frozen=True)
class ActivitySource:
    model: type
    subject_kind: str
    operations: tuple[str, ...]
    view: str
    label: str
    # Called as predicate(source, tenant_id, product_id, project_id), using the
    # same unaliased model as columns/subject_id. None means model.project_id.
    project_predicate: Callable | None = None
    product_column: SQLExpr | None = None
    subject_id: SQLExpr | None = None
    subject_revision: SQLExpr | None = None
    columns: dict[str, SQLExpr] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "columns", MappingProxyType(dict(self.columns)))


def _build_readiness_project(source, tenant_id, product_id, project_id):
    return exists(
        select(literal(1))
        .select_from(Build)
        .where(
            Build.tenant_id == tenant_id,
            Build.product_id == product_id,
            Build.project_id == project_id,
            Build.id == source.model.build_id,
            Build.revision == source.model.build_revision,
        )
        .correlate(source.model, registered_models.Project)
    )


def _configuration_project(source, tenant_id, product_id, project_id):
    model = source.model
    planned_id, actual_id, actual_revision = (
        (
            Build.engineering_configuration_id,
            ActualConfiguration.actual_engineering_configuration_id,
            ActualConfiguration.actual_engineering_revision,
        )
        if model is EngineeringConfiguration
        else (
            Build.manufacturing_configuration_id,
            ActualConfiguration.actual_manufacturing_configuration_id,
            ActualConfiguration.actual_manufacturing_revision,
        )
    )
    planned = exists(
        select(literal(1))
        .select_from(Build)
        .where(
            Build.tenant_id == tenant_id,
            Build.product_id == product_id,
            Build.project_id == project_id,
            planned_id == model.id,
        )
        .correlate(model, registered_models.Project)
    )
    actual = exists(
        select(literal(1))
        .select_from(ActualConfiguration)
        .where(
            ActualConfiguration.tenant_id == tenant_id,
            ActualConfiguration.product_id == product_id,
            ActualConfiguration.project_id == project_id,
            actual_id == model.id,
            actual_revision == model.revision,
        )
        .correlate(model, registered_models.Project)
    )
    return or_(planned, actual)


def _bom_project(source, tenant_id, product_id, project_id):
    model = source.model
    configuration = and_(
        EngineeringConfiguration.tenant_id == tenant_id,
        EngineeringConfiguration.product_id == product_id,
        EngineeringConfiguration.bom_id == model.id,
        EngineeringConfiguration.bom_revision == model.revision,
    )
    planned = exists(
        select(literal(1))
        .select_from(Build)
        .join(
            EngineeringConfiguration,
            EngineeringConfiguration.id == Build.engineering_configuration_id,
        )
        .where(
            Build.tenant_id == tenant_id,
            Build.product_id == product_id,
            Build.project_id == project_id,
            configuration,
        )
        .correlate(model, registered_models.Project)
    )
    actual = exists(
        select(literal(1))
        .select_from(ActualConfiguration)
        .join(
            EngineeringConfiguration,
            and_(
                EngineeringConfiguration.id
                == ActualConfiguration.actual_engineering_configuration_id,
                EngineeringConfiguration.revision
                == ActualConfiguration.actual_engineering_revision,
            ),
        )
        .where(
            ActualConfiguration.tenant_id == tenant_id,
            ActualConfiguration.product_id == product_id,
            ActualConfiguration.project_id == project_id,
            configuration,
        )
        .correlate(model, registered_models.Project)
    )
    return or_(planned, actual)


def _g0_project(source, tenant_id, product_id, project_id):
    model = source.model
    return and_(
        model.tenant_id == tenant_id,
        model.created_product_id == product_id,
        model.created_project_id == project_id,
        model.outcome == "approved",
        model.receipt_id.is_not(None),
    )


SOURCES = (
    ActivitySource(
        ProjectRiskFollowup,
        "risk_followup",
        ("work.risk.followup.record",),
        "plan",
        "内部风险跟进",
        columns={"title": ProjectRiskFollowup.body["summary"].astext,
                 "sources": ProjectRiskFollowup.sources},
    ),
    # G0's receipt belongs to the Proposal, not the Decision. The Decision has
    # no revision: literal(None) instructs the owner to use the actual receipt's
    # subject_revision, pinned by Decision.receipt_id, never a fabricated 1.
    ActivitySource(
        ProposalDecision,
        "proposal",
        ("proposal.g0.decide",),
        "plan",
        "项目建立依据",
        project_predicate=_g0_project,
        product_column=ProposalDecision.created_product_id,
        subject_id=ProposalDecision.proposal_id,
        subject_revision=literal(None),
        columns={"title": ProposalDecision.creation["project_name"].astext},
    ),
    ActivitySource(PlanProposal, "plan_proposal", ("work.plan.propose",), "plan", "计划候选"),
    ActivitySource(PlanRevision, "plan_revision", ("work.plan.apply",), "plan", "应用的计划"),
    ActivitySource(
        BomRevision,
        "bom_revision",
        ("engineering.bom.revise",),
        "build",
        "关联BOM记录",
        project_predicate=_bom_project,
        columns={"title": BomRevision.name, "sources": BomRevision.sources},
    ),
    ActivitySource(
        EngineeringConfiguration,
        "engineering_configuration",
        ("engineering.configuration.create",),
        "build",
        "关联工程配置记录",
        project_predicate=_configuration_project,
        columns={
            "title": EngineeringConfiguration.name,
            "sources": EngineeringConfiguration.sources,
        },
    ),
    ActivitySource(
        ProcessRevision,
        "process_revision",
        ("npi.process.revise",),
        "build",
        "关联制造配置记录",
        project_predicate=_configuration_project,
        columns={"title": ProcessRevision.name, "sources": ProcessRevision.sources},
    ),
    ActivitySource(
        Build, "build", ("build.create",), "build", "试制计划", columns={"title": Build.name}
    ),
    ActivitySource(
        BuildReadiness,
        "build_readiness",
        ("build.readiness.compute",),
        "build",
        "准备条件计算",
        project_predicate=_build_readiness_project,
    ),
    ActivitySource(
        BuildAuthorizationDecision,
        "build_authorization",
        ("build.engineering.authorize", "build.manufacturing.authorize"),
        "start",
        "专业开工决定",
        columns={"sources": BuildAuthorizationDecision.sources},
    ),
    ActivitySource(
        BuildStart,
        "build_start",
        ("build.start",),
        "start",
        "实际开工记录",
        columns={
            "sources": BuildStart.sources,
            "occurred_at": BuildStart.occurred_at,
            "original_timezone": BuildStart.occurred_timezone,
        },
    ),
    ActivitySource(
        BuildOperationalFact,
        "build_operational_fact",
        ("build.operational_facts.import",),
        "start",
        "受控执行事实",
        columns={"sources": BuildOperationalFact.sources},
    ),
    ActivitySource(
        ActualConfiguration,
        "actual_configuration",
        ("build.configuration.actual.record",),
        "execution",
        "实际配置记录",
        columns={
            "sources": ActualConfiguration.sources,
            "occurred_at": ActualConfiguration.observed_at,
        },
    ),
    ActivitySource(
        BuildLot,
        "build_lot",
        ("build.output.record",),
        "execution",
        "实际产出批次",
        columns={
            "title": BuildLot.lot_label,
            "sources": BuildLot.sources,
            "occurred_at": BuildLot.occurred_at,
        },
    ),
    ActivitySource(
        SampleAllocation,
        "sample_allocation",
        ("build.sample.allocate",),
        "execution",
        "样件分配记录",
        columns={"sources": SampleAllocation.sources},
    ),
    ActivitySource(
        SampleReadinessFact,
        "sample_readiness_fact",
        ("build.sample.readiness.record",),
        "handoff",
        "样件就绪记录",
        columns={
            "sources": SampleReadinessFact.sources,
            "occurred_at": SampleReadinessFact.occurred_at,
            "original_timezone": SampleReadinessFact.occurred_timezone,
        },
    ),
    ActivitySource(
        SupplySnapshot,
        "supply_snapshot",
        ("supply.snapshot.record",),
        "supply",
        "供给快照",
        columns={"sources": SupplySnapshot.sources},
    ),
    ActivitySource(
        KitProjection, "supply_coverage", ("supply.kit.compute",), "supply", "齐套计算记录"
    ),
    ActivitySource(
        CostInputSnapshot,
        "cost_inputs",
        ("cost.inputs.record",),
        "cost",
        "成本输入快照",
        columns={"sources": CostInputSnapshot.sources},
    ),
    ActivitySource(
        CostEstimate, "cost_estimate", ("cost.estimate.compute",), "cost", "成本计算记录"
    ),
    ActivitySource(
        VerificationPreparation,
        "verification_preparation",
        ("verification.preparation.record",),
        "verification",
        "验证准备记录",
        columns={"sources": VerificationPreparation.sources},
    ),
    ActivitySource(
        FormalVerificationRequest,
        "verification_request",
        (
            "verification.request.create",
            "verification.method.prepare",
            "verification.schedule.propose",
        ),
        "professional",
        "验证请求及方法记录",
        columns={
            "title": FormalVerificationRequest.request_snapshot["title"].astext,
            "sources": FormalVerificationRequest.sources,
        },
    ),
    ActivitySource(
        FormalVerificationRequest,
        "verification_request",
        (
            "verification.handoff.offer",
            "verification.handoff.accept",
            "verification.handoff.return",
        ),
        "handoff",
        "验证交接记录",
        columns={
            "title": FormalVerificationRequest.request_snapshot["title"].astext,
            "sources": FormalVerificationRequest.sources,
        },
    ),
    ActivitySource(
        ActualMethodBatch,
        "verification_actual_method",
        ("verification.actual_method.prepare",),
        "handoff",
        "实际方法核对",
        columns={"sources": ActualMethodBatch.sources},
    ),
    ActivitySource(
        VerificationRunVersion,
        "test_run",
        (
            "test.run.plan",
            "verification.schedule.promise",
            "test.run.start",
        ),
        "launch",
        "测试计划与开测记录",
        columns={"sources": VerificationRunVersion.sources},
    ),
    ActivitySource(
        VerificationRunVersion,
        "test_run",
        (
            "test.results.import",
            "test.run.review",
            "test.disposition.decide",
        ),
        "results",
        "测试结果与处置记录",
        columns={"sources": VerificationRunVersion.sources},
    ),
    ActivitySource(
        TestResultProjection,
        "test_result_projection",
        ("test.result.compute",),
        "results",
        "结果计算记录",
        columns={"sources": TestResultProjection.sources},
    ),
    ActivitySource(
        TestResourceFact,
        "test_resource_fact",
        ("test.resources.import",),
        "launch",
        "受控测试资源事实",
        columns={"sources": TestResourceFact.sources},
    ),
    ActivitySource(
        QualityIssueVersion,
        "quality_issue",
        (
            "quality.issue.create",
            "quality.issue.merge",
            "quality.issue.triage",
            "quality.issue.containment.record",
            "quality.capa.draft",
            "quality.issue.root_cause.decide",
            "quality.capa.actions.complete",
        ),
        "quality",
        "问题及整改记录",
        columns={
            "title": QualityIssueVersion.issue_snapshot["title"].astext,
            "sources": QualityIssueVersion.sources,
        },
    ),
    ActivitySource(
        RemediationLinkRecord,
        "capa_remediation_link",
        ("quality.capa.followup.link",),
        "quality",
        "整改输出回链",
        columns={"sources": RemediationLinkRecord.sources},
    ),
    ActivitySource(
        CapaVerificationEvidence,
        "capa_verification_candidate",
        ("quality.capa.verification.candidate.record",),
        "quality",
        "整改有效性候选",
        columns={"sources": CapaVerificationEvidence.sources},
    ),
    ActivitySource(
        RuleFact,
        "capa_verification_rule",
        ("quality.capa.verification.rule.import",),
        "quality",
        "受控整改验证规则",
        columns={"sources": RuleFact.sources},
    ),
    ActivitySource(
        ObservationFact,
        "capa_observation",
        ("quality.capa.observation.record",),
        "quality",
        "整改观察记录",
        columns={"sources": ObservationFact.sources},
    ),
    ActivitySource(
        NamedReviewRecord,
        "capa_named_verification_review",
        ("quality.capa.verification.review",),
        "quality",
        "整改有效性具名核对",
        columns={"sources": NamedReviewRecord.sources},
    ),
    ActivitySource(
        QualityPolicyFact,
        "quality_policy_fact",
        ("quality.policy.import",),
        "quality",
        "受控质量政策记录",
        columns={"sources": QualityPolicyFact.sources},
    ),
    ActivitySource(
        ProfessionalFact,
        "professional_authority_fact",
        ("professional.authority.import",),
        "professional",
        "受控专业事实登记",
        columns={"sources": ProfessionalFact.sources},
    ),
    ActivitySource(
        ChangeRequestVersion,
        "change_request",
        (
            "change.request.create",
            "change.impact.compute",
            "change.order.prepare",
            "change.order.approve",
            "change.implementation.record",
            "change.effectivity.record",
            "change.verification.record",
            "change.close",
        ),
        "quality",
        "变更记录",
        columns={
            "title": ChangeRequestVersion.request_snapshot["title"].astext,
            "sources": ChangeRequestVersion.sources,
        },
    ),
    ActivitySource(
        ChangePolicyFact,
        "change_policy_fact",
        ("change.policy.import",),
        "quality",
        "受控变更政策",
        columns={"sources": ChangePolicyFact.sources},
    ),
    ActivitySource(
        ChangeCoverageFact,
        "change_coverage_fact",
        ("change.coverage.import",),
        "quality",
        "受控变更覆盖事实",
        columns={"sources": ChangeCoverageFact.sources},
    ),
    ActivitySource(
        ChangeSelectionFact,
        "change_selection_fact",
        ("change.selection.decide",),
        "quality",
        "变更选定范围决定",
        columns={"sources": ChangeSelectionFact.sources},
    ),
    ActivitySource(
        PreparationVersion,
        "work_instruction",
        ("npi.work_instruction.record",),
        "build",
        "作业指导记录",
        columns={"title": PreparationVersion.title, "sources": PreparationVersion.sources},
    ),
    ActivitySource(
        PreparationVersion,
        "control_plan",
        ("npi.control_plan.record",),
        "build",
        "控制计划记录",
        columns={"title": PreparationVersion.title, "sources": PreparationVersion.sources},
    ),
    ActivitySource(
        PreparationVersion,
        "manufacturing_baseline",
        ("npi.manufacturing_baseline.record",),
        "build",
        "制造准备基线记录",
        columns={"title": PreparationVersion.title, "sources": PreparationVersion.sources},
    ),
    ActivitySource(
        ManufacturingBaselinePublication,
        "manufacturing_publication",
        ("npi.manufacturing_baseline.publish",),
        "build",
        "制造发布记录",
        columns={"sources": ManufacturingBaselinePublication.sources},
    ),
    ActivitySource(
        NativePilotRun,
        "pilot_run",
        ("npi.pilot.create",),
        "build",
        "试产建立记录",
        columns={"sources": NativePilotRun.sources},
    ),
    ActivitySource(
        NativePilotObservation,
        "pilot_observation",
        ("npi.pilot.result.record",),
        "build",
        "试产原值记录",
        columns={"sources": NativePilotObservation.sources},
    ),
    ActivitySource(
        ReleasePackage,
        "release_package",
        ("release.package.assemble",),
        "build",
        "固定发布包",
        columns={"sources": ReleasePackage.sources},
    ),
    ActivitySource(
        ReleaseDecision,
        "release_decision",
        ("release.engineering.approve", "release.manufacturing.approve"),
        "build",
        "专业放行决定",
        columns={"sources": ReleaseDecision.sources},
    ),
    ActivitySource(
        ReleaseExceptionDecision,
        "release_exception",
        ("release.exception.decide", "release.exception.withdraw"),
        "build",
        "有限例外决定",
        columns={"sources": ReleaseExceptionDecision.sources},
    ),
    ActivitySource(
        ReleasePolicyFact,
        "release_policy_fact",
        ("release.policy.import",),
        "build",
        "受控发布政策",
        columns={"sources": ReleasePolicyFact.sources},
    ),
    ActivitySource(
        ExternalHandoffAuthorization,
        "external_handoff",
        ("integration.handoff.authorize",),
        "build",
        "固定外部移交授权",
        columns={"sources": ExternalHandoffAuthorization.sources},
    ),
    ActivitySource(
        ExternalReceipt,
        "external_receipt",
        ("integration.receipt.record",),
        "build",
        "外部结果回执",
        columns={"sources": ExternalReceipt.sources, "occurred_at": ExternalReceipt.occurred_at},
    ),
    ActivitySource(
        ExternalWaitVersion,
        "external_wait",
        ("work.external_wait.record",),
        "plan",
        "外部等待登记",
        columns={
            "title": ExternalWaitVersion.body["title"].astext,
            "sources": ExternalWaitVersion.sources,
        },
    ),
    ActivitySource(
        WorkTaskVersion,
        "work_task",
        (
            "work.task.create",
            "work.task.assign",
            "work.task.accept",
            "work.task.start",
            "work.task.submit",
            "work.task.review",
        ),
        "plan",
        "项目行动记录",
        columns={
            "title": WorkTaskVersion.body["title"].astext,
            "sources": WorkTaskVersion.sources,
            **{
                key: case(
                    (
                        WorkTaskVersion.operation == "work.task.start",
                        WorkTaskVersion.body["actual_start"][field].astext,
                    ),
                    (
                        WorkTaskVersion.operation == "work.task.submit",
                        WorkTaskVersion.body["submission"]["time"][field].astext,
                    ),
                    (
                        WorkTaskVersion.operation == "work.task.review",
                        WorkTaskVersion.body["review"]["time"][field].astext,
                    ),
                )
                for key, field in (
                    ("occurred_at", "actual_at"),
                    ("original_timezone", "original_timezone"),
                )
            },
        },
    ),
    ActivitySource(
        WorkCommitmentVersion,
        "work_commitment",
        ("work.commitment.accept",),
        "plan",
        "个人承诺记录",
        columns={"sources": WorkCommitmentVersion.sources},
    ),
    ActivitySource(
        WorkCommitmentReview,
        "work_commitment_review",
        ("work.commitment.review",),
        "plan",
        "承诺履行核对",
        columns={"sources": WorkCommitmentReview.sources},
    ),
    ActivitySource(
        ProjectStatusUpdate,
        "project_status_update",
        ("work.status_update.create",),
        "plan",
        "具名项目状态更新",
        columns={
            "summary": ProjectStatusUpdate.fact_summary,
            "next_steps": ProjectStatusUpdate.next_steps,
            "task_refs": ProjectStatusUpdate.task_refs,
            "sources": ProjectStatusUpdate.sources,
        },
    ),
)


OPERATION_LABELS = MappingProxyType(
    {
        "work.external_wait.record": "登记外部等待",
        "proposal.g0.decide": "项目建立决定已保存",
        "work.plan.propose": "计划候选已保存",
        "work.plan.apply": "计划应用已记录",
        "engineering.bom.revise": "关联BOM版本记录",
        "engineering.configuration.create": "关联工程配置记录",
        "npi.process.revise": "关联制造配置记录",
        "build.create": "试制计划已保存",
        "build.readiness.compute": "试制准备计算已返回",
        "build.engineering.authorize": "工程开工决定已保存",
        "build.manufacturing.authorize": "制造开工决定已保存",
        "build.start": "实际开工已记录",
        "build.operational_facts.import": "受控执行事实已登记",
        "build.configuration.actual.record": "实际配置已记录",
        "build.output.record": "实际产出批次已记录",
        "build.sample.allocate": "样件分配已记录",
        "build.sample.readiness.record": "样件就绪事实已记录",
        "supply.snapshot.record": "供给快照已保存",
        "supply.kit.compute": "齐套计算已返回",
        "cost.inputs.record": "成本输入快照已保存",
        "cost.estimate.compute": "成本计算已返回",
        "verification.preparation.record": "验证准备已记录",
        "verification.request.create": "验证请求已保存",
        "verification.method.prepare": "验证方法准备已记录",
        "verification.schedule.propose": "验证窗口候选已保存",
        "verification.actual_method.prepare": "实际方法核对已记录",
        "verification.handoff.offer": "交样已记录",
        "verification.handoff.accept": "品质接收已记录",
        "verification.handoff.return": "交样退回已记录",
        "test.run.plan": "测试运行计划已保存",
        "verification.schedule.promise": "本人开测承诺已记录",
        "test.run.start": "实际开测已记录",
        "test.results.import": "测试原值导入已记录",
        "test.result.compute": "测试结果计算已返回",
        "test.run.review": "测试运行复核已记录",
        "test.disposition.decide": "测试处置决定已保存",
        "test.resources.import": "受控测试资源事实已登记",
        "quality.issue.create": "问题已建立",
        "quality.issue.merge": "问题合并已记录",
        "quality.issue.triage": "问题分诊已记录",
        "quality.issue.containment.record": "遏制事实已记录",
        "quality.capa.draft": "整改草稿已保存",
        "quality.issue.root_cause.decide": "实际根因决定已保存",
        "quality.capa.actions.complete": "整改措施实绩已记录",
        "quality.capa.followup.link": "整改输出回链已保存",
        "quality.capa.verification.candidate.record": "整改有效性候选已保存",
        "quality.capa.verification.rule.import": "受控整改验证规则已登记",
        "quality.capa.observation.record": "整改观察事实已记录",
        "quality.capa.verification.review": "整改有效性具名核对已保存",
        "quality.policy.import": "受控质量政策已登记",
        "professional.authority.import": "受控专业事实已登记",
        "change.request.create": "变更请求已保存",
        "change.impact.compute": "变更影响计算已返回",
        "change.order.prepare": "变更令候选已保存",
        "change.order.approve": "变更批准决定已保存",
        "change.implementation.record": "变更实施事实已记录",
        "change.effectivity.record": "变更实际采用已记录",
        "change.verification.record": "变更独立复核决定已保存",
        "change.close": "变更已具名关闭",
        "change.policy.import": "受控变更政策已登记",
        "change.coverage.import": "受控变更覆盖事实已登记",
        "change.selection.decide": "变更范围选定已记录",
        "npi.work_instruction.record": "作业指导版本已保存",
        "npi.control_plan.record": "控制计划版本已保存",
        "npi.manufacturing_baseline.record": "制造准备基线已保存",
        "npi.manufacturing_baseline.publish": "制造发布决定已保存",
        "npi.pilot.create": "试产记录已建立",
        "npi.pilot.result.record": "试产原值已记录",
        "release.package.assemble": "固定发布包已保存",
        "release.engineering.approve": "工程放行决定已保存",
        "release.manufacturing.approve": "制造放行决定已保存",
        "release.exception.decide": "有限例外决定已保存",
        "release.exception.withdraw": "例外撤回决定已保存",
        "release.policy.import": "受控发布政策已登记",
        "integration.handoff.authorize": "固定外部移交授权已保存",
        "integration.receipt.record": "外部结果回执已记录",
        "work.task.create": "项目行动已建立",
        "work.task.assign": "责任分派已记录",
        "work.task.accept": "本人责任承接已记录",
        "work.task.start": "实际开始已记录",
        "work.task.submit": "成果提交已记录",
        "work.task.review": "成果验收决定已保存",
        "work.commitment.accept": "本人承诺已记录",
        "work.commitment.review": "接收者承诺履行核对已记录",
        "work.status_update.create": "具名项目状态更新已保存",
        "work.risk.followup.record": "内部风险跟进已记录",
    }
)
