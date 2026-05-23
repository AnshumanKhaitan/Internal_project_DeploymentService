import logging
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import DeploymentRecord

logger = logging.getLogger(__name__)


class DeploymentDBService:

    @staticmethod
    def create_deployment(deployment: DeploymentRecord) -> bool:
        """
        Persist a deployment record.

        Returns True on success, False on failure.
        Never raises — a DB failure must not crash the deployment response.
        """
        try:
            with Session(engine) as session:
                session.add(deployment)
                session.commit()
                logger.info(
                    "[DB] Persisted deployment %s (status=%s, frontend=%s, backend=%s)",
                    deployment.deployment_id,
                    deployment.status,
                    deployment.frontend_url,
                    deployment.backend_url,
                )
                return True
        except Exception as exc:
            logger.error(
                "[DB] Failed to persist deployment %s: %s",
                deployment.deployment_id,
                exc,
            )
            return False

    @staticmethod
    def get_all_deployments() -> list[DeploymentRecord]:
        """Return all deployment records, newest first."""
        try:
            with Session(engine) as session:
                records = session.exec(
                    select(DeploymentRecord).order_by(
                        DeploymentRecord.created_at.desc()  # type: ignore[arg-type]
                    )
                ).all()
                return list(records)
        except Exception as exc:
            logger.error("[DB] get_all_deployments failed: %s", exc)
            return []

    @staticmethod
    def get_deployment(deployment_id: str) -> DeploymentRecord | None:
        """Return a single deployment record by ID."""
        try:
            with Session(engine) as session:
                return session.get(DeploymentRecord, deployment_id)
        except Exception as exc:
            logger.error(
                "[DB] get_deployment(%s) failed: %s", deployment_id, exc
            )
            return None

    @staticmethod
    def update_status(deployment_id: str, status: str) -> bool:
        """Update the status of an existing deployment record."""
        try:
            with Session(engine) as session:
                record = session.get(DeploymentRecord, deployment_id)
                if record:
                    record.status = status
                    session.add(record)
                    session.commit()
                    return True
                return False
        except Exception as exc:
            logger.error(
                "[DB] update_status(%s → %s) failed: %s",
                deployment_id,
                status,
                exc,
            )
            return False