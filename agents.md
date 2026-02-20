# Clockchain Agents

Background workers that run alongside the FastAPI server. Each is started conditionally during app lifespan based on environment variables and available credentials.

## Renderer (`app/workers/renderer.py`)

**Class:** `FlashClient`

HTTP client for the Flash scene-generation service. Not a background loop — called on demand when a generation job is processed.

- `generate_sync(query, preset, request_context)` — POST to Flash's `/api/v1/timepoints/generate/sync`
- `get_timepoint(timepoint_id)` — GET a rendered timepoint from Flash
- Authenticates via `X-Service-Key` header
- 300-second timeout for long-running scene renders

**Config:** `FLASH_URL`, `FLASH_SERVICE_KEY`

## Expander (`app/workers/expander.py`)

**Class:** `GraphExpander`

Autonomous graph-growth loop. Picks frontier nodes (low edge-count) and asks an LLM via OpenRouter to suggest 3–5 related historical events, then adds them to the graph with edges back to the source.

- Runs on a configurable interval (default 300s)
- Selects frontier nodes via `GraphManager.get_frontier_nodes(threshold=3)`
- Sends a structured prompt via OpenRouter's chat completions API and parses the JSON response
- New nodes are created at Layer 1 (public, with metadata)
- Edges are created with the type suggested by the model (`causes`, `contemporaneous`, `same_location`, or `thematic`)
- Saves the graph after each expansion cycle

**Config:** `EXPANSION_ENABLED`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`

## Judge (`app/workers/judge.py`)

**Class:** `ContentJudge`

LLM-based content moderation gate. Called inline before scene generation to screen user queries.

- Sends the query via OpenRouter's chat completions API with a classification prompt
- Returns one of three verdicts:
  - `approve` — safe historical topic
  - `sensitive` — historically significant but mature; approved with disclaimer
  - `reject` — harmful, hateful, or not a genuine historical query
- Not a background loop — invoked per-request

**Config:** `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`

## Daily Worker (`app/workers/daily.py`)

**Class:** `DailyWorker`

"Today in History" cron loop. Finds graph events matching today's month/day and queues Flash scene generation for those that lack one.

- Runs every 24 hours
- Queries `GraphManager.today_in_history(month, day)` for matching public events
- Filters to events missing a `flash_timepoint_id` / `flash_scene`
- Ranks candidates by graph degree and content layer
- Generates up to 5 scenes per cycle via the `JobManager`

**Config:** `DAILY_CRON_ENABLED`

## Auto-Linking (`app/core/graph.py`)

Not a standalone worker, but runs automatically inside `GraphManager.add_node()`. When a new node is added, `_auto_link` scans existing nodes and creates bidirectional edges for:

| Edge Type | Condition |
|-----------|-----------|
| `contemporaneous` | Year within +/- 1 |
| `same_location` | Matching country + region + city |
| `thematic` | Overlapping tags |

`causes` edges are **not** auto-linked — they are only created manually or by the Expander when the LLM suggests a causal relationship.
