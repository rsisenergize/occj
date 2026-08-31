# Omnichannel Customer Journey Investigation & Recovery Agent

An evidence-backed operational workspace that reconstructs a customer's journey
across web/app, store, orders, fulfillment, payments, contact-centre and
returns systems; locates where it failed; and coordinates an authorized
recovery — while making every fact, inference, and decision explicit and
replayable.

## Architecture

```
React (Vite/TS) ──deploy──> Vercel (static)
   │  REST                     │  (planned) subscribes directly to Supabase Realtime
   ▼                           ▼
FastAPI backend ──deploy──> Railway
   │
   ├─ Supabase Postgres (pooled/PgBouncer conn string) — domain model, provenance, audit log
   ├─ Groq (OpenAI-compatible) — hypothesis rationale, NBA explanations, customer messages
   ├─ Freshdesk connector — contact-centre evidence + customer notification channel
   ├─ Freshservice connector — ITSM: incident correlation (evidence) + escalation (action)
   └─ Mock connectors — web/app analytics, POS, OMS, fulfillment/carrier, payments
      (seeded, reproducible failure scenarios: timeout / fail-then-succeed / partial-failure)
```

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

## Deployment

**Frontend → Vercel.** Connect this repo, set the project root to `frontend/`,
and set `VITE_API_BASE_URL` to the deployed backend URL. `frontend/vercel.json`
handles SPA routing.

**Backend → Railway.** Connect this repo with the service root at `backend/`
(uses `backend/Dockerfile`, which runs `alembic upgrade head` before serving —
staging/prod never falls back to `create_all`). Set `ENVIRONMENT=staging`,
`DATABASE_URL` to Supabase's **pooled** connection string (PgBouncer,
transaction mode, port 6543 — a serverless-adjacent multi-instance deployment
exhausts Postgres's connection limit fast on the direct/unpooled string),
`JWT_SECRET`, `CORS_ORIGINS` (the Vercel origin), and whichever of
`LLM_*` / `FRESHDESK_*` / `FRESHSERVICE_*` you have credentials for.

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
  alembic/          Migrations (the only schema path outside local dev)
  tests/            pytest suite
frontend/
  src/
    api/, auth/, components/, pages/, types.ts
docker-compose.yml  Local full-stack parity (Postgres + backend + frontend)
```
