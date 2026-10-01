from fastapi import APIRouter

from app.models.runner import Runner
from app.services import services

router = APIRouter(prefix="/runners", tags=["runners"])


@router.get("", response_model=list[Runner], response_model_by_alias=True)
async def list_runners() -> list[Runner]:
    return await services.runners.list()
