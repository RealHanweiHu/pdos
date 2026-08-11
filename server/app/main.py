from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router

app = FastAPI(
    title="PDOS API",
    description="API surface for the PDOS preview.",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(auth_router)
