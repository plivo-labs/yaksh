import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yaksh.api.deps import SessionDep
from yaksh.db.models import Labeler
from yaksh.evaluation import labels

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


async def require_labeler(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Labeler:
    """A labeler's token opens the review routes and nothing else."""
    labeler = (
        await labels.labeler_with_token(session, credentials.credentials) if credentials else None
    )
    if labeler is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid labeler token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return labeler


LabelerDep = Annotated[Labeler, Depends(require_labeler)]
