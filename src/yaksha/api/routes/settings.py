import secrets as random_secrets
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.api.auth import require_token
from yaksha.api.deps import AppSettingsDep, SessionDep
from yaksha.api.errors import CLIENT_ERRORS, UNAVAILABLE, json_errors
from yaksha.api.schemas.settings import (
    Efforts,
    ImportResult,
    Models,
    PlivoAccount,
    ProviderTest,
    SecretWrite,
    SettingsImport,
    SettingsRead,
    SigningKey,
)
from yaksha.domain.errors import UnavailableError, ValidationError
from yaksha.domain.settings import (
    TRIGGER_SECRET,
    TRIGGER_SECRET_NAME,
    AppSettings,
    SecretName,
    SettingsValues,
)
from yaksha.integrations import provider_checks
from yaksha.integrations.provider_checks import ProviderCheckError
from yaksha.settings import service, store
from yaksha.settings.cipher import Cipher

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_token)])

TriggerSecretName = Annotated[str, Path(pattern=TRIGGER_SECRET_NAME.pattern + "$")]


def cipher_of(request: Request) -> Cipher:
    return request.app.state.source.cipher


CipherDep = Annotated[Cipher, Depends(cipher_of)]


@router.get("")
async def get_settings(settings: AppSettingsDep) -> SettingsRead:
    return SettingsRead.of(settings)


@router.put("/values")
async def put_values(
    values: SettingsValues, session: SessionDep, cipher: CipherDep
) -> SettingsRead:
    """Replace every setting that is not a secret. A change applies to the next call."""
    return SettingsRead.of(
        await store.change(session, cipher, values=values.model_dump(mode="json"))
    )


@router.put("/secrets/{name}")
async def put_secret(
    name: SecretName,
    secret: SecretWrite,
    settings: AppSettingsDep,
    session: SessionDep,
    cipher: CipherDep,
) -> SettingsRead:
    """Check the key with its provider, then save it. A key the provider refuses is not
    saved."""
    return SettingsRead.of(
        await checked_change(settings, session, cipher, secrets={name: secret.value})
    )


@router.put("/plivo")
async def put_plivo_account(
    account: PlivoAccount, settings: AppSettingsDep, session: SessionDep, cipher: CipherDep
) -> SettingsRead:
    """Save the Auth ID and Auth token of a Plivo account together, after Plivo accepts them;
    this is how to move to another account."""
    secrets: dict[str, str | None] = {
        SecretName.PLIVO_AUTH_ID: account.auth_id,
        SecretName.PLIVO_AUTH_TOKEN: account.auth_token,
    }
    return SettingsRead.of(await checked_change(settings, session, cipher, secrets=secrets))


async def checked_change(
    settings: AppSettings,
    session: AsyncSession,
    cipher: Cipher,
    *,
    values: Mapping[str, Any] | None = None,
    secrets: Mapping[str, str | None],
) -> AppSettings:
    """Check every new key with its provider, then save the change; nothing is saved when a
    check fails."""
    try:
        await service.check_secrets(store.planned(settings, values, secrets), secrets)
    except ProviderCheckError as error:
        raise ValidationError(f"{error}; nothing was saved") from None
    return await store.change(session, cipher, values=values, secrets=secrets)


@router.delete("/secrets/{name}")
async def delete_secret(name: SecretName, session: SessionDep, cipher: CipherDep) -> SettingsRead:
    return SettingsRead.of(await store.change(session, cipher, secrets={name: None}))


@router.put("/trigger-secrets/{name}")
async def put_trigger_secret(
    name: TriggerSecretName, secret: SecretWrite, session: SessionDep, cipher: CipherDep
) -> SettingsRead:
    """A value a trigger template uses as {{secrets.NAME}}."""
    return SettingsRead.of(
        await store.change(session, cipher, secrets={TRIGGER_SECRET + name: secret.value})
    )


@router.delete("/trigger-secrets/{name}")
async def delete_trigger_secret(
    name: TriggerSecretName, session: SessionDep, cipher: CipherDep
) -> SettingsRead:
    return SettingsRead.of(
        await store.change(session, cipher, secrets={TRIGGER_SECRET + name: None})
    )


@router.post("/signing-key", status_code=status.HTTP_201_CREATED)
async def new_signing_key(session: SessionDep, cipher: CipherDep) -> SigningKey:
    """Make a new key that signs every outbound trigger, replacing the old one. The response
    is the only time the key is shown."""
    key = f"whsec_{random_secrets.token_urlsafe(32)}"
    await store.change(session, cipher, secrets={SecretName.TRIGGER_SIGNING_KEY: key})
    return SigningKey(key=key)


@router.post("/providers/{provider}/test")
async def test_provider(provider: service.Provider, settings: AppSettingsDep) -> ProviderTest:
    """Use the saved settings of one provider for a small piece of real work. The provider
    may charge for it."""
    try:
        detail = await service.test_provider(settings, provider)
    except ProviderCheckError as error:
        return ProviderTest(provider=provider, ok=False, detail=str(error))
    return ProviderTest(provider=provider, ok=True, detail=detail)


def llm_key(settings: AppSettings) -> str:
    if settings.secrets.llm_api_key is None:
        raise UnavailableError("the LLM provider key is not saved")
    return settings.secrets.llm_api_key.get_secret_value()


@router.get("/models", responses=UNAVAILABLE)
async def list_models(settings: AppSettingsDep) -> Models:
    """The models the LLM provider lists. A deployment name the list lacks, as on Azure,
    can still be saved."""
    try:
        return Models(
            models=await provider_checks.llm_models(settings.llm.base_url, llm_key(settings))
        )
    except ProviderCheckError as error:
        raise UnavailableError(str(error)) from None


@router.get("/models/{model}/efforts", responses=UNAVAILABLE)
async def model_efforts(model: str, settings: AppSettingsDep) -> Efforts:
    """The reasoning efforts the model takes. It sends one short request for each effort."""
    try:
        efforts = await provider_checks.reasoning_efforts(
            settings.llm.base_url, llm_key(settings), model
        )
    except ProviderCheckError as error:
        raise UnavailableError(str(error)) from None
    return Efforts(model=model, efforts=efforts)


@router.get(
    "/export",
    response_class=PlainTextResponse,
    responses={
        200: {"content": {"application/yaml": {}}, "description": "The settings as YAML."},
        **json_errors(CLIENT_ERRORS),
    },
)
async def export_settings(settings: AppSettingsDep) -> PlainTextResponse:
    """The values that differ from the defaults, and each saved secret as a ${NAME}
    placeholder; never a secret's value."""
    return PlainTextResponse(service.export_document(settings), media_type="application/yaml")


@router.post("/import")
async def import_settings(
    request: SettingsImport, settings: AppSettingsDep, session: SessionDep, cipher: CipherDep
) -> ImportResult:
    """Apply a YAML settings document: every key is checked with its provider first, and
    nothing is saved unless every check passes."""
    plan = service.parse_document(request.document, request.env)
    changes = service.describe_changes(settings, store.planned(settings, plan.values, plan.secrets))
    if request.dry_run:
        return ImportResult(
            changes=changes, skipped=plan.skipped, settings=SettingsRead.of(settings)
        )
    saved = await checked_change(
        settings, session, cipher, values=plan.values, secrets=plan.secrets
    )
    return ImportResult(changes=changes, skipped=plan.skipped, settings=SettingsRead.of(saved))
