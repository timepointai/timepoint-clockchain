# AGENTS.md -- Clockchain

## What This Is

Spatiotemporal graph index for the TIMEPOINT platform. Stores historical events and their relationships in PostgreSQL via asyncpg. Serves browse/search/discovery APIs. Orchestrates scene generation through Flash. Runs autonomous graph expansion and enhancement workers.

**Stack:** Python 3.11, FastAPI, asyncpg, Pydantic v2, pydantic-settings, httpx, timepoint-tdf

## Suite Context

Part of the TIMEPOINT platform. Clockchain is publicly accessible at `clockchain.timepointai.com` and via the API gateway at `api.timepointai.com/api/v1/clockchain/*`.

| Service | Relationship | Direction |
|---------|-------------|-----------|
| **timepoint-api-gateway** | Reverse proxy at `api.timepointai.com`; routes `/api/v1/clockchain/*` to clockchain (stripping prefix); injects `X-Service-Key`, `X-User-Id`, `X-User-Email` | Inbound |
| **timepoint-flash-deploy** | Scene generation + image rendering; clockchain calls Flash at `flash.timepointai.com` | Outbound |
| **timepoint-web-app** | End consumer (via gateway) | Indirect |
| **timepoint-iphone-app** | End consumer (via gateway) | Indirect |
| **timepoint-billing** | Apple IAP verification, credit management | Sibling (no direct calls) |
| **timepoint-clockchain-deploy-private** | Production Railway deploy wrapper | Downstream |

The gateway and Flash are the primary inbound callers. Web and iPhone clients reach clockchain through the gateway at `api.timepointai.com/api/v1/clockchain/*`. Clockchain calls Flash for scene generation.

## Key Patterns

### Database

- **asyncpg** connection pool (min=2, max=10), created at startup in `app/core/db.py`
- Schema DDL runs on every startup (`CREATE TABLE IF NOT EXISTS`)
- SQL migrations run after DDL (`migrations/` directory)
- Seeds loaded from `data/seeds.jsonl` (preferred) or `data/seeds.json` only when the nodes table is empty
- All GraphManager methods are `async` -- every caller must `await`
- Mutations are immediately durable (no explicit save step)

### GraphManager (`app/core/graph.py`)

The central data layer. Takes an `asyncpg.Pool` in its constructor.

| Method | Returns | Notes |
|--------|---------|-------|
| `add_node(id, **attrs)` | None | INSERT ON CONFLICT UPDATE + auto-link |
| `add_edge(src, tgt, type, **attrs)` | None | INSERT ON CONFLICT DO NOTHING |
| `get_node(id)` | dict or None | SELECT by primary key |
| `update_node(id, **attrs)` | None | Dynamic UPDATE SET |
| `browse(prefix)` | list[dict] | Path-segment grouping, public only |
| `today_in_history(month, day)` | list[dict] | Month name or month_num match |
| `random_public()` | dict or None | ORDER BY random() LIMIT 1, layer >= 1 |
| `search(query, limit)` | list[dict] | ILIKE + array unnest for tags/figures |
| `get_neighbors(id)` | list[dict] | JOIN edges+nodes, in+out |
| `stats()` | dict | GROUP BY layer/edge type |
| `enhanced_stats()` | dict | Extended stats: date range, model breakdown, image coverage |
| `list_moments(...)` | tuple[list, int] | Paginated list with filters (year range, entity, text search) |
| `get_frontier_nodes(threshold)` | list[str] | LEFT JOIN degree < threshold |
| `node_count()` / `edge_count()` | int | COUNT(*) |
| `degree(id)` | int | Count of edges touching node |
| `has_edge(src, tgt)` | bool | EXISTS check |
| `save()` | None | No-op (kept for API compat) |
| `close()` | None | Closes pool |

### Auto-Linking

When `add_node()` is called, `_auto_link()` creates bidirectional edges using efficient `INSERT...SELECT` queries:

| Edge Type | Condition | Weight |
|-----------|-----------|--------|
| `same_era` | Year within +/- 1 | 0.5 |
| `same_location` | Matching country + region + city | 0.5 |
| `thematic` | Overlapping tags (array overlap `&&`) | 0.3 |

