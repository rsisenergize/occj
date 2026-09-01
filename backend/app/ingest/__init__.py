"""New ingestion/streaming/reconciliation pipeline: Adapter -> EventStreamer
(in-process pub/sub) -> Reconciliation Engine -> Postgres (append-only) ->
Outbox, plus a read-only Debug UI/API to verify the pipeline end-to-end.

Deliberately additive and self-contained: nothing in this package is
imported by the existing app/reconciliation/, app/engine/, or app/models/
(Case/EvidenceRecord) pipeline, and nothing in this package imports from
those either -- the two pipelines run side by side. The existing pipeline
keeps serving the live app unchanged; this one exists to be validated on
its own via the debug UI before anything downstream (hypothesis/impact/NBA)
is ever rewired onto it.

No LLM/ML anywhere in this package -- every decision here is deterministic,
rule-based logic. See README.md's "Ingestion pipeline v2" section for the
full design writeup, including the two assumptions this package makes
beyond what the spec stated explicitly (log/log_version identity, and the
DB-level append-only enforcement mechanism).
"""
