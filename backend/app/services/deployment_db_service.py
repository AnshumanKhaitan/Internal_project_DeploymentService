from sqlmodel import Session

from app.db.database import engine
from app.db.models import DeploymentRecord


class DeploymentDBService:

    @staticmethod
    def create_deployment(
        deployment: DeploymentRecord
    ):

        with Session(engine) as session:

            session.add(
                deployment
            )

            session.commit()

    @staticmethod
    def get_all_deployments():

        with Session(engine) as session:

            return session.query(
                DeploymentRecord
            ).all()