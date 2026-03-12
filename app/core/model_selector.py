import asyncio
import logging
import time

import httpx

logger = logging.getLogger("clockchain.model_selector")

OPENROUTER_FRONTEND_URL = "https://openrouter.ai/api/frontend/models"

ALLOWED_PROVIDERS = {"deepseek", "qwen", "meta-llama", "mistralai", "nvidia", "stabilityai"}
BLOCKED_PROVIDERS = {"google", "anthropic", "openai"}

FALLBACK_CHAIN = [
    "deepseek/deepseek-chat-v3-0324",
    "qwen/qwen-2.5-72b-instruct",
    "meta-llama/llama-4-maverick",
]

CACHE_TTL = 86400  # 24 hours


class ModelSelector:
    def __init__(self):
        self._cache: list[str] = []
        self._cache_ts: float = 0
        self._active_model: str = FALLBACK_CHAIN[0]
        self._lock = asyncio.Lock()

    @property
    def active_model(self) -> str:
        return self._active_model

    async def resolve(self) -> str:
        async with self._lock:
            if self._cache and (time.monotonic() - self._cache_ts) < CACHE_TTL:
                return self._active_model

            models = await self._fetch_distillable()
            if models:
                self._cache = models
                self._cache_ts = time.monotonic()
                self._active_model = models[0]
                logger.info(
                    "Resolved permissive model: %s (%d candidates)",
                    self._active_model,
                    len(models),
                )
            else:
                self._active_model = FALLBACK_CHAIN[0]
                logger.warning(
                    "No distillable models found, using fallback: %s",
                    self._active_model,
                )
            return self._active_model

    async def _fetch_distillable(self) -> list[str]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(OPENROUTER_FRONTEND_URL, timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Failed to fetch OpenRouter models: %s", e)
            return []

        models = data if isinstance(data, list) else data.get("data", [])
        candidates = []
        for m in models:
            model_id = m.get("slug") or m.get("id", "")
            provider = model_id.split("/")[0] if "/" in model_id else ""

            if provider in BLOCKED_PROVIDERS:
                continue
            if provider not in ALLOWED_PROVIDERS:
                continue
            if not m.get("is_trainable_text"):
                continue

            candidates.append(model_id)

        # Prefer models in the fallback chain order, then alphabetical
        def sort_key(mid: str) -> tuple[int, str]:
            try:
                return (FALLBACK_CHAIN.index(mid), mid)
            except ValueError:
                return (len(FALLBACK_CHAIN), mid)

        candidates.sort(key=sort_key)
        return candidates

    def validate_model(self, model_id: str) -> bool:
        if not model_id or "/" not in model_id:
            return False
        provider = model_id.split("/")[0]
        if provider in BLOCKED_PROVIDERS:
            return False
        if provider not in ALLOWED_PROVIDERS:
            return False
        return True
