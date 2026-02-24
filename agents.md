# AGENTS.md -- Clockchain

## What This Is

Spatiotemporal graph index for the TIMEPOINT platform. Stores historical events and their relationships in PostgreSQL via asyncpg. Serves browse/search/discovery APIs. Orchestrates scene generation through Flash. Runs autonomous graph expansion and daily content workers.

**Stack:** Python 3.11, FastAPI, asyncpg, Pydantic v2, pydantic-settings, httpx

## Suite Context

Part of the TIMEPOINT platform. Clockchain is a backend-only service -- not publicly exposed. Flash is its sole inbound caller.

| Service | Relationship | Direction |
|---------|-------------|-----------|
| **timepoint-flash-deploy** | Scene generation + proxied API gateway | Bidirectional |
| **timepoint-web-app** | Consumes clockchain data via Flash proxy | Inbound (via Flash) |
| **timepoint-iphone-app** | Consumes clockchain data via Flash proxy (SwiftUI, v1.0.0 build 2, TestFlight-ready) | Inbound (via Flash) |
| **timepoint-billing** | Apple IAP verification, credit management | Sibling (no direct calls) |
| **timepoint-clockchain-deploy-private** | Production Railway deploy wrapper | Downstream |

Flash is the only service that calls clockchain directly. Web and iPhone clients reach clockchain through Flash's `/api/v1/clockchain/*` proxy. Clockchain calls Flash for scene generation.

## Key Patterns

### Database

- **asyncpg** connection pool (min=2, max=10), created at startup in `app/core/db.py`
- Schema DDL runs on every startup (`CREATE TABLE IF NOT EXISTS`)
- Seeds loaded from `data/seeds.json` only when the nodes table is empty
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
| `contemporaneous` | Year within +/- 1 | 0.5 |
| `same_location` | Matching country + region + city | 0.5 |
| `thematic` | Overlapping tags (array overlap `&&`) | 0.3 |

`causes` edges are never auto-linked -- only created by the Expander or manually via `add_edge()`.

### Auth

- Inbound: `X-Service-Key` header, validated with `hmac.compare_digest()` (timing-safe)
- Outbound to Flash: `X-Service-Key` header on all requests
- User identity: Optional `X-User-Id` header forwarded by Flash
- `/health` and `/` are unauthenticated

### URL System

Canonical 8-segment paths: `/{year}/{month}/{day}/{time}/{country}/{region}/{city}/{slug}`

- `app/core/url.py` -- `build_path()`, `parse_path()`, `parse_partial_path()`, `slugify()`
- Month is always lowercase spelled-out name, `month_num` stored separately as integer

## Autonomous Workers

### Renderer (`app/workers/renderer.py`)

HTTP client wrapping Flash API. Methods: `generate_sync(query, preset, request_context)` and `get_timepoint(timepoint_id)`. Used by the JobManager and DailyWorker to generate Flash scenes from clockchain moments.

### Expander (`app/workers/expander.py`)

LLM-driven autonomous graph growth loop. Runs on a configurable interval (default 300 seconds). Each cycle:

1. Finds frontier nodes with degree < 3
2. Sends the node's metadata to OpenRouter with a historian prompt
3. Parses the LLM response as a JSON array of 3-5 related events
4. Adds new nodes to the graph with Layer 1 metadata
5. Creates typed edges back to the source node

Gated by `EXPANSION_ENABLED=true` and requires `OPENROUTER_API_KEY`. Can also be triggered manually via `POST /api/v1/expand-once` (runs one expansion cycle on demand regardless of the `EXPANSION_ENABLED` flag, but still requires `OPENROUTER_API_KEY`).

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

59 tests. No mocked database -- all tests hit real Postgres for correctness.

## File Reference

### Core
| File | Purpose |
|------|---------|
| `app/core/db.py` | Pool creation, schema DDL, seeding |
| `app/core/graph.py` | GraphManager (all async, PostgreSQL-backed) |
| `app/core/config.py` | Settings from env vars |
| `app/core/auth.py` | Service key validation (hmac) |
| `app/core/url.py` | Canonical URL build/parse/slugify |
| `app/core/jobs.py` | In-memory job queue for generation |

### API
| File | Purpose |
|------|---------|
| `app/api/moments.py` | Browse, search, today, random, get moment |
| `app/api/generate.py` | Generate, publish, index, bulk-generate |
| `app/api/graph.py` | Neighbors, stats |

### Workers
| File | Purpose |
|------|---------|
| `app/workers/renderer.py` | Flash HTTP client (generate_sync, get_timepoint) |
| `app/workers/expander.py` | Autonomous LLM-driven graph growth loop |
| `app/workers/judge.py` | Content moderation gate (approve/sensitive/reject) |
| `app/workers/daily.py` | "Today in History" scene generation cron |

### Other
| File | Purpose |
|------|---------|
| `app/models/schemas.py` | Pydantic request/response models |
| `data/seeds.json` | 5 seed events loaded on empty database |
| `scripts/migrate_graph_json.py` | One-time migration from NetworkX graph.json |

## Common Tasks

### Add a new node attribute

1. Add column to `SCHEMA_DDL` in `app/core/db.py`
2. Add to the INSERT and ON CONFLICT UPDATE in `GraphManager.add_node()` in `app/core/graph.py`
3. Add to `_row_to_dict()` if it needs special serialization
4. Add to seed insertion in `seed_if_empty()` if present in seeds.json
5. Add to Pydantic schema in `app/models/schemas.py` if exposed via API

### Add a new edge type

1. Add to the CHECK constraint in `SCHEMA_DDL` (requires a migration or `ALTER TABLE`)
2. Add to `VALID_EDGE_TYPES` in `app/core/graph.py`
3. Optionally add auto-linking logic in `_auto_link()`

### Add a new API endpoint

1. Add route in the appropriate `app/api/*.py` file
2. Use `Depends(get_graph_manager)` for graph access
3. All GraphManager calls must be `await`ed
4. Add test in `tests/test_api_moments.py` or relevant test file

### Run SAST

```bash
pip install bandit semgrep
bandit -r app/ -f json -o bandit_results.json
semgrep --config auto app/
```
