from datetime import datetime

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


class EdgeResponse(BaseModel):
    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    theme: str = ""


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
    tdf_hash: str | None = None
    created_at: str = ""
    published_at: str = ""
    flash_scene: dict | None = None
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


class GraphStatsResponse(BaseModel):
    total_nodes: int
    total_edges: int
    layer_counts: dict[str, int] = Field(default_factory=dict)
    edge_type_counts: dict[str, int] = Field(default_factory=dict)
    source_type_counts: dict[str, int] = Field(default_factory=dict)


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


class SubgraphEdgeInput(BaseModel):
    source: str
    target: str
    type: str = "thematic"
    weight: float = 1.0
    theme: str = ""


class SubgraphIngestRequest(BaseModel):
    nodes: list[SubgraphNodeInput] = Field(default_factory=list)
    edges: list[SubgraphEdgeInput] = Field(default_factory=list)


class SubgraphIngestResponse(BaseModel):
    ingested_nodes: int = 0
    ingested_edges: int = 0
