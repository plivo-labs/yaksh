from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from yaksh.api.auth import require_token
from yaksh.api.deps import AppSettingsDep, SessionDep, SettingsDep
from yaksh.api.schemas.phone_numbers import (
    ApplicationChoice,
    ApplicationRead,
    NumberState,
    PhoneAccountRead,
    PhoneNumberRead,
    PhoneNumbers,
)
from yaksh.config import Settings
from yaksh.db.models import PhoneNumber
from yaksh.domain.errors import ValidationError
from yaksh.domain.numbers import E164, Owner, PhoneAccountApi, owner
from yaksh.domain.settings import AppSettings
from yaksh.settings import store
from yaksh.simulation import numbers, phone_account

NumberPath = Annotated[str, Path(pattern=E164.__metadata__[0].pattern)]


def state(row: PhoneNumber, now: datetime) -> NumberState:
    if row.conversation_id is not None:
        return NumberState.IN_USE
    if row.available_after is not None and row.available_after > now:
        return NumberState.RESTING
    return NumberState.READY


def account_api(request: Request, app: AppSettingsDep) -> PhoneAccountApi:
    credentials = app.plivo_credentials
    if credentials is None:
        raise ValidationError("add the Plivo Auth ID and Auth token in Settings")
    return request.app.state.providers.phone_account(*credentials)


AccountApiDep = Annotated[PhoneAccountApi, Depends(account_api)]


def chosen_application(app: AppSettings) -> str:
    app_id = app.phone.application_id
    if app_id is None:
        raise ValidationError(numbers.NO_APPLICATION)
    return app_id


def reachable_url(settings: Settings) -> str:
    if settings.public_url is None:
        raise ValidationError("set YAKSH_PUBLIC_URL to the address Plivo can reach")
    return settings.public_url


router = APIRouter(
    prefix="/phone-numbers", tags=["phone-numbers"], dependencies=[Depends(require_token)]
)


async def listing(session: SessionDep, settings: Settings, app: AppSettings) -> PhoneNumbers:
    app_id = app.phone.application_id
    rows = await numbers.account_numbers(session)
    checked_at, check_error = await phone_account.last_check(session)
    now = datetime.now(UTC)
    items = []
    for row in rows:
        who = owner(row.application_id, row.application_name, row.voice, app_id)
        items.append(
            PhoneNumberRead(
                number=row.number,
                alias=row.alias,
                region=row.region,
                owner=who,
                application_id=row.application_id,
                application_name=row.application_name,
                state=state(row, now) if who is Owner.TEST else None,
            )
        )
    return PhoneNumbers(
        items=items,
        application_id=app_id,
        checked_at=checked_at,
        check_error=check_error,
        problem=await numbers.inbound_problem(session, settings, app),
        outbound_problem=await numbers.outbound_problem(session, settings, app),
        rest_s=app.phone.number_rest_s,
    )


@router.get("")
async def list_phone_numbers(
    session: SessionDep, settings: SettingsDep, app: AppSettingsDep
) -> PhoneNumbers:
    """Every number of the phone account with its owner, as the last check found them. A
    number linked to the receiving application is a test number."""
    return await listing(session, settings, app)


@router.post("/check")
async def check_phone_numbers(
    session: SessionDep, settings: SettingsDep, app: AppSettingsDep, api: AccountApiDep
) -> PhoneNumbers:
    """Read the account's numbers again now, to see changes made in the Plivo console."""
    await phone_account.check_numbers(session, api)
    return await listing(session, settings, app)


@router.post("/{number}/use")
async def use_phone_number(
    number: NumberPath,
    session: SessionDep,
    settings: SettingsDep,
    app: AppSettingsDep,
    api: AccountApiDep,
) -> PhoneNumbers:
    """Make a free number a test number: Yaksh links it to the receiving application in
    Plivo. A number another application receives is refused."""
    await phone_account.use_number(session, api, number, chosen_application(app))
    await phone_account.check_numbers(session, api)
    return await listing(session, settings, app)


