import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from app.core.graph import GraphManager

logger = logging.getLogger("clockchain.expander")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

EXPANSION_PROMPT = """You are a historian. Given this historical event, suggest 3-5 closely related historical events.

Event: {name}
Date: {year}/{month}/{day}
Location: {country}, {region}, {city}
Description: {one_liner}

Return a JSON array of objects, each with:
- "name": event name
- "year": integer (negative for BCE)
- "month": lowercase month name (e.g. "march")
- "day": integer
- "time": 4-digit 24hr string (e.g. "1400")
- "country": lowercase, hyphenated
- "region": lowercase, hyphenated
- "city": lowercase, hyphenated
- "one_liner": one sentence description
- "tags": list of lowercase hyphenated tags
- "figures": list of historical figure names
- "edge_type": one of "causes", "contemporaneous", "same_location", "thematic"

Return ONLY the JSON array, no other text."""


class GraphExpander:
    def __init__(
        self,
        graph_manager: GraphManager,
        api_key: str,
        model: str = "google/gemini-2.0-flash-001",
        interval_seconds: int = 300,
    ):
        self.gm = graph_manager
        self.api_key = api_key
        self.model = model
        self.interval = interval_seconds

    async def start(self):
        logger.info("Graph expander starting (interval=%ds)", self.interval)
        while True:
            try:
                await self._expand_once()
            except asyncio.CancelledError:
                logger.info("Graph expander cancelled")
                break
            except Exception as e:
                logger.error("Expander error: %s", e)
            await asyncio.sleep(self.interval)

    async def _expand_once(self):
        frontier = self.gm.get_frontier_nodes(threshold=3)
        if not frontier:
            logger.info("No frontier nodes to expand")
            return

        node_id = frontier[0]
        node = self.gm.get_node(node_id)
        if not node:
            return

        logger.info("Expanding from node: %s", node_id)
        related = await self._generate_related(node)

        for event in related:
            await self._add_event(event, source_node_id=node_id)

        await self.gm.save()
        logger.info("Expansion complete: added %d events from %s", len(related), node_id)

    async def _generate_related(self, node: dict) -> list[dict]:
        prompt = EXPANSION_PROMPT.format(
            name=node.get("name", ""),
            year=node.get("year", ""),
            month=node.get("month", ""),
            day=node.get("day", ""),
            country=node.get("country", ""),
            region=node.get("region", ""),
            city=node.get("city", ""),
            one_liner=node.get("one_liner", ""),
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        return json.loads(text)

    async def _add_event(self, event: dict, source_node_id: str):
        from app.core.url import build_path, MONTH_TO_NUM

        month_str = str(event.get("month", "january")).lower()
        month_num = MONTH_TO_NUM.get(month_str, 1)

        path = build_path(
            year=event.get("year", 0),
            month=month_num,
            day=event.get("day", 1),
            time=event.get("time", "1200"),
            country=event.get("country", "unknown"),
            region=event.get("region", "unknown"),
            city=event.get("city", "unknown"),
            slug=event.get("name", "unknown"),
        )

        if self.gm.get_node(path):
            return

        await self.gm.add_node(
            path,
            type="event",
            name=event.get("name", ""),
            year=event.get("year", 0),
            month=month_str,
            month_num=month_num,
            day=event.get("day", 1),
            time=event.get("time", "1200"),
            country=event.get("country", "unknown"),
            region=event.get("region", "unknown"),
            city=event.get("city", "unknown"),
            slug=path.split("/")[-1],
            layer=1,
            visibility="public",
            created_by="system",
            tags=event.get("tags", []),
            one_liner=event.get("one_liner", ""),
            figures=event.get("figures", []),
            flash_timepoint_id=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        edge_type = event.get("edge_type", "thematic")
        if edge_type in {"causes", "contemporaneous", "same_location", "thematic"}:
            try:
                await self.gm.add_edge(
                    source_node_id, path, edge_type, weight=0.5
                )
            except ValueError:
                pass
