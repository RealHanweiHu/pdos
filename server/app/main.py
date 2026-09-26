from fastapi import FastAPI

from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.change_governance import router as change_governance_router
from app.api.conversations import router as conversations_router
from app.api.customer_changes import router as customer_changes_router
from app.api.customer_reports import router as customer_reports_router
from app.api.dashboard import router as dashboard_router
from app.api.decision_intake import router as decision_intake_router
from app.api.decisions import router as decisions_router
from app.api.deliverable_checks import router as deliverable_checks_router
from app.api.development_cases import router as development_cases_router
from app.api.dingtalk import router as dingtalk_router
from app.api.discussion_research import router as discussion_research_router
from app.api.document_previews import router as document_previews_router
from app.api.events import router as events_router
from app.api.evidence import router as evidence_router
from app.api.field_captures import router as field_captures_router
from app.api.findings import router as findings_router
from app.api.fmea_candidates import router as fmea_candidates_router
from app.api.gates import router as gates_router
from app.api.health import router as health_router
from app.api.initial_plan_candidates import router as initial_plan_candidates_router
from app.api.issue_intake import compensation_router as issue_intake_compensation_router
from app.api.issue_intake import router as issue_intake_router
from app.api.issue_risks import router as issue_risks_router
from app.api.living_fmea import router as living_fmea_router
from app.api.meetings import router as meetings_router
from app.api.memories import router as memories_router
from app.api.model_governance import router as model_governance_router
from app.api.my_work import router as my_work_router
from app.api.npi_execution import router as npi_execution_router
from app.api.open_api import external_router as open_api_router
from app.api.open_api import router as open_api_admin_router
from app.api.organization import router as organization_router
from app.api.plan_scenarios import router as plan_scenarios_router
from app.api.process_templates import router as process_templates_router
from app.api.product_engineering import router as product_engineering_router
from app.api.product_research import router as product_research_router
from app.api.product_workspace import router as product_workspace_router
from app.api.project_completion import router as project_completion_router
from app.api.project_discussions import router as project_discussions_router
from app.api.project_intake import router as project_intake_router
from app.api.project_reports import router as project_reports_router
from app.api.project_templates import router as project_templates_router
from app.api.project_webhooks import router as project_webhooks_router
from app.api.projects import router as projects_router
from app.api.quality_capa import router as quality_capa_router
from app.api.quality_complaints import router as quality_complaints_router
from app.api.quality_issue_links import router as quality_issue_links_router
from app.api.quality_operations import router as quality_operations_router
from app.api.reminders import router as reminders_router
from app.api.requirements import router as requirements_router
from app.api.research_measurement import router as research_measurement_router
from app.api.research_workpacks import router as research_workpacks_router
from app.api.review_candidates import router as review_candidates_router
from app.api.search import router as search_router
from app.api.tencent_meeting import router as tencent_meeting_router
from app.api.users import router as users_router
from app.api.value_measurement import router as value_measurement_router
from app.api.value_workpacks import router as value_workpacks_router
from app.api.work_items import router as work_items_router

app = FastAPI(
    title="PDOS API",
    description="API surface for the PDOS preview.",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(organization_router)
app.include_router(dingtalk_router)
app.include_router(open_api_admin_router)
app.include_router(project_webhooks_router)
app.include_router(value_measurement_router)
app.include_router(research_measurement_router)
app.include_router(research_workpacks_router)
app.include_router(value_workpacks_router)
app.include_router(open_api_router)
app.include_router(tencent_meeting_router)
app.include_router(ai_router)
app.include_router(conversations_router)
app.include_router(review_candidates_router)
app.include_router(projects_router)
app.include_router(dashboard_router)
app.include_router(gates_router)
app.include_router(product_engineering_router)
app.include_router(npi_execution_router)
app.include_router(change_governance_router)
app.include_router(discussion_research_router)
app.include_router(project_discussions_router)
app.include_router(customer_changes_router)
app.include_router(meetings_router)
app.include_router(evidence_router)
app.include_router(search_router)
app.include_router(field_captures_router)
app.include_router(document_previews_router)
app.include_router(deliverable_checks_router)
app.include_router(requirements_router)
app.include_router(development_cases_router)
app.include_router(events_router)
app.include_router(work_items_router)
app.include_router(my_work_router)
app.include_router(reminders_router)
app.include_router(issue_risks_router)
app.include_router(issue_intake_router)
app.include_router(issue_intake_compensation_router)
app.include_router(decisions_router)
app.include_router(decision_intake_router)
app.include_router(project_intake_router)
app.include_router(project_completion_router)
app.include_router(project_templates_router)
app.include_router(process_templates_router)
app.include_router(product_workspace_router)
app.include_router(product_research_router)
app.include_router(initial_plan_candidates_router)
app.include_router(plan_scenarios_router)
app.include_router(quality_complaints_router)
app.include_router(quality_capa_router)
app.include_router(quality_operations_router)
app.include_router(quality_issue_links_router)
app.include_router(fmea_candidates_router)
app.include_router(living_fmea_router)
app.include_router(project_reports_router)
app.include_router(customer_reports_router)
app.include_router(memories_router)
app.include_router(model_governance_router)
app.include_router(findings_router)
