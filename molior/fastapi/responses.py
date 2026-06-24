"""
Response helpers and pagination — FastAPI equivalents of molior/tools.py helpers.

OKResponse / ErrorResponse are kept as thin wrappers so ported handler code
reads similarly to the original.  New handlers should prefer returning plain
dicts (FastAPI serialises them automatically) or Pydantic models.
"""

from typing import Any, Optional

from fastapi import Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Query as SAQuery


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def OKResponse(data: Any = "", status: int = 200) -> JSONResponse:
    """Drop-in for tools.OKResponse."""
    return JSONResponse(status_code=status, content=data)


def ErrorResponse(status: int, msg: str) -> JSONResponse:
    """Drop-in for tools.ErrorResponse."""
    return JSONResponse(status_code=status, content=msg)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationParams:
    """
    Reusable pagination dependency.

    Replaces the paginate() helper from tools.py.  Supports both
    page_size and per_page query parameters (matching existing API behaviour).

    Usage:

        @router.get("/things")
        def list_things(
            pagination: PaginationParams = Depends(),
            db: Session = Depends(get_db),
        ):
            query = db.query(Thing)
            total = query.count()
            results = pagination.apply(query).all()
            return {"total_result_count": total, "results": results}
    """

    def __init__(
        self,
        page: Optional[int] = Query(default=None, ge=1),
        page_size: Optional[int] = Query(default=None, alias="page_size", ge=1),
        per_page: Optional[int] = Query(default=None, alias="per_page", ge=1),
    ):
        self.page = page or 1
        self.page_size = page_size or per_page or 10

    def apply(self, query: SAQuery) -> SAQuery:
        """Apply LIMIT / OFFSET to a SQLAlchemy query."""
        return query.limit(self.page_size).offset((self.page - 1) * self.page_size)
