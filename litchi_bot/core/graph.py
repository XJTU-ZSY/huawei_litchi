from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import heapq

from .models import Edge


@dataclass(frozen=True)
class Step:
    node_id: str
    cost: int
    edge_id: str


class MapGraph:
    def __init__(self, edges: list[Edge]) -> None:
        self._adjacency: dict[str, list[Step]] = defaultdict(list)
        for edge in edges:
            self._adjacency[edge.from_node_id].append(Step(edge.to_node_id, edge.distance, edge.edge_id))
            if edge.bidirectional:
                self._adjacency[edge.to_node_id].append(Step(edge.from_node_id, edge.distance, edge.edge_id))

        for steps in self._adjacency.values():
            steps.sort(key=lambda step: (step.cost, step.node_id, step.edge_id))

    @classmethod
    def from_raw_edges(cls, raw_edges: list[dict]) -> "MapGraph":
        edges = [edge for raw in raw_edges if (edge := Edge.from_raw(raw)) is not None]
        return cls(edges)

    def neighbors(self, node_id: str) -> list[str]:
        return [step.node_id for step in self._adjacency.get(node_id, [])]

    def next_hop(self, start: str, goals: list[str] | tuple[str, ...] | set[str]) -> str | None:
        path = self.shortest_path(start, goals)
        if len(path) < 2:
            return None
        return path[1]

    def shortest_path(self, start: str, goals: list[str] | tuple[str, ...] | set[str]) -> list[str]:
        goal_set = set(goals)
        if not start or not goal_set:
            return []
        if start in goal_set:
            return [start]

        queue: list[tuple[int, str]] = [(0, start)]
        best_cost: dict[str, int] = {start: 0}
        previous: dict[str, str] = {}
        found: str | None = None

        while queue:
            cost, node_id = heapq.heappop(queue)
            if cost != best_cost.get(node_id):
                continue
            if node_id in goal_set:
                found = node_id
                break

            for step in self._adjacency.get(node_id, []):
                next_cost = cost + step.cost
                old_cost = best_cost.get(step.node_id)
                if old_cost is None or next_cost < old_cost:
                    best_cost[step.node_id] = next_cost
                    previous[step.node_id] = node_id
                    heapq.heappush(queue, (next_cost, step.node_id))

        if found is None:
            return []

        path = [found]
        while path[-1] != start:
            path.append(previous[path[-1]])
        path.reverse()
        return path
