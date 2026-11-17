"""Database engine and session factory.

- The *engine* owns a pool of connections to PostgreSQL (created once per process).
- A *session* is a short-lived unit of work: one per HTTP request (see get_db).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,  # connections kept open
    max_overflow=20,  # extra connections allowed under burst load
    pool_pre_ping=True,  # test a connection before using it (survives DB restarts)
    pool_recycle=1800,  # replace connections older than 30 min
    # Every session works in UTC, so timestamps are identical on a laptop in India
    # and a server in us-east-1 (the API then returns e.g. "2026-11-17T10:07:59Z").
    connect_args={"options": "-c timezone=UTC"},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: open a session for the request and always close it afterwards.

    Services decide when to commit. If an exception escapes, the session is closed
    without committing, so the transaction is rolled back automatically.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