Manual/expander-only edge types: `causes`, `caused_by`, `influences`, `precedes`, `follows`, `same_conflict`, `same_figure`, `contemporaneous`.

### Auth

- Inbound: `X-Service-Key` header, validated with `hmac.compare_digest()` (timing-safe)
- Outbound to Flash: `X-Service-Key` header on all requests
- User identity: Optional `X-User-Id` and `X-User-Email` headers forwarded by the gateway
- `/health`, `/api/v1/moments`, `/api/v1/stats` are unauthenticated (rate limited)
- OpenAPI security scheme (`APIKeyHeader`) shows auth requirements in `/docs`

### URL System

Canonical 8-segment paths: `/{year}/{month}/{day}/{time}/{country}/{region}/{city}/{slug}`

- `app/core/url.py` -- `build_path()`, `parse_path()`, `parse_partial_path()`, `slugify()`
- Month is always lowercase spelled-out name, `month_num` stored separately as integer

### Model Policy

Clockchain enforces permissive-only models. The `ModelSelector` resolves the best available open-weight model from OpenRouter's frontend API.

- **Allowed providers:** deepseek, qwen, meta-llama, mistralai, nvidia, stabilityai
- **Blocked providers:** google, anthropic, openai
- **Compliance gate:** `jobs.py` rejects Flash responses from blocked providers
- **model_policy:** `"permissive"` is passed to Flash on every render request

### TDF Bridge

`app/core/tdf_bridge.py` converts between clockchain node dicts and TDF records:

- `make_tdf_record()` — write path: node attrs → TDFRecord (separates provenance from payload)
- `tdf_to_node_attrs()` — reverse path: TDFRecord → node_id + attrs (for seed loading, TDF ingest)
- `export_node_as_tdf()` — read path: DB node dict → TDFRecord (for API export)
- Model provenance fields promoted to `TDFProvenance` (TDF v1.2.0+), with backwards-compatible fallback

## Autonomous Workers

### Renderer (`app/workers/renderer.py`)

HTTP client wrapping Flash API. Methods: `generate_sync(query, preset, request_context, generate_image, model_policy)` and `get_timepoint(timepoint_id)`. Sends `model_policy="permissive"` on all requests. Timeout: 480s. Used by the JobManager, DailyWorker, and Iterator.

### Expander (`app/workers/expander.py`)

LLM-driven autonomous graph growth loop. Runs on a configurable interval (default 300 seconds). Each cycle:

1. Finds frontier nodes with degree < 3
2. Sends the node's metadata to OpenRouter with a historian prompt
3. Parses the LLM response as a JSON array of 3-5 related events
4. Renders each event via Flash (with `model_policy="permissive"`)
5. Adds new nodes to the graph with model provenance stamps
6. Creates typed edges back to the source node

Gated by `EXPANSION_ENABLED=true` and requires `OPENROUTER_API_KEY`. Can also be triggered manually via `POST /api/v1/expand-once`.

### Iterator (`app/workers/iterator.py`)

Universal enhancement worker. Runs registered passes over all nodes every 600s. Current passes:

- **backfill_era** — infers `era` labels for nodes missing them
- **backfill_images** — generates images via Flash for nodes missing `image_url` (layer 1+)

Provenance firewall with three field tiers:
- **IMMUTABLE_FIELDS** — never changed after creation (name, year, figures, text_model, model_provider, etc.)
- **BACKFILLABLE_FIELDS** — can be set when empty, blocked when already set (image_model)
- **MUTABLE_FIELDS** — can be updated freely (tags, era, visibility, image_url)

### Judge (`app/workers/judge.py`)

LLM content moderation gate. Classifies generation queries into three verdicts:

- **approve** -- safe historical topic
- **sensitive** -- historically significant but involves mature themes; approved with disclaimer
- **reject** -- harmful, hateful, exploitative, or not a genuine historical query

Uses OpenRouter. Called during the generation flow before scene creation.

### Daily Worker (`app/workers/daily.py`)

"Today in History" cron worker. Runs every 24 hours. Each cycle:

