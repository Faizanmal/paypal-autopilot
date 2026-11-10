from fastapi import APIRouter

from app.api.system import health, ready
from app.modules.ai.router import router as ai_router
from app.modules.ai.studio import router as studio_router
from app.modules.autopilot.router import router as autopilot_router
from app.modules.finance.router import router as finance_router
from app.modules.identity.router import router as identity_router
from app.modules.office.router import router as office_router
from app.modules.spendpilot.router import router as spendpilot_router
from app.modules.trustflow.router import router as trustflow_router

api_router = APIRouter(prefix="/api/v1")
api_router.add_api_route("/health", health, methods=["GET"], tags=["system"], operation_id="api_health")
api_router.add_api_route("/ready", ready, methods=["GET"], tags=["system"], operation_id="api_ready")
api_router.include_router(identity_router)
api_router.include_router(ai_router)
api_router.include_router(studio_router)
api_router.include_router(trustflow_router)
api_router.include_router(autopilot_router)
api_router.include_router(spendpilot_router)
api_router.include_router(office_router)
api_router.include_router(finance_router)
