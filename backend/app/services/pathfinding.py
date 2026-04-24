from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass, field
from typing import Iterable

from scipy.spatial import cKDTree

from backend.app.database import get_db_connection

logger = logging.getLogger(__name__)

WALK_SPEED_MPS = 1.4
V_MAX_MPS = 15.0  # upper bound on any edge speed; keeps A* heuristic admissible
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class ClosureMask:
    blocked_stations: frozenset[str] = frozenset()
    blocked_segments: frozenset[tuple[int, int]] = frozenset()
    blocked_lines: frozenset[str] = frozenset()

    @classmethod
    def empty(cls) -> "ClosureMask":
        return cls()


@dataclass
class _Node:
    idx: int
    lat: float
    lng: float
    kind: str  # "walk" | "platform"
    platform_id: int | None = None
    station_id: str | None = None
    station_name: str | None = None
    line_id: str | None = None


@dataclass
class _Edge:
    to_idx: int
    weight: float
    kind: str  # "walk" | "ride" | "transfer" | "entrance"
    line_id: str | None = None


@dataclass
class PathStep:
    kind: str
    description: str
    duration_s: float
    line_id: str | None = None


@dataclass
class PathResult:
    total_time_s: float
    steps: list[PathStep]
    coords: list[tuple[float, float]]


class PathNotFoundError(Exception):
    pass


@dataclass
class _Overlay:
    """Per-query virtual nodes + extra edges; never touches the base graph."""

    node_coords: dict[int, tuple[float, float]] = field(default_factory=dict)
    extra_adj: dict[int, list[_Edge]] = field(default_factory=dict)


