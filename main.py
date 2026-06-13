"""DevVoice FastAPI app — clean endpoints with async job queue and rate limiting."""
from __future__ import annotations

from fastapi import FastAPI
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

from app.db import init_db
from app.routes import content, health, result

# Rate limiter: 10 requests per minute per IP
limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])

app = FastAPI(
    title="DevVoice",
    description="Drop a README, get a reviewed X thread, LinkedIn post, and dev.to article.",
    version="0.1.0",
)

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"detail": "Rate limit exceeded: 10 requests per minute per IP"},
))

app.include_router(health.router, tags=["health"])
app.include_router(content.router, tags=["content"])
app.include_router(result.router, tags=["results"])


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
@limiter.limit("30/minute")
def root(request) -> dict:
    return {
        "service": "devvoice",
        "rate_limit": "10 requests/minute per IP (except /health)",
        "endpoints": [
            "POST /generate-x-post → job_id",
            "POST /generate-linkedin-post → job_id",
            "POST /generate-article → job_id",
            "GET /result/{job_id} → content (when ready)",
            "GET /health → no limit",
        ],
    }
