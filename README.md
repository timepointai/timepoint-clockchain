# timepoint-clockchain

TIMEPOINT's spatiotemporal graph index and autonomous content orchestrator. Maintains a PostgreSQL-backed graph of historical moments, orchestrates scene generation via Flash, and serves browse/search/discovery data to the TIMEPOINT platform.

## Architecture

```
timepoint-clockchain/
├── app/
│   ├── main.py              # FastAPI app, lifespan, health endpoint
│   ├── api/
│   │   ├── __init__.py      # API router aggregation
│   │   ├── moments.py       # /moments, /browse, /today, /random, /search
│   │   ├── generate.py      # /generate, /jobs, /publish, /bulk-generate, /index
│   │   └── graph.py         # /graph/neighbors, /stats
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── auth.py          # Service key + user ID extraction
│   │   ├── db.py            # asyncpg pool, schema DDL, seeding
│   │   ├── graph.py         # PostgreSQL-backed GraphManager (async)
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
│   └── seeds.json           # 5 seed historical events
├── scripts/
│   └── migrate_graph_json.py # One-time migration from graph.json to Postgres
├── tests/
├── Dockerfile
├── railway.json
└── pyproject.toml
```

## Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Or with uv
uv sync

# Copy env template and fill in your keys
cp .env.example .env
```

### PostgreSQL

Clockchain requires a PostgreSQL database. The schema is created automatically on startup.

```bash
# Local dev (macOS)
brew services start postgresql@16
createdb clockchain

# Or via Docker
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=test -e POSTGRES_DB=clockchain postgres:16
```

Set `DATABASE_URL` in your `.env`:
```
DATABASE_URL=postgresql://localhost:5432/clockchain
```

## Running

```bash
uvicorn app.main:app --port 8080
```

On startup, the service:
1. Creates an asyncpg connection pool
2. Runs schema DDL (CREATE TABLE IF NOT EXISTS)
3. Seeds the database from `seeds.json` if the nodes table is empty
4. Starts the GraphManager, workers, and API server

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | | PostgreSQL connection URL |
| `SERVICE_API_KEY` | Yes | | Shared secret for inbound service auth |
| `FLASH_URL` | No | `http://timepoint-flash-deploy.railway.internal:8080` | Flash service URL |
| `FLASH_SERVICE_KEY` | Yes | | Auth key for Flash API calls |
| `DATA_DIR` | No | `./data` | Directory for seed data and scene files |
| `ENVIRONMENT` | No | `development` | Environment name |
| `DEBUG` | No | `false` | Enable debug logging |
| `PORT` | No | `8080` | Server port |
| `OPENROUTER_API_KEY` | No | | OpenRouter API key (for expander + judge) |
| `OPENROUTER_MODEL` | No | `google/gemini-2.0-flash-001` | Model for AI workers |
| `EXPANSION_ENABLED` | No | `false` | Enable autonomous graph expansion |
| `DAILY_CRON_ENABLED` | No | `false` | Enable "Today in History" worker |
| `ADMIN_KEY` | No | | Key for bulk generation endpoint |

## API Reference

All endpoints require `X-Service-Key` header except `/health` and `/`.

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
| 0 | URL path + event name | Clockchain graph (Postgres) |
| 1 | Metadata (figures, tags, one-liner) | Clockchain graph (Postgres) |
| 2 | Flash scene reference | `flash_timepoint_id` in graph node |

### Edge Types

- `causes` -- causal relationship
- `contemporaneous` -- same year (+/- 1)
- `same_location` -- matching country/region/city
- `thematic` -- overlapping tags

### Database Schema

Two tables with indexes:

```sql
nodes (id TEXT PK, type, name, year, month, month_num, day, time,
       country, region, city, slug, layer, visibility, created_by,
       tags TEXT[], one_liner, figures TEXT[], flash_timepoint_id,
       flash_slug, flash_share_url, era, created_at, published_at)

edges (source TEXT FK, target TEXT FK, type TEXT CHECK(...),
       weight FLOAT, theme TEXT, PK(source, target, type))
```

Indexes on: visibility, (month, day), year, (country, region, city), GIN on tags/figures, GIN trigram on name/one_liner (when pg_trgm is available).

## Testing

Tests run against a real PostgreSQL database:

```bash
# Start Postgres
brew services start postgresql@16   # or Docker

# Create test database
createdb clockchain_test

# Run tests
DATABASE_URL=postgresql://localhost:5432/clockchain_test pytest tests/ -v
```

59 tests covering: graph operations, edge auto-linking, API endpoints, health checks, generation/indexing, expander/daily workers, content judge, and URL parsing.

## Deployment

Deployed on Railway via the [deploy-private](https://github.com/timepoint-ai/timepoint-clockchain-deploy-private) repo. Railway provides `DATABASE_URL` automatically via the Postgres plugin.

### Migration from graph.json

If migrating from the previous NetworkX/JSON storage:

```bash
DATABASE_URL=postgresql://... python scripts/migrate_graph_json.py data/graph.json
```

## Seed Data

5 initial events loaded from `data/seeds.json` when the database is empty:

1. Assassination of Julius Caesar (-44 BCE)
2. Trinity Test (1945)
3. Apollo 12 Lightning Launch (1969)
4. Apollo 11 Moon Landing (1969)
5. AlphaGo Move 37 (2016)