class PathfindingService:
    """Singleton: load graph once, answer queries with per-request overlay."""

    def __init__(self) -> None:
        self._nodes: list[_Node] = []
        self._adj: list[list[_Edge]] = []
        self._walk_idx_by_node_id: dict[int, int] = {}
        self._platform_idx_by_id: dict[int, int] = {}
        self._walk_tree: cKDTree | None = None
        self._walk_indices: list[int] = []
        self._load()

    # ---------------- loading ----------------

    def _load(self) -> None:
        with get_db_connection() as conn:
            walk_rows = conn.execute("SELECT id, lat, lng FROM walk_nodes").fetchall()
            plat_rows = conn.execute(
                "SELECT id, station_id, station_name, line_id, lat, lng FROM platforms"
            ).fetchall()
            ride_rows = conn.execute(
                "SELECT from_platform, to_platform, travel_time_s, line_id FROM ride_edges"
            ).fetchall()
            transfer_rows = conn.execute(
                "SELECT from_platform, to_platform, transfer_time_s FROM transfer_edges"
            ).fetchall()
            entrance_rows = conn.execute(
                "SELECT platform_id, walk_node_id, travel_time_s FROM entrance_edges"
            ).fetchall()
            walk_edge_rows = conn.execute(
                "SELECT from_node, to_node, travel_time_s FROM walk_edges"
            ).fetchall()

        for r in walk_rows:
            idx = len(self._nodes)
            self._nodes.append(_Node(idx=idx, lat=r["lat"], lng=r["lng"], kind="walk"))
            self._walk_idx_by_node_id[r["id"]] = idx

        for r in plat_rows:
            idx = len(self._nodes)
            self._nodes.append(
                _Node(
                    idx=idx,
                    lat=r["lat"],
                    lng=r["lng"],
                    kind="platform",
                    platform_id=r["id"],
                    station_id=r["station_id"],
                    station_name=r["station_name"],
                    line_id=r["line_id"],
                )
            )
            self._platform_idx_by_id[r["id"]] = idx

        self._adj = [[] for _ in self._nodes]

        for r in walk_edge_rows:
            a = self._walk_idx_by_node_id.get(r["from_node"])
            b = self._walk_idx_by_node_id.get(r["to_node"])
            if a is None or b is None:
                continue
            self._adj[a].append(_Edge(to_idx=b, weight=r["travel_time_s"], kind="walk"))

        for r in ride_rows:
            a = self._platform_idx_by_id.get(r["from_platform"])
            b = self._platform_idx_by_id.get(r["to_platform"])
            if a is None or b is None:
                continue
            self._adj[a].append(
                _Edge(to_idx=b, weight=r["travel_time_s"], kind="ride", line_id=r["line_id"])
            )

        for r in transfer_rows:
            a = self._platform_idx_by_id.get(r["from_platform"])
            b = self._platform_idx_by_id.get(r["to_platform"])
            if a is None or b is None:
                continue
            self._adj[a].append(
                _Edge(to_idx=b, weight=r["transfer_time_s"], kind="transfer")
            )

        for r in entrance_rows:
            p = self._platform_idx_by_id.get(r["platform_id"])
            w = self._walk_idx_by_node_id.get(r["walk_node_id"])
            if p is None or w is None:
                continue
            # bidirectional: walk <-> platform
            self._adj[w].append(_Edge(to_idx=p, weight=r["travel_time_s"], kind="entrance"))
            self._adj[p].append(_Edge(to_idx=w, weight=r["travel_time_s"], kind="entrance"))

        self._walk_indices = [n.idx for n in self._nodes if n.kind == "walk"]
        if self._walk_indices:
            coords = [(self._nodes[i].lat, self._nodes[i].lng) for i in self._walk_indices]
            self._walk_tree = cKDTree(coords)

        logger.info(
            "Graph loaded: %d nodes, %d edges",
            len(self._nodes),
            sum(len(a) for a in self._adj),
        )

    # ---------------- public ----------------

    @property
    def is_ready(self) -> bool:
        return bool(self._nodes) and self._walk_tree is not None

    def find_path(
        self,
        lat_start: float,
        lng_start: float,
        lat_end: float,
        lng_end: float,
        closures: ClosureMask | None = None,
    ) -> PathResult:
        if not self.is_ready:
            raise PathNotFoundError("Graph not loaded")
        closures = closures or ClosureMask.empty()

        overlay, start_idx, end_idx = self._build_overlay(
            lat_start, lng_start, lat_end, lng_end
        )
        came_from, came_edge, g_score = self._a_star(start_idx, end_idx, overlay, closures)
        if end_idx not in came_from and start_idx != end_idx:
            raise PathNotFoundError("No route found")

        path_idx, path_edges = self._reconstruct(start_idx, end_idx, came_from, came_edge)
        return self._format(path_idx, path_edges, overlay, g_score[end_idx])

    # ---------------- internal helpers ----------------

    def _coord(self, idx: int, overlay: _Overlay) -> tuple[float, float]:
        if idx < len(self._nodes):
            n = self._nodes[idx]
            return n.lat, n.lng
        return overlay.node_coords[idx]

    def _neighbors(self, idx: int, overlay: _Overlay) -> Iterable[_Edge]:
        if idx < len(self._adj):
            yield from self._adj[idx]
        if idx in overlay.extra_adj:
            yield from overlay.extra_adj[idx]

    def _build_overlay(
        self, lat_s: float, lng_s: float, lat_e: float, lng_e: float
    ) -> tuple[_Overlay, int, int]:
        assert self._walk_tree is not None
        overlay = _Overlay()

        start_idx = len(self._nodes)
        end_idx = start_idx + 1
        overlay.node_coords[start_idx] = (lat_s, lng_s)
        overlay.node_coords[end_idx] = (lat_e, lng_e)

        # Snap each endpoint to the nearest walk node.
        _, start_walk_pos = self._walk_tree.query((lat_s, lng_s), k=1)
        _, end_walk_pos = self._walk_tree.query((lat_e, lng_e), k=1)
        start_walk_idx = self._walk_indices[int(start_walk_pos)]
        end_walk_idx = self._walk_indices[int(end_walk_pos)]

        sw = self._nodes[start_walk_idx]
        ew = self._nodes[end_walk_idx]
        t_start = haversine_m(lat_s, lng_s, sw.lat, sw.lng) / WALK_SPEED_MPS
        t_end = haversine_m(lat_e, lng_e, ew.lat, ew.lng) / WALK_SPEED_MPS

        # Start is a source; end is a sink. Directed is enough.
        overlay.extra_adj[start_idx] = [
            _Edge(to_idx=start_walk_idx, weight=t_start, kind="walk")
        ]
        overlay.extra_adj.setdefault(end_walk_idx, []).append(
            _Edge(to_idx=end_idx, weight=t_end, kind="walk")
        )
        return overlay, start_idx, end_idx

    def _is_blocked(self, from_idx: int, edge: _Edge, closures: ClosureMask) -> bool:
        if not closures.blocked_stations and not closures.blocked_segments and not closures.blocked_lines:
            return False
        to_n = self._nodes[edge.to_idx] if edge.to_idx < len(self._nodes) else None
        from_n = self._nodes[from_idx] if from_idx < len(self._nodes) else None

        if edge.kind == "ride":
            if edge.line_id and edge.line_id in closures.blocked_lines:
                return True
            if from_n and to_n:
                seg = (from_n.platform_id, to_n.platform_id)
                if seg in closures.blocked_segments:
                    return True
            if to_n and to_n.station_id in closures.blocked_stations:
                return True
            if from_n and from_n.station_id in closures.blocked_stations:
                return True
        elif edge.kind == "transfer":
            if to_n and to_n.station_id in closures.blocked_stations:
                return True
            if to_n and to_n.line_id in closures.blocked_lines:
                return True
        elif edge.kind == "entrance":
            if to_n and to_n.kind == "platform":
                if to_n.station_id in closures.blocked_stations:
                    return True
                if to_n.line_id in closures.blocked_lines:
                    return True
            if from_n and from_n.kind == "platform":
                if from_n.station_id in closures.blocked_stations:
                    return True
                if from_n.line_id in closures.blocked_lines:
                    return True
        return False

    def _heuristic(self, idx: int, goal_coord: tuple[float, float], overlay: _Overlay) -> float:
        lat, lng = self._coord(idx, overlay)
        return haversine_m(lat, lng, goal_coord[0], goal_coord[1]) / V_MAX_MPS

    def _a_star(
        self,
        start_idx: int,
        end_idx: int,
        overlay: _Overlay,
        closures: ClosureMask,
    ) -> tuple[dict[int, int], dict[int, _Edge], dict[int, float]]:
        goal_coord = self._coord(end_idx, overlay)
        g_score: dict[int, float] = {start_idx: 0.0}
        came_from: dict[int, int] = {}
        came_edge: dict[int, _Edge] = {}
        open_heap: list[tuple[float, int, int]] = []
        counter = 0
        heapq.heappush(open_heap, (self._heuristic(start_idx, goal_coord, overlay), counter, start_idx))
        closed: set[int] = set()

        while open_heap:
            _, _, current = heapq.heappop(open_heap)
            if current == end_idx:
                return came_from, came_edge, g_score
            if current in closed:
                continue
            closed.add(current)

            for edge in self._neighbors(current, overlay):
                if edge.to_idx in closed:
                    continue
                if self._is_blocked(current, edge, closures):
                    continue
                tentative_g = g_score[current] + edge.weight
                if tentative_g < g_score.get(edge.to_idx, math.inf):
                    g_score[edge.to_idx] = tentative_g
                    came_from[edge.to_idx] = current
                    came_edge[edge.to_idx] = edge
                    f = tentative_g + self._heuristic(edge.to_idx, goal_coord, overlay)
                    counter += 1
                    heapq.heappush(open_heap, (f, counter, edge.to_idx))

        return came_from, came_edge, g_score

    def _reconstruct(
        self,
        start_idx: int,
        end_idx: int,
        came_from: dict[int, int],
        came_edge: dict[int, _Edge],
    ) -> tuple[list[int], list[_Edge]]:
        nodes: list[int] = [end_idx]
        edges: list[_Edge] = []
        cur = end_idx
        while cur != start_idx:
            edges.append(came_edge[cur])
            cur = came_from[cur]
            nodes.append(cur)
        nodes.reverse()
        edges.reverse()
        return nodes, edges

    def _format(
        self,
        path_idx: list[int],
        path_edges: list[_Edge],
        overlay: _Overlay,
        total_time: float,
    ) -> PathResult:
        coords = [self._coord(i, overlay) for i in path_idx]

        steps: list[PathStep] = []
        i = 0
        while i < len(path_edges):
            edge = path_edges[i]
            from_node = self._nodes[path_idx[i]] if path_idx[i] < len(self._nodes) else None
            to_node = self._nodes[path_idx[i + 1]] if path_idx[i + 1] < len(self._nodes) else None

            if edge.kind == "walk":
                # Coalesce consecutive walk edges.
                dur = 0.0
                j = i
                while j < len(path_edges) and path_edges[j].kind == "walk":
                    dur += path_edges[j].weight
                    j += 1
                steps.append(PathStep(kind="walk", description=f"Walk ({self._fmt_dur(dur)})", duration_s=dur))
                i = j
                continue

            if edge.kind == "entrance":
                if from_node and from_node.kind == "walk" and to_node and to_node.kind == "platform":
                    steps.append(
                        PathStep(
                            kind="enter",
                            description=f"Enter metro at {to_node.station_name} (Line {to_node.line_id})",
                            duration_s=edge.weight,
                            line_id=to_node.line_id,
                        )
                    )
                else:
                    name = from_node.station_name if from_node else "metro"
                    steps.append(
                        PathStep(
                            kind="exit",
                            description=f"Exit metro at {name} to street",
                            duration_s=edge.weight,
                        )
                    )
                i += 1
                continue

            if edge.kind == "ride":
                # Coalesce consecutive rides on the same line.
                dur = 0.0
                j = i
                last_to = to_node
                while (
                    j < len(path_edges)
                    and path_edges[j].kind == "ride"
                    and path_edges[j].line_id == edge.line_id
                ):
                    dur += path_edges[j].weight
                    last_to_idx = path_idx[j + 1]
                    last_to = self._nodes[last_to_idx] if last_to_idx < len(self._nodes) else None
                    j += 1
                start_name = from_node.station_name if from_node else "?"
                end_name = last_to.station_name if last_to else "?"
                steps.append(
                    PathStep(
                        kind="ride",
                        description=f"Take Line {edge.line_id} from {start_name} to {end_name}",
                        duration_s=dur,
                        line_id=edge.line_id,
                    )
                )
                i = j
                continue

            if edge.kind == "transfer":
                line_to = to_node.line_id if to_node else "?"
                name = from_node.station_name if from_node else "station"
                steps.append(
                    PathStep(
                        kind="transfer",
                        description=f"Transfer at {name} to Line {line_to}",
                        duration_s=edge.weight,
                        line_id=line_to,
                    )
                )
                i += 1
                continue

            i += 1  # fallback

        return PathResult(total_time_s=total_time, steps=steps, coords=coords)

    @staticmethod
    def _fmt_dur(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        if m == 0:
            return f"{s}s"
        return f"{m}m {s}s"
