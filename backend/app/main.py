"""
Anti Gravity Deployments - FastAPI Application

Main application entry point for the backend API server.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from app.api.routes import router
from app.db.database import engine

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)


def create_tables() -> None:
    """Create all database tables on startup (idempotent)."""
    try:
        # Import model so SQLModel registers it
        from app.db.models import DeploymentRecord  # noqa: F401
        SQLModel.metadata.create_all(engine)
        logger.info("Database tables ensured")
    except Exception as exc:
        logger.error("Failed to create database tables: %s", exc)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Anti Gravity Deployments API",
        description=(
            "Backend API for the Anti Gravity internal deployment platform. "
            "Handles project uploads, container builds, deployment management, "
            "and real-time status updates."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware — allow frontend to connect
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://172.25.208.1:3000",
            "*",  # Allow all origins for self-hosted deployments
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    async def on_startup():
        """Initialize database tables on application startup."""
        create_tables()
        logger.info("Anti Gravity Deployments API started")

    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint — API information."""
        return {
            "service": "Anti Gravity Deployments API",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
