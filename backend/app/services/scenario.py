from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from backend.app.database import get_db_connection
from backend.app.services.pathfinding import ClosureMask

logger = logging.getLogger(__name__)

_VALID_TYPES = {"station", "segment", "line"}


class ScenarioError(ValueError):
    """Raised for invalid scenario payloads."""


@dataclass
class Scenario:
    id: int
    type: str
    payload: dict[str, Any]
    created_at: str


class ScenarioService:
    """CRUD on admin scenarios + compiles active ones into a ClosureMask."""

    def __init__(self) -> None:
        self._mask: ClosureMask = ClosureMask.empty()
        self.refresh()

    # ---------------- read ----------------

    def get_mask(self) -> ClosureMask:
        return self._mask

    def list_scenarios(self) -> list[Scenario]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, type, payload_json, created_at FROM scenarios ORDER BY id"
            ).fetchall()
        return [
            Scenario(
                id=r["id"],
                type=r["type"],
                payload=json.loads(r["payload_json"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ---------------- write ----------------

    def create_scenario(self, s_type: str, payload: dict[str, Any]) -> Scenario:
        self._validate(s_type, payload)
        if s_type == "segment":
            self._validate_segment_payload(payload)
        with get_db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO scenarios (type, payload_json) VALUES (?, ?)",
                (s_type, json.dumps(payload)),
            )
            sid = cur.lastrowid
            row = conn.execute(
                "SELECT id, type, payload_json, created_at FROM scenarios WHERE id = ?",
                (sid,),
            ).fetchone()
        self.refresh()
        return Scenario(
            id=row["id"],
            type=row["type"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )

    def delete_scenario(self, sid: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.execute("DELETE FROM scenarios WHERE id = ?", (sid,))
            deleted = cur.rowcount > 0
        if deleted:
            self.refresh()
        return deleted

    def clear_all(self) -> int:
        with get_db_connection() as conn:
            cur = conn.execute("DELETE FROM scenarios")
            count = cur.rowcount
        self.refresh()
        return count

    # ---------------- internal ----------------

    @staticmethod
    def _validate(s_type: str, payload: dict[str, Any]) -> None:
        if s_type not in _VALID_TYPES:
            raise ScenarioError(f"Unknown scenario type: {s_type!r}")
        if s_type == "station":
            if not payload.get("station_id"):
                raise ScenarioError("station scenario requires 'station_id'")
        elif s_type == "line":
            if not payload.get("line_id"):
                raise ScenarioError("line scenario requires 'line_id'")
        elif s_type == "segment":
            for key in ("line_id", "from_station_id", "to_station_id"):
                if not payload.get(key):
                    raise ScenarioError(f"segment scenario requires {key!r}")

    def _validate_segment_payload(self, payload: dict[str, Any]) -> None:
        line = payload.get("line_id")
        a = payload.get("from_station_id")
        b = payload.get("to_station_id")
        if not (line and a and b):
            return

        with get_db_connection() as conn:
            platform_rows = conn.execute(
                "SELECT id, station_id, line_id FROM platforms WHERE line_id = ?",
                (line,),
            ).fetchall()
            platform_by_key = {(r["station_id"], r["line_id"]): r["id"] for r in platform_rows}
            pa = platform_by_key.get((a, line))
            pb = platform_by_key.get((b, line))
            if pa is None or pb is None:
                raise ScenarioError("Segment scenario references invalid station or line")
            if pa == pb:
                raise ScenarioError("Segment scenario must specify two different stations")

            if self._find_segment_path(conn, line, pa, pb) is None:
                raise ScenarioError(
                    "Segment scenario must close a connected section of the selected line"
                )

    def _find_segment_path(
        self, conn: sqlite3.Connection, line: str, a: int, b: int
    ) -> list[int] | None:
        rows = conn.execute(
            "SELECT from_platform, to_platform FROM ride_edges WHERE line_id = ?",
            (line,),
        ).fetchall()
        adjacency: dict[int, set[int]] = defaultdict(set)
        for r in rows:
            adjacency[r["from_platform"]].add(r["to_platform"])
            adjacency[r["to_platform"]].add(r["from_platform"])

        visited: set[int] = {a}
        queue = deque([(a, [a])])
        while queue:
            current, path = queue.popleft()
            if current == b:
                return path
            for neighbor in adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
        return None

    def refresh(self) -> None:
        """Recompile the cached mask from DB state."""
        with get_db_connection() as conn:
            platform_rows = conn.execute(
                "SELECT id, station_id, line_id FROM platforms"
            ).fetchall()
            scenario_rows = conn.execute(
                "SELECT type, payload_json FROM scenarios"
            ).fetchall()

            platform_by_key: dict[tuple[str, str], int] = {
                (r["station_id"], r["line_id"]): r["id"] for r in platform_rows
            }
            by_station: dict[str, list[int]] = defaultdict(list)
            for (sid, _line), pk in platform_by_key.items():
                by_station[sid].append(pk)

            blocked_stations: set[str] = set()
            blocked_segments: set[tuple[int, int]] = set()
            blocked_lines: set[str] = set()

            for row in scenario_rows:
                payload = json.loads(row["payload_json"])
                t = row["type"]
                if t == "station":
                    sid = payload.get("station_id")
                    if sid:
                        blocked_stations.add(sid)
                elif t == "line":
                    lid = payload.get("line_id")
                    if lid:
                        blocked_lines.add(lid)
                elif t == "segment":
                    line = payload.get("line_id")
                    a = payload.get("from_station_id")
                    b = payload.get("to_station_id")
                    pa = platform_by_key.get((a, line)) if (line and a) else None
                    pb = platform_by_key.get((b, line)) if (line and b) else None
                    if pa and pb:
                        path = self._find_segment_path(conn, line, pa, pb)
                        if path is not None:
                            # also mark the endpoint stations as closed so the UI
                            # renders them like closed stations
                            if a:
                                blocked_stations.add(a)
                            if b:
                                blocked_stations.add(b)
                            for x, y in zip(path, path[1:]):
                                blocked_segments.add((x, y))
                                blocked_segments.add((y, x))
                        else:
                            logger.warning(
                                "Ignoring invalid segment scenario for line %s: %s-%s",
                                line,
                                a,
                                b,
                            )

            self._mask = ClosureMask(
                blocked_stations=frozenset(blocked_stations),
                blocked_segments=frozenset(blocked_segments),
                blocked_lines=frozenset(blocked_lines),
            )
        logger.info(
            "Scenario mask refreshed: %d stations, %d segments, %d lines",
            len(blocked_stations),
            len(blocked_segments) // 2,
            len(blocked_lines),
        )
