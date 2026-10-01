from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from truman.api.auth import require_token
from truman.api.deps import SessionDep, SettingsDep
from truman.api.schemas.phone_numbers import NumberState, PhoneNumberRead, PhoneNumbers
from truman.db.models import PhoneNumber
from truman.simulation import numbers


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
async def list_phone_numbers(session: SessionDep, settings: SettingsDep) -> PhoneNumbers:
    """The numbers Truman may use, as the worker last synced them from the Plivo account."""
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
        outbound_problem=await numbers.outbound_problem(session, settings),
        rest_s=settings.number_rest_s,
    )
