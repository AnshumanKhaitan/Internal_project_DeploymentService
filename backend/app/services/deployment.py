"""
Anti Gravity Deployments - Deployment Service

Core service for handling deployment lifecycle:
upload, extraction, analysis, and state management.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.schemas import (
    DeploymentState,
    DeploymentStatus,
    ProjectAnalysis,
    DeploymentConfig,
    RuntimeType,
    FrameworkType,
)
from app.utils.helpers import (
    create_deployment_workspace,
    cleanup_workspace,
)


class DeploymentService:
    """Service for managing deployment lifecycle."""

    def __init__(self):
        self._deployments: dict[str, DeploymentState] = {}
        self._workspaces: dict[str, Path] = {}

    def create_deployment(
        self,
        project_name: str,
        deployment_id: Optional[str] = None,
        workspace: Optional[Path] = None,
    ) -> DeploymentState:
        """Create a new deployment entry."""
        if deployment_id is None:
            deployment_id = str(uuid.uuid4())[:8]

        deployment = DeploymentState(
            id=deployment_id,
            status=DeploymentStatus.PENDING,
            project_name=project_name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._deployments[deployment_id] = deployment

        if workspace:
            self._workspaces[deployment_id] = workspace

        return deployment

    def get_deployment(self, deployment_id: str) -> Optional[DeploymentState]:
        """Get deployment state by ID."""
        return self._deployments.get(deployment_id)

    def get_workspace(self, deployment_id: str) -> Optional[Path]:
        """Get the workspace path for a deployment."""
        return self._workspaces.get(deployment_id)

    def list_deployments(self) -> list[DeploymentState]:
        """List all deployments."""
        return list(self._deployments.values())

    def update_status(
        self, deployment_id: str, status: DeploymentStatus
    ) -> Optional[DeploymentState]:
        """Update the status of a deployment."""
        deployment = self._deployments.get(deployment_id)
        if deployment:
            deployment.status = status
            deployment.updated_at = datetime.utcnow()
        return deployment

    def update_analysis(
        self, deployment_id: str, analysis: ProjectAnalysis
    ) -> Optional[DeploymentState]:
        """Update deployment with analysis results."""
        deployment = self._deployments.get(deployment_id)
        if deployment:
            deployment.analysis = analysis
            deployment.updated_at = datetime.utcnow()
        return deployment

    def set_error(
        self, deployment_id: str, error: str
    ) -> Optional[DeploymentState]:
        """Set error state on a deployment."""
        deployment = self._deployments.get(deployment_id)
        if deployment:
            deployment.status = DeploymentStatus.FAILED
            deployment.error = error
            deployment.updated_at = datetime.utcnow()
        return deployment

    def delete_deployment(self, deployment_id: str) -> bool:
        """Remove a deployment and clean up its workspace."""
        if deployment_id in self._deployments:
            # Clean up workspace if exists
            workspace = self._workspaces.pop(deployment_id, None)
            if workspace:
                cleanup_workspace(workspace)
            del self._deployments[deployment_id]
            return True
        return False

    def mock_analyze_project(self) -> ProjectAnalysis:
        """Return mock project analysis data (placeholder)."""
        return ProjectAnalysis(
            runtime=RuntimeType.NODEJS,
            runtime_version="20.11.0",
            framework=FrameworkType.NEXTJS,
            framework_version="15.0.0",
            detected_port=3000,
            has_dockerfile=False,
            has_docker_compose=False,
            entry_point="package.json",
            dependencies_count=47,
        )


# Singleton instance
deployment_service = DeploymentService()
