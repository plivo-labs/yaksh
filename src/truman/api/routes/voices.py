from fastapi import APIRouter, Depends, Response

from truman.api.auth import require_token
from truman.api.deps import VoiceCatalogsDep
from truman.api.pagination import Page, PageDep
from truman.domain.personas import Language, VoiceProvider
from truman.domain.voices import VoiceInfo, VoicePreview
from truman.simulation import personas

router = APIRouter(prefix="/voices", tags=["voices"], dependencies=[Depends(require_token)])


@router.get("")
async def list_voices(
    provider: VoiceProvider,
    catalogs: VoiceCatalogsDep,
    page: PageDep,
    language: Language | None = None,
) -> Page[VoiceInfo]:
    voices, total = await personas.list_voices(
        catalogs, provider, offset=page.offset, limit=page.page_size, language=language
    )
    return Page.of(voices, total, page)


@router.post("/preview", response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def preview_voice(command: VoicePreview, catalogs: VoiceCatalogsDep) -> Response:
    audio = await personas.preview_voice(catalogs, command.voice, command.language)
    return Response(content=audio, media_type="audio/wav")
