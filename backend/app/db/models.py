from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class DeploymentRecord(
    SQLModel,
    table=True,
):

    deployment_id: str = Field(
        primary_key=True
    )

    project_name: str

    frontend_url: Optional[str] = None

    backend_url: Optional[str] = None

    status: str

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )