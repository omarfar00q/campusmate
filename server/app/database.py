"""Database engine and session management for CampusMate."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from campusmate.server.app.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_database_url() -> str:
    """Get the configured database URL."""
    return os.getenv("DATABASE_URL", "sqlite:///./campusmate.db").strip()


def get_engine(db_url: str | None = None) -> Engine:
    """Return the global SQLAlchemy Engine, creating it if needed."""
    global _engine, _session_factory
    url = db_url or get_database_url()
    if _engine is None or db_url is not None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, echo=False, connect_args=connect_args)
        if db_url is None:
            _engine = engine
            _session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        return engine
    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None or engine is not None:
        eng = engine or get_engine()
        _session_factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    return _session_factory


def init_db(engine: Engine | None = None) -> None:
    """Create all database tables."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)


def reset_db(engine: Engine | None = None) -> None:
    """Drop and recreate all tables for a clean state."""
    eng = engine or get_engine()
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)


@contextmanager
def get_db_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Provide a transactional database session."""
    factory = get_session_factory(engine)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
