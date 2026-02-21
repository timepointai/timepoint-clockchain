import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings


async def verify_service_key(
    x_service_key: str = Header(..., alias="X-Service-Key"),
) -> str:
    settings = get_settings()
    if not settings.SERVICE_API_KEY:
        raise HTTPException(status_code=503, detail="Service key not configured")
    if not hmac.compare_digest(x_service_key, settings.SERVICE_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid service key")
    return x_service_key


async def get_user_id(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> str | None:
    return x_user_id
