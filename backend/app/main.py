"""
Anti Gravity Deployments - FastAPI Application

Main application entry point for the backend API server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db import create_db_and_tables

from app.api.routes import router


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
    create_db_and_tables()

    # CORS middleware — allow frontend to connect
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://frontend:3000",
            "http://localhost:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(router, prefix="/api")

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
