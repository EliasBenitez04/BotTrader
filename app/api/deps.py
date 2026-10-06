import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_admin_token(
    x_bot_token: Annotated[str | None, Header(alias="X-Bot-Token")] = None,
) -> None:
    settings = get_settings()
    configured = settings.bot_admin_token

    if not configured or configured == "change-this-token":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BOT_ADMIN_TOKEN must be configured before administrative actions are enabled",
        )

    if x_bot_token is None or not secrets.compare_digest(x_bot_token, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Bot-Token",
        )