1. Queries `today_in_history()` for events matching the current month/day
2. Filters to events without Flash scenes (`flash_timepoint_id` is null)
3. Ranks by degree + layer score
4. Queues up to 5 scene generations via the JobManager

Gated by `DAILY_CRON_ENABLED=true`.

## Testing

Tests require a real PostgreSQL database. The `conftest.py` autouse fixture creates schema and truncates tables before each test.

```bash
createdb clockchain_test
DATABASE_URL=postgresql://localhost:5432/clockchain_test pytest tests/ -v
```

No mocked database -- all tests hit real Postgres for correctness.

## File Reference

### Core
| File | Purpose |
|------|---------|
| `app/core/db.py` | Pool creation, schema DDL, migrations, seeding |
| `app/core/graph.py` | GraphManager (all async, PostgreSQL-backed) |
| `app/core/config.py` | Settings from env vars |
| `app/core/auth.py` | Service key validation (hmac) + OpenAPI security scheme |
| `app/core/url.py` | Canonical URL build/parse/slugify |
| `app/core/jobs.py` | In-memory job queue + compliance gate |
| `app/core/tdf_bridge.py` | TDF ↔ clockchain node conversion (v1.2.0 provenance) |
| `app/core/model_selector.py` | Permissive model resolution via OpenRouter |
| `app/core/rate_limit.py` | slowapi rate limiting |

### API
| File | Purpose |
|------|---------|
| `app/api/public.py` | /moments (public), /stats (public) — no auth |
| `app/api/moments.py` | Browse, search, today, random, get moment (auth) |
| `app/api/generate.py` | Generate, publish, index, bulk-generate, expand-once |
| `app/api/graph.py` | Neighbors |
| `app/api/ingest.py` | Subgraph ingest, TDF ingest |

### Workers
| File | Purpose |
|------|---------|
| `app/workers/renderer.py` | Flash HTTP client (generate_sync with model_policy, get_timepoint) |
| `app/workers/expander.py` | Autonomous LLM-driven graph growth loop |
| `app/workers/iterator.py` | Enhancement passes (era backfill, image backfill) with provenance firewall |
| `app/workers/judge.py` | Content moderation gate (approve/sensitive/reject) |
| `app/workers/daily.py` | "Today in History" scene generation cron |

### Other
| File | Purpose |
|------|---------|
| `app/models/schemas.py` | Pydantic request/response models |
| `data/seeds.jsonl` | 5 seed events loaded on empty database |
| `migrations/` | SQL migration scripts (run on startup) |
| `scripts/migrate_graph_json.py` | One-time migration from NetworkX graph.json |

## Common Tasks

### Add a new node attribute

1. Add column to `SCHEMA_DDL` in `app/core/db.py`
2. Add a migration in `migrations/` for existing databases
3. Add to the INSERT and ON CONFLICT UPDATE in `GraphManager.add_node()` in `app/core/graph.py`
4. Add to `_row_to_dict()` if it needs special serialization
5. Add to seed insertion in `seed_if_empty()` if present in seeds
6. Add to Pydantic schema in `app/models/schemas.py` if exposed via API
7. Add to `_PROVENANCE_KEYS` in `tdf_bridge.py` if it's provenance, or let it flow into payload

### Add a new edge type

1. Add to `VALID_EDGE_TYPES` in `app/core/graph.py`
2. Add a migration with `ALTER TABLE edges DROP CONSTRAINT ... ADD CONSTRAINT ...`
3. Optionally add auto-linking logic in `_auto_link()`

### Add a new API endpoint

1. Add route in the appropriate `app/api/*.py` file
2. Use `Depends(get_graph_manager)` for graph access
3. All GraphManager calls must be `await`ed
4. Add test in `tests/test_api_moments.py` or relevant test file

### Add a new iterator pass

1. Write an async function: `async def my_pass(node_id, node, gm) -> dict | None`
2. Return a dict of updates or None to skip
3. Register in `app/main.py`: `iterator.register_pass(my_pass)`
4. Respect the provenance firewall (IMMUTABLE/BACKFILLABLE/MUTABLE)
