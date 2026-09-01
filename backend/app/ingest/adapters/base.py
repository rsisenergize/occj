"""Shared adapter plumbing: webhook signature verification, ISO-8601
parsing, and a tiny router-factory so each of the 7 adapter files only has
to define normalize() plus a couple of constants -- normalize() stays a
pure, trivially unit-testable function (raw dict in, CanonicalEvent out)
per the spec's testing checklist, with everything HTTP-shaped factored out
here."""
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import get_settings
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent
from app.ingest.subscriber import streamer

logger = logging.getLogger(__name__)
settings = get_settings()

NormalizeFn = Callable[[dict], CanonicalEvent]


def parse_iso(value: str) -> datetime:
    """Accepts a trailing 'Z' as well as an explicit offset."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def verify_signature(request: Request, x_signature: str | None = Header(default=None)) -> bytes:
    """Returns the raw request body after verifying its HMAC-SHA256
    signature (header: X-Signature = hex(HMAC-SHA256(secret, body))). If
    INGEST_WEBHOOK_SECRET is unset (local dev default), verification is
    skipped -- see config.py's comment; this is a real gap to close before
    handling non-synthetic traffic, not a stance for production."""
    body = await request.body()
    if not settings.ingest_webhook_secret:
        return body
    if not x_signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Signature header")
    expected = hmac.new(settings.ingest_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")
    return body


def build_webhook_router(*, source: IngestSourceSystem, path: str, normalize: NormalizeFn) -> APIRouter:
    """One POST route: verify signature -> parse JSON -> normalize() ->
    publish -> 202. Adapters never call the Reconciliation Engine directly
    -- this is the only thing a webhook handler is allowed to do besides
    validation, per spec §7's explicit constraint."""
    router = APIRouter(prefix="/ingest", tags=["ingest-webhooks"])

    async def webhook(body: bytes = Depends(verify_signature)) -> dict:
        try:
            raw = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body") from exc
        try:
            event = normalize(raw)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Payload failed normalization: {exc}") from exc
        await streamer.publish(event)
        return {"status": "accepted", "source_system": source.value, "fact_type": event.fact_type}

    router.add_api_route(
        path, webhook, methods=["POST"], status_code=status.HTTP_202_ACCEPTED, name=f"ingest_{source.value}_webhook"
    )
    return router
