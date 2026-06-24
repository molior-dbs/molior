"""
Database session dependency.

Replaces MoliorServer.create_cirrina_context / destroy_cirrina_context.

Usage in a handler:

    from ..db import get_db

    @router.get("/something")
    def my_handler(db: Session = Depends(get_db)):
        return db.query(...)
"""

from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from ..model.database import database


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a per-request SQLAlchemy session."""
    maker = sessionmaker(bind=database.engine)
    db = maker()
    try:
        yield db
    finally:
        db.close()
