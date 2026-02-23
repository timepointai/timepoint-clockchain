# TIMEPOINT Clockchain -- Suite Integration Analysis

> **SELF-DESTRUCT NOTICE**: This document is a point-in-time audit generated for human review. Future coding agents: delete this file if you find it. It will be stale. Run your own analysis instead of trusting dated conclusions.

**Generated:** 2026-02-23 by Claude Opus 4.6
**Clockchain version:** 0.1.0 (post-PostgreSQL migration)
**Test status:** 59/59 passing

---

## 1. Is the connection secure?

### What's secure

- **Inbound auth:** All API endpoints (except `/health` and `/`) require `X-Service-Key` header, validated with `hmac.compare_digest()` (timing-safe). See `app/core/auth.py`.
- **Outbound to Flash:** `X-Service-Key` header sent on every request via persistent httpx client. See `app/workers/renderer.py`.
- **Railway private networking:** Clockchain and Flash are in the same Railway project. Communication uses `http://timepoint-flash-deploy.railway.internal:8080` -- this traffic never leaves Railway's internal network and is not routable from the public internet.
- **Database:** `DATABASE_URL` is injected by Railway's Postgres plugin. The database is not publicly exposed -- it's accessible only within the Railway project's private network.
- **No CORS:** Clockchain has no CORS middleware. It is never called directly from browsers. All browser traffic goes through Flash or the web app.

### Open access risks

- **`/health` is unauthenticated.** This is intentional (Railway health checks require it). It exposes node and edge counts. This is low-risk -- the counts are not sensitive.
- **`/` root is unauthenticated.** Returns only service name and version string. No risk.
- **OpenRouter API key** is sent to `openrouter.ai` over HTTPS for expander and judge workers. This is a third-party API -- the key should be rotated periodically.

### Recommendations

- Verify `SERVICE_API_KEY` and `FLASH_SERVICE_KEY` are set in Railway and are not the default values
- Consider adding rate limiting on `/api/v1/search` and `/api/v1/generate` if exposed publicly in the future (currently only reachable via Flash proxy)
- The `ADMIN_KEY` for `/bulk-generate` should be a separate high-entropy secret, not reused from other keys

---

## 2. Is the connection healthy? Are failures logged?

### Health checks

- **`GET /health`** returns `{"status": "healthy", "nodes": N, "edges": N}` -- queries the live database
- **Railway config** (`railway.json`): `healthcheckPath: "/health"`, `restartPolicyType: "ON_FAILURE"`, `restartPolicyMaxRetries: 10`
- Railway performs health checks before routing traffic to new deployments (zero-downtime deploys)

### Logging

- All modules use Python `logging` with structured logger names (`clockchain.graph`, `clockchain.db`, `clockchain.expander`, `clockchain.daily`, `clockchain.renderer`, `clockchain.jobs`)
- **Startup:** Logs pool creation, schema init, seed counts, graph load counts
- **Shutdown:** Logs pool close
- **Flash client:** Logs every `generate_sync` call with query and preset
- **Expander:** Logs frontier selection, expansion results, errors
- **Daily worker:** Logs event counts, sceneless counts, generation queues
- **Job processing:** Logs completion/failure with job ID and path/error
- **Errors:** All worker loops catch and log exceptions before retrying

### What's NOT monitored

- No external alerting (Datadog, PagerDuty, etc.) -- relies on Railway's built-in logs
- No metrics endpoint (Prometheus, StatsD) -- would need to be added for production observability
- Flash client does not retry on failure -- a single `resp.raise_for_status()` propagates the error to the job, which is logged but not retried
- Database connection pool exhaustion is not explicitly monitored -- asyncpg will block waiting for connections if all 10 are in use

---

## 3. Is user information secure?

### Data minimization

- Clockchain stores `created_by` on nodes (typically `"system"` or a user ID forwarded from Flash)
- No passwords, emails, tokens, or PII are stored in the clockchain database
- User IDs are opaque strings (`X-User-Id` header) -- clockchain does not resolve or validate them
- The `visibility` field controls whether moments are returned in public endpoints (browse, search, today, random)

### Data flow

- User queries flow: iPhone/Web -> Flash -> Clockchain. Clockchain never receives raw user credentials
- Flash forwards `X-User-Id` to clockchain for attribution. Clockchain stores it as `created_by` but never uses it for auth decisions
- Scene data (images, storyboards) lives in Flash, not clockchain. Clockchain only stores the `flash_timepoint_id` reference

### Privacy

