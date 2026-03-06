import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _get_key(request: Request) -> str:
    key = request.headers.get("X-Service-Key")
    if key:
        return "auth:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return get_remote_address(request) or "127.0.0.1"


limiter = Limiter(key_func=_get_key)
