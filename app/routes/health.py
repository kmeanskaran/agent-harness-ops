from fastapi import APIRouter

from app.redis_store import get_client

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness + Redis connectivity check (used by Railway healthcheck)."""
    try:
        get_client().ping()
        redis_ok = True
    except Exception:  # noqa: BLE001
        redis_ok = False
    return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok}
