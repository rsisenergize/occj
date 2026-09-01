"""7 per-source adapters, each owning a normalize() function that
translates its source's raw payload shape into the canonical envelope
(app.ingest.schemas.CanonicalEvent) -- see each file's module docstring
for the specific raw-format quirks it handles, per spec §2.1."""
