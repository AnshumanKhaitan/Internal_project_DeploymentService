from typing import Optional
from sqlmodel import SQLModel, Field


class DeploymentRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)

    project_name: str

    runtime: Optional[str] = None

    status: str

    container_name: Optional[str] = None

    image_name: Optional[str] = None

    assigned_port: Optional[int] = None

    traefik_route: Optional[str] = None