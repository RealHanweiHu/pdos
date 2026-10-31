from fastapi import FastAPI

from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.change_governance import router as change_governance_router
from app.api.deliverable_checks import router as deliverable_checks_router
from app.api.development_cases import router as development_cases_router
from app.api.dingtalk import router as dingtalk_router
from app.api.events import router as events_router
from app.api.findings import router as findings_router
from app.api.gates import router as gates_router
from app.api.health import router as health_router
from app.api.issue_risks import router as issue_risks_router
from app.api.memories import router as memories_router
from app.api.model_governance import router as model_governance_router
from app.api.npi_execution import router as npi_execution_router
from app.api.portfolio import router as portfolio_router
from app.api.product_engineering import router as product_engineering_router
from app.api.projects import router as projects_router
from app.api.quality_capa import router as quality_capa_router
from app.api.quality_complaints import router as quality_complaints_router
from app.api.requirements import router as requirements_router
from app.api.resources_costs import router as resources_costs_router
from app.api.work_items import router as work_items_router

app = FastAPI(
    title="PDOS API",
    description="API surface for the PDOS preview.",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(dingtalk_router)
app.include_router(ai_router)
app.include_router(projects_router)
app.include_router(gates_router)
app.include_router(product_engineering_router)
app.include_router(npi_execution_router)
app.include_router(change_governance_router)
app.include_router(deliverable_checks_router)
app.include_router(requirements_router)
app.include_router(development_cases_router)
app.include_router(events_router)
app.include_router(work_items_router)
app.include_router(issue_risks_router)
app.include_router(portfolio_router)
app.include_router(resources_costs_router)
app.include_router(quality_complaints_router)
app.include_router(quality_capa_router)
app.include_router(memories_router)
app.include_router(model_governance_router)
app.include_router(findings_router)
