from fastapi import APIRouter, HTTPException, status

from database.connection import test_connection


router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("/live")
def liveness() -> dict[str, str]:
    return {
        "status": "ok",
    }


@router.get("/ready")
def readiness() -> dict[str, str]:
    try:
        test_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc

    return {
        "status": "ready",
        "database": "ok",
    }
