from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.security.access import require_api_access
from .client import CentralApplicationClient, CentralConnectionError, eligible_douyin_shops


router = APIRouter(prefix="/api/v1/central", tags=["central-connection"],
                   dependencies=[Depends(require_api_access)])


class CentralConnectionStatus(BaseModel):
    state: Literal["not_configured", "connected", "unavailable"]
    authorized_shop_count: int | None = None
    eligible_douyin_shop_count: int | None = None
    reason: str | None = None


def get_central_client(settings: Annotated[Settings, Depends(get_settings)]) -> CentralApplicationClient:
    return CentralApplicationClient(settings)


@router.get("/status", response_model=CentralConnectionStatus)
def central_status(
    response: Response,
    client: Annotated[CentralApplicationClient, Depends(get_central_client)],
) -> CentralConnectionStatus:
    response.headers["Cache-Control"] = "no-store"
    try:
        shops = client.list_shops()
    except CentralConnectionError as error:
        if error.reason == "not_configured":
            return CentralConnectionStatus(state="not_configured")
        return CentralConnectionStatus(state="unavailable", reason=error.reason)
    return CentralConnectionStatus(
        state="connected", authorized_shop_count=len(shops),
        eligible_douyin_shop_count=len(eligible_douyin_shops(shops)),
    )
