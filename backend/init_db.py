from sqlmodel import SQLModel

from app.db.database import engine
from app.db.models import DeploymentRecord

SQLModel.metadata.create_all(
    engine
)

print(
    "Database tables created!"
)