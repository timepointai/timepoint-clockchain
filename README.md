# timepoint-clockchain

TIMEPOINT's spatiotemporal graph index and autonomous content orchestrator. Maintains an ever-growing NetworkX graph of historical moments, orchestrates scene generation via Flash, and serves browse/search/discovery data to the TIMEPOINT platform.

## Architecture

```
timepoint-clockchain/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, health endpoint
│   ├── api/
│   │   ├── __init__.py      # API router aggregation
│   │   ├── moments.py       # /moments, /browse, /today, /random, /search
│   │   ├── generate.py      # /generate, /jobs, /publish, /bulk-generate, /index
│   │   └── graph.py         # /graph/neighbors, /stats
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── auth.py          # Service key + user ID extraction
│   │   ├── graph.py         # NetworkX graph manager
│   │   ├── url.py           # Canonical temporal URL system
│   │   └── jobs.py          # In-memory job queue
│   ├── workers/
│   │   ├── renderer.py      # Flash HTTP client
│   │   ├── expander.py      # Autonomous graph expansion (OpenRouter)
│   │   ├── judge.py         # LLM content moderation (OpenRouter)
│   │   └── daily.py         # "Today in History" daily worker
│   └── models/
│       └── schemas.py       # Pydantic response/request models
├── data/
│   ├── seeds.json           # 5 seed historical events
│   └── graph.json           # Persisted graph (created on first run)
├── tests/
├── .env.example          # Environment variable template
├── Dockerfile
├── railway.json
└── pyproject.toml
```

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # then fill in your keys
```

## Running

```bash
# Start the service
uvicorn app.main:app --port 8080
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SERVICE_API_KEY` | Yes | | Shared secret for inbound service auth |
| `FLASH_URL` | No | `http://timepoint-flash-deploy.railway.internal:8080` | Flash service URL |
| `FLASH_SERVICE_KEY` | Yes | | Auth key for Flash API calls |
| `DATA_DIR` | No | `./data` | Directory for graph persistence |
| `ENVIRONMENT` | No | `development` | Environment name |
| `DEBUG` | No | `false` | Enable debug logging |
| `PORT` | No | `8080` | Server port |
| `OPENROUTER_API_KEY` | No | | OpenRouter API key (for expander + judge) |
| `OPENROUTER_MODEL` | No | `google/gemini-2.0-flash-001` | Model for AI workers |
| `EXPANSION_ENABLED` | No | `false` | Enable autonomous graph expansion |
| `DAILY_CRON_ENABLED` | No | `false` | Enable "Today in History" worker |
| `ADMIN_KEY` | No | | Key for bulk generation endpoint |

## API Reference

All endpoints require `X-Service-Key` header.

### Browse & Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (no auth required) |
| `GET` | `/api/v1/browse` | List root segments (years) |
| `GET` | `/api/v1/browse/{path}` | Hierarchical listing (public only) |
| `GET` | `/api/v1/moments/{path}` | Full moment data |
| `GET` | `/api/v1/today` | Events matching today's date |
| `GET` | `/api/v1/random` | Random public moment (Layer 1+) |
| `GET` | `/api/v1/search?q={query}` | Full-text search |

### Graph

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/graph/neighbors/{path}` | Connected nodes with edge metadata |
| `GET` | `/api/v1/stats` | Graph statistics |

### Generation & Indexing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/generate` | Queue scene generation via Flash |
| `GET` | `/api/v1/jobs/{job_id}` | Poll job status |
| `POST` | `/api/v1/moments/{path}/publish` | Set visibility to public |
| `POST` | `/api/v1/bulk-generate` | Bulk generation (admin key required) |
| `POST` | `/api/v1/index` | Add/update a moment in the graph |

### Canonical URL Format

```
/{year}/{month}/{day}/{time}/{country}/{region}/{city}/{slug}
```

- `year`: integer, negative for BCE (e.g., `-44`)
- `month`: spelled out, lowercase (e.g., `march`)
- `day`: integer, no zero-padding
- `time`: 24hr, no colon (e.g., `1030`)
- `country`: modern borders, kebab-case
- `region`: state/province, kebab-case
- `city`: city/locality, kebab-case
- `slug`: auto-generated, kebab-case

### Content Layers

| Layer | Content | Storage |
|-------|---------|---------|
| 0 | URL path + event name | Clockchain graph |
| 1 | Metadata (figures, tags, one-liner) | Clockchain graph |
| 2 | Flash scene reference | `flash_timepoint_id` in graph node |

### Edge Types

- `causes` — causal relationship
- `contemporaneous` — same year (+/- 1)
- `same_location` — matching country/region/city
- `thematic` — overlapping tags

## Testing

```bash
pytest tests/ -v
```

## Deployment

Deployed on Railway via Dockerfile.

```bash
docker build -t timepoint-clockchain .
docker run -p 8080:8080 -e SERVICE_API_KEY=key -e FLASH_SERVICE_KEY=key timepoint-clockchain
```

## Seed Data

5 initial events loaded from `data/seeds.json`:

1. Assassination of Julius Caesar (-44 BCE)
2. Trinity Test (1945)
3. Apollo 12 Lightning Launch (1969)
4. Apollo 11 Moon Landing (1969)
5. AlphaGo Move 37 (2016)
