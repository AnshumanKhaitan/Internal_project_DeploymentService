from sqlmodel import create_engine

DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/anti_gravity"
)

engine = create_engine(
    DATABASE_URL,
    echo=True,
)