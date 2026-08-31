from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models.case import Case, Customer
from app.models.enums import CaseTriggerType


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        import app.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


def ago(base: datetime, **kwargs) -> datetime:
    return base - timedelta(**kwargs)


async def make_customer(session: AsyncSession, **kwargs) -> Customer:
    defaults = dict(external_customer_id="cust-test", display_name="Test Customer", tier="standard")
    defaults.update(kwargs)
    customer = Customer(**defaults)
    session.add(customer)
    await session.flush()
    return customer


async def make_case(session: AsyncSession, customer: Customer, **kwargs) -> Case:
    defaults = dict(
        customer_id=customer.id,
        trigger_type=CaseTriggerType.MANUAL,
        last_activity_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    case = Case(**defaults)
    session.add(case)
    await session.flush()
    return case
