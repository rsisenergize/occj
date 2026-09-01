"""Import every model module so Base.metadata sees all tables (needed by
db.init_db's create_all and by Alembic's autogenerate).

Deliberately does NOT import app.ingest.models here: app.ingest.models
imports app.models.mixins, and importing any submodule of app.models
first runs this __init__.py -- so importing app.ingest.models from inside
this file is a circular import. Instead, every entry point that needs the
full metadata (db.init_db, alembic/env.py) imports app.models AND
app.ingest.models as two separate statements, in that order."""
from app.models.action import ActionRequest, Approval, ToolExecution
from app.models.audit import AuditEntry
from app.models.auth import User
from app.models.canonical import CanonicalEvent, UncertaintyFlag
from app.models.case import Case, Customer
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import EvidenceLink, Hypothesis
from app.models.impact import ImpactAssessment

__all__ = [
    "AuditEntry",
    "User",
    "Case",
    "Customer",
    "CanonicalEvent",
    "UncertaintyFlag",
    "EvidenceRecord",
    "EvidenceLink",
    "Hypothesis",
    "ImpactAssessment",
    "ActionRequest",
    "Approval",
    "ToolExecution",
]
