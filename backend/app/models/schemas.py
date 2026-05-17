"""
Anti Gravity Deployments - Data Models & Schemas

Pydantic models for request/response validation and deployment state management.
"""

from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DeploymentStatus(str, Enum):
    """Possible states for a deployment."""
    PENDING = "pending"
    UPLOADING = "uploading"
    ANALYZING = "analyzing"
    BUILDING = "building"
    DEPLOYING = "deploying"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    REMOVING = "removing"


class RuntimeType(str, Enum):
    """Supported runtime environments."""
    NODEJS = "nodejs"
    PYTHON = "python"
    GO = "go"
    RUST = "rust"
    STATIC = "static"
    UNKNOWN = "unknown"


class FrameworkType(str, Enum):
    """Detected application frameworks."""
    NEXTJS = "nextjs"
    REACT = "react"
    VITE = "vite"
    VUE = "vue"
    ANGULAR = "angular"
    EXPRESS = "express"
    FASTAPI = "fastapi"
    FLASK = "flask"
    DJANGO = "django"
    STATIC = "static"
    UNKNOWN = "unknown"


class DependencyInfo(BaseModel):
    """A single detected dependency."""
    name: str
    version: str = ""
    is_dev: bool = False


class ScriptInfo(BaseModel):
    """An npm/project script."""
    name: str
    command: str


class ProjectAnalysis(BaseModel):
    """Analysis results from scanning a project ZIP."""
    runtime: RuntimeType = RuntimeType.UNKNOWN
    runtime_version: Optional[str] = None
    framework: FrameworkType = FrameworkType.UNKNOWN
    framework_version: Optional[str] = None
    detected_port: int = 3000
    has_dockerfile: bool = False
    has_docker_compose: bool = False
    entry_point: Optional[str] = None
    startup_command: Optional[str] = None
    dependencies: list[DependencyInfo] = []
    dependencies_count: int = 0
    scripts: list[ScriptInfo] = []
    env_template_keys: list[str] = []
    env_template_file: Optional[str] = None
    project_root: Optional[str] = None
    file_count: int = 0
    total_size_bytes: int = 0


class EnvironmentVariable(BaseModel):
    """A single environment variable for deployment."""
    key: str = Field(..., min_length=1, max_length=256)
    value: str = Field(default="", max_length=4096)
    is_secret: bool = False


class DeploymentConfig(BaseModel):
    """Configuration for a deployment."""
    image_name: str = Field(..., min_length=1, max_length=128)
    container_name: str = Field(..., min_length=1, max_length=128)
    route: str = Field(default="/", max_length=256)
    memory_mb: int = Field(default=512, ge=64, le=4096)
    cpu_cores: float = Field(default=0.5, ge=0.1, le=4.0)
    port: int = Field(default=3000, ge=1, le=65535)
    env_vars: list[EnvironmentVariable] = []


class DeploymentState(BaseModel):
    """Full state of a deployment."""
    id: str
    status: DeploymentStatus = DeploymentStatus.PENDING
    project_name: Optional[str] = None
    config: Optional[DeploymentConfig] = None
    analysis: Optional[ProjectAnalysis] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    logs: list[str] = []
    error: Optional[str] = None
    url: Optional[str] = None


class UploadResponse(BaseModel):
    """Response returned after uploading a project ZIP."""
    deployment_id: str
    status: DeploymentStatus
    message: str
    analysis: Optional[ProjectAnalysis] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "0.1.0"
    service: str = "anti-gravity-deployments"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LogEntry(BaseModel):
    """A single log entry from the deployment process."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: str = "info"
    message: str = ""


class DeploymentEvent(BaseModel):
    """Server-sent event for deployment progress updates."""
    event_type: str
    deployment_id: str
    data: dict = {}
