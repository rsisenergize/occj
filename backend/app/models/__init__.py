"""Import every model module so Base.metadata sees all tables (needed by
db.init_db's create_all and by Alembic's autogenerate)."""
from app.models.audit import AuditEntry
from app.models.auth import User
from app.models.case import Case, Customer
from app.models.canonical import CanonicalEvent, UncertaintyFlag
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import EvidenceLink, Hypothesis
from app.models.impact import ImpactAssessment
from app.models.action import ActionRequest, Approval, ToolExecution

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
