from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from yaksha.api.auth import require_token
from yaksha.api.deps import AppSettingsDep, SessionDep, SettingsDep
from yaksha.api.schemas.phone_numbers import NumberState, PhoneNumberRead, PhoneNumbers
from yaksha.db.models import PhoneNumber
from yaksha.simulation import numbers


def state(row: PhoneNumber, now: datetime) -> NumberState:
    if row.conversation_id is not None:
        return NumberState.IN_USE
    if row.available_after is not None and row.available_after > now:
        return NumberState.RESTING
    return NumberState.FREE


router = APIRouter(
    prefix="/phone-numbers", tags=["phone-numbers"], dependencies=[Depends(require_token)]
)


@router.get("")
async def list_phone_numbers(
    session: SessionDep, settings: SettingsDep, app: AppSettingsDep
) -> PhoneNumbers:
    """The numbers Yaksha may use, as the worker last synced them from the Plivo account."""
    app_id = settings.plivo_app_id
    rows = await numbers.enabled_pool(session)
    now = datetime.now(UTC)
    return PhoneNumbers(
        items=[
            PhoneNumberRead(
                number=row.number,
                alias=row.alias,
                region=row.region,
                application_id=row.application_id,
                application_name=row.application_name,
                on_outbound_application=app_id is not None and row.application_id == app_id,
                state=state(row, now),
            )
            for row in rows
        ],
        outbound_problem=await numbers.outbound_problem(session, settings, app),
        rest_s=app.phone.number_rest_s,
    )