@router.post("/{number}/stop")
async def stop_phone_number(
    number: NumberPath,
    session: SessionDep,
    settings: SettingsDep,
    app: AppSettingsDep,
    api: AccountApiDep,
) -> PhoneNumbers:
    """Stop using a test number: Yaksh removes its application in Plivo. Refused while a test
    holds the number or it rests after one."""
    await phone_account.stop_number(session, api, number, chosen_application(app))
    await phone_account.check_numbers(session, api)
    return await listing(session, settings, app)


account_router = APIRouter(
    prefix="/phone-account", tags=["phone-account"], dependencies=[Depends(require_token)]
)


async def account_read(
    session: SessionDep, settings: Settings, app: AppSettings, api: PhoneAccountApi | None
) -> PhoneAccountRead:
    app_id = app.phone.application_id
    application = None
    if app_id is not None:
        if api is None:
            application = ApplicationRead(id=app_id, name=None, answer_url=None, problems=[])
        else:
            receiving = await phone_account.receiving_application(api, app_id, settings.public_url)
            found = receiving.application
            application = ApplicationRead(
                id=app_id,
                name=found.name if found else None,
                answer_url=found.answer_url if found else None,
                problems=receiving.problems,
            )
    test_numbers = 0
    if app_id is not None:
        test_numbers = sum(
            1 for row in await numbers.account_numbers(session) if row.application_id == app_id
        )
    return PhoneAccountRead(
        provider="plivo",
        credentials_saved=api is not None,
        application=application,
        test_numbers=test_numbers,
    )


async def choose(
    request: Request,
    session: SessionDep,
    settings: Settings,
    api: PhoneAccountApi,
    app_id: str,
) -> PhoneAccountRead:
    app = await store.change(
        session, request.app.state.source.cipher, values={"phone": {"application_id": app_id}}
    )
    await phone_account.check_numbers(session, api)
    return await account_read(session, settings, app, api)


@account_router.get("")
async def get_phone_account(
    request: Request, session: SessionDep, settings: SettingsDep, app: AppSettingsDep
) -> PhoneAccountRead:
    """The phone account: whether its credentials are saved, and the receiving application
    with why it does not send calls to this install, if it does not."""
    credentials = app.plivo_credentials
    api = request.app.state.providers.phone_account(*credentials) if credentials else None
    return await account_read(session, settings, app, api)


@account_router.get("/applications")
async def list_applications(api: AccountApiDep, settings: SettingsDep) -> list[ApplicationRead]:
    """The applications people may choose to receive test calls, without Plivo CX agents'."""
    found = await phone_account.choosable_applications(api)
    return [
        ApplicationRead(
            id=application.app_id,
            name=application.name,
            answer_url=application.answer_url,
            problems=application.problems(settings.public_url) if settings.public_url else [],
        )
        for application in found
    ]


@account_router.put("/application")
async def choose_application(
    choice: ApplicationChoice,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    api: AccountApiDep,
) -> PhoneAccountRead:
    """Choose the application that receives test calls. Its numbers become the test numbers."""
    if choice.application_id not in {
        application.app_id for application in await phone_account.choosable_applications(api)
    }:
        raise ValidationError(f"the Plivo account has no application {choice.application_id}")
    return await choose(request, session, settings, api, choice.application_id)


@account_router.post("/application/new")
async def make_application(
    request: Request, session: SessionDep, settings: SettingsDep, api: AccountApiDep
) -> PhoneAccountRead:
    """Make an application that sends calls to this install, and choose it."""
    app_id = await phone_account.make_application(api, reachable_url(settings))
    return await choose(request, session, settings, api, app_id)


@account_router.post("/application/fix")
async def fix_application(
    session: SessionDep, settings: SettingsDep, app: AppSettingsDep, api: AccountApiDep
) -> PhoneAccountRead:
    """Point the receiving application's answer and hangup URLs at this install."""
    await phone_account.fix_application(api, chosen_application(app), reachable_url(settings))
    await phone_account.check_numbers(session, api)
    return await account_read(session, settings, app, api)
