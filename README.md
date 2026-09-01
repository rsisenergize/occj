# Omnichannel Customer Journey Investigation & Recovery Agent

An evidence-backed operational workspace that reconstructs a customer's journey
across web/app, store, orders, fulfillment, payments, contact-centre and
returns systems; locates where it failed; and coordinates an authorized
recovery — while making every fact, inference, and decision explicit and
replayable.

## Architecture

```
React (Vite/TS) ──deploy──> Railway service #1 (Dockerfile → nginx, static bundle)
   │  REST                     │  (planned) subscribes directly to Supabase Realtime
   ▼                           ▼
FastAPI backend ──deploy──> Railway service #2 (Dockerfile → uvicorn)
   │
   ├─ Supabase Postgres (pooled/PgBouncer conn string) — domain model, provenance, audit log
   ├─ Groq (OpenAI-compatible) — hypothesis rationale, NBA explanations, customer messages
   ├─ Freshdesk connector — contact-centre evidence + customer notification channel
   ├─ Freshservice connector — ITSM: incident correlation (evidence) + escalation (action)
   └─ Mock connectors — web/app analytics, POS, OMS, fulfillment/carrier, payments
      (seeded, reproducible failure scenarios: timeout / fail-then-succeed / partial-failure)
```

Both frontend and backend deploy to **Railway**, as two services in one
project — Railway has no first-class "static site" product, so the frontend
ships as its own Dockerfile-built nginx service rather than a separate static
host. Postgres/Realtime still lives on Supabase (a database is not something
Railway's free/trial tier should be carrying alongside two app services).

**Backend** (`backend/`): FastAPI + SQLAlchemy (async) + Alembic. Runs unmodified
against SQLite (local dev) or Postgres/Supabase (staging/prod) — only
`DATABASE_URL` changes.

**Frontend** (`frontend/`): Vite + React + TypeScript. No UI framework
dependency, hand-rolled CSS. Polls the API every 8s for updates today; the
polling call sites (`CaseListPage`, `CaseDetailPage`, `ApprovalsQueuePage`)
are exactly where a Supabase Realtime subscription would replace it once a
Supabase project is provisioned and connected — see "Realtime" below.

## Domain model & engine pipeline

| Stage | What happens | Module |
|---|---|---|
| Issue reported | Case opens via customer contact, a system-detected anomaly, or manual creation | `app/engine/case_service.py` |
| Journey assembled | Evidence reconciled into a canonical, time-aware timeline; missing/stale/duplicate/contradictory evidence flagged explicitly | `app/reconciliation/reconciler.py` |
| Failure located | LLM proposes evidence-grounded hypotheses (citations to non-existent evidence are dropped); confidence is *always* computed deterministically from the resulting evidence links, never from the model's own opinion | `app/engine/hypothesis_engine.py` |
| Evidence checked / Impact assessed | Explainable composite score: financial exposure × customer-tier weight × (1 + SLA-breach ratio) | `app/engine/impact_engine.py` |
| Recovery options ranked | Tiered, category-specific remedy catalog; ≥$75 (configurable) or any "exceptional" remedy requires approval | `app/engine/recovery_catalog.py` |
| Actions coordinated | Deterministic next-best-action engine (no LLM in the decision loop — only in the narrative text) drives evidence requests, ITSM escalation, approval-gated recovery execution | `app/engine/nba_engine.py`, `app/tools/executor.py` |
| Customer updated | LLM drafts a message grounded *only* in the already-executed action's own data | `app/engine/customer_messaging.py` |
| Outcome retained | Case closes with a frozen summary; audit trail retains everything | `app/audit/` |

Every state-changing event — evidence ingested, hypothesis created/superseded,
action proposed/approved/executed, stage transition — writes one row to the
append-only `audit_entries` table, tagged with an `actor_type` of `system`,
`ai_inference`, `human_input`, `automated_action`, or `human_decision`. That's
what makes `/cases/{id}/replay?as_of=...` able to reconstruct exactly what the
system knew and why it acted at any point in a case's history, purely by
folding the log.

New/corrected evidence that shifts the leading hypothesis's confidence past a
configurable delta (`REEVALUATION_CONFIDENCE_DELTA`) flags the case for
re-evaluation and jumps its displayed stage back to "failure located" —
material changes never sit silently under a stale conclusion.

## Ingestion pipeline v2 (`backend/app/ingest/`)

A second, deliberately additive ingestion/reconciliation pipeline, built to a
separate enterprise-facing spec: **Adapter → in-process Streamer (pub/sub,
not Kafka) → Reconciliation Engine → Postgres (append-only) → Outbox**,
plus a read-only Debug UI to verify it end to end. It runs *alongside* the
pipeline above — nothing in `app/ingest/` is imported by
`app/reconciliation/`, `app/engine/`, or `app/models/`, and nothing in
those imports `app/ingest/`. Two separate customer-journey pipelines
share only the `customers` table (one identity, not two that could drift
apart). A future module is expected to rewire hypothesis/impact/NBA onto
this schema and retire the older one; until then, the live app is
unaffected by anything below.

**Flow:** 7 webhook adapters (`app/ingest/adapters/*.py`, one per source:
`webapp`, `pos`, `oms`, `wms`, `payments`, `cc`, `returns`) each validate
an HMAC signature (`X-Signature` header, skipped when `INGEST_WEBHOOK_SECRET`
is unset) and `normalize()` their source's raw payload into one canonical
envelope (`app/ingest/schemas.py::CanonicalEvent`), then publish to the
in-process `EventStreamer` (`app/ingest/streamer.py`) and return `202`
immediately — reconciliation happens out of band. The streamer fans out to
every independent subscriber (today: just the Reconciliation Engine;
`Audit/Projector` can subscribe later without touching adapter code), with
per-subscriber retry (3 attempts, backoff) and a `dead_letter` table for
anything that still fails. The Reconciliation Engine
(`app/ingest/engine.py`) resolves customer → timeline → order, writes an
append-only `log_version`/`order_version` row, detects conflicts against
the prior version (`app/ingest/materiality.py`), attempts auto-resolution
via a pluggable strategy (`app/ingest/conflict_strategies.py` — ships one
concrete example, trusted-source-precedence for payment amounts), and
writes an `outbox` row — all in one DB transaction (see
`test_outbox_write_is_atomic_with_the_version_it_describes` in
`tests/test_ingest_engine.py` for the rollback proof).

**[LIMITATION: no durability without Kafka.]** Every event lives only in
an in-memory `asyncio.Queue` between publish and consumption. If the
process crashes in that window, the event is lost — there is no
write-ahead log or replay. This is an explicit, scoped trade-off for this
iteration, not an oversight. **Swap-in point for Kafka:** anything holding
an `EventStreamer` only ever calls `.publish(event)` and
`.subscribe(handler, source_systems=...)` (see the `EventBus` protocol in
`streamer.py`) — a future `KafkaEventBus` implementing the same two
methods drops in without touching `adapters/` or `engine.py`.

**Two assumptions worth knowing about, since the spec didn't fully pin
them down:**
- **`log`/`log_version` identity.** The canonical envelope has no
  source-system idempotency key, so a `Log` row is a grouping *slot* keyed
  on `(timeline_id, order_id, source_system, fact_type)` — e.g. "the
  fulfilment_update history for order X" — and every new event under that
  slot becomes a new `LogVersion`, unconditionally. Whether two versions
  actually *disagree* (vs. one being expected progression, like
  `placed → shipped`) is a separate question, answered by
  `materiality.py`'s per-fact-type rules, not by log identity. If your
  source systems instead deliver a stable event ID per correction, log
  identity should be keyed on that instead — this was the more defensible
  choice without one.
- **DB-level append-only enforcement.** The spec asked for
  `REVOKE UPDATE, DELETE` on the connecting role. In Postgres, a `REVOKE`
  never restricts a table's **owner** — and the role migrations run as
  (and the app currently connects as) owns these tables, so that `REVOKE`
  would silently do nothing. Implemented instead as a `BEFORE UPDATE OR
  DELETE` trigger (see migration `ba9ae356323d`) that rejects unconditionally
  for *every* role, including the owner — a stronger guarantee, and one
  that doesn't require provisioning a new cluster-level Postgres role via a
  migration against the managed Supabase instance (a separate, higher-risk
  change). Postgres-only: SQLite has no equivalent, so local dev keeps
  append-only as application discipline only, same as the rest of this
  codebase's `EvidenceRecord`. One consequence: `superseded_by` on
  `LogVersion`/`OrderVersion` is always `NULL` — setting it after the fact
  would itself be a blocked `UPDATE` — so "latest version" is found via
  `MAX(version_no)` instead, which needs no mutation.

**Debugging a stuck/missing event, using the Debug UI** (admin-only, top
nav once logged in as `admin1`): check **Pipeline Health** first — a
source with a stale or `never` "last seen" means its adapter isn't being
called or is failing before `publish()`. If the source shows recent
events but you don't see the fact you expect, check **Dead letters** on
that same page — a non-empty entry means the Reconciliation Engine raised
on that event 3 times (the raw event + exact error is shown, e.g.
`UnresolvableIdentityError` when a WMS-style event's `order_id` doesn't
resolve to any known order yet). If nothing's dead-lettered either, use
**Timeline Explorer** with the customer_id or order_ref to see exactly
what did land — every version, in order, with its `provenance`. **Conflicts**
lists anything flagged as materially different, resolved or not, with the
disagreeing payloads side by side. **Live Ingestion Feed** is the rawest
view — every `log_version`/`order_version` write across all sources,
newest first, filterable by source/customer, click-through to full JSON.

**Running it:** the 7 endpoints are `POST /ingest/{webapp,pos,oms,wms,payments,cc,returns}`
on the same backend service — no separate process. Example:
```bash
curl -X POST http://localhost:8000/ingest/oms \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"cust-1001","ord_id":"ord-5001","stat":"shipped","event_ts":"2026-08-15T18:00:00Z","tz":"UTC"}'
# -> 202 {"status":"accepted","source_system":"oms","fact_type":"order_status"}
```
Tests: `pytest tests/test_ingest_*.py` (unit: adapters' `normalize()`,
materiality rules, conflict strategies, streamer retry/dead-letter/fan-out;
integration: full engine pipeline against SQLite, outbox atomicity). The
two append-only trigger tests (`test_ingest_append_only.py`) require a real
Postgres instance and are skipped, not faked, without
`TEST_POSTGRES_URL` set — SQLite cannot verify a Postgres-only trigger.

## What's real vs. mocked

- **Real, when credentials are configured:** Groq (LLM), Freshdesk (contact-centre
  evidence + customer notification), Freshservice (ITSM correlation + escalation).
- **Always mocked (per the brief's allowance to use representative
  interfaces):** web/app analytics, POS, OMS, fulfillment/carrier, payments.
  Mock connectors use **seeded, not random** failure scenarios
  (`target["_simulate"] = "timeout" | "fail_then_succeed" | "partial_failure"`)
  so retry/timeout/partial-failure recovery is reproducible on demand rather
  than luck-of-the-draw.
- **Graceful degradation everywhere:** with no `LLM_API_KEY` set, hypothesis
  narratives and customer messages fall back to deterministic templates —
  the system is fully demoable with zero external credentials.

## Running locally

### Option A: docker-compose (closest to production topology)

```
docker compose up --build
```

Backend on `:8000`, frontend on `:5173`, Postgres on `:5432`. Set
`LLM_API_KEY`, `FRESHDESK_*`, `FRESHSERVICE_*` in your shell environment
before running to enable real integrations; omit them for the mock/template
fallback path.

### Option B: run backend and frontend directly

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # defaults to SQLite, no external creds needed
alembic upgrade head    # or rely on create_all in ENVIRONMENT=dev (default)
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:5173`, sign in as `agent1` / `demo-pass` (also
`supervisor1`, `finance1`, `admin1` — all same password), and as `admin1`
click **Seed demo data** on the case list to populate 8 representative cases.

### Tests

```bash
cd backend && source .venv/bin/activate && pytest -q      # 24 tests: reconciliation,
                                                             # hypothesis grounding, full
                                                             # pipeline, retry/timeout/
                                                             # partial-failure, RBAC, API
cd frontend && npm run build                                # typecheck + production build
```

## Deployment (Railway + Supabase)

Railway's free offering is a one-time 30-day / $5 usage-credit trial, then an
ongoing ~$1/month "Free" plan (1 vCPU / 0.5GB per service) — enough for a
low-traffic demo, not for guaranteed always-on hosting. Both services below
share whatever credit the account has; the $5/mo Hobby plan is the fallback
if the trial/free credit isn't enough for how long this needs to stay up.

One Railway project, two services, both **Dockerfile-builder** (Railway
auto-detects the `Dockerfile` in each service's root — no `railway.json`
needed):

**Service 1 — backend.** Root directory `backend/`. Runs
`backend/Dockerfile`, which executes `alembic upgrade head` before serving —
staging/prod never falls back to `create_all`. Environment variables:
`ENVIRONMENT=staging`, `DATABASE_URL` = Supabase's **pooled** connection
string (PgBouncer, transaction mode, port 6543 — an unpooled string exhausts
Postgres's connection limit fast once there's more than one backend
instance/worker), `JWT_SECRET`, `CORS_ORIGINS` = the frontend service's
Railway-assigned domain, plus whichever of `LLM_*` / `FRESHDESK_*` /
`FRESHSERVICE_*` you have credentials for. Railway sets `$PORT` itself; the
Dockerfile's `CMD` already binds to it.

**Service 2 — frontend.** Root directory `frontend/`. Runs
`frontend/Dockerfile` (multi-stage: `npm run build`, then nginx serves the
static bundle, listening on Railway's `$PORT` via an nginx template — see
`frontend/nginx-templates/default.conf.template`). Set `VITE_API_BASE_URL`
as a **build-time** variable (Vite bakes it into the JS bundle; it's not
readable at container runtime) to the backend service's Railway domain —
set it *after* the backend service exists so you have that domain to point
at, then deploy the frontend.

**Database → Supabase.** Create a project, grab the pooled connection string
for `DATABASE_URL`. Realtime: the frontend's polling call sites are where a
direct `supabase-js` subscription to Postgres changes would replace polling —
not yet wired up pending a provisioned project, but the seam is intentional
and narrow (three call sites, documented inline).

**Environment variables reference:** `backend/.env.example` documents every
setting (persistence, LLM, Freshdesk/Freshservice, auth, business-rule
thresholds); `frontend/.env.example` has the one frontend variable.

## Repository layout

```
backend/
  app/
    models/        SQLAlchemy domain model (provenance, versioning, audit)
    reconciliation/ Evidence ingestion, canonical timeline, uncertainty detection
    engine/         Hypothesis, impact, NBA, recovery catalog, stage tracking, orchestration
    llm/            OpenAI-compatible client (Groq), degrades to template fallback
    tools/          Connector interface, executor (retry/timeout/idempotency), registry, connectors/
    approvals/      Role-checked approval decision service
    audit/          Append-only writer + replay
    auth/           JWT + bcrypt, RBAC dependencies
    api/routers/    FastAPI routes
    seed/           Synthetic representative dataset
    ingest/         Pipeline v2: adapters/, streamer, reconciliation engine,
                    conflict strategies, debug API -- see its own README section
  alembic/          Migrations (the only schema path outside local dev)
  tests/            pytest suite
frontend/
  src/
    api/, auth/, components/, pages/, types.ts
    pages/debug/    Admin-only Debug UI for the ingest/ pipeline (4 views)
docker-compose.yml  Local full-stack parity (Postgres + backend + frontend)
```
