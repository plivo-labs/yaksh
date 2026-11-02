import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yaksh.api.deps import SessionDep
from yaksh.db.models import Labeler, TraceToken
from yaksh.evaluation import labels, trace_store

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


async def require_trace_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> TraceToken:
    """The trace token opens the OTLP endpoint and nothing else. Its route checks it before it
    reads the body, in a session of its own: the connection goes back to the pool before a slow
    upload starts."""
    token = None
    if credentials is not None:
        async with request.app.state.sessionmaker() as session:
            token = await trace_store.token_with(session, credentials.credentials)
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid trace token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


TraceTokenDep = Annotated[TraceToken, Depends(require_trace_token)]
