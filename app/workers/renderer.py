import logging

import httpx

logger = logging.getLogger("clockchain.renderer")


class FlashClient:
    def __init__(self, base_url: str, service_key: str):
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Service-Key": self.service_key},
            timeout=600.0,
        )

    async def generate_sync(
        self,
        query: str,
        preset: str = "balanced",
        request_context: dict | None = None,
        generate_image: bool = True,
        model_policy: str | None = None,
    ) -> dict:
        logger.info("Flash generate: query=%r preset=%s generate_image=%s model_policy=%s", query, preset, generate_image, model_policy)
        body: dict = {"query": query, "preset": preset, "generate_image": generate_image}
        if model_policy:
            body["model_policy"] = model_policy
        if request_context:
            body["request_context"] = request_context
        resp = await self._client.post(
            "/api/v1/timepoints/generate/sync",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_timepoint(self, timepoint_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/timepoints/{timepoint_id}")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
