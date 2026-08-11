from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.development_cases import router as development_cases_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.requirements import router as requirements_router

app = FastAPI(
    title="PDOS API",
    description="API surface for the PDOS preview.",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(requirements_router)
app.include_router(development_cases_router)
