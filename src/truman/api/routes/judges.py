from fastapi import APIRouter, Depends

from truman.api.auth import require_token
from truman.api.deps import SessionDep, SettingsDep
from truman.domain.evaluations import JudgeAgreement
from truman.evaluation import labels

router = APIRouter(prefix="/judges", tags=["judges"], dependencies=[Depends(require_token)])


@router.get("/agreement")
async def get_agreement(session: SessionDep, settings: SettingsDep) -> JudgeAgreement:
    """How often blind audit labels agree with each judge version and with the machine's
    scenario verdicts, how often labelers agree, and how much of the offered set is labeled."""
    return await labels.agreement(session, settings.audit_weekly_budget)
