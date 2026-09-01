"""Integration test for the DB-level append-only enforcement (Postgres
trigger on ingest_log_versions / ingest_order_versions -- see the Alembic
migration ba9ae356323d). Genuinely requires a live Postgres instance: the
trigger is Postgres-only by design (see the migration's comment on why
this isn't portable to SQLite), so this test is honestly skipped, not
faked, when one isn't configured -- set TEST_POSTGRES_URL to run it, e.g.
against a local `docker run postgres:17` or the Supabase project's pooled
connection string.
"""
import os
import uuid

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="TEST_POSTGRES_URL not set -- the append-only trigger is Postgres-only and cannot be verified against SQLite",
)


@pytest.fixture
async def pg_engine():
    engine = create_async_engine(TEST_POSTGRES_URL)
    yield engine
    await engine.dispose()


async def test_update_on_log_version_is_rejected(pg_engine):
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        timeline_id = uuid.uuid4().hex
        customer_id = uuid.uuid4().hex
        log_id = uuid.uuid4().hex
        version_id = uuid.uuid4().hex
        await conn.execute(
            text(
                "INSERT INTO customers (id, external_customer_id, display_name, tier, created_at) "
                "VALUES (:id, :ext, :name, 'standard', now())"
            ),
            {"id": customer_id, "ext": f"cust-{customer_id[:8]}", "name": "Append Only Test"},
        )
        await conn.execute(
            text("INSERT INTO ingest_timelines (id, customer_id, status, schema_version, created_at) VALUES (:id, :cid, 'open', 1, now())"),
            {"id": timeline_id, "cid": customer_id},
        )
        await conn.execute(
            text(
                "INSERT INTO ingest_logs (id, timeline_id, customer_id, order_id, source_system, fact_type, created_at) "
                "VALUES (:id, :tid, :cid, NULL, 'oms', 'order_status', now())"
            ),
            {"id": log_id, "tid": timeline_id, "cid": customer_id},
        )
        await conn.execute(
            text(
                "INSERT INTO ingest_log_versions (id, log_id, version_no, payload, event_time, received_time, timezone, provenance, created_at) "
                "VALUES (:id, :lid, 1, '{}'::jsonb, now(), now(), 'UTC', 'oms', now())"
            ),
            {"id": version_id, "lid": log_id},
        )

    async with pg_engine.begin() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(
                text("UPDATE ingest_log_versions SET payload = '{\"tampered\": true}'::jsonb WHERE id = :id"),
                {"id": version_id},
            )


async def test_delete_on_order_version_is_rejected(pg_engine):
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        customer_id = uuid.uuid4().hex
        timeline_id = uuid.uuid4().hex
        order_id = uuid.uuid4().hex
        version_id = uuid.uuid4().hex
        await conn.execute(
            text(
                "INSERT INTO customers (id, external_customer_id, display_name, tier, created_at) "
                "VALUES (:id, :ext, :name, 'standard', now())"
            ),
            {"id": customer_id, "ext": f"cust-{customer_id[:8]}", "name": "Append Only Test 2"},
        )
        await conn.execute(
            text("INSERT INTO ingest_timelines (id, customer_id, status, schema_version, created_at) VALUES (:id, :cid, 'open', 1, now())"),
            {"id": timeline_id, "cid": customer_id},
        )
        await conn.execute(
            text(
                "INSERT INTO ingest_orders (id, timeline_id, customer_id, order_ref, created_at) "
                "VALUES (:id, :tid, :cid, :ref, now())"
            ),
            {"id": order_id, "tid": timeline_id, "cid": customer_id, "ref": f"ord-{order_id[:8]}"},
        )
        await conn.execute(
            text(
                "INSERT INTO ingest_order_versions (id, order_id, version_no, status, payload, event_time, received_time, timezone, provenance, created_at) "
                "VALUES (:id, :oid, 1, 'placed', '{}'::jsonb, now(), now(), 'UTC', 'oms', now())"
            ),
            {"id": version_id, "oid": order_id},
        )

    async with pg_engine.begin() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text("DELETE FROM ingest_order_versions WHERE id = :id"), {"id": version_id})
