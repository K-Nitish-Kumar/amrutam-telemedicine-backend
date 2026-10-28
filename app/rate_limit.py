import threading
import time
from collections import defaultdict

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP fixed-window limiting. Redis implementation is atomic and cross-replica."""
    def __init__(self, app):
        super().__init__(app)
        self.lock = threading.Lock()
        self.local = defaultdict(lambda: [0, 0])
        self.redis = None
        if get_settings().rate_limit_backend == "redis":
            import redis
            self.redis = redis.Redis.from_url(get_settings().redis_url, socket_timeout=1)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in {"/health/live", "/health/ready"}:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"  # never trust arbitrary X-Forwarded-For
        login_path = path in {"/auth/login", "/auth/register", "/auth/mfa/verify-login"}
        limit, window = (10, 60) if login_path else (120, 60)
        tick = int(time.time()) // window
        key = f"amrutam:limit:{ip}:{'auth' if login_path else 'api'}:{tick}"
        try:
            if self.redis:
                count = self.redis.incr(key)
                if count == 1:
                    self.redis.expire(key, window + 2)
            else:
                with self.lock:
                    if len(self.local) > 10000:
                        self.local.clear()
                    rec = self.local[key]
                    rec[0] += 1
                    count = rec[0]
        except Exception:
            # Fail closed in production; upstream alerts should flag Redis outage.
            return JSONResponse({"detail": "Rate limiter unavailable"}, status_code=503)
        if count > limit:
            retry = window - int(time.time()) % window
            return JSONResponse({"detail": "Too many requests"}, status_code=429,
                                headers={"Retry-After": str(retry)})
        return await call_next(request)
