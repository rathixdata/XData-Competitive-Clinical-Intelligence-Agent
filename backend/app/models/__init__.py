"""Import every model so Base.metadata is complete (alembic, tests)."""

from app.models.entities import (  # noqa: F401
    Asset,
    AssetProfileVersion,
    Catalyst,
    Company,
    Concept,
    Disclosure,
    EntityAlias,
    EntityLink,
    ProfileFieldDefinition,
    Publication,
    RegulatoryEvent,
    Relationship,
    Trial,
)
from app.models.intelligence import (  # noqa: F401
    AskSession,
    AskTurn,
    Claim,
    Feedback,
    FeedbackDataset,
    GeneratedArtifact,
    GenerationRecord,
    IntelligenceEvent,
    ModelRelease,
)
from app.models.landscape import (  # noqa: F401
    AlertPolicy,
    Landscape,
    LandscapeMember,
    LandscapeTemplate,
    Notification,
    NotifiedEventState,
    ProximityRule,
    Report,
    SavedView,
    Watchlist,
    WatchlistItem,
)
from app.models.rag import DocumentChunk  # noqa: F401
from app.models.sources import (  # noqa: F401
    ChangeEvent,
    ConnectorConfig,
    ConnectorRun,
    SourceDocument,
    SourceSnapshot,
)
from app.models.tenancy import (  # noqa: F401
    ApiKey,
    AuditLog,
    FeatureFlag,
    IdempotencyRecord,
    Tenant,
    UsageRecord,
    User,
)
