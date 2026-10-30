"""POST /demo/reset: clear the configured demo dataset's runs so the demo can be replayed.

Guard: it works only while PUBLIC_DEMO_API is on (403 `demo_reset_disabled` otherwise), and only
ever touches the configured `DATASET`. Seed inputs (bank, GL, balances) and all rules stay: learned
rules survive a reset (B-14) and are forgotten with `DELETE /rules`. `audit_log` keeps its history:
the reset itself is logged as a `demo_reset` row.
"""

from fastapi import APIRouter, Depends

from app.api.auth import AuthContext, get_user_or_demo
from app.api.routes.runs import run_store
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.recon.run_store import RunStore
from app.schemas.runs import DemoResetResponse

router = APIRouter(tags=["demo"], dependencies=[Depends(get_user_or_demo)])


@router.post("/demo/reset", response_model=DemoResetResponse)
async def reset_demo(
    auth: AuthContext = Depends(get_user_or_demo),
    store: RunStore = Depends(run_store),
    settings: Settings = Depends(get_settings),
) -> DemoResetResponse:
    if not settings.public_demo_api:
        raise AppError(code="demo_reset_disabled", message="Demo reset needs PUBLIC_DEMO_API", status_code=403)
    runs, kept = await store.reset(settings.dataset, actor=f"user:{auth.user.email}")
    return DemoResetResponse(dataset=settings.dataset, runs_deleted=runs, rules_kept=kept)
