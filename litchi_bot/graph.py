from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import ceil
from typing import Iterable


ROUTE_COST = {
    "ROAD": 1380,
    "WATER": 1250,
    "MOUNTAIN": 1780,
    "BRANCH": 1550,
}


@dataclass(frozen=True)
class Edge:
    edge_id: str
    from_node: str
    to_node: str
    route_type: str
    distance: int
    bidirectional: bool = True

    @classmethod
    def from_raw(cls, raw: dict) -> "Edge":
        return cls(
            edge_id=str(raw.get("edgeId", "")),
            from_node=str(raw.get("fromNodeId") or raw.get("fromNode") or ""),
            to_node=str(raw.get("toNodeId") or raw.get("toNode") or ""),
            route_type=str(raw.get("routeType") or "ROAD"),
            distance=int(raw.get("distance") or 0),
            bidirectional=bool(raw.get("bidirectional", True)),
        )

    @property
    def movement_cost(self) -> int:
        return ceil(self.distance * ROUTE_COST.get(self.route_type, ROUTE_COST["ROAD"]))


class RouteGraph:
    def __init__(self, edges: Iterable[Edge]) -> None:
        self.edges = list(edges)
        self._adjacency: dict[str, list[tuple[str, Edge]]] = {}
        for edge in self.edges:
            if not edge.from_node or not edge.to_node:
                continue
            self._adjacency.setdefault(edge.from_node, []).append((edge.to_node, edge))
            if edge.bidirectional:
                self._adjacency.setdefault(edge.to_node, []).append((edge.from_node, edge))

    @classmethod
    def from_raw_edges(cls, raw_edges: Iterable[dict]) -> "RouteGraph":
        return cls(Edge.from_raw(raw) for raw in raw_edges)

    def neighbors(self, node_id: str) -> list[str]:
        return [neighbor for neighbor, _ in self._adjacency.get(node_id, [])]

    def path_movement_rounds(self, path: Iterable[str]) -> int | None:
        nodes = list(path)
        total = 0
        for from_node, to_node in zip(nodes, nodes[1:]):
            edge = self._edge_between(from_node, to_node)
            if edge is None:
                return None
            total += max(1, ceil(edge.movement_cost / 1000))
        return total

    def shortest_path_movement_rounds(
        self,
        start: str | None,
        goals: str | Iterable[str] | None,
        blocked: set[str] | None = None,
    ) -> int | None:
        path = self.shortest_path(start, goals, blocked=blocked)
        if not path:
            return None
        return self.path_movement_rounds(path)

    def shortest_path(
        self,
        start: str | None,
        goals: str | Iterable[str] | None,
        blocked: set[str] | None = None,
    ) -> list[str]:
        if not start or not goals:
            return []
        goal_set = {goals} if isinstance(goals, str) else set(goals)
        if start in goal_set:
            return [start]
        blocked = blocked or set()
        queue: list[tuple[int, str, list[str]]] = [(0, start, [start])]
        best: dict[str, int] = {start: 0}
        while queue:
            cost, node_id, path = heappop(queue)
            if cost > best.get(node_id, 0):
                continue
            for neighbor, edge in self._adjacency.get(node_id, []):
                if neighbor in blocked and neighbor not in goal_set:
                    continue
                next_cost = cost + max(1, edge.movement_cost)
                if next_cost >= best.get(neighbor, 10**18):
                    continue
                next_path = path + [neighbor]
                if neighbor in goal_set:
                    return next_path
                best[neighbor] = next_cost
                heappush(queue, (next_cost, neighbor, next_path))
        return []

    def _edge_between(self, from_node: str, to_node: str) -> Edge | None:
        for neighbor, edge in self._adjacency.get(from_node, []):
            if neighbor == to_node:
                return edge
        return None
