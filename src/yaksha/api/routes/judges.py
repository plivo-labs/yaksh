from fastapi import APIRouter, Depends

from yaksha.api.auth import require_token
from yaksha.api.deps import SessionDep, SettingsDep
from yaksha.domain.evaluations import JudgeAgreement
from yaksha.evaluation import labels

router = APIRouter(prefix="/judges", tags=["judges"], dependencies=[Depends(require_token)])


@router.get("/agreement")
async def get_agreement(session: SessionDep, settings: SettingsDep) -> JudgeAgreement:
    """How often blind audit labels agree with each judge version and with the machine's
    scenario verdicts, how often labelers agree, and how much of the offered set is labeled."""
    return await labels.agreement(session, settings.audit_weekly_budget)
