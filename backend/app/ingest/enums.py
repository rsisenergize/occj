from enum import StrEnum


class IngestSourceSystem(StrEnum):
    """The 7 source systems, using the short codes this module's spec names
    adapters after -- deliberately a separate enum from
    app.models.enums.SourceType (the older pipeline's 8-value enum with
    different naming), so this package has no coupling to that one."""

    WEBAPP = "webapp"
    POS = "pos"
    OMS = "oms"
    WMS = "wms"
    PAYMENTS = "payments"
    CC = "cc"
    RETURNS = "returns"


class TimelineStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class ConflictResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
