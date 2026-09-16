import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


async def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected: str = request.app.state.settings.api_token.get_secret_value()
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
