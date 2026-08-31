from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.db import get_session
from app.models.auth import User
from app.models.case import Customer
from app.models.enums import UserRole
from app.seed.synthetic_data import seed_all

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/seed")
async def seed_demo_data(
    session: AsyncSession = Depends(get_session), _: User = Depends(require_roles(UserRole.ADMIN))
) -> dict:
    """Seeds the representative multi-case dataset described in
    app/seed/synthetic_data.py. Guarded against re-seeding: if the first
    demo customer already exists, returns without creating duplicates --
    re-running this only ever produces one copy of the dataset."""
    existing = await session.scalar(select(Customer).where(Customer.external_customer_id == "cust-1001"))
    if existing is not None:
        return {"status": "already_seeded", "count": 0}
    result = await seed_all(session)
    return {"status": "seeded", **result}
