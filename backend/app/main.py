import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routers import approvals, audit, auth, cases, demo, ingestion
from app.auth.security import hash_password
from app.config import get_settings
from app.db import AsyncSessionLocal, init_db
from app.models.auth import User
from app.models.enums import UserRole

settings = get_settings()

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

# Vercel-hosted frontend origin(s) -- set via env in prod; permissive default
# for local dev only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "dev" else settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(ingestion.router)
app.include_router(demo.router)


DEMO_USERS = [
    ("agent1", UserRole.AGENT, "Alex Agent"),
    ("supervisor1", UserRole.SUPERVISOR, "Sam Supervisor"),
    ("finance1", UserRole.FINANCE_APPROVER, "Farah Finance"),
    ("admin1", UserRole.ADMIN, "Ada Admin"),
]


@app.on_event("startup")
async def on_startup() -> None:
    if settings.environment == "dev":
        # Postgres/Supabase in staging+prod is migrated via Alembic
        # (backend/alembic/), not create_all.
        await init_db()
    async with AsyncSessionLocal() as session:
        for username, role, display_name in DEMO_USERS:
            existing = await session.scalar(select(User).where(User.username == username))
            if existing is None:
                session.add(
                    User(
                        username=username,
                        password_hash=hash_password("demo-pass"),
                        role=role,
                        display_name=display_name,
                    )
                )
        await session.commit()
    logger.info("Startup complete (environment=%s)", settings.environment)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
