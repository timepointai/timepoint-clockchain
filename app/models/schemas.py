from pydantic import BaseModel, Field


class MomentSummary(BaseModel):
    path: str
    name: str
    one_liner: str = ""
    year: int = 0
    month: int = 0
    day: int = 0
    layer: int = 0
    visibility: str = "private"
    source_type: str = "historical"
    image_url: str | None = None


class EdgeResponse(BaseModel):
    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    theme: str = ""
    description: str = ""
    created_by: str = "auto"


class MomentResponse(BaseModel):
    path: str
    name: str
    one_liner: str = ""
    year: int = 0
    month: int = 0
    day: int = 0
    time: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    layer: int = 0
    visibility: str = "private"
    tags: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    created_by: str = ""
    source_type: str = "historical"
    confidence: float | None = None
    source_run_id: str | None = None
    tdf_hash: str = ""
    image_url: str | None = None
    created_at: str = ""
    published_at: str = ""
    schema_version: str = "0.1"
    text_model: str = ""
    image_model: str = ""
    model_provider: str = ""
    model_permissiveness: str = "unknown"
    generation_id: str = ""
    proposed_by: str = ""
    challenged_by: list[str] = Field(default_factory=list)
    status: str = "proposed"
    edges: list[EdgeResponse] = Field(default_factory=list)


class BrowseItem(BaseModel):
    segment: str
    count: int
    label: str = ""


class BrowseResponse(BaseModel):
    prefix: str
    items: list[BrowseItem] = Field(default_factory=list)


class SearchResult(BaseModel):
    path: str
    name: str
    one_liner: str = ""
    score: float = 0.0
    image_url: str | None = None


class GraphStatsResponse(BaseModel):
    total_nodes: int
    total_edges: int
    layer_counts: dict[str, int] = Field(default_factory=dict)
    edge_type_counts: dict[str, int] = Field(default_factory=dict)
    source_type_counts: dict[str, int] = Field(default_factory=dict)


class MomentListItem(BaseModel):
    path: str
    name: str
    one_liner: str = ""
    year: int | None = None
    month: str = ""
    day: int = 0
    country: str = ""
    region: str = ""
    city: str = ""
    source_type: str = "historical"
    confidence: float | None = None
    image_url: str | None = None
    schema_version: str = "0.1"
    text_model: str = ""
    image_model: str = ""
    status: str = "proposed"


class PaginatedMomentsResponse(BaseModel):
    items: list[MomentListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class EnhancedStatsResponse(GraphStatsResponse):
    date_range: dict = Field(default_factory=dict)
    avg_confidence: float | None = None
    last_updated: str | None = None
    nodes_with_images: int = 0
    schema_version_counts: dict[str, int] = Field(default_factory=dict)
    text_model_counts: dict[str, int] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    query: str
    preset: str = "default"
    visibility: str = "private"


class JobResponse(BaseModel):
    job_id: str
    status: str
    path: str | None = None
    error: str | None = None
    created_at: str = ""
    completed_at: str | None = None


class BulkGenerateRequest(BaseModel):
    queries: list[GenerateRequest]


class PublishRequest(BaseModel):
    visibility: str = "public"


class TodayResponse(BaseModel):
    month: int
    day: int
    events: list[MomentSummary] = Field(default_factory=list)


class SubgraphNodeInput(BaseModel):
    id: str
    name: str = ""
    year: int | None = None
    month: str = ""
    month_num: int = 0
    day: int = 0
    time: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    slug: str = ""
    layer: int = 0
    visibility: str = "public"
    tags: list[str] = Field(default_factory=list)
    one_liner: str = ""
    figures: list[str] = Field(default_factory=list)
    source_type: str = "historical"
    confidence: float | None = None
    source_run_id: str | None = None
    tdf_hash: str | None = None
    schema_version: str = "0.2"
    text_model: str = ""
    image_model: str = ""
    model_provider: str = ""
    model_permissiveness: str = "unknown"
    generation_id: str = ""


class SubgraphEdgeInput(BaseModel):
    source: str
    target: str
    type: str = "thematic"
    weight: float = 1.0
    theme: str = ""
    description: str = ""
    created_by: str = "auto"


class SubgraphIngestRequest(BaseModel):
    nodes: list[SubgraphNodeInput] = Field(default_factory=list)
    edges: list[SubgraphEdgeInput] = Field(default_factory=list)


class SubgraphIngestResponse(BaseModel):
    ingested_nodes: int = 0
    ingested_edges: int = 0


# --- Agent / Multi-Writer schemas ---


class AgentRegisterRequest(BaseModel):
    agent_name: str
    permissions: str = "write"


class AgentRegisterResponse(BaseModel):
    agent_id: int
    agent_name: str
    token: str
    permissions: str = "write"


class AgentInfo(BaseModel):
    agent_id: int
    agent_name: str
    permissions: str = "write"
    is_active: bool = True
    created_at: str = ""


class AgentListResponse(BaseModel):
    agents: list[AgentInfo] = Field(default_factory=list)
    total: int = 0


# --- Propose/Challenge protocol schemas ---

VALID_MOMENT_STATUSES = {"proposed", "challenged", "verified", "alternative"}


class ProposeRequest(BaseModel):
    """Submit a new moment for consideration."""
    id: str = Field(..., description="Spatiotemporal path ID for the moment")
    name: str = ""
    one_liner: str = ""
    year: int | None = None
    month: str = ""
    month_num: int = 0
    day: int = 0
    time: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    slug: str = ""
    layer: int = 0
    visibility: str = "public"
    tags: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    source_type: str = "historical"
    confidence: float | None = None
    source_run_id: str | None = None
    schema_version: str = "0.2"
    text_model: str = ""
    image_model: str = ""
    model_provider: str = ""
    model_permissiveness: str = "unknown"
    generation_id: str = ""
    edges: list[SubgraphEdgeInput] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="Evidence/source URLs")


class ProposeResponse(BaseModel):
    path: str
    name: str
    status: str = "proposed"
    proposed_by: str = ""


class ChallengeRequest(BaseModel):
    """Dispute an existing moment with a competing version."""
    competing_moment: ProposeRequest = Field(
        ..., description="The challenger's alternative version"
    )
    reason: str = Field("", description="Reason for the challenge")


class ChallengeResponse(BaseModel):
    original_moment_id: str
    original_status: str = "challenged"
    competing_moment_id: str
    competing_status: str = "proposed"
    challenged_by: str = ""


class VerifyResponse(BaseModel):
    moment_id: str
    status: str = "verified"
    verified_by: str = ""


class ReconcileRequest(BaseModel):
    """Resolve two competing moments — pick a winner."""
    winner_id: str
    loser_id: str
    reason: str = ""


class ReconcileResponse(BaseModel):
    winner_id: str
    winner_status: str = "verified"
    loser_id: str
    loser_status: str = "alternative"
    reconciled_by: str = ""


class MomentHistoryEntry(BaseModel):
    action: str  # proposed, challenged, verified, reconciled
    agent: str = ""
    timestamp: str = ""
    details: str = ""


class MomentHistoryResponse(BaseModel):
    moment_id: str
    status: str = ""
    history: list[MomentHistoryEntry] = Field(default_factory=list)
