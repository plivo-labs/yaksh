from fastapi import APIRouter, Depends

from yaksh.api.auth import require_token
from yaksh.api.deps import AppSettingsDep, SessionDep
from yaksh.domain.evaluations import JudgeAgreement
from yaksh.evaluation import labels

router = APIRouter(prefix="/judges", tags=["judges"], dependencies=[Depends(require_token)])


@router.get("/agreement")
async def get_agreement(session: SessionDep, settings: AppSettingsDep) -> JudgeAgreement:
    """How often blind audit labels agree with each judge version and with the machine's
    scenario verdicts, how often labelers agree, and how much of the offered set is labeled."""
    return await labels.agreement(session, settings.audit.weekly_budget)
