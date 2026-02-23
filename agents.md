# AGENTS.md -- Clockchain

## What This Is

Spatiotemporal graph index for the TIMEPOINT platform. Stores historical events and their relationships in PostgreSQL via asyncpg. Serves browse/search/discovery APIs. Orchestrates scene generation through Flash. Runs autonomous graph expansion and daily content workers.

**Stack:** Python 3.11, FastAPI, asyncpg, Pydantic v2, pydantic-settings, httpx

## Suite Context

| Service | Relationship | Direction |
|---------|-------------|-----------|
| **timepoint-flash-deploy** | Scene generation + proxied API gateway | Bidirectional |
| **timepoint-web-app** | Consumes clockchain data via Flash proxy | Inbound (via Flash) |
| **timepoint-iphone-app** | Consumes clockchain data via Flash proxy | Inbound (via Flash) |
| **timepoint-billing** | None | No direct connection |
| **timepoint-pro** | None | No direct connection |
| **timepoint-snag-bench** | None | No direct connection |

Flash is the only service that calls clockchain directly. Web and iPhone clients reach clockchain through Flash's `/api/v1/clockchain/*` proxy. Clockchain calls Flash for scene generation.

**Networking:** Same Railway project as Flash. Uses `http://timepoint-flash-deploy.railway.internal:8080` (private networking, no public exposure).

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

## Railway Deployment

Deployed via [timepoint-clockchain-deploy-private](https://github.com/timepoint-ai/timepoint-clockchain-deploy-private). 3-stage Dockerfile clones this upstream repo at build time.

- **Railway Postgres plugin** provides `DATABASE_URL` automatically
- **Health check:** `GET /health` (configured in `railway.json`)
- **Restart policy:** ON_FAILURE, max 10 retries
- **Internal URL:** `http://timepoint-clockchain.railway.internal:8080`

To redeploy with latest upstream:
```bash
cd timepoint-clockchain-deploy-private
git commit --allow-empty -m "chore: rebuild with latest upstream"
git push
```

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
