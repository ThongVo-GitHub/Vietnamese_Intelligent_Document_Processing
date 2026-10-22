from fastapi import FastAPI, Response, status

from app.config import get_settings
from app.database import database_is_ready
from app.routers.dossiers import router as dossiers_router
from app.routers.jobs import router as jobs_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Backend API for Vietnamese Intelligent Document Processing",
    version="0.1.0",
)

app.include_router(dossiers_router)
app.include_router(jobs_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": f"Welcome to {settings.app_name}",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "backend",
        "environment": settings.app_env,
    }


@app.get("/health/ready")
def readiness(response: Response) -> dict[str, str]:
    if not database_is_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "not_ready",
            "service": "backend",
            "database": "unavailable",
        }
    return {
        "status": "ok",
        "service": "backend",
        "database": "connected",
    }
