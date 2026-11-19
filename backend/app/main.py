from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.health import router as health_router
from app.api.investigation import router as investigation_router
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("AI Kubernetes Agent API started")
    yield
    logger.info("AI Kubernetes Agent API stopped")


app = FastAPI(
    title="AI Kubernetes Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(investigation_router)
