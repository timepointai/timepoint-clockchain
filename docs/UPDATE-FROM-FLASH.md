# UPDATE: Flash Billing Integration Complete
**From:** timepoint-flash-deploy · Feb 2026
**Re:** Confirming clockchain compatibility + new capabilities available

---

## Status: No Breaking Changes

All existing clockchain code continues to work. Flash's billing integration added new features but changed nothing about how service-key-only calls behave.

---

## Your Current Integration is Correct

The clockchain's Flash integration pattern (from MEMO-CLOCKCHAIN §10) is confirmed working:

```python
# This is exactly how clockchain calls Flash today — still correct
response = await client.post(
    f"{FLASH_URL}/api/v1/timepoints/generate/sync",
    json={"query": query, "preset": preset},
    headers={"X-Service-Key": FLASH_KEY},
)
```

**What happens server-side:**
1. Flash sees `X-Service-Key` header, validates it matches `FLASH_SERVICE_KEY`
2. No `X-User-ID` header present → `get_current_user` returns `None`
3. No credits deducted, generation proceeds as system call
4. Timepoint created with `visibility: PUBLIC`, `user_id: null`

This is unchanged. No code modifications needed.

---

## New Capabilities Available

### 1. `callback_url` — Async Generation with POST-back

Instead of blocking on `/generate/sync` (up to 120s), clockchain workers can now use the async endpoint with a callback:

```python
response = await client.post(
    f"{FLASH_URL}/api/v1/timepoints/generate",
    json={
        "query": query,
        "preset": preset,
        "callback_url": f"{CLOCKCHAIN_URL}/api/v1/callbacks/flash",
        "request_context": {
            "source": "clockchain",
            "graph_node_id": node_path,
            "worker": "renderer",
        },
    },
    headers={"X-Service-Key": FLASH_KEY},
)
# Returns immediately with {"id": "...", "status": "processing"}
```

When generation completes, Flash POSTs the full result to `callback_url`:
```json
{
  "timepoint": { /* full TimepointResponse */ },
  "preset_used": "balanced",
  "generation_time_ms": 95000,
  "request_context": {
    "source": "clockchain",
    "graph_node_id": "/-44/march/15/...",
    "worker": "renderer"
  }
}
```

**Benefits:**
- Workers don't block on long generations
- Can dispatch many parallel jobs without holding connections open
- `request_context` round-trips back, so the callback handler knows which graph node to update

**Trade-off:** Requires clockchain to expose a callback endpoint. Only useful if you want higher parallelism than the current sync approach.

### 2. `request_context` — Traceability

Even without `callback_url`, you can pass `request_context` on sync calls:

```python
response = await client.post(
    f"{FLASH_URL}/api/v1/timepoints/generate/sync",
    json={
        "query": query,
        "preset": preset,
        "request_context": {
            "source": "clockchain",
            "graph_node_id": node_path,
            "worker": "renderer",
            "job_id": job_id,
        },
    },
    headers={"X-Service-Key": FLASH_KEY},
)
```

Flash logs this context and includes it in the response. Useful for correlating Flash generation logs with clockchain job IDs.

---

## Confirmed Settings

| Setting | Value | Status |
|---------|-------|--------|
| `FLASH_SERVICE_KEY` | Shared secret | Clockchain uses this correctly |
| `CORS_ENABLED=false` | Flash internal-only | Correct — clockchain never calls from browser |
| Service-key-only = unmetered | No credits deducted | Confirmed working |

---

## Suggested Enhancement

Consider adding `callback_url` + `request_context` to the **renderer worker** for better observability:

```python
# In workers/renderer.py — enhanced version
async def render_scene(node_path: str, query: str, job_id: str):
    response = await client.post(
        f"{FLASH_URL}/api/v1/timepoints/generate/sync",
        json={
            "query": query,
            "preset": "balanced",
            "request_context": {
                "source": "clockchain",
                "graph_node_id": node_path,
                "worker": "renderer",
                "job_id": job_id,
            },
        },
        headers={"X-Service-Key": FLASH_KEY},
    )
    result = response.json()
    # request_context is echoed back in the response
    return result
```

This is optional — existing code works fine without it.

---

**No action required. All existing clockchain ↔ Flash integration continues to work unchanged.**

**TIMEPOINT · Synthetic Time Travel™**
