"""Combines all 7 source adapters' routers into one, for a single
app.include_router() call in main.py. Each adapter still owns its own
route/normalize() independently -- this module is purely aggregation."""
from fastapi import APIRouter

from app.ingest.adapters import (
    cc_adapter,
    oms_adapter,
    payments_adapter,
    pos_adapter,
    returns_adapter,
    webapp_adapter,
    wms_adapter,
)

router = APIRouter()
for adapter_module in (webapp_adapter, pos_adapter, oms_adapter, wms_adapter, payments_adapter, cc_adapter, returns_adapter):
    router.include_router(adapter_module.router)
