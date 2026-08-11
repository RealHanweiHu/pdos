from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="PDOS API",
    description="API surface for the PDOS preview.",
    version="0.1.0",
)
app.include_router(health_router)