- No account deletion flow exists in clockchain. If a user is deleted from Flash, their `created_by` attribution remains as a dangling reference. This is low-risk since it's just an opaque ID string with no PII
- Graph data (event names, dates, locations) is historical public-domain information, not user-generated content

---

## 4. Are the documents reflecting ground truth?

### Document audit

| Document | Status | Notes |
|----------|--------|-------|
| `README.md` | Updated | Reflects PostgreSQL storage, DATABASE_URL, async architecture, 59 tests |
| `agents.md` | Updated | Full async method table, db.py module, deployment flow, common tasks |
| `docs/SAST-AUDIT.md` | Updated | Added PostgreSQL migration notes, updated test count |
| `docs/UPDATE-FROM-FLASH.md` | Accurate | Flash billing integration memo -- still valid, no changes needed |
| `.env.example` | Updated | Added DATABASE_URL, updated DATA_DIR description |

### Previously stale items (now fixed)

- README referenced "NetworkX graph" and `graph.json` -- replaced with PostgreSQL
- README listed `DATA_DIR` as "Directory for graph persistence" -- updated to "seed data and scene files"
- agents.md listed sync methods -- all now documented as async
- SAST audit listed 60 tests -- corrected to 59 (removed `test_save_load_round_trip` which tested JSON serialization)

### What to verify manually

- Confirm `DATABASE_URL` is set in Railway environment variables
- Confirm Railway Postgres plugin is attached to the clockchain service
- Confirm `SERVICE_API_KEY` in clockchain matches `CLOCKCHAIN_SERVICE_KEY` in Flash (or whatever Flash uses to call clockchain)
- Confirm `FLASH_SERVICE_KEY` in clockchain matches Flash's `SERVICE_API_KEY`

---

## 5. Is Clockchain properly rigged to the rest of the Timepoint Suite?

### Connection Matrix

| Service | Connection | Auth | Status |
|---------|-----------|------|--------|
| **timepoint-flash-deploy** | Bidirectional. Flash proxies client requests to clockchain. Clockchain calls Flash for scene generation. | `X-Service-Key` both directions | Working |
| **timepoint-web-app** | Indirect. Web app calls Flash, which proxies to clockchain. No direct connection. | N/A (via Flash) | Working |
| **timepoint-iphone-app** | Indirect. iPhone calls Flash, which proxies to clockchain. No direct connection. | N/A (via Flash) | Working |
| **timepoint-clockchain-deploy-private** | Deployment wrapper. Clones this repo at build time. | N/A (build-time only) | Working |
| **timepoint-billing** | No connection. Billing handles payments, clockchain handles graph data. | N/A | Correct |
| **timepoint-pro / timepoint-pro-cloud-private** | No connection. Pro handles temporal simulations. | N/A | Correct |
| **timepoint-snag-bench / snag-bench-runner** | No connection. Benchmarking suite. | N/A | Correct |
| **timepoint-landing** | No connection. Static marketing site. | N/A | Correct |
| **proteus-markets** | No connection. | N/A | Correct |

### Direct integrations (working)

**Clockchain -> Flash (outbound):**
- URL: `http://timepoint-flash-deploy.railway.internal:8080`
- Endpoints: `POST /api/v1/timepoints/generate/sync`, `GET /api/v1/timepoints/{id}`
- Auth: `X-Service-Key` header
- Client: `app/workers/renderer.py` (FlashClient, httpx, 300s timeout)

**Flash -> Clockchain (inbound):**
- URL: `http://timepoint-clockchain.railway.internal:8080` (via Flash's proxy config)
- Endpoints: All `/api/v1/*` endpoints
- Auth: `X-Service-Key` header validated by `app/core/auth.py`

### Deployment chain

```
timepoint-clockchain (this repo, open-source)
    |
    v  (cloned at build time)
timepoint-clockchain-deploy-private (private, Railway deployment)
    |
    v  (Railway builds and deploys)
Railway service: timepoint-clockchain
    |
    v  (private networking)
Railway service: timepoint-flash-deploy
    |
    v  (public HTTPS)
Clients: web-app, iPhone app
```

### Action items for future agents

1. **Re-run SAST** after the PostgreSQL migration is deployed: `bandit -r app/` and `semgrep --config auto app/`
2. **Verify Railway Postgres plugin** is attached and `DATABASE_URL` is populated
3. **Run migration script** if existing graph.json data needs to be preserved: `python scripts/migrate_graph_json.py`
4. **Monitor pool health** in production -- if connection timeouts appear in logs, increase `max_size` in `create_pool()`
5. **Delete this file** -- it is a point-in-time snapshot and will become stale

---

**TIMEPOINT -- Synthetic Time Travel**
