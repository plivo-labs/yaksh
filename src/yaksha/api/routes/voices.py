import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from yaksha.api.auth import require_token
from yaksha.api.deps import SessionDep, VoiceClientsDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.pagination import Page, PageDep
from yaksha.api.schemas.voices import VoiceRead
from yaksha.domain.languages import Language
from yaksha.domain.voices import (
    PROVIDER_VOICE_ID,
    ProviderVoice,
    VoiceCreate,
    VoicePreview,
    VoiceProvider,
    VoiceUpdate,
)
from yaksha.simulation import voices

router = APIRouter(prefix="/voices", tags=["voices"], dependencies=[Depends(require_token)])


@router.get("")
async def list_voices(
    session: SessionDep, page: PageDep, language: Language | None = None
) -> Page[VoiceRead]:
    rows, total = await voices.list_voices(
        session, offset=page.offset, limit=page.page_size, language=language
    )
    return Page.of([VoiceRead.model_validate(row) for row in rows], total, page)


@router.get("/lookup", responses=UNAVAILABLE)
async def lookup_voice(
    provider: VoiceProvider,
    provider_voice_id: Annotated[str, Query(pattern=PROVIDER_VOICE_ID)],
    clients: VoiceClientsDep,
) -> ProviderVoice:
    """What the provider says about a voice on the account. Saves nothing."""
    return await voices.lookup_voice(clients, provider, provider_voice_id)


@router.post("", status_code=status.HTTP_201_CREATED, responses=UNAVAILABLE)
async def create_voice(
    command: VoiceCreate, session: SessionDep, clients: VoiceClientsDep
) -> VoiceRead:
    return VoiceRead.model_validate(await voices.create_voice(session, clients, command))


@router.patch("/{voice_id}")
async def update_voice(voice_id: uuid.UUID, update: VoiceUpdate, session: SessionDep) -> VoiceRead:
    return VoiceRead.model_validate(await voices.update_voice(session, voice_id, update))


@router.delete("/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(voice_id: uuid.UUID, session: SessionDep) -> None:
    await voices.delete_voice(session, voice_id)


@router.post(
    "/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}, **UNAVAILABLE},
)
async def preview_voice(command: VoicePreview, clients: VoiceClientsDep) -> Response:
    audio = await voices.preview_voice(
        clients, command.voice, command.language, command.background_noise
    )
    return Response(content=audio, media_type="audio/wav")
