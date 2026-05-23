import os
from sqlmodel import create_engine
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
import logging

logger = logging.getLogger(__name__)

# ── Database URL ─────────────────────────────────────────────────────────────
# Prefer PostgreSQL if env var is set.  Fall back to SQLite for local dev.

_POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/anti_gravity",
)

_SQLITE_URL = "sqlite:///./anti_gravity.db"


def _make_engine():
    """Create database engine with appropriate settings and fallback."""

    # Try PostgreSQL first
    if _POSTGRES_URL.startswith("postgresql"):
        try:
            eng = create_engine(
                _POSTGRES_URL,
                echo=False,
                pool_pre_ping=True,       # reconnect on stale connections
                pool_size=5,
                max_overflow=10,
                pool_recycle=300,         # recycle connections every 5 min
                pool_timeout=30,
                connect_args={
                    "connect_timeout": 10,
                },
            )
            # Quick connectivity test
            with eng.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            logger.info("Connected to PostgreSQL: %s", _POSTGRES_URL.split("@")[-1])
            return eng
        except Exception as exc:
            logger.warning(
                "PostgreSQL unavailable (%s). Falling back to SQLite.", exc
            )

    # SQLite fallback — works on any machine without Postgres
    logger.info("Using SQLite database: %s", _SQLITE_URL)
    eng = create_engine(
        _SQLITE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return eng


engine = _make_engine()