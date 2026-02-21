import asyncio
import json
import logging
import os
import secrets
from pathlib import Path

import networkx as nx
from fastapi import Request

logger = logging.getLogger("clockchain.graph")

VALID_EDGE_TYPES = {"causes", "contemporaneous", "same_location", "thematic"}


class GraphManager:
    BUNDLED_SEEDS_PATH = Path("/app/seeds/seeds.json")

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.graph_path = self.data_dir / "graph.json"
        self.seeds_path = self.data_dir / "seeds.json"
        self.graph = nx.DiGraph()
        self._lock = asyncio.Lock()

    async def load(self):
        async with self._lock:
            if self.graph_path.exists():
                logger.info("Loading graph from %s", self.graph_path)
                with open(self.graph_path) as f:
                    data = json.load(f)
                self.graph = nx.node_link_graph(data, directed=True)
            elif self.seeds_path.exists():
                logger.info("Initializing graph from seeds at %s", self.seeds_path)
                with open(self.seeds_path) as f:
                    seeds = json.load(f)
                self._load_seeds(seeds)
            elif self.BUNDLED_SEEDS_PATH.exists():
                logger.info("Volume empty, loading bundled seeds from %s", self.BUNDLED_SEEDS_PATH)
                with open(self.BUNDLED_SEEDS_PATH) as f:
                    seeds = json.load(f)
                self._load_seeds(seeds)
            else:
                logger.warning("No graph or seeds found, starting empty")
            logger.info(
                "Graph loaded: %d nodes, %d edges",
                self.graph.number_of_nodes(),
                self.graph.number_of_edges(),
            )

    def _load_seeds(self, seeds: dict):
        for node in seeds.get("nodes", []):
            node_id = node.pop("id")
            self.graph.add_node(node_id, **node)
        for edge in seeds.get("edges", []):
            self.graph.add_edge(
                edge["source"],
                edge["target"],
                type=edge.get("type", "thematic"),
                weight=edge.get("weight", 1.0),
                theme=edge.get("theme", ""),
            )

    async def save(self):
        async with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            data = nx.node_link_data(self.graph)
            with open(self.graph_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info("Graph saved to %s", self.graph_path)

    async def add_node(self, node_id: str, **attrs) -> None:
        async with self._lock:
            self.graph.add_node(node_id, **attrs)
            self._auto_link(node_id)

    async def add_edge(self, src: str, tgt: str, edge_type: str, **attrs) -> None:
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid edge type: {edge_type}. Must be one of {VALID_EDGE_TYPES}")
        async with self._lock:
            self.graph.add_edge(src, tgt, type=edge_type, **attrs)

    def get_node(self, node_id: str) -> dict | None:
        if node_id not in self.graph:
            return None
        attrs = dict(self.graph.nodes[node_id])
        attrs["path"] = node_id
        return attrs

    def browse(self, prefix: str = "") -> list[dict]:
        prefix = prefix.strip("/")
        results: dict[str, int] = {}
        for node_id in self.graph.nodes:
            attrs = self.graph.nodes[node_id]
            if attrs.get("visibility") != "public":
                continue
            node_path = node_id.strip("/")
            if prefix and not node_path.startswith(prefix):
                continue
            remainder = node_path[len(prefix):].strip("/") if prefix else node_path
            if not remainder:
                continue
            next_segment = remainder.split("/")[0]
            results[next_segment] = results.get(next_segment, 0) + 1
        items = [
            {"segment": seg, "count": count, "label": seg}
            for seg, count in sorted(results.items())
        ]
        return items

    def today_in_history(self, month: int, day: int) -> list[dict]:
        from app.core.url import NUM_TO_MONTH
        month_name = NUM_TO_MONTH.get(month, "")
        results = []
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("visibility") != "public":
                continue
            node_month = attrs.get("month", "")
            node_day = attrs.get("day")
            if (
                (isinstance(node_month, str) and node_month.lower() == month_name)
                or (isinstance(node_month, int) and node_month == month)
            ) and node_day == day:
                results.append({**attrs, "path": node_id})
        return results

    def random_public(self) -> dict | None:
        public = [
            node_id
            for node_id, attrs in self.graph.nodes(data=True)
            if attrs.get("visibility") == "public" and attrs.get("layer", 0) >= 1
        ]
        if not public:
            return None
        node_id = secrets.choice(public)
        attrs = dict(self.graph.nodes[node_id])
        attrs["path"] = node_id
        return attrs

    def search(self, query: str, limit: int = 20) -> list[dict]:
        query_lower = query.lower()
        results = []
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("visibility") != "public":
                continue
            score = 0.0
            name = attrs.get("name", "")
            one_liner = attrs.get("one_liner", "")
            tags = attrs.get("tags", [])
            figures = attrs.get("figures", [])
            searchable = " ".join(
                [name, one_liner]
                + (tags if isinstance(tags, list) else [])
                + (figures if isinstance(figures, list) else [])
            ).lower()
            if query_lower in searchable:
                if query_lower in name.lower():
                    score = 1.0
                elif query_lower in one_liner.lower():
                    score = 0.7
                else:
                    score = 0.4
                results.append({**attrs, "path": node_id, "score": score})
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    def get_neighbors(self, node_id: str) -> list[dict]:
        if node_id not in self.graph:
            return []
        neighbors = []
        for _, tgt, data in self.graph.out_edges(node_id, data=True):
            tgt_attrs = dict(self.graph.nodes[tgt])
            neighbors.append({
                "path": tgt,
                "name": tgt_attrs.get("name", ""),
                "edge_type": data.get("type", ""),
                "weight": data.get("weight", 1.0),
                "theme": data.get("theme", ""),
            })
        for src, _, data in self.graph.in_edges(node_id, data=True):
            src_attrs = dict(self.graph.nodes[src])
            neighbors.append({
                "path": src,
                "name": src_attrs.get("name", ""),
                "edge_type": data.get("type", ""),
                "weight": data.get("weight", 1.0),
                "theme": data.get("theme", ""),
            })
        return neighbors

    def stats(self) -> dict:
        layer_counts: dict[str, int] = {}
        edge_type_counts: dict[str, int] = {}
        for _, attrs in self.graph.nodes(data=True):
            layer = str(attrs.get("layer", 0))
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
        for _, _, data in self.graph.edges(data=True):
            etype = data.get("type", "unknown")
            edge_type_counts[etype] = edge_type_counts.get(etype, 0) + 1
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "layer_counts": layer_counts,
            "edge_type_counts": edge_type_counts,
        }

    def get_frontier_nodes(self, threshold: int = 3) -> list[str]:
        return [
            node_id
            for node_id in self.graph.nodes
            if self.graph.degree(node_id) < threshold
        ]

    def _auto_link(self, node_id: str):
        attrs = self.graph.nodes.get(node_id, {})
        node_year = attrs.get("year")
        node_country = attrs.get("country", "")
        node_region = attrs.get("region", "")
        node_city = attrs.get("city", "")
        node_tags = set(attrs.get("tags", []))

        for other_id, other_attrs in self.graph.nodes(data=True):
            if other_id == node_id:
                continue

            # contemporaneous: same year +/- 1
            other_year = other_attrs.get("year")
            if (
                node_year is not None
                and other_year is not None
                and abs(node_year - other_year) <= 1
            ):
                if not self.graph.has_edge(node_id, other_id):
                    self.graph.add_edge(node_id, other_id, type="contemporaneous", weight=0.5)
                if not self.graph.has_edge(other_id, node_id):
                    self.graph.add_edge(other_id, node_id, type="contemporaneous", weight=0.5)

            # same_location: matching country + region + city
            if (
                node_country
                and node_country == other_attrs.get("country", "")
                and node_region == other_attrs.get("region", "")
                and node_city == other_attrs.get("city", "")
            ):
                if not self.graph.has_edge(node_id, other_id):
                    self.graph.add_edge(node_id, other_id, type="same_location", weight=0.5)
                if not self.graph.has_edge(other_id, node_id):
                    self.graph.add_edge(other_id, node_id, type="same_location", weight=0.5)

            # thematic: overlapping tags
            other_tags = set(other_attrs.get("tags", []))
            overlap = node_tags & other_tags
            if overlap:
                theme = ", ".join(sorted(overlap))
                if not self.graph.has_edge(node_id, other_id):
                    self.graph.add_edge(
                        node_id, other_id, type="thematic", weight=0.3, theme=theme
                    )
                if not self.graph.has_edge(other_id, node_id):
                    self.graph.add_edge(
                        other_id, node_id, type="thematic", weight=0.3, theme=theme
                    )


async def get_graph_manager(request: Request) -> GraphManager:
    return request.app.state.graph_manager
