#!/usr/bin/env python3
"""
Local match server for "一骑红尘：荔枝争运战".

The server implements the TCP framing protocol described by the competition
documents:

    5 ASCII decimal digits + UTF-8 JSON body

It is intended as a local referee/debug server for client development.  The
implementation keeps all dependencies in the Python standard library and writes
both human-readable logs and structured JSONL audit logs.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import logging
import math
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


MAX_FRAME_LEN = 99_999
RULES_VERSION = "local-python-v1"
START_ROUND = 1
DEFAULT_DURATION_ROUND = 600
DEFAULT_ALLOWED_PLAYER_IDS = {1001, 1002}

TEAM_BY_CAMP = {0: "RED", 1: "BLUE"}
CAMP_BY_TEAM = {"RED": 0, "BLUE": 1}

ROUTE_COST = {
    "ROAD": 1380,
    "WATER": 1250,
    "MOUNTAIN": 1780,
    "BRANCH": 1550,
}

ROUTE_FRESHNESS_DROP = {
    "ROAD": 0.055,
    "WATER": 0.045,
    "MOUNTAIN": 0.070,
    "BRANCH": 0.065,
}

IDLE_FRESHNESS_DROP = 0.05
FRESHNESS_THRESHOLDS = [90, 80, 70, 60, 50, 40, 30, 20, 10]

MAIN_ACTIONS = {
    "WAIT",
    "MOVE",
    "DELIVER",
    "VERIFY_GATE",
    "SET_GUARD",
    "BREAK_GUARD",
    "FORCED_PASS",
    "CLAIM_RESOURCE",
    "USE_RESOURCE",
    "CLAIM_TASK",
    "CLEAR",
    "PROCESS",
    "DOCK",
    "RUSH_SPEED",
    "RUSH_PROTECT",
}

SQUAD_ACTIONS = {
    "SQUAD_SCOUT",
    "SQUAD_CLEAR",
    "SQUAD_REINFORCE",
    "SQUAD_WEAKEN",
}

WINDOW_ACTIONS = {"WINDOW_CARD"}
RUSH_ACTIONS = {"RUSH_SPEED", "RUSH_PROTECT"}
ALL_ACTIONS = MAIN_ACTIONS | SQUAD_ACTIONS | WINDOW_ACTIONS | {"BREAK_ORDER"}

HORSE_BUFFS = {"FAST_HORSE", "SHORT_HORSE"}
MOVE_SPEED_BY_BUFF = {
    "FAST_HORSE": 1200,
    "SHORT_HORSE": 1150,
    "RUSH_SPEED": 1300,
}

BUFF_DURATION = {
    "FAST_HORSE": 20,
    "SHORT_HORSE": 14,
    "RUSH_SPEED": 15,
    "RUSH_PROTECT": 30,
}

WINDOW_CARDS = {"YAN_DIE", "QIANG_XING", "XIAN_GONG", "BING_ZHENG", "ABSTAIN"}

CARD_WIN_TABLE = {
    ("YAN_DIE", "QIANG_XING"): 1,
    ("YAN_DIE", "XIAN_GONG"): -1,
    ("YAN_DIE", "BING_ZHENG"): -1,
    ("QIANG_XING", "YAN_DIE"): -1,
    ("QIANG_XING", "XIAN_GONG"): 1,
    ("QIANG_XING", "BING_ZHENG"): -1,
    ("XIAN_GONG", "YAN_DIE"): 1,
    ("XIAN_GONG", "QIANG_XING"): -1,
    ("XIAN_GONG", "BING_ZHENG"): 1,
    ("BING_ZHENG", "YAN_DIE"): 1,
    ("BING_ZHENG", "QIANG_XING"): 1,
    ("BING_ZHENG", "XIAN_GONG"): -1,
}


class ProtocolError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")


def parse_wire_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pack_message(msg_name: str, msg_data: Dict[str, Any]) -> bytes:
    body = json.dumps(
        {"msg_name": msg_name, "msg_data": msg_data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_FRAME_LEN:
        raise ProtocolError("INVALID_LENGTH_PREFIX", f"message body too large: {len(body)} bytes")
    return f"{len(body):05d}".encode("ascii") + body


async def read_message(reader: asyncio.StreamReader) -> Dict[str, Any]:
    prefix = await reader.readexactly(5)
    if not prefix.isdigit():
        raise ProtocolError("INVALID_LENGTH_PREFIX", f"invalid length prefix: {prefix!r}")
    size = int(prefix)
    if size <= 0 or size > MAX_FRAME_LEN:
        raise ProtocolError("INVALID_LENGTH_PREFIX", f"invalid frame size: {size}")
    body = await reader.readexactly(size)
    try:
        obj = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ProtocolError("INVALID_JSON", f"body is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProtocolError("INVALID_JSON", f"body is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("INVALID_JSON", "message body must be a JSON object")
    return obj


class AuditLogger:
    """Structured JSONL logger used for protocol and referee replay."""

    def __init__(self, log_dir: Path, match_id: str):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{match_id}.audit.jsonl"
        self._fp = self.path.open("a", encoding="utf-8")
        self._lock = asyncio.Lock()
        self._closed = False

    async def write(self, kind: str, **payload: Any) -> None:
        if self._closed:
            return
        record = {"ts": utc_now_iso(), "kind": kind, **payload}
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            if self._closed:
                return
            self._fp.write(line + "\n")
            self._fp.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fp.close()


class ReplayLogger:
    """Clean JSONL replay containing server-visible game messages only."""

    def __init__(self, log_dir: Path, match_id: str):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{match_id}.replay.jsonl"
        self._fp = self.path.open("a", encoding="utf-8")
        self._lock = asyncio.Lock()
        self._closed = False

    async def write_message(self, msg_name: str, msg_data: Dict[str, Any]) -> None:
        if self._closed:
            return
        message = {"msg_name": msg_name, "msg_data": msg_data}
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            if self._closed:
                return
            self._fp.write(line + "\n")
            self._fp.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fp.close()


def close_logger_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def setup_logging(log_dir: Path, verbose: bool) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lychee_server")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(log_dir / f"server_{stamp}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
    return logger


@dataclass
class NodeConfig:
    node_id: str
    code: str
    name: str
    node_type: str
    x: int
    y: int
    icon: str
    start: bool = False
    terminal: bool = False

    def to_wire(self) -> Dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "code": self.code,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "type": self.node_type,
            "icon": self.icon,
            "nodeType": self.node_type,
            "start": self.start,
            "terminal": self.terminal,
        }


@dataclass
class EdgeConfig:
    edge_id: str
    from_node: str
    to_node: str
    route_type: str
    distance: int
    bidirectional: bool = True
    path_id: Optional[str] = None

    def to_wire(self) -> Dict[str, Any]:
        return {
            "edgeId": self.edge_id,
            "fromNode": self.from_node,
            "toNode": self.to_node,
            "fromNodeId": self.from_node,
            "toNodeId": self.to_node,
            "routeType": self.route_type,
            "distance": self.distance,
            "bidirectional": self.bidirectional,
            "pathId": self.path_id or self.edge_id,
        }


@dataclass
class ResourceConfig:
    node_id: str
    resource_type: str
    count: int
    claim_round: int

    def to_wire(self) -> Dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "resourceType": self.resource_type,
            "count": self.count,
            "claimRound": self.claim_round,
        }


@dataclass
class ProcessConfig:
    node_id: str
    process_type: str
    process_round: int
    can_window: bool = True

    def to_wire(self) -> Dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "processType": self.process_type,
            "processRound": self.process_round,
            "canWindow": self.can_window,
        }


@dataclass
class TaskTemplate:
    template_id: str
    name: str
    candidate_node_ids: List[str]
    process_type: str
    process_round: int
    required_freshness: float
    required_resource_types: List[str]
    score: int

    def to_wire(self) -> Dict[str, Any]:
        return {
            "taskTemplateId": self.template_id,
            "name": self.name,
            "candidateNodeIds": self.candidate_node_ids,
            "processType": self.process_type,
            "processRound": self.process_round,
            "requiredFreshness": self.required_freshness,
            "requiredResourceTypes": list(self.required_resource_types),
            "score": self.score,
        }


@dataclass
class GuardState:
    owner_team_id: Optional[str] = None
    defense: int = 0
    initial_defense: int = 0
    max_defense: int = 6
    complete_round: int = 0
    guard_block_count: int = 0
    key_pass_combat_count: int = 0

    @property
    def active(self) -> bool:
        return self.owner_team_id is not None and self.defense > 0

    def to_wire(self, current_round: int) -> Dict[str, Any]:
        return {
            "ownerTeamId": self.owner_team_id,
            "defense": self.defense,
            "initialDefense": self.initial_defense,
            "maxDefense": self.max_defense,
            "completeRound": self.complete_round,
            "ageRound": max(0, current_round - self.complete_round) if self.complete_round else 0,
            "active": self.active,
        }


@dataclass
class ScoutMarker:
    team_id: str
    created_round: int
    process_reduce_round: int = 3
    remaining_triggers: int = 1
    duration_round: int = 45

    def remain(self, current_round: int) -> int:
        return max(0, self.created_round + self.duration_round - current_round + 1)

    def active(self, current_round: int) -> bool:
        return self.remaining_triggers > 0 and self.remain(current_round) > 0

    def to_wire(self, current_round: int) -> Dict[str, Any]:
        return {
            "teamId": self.team_id,
            "remainRound": self.remain(current_round),
            "processReduceRound": self.process_reduce_round,
            "remainingTriggers": self.remaining_triggers,
        }


@dataclass
class ObstacleResidue:
    cleared_by_player_id: int
    cleared_by_team_id: str
    clear_round: int
    until_round: int
    tax_round: int = 6

    def to_wire(self, current_round: int) -> Dict[str, Any]:
        return {
            "clearedByPlayerId": self.cleared_by_player_id,
            "clearedByTeamId": self.cleared_by_team_id,
            "clearRound": self.clear_round,
            "untilRound": self.until_round,
            "remainRound": max(0, self.until_round - current_round + 1),
            "taxRound": self.tax_round,
        }


@dataclass
class NodeState:
    config: NodeConfig
    process_type: Optional[str] = None
    process_round: int = 0
    can_window: bool = True
    resource_stock: Dict[str, int] = field(default_factory=dict)
    guard: GuardState = field(default_factory=GuardState)
    scouted: List[ScoutMarker] = field(default_factory=list)
    effective_combat_count: int = 0
    has_obstacle: bool = False
    obstacle_type: Optional[str] = None
    obstacle_residue: Optional[ObstacleResidue] = None

    def to_wire(self, current_round: int) -> Dict[str, Any]:
        stock = {
            "ICE_BOX": 0,
            "FAST_HORSE": 0,
            "SHORT_HORSE": 0,
            "BOAT_RIGHT": 0,
            "PASS_TOKEN": 0,
            "OFFICIAL_PERMIT": 0,
            "INTEL": 0,
        }
        stock.update(self.resource_stock)
        self.scouted = [m for m in self.scouted if m.active(current_round)]
        return {
            "nodeId": self.config.node_id,
            "name": self.config.name,
            "x": self.config.x,
            "y": self.config.y,
            "nodeType": self.config.node_type,
            "processType": self.process_type,
            "processRound": self.process_round,
            "start": self.config.start,
            "terminal": self.config.terminal,
            "visible": True,
            "guard": self.guard.to_wire(current_round),
            "resourceVisible": True,
            "resourceStock": stock,
            "scouted": [m.to_wire(current_round) for m in self.scouted],
            "effectiveCombatCount": self.effective_combat_count,
            "guardBlockCount": self.guard.guard_block_count,
            "keyPassCombatCount": self.guard.key_pass_combat_count,
            "hasObstacle": self.has_obstacle,
            "obstacleType": self.obstacle_type,
            "obstacleResidue": self.obstacle_residue.to_wire(current_round)
            if self.obstacle_residue and self.obstacle_residue.until_round >= current_round
            else None,
            "canWindow": self.can_window,
        }


@dataclass
class BuffState:
    buff_type: str
    remaining_round: int
    move_multiplier: float = 1.0
    freshness_multiplier: float = 1.0

    def to_wire(self) -> Dict[str, Any]:
        return {
            "type": self.buff_type,
            "remainingRound": self.remaining_round,
            "moveMultiplier": self.move_multiplier,
            "freshnessMultiplier": self.freshness_multiplier,
        }


@dataclass
class ProcessState:
    action: str
    object_key: str
    target_node_id: str
    started_round: int
    total_round: int
    remain_round: int
    task_id: Optional[str] = None
    resource_type: Optional[str] = None
    process_type: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> Dict[str, Any]:
        done = max(0, self.total_round - self.remain_round)
        progress = 1.0 if self.total_round <= 0 else min(1.0, done / self.total_round)
        return {
            "action": self.action,
            "objectKey": self.object_key,
            "targetNodeId": self.target_node_id,
            "taskId": self.task_id,
            "resourceType": self.resource_type,
            "type": self.process_type or self.action,
            "startedRound": self.started_round,
            "totalRound": self.total_round,
            "remainRound": self.remain_round,
            "remainingRound": self.remain_round,
            "progress": round(progress, 4),
        }


@dataclass
class PlayerState:
    player_id: int
    player_name: str
    camp: int
    team_id: str
    online: bool = True
    state: str = "IDLE"
    current_node_id: str = "S01"
    next_node_id: Optional[str] = None
    route_edge_id: Optional[str] = None
    route_type: Optional[str] = None
    move_direction: str = "NONE"
    move_progress_round: int = 0
    current_edge_cost: int = 0
    edge_progress_ms: int = 0
    edge_total_ms: int = 0
    freshness: float = 100.0
    good_fruit: int = 100
    frozen_good_fruit: int = 0
    bad_fruit: int = 0
    squad_available: int = 8
    squad_in_flight: int = 0
    guard_action_point: int = 4
    verified: bool = False
    delivered: bool = False
    deliver_round: int = 0
    deliver_good_fruit: int = 0
    deliver_freshness: float = 0.0
    retired: bool = False
    retired_round: int = 0
    missing_action_rounds: int = 0
    illegal_action_count: int = 0
    post_deliver_violation_count: int = 0
    break_order_ready: bool = False
    rush_tactic_used_count: int = 0
    buffs: List[BuffState] = field(default_factory=list)
    current_process: Optional[ProcessState] = None
    resources: Dict[str, int] = field(default_factory=dict)
    task_score_raw: int = 0
    bounty_score_raw: int = 0
    fixed_process_done_node_id: Optional[str] = None
    freshness_crossed: set = field(default_factory=set)
    last_forced_pass_node_id: Optional[str] = None
    route_rounds: Dict[str, int] = field(default_factory=lambda: {"ROAD": 0, "WATER": 0, "MOUNTAIN": 0, "BRANCH": 0})
    route_switch_count: int = 0
    last_route_type_for_switch: Optional[str] = None
    route_task_score: Dict[str, int] = field(default_factory=lambda: {"ROAD": 0, "WATER": 0, "MOUNTAIN": 0, "BRANCH": 0})
    route_resource_count: Dict[str, int] = field(default_factory=lambda: {"ROAD": 0, "WATER": 0, "MOUNTAIN": 0, "BRANCH": 0})
    last_freshness_route_type: Optional[str] = None

    def active_buff(self, *types: str) -> Optional[BuffState]:
        wanted = set(types)
        for buff in self.buffs:
            if buff.buff_type in wanted and buff.remaining_round > 0:
                return buff
        return None

    def base_move_amount(self) -> int:
        rush = self.active_buff("RUSH_SPEED")
        if rush:
            return MOVE_SPEED_BY_BUFF["RUSH_SPEED"]
        horse = self.active_buff("FAST_HORSE", "SHORT_HORSE")
        if horse:
            return MOVE_SPEED_BY_BUFF[horse.buff_type]
        return 1000

    def freshness_multiplier(self) -> float:
        multiplier = 1.0
        for buff in self.buffs:
            if buff.remaining_round <= 0:
                continue
            if buff.buff_type == "RUSH_SPEED":
                multiplier *= 1.25
            elif buff.buff_type == "RUSH_PROTECT":
                multiplier *= 0.2
        return multiplier

    def add_buff(self, buff_type: str) -> None:
        self.buffs = [b for b in self.buffs if b.buff_type not in HORSE_BUFFS or buff_type not in HORSE_BUFFS]
        self.buffs = [b for b in self.buffs if b.buff_type != buff_type]
        self.buffs.append(
            BuffState(
                buff_type=buff_type,
                remaining_round=BUFF_DURATION[buff_type],
                move_multiplier=1.0,
                freshness_multiplier=0.2 if buff_type == "RUSH_PROTECT" else 1.25 if buff_type == "RUSH_SPEED" else 1.0,
            )
        )

    def tick_buffs(self) -> None:
        for buff in self.buffs:
            buff.remaining_round -= 1
        self.buffs = [b for b in self.buffs if b.remaining_round > 0]


@dataclass
class TaskState:
    task_id: str
    template: TaskTemplate
    node_id: str
    route_bucket: str
    refresh_round: int
    expire_round: int = 0
    active: bool = True
    completed: bool = False
    failed: bool = False
    failure_reason: str = ""
    owner_player_id: int = 0
    protection_player_id: int = 0

    def to_wire(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "taskTemplateId": self.template.template_id,
            "name": self.template.name,
            "nodeId": self.node_id,
            "routeBucket": self.route_bucket,
            "processType": self.template.process_type,
            "processRound": self.template.process_round,
            "score": self.template.score,
            "refreshRound": self.refresh_round,
            "expireRound": self.expire_round,
            "active": self.active,
            "completed": self.completed,
            "failed": self.failed,
            "failureReason": self.failure_reason,
            "ownerPlayerId": self.owner_player_id,
            "protectionPlayerId": self.protection_player_id,
        }


@dataclass
class BountyState:
    bounty_id: str
    bounty_type: str
    node_id: str
    owner_team_id: str
    trigger_reason: str
    trigger_round: int
    reward_score: int
    reward_resource_type: str = ""
    cooldown_until_round: int = 0
    active: bool = True
    completed: bool = False
    winner_player_id: int = 0

    def to_wire(self) -> Dict[str, Any]:
        return {
            "bountyId": self.bounty_id,
            "bountyType": self.bounty_type,
            "nodeId": self.node_id,
            "ownerTeamId": self.owner_team_id,
            "triggerReason": self.trigger_reason,
            "triggerRound": self.trigger_round,
            "cooldownUntilRound": self.cooldown_until_round,
            "rewardScore": self.reward_score,
            "rewardResourceType": self.reward_resource_type,
            "active": self.active,
            "completed": self.completed,
            "winnerPlayerId": self.winner_player_id,
        }


@dataclass
class ContestState:
    contest_id: str
    contest_type: str
    target_node_id: str
    red_player_id: int
    blue_player_id: int
    initiator_player_id: int
    created_round: int
    object_key: str
    resource_type: Optional[str] = None
    task_id: Optional[str] = None
    source_action_types: Dict[str, str] = field(default_factory=dict)
    source_task_ids: Dict[str, str] = field(default_factory=dict)
    source_rush_tactics: Dict[str, str] = field(default_factory=dict)
    round_index: int = 1
    total_rounds: int = 3
    red_point: int = 0
    blue_point: int = 0
    red_cost_count: int = 0
    blue_cost_count: int = 0
    deadline_round: int = 0
    resolved: bool = False
    winner_team_id: Optional[str] = None
    cards: Dict[str, str] = field(default_factory=dict)
    status: str = "ACTIVE"

    def to_wire(self, current_round: int) -> Dict[str, Any]:
        return {
            "contestId": self.contest_id,
            "contestType": self.contest_type,
            "targetNodeId": self.target_node_id,
            "resourceType": self.resource_type,
            "taskId": self.task_id,
            "redPlayerId": self.red_player_id,
            "bluePlayerId": self.blue_player_id,
            "initiatorPlayerId": self.initiator_player_id,
            "initialTimeTaxRound": 0,
            "initialBlockType": "",
            "initialGuardOwnerTeamId": "",
            "initialGuardCompleteRound": 0,
            "initialGuardTaxRound": 0,
            "initialObstacle": False,
            "initialObstacleType": "",
            "initialObstacleTaxRound": 0,
            "breakOrderCostTypes": {},
            "sourceActionTypes": self.source_action_types,
            "sourceTaskIds": self.source_task_ids,
            "sourceRushTactics": self.source_rush_tactics,
            "roundIndex": self.round_index,
            "totalRounds": self.total_rounds,
            "redPoint": self.red_point,
            "bluePoint": self.blue_point,
            "redCostCount": self.red_cost_count,
            "blueCostCount": self.blue_cost_count,
            "deadlineRound": self.deadline_round or current_round,
            "resolved": self.resolved,
            "winnerTeamId": self.winner_team_id,
            "cards": self.cards,
            "status": self.status,
            "objectKey": self.object_key,
            "suppressUntilRound": 0,
            "remainRound": 0,
        }


@dataclass
class SquadOrder:
    order_id: str
    player_id: int
    action: str
    target_node_id: str
    submit_round: int
    arrival_round: int
    cost: int


@dataclass
class ActionDecision:
    action: str
    accepted: bool
    result: str = "ACCEPTED"
    error_code: Optional[str] = None
    message: str = ""

    def to_result(self, round_no: int, player_id: int) -> Dict[str, Any]:
        data = {
            "round": round_no,
            "playerId": player_id,
            "action": self.action,
            "accepted": self.accepted,
            "result": self.result,
        }
        if self.error_code:
            data["errorCode"] = self.error_code
        if self.message:
            data["message"] = self.message
        return data


def build_default_map() -> Tuple[
    Dict[str, NodeConfig],
    List[EdgeConfig],
    List[ResourceConfig],
    Dict[str, ProcessConfig],
    Dict[str, TaskTemplate],
    Dict[str, Any],
]:
    nodes = {
        "S01": NodeConfig("S01", "101", "岭南果园", "START", 5, 50, "start", start=True),
        "S02": NodeConfig("S02", "102", "南岭驿", "CHECKPOINT", 15, 47, "station"),
        "S03": NodeConfig("S03", "103", "梅关驿", "PASS", 26, 43, "pass"),
        "S04": NodeConfig("S04", "104", "江南码头", "DOCK", 25, 32, "dock"),
        "S05": NodeConfig("S05", "105", "洞庭水驿", "WATER_STATION", 39, 29, "water"),
        "S06": NodeConfig("S06", "106", "五岭山道", "MOUNTAIN_NODE", 22, 55, "mountain"),
        "S07": NodeConfig("S07", "107", "荆襄大驿", "STATION", 43, 42, "station"),
        "S08": NodeConfig("S08", "108", "秦岭栈道", "MOUNTAIN_PASS", 47, 52, "mountain"),
        "S09": NodeConfig("S09", "109", "洛阳驿", "STATION", 56, 38, "station"),
        "S10": NodeConfig("S10", "110", "武关", "KEY_PASS", 62, 33, "key_pass"),
        "S11": NodeConfig("S11", "111", "潼关驿", "PASS", 68, 29, "pass"),
        "S12": NodeConfig("S12", "112", "关中平原", "JUNCTION", 71, 24, "junction"),
        "S13": NodeConfig("S13", "113", "灞桥驿", "PALACE_STATION", 74, 20, "palace"),
        "S14": NodeConfig("S14", "114", "朱雀门", "GATE", 76, 18, "gate"),
        "S15": NodeConfig("S15", "115", "兴庆宫", "FINISH", 78, 18, "finish", terminal=True),
    }

    edges = [
        EdgeConfig("E01", "S01", "S02", "ROAD", 30),
        EdgeConfig("E02", "S02", "S03", "ROAD", 25),
        EdgeConfig("E03", "S03", "S07", "ROAD", 54),
        EdgeConfig("E04", "S07", "S09", "ROAD", 46),
        EdgeConfig("E05", "S09", "S10", "ROAD", 40),
        EdgeConfig("E06", "S10", "S11", "ROAD", 36),
        EdgeConfig("E07", "S11", "S12", "ROAD", 20),
        EdgeConfig("E08", "S12", "S13", "ROAD", 25),
        EdgeConfig("E09", "S13", "S14", "ROAD", 18),
        EdgeConfig("E10", "S14", "S15", "ROAD", 10),
        EdgeConfig("E11", "S02", "S04", "ROAD", 20),
        EdgeConfig("E12", "S04", "S05", "WATER", 44),
        EdgeConfig("E13", "S05", "S07", "BRANCH", 46),
        EdgeConfig("E15", "S01", "S06", "MOUNTAIN", 44),
        EdgeConfig("E16", "S06", "S08", "MOUNTAIN", 54),
        EdgeConfig("E17", "S08", "S10", "BRANCH", 46),
        EdgeConfig("E18", "S03", "S06", "BRANCH", 38),
        EdgeConfig("E19", "S05", "S09", "WATER", 48),
        EdgeConfig("E20", "S07", "S08", "MOUNTAIN", 42),
        EdgeConfig("E21", "S04", "S07", "BRANCH", 54),
        EdgeConfig("E22", "S08", "S09", "BRANCH", 64),
    ]

    process_configs = {
        "S02": ProcessConfig("S02", "TRANSFER", 4),
        "S04": ProcessConfig("S04", "BOARD", 7),
        "S05": ProcessConfig("S05", "WATER_TRANSFER", 6),
        "S11": ProcessConfig("S11", "PASS_TRANSFER", 5),
        "S13": ProcessConfig("S13", "PALACE_TRANSFER", 5),
        "S14": ProcessConfig("S14", "VERIFY", 6),
    }

    resources = [
        ResourceConfig("S03", "ICE_BOX", 1, 2),
        ResourceConfig("S03", "PASS_TOKEN", 1, 2),
        ResourceConfig("S03", "INTEL", 1, 2),
        ResourceConfig("S04", "SHORT_HORSE", 1, 2),
        ResourceConfig("S04", "BOAT_RIGHT", 1, 2),
        ResourceConfig("S04", "INTEL", 1, 2),
        ResourceConfig("S06", "ICE_BOX", 1, 2),
        ResourceConfig("S06", "INTEL", 1, 2),
        ResourceConfig("S08", "SHORT_HORSE", 1, 2),
        ResourceConfig("S08", "PASS_TOKEN", 1, 2),
        ResourceConfig("S08", "INTEL", 1, 2),
        ResourceConfig("S07", "ICE_BOX", 1, 2),
        ResourceConfig("S07", "SHORT_HORSE", 1, 2),
        ResourceConfig("S11", "INTEL", 1, 2),
        ResourceConfig("S09", "FAST_HORSE", 1, 2),
        ResourceConfig("S09", "OFFICIAL_PERMIT", 1, 2),
        ResourceConfig("S10", "INTEL", 1, 2),
        ResourceConfig("S13", "PASS_TOKEN", 1, 2),
        ResourceConfig("S13", "OFFICIAL_PERMIT", 1, 2),
        ResourceConfig("S13", "INTEL", 1, 2),
    ]

    templates = {
        "T01": TaskTemplate("T01", "限时过关", ["S03"], "CHECK_PASS", 3, 0, [], 30),
        "T02": TaskTemplate("T02", "抵驿催运", ["S07", "S10"], "STATION_URGE", 4, 0, [], 30),
        "T04": TaskTemplate("T04", "清障任务", ["S06", "S08"], "CLEAR_OBSTACLE", 6, 0, [], 30),
        "T06": TaskTemplate("T06", "争马换乘", ["S09", "S04", "S06"], "HORSE_TRANSFER", 3, 0, ["FAST_HORSE"], 30),
        "T08": TaskTemplate("T08", "码头争船", ["S04", "S05"], "DOCK_BOAT", 4, 0, [], 30),
        "T11": TaskTemplate("T11", "栈道复核", ["S08", "S10", "S11"], "PLANK_RECHECK", 4, 0, [], 30),
        "T12": TaskTemplate("T12", "官道关验", ["S11", "S13"], "ROAD_VERIFY", 5, 0, [], 15),
        "T13": TaskTemplate("T13", "水陆联运", ["S13", "S09", "S12"], "MULTIMODAL", 5, 0, [], 15),
        "T14": TaskTemplate("T14", "山口急递", ["S10", "S11", "S12"], "MOUNTAIN_EXPRESS", 5, 0, [], 15),
    }

    gameplay = {
        "roles": {
            "startNodeId": "S01",
            "gateNodeId": "S14",
            "terminalNodeIds": ["S15"],
            "safeZoneNodeIds": ["S15"],
            "reverifyNodeId": "S14",
            "rushExcludedNodeIds": ["S11", "S12", "S13"],
        },
        "resources": [r.to_wire() for r in resources],
        "processNodes": [p.to_wire() for p in process_configs.values()],
        "taskCandidates": {tid: t.candidate_node_ids for tid, t in templates.items()},
        "routeTaskBuckets": {
            "ROAD": ["S03", "S07", "S09", "S10", "S11", "S12", "S13"],
            "WATER": ["S04", "S05", "S09"],
            "MOUNTAIN": ["S06", "S08", "S10"],
            "BRANCH": ["S04", "S05", "S07", "S08", "S09", "S10"],
        },
        "obstacleCandidateNodeIds": ["S06", "S08", "S10", "S11"],
    }
    return nodes, edges, resources, process_configs, templates, gameplay


class GameState:
    def __init__(self, duration_round: int, seed: int, match_id: Optional[str] = None):
        self.match_id = match_id or f"match_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.duration_round = duration_round
        self.seed = seed
        self.seed_hash = hashlib.sha256(str(seed).encode("ascii")).hexdigest()[:16]
        self.random = random.Random(seed)
        (
            self.node_configs,
            self.edge_configs,
            self.resource_configs,
            self.process_configs,
            self.task_templates,
            self.gameplay,
        ) = build_default_map()
        self.nodes: Dict[str, NodeState] = self._build_node_state()
        self.edges_by_pair: Dict[Tuple[str, str], EdgeConfig] = {}
        self.neighbors: Dict[str, List[str]] = {node_id: [] for node_id in self.node_configs}
        for edge in self.edge_configs:
            self.edges_by_pair[(edge.from_node, edge.to_node)] = edge
            self.neighbors[edge.from_node].append(edge.to_node)
            if edge.bidirectional:
                self.edges_by_pair[(edge.to_node, edge.from_node)] = edge
                self.neighbors[edge.to_node].append(edge.from_node)

        self.players: Dict[int, PlayerState] = {}
        self.round = START_ROUND
        self.phase = "NORMAL"
        self.events_for_next_inquire: List[Dict[str, Any]] = []
        self.action_results_for_next_inquire: List[Dict[str, Any]] = []
        self.event_counter = 0
        self.contest_counter = 0
        self.order_counter = 0
        self.tasks: Dict[str, TaskState] = {}
        self.bounties: Dict[str, BountyState] = {}
        self.contests: Dict[str, ContestState] = {}
        self.contest_draw_counts: Dict[str, int] = {}
        self.contest_cooldowns: Dict[str, int] = {}
        self.squad_orders: List[SquadOrder] = []
        self.weather_schedule = [
            {"weatherId": "W_01", "type": "HOT", "region": "ALL", "startRound": 100, "durationRound": 60},
            {"weatherId": "W_02", "type": "HEAVY_RAIN", "region": "WATER", "startRound": 220, "durationRound": 60},
            {"weatherId": "W_03", "type": "MOUNTAIN_FOG", "region": "MOUNTAIN", "startRound": 340, "durationRound": 60},
            {"weatherId": "W_04", "type": "HOT", "region": "ALL", "startRound": 460, "durationRound": 60},
        ]
        self.rush_started_emitted = False
        self._create_initial_tasks()

    def _build_node_state(self) -> Dict[str, NodeState]:
        nodes = {node_id: NodeState(config=config) for node_id, config in self.node_configs.items()}
        for process in self.process_configs.values():
            nodes[process.node_id].process_type = process.process_type
            nodes[process.node_id].process_round = process.process_round
            nodes[process.node_id].can_window = process.can_window
        for resource in self.resource_configs:
            nodes[resource.node_id].resource_stock[resource.resource_type] = (
                nodes[resource.node_id].resource_stock.get(resource.resource_type, 0) + resource.count
            )
        nodes["S06"].has_obstacle = True
        nodes["S06"].obstacle_type = "LANDSLIDE"
        nodes["S08"].has_obstacle = True
        nodes["S08"].obstacle_type = "ROCKFALL"
        for node in nodes.values():
            node.guard.max_defense = self.guard_max_defense(node.config.node_id)
        return nodes

    def _create_initial_tasks(self) -> None:
        task_specs = [
            ("T01", "S03"),
            ("T02", "S07"),
            ("T02", "S10"),
            ("T04", "S06"),
            ("T04", "S08"),
            ("T06", "S09"),
            ("T06", "S04"),
            ("T08", "S04"),
            ("T08", "S05"),
            ("T11", "S08"),
            ("T11", "S10"),
            ("T12", "S11"),
            ("T13", "S13"),
            ("T14", "S10"),
        ]
        for index, (template_id, node_id) in enumerate(task_specs, start=1):
            template = self.task_templates[template_id]
            task_id = f"{template_id}_{index:03d}"
            self.tasks[task_id] = TaskState(
                task_id=task_id,
                template=template,
                node_id=node_id,
                route_bucket=self.route_bucket_for_node(node_id),
                refresh_round=1,
                expire_round=0,
            )

    def route_bucket_for_node(self, node_id: str) -> str:
        for bucket, node_ids in self.gameplay["routeTaskBuckets"].items():
            if node_id in node_ids and bucket != "BRANCH":
                return bucket
        return "BRANCH"

    @staticmethod
    def guard_max_defense(node_id: str) -> int:
        if node_id == "S10":
            return 7
        if node_id == "S14":
            return 4
        if node_id in {"S06", "S08", "S11"}:
            return 5
        return 6

    def add_player(self, player_id: int, player_name: str) -> PlayerState:
        camp = len(self.players)
        team_id = TEAM_BY_CAMP[camp]
        player = PlayerState(player_id=player_id, player_name=player_name, camp=camp, team_id=team_id)
        self.players[player_id] = player
        return player

    def start_payload(self) -> Dict[str, Any]:
        nodes = [cfg.to_wire() for cfg in self.node_configs.values()]
        edges = [edge.to_wire() for edge in self.edge_configs]
        resources = [resource.to_wire() for resource in self.resource_configs]
        task_templates = [template.to_wire() for template in self.task_templates.values()]
        map_payload = {
            "schemaVersion": "1.0",
            "mapId": "preliminary_default",
            "mapName": "一骑红尘：荔枝争运战竞技地图",
            "designVersion": "local-default",
            "mapConfigFile": "embedded_default_map",
            "data": "",
            "maxX": 80,
            "maxY": 60,
            "nodes": nodes,
            "edges": edges,
            "routePaths": [],
            "weatherRegionRule": {
                "forecastLeadRound": 30,
                "durationRound": 60,
                "types": ["HOT", "HEAVY_RAIN", "MOUNTAIN_FOG"],
            },
            "layers": [],
            "gameplay": self.gameplay,
        }
        return {
            "matchId": self.match_id,
            "rulesVersion": RULES_VERSION,
            "seedHash": self.seed_hash,
            "round": START_ROUND,
            "tick": 0,
            "durationRound": self.duration_round,
            "map": map_payload,
            "players": [
                {
                    "playerId": player.player_id,
                    "camp": player.camp,
                    "teamId": player.team_id,
                    "name": player.player_name,
                }
                for player in self.players.values()
            ],
            "nodes": nodes,
            "edges": edges,
            "routePaths": [],
            "resources": resources,
            "taskTemplates": task_templates,
        }

    def weather_payload(self) -> Dict[str, Any]:
        active = []
        forecast = []
        for item in self.weather_schedule:
            start = item["startRound"]
            end = start + item["durationRound"] - 1
            if start <= self.round <= end:
                active.append(
                    {
                        "weatherId": item["weatherId"],
                        "type": item["type"],
                        "region": item["region"],
                        "remainRound": end - self.round + 1,
                    }
                )
            elif start - 30 <= self.round < start:
                forecast.append(dict(item))
        return {"active": active, "forecast": forecast}

    def inquire_payload(self) -> Dict[str, Any]:
        return {
            "matchId": self.match_id,
            "rulesVersion": RULES_VERSION,
            "round": self.round,
            "tick": self.round - 1,
            "phase": self.phase,
            "players": [self.player_wire(player) for player in self.players.values()],
            "nodes": [node.to_wire(self.round) for node in self.nodes.values()],
            "edges": [edge.to_wire() for edge in self.edge_configs],
            "weather": self.weather_payload(),
            "tasks": [task.to_wire() for task in self.tasks.values() if task.active or task.completed or task.failed],
            "bounties": [bounty.to_wire() for bounty in self.bounties.values() if bounty.active or bounty.completed],
            "contests": [
                contest.to_wire(self.round)
                for contest in self.contests.values()
                if not contest.resolved and self.round >= contest.created_round + 1
            ],
            "events": list(self.events_for_next_inquire),
            "actionResults": list(self.action_results_for_next_inquire),
            "scorePreview": {player.team_id: self.calculate_score(player)["total"] for player in self.players.values()},
            "debug": {},
        }

    def player_wire(self, player: PlayerState) -> Dict[str, Any]:
        score = self.calculate_score(player)
        progress = 0 if player.edge_total_ms <= 0 else player.edge_progress_ms / player.edge_total_ms
        return {
            "playerId": player.player_id,
            "camp": player.camp,
            "teamId": player.team_id,
            "playerName": player.player_name,
            "online": player.online,
            "state": player.state,
            "currentNodeId": player.current_node_id,
            "nextNodeId": player.next_node_id,
            "routeEdgeId": player.route_edge_id,
            "routeType": player.route_type,
            "moveDirection": player.move_direction,
            "moveProgress": round(progress, 4),
            "moveProgressRound": player.move_progress_round,
            "currentEdgeCost": player.current_edge_cost,
            "edgeProgressPermille": int(progress * 1000),
            "edgeProgressMs": player.edge_progress_ms,
            "edgeTotalMs": player.edge_total_ms,
            "freshness": round(player.freshness, 3),
            "goodFruit": player.good_fruit,
            "frozenGoodFruit": player.frozen_good_fruit,
            "badFruit": player.bad_fruit,
            "squadAvailable": player.squad_available,
            "squadInFlight": player.squad_in_flight,
            "guardActionPoint": player.guard_action_point,
            "verified": player.verified,
            "delivered": player.delivered,
            "retired": player.retired,
            "retiredRound": player.retired_round,
            "missingActionRounds": player.missing_action_rounds,
            "illegalActionCount": player.illegal_action_count,
            "penaltyScore": score["penalty"],
            "breakOrderReady": player.break_order_ready,
            "rushTacticUsedCount": player.rush_tactic_used_count,
            "buffs": [buff.to_wire() for buff in player.buffs],
            "currentProcess": player.current_process.to_wire() if player.current_process else None,
            "resources": dict(player.resources),
            "totalScore": score["total"],
            "taskScore": score["tasks"],
            "bountyScore": score["bounty"],
            "scoreDetail": score,
        }

    def event(self, event_type: str, round_no: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.event_counter += 1
        event = {
            "eventId": f"EV_{round_no:03d}_{self.event_counter:05d}",
            "type": event_type,
            "round": round_no,
            "payload": payload,
        }
        self.events_for_next_inquire.append(event)
        return event

    def reject(
        self,
        player: PlayerState,
        action: str,
        error_code: str,
        message: str,
        illegal: bool = False,
    ) -> ActionDecision:
        if illegal:
            player.illegal_action_count += 1
            event_type = "INVALID_ACTION"
        else:
            event_type = "ACTION_REJECTED"
        self.event(event_type, self.round, {
            "playerId": player.player_id,
            "action": action,
            "errorCode": error_code,
            "message": message,
        })
        return ActionDecision(action=action, accepted=False, result="ACTION_REJECTED", error_code=error_code, message=message)

    def accept(self, action: str, message: str = "ACCEPTED") -> ActionDecision:
        return ActionDecision(action=action, accepted=True, result="ACCEPTED", message=message if message != "ACCEPTED" else "")

    def fixed_process_required(self, player: PlayerState) -> bool:
        node = self.nodes[player.current_node_id]
        if node.process_type and node.process_type != "VERIFY":
            return player.fixed_process_done_node_id != player.current_node_id
        return False

    def edge_between(self, from_node: str, to_node: str) -> Optional[EdgeConfig]:
        return self.edges_by_pair.get((from_node, to_node))

    def route_total_ms(self, edge: EdgeConfig) -> int:
        return math.ceil(edge.distance * ROUTE_COST[edge.route_type])

    def shortest_distance(self, start: str, target: str) -> float:
        if start == target:
            return 0
        unseen = {node_id: math.inf for node_id in self.node_configs}
        unseen[start] = 0
        visited = set()
        while unseen:
            node_id = min((n for n in unseen if n not in visited), key=lambda n: unseen[n], default=None)
            if node_id is None or unseen[node_id] == math.inf:
                return math.inf
            if node_id == target:
                return unseen[node_id]
            visited.add(node_id)
            for neighbor in self.neighbors[node_id]:
                edge = self.edge_between(node_id, neighbor)
                if not edge:
                    continue
                unseen[neighbor] = min(unseen[neighbor], unseen[node_id] + edge.distance)
            if len(visited) == len(self.node_configs):
                return math.inf
        return math.inf

    def move_weather_multiplier(self, route_type: Optional[str]) -> int:
        active = self.weather_payload()["active"]
        for weather in active:
            if weather["type"] == "HEAVY_RAIN" and route_type == "WATER":
                return 1350
            if weather["type"] == "MOUNTAIN_FOG" and route_type == "MOUNTAIN":
                return 1100
        return 1000

    def weather_freshness_multiplier(self, player: PlayerState, route_type: Optional[str]) -> float:
        multiplier = 1.0
        for weather in self.weather_payload()["active"]:
            if weather["type"] == "HOT":
                multiplier *= 1.5
            elif weather["type"] == "HEAVY_RAIN" and route_type == "WATER":
                multiplier *= 1.3
        return multiplier

    def process_weather_extra_rounds(self, node_id: str, process_type: Optional[str]) -> int:
        node = self.nodes[node_id]
        for weather in self.weather_payload()["active"]:
            if weather["type"] == "HEAVY_RAIN" and (
                node.config.node_type in {"DOCK", "WATER_STATION"} or process_type in {"BOARD", "WATER_TRANSFER"}
            ):
                return 4
        return 0

    def process_round_with_modifiers(
        self,
        player: PlayerState,
        node_id: str,
        base_round: int,
        process_type: Optional[str],
        break_order: bool = False,
    ) -> int:
        total = base_round + self.process_weather_extra_rounds(node_id, process_type)
        if break_order and process_type == "VERIFY":
            total = max(3, total - 3)
        else:
            marker = self.consume_scout_marker(player.team_id, node_id)
            if marker:
                total = max(2, total - marker.process_reduce_round)
        return max(1, total)

    def consume_scout_marker(self, team_id: str, node_id: str) -> Optional[ScoutMarker]:
        node = self.nodes[node_id]
        for marker in node.scouted:
            if marker.team_id == team_id and marker.active(self.round):
                marker.remaining_triggers -= 1
                self.event("SCOUT_MARKER_CONSUME", self.round, {
                    "teamId": team_id,
                    "nodeId": node_id,
                    "processReduceRound": marker.process_reduce_round,
                })
                return marker
        return None

    def object_cooldown_until(self, object_key: str) -> int:
        until_round = self.contest_cooldowns.get(object_key, 0)
        if until_round < self.round:
            self.contest_cooldowns.pop(object_key, None)
            self.contest_draw_counts.pop(object_key, None)
            return 0
        return until_round

    def object_on_cooldown(self, object_key: str) -> bool:
        return self.object_cooldown_until(object_key) >= self.round

    def processing_player_for_object(self, object_key: str, exclude_player_id: Optional[int] = None) -> Optional[PlayerState]:
        for player in self.players.values():
            if exclude_player_id is not None and player.player_id == exclude_player_id:
                continue
            proc = player.current_process
            if proc and proc.object_key == object_key and player.state in {"PROCESSING", "VERIFYING", "FORCED_PASSING"}:
                return player
        return None

    def reject_unavailable_object(self, player: PlayerState, action: str, object_key: str) -> Optional[ActionDecision]:
        cooldown_until = self.object_cooldown_until(object_key)
        if cooldown_until:
            return self.reject(
                player,
                action,
                "WINDOW_DRAW_RETRY_LIMIT",
                f"{object_key} is cooling down until round {cooldown_until}",
            )
        busy_player = self.processing_player_for_object(object_key, exclude_player_id=player.player_id)
        if busy_player:
            return self.reject(
                player,
                action,
                "OBJECT_BUSY",
                f"{object_key} is being processed by player {busy_player.player_id}",
            )
        return None

    def clear_contest_history(self, object_key: str) -> None:
        self.contest_draw_counts.pop(object_key, None)
        self.contest_cooldowns.pop(object_key, None)

    def calculate_score(self, player: PlayerState) -> Dict[str, Any]:
        penalty = min(20, max(0, player.illegal_action_count - 5)) + min(30, player.post_deliver_violation_count * 5)
        raw_task = player.task_score_raw
        raw_bounty = player.bounty_score_raw
        if player.delivered:
            delivery = min(240, 120 + math.floor(raw_task * 4 / 3))
            good = math.floor(player.deliver_good_fruit / 100 * 180)
            freshness = math.floor(player.deliver_freshness / 100 * 180)
            raw_time = math.floor((self.duration_round - player.deliver_round) / self.duration_round * 70)
            time_score = math.floor(raw_time * min(raw_task, 90) / 90) if raw_task > 0 else 0
            tasks = min(180, raw_task + self.task_milestone_bonus(raw_task))
            bounty = min(raw_bounty, 80) + 20 if raw_bounty > 0 else 0
        else:
            delivery = 0
            good = 0
            freshness = 0
            time_score = 0
            tasks = min(raw_task, 80)
            bounty = min(raw_bounty, 25)
        total = max(0, delivery + good + freshness + time_score + tasks + bounty - penalty)
        return {
            "delivery": delivery,
            "goodFruit": good,
            "freshness": freshness,
            "time": time_score,
            "tasks": tasks,
            "bounty": bounty,
            "penalty": penalty,
            "total": total,
        }

    @staticmethod
    def task_milestone_bonus(raw_task: int) -> int:
        if raw_task >= 110:
            return 50
        if raw_task >= 90:
            return 35
        if raw_task >= 60:
            return 15
        return 0

    def classify_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        groups = {"main": [], "squad": [], "window": [], "rush": []}
        for action in actions:
            action_type = action.get("action")
            if action_type in MAIN_ACTIONS:
                groups["main"].append(action)
            if action_type in SQUAD_ACTIONS:
                groups["squad"].append(action)
            if action_type in WINDOW_ACTIONS:
                groups["window"].append(action)
            if action_type in RUSH_ACTIONS or action.get("rushTactic") == "BREAK_ORDER":
                groups["rush"].append(action)
        return groups

    def settle_round(
        self,
        action_packets: Dict[int, Optional[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        self.events_for_next_inquire = []
        self.action_results_for_next_inquire = []
        self.update_phase()
        self.resolve_squad_arrivals()

        parsed_actions: Dict[int, List[Dict[str, Any]]] = {}
        first_decisions: Dict[int, ActionDecision] = {}
        contestable: Dict[str, List[Tuple[PlayerState, Dict[str, Any]]]] = {}

        for player in self.players.values():
            player.last_freshness_route_type = None
            if player.retired:
                first_decisions[player.player_id] = self.accept("WAIT", "RETIRED")
                parsed_actions[player.player_id] = []
                continue
            packet = action_packets.get(player.player_id)
            if packet is None:
                parsed_actions[player.player_id] = []
                if not player.delivered:
                    player.missing_action_rounds += 1
                    if player.missing_action_rounds == 10:
                        self.event("DISCONNECT_WARNING", self.round, {"playerId": player.player_id})
                    if player.missing_action_rounds >= 60:
                        player.retired = True
                        player.retired_round = self.round
                        player.state = "RETIRED"
                        self.event("PLAYER_RETIRED", self.round, {"playerId": player.player_id})
                if player.state == "WAITING":
                    player.state = "MOVING"
                    player.move_direction = "FORWARD"
                first_decisions[player.player_id] = self.accept("WAIT", "SYSTEM_WAIT")
                continue

            player.missing_action_rounds = 0
            actions = packet.get("actions", [])
            parsed_actions[player.player_id] = actions
            if not actions:
                if player.state == "WAITING":
                    player.state = "MOVING"
                    player.move_direction = "FORWARD"
                first_decisions[player.player_id] = self.accept("WAIT")
                continue

            groups = self.classify_actions(actions)
            conflict = False
            for group_name, grouped in groups.items():
                if len(grouped) > 1:
                    conflict = True
                    player.illegal_action_count += 1
                    self.event("INVALID_ACTION", self.round, {
                        "playerId": player.player_id,
                        "action": grouped[0].get("action", ""),
                        "errorCode": "INVALID_ACTION_CONFLICT",
                        "message": f"multiple {group_name} actions in one frame",
                    })
            if conflict:
                first_decisions[player.player_id] = ActionDecision(
                    action=actions[0].get("action", "UNKNOWN"),
                    accepted=False,
                    result="ACTION_REJECTED",
                    error_code="INVALID_ACTION_CONFLICT",
                    message="same category action conflict",
                )
                parsed_actions[player.player_id] = []
                continue

            if player.delivered:
                active_actions = [a for a in actions if a.get("action") not in {"WAIT", "DELIVER"}]
                if active_actions:
                    player.post_deliver_violation_count += 1
                    self.event("POST_DELIVER_PENALTY", self.round, {
                        "playerId": player.player_id,
                        "penalty": 5,
                        "actions": actions,
                    })
                    first_decisions[player.player_id] = ActionDecision(
                        action=active_actions[0].get("action", "UNKNOWN"),
                        accepted=False,
                        result="ACTION_REJECTED",
                        error_code="SAFE_ZONE_FORBIDDEN",
                        message="active action after delivery",
                    )
                    parsed_actions[player.player_id] = []
                    continue

            main = groups["main"][0] if groups["main"] else None
            if main:
                object_key = self.contestable_object_key(player, main)
                if object_key:
                    contestable.setdefault(object_key, []).append((player, main))

        blocked_by_contest = set()
        for object_key, attempts in contestable.items():
            cooldown_until = self.object_cooldown_until(object_key)
            if cooldown_until:
                for player, action in attempts:
                    blocked_by_contest.add((player.player_id, id(action)))
                    first_decisions[player.player_id] = self.reject(
                        player,
                        action.get("action", "UNKNOWN"),
                        "WINDOW_DRAW_RETRY_LIMIT",
                        f"{object_key} is cooling down until round {cooldown_until}",
                    )
                continue
            unique_players = {player.player_id for player, _ in attempts}
            if len(unique_players) >= 2:
                self.create_contest(object_key, attempts)
                for player, action in attempts:
                    blocked_by_contest.add((player.player_id, id(action)))
                    first_decisions[player.player_id] = self.accept(action.get("action", "UNKNOWN"), "CONTEST_CREATED")

        card_actions: Dict[int, Dict[str, Any]] = {}
        for player_id, actions in parsed_actions.items():
            for action in actions:
                if action.get("action") == "WINDOW_CARD":
                    card_actions[player_id] = action
        self.process_contest_cards(card_actions)

        for player in self.players.values():
            if player.retired:
                continue
            actions = parsed_actions.get(player.player_id, [])
            decisions: List[ActionDecision] = []
            for action in actions:
                if (player.player_id, id(action)) in blocked_by_contest:
                    decisions.append(self.accept(action.get("action", "UNKNOWN"), "CONTEST_CREATED"))
                    continue
                action_type = action.get("action")
                if action_type == "WINDOW_CARD":
                    decisions.append(self.accept("WINDOW_CARD"))
                elif action_type in SQUAD_ACTIONS:
                    decisions.append(self.handle_squad_action(player, action))
                elif action_type in MAIN_ACTIONS:
                    decisions.append(self.handle_main_action(player, action))
                elif action_type == "BREAK_ORDER":
                    decisions.append(
                        self.reject(
                            player,
                            "BREAK_ORDER",
                            "RUSH_TACTIC_INVALID_BINDING",
                            "BREAK_ORDER cannot be sent alone",
                            illegal=True,
                        )
                    )
                elif action_type:
                    decisions.append(self.reject(player, action_type, "INVALID_ACTION_TYPE", "unknown action", illegal=True))
            if not decisions and not first_decisions.get(player.player_id):
                decisions.append(self.accept("WAIT"))
            if decisions:
                first_decisions[player.player_id] = self.merge_decisions(decisions)

        self.progress_states()
        self.apply_freshness_and_buffs()
        self.update_phase()
        self.check_end_of_guard_weathering()

        for player in self.players.values():
            decision = first_decisions.get(player.player_id) or self.accept("WAIT")
            self.action_results_for_next_inquire.append(decision.to_result(self.round, player.player_id))

        self.round += 1
        return self.events_for_next_inquire, self.action_results_for_next_inquire

    @staticmethod
    def merge_decisions(decisions: List[ActionDecision]) -> ActionDecision:
        if not decisions:
            return ActionDecision("WAIT", True)
        for decision in decisions:
            if not decision.accepted:
                return decision
        return decisions[0]

    def contestable_object_key(self, player: PlayerState, action: Dict[str, Any]) -> Optional[str]:
        action_type = action.get("action")
        if player.state not in {"IDLE"}:
            return None
        if action_type == "CLAIM_RESOURCE":
            target = action.get("targetNodeId")
            resource = action.get("resourceType")
            return f"RESOURCE:{target}:{resource}" if target and resource else None
        if action_type == "CLAIM_TASK":
            task_id = action.get("taskId")
            return f"TASK:{task_id}" if task_id else None
        if action_type in {"PROCESS", "DOCK"}:
            target = action.get("targetNodeId") or player.current_node_id
            node = self.nodes.get(target)
            if node and node.process_type and node.process_type != "VERIFY":
                return f"PROCESS:{target}:{node.process_type}"
        if action_type == "VERIFY_GATE":
            if self.phase != "RUSH" or player.verified:
                return None
            return f"GATE:{player.current_node_id}" if player.current_node_id == "S14" else None
        if action_type == "CLEAR":
            target = action.get("targetNodeId")
            return f"OBSTACLE:{target}" if target else None
        return None

    def create_contest(self, object_key: str, attempts: List[Tuple[PlayerState, Dict[str, Any]]]) -> None:
        by_team = {player.team_id: (player, action) for player, action in attempts}
        if "RED" not in by_team or "BLUE" not in by_team:
            return
        red_player, red_action = by_team["RED"]
        blue_player, blue_action = by_team["BLUE"]
        self.contest_counter += 1
        parts = object_key.split(":")
        contest_type = {
            "RESOURCE": "RESOURCE",
            "TASK": "TASK",
            "PROCESS": "DOCK",
            "GATE": "GATE",
            "OBSTACLE": "OBSTACLE",
        }.get(parts[0], "TASK")
        target_node = ""
        resource_type = None
        task_id = None
        if parts[0] == "RESOURCE":
            target_node = parts[1]
            resource_type = parts[2]
        elif parts[0] == "TASK":
            task_id = parts[1]
            task = self.tasks.get(task_id)
            target_node = task.node_id if task else ""
        else:
            target_node = parts[1] if len(parts) > 1 else ""
        contest = ContestState(
            contest_id=f"C_{self.contest_counter:04d}",
            contest_type=contest_type,
            target_node_id=target_node,
            resource_type=resource_type,
            task_id=task_id,
            red_player_id=red_player.player_id,
            blue_player_id=blue_player.player_id,
            initiator_player_id=red_player.player_id,
            created_round=self.round,
            object_key=object_key,
            deadline_round=self.round + 1,
            source_action_types={
                str(red_player.player_id): red_action.get("action", ""),
                str(blue_player.player_id): blue_action.get("action", ""),
            },
            source_task_ids={
                str(red_player.player_id): red_action.get("taskId", ""),
                str(blue_player.player_id): blue_action.get("taskId", ""),
            },
            source_rush_tactics={
                str(red_player.player_id): red_action.get("rushTactic", ""),
                str(blue_player.player_id): blue_action.get("rushTactic", ""),
            },
        )
        self.contests[contest.contest_id] = contest
        red_player.state = "CONTESTING"
        blue_player.state = "CONTESTING"
        self.event("WINDOW_CONTEST_START", self.round, {
            "contestId": contest.contest_id,
            "contestType": contest.contest_type,
            "targetNodeId": contest.target_node_id,
            "resourceType": contest.resource_type,
            "taskId": contest.task_id,
            "objectKey": object_key,
        })

    def process_contest_cards(self, card_actions: Dict[int, Dict[str, Any]]) -> None:
        for contest in list(self.contests.values()):
            if contest.resolved or self.round <= contest.created_round:
                continue
            if self.round > contest.created_round + contest.total_rounds:
                continue
            red = self.players.get(contest.red_player_id)
            blue = self.players.get(contest.blue_player_id)
            if not red or not blue:
                continue
            red_card = self.effective_card(red, card_actions.get(red.player_id), contest)
            blue_card = self.effective_card(blue, card_actions.get(blue.player_id), contest)
            contest.cards[f"R{contest.round_index}:RED"] = red_card
            contest.cards[f"R{contest.round_index}:BLUE"] = blue_card
            result = self.compare_cards(red_card, blue_card)
            if result > 0:
                contest.red_point += 1
            elif result < 0:
                contest.blue_point += 1
            self.event("WINDOW_CARD_REVEAL", self.round, {
                "contestId": contest.contest_id,
                "roundIndex": contest.round_index,
                "redCard": red_card,
                "blueCard": blue_card,
                "redPoint": contest.red_point,
                "bluePoint": contest.blue_point,
            })
            if contest.round_index >= contest.total_rounds:
                self.resolve_contest(contest)
            else:
                contest.round_index += 1
                contest.deadline_round = self.round + 1

    def effective_card(self, player: PlayerState, action: Optional[Dict[str, Any]], contest: ContestState) -> str:
        if not action or action.get("contestId") != contest.contest_id:
            return "ABSTAIN"
        card = action.get("card", "ABSTAIN")
        if card not in WINDOW_CARDS:
            player.illegal_action_count += 1
            self.event("INVALID_ACTION", self.round, {
                "playerId": player.player_id,
                "action": "WINDOW_CARD",
                "contestId": contest.contest_id,
                "errorCode": "INVALID_ACTION_TYPE",
                "message": "unknown window card",
            })
            return "ABSTAIN"
        if card == "YAN_DIE":
            if player.resources.get("PASS_TOKEN", 0) > 0:
                player.resources["PASS_TOKEN"] -= 1
            elif player.resources.get("OFFICIAL_PERMIT", 0) > 0:
                player.resources["OFFICIAL_PERMIT"] -= 1
            else:
                return "ABSTAIN"
        elif card == "QIANG_XING":
            if player.active_buff("FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"):
                pass
            elif player.resources.get("FAST_HORSE", 0) > 0:
                player.resources["FAST_HORSE"] -= 1
            elif player.resources.get("SHORT_HORSE", 0) > 0:
                player.resources["SHORT_HORSE"] -= 1
            else:
                return "ABSTAIN"
        elif card == "XIAN_GONG":
            if player.freshness < 80 or player.good_fruit <= 0:
                return "ABSTAIN"
            player.good_fruit -= 1
        elif card == "BING_ZHENG":
            if player.guard_action_point <= 0:
                return "ABSTAIN"
            player.guard_action_point -= 1
        return card

    @staticmethod
    def compare_cards(red_card: str, blue_card: str) -> int:
        if red_card == "ABSTAIN" and blue_card == "ABSTAIN":
            return 0
        if red_card != "ABSTAIN" and blue_card == "ABSTAIN":
            return 1
        if red_card == "ABSTAIN" and blue_card != "ABSTAIN":
            return -1
        if red_card == blue_card:
            return 0
        return CARD_WIN_TABLE.get((red_card, blue_card), 0)

    def resolve_contest(self, contest: ContestState) -> None:
        contest.resolved = True
        red = self.players[contest.red_player_id]
        blue = self.players[contest.blue_player_id]
        if contest.red_point > contest.blue_point:
            winner = red
            loser = blue
            contest.winner_team_id = "RED"
        elif contest.blue_point > contest.red_point:
            winner = blue
            loser = red
            contest.winner_team_id = "BLUE"
        else:
            winner = None
            loser = None
            contest.winner_team_id = "DRAW"
        self.event("WINDOW_CONTEST_END", self.round, {
            "contestId": contest.contest_id,
            "winnerTeamId": contest.winner_team_id,
            "redPoint": contest.red_point,
            "bluePoint": contest.blue_point,
        })
        if winner is None:
            red.state = "RESTING"
            blue.state = "RESTING"
            red.current_process = ProcessState("REST", f"REST:{contest.contest_id}:RED", red.current_node_id, self.round, 3, 3)
            blue.current_process = ProcessState("REST", f"REST:{contest.contest_id}:BLUE", blue.current_node_id, self.round, 3, 3)
            draw_count = self.contest_draw_counts.get(contest.object_key, 0) + 1
            self.contest_draw_counts[contest.object_key] = draw_count
            self.event("WINDOW_CONTEST_DRAW", self.round, {
                "contestId": contest.contest_id,
                "objectKey": contest.object_key,
                "drawCount": draw_count,
            })
            if draw_count >= 2:
                cooldown = 6 if contest.contest_type == "GATE" else 18
                suppress_until = self.round + cooldown
                self.contest_cooldowns[contest.object_key] = suppress_until
                self.event("WINDOW_CONTEST_REPEAT_SUPPRESSED", self.round, {
                    "contestId": contest.contest_id,
                    "objectKey": contest.object_key,
                    "contestType": contest.contest_type,
                    "suppressUntilRound": suppress_until,
                    "cooldownRound": cooldown,
                })
            return
        self.clear_contest_history(contest.object_key)
        winner.state = "IDLE"
        loser.state = "IDLE"
        source_action = contest.source_action_types.get(str(winner.player_id), "")
        synthetic = {"action": source_action}
        if contest.resource_type:
            synthetic.update({"targetNodeId": contest.target_node_id, "resourceType": contest.resource_type})
        if contest.task_id:
            synthetic["taskId"] = contest.task_id
        rush_tactic = contest.source_rush_tactics.get(str(winner.player_id), "")
        if rush_tactic:
            synthetic["rushTactic"] = rush_tactic
        self.event(f"{contest.contest_type}_CONTEST_WIN", self.round, {
            "contestId": contest.contest_id,
            "playerId": winner.player_id,
            "targetNodeId": contest.target_node_id,
            "taskId": contest.task_id,
            "resourceType": contest.resource_type,
        })
        self.handle_main_action(winner, synthetic)

    def handle_squad_action(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        action_type = action["action"]
        target = action.get("targetNodeId")
        if player.current_node_id == "S15" and not player.delivered:
            return self.reject(player, action_type, "SAFE_ZONE_FORBIDDEN", "S15 forbids squad actions before delivery")
        if self.phase == "RUSH":
            return self.reject(player, action_type, "SAFE_ZONE_FORBIDDEN", "new squad actions are forbidden in RUSH")
        if not target or target not in self.nodes:
            return self.reject(player, action_type, "TARGET_NOT_FOUND", "missing or unknown target", illegal=not target)
        cost = {"SQUAD_SCOUT": 1, "SQUAD_CLEAR": 2, "SQUAD_REINFORCE": 2, "SQUAD_WEAKEN": 2}[action_type]
        if player.squad_available < cost:
            return self.reject(player, action_type, "RESOURCE_NOT_ENOUGH", "not enough squad members")
        delay = self.squad_delay(player, target, action_type)
        self.order_counter += 1
        order = SquadOrder(
            order_id=f"SQ_{self.order_counter:04d}",
            player_id=player.player_id,
            action=action_type,
            target_node_id=target,
            submit_round=self.round,
            arrival_round=self.round + delay,
            cost=cost,
        )
        player.squad_available -= cost
        player.squad_in_flight += cost
        self.squad_orders.append(order)
        self.event("SQUAD_DISPATCH", self.round, {
            "orderId": order.order_id,
            "playerId": player.player_id,
            "action": action_type,
            "targetNodeId": target,
            "arrivalRound": order.arrival_round,
            "cost": cost,
        })
        return self.accept(action_type)

    def squad_delay(self, player: PlayerState, target_node_id: str, action_type: str) -> int:
        start_node = self.node_configs[player.current_node_id]
        target = self.node_configs[target_node_id]
        distance = max(abs(start_node.x - target.x), abs(start_node.y - target.y))
        delay = min(15, max(3, math.ceil(distance / 3)))
        if action_type == "SQUAD_SCOUT":
            for weather in self.weather_payload()["active"]:
                if weather["type"] == "MOUNTAIN_FOG" and target.node_type in {"MOUNTAIN_NODE", "MOUNTAIN_PASS", "KEY_PASS"}:
                    delay = min(15, delay + 2)
        return delay

    def resolve_squad_arrivals(self) -> None:
        priority = {"SQUAD_REINFORCE": 0, "SQUAD_WEAKEN": 1, "SQUAD_CLEAR": 2, "SQUAD_SCOUT": 3}
        arrivals = [order for order in self.squad_orders if order.arrival_round <= self.round]
        self.squad_orders = [order for order in self.squad_orders if order.arrival_round > self.round]
        for order in sorted(arrivals, key=lambda item: priority[item.action]):
            player = self.players.get(order.player_id)
            if not player:
                continue
            player.squad_in_flight = max(0, player.squad_in_flight - order.cost)
            node = self.nodes.get(order.target_node_id)
            if not node:
                self.event("SQUAD_FAILED", self.round, {
                    "orderId": order.order_id,
                    "playerId": order.player_id,
                    "action": order.action,
                    "targetNodeId": order.target_node_id,
                })
                continue
            if order.action == "SQUAD_SCOUT":
                node.scouted.append(ScoutMarker(player.team_id, self.round))
                self.event("SQUAD_SCOUT", self.round, {
                    "orderId": order.order_id,
                    "playerId": player.player_id,
                    "targetNodeId": order.target_node_id,
                    "hasObstacle": node.has_obstacle,
                    "resourceStock": dict(node.resource_stock),
                    "guard": node.guard.to_wire(self.round),
                })
                self.event("SCOUT_MARKER_ADD", self.round, {
                    "playerId": player.player_id,
                    "teamId": player.team_id,
                    "targetNodeId": order.target_node_id,
                    "expireRound": self.round + 45,
                })
            elif order.action == "SQUAD_CLEAR" and node.has_obstacle:
                self.clear_obstacle(node, player, residue=True)
                self.event("SQUAD_CLEAR", self.round, {
                    "orderId": order.order_id,
                    "playerId": player.player_id,
                    "targetNodeId": order.target_node_id,
                })
            elif order.action == "SQUAD_REINFORCE" and node.guard.active and node.guard.owner_team_id == player.team_id:
                before = node.guard.defense
                node.guard.defense = min(node.guard.max_defense, node.guard.defense + 2)
                self.event("SQUAD_REINFORCE", self.round, {
                    "orderId": order.order_id,
                    "playerId": player.player_id,
                    "targetNodeId": order.target_node_id,
                    "before": before,
                    "after": node.guard.defense,
                })
            elif order.action == "SQUAD_WEAKEN" and node.guard.active and node.guard.owner_team_id != player.team_id:
                before = node.guard.defense
                node.guard.defense = max(0, node.guard.defense - 2)
                if node.guard.defense == 0:
                    node.guard.owner_team_id = None
                self.event("SQUAD_WEAKEN", self.round, {
                    "orderId": order.order_id,
                    "playerId": player.player_id,
                    "targetNodeId": order.target_node_id,
                    "before": before,
                    "after": node.guard.defense,
                })
            else:
                self.event("SQUAD_FAILED", self.round, {
                    "orderId": order.order_id,
                    "playerId": player.player_id,
                    "action": order.action,
                    "targetNodeId": order.target_node_id,
                })

    def handle_main_action(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        action_type = action["action"]
        if action_type == "BREAK_ORDER":
            return self.reject(player, action_type, "RUSH_TACTIC_INVALID_BINDING", "BREAK_ORDER cannot be sent alone", illegal=True)
        if player.state == "COST_BANKRUPT":
            player.state = "IDLE"
        if player.retired:
            return self.reject(player, action_type, "ACTION_REJECTED", "player retired")
        if player.state in {"PROCESSING", "VERIFYING", "FORCED_PASSING"}:
            return self.accept(action_type, "PROCESS_CONTINUES")
        if player.state == "RESTING" and action_type != "WAIT":
            return self.reject(player, action_type, "RESTING_ACTION_FORBIDDEN", "resting")
        if player.state == "CONTESTING" and action_type not in {"WAIT"}:
            return self.reject(player, action_type, "ACTION_REJECTED", "contest in progress")
        if player.current_node_id == "S15" and not player.delivered:
            if action_type == "WAIT":
                pass
            elif action_type == "MOVE" and action.get("targetNodeId") == "S14":
                pass
            elif action_type == "DELIVER":
                pass
            else:
                return self.reject(player, action_type, "SAFE_ZONE_FORBIDDEN", "S15 only allows WAIT, DELIVER, or MOVE back to S14 before delivery")

        handlers = {
            "WAIT": self.action_wait,
            "MOVE": self.action_move,
            "DELIVER": self.action_deliver,
            "VERIFY_GATE": self.action_verify_gate,
            "SET_GUARD": self.action_set_guard,
            "BREAK_GUARD": self.action_break_guard,
            "FORCED_PASS": self.action_forced_pass,
            "CLAIM_RESOURCE": self.action_claim_resource,
            "USE_RESOURCE": self.action_use_resource,
            "CLAIM_TASK": self.action_claim_task,
            "CLEAR": self.action_clear,
            "PROCESS": self.action_process,
            "DOCK": self.action_process,
            "RUSH_SPEED": self.action_rush_speed,
            "RUSH_PROTECT": self.action_rush_protect,
        }
        return handlers[action_type](player, action)

    def action_wait(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        if player.state in {"MOVING", "WAITING"}:
            player.state = "WAITING"
            player.move_direction = "PAUSED"
        self.event("WAIT", self.round, {"playerId": player.player_id})
        return self.accept("WAIT")

    def action_move(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        if not target:
            return self.reject(player, "MOVE", "MOVE_MISSING_TARGET", "MOVE requires targetNodeId", illegal=True)
        if target not in self.nodes:
            return self.reject(player, "MOVE", "TARGET_NOT_FOUND", "target node not found", illegal=True)
        if player.state in {"MOVING", "WAITING"}:
            if target == player.next_node_id:
                player.state = "MOVING"
                player.move_direction = "FORWARD"
                return self.accept("MOVE")
            edge = self.edge_between(player.current_node_id, target)
            if edge and target != player.current_node_id:
                return self.start_move(player, target, edge)
            return self.reject(player, "MOVE", "TARGET_NOT_REACHABLE", "moving player can only continue or reroute from origin", illegal=True)
        if player.state != "IDLE":
            return self.reject(player, "MOVE", "MOVING_ACTION_FORBIDDEN", f"state {player.state} cannot move")
        if self.fixed_process_required(player):
            return self.reject(player, "MOVE", "PROCESS_REQUIRED", "fixed process at current node is not complete")
        if player.current_node_id == "S15" and target == "S14":
            edge = self.edge_between("S15", "S14")
            return self.start_move(player, target, edge) if edge else self.reject(player, "MOVE", "MOVE_EDGE_NOT_FOUND", "no edge")
        if target == "S15" and not player.verified:
            return self.reject(player, "MOVE", "VERIFY_REQUIRED", "gate verification required before entering S15")
        edge = self.edge_between(player.current_node_id, target)
        if not edge:
            return self.reject(player, "MOVE", "MOVE_EDGE_NOT_FOUND", "no public edge", illegal=True)
        target_node = self.nodes[target]
        if target_node.guard.active and target_node.guard.owner_team_id != player.team_id:
            return self.reject(player, "MOVE", "MOVE_BLOCKED_BY_GUARD", "target blocked by enemy guard")
        if target_node.has_obstacle:
            return self.reject(player, "MOVE", "TARGET_NOT_REACHABLE", "target blocked by obstacle")
        return self.start_move(player, target, edge)

    def start_move(self, player: PlayerState, target: str, edge: EdgeConfig) -> ActionDecision:
        if player.route_type and edge.route_type != player.route_type:
            player.route_switch_count += 1
        player.state = "MOVING"
        player.next_node_id = target
        player.route_edge_id = edge.edge_id
        player.route_type = edge.route_type
        player.move_direction = "FORWARD"
        player.current_edge_cost = ROUTE_COST[edge.route_type]
        player.edge_total_ms = self.route_total_ms(edge)
        residue = self.nodes[target].obstacle_residue
        if residue and residue.until_round >= self.round and residue.cleared_by_team_id != player.team_id:
            player.edge_total_ms += residue.tax_round * 1000
            self.event("OBSTACLE_RESIDUAL_TAX", self.round, {
                "playerId": player.player_id,
                "nodeId": target,
                "taxRound": residue.tax_round,
            })
        player.edge_progress_ms = 0
        player.move_progress_round = 0
        player.fixed_process_done_node_id = None
        self.event("MOVE_PROGRESS", self.round, {
            "playerId": player.player_id,
            "fromNodeId": player.current_node_id,
            "toNodeId": target,
            "routeEdgeId": edge.edge_id,
            "routeType": edge.route_type,
            "edgeProgressMs": 0,
            "edgeTotalMs": player.edge_total_ms,
            "progress": 0,
        })
        return self.accept("MOVE")

    def action_process(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId") or player.current_node_id
        if target != player.current_node_id:
            return self.reject(player, action["action"], "NOT_AT_TARGET_NODE", "process target must be current node")
        node = self.nodes[player.current_node_id]
        if not node.process_type or node.process_type == "VERIFY":
            return self.reject(player, action["action"], "PROCESS_NOT_AVAILABLE", "no fixed process at current node")
        if action["action"] == "DOCK" and node.process_type != "BOARD":
            return self.reject(player, "DOCK", "PROCESS_NOT_AVAILABLE", "DOCK only works for BOARD process")
        object_key = f"PROCESS:{node.config.node_id}:{node.process_type}"
        unavailable = self.reject_unavailable_object(player, action["action"], object_key)
        if unavailable:
            return unavailable
        total = self.process_round_with_modifiers(player, node.config.node_id, node.process_round, node.process_type)
        player.state = "PROCESSING"
        player.current_process = ProcessState(
            action="PROCESS",
            object_key=object_key,
            target_node_id=node.config.node_id,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type=node.process_type,
        )
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "nodeId": node.config.node_id,
            "processType": node.process_type,
            "remainRound": total,
        })
        return self.accept(action["action"])

    def action_claim_resource(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        resource_type = action.get("resourceType")
        if not target or not resource_type:
            return self.reject(player, "CLAIM_RESOURCE", "RESOURCE_NOT_ENOUGH", "targetNodeId and resourceType are required")
        if target != player.current_node_id:
            return self.reject(player, "CLAIM_RESOURCE", "NOT_AT_TARGET_NODE", "resource target must be current node")
        node = self.nodes.get(target)
        if not node or node.resource_stock.get(resource_type, 0) <= 0:
            return self.reject(player, "CLAIM_RESOURCE", "RESOURCE_NOT_ENOUGH", "resource stock not enough")
        claim_round = next(
            (r.claim_round for r in self.resource_configs if r.node_id == target and r.resource_type == resource_type),
            2,
        )
        total = self.process_round_with_modifiers(player, target, claim_round, "CLAIM_RESOURCE")
        player.state = "PROCESSING"
        player.current_process = ProcessState(
            action="CLAIM_RESOURCE",
            object_key=f"RESOURCE:{target}:{resource_type}",
            target_node_id=target,
            resource_type=resource_type,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type="CLAIM_RESOURCE",
        )
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "action": "CLAIM_RESOURCE",
            "nodeId": target,
            "resourceType": resource_type,
            "remainRound": total,
        })
        return self.accept("CLAIM_RESOURCE")

    def action_use_resource(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        resource_type = action.get("resourceType")
        target = action.get("targetNodeId")
        if not resource_type:
            return self.reject(player, "USE_RESOURCE", "RESOURCE_NOT_ENOUGH", "resourceType is required")
        if player.resources.get(resource_type, 0) <= 0:
            return self.reject(player, "USE_RESOURCE", "RESOURCE_NOT_ENOUGH", "resource not in inventory")
        if resource_type == "ICE_BOX":
            if player.state not in {"IDLE"}:
                return self.reject(player, "USE_RESOURCE", "MOVING_ACTION_FORBIDDEN", "ICE_BOX can only be used while stopped")
            if player.freshness <= 0:
                return self.reject(player, "USE_RESOURCE", "RESOURCE_NOT_USABLE", "freshness is zero")
            player.resources[resource_type] -= 1
            player.freshness = min(100.0, player.freshness + 10)
        elif resource_type in HORSE_BUFFS:
            if player.active_buff("RUSH_SPEED"):
                return self.reject(player, "USE_RESOURCE", "HORSE_BUFF_CONFLICT", "horse buff conflicts with RUSH_SPEED")
            player.resources[resource_type] -= 1
            player.add_buff(resource_type)
        elif resource_type == "INTEL":
            if player.state != "IDLE":
                return self.reject(player, "USE_RESOURCE", "MOVING_ACTION_FORBIDDEN", "INTEL can only be used while stopped")
            if not target or target not in self.nodes:
                return self.reject(player, "USE_RESOURCE", "TARGET_NOT_FOUND", "INTEL requires valid targetNodeId")
            if self.shortest_distance(player.current_node_id, target) > 15:
                return self.reject(player, "USE_RESOURCE", "TARGET_NOT_REACHABLE", "INTEL target too far")
            player.resources[resource_type] -= 1
            self.nodes[target].scouted.append(ScoutMarker(player.team_id, self.round))
            self.event("SCOUT_MARKER_ADD", self.round, {
                "playerId": player.player_id,
                "teamId": player.team_id,
                "targetNodeId": target,
                "expireRound": self.round + 45,
            })
        elif resource_type in {"PASS_TOKEN", "OFFICIAL_PERMIT"}:
            player.resources[resource_type] -= 1
        else:
            return self.reject(player, "USE_RESOURCE", "RESOURCE_NOT_USABLE", f"{resource_type} is not actively usable")
        self.event("RESOURCE_USE", self.round, {
            "playerId": player.player_id,
            "resourceType": resource_type,
            "targetNodeId": target,
        })
        return self.accept("USE_RESOURCE")

    def action_claim_task(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        task_id = action.get("taskId")
        if not task_id:
            return self.reject(player, "CLAIM_TASK", "TASK_NOT_FOUND", "taskId is required", illegal=True)
        task = self.tasks.get(task_id)
        if not task or not task.active or task.completed or task.failed:
            return self.reject(player, "CLAIM_TASK", "TASK_NOT_FOUND", "task not available")
        if task.expire_round and self.round > task.expire_round:
            task.active = False
            task.failed = True
            task.failure_reason = "EXPIRED"
            return self.reject(player, "CLAIM_TASK", "TASK_EXPIRED", "task expired")
        if task.template.template_id == "T04":
            if player.current_node_id != task.node_id and task.node_id not in self.neighbors[player.current_node_id]:
                return self.reject(player, "CLAIM_TASK", "NOT_AT_TARGET_NODE", "T04 requires target or adjacent node")
            if not self.nodes[task.node_id].has_obstacle:
                task.active = False
                task.failed = True
                task.failure_reason = "OBSTACLE_NOT_FOUND"
                return self.reject(player, "CLAIM_TASK", "OBSTACLE_NOT_FOUND", "T04 obstacle not found")
        elif player.current_node_id != task.node_id:
            return self.reject(player, "CLAIM_TASK", "NOT_AT_TARGET_NODE", "task target must be current node")
        object_key = f"TASK:{task.task_id}"
        unavailable = self.reject_unavailable_object(player, "CLAIM_TASK", object_key)
        if unavailable:
            return unavailable
        if task.template.template_id == "T06":
            if player.resources.get("FAST_HORSE", 0) > 0:
                player.resources["FAST_HORSE"] -= 1
            elif player.resources.get("SHORT_HORSE", 0) > 0:
                player.resources["SHORT_HORSE"] -= 1
            else:
                return self.reject(player, "CLAIM_TASK", "TASK_REQUIREMENT_NOT_MET", "T06 requires horse resource")
        total = self.process_round_with_modifiers(player, task.node_id, task.template.process_round, task.template.process_type)
        player.state = "PROCESSING"
        player.current_process = ProcessState(
            action="CLAIM_TASK",
            object_key=object_key,
            target_node_id=task.node_id,
            task_id=task.task_id,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type=task.template.process_type,
        )
        task.owner_player_id = player.player_id
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "action": "CLAIM_TASK",
            "taskId": task.task_id,
            "nodeId": task.node_id,
            "remainRound": total,
        })
        return self.accept("CLAIM_TASK")

    def action_clear(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        if not target or target not in self.nodes:
            return self.reject(player, "CLEAR", "TARGET_NOT_FOUND", "CLEAR requires valid target", illegal=not target)
        if target != player.current_node_id and target not in self.neighbors[player.current_node_id]:
            return self.reject(player, "CLEAR", "TARGET_NOT_REACHABLE", "target must be current or adjacent", illegal=True)
        node = self.nodes[target]
        if not node.has_obstacle:
            return self.reject(player, "CLEAR", "OBSTACLE_NOT_FOUND", "target has no obstacle")
        object_key = f"OBSTACLE:{target}"
        unavailable = self.reject_unavailable_object(player, "CLEAR", object_key)
        if unavailable:
            return unavailable
        if player.good_fruit <= 0:
            return self.reject(player, "CLEAR", "RESOURCE_NOT_ENOUGH", "CLEAR requires 1 good fruit")
        player.good_fruit -= 1
        player.frozen_good_fruit += 1
        total = self.process_round_with_modifiers(player, target, 6, "CLEAR_OBSTACLE")
        player.state = "PROCESSING"
        player.current_process = ProcessState(
            action="CLEAR",
            object_key=object_key,
            target_node_id=target,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type="CLEAR_OBSTACLE",
            extra={"frozenGoodFruit": 1},
        )
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "action": "CLEAR",
            "nodeId": target,
            "remainRound": total,
        })
        return self.accept("CLEAR")

    def action_verify_gate(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        if self.phase != "RUSH":
            return self.reject(player, "VERIFY_GATE", "VERIFY_REQUIRED", "VERIFY_GATE is only available in RUSH", illegal=True)
        target = action.get("targetNodeId") or player.current_node_id
        if target != "S14" or player.current_node_id != "S14":
            return self.reject(player, "VERIFY_GATE", "NOT_AT_TARGET_NODE", "must be at S14")
        if player.verified:
            self.event("VERIFY_GATE_ALREADY_DONE", self.round, {"playerId": player.player_id, "nodeId": "S14"})
            return self.reject(player, "VERIFY_GATE", "ALREADY_VERIFIED", "already verified")
        unavailable = self.reject_unavailable_object(player, "VERIFY_GATE", "GATE:S14")
        if unavailable:
            return unavailable
        break_order = action.get("rushTactic") == "BREAK_ORDER"
        if break_order and not self.consume_break_order_cost(player):
            break_order = False
        total = self.process_round_with_modifiers(player, "S14", 6, "VERIFY", break_order=break_order)
        player.state = "VERIFYING"
        player.current_process = ProcessState(
            action="VERIFY_GATE",
            object_key="GATE:S14",
            target_node_id="S14",
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type="VERIFY",
            extra={"breakOrder": break_order},
        )
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "action": "VERIFY_GATE",
            "nodeId": "S14",
            "remainRound": total,
            "rushTactic": "BREAK_ORDER" if break_order else None,
        })
        return self.accept("VERIFY_GATE")

    def action_deliver(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        if player.delivered:
            return self.accept("DELIVER", "ALREADY_DELIVERED")
        if player.current_node_id != "S15" or player.state != "IDLE":
            return self.reject(player, "DELIVER", "DELIVER_NOT_AT_TERMINAL", "must be idle at S15")
        if not player.verified:
            return self.reject(player, "DELIVER", "DELIVER_NOT_VERIFIED", "gate verification required")
        if player.good_fruit <= 0 or player.freshness <= 0:
            return self.reject(player, "DELIVER", "DELIVER_REQUIREMENT_NOT_MET", "good fruit and freshness must be positive")
        player.delivered = True
        player.state = "DELIVERED"
        player.deliver_round = self.round
        player.deliver_good_fruit = player.good_fruit
        player.deliver_freshness = player.freshness
        self.event("DELIVER_SUCCESS", self.round, {
            "playerId": player.player_id,
            "nodeId": "S15",
            "goodFruit": player.good_fruit,
            "freshness": round(player.freshness, 3),
        })
        return self.accept("DELIVER")

    def action_set_guard(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        extra = int(action.get("extraGoodFruit", 0) or 0)
        if target != player.current_node_id:
            return self.reject(player, "SET_GUARD", "NOT_AT_TARGET_NODE", "guard target must be current node")
        if target == "S15":
            return self.reject(player, "SET_GUARD", "SAFE_ZONE_FORBIDDEN", "S15 cannot be guarded")
        if extra < 0 or extra > 2:
            return self.reject(player, "SET_GUARD", "PARAM_OUT_OF_RANGE", "extraGoodFruit must be 0..2", illegal=True)
        node = self.nodes[target]
        if node.guard.active:
            return self.reject(player, "SET_GUARD", "OBJECT_BUSY", "node already has active guard")
        base_cost = 1 if target in {"S10", "S14"} else 0
        if player.good_fruit < base_cost + extra:
            return self.reject(player, "SET_GUARD", "RESOURCE_NOT_ENOUGH", "not enough good fruit")
        player.good_fruit -= base_cost + extra
        total = 4
        player.state = "PROCESSING"
        player.current_process = ProcessState(
            action="SET_GUARD",
            object_key=f"GUARD:{target}",
            target_node_id=target,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type="SET_GUARD",
            extra={"extraGoodFruit": extra, "baseCost": base_cost},
        )
        self.event("PROCESS_PROGRESS", self.round, {
            "playerId": player.player_id,
            "action": "SET_GUARD",
            "nodeId": target,
            "remainRound": total,
        })
        return self.accept("SET_GUARD")

    def action_break_guard(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        good = int(action.get("goodFruit", 0) or 0)
        bad = int(action.get("badFruit", 0) or 0)
        if not target or target not in self.nodes:
            return self.reject(player, "BREAK_GUARD", "TARGET_NOT_FOUND", "target required", illegal=not target)
        if target == player.current_node_id or target not in self.neighbors[player.current_node_id]:
            return self.reject(player, "BREAK_GUARD", "TARGET_NOT_REACHABLE", "target must be adjacent", illegal=True)
        if good < 0 or good > 2 or bad < 0 or bad > 2:
            return self.reject(player, "BREAK_GUARD", "PARAM_OUT_OF_RANGE", "goodFruit/badFruit must be 0..2", illegal=True)
        if player.good_fruit < good or player.bad_fruit < bad:
            return self.reject(player, "BREAK_GUARD", "RESOURCE_NOT_ENOUGH", "not enough fruit")
        node = self.nodes[target]
        if not node.guard.active or node.guard.owner_team_id == player.team_id:
            return self.reject(player, "BREAK_GUARD", "TARGET_NOT_FOUND", "enemy active guard not found")
        break_bonus = 0
        if action.get("rushTactic") == "BREAK_ORDER" and self.consume_break_order_cost(player):
            break_bonus = 3
        player.good_fruit -= good
        player.bad_fruit -= bad
        attack = good * 2 + bad * 3 + break_bonus
        before = node.guard.defense
        if attack >= node.guard.defense:
            node.guard.defense = 0
            owner = node.guard.owner_team_id
            node.guard.owner_team_id = None
            self.event("GUARD_BREAK", self.round, {
                "playerId": player.player_id,
                "nodeId": target,
                "before": before,
                "after": 0,
                "attack": attack,
            })
            self.try_claim_bounty(player, target, owner)
        else:
            node.guard.defense -= attack
            player.state = "RESTING"
            player.current_process = ProcessState("REST", f"REST:BREAK:{target}", player.current_node_id, self.round, 5, 5)
            node.guard.guard_block_count += 1
            self.event("GUARD_BREAK", self.round, {
                "playerId": player.player_id,
                "nodeId": target,
                "before": before,
                "after": node.guard.defense,
                "attack": attack,
                "success": False,
            })
        return self.accept("BREAK_GUARD")

    def action_forced_pass(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        target = action.get("targetNodeId")
        if not target or target not in self.nodes:
            return self.reject(player, "FORCED_PASS", "TARGET_NOT_FOUND", "target required", illegal=not target)
        if target == player.last_forced_pass_node_id:
            return self.reject(player, "FORCED_PASS", "FORCED_PASS_REPEAT", "cannot repeat forced pass at same node")
        edge = self.edge_between(player.current_node_id, target)
        if not edge:
            return self.reject(player, "FORCED_PASS", "TARGET_NOT_REACHABLE", "target must be adjacent", illegal=True)
        node = self.nodes[target]
        has_enemy_guard = node.guard.active and node.guard.owner_team_id != player.team_id
        if not has_enemy_guard and not node.has_obstacle:
            return self.reject(player, "FORCED_PASS", "ACTION_REJECTED", "target has no blocking object")
        tax = 0
        if node.has_obstacle:
            tax = max(tax, 8)
        if has_enemy_guard:
            tax = max(tax, self.guard_time_tax(target, node.guard.defense))
        move_rounds = math.ceil(self.route_total_ms(edge) / player.base_move_amount())
        total = move_rounds + tax
        player.state = "FORCED_PASSING"
        player.current_process = ProcessState(
            action="FORCED_PASS",
            object_key=f"PASS:{target}",
            target_node_id=target,
            started_round=self.round,
            total_round=total,
            remain_round=total,
            process_type="FORCED_PASS",
            extra={"edgeId": edge.edge_id, "routeType": edge.route_type},
        )
        self.event("FORCED_PASS_START", self.round, {
            "playerId": player.player_id,
            "targetNodeId": target,
            "routeEdgeId": edge.edge_id,
            "timeTax": tax,
            "totalRound": total,
        })
        return self.accept("FORCED_PASS")

    def guard_time_tax(self, node_id: str, defense: int) -> int:
        if node_id == "S10":
            return min(50, 15 + defense * 5)
        if node_id == "S14":
            return min(32, 12 + defense * 5)
        if self.nodes[node_id].has_obstacle:
            return min(28, 8 + defense * 5)
        return min(40, 10 + defense * 5)

    def action_rush_speed(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        if self.phase != "RUSH" or player.rush_tactic_used_count > 0:
            return self.reject(player, "RUSH_SPEED", "RUSH_TACTIC_INVALID_BINDING", "RUSH_SPEED unavailable", illegal=True)
        if player.active_buff("FAST_HORSE", "SHORT_HORSE"):
            return self.reject(player, "RUSH_SPEED", "HORSE_BUFF_CONFLICT", "horse buff conflict")
        if player.good_fruit < 2:
            return self.reject(player, "RUSH_SPEED", "RESOURCE_NOT_ENOUGH", "RUSH_SPEED costs 2 good fruit")
        player.good_fruit -= 2
        player.rush_tactic_used_count += 1
        player.add_buff("RUSH_SPEED")
        self.event("RUSH_TACTIC_USE", self.round, {
            "playerId": player.player_id,
            "rushTactic": "RUSH_SPEED",
        })
        return self.accept("RUSH_SPEED")

    def action_rush_protect(self, player: PlayerState, action: Dict[str, Any]) -> ActionDecision:
        if self.phase != "RUSH" or player.rush_tactic_used_count > 0:
            return self.reject(player, "RUSH_PROTECT", "RUSH_TACTIC_INVALID_BINDING", "RUSH_PROTECT unavailable", illegal=True)
        if player.state != "IDLE":
            return self.reject(player, "RUSH_PROTECT", "MOVING_ACTION_FORBIDDEN", "must be idle at node")
        player.rush_tactic_used_count += 1
        player.add_buff("RUSH_PROTECT")
        self.event("RUSH_TACTIC_USE", self.round, {
            "playerId": player.player_id,
            "rushTactic": "RUSH_PROTECT",
        })
        return self.accept("RUSH_PROTECT")

    def consume_break_order_cost(self, player: PlayerState) -> bool:
        if self.phase != "RUSH" or player.rush_tactic_used_count > 0:
            player.illegal_action_count += 1
            self.event("INVALID_ACTION", self.round, {
                "playerId": player.player_id,
                "action": "BREAK_ORDER",
                "errorCode": "RUSH_TACTIC_INVALID_BINDING",
            })
            return False
        if player.bad_fruit >= 2:
            player.bad_fruit -= 2
            cost_type = "BAD_FRUIT"
        elif player.good_fruit >= 1:
            player.good_fruit -= 1
            cost_type = "GOOD_FRUIT"
        else:
            return False
        player.rush_tactic_used_count += 1
        self.event("BREAK_ORDER_BIND", self.round, {
            "playerId": player.player_id,
            "costType": cost_type,
        })
        return True

    def progress_states(self) -> None:
        for player in self.players.values():
            if player.retired or player.delivered:
                continue
            if player.state == "MOVING":
                self.progress_move(player)
            elif player.state == "WAITING":
                self.event("WAIT", self.round, {"playerId": player.player_id, "moveDirection": "PAUSED"})
            elif player.state in {"PROCESSING", "VERIFYING", "FORCED_PASSING", "RESTING"} and player.current_process:
                self.progress_process(player)

    def progress_move(self, player: PlayerState) -> None:
        route_type = player.route_type
        weather_multiplier = self.move_weather_multiplier(route_type)
        amount = math.floor(player.base_move_amount() * 1000 / weather_multiplier)
        player.edge_progress_ms += amount
        player.move_progress_round += 1
        player.last_freshness_route_type = route_type
        if route_type in player.route_rounds:
            player.route_rounds[route_type] += 1
        if player.edge_progress_ms >= player.edge_total_ms:
            arrived = player.next_node_id
            previous = player.current_node_id
            player.current_node_id = arrived or player.current_node_id
            player.next_node_id = None
            player.route_edge_id = None
            player.route_type = None
            player.move_direction = "NONE"
            player.edge_progress_ms = 0
            player.edge_total_ms = 0
            player.move_progress_round = 0
            player.current_edge_cost = 0
            player.state = "IDLE"
            player.fixed_process_done_node_id = None
            self.event("NODE_ENTER", self.round, {
                "playerId": player.player_id,
                "fromNodeId": previous,
                "nodeId": player.current_node_id,
            })
        else:
            progress = player.edge_progress_ms / player.edge_total_ms if player.edge_total_ms else 0
            self.event("MOVE_PROGRESS", self.round, {
                "playerId": player.player_id,
                "fromNodeId": player.current_node_id,
                "toNodeId": player.next_node_id,
                "routeEdgeId": player.route_edge_id,
                "routeType": route_type,
                "progress": round(progress, 4),
                "edgeProgressMs": player.edge_progress_ms,
                "edgeTotalMs": player.edge_total_ms,
            })

    def progress_process(self, player: PlayerState) -> None:
        proc = player.current_process
        if not proc:
            return
        proc.remain_round -= 1
        if proc.remain_round > 0:
            self.event("PROCESS_PROGRESS", self.round, {
                "playerId": player.player_id,
                "action": proc.action,
                "objectKey": proc.object_key,
                "targetNodeId": proc.target_node_id,
                "remainRound": proc.remain_round,
            })
            return
        self.complete_process(player, proc)

    def complete_process(self, player: PlayerState, proc: ProcessState) -> None:
        player.current_process = None
        player.state = "IDLE"
        self.event("PROCESS_COMPLETE", self.round, {
            "playerId": player.player_id,
            "action": proc.action,
            "objectKey": proc.object_key,
            "targetNodeId": proc.target_node_id,
        })
        if proc.action in {"PROCESS", "CLAIM_RESOURCE", "CLAIM_TASK", "CLEAR", "VERIFY_GATE"}:
            self.clear_contest_history(proc.object_key)
        if proc.action == "PROCESS":
            player.fixed_process_done_node_id = proc.target_node_id
        elif proc.action == "CLAIM_RESOURCE":
            node = self.nodes[proc.target_node_id]
            if proc.resource_type and node.resource_stock.get(proc.resource_type, 0) > 0:
                node.resource_stock[proc.resource_type] -= 1
                player.resources[proc.resource_type] = player.resources.get(proc.resource_type, 0) + 1
                bucket = self.route_bucket_for_node(proc.target_node_id)
                player.route_resource_count[bucket] = player.route_resource_count.get(bucket, 0) + 1
                self.event("RESOURCE_CLAIM", self.round, {
                    "playerId": player.player_id,
                    "nodeId": proc.target_node_id,
                    "resourceType": proc.resource_type,
                })
            else:
                self.event("ACTION_REJECTED", self.round, {
                    "playerId": player.player_id,
                    "action": proc.action,
                    "errorCode": "RESOURCE_NOT_ENOUGH",
                    "message": "resource missing at completion",
                })
        elif proc.action == "CLAIM_TASK" and proc.task_id:
            task = self.tasks.get(proc.task_id)
            if task and task.active and not task.completed:
                if task.template.template_id == "T04" and not self.nodes[task.node_id].has_obstacle:
                    task.active = False
                    task.failed = True
                    task.failure_reason = "OBSTACLE_NOT_FOUND"
                    self.event("TASK_TARGET_LOST", self.round, {
                        "playerId": player.player_id,
                        "taskId": task.task_id,
                        "nodeId": task.node_id,
                    })
                else:
                    task.completed = True
                    task.active = False
                    task.owner_player_id = player.player_id
                    player.task_score_raw += task.template.score
                    player.route_task_score[task.route_bucket] = player.route_task_score.get(task.route_bucket, 0) + task.template.score
                    if task.template.template_id == "T04":
                        self.clear_obstacle(self.nodes[task.node_id], player, residue=False)
                    self.event("TASK_COMPLETE", self.round, {
                        "playerId": player.player_id,
                        "taskId": task.task_id,
                        "taskTemplateId": task.template.template_id,
                        "nodeId": task.node_id,
                        "score": task.template.score,
                    })
        elif proc.action == "CLEAR":
            if player.frozen_good_fruit > 0:
                player.frozen_good_fruit -= 1
            node = self.nodes[proc.target_node_id]
            if node.has_obstacle:
                self.clear_obstacle(node, player, residue=True)
            else:
                self.event("ACTION_REJECTED", self.round, {
                    "playerId": player.player_id,
                    "action": proc.action,
                    "errorCode": "OBSTACLE_NOT_FOUND",
                    "message": "obstacle missing at completion",
                })
        elif proc.action == "VERIFY_GATE":
            player.verified = True
            self.event("VERIFY_GATE_COMPLETE", self.round, {
                "playerId": player.player_id,
                "nodeId": proc.target_node_id,
            })
        elif proc.action == "SET_GUARD":
            node = self.nodes[proc.target_node_id]
            extra = int(proc.extra.get("extraGoodFruit", 0))
            defense = min(node.guard.max_defense, 2 + extra * 2)
            node.guard.owner_team_id = player.team_id
            node.guard.defense = defense
            node.guard.initial_defense = defense
            node.guard.complete_round = self.round
            self.enforce_guard_limit(player.team_id)
            self.event("GUARD_SET", self.round, {
                "playerId": player.player_id,
                "nodeId": proc.target_node_id,
                "ownerTeamId": player.team_id,
                "defense": defense,
                "maxDefense": node.guard.max_defense,
            })
        elif proc.action == "FORCED_PASS":
            target = proc.target_node_id
            previous = player.current_node_id
            player.current_node_id = target
            player.fixed_process_done_node_id = None
            player.last_forced_pass_node_id = target
            self.event("FORCED_PASS_END", self.round, {
                "playerId": player.player_id,
                "fromNodeId": previous,
                "nodeId": target,
            })
        elif proc.action == "REST":
            player.state = "IDLE"

    def clear_obstacle(self, node: NodeState, player: PlayerState, residue: bool) -> None:
        node.has_obstacle = False
        node.obstacle_type = None
        if residue:
            node.obstacle_residue = ObstacleResidue(
                cleared_by_player_id=player.player_id,
                cleared_by_team_id=player.team_id,
                clear_round=self.round,
                until_round=self.round + 30,
            )
        self.event("OBSTACLE_CLEAR", self.round, {
            "playerId": player.player_id,
            "nodeId": node.config.node_id,
            "residue": residue,
        })

    def enforce_guard_limit(self, team_id: str) -> None:
        owned = [
            node
            for node in self.nodes.values()
            if node.guard.active and node.guard.owner_team_id == team_id
        ]
        owned.sort(key=lambda n: n.guard.complete_round)
        while len(owned) > 2:
            old = owned.pop(0)
            old.guard.owner_team_id = None
            old.guard.defense = 0
            self.event("GUARD_WEATHERING", self.round, {
                "nodeId": old.config.node_id,
                "ownerTeamId": team_id,
                "reason": "GUARD_LIMIT",
            })

    def try_claim_bounty(self, player: PlayerState, target: str, owner_team: Optional[str]) -> None:
        bounty = next((b for b in self.bounties.values() if b.node_id == target and b.active), None)
        if not bounty:
            return
        owner_player = next((p for p in self.players.values() if p.team_id == owner_team), None)
        if owner_player and self.calculate_score(player)["total"] >= self.calculate_score(owner_player)["total"]:
            return
        bounty.active = False
        bounty.completed = True
        bounty.winner_player_id = player.player_id
        player.bounty_score_raw += bounty.reward_score
        self.event("BOUNTY_CLAIM", self.round, {
            "playerId": player.player_id,
            "bountyId": bounty.bounty_id,
            "nodeId": target,
            "rewardScore": bounty.reward_score,
        })

    def maybe_create_bounty(self, node: NodeState) -> None:
        if not node.guard.active:
            return
        if any(b.node_id == node.config.node_id and b.active for b in self.bounties.values()):
            return
        age = self.round - node.guard.complete_round
        if age not in {30, 60} and node.guard.guard_block_count < 2 and node.guard.key_pass_combat_count < 3:
            return
        bounty_type = "KEY_BOUNTY" if node.config.node_type == "KEY_PASS" else "NORMAL_BOUNTY"
        reward = 18 if bounty_type == "KEY_BOUNTY" else 10
        bounty_id = f"B_{node.config.node_id}_{len(self.bounties) + 1:03d}"
        self.bounties[bounty_id] = BountyState(
            bounty_id=bounty_id,
            bounty_type=bounty_type,
            node_id=node.config.node_id,
            owner_team_id=node.guard.owner_team_id or "",
            trigger_reason="GUARD_STANDING",
            trigger_round=self.round,
            reward_score=reward,
        )
        self.event("BOUNTY_CREATE", self.round, {
            "bountyId": bounty_id,
            "bountyType": bounty_type,
            "nodeId": node.config.node_id,
            "rewardScore": reward,
        })

    def check_end_of_guard_weathering(self) -> None:
        for node in self.nodes.values():
            guard = node.guard
            if not guard.active or guard.complete_round >= self.round:
                continue
            age = self.round - guard.complete_round
            first_weather = 45 if node.config.node_type == "KEY_PASS" and guard.initial_defense >= 4 else 30
            should_weather = age == first_weather or (age > first_weather and (age - first_weather) % 30 == 0)
            if should_weather:
                before = guard.defense
                guard.defense = max(0, guard.defense - 1)
                self.event("GUARD_WEATHERING", self.round, {
                    "nodeId": node.config.node_id,
                    "ownerTeamId": guard.owner_team_id,
                    "before": before,
                    "after": guard.defense,
                })
                if guard.defense == 0:
                    guard.owner_team_id = None
            self.maybe_create_bounty(node)

    def apply_freshness_and_buffs(self) -> None:
        for player in self.players.values():
            if player.retired or player.delivered:
                continue
            route_type = player.last_freshness_route_type
            base = ROUTE_FRESHNESS_DROP.get(route_type, IDLE_FRESHNESS_DROP)
            drop = base * self.weather_freshness_multiplier(player, route_type) * player.freshness_multiplier()
            before = player.freshness
            player.freshness = max(0.0, min(100.0, player.freshness - drop))
            if abs(before - player.freshness) > 1e-9:
                self.event("FRESHNESS_DROP", self.round, {
                    "playerId": player.player_id,
                    "before": round(before, 3),
                    "after": round(player.freshness, 3),
                    "drop": round(drop, 4),
                })
            for threshold in FRESHNESS_THRESHOLDS:
                if threshold not in player.freshness_crossed and before >= threshold and player.freshness < threshold:
                    player.freshness_crossed.add(threshold)
                    if player.good_fruit > 0:
                        player.good_fruit -= 1
                        player.bad_fruit += 1
                        self.event("GOOD_TO_BAD", self.round, {
                            "playerId": player.player_id,
                            "threshold": threshold,
                            "goodFruit": player.good_fruit,
                            "badFruit": player.bad_fruit,
                        })
                    elif player.frozen_good_fruit > 0:
                        player.frozen_good_fruit -= 1
                        player.bad_fruit += 1
                        player.state = "COST_BANKRUPT"
                        player.current_process = None
                        self.event("COST_BANKRUPT", self.round, {
                            "playerId": player.player_id,
                            "threshold": threshold,
                        })
            if player.good_fruit + player.frozen_good_fruit <= 0:
                player.freshness = 0
            if player.freshness <= 0 and player.good_fruit + player.frozen_good_fruit > 0:
                scrapped = player.good_fruit + player.frozen_good_fruit
                player.good_fruit = 0
                player.frozen_good_fruit = 0
                player.current_process = None
                if player.state in {"PROCESSING", "VERIFYING"}:
                    player.state = "COST_BANKRUPT"
                self.event("GOOD_FRUIT_SCRAP", self.round, {
                    "playerId": player.player_id,
                    "scrapped": scrapped,
                })
            player.tick_buffs()

    def update_phase(self) -> None:
        if self.phase == "RUSH":
            return
        should_rush = self.round >= 450
        if not should_rush and self.round >= 390:
            for player in self.players.values():
                if player.current_node_id == "S14":
                    should_rush = True
                elif player.current_node_id not in {"S11", "S12", "S13"} and self.shortest_distance(player.current_node_id, "S14") <= 15:
                    should_rush = True
        if should_rush:
            self.phase = "RUSH"
            if not self.rush_started_emitted:
                self.rush_started_emitted = True
                self.event("RUSH_START", self.round, {"phase": "RUSH"})

    def is_over(self) -> bool:
        if self.round > self.duration_round:
            return True
        active = [p for p in self.players.values() if not p.retired]
        if len(active) <= 1 and len(self.players) >= 2:
            return True
        return len(self.players) >= 2 and all(p.delivered or p.retired for p in self.players.values())

    def over_payload(self) -> Dict[str, Any]:
        scores = {player.player_id: self.calculate_score(player)["total"] for player in self.players.values()}
        retired = [p for p in self.players.values() if p.retired and not p.delivered]
        if len(retired) == 1:
            result_type = "FORFEIT"
            winner = next((p for p in self.players.values() if not p.retired), None)
            winner_id = winner.player_id if winner else None
            reason = "PLAYER_RETIRED"
        else:
            result_type = "NORMAL"
            reason = "ALL_DELIVERED" if all(p.delivered for p in self.players.values()) else "ROUND_LIMIT"
            if scores:
                max_score = max(scores.values())
                winners = [pid for pid, score in scores.items() if score == max_score]
                winner_id = winners[0] if len(winners) == 1 else None
                if winner_id is None:
                    result_type = "DRAW"
            else:
                winner_id = None
        return {
            "matchId": self.match_id,
            "overRound": min(self.round - 1, self.duration_round),
            "resultType": result_type,
            "overReason": reason,
            "winnerPlayerId": winner_id,
            "players": [self.over_player_wire(player) for player in self.players.values()],
        }

    def over_player_wire(self, player: PlayerState) -> Dict[str, Any]:
        score = self.calculate_score(player)
        return {
            "playerId": player.player_id,
            "playerName": player.player_name,
            "camp": player.camp,
            "teamId": player.team_id,
            "delivered": player.delivered,
            "deliverRound": player.deliver_round,
            "retired": player.retired,
            "retiredRound": player.retired_round,
            "goodFruit": player.deliver_good_fruit if player.delivered else player.good_fruit,
            "badFruit": player.bad_fruit,
            "freshness": round(player.deliver_freshness if player.delivered else player.freshness, 3),
            "taskScore": score["tasks"],
            "bountyScore": score["bounty"],
            "penaltyScore": score["penalty"],
            "totalScore": score["total"],
            "totalGold": score["total"],
            "scoreDetail": score,
            "roadRounds": player.route_rounds.get("ROAD", 0),
            "waterRounds": player.route_rounds.get("WATER", 0),
            "mountainRounds": player.route_rounds.get("MOUNTAIN", 0),
            "branchRounds": player.route_rounds.get("BRANCH", 0),
            "routeSwitchCount": player.route_switch_count,
            "routeTaskScore": json.dumps(player.route_task_score, ensure_ascii=False),
            "routeResourceCount": json.dumps(player.route_resource_count, ensure_ascii=False),
            "illegalActionCount": player.illegal_action_count,
            "missingActionRounds": player.missing_action_rounds,
        }


@dataclass
class ClientSession:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    address: str
    player_id: Optional[int] = None
    player_name: str = ""
    ready: bool = False

    def label(self) -> str:
        return f"P{self.player_id}" if self.player_id is not None else self.address


class MatchServer:
    def __init__(
        self,
        host: str,
        port: int,
        tick_ms: int,
        duration_round: int,
        seed: int,
        log_dir: Path,
        verbose: bool,
        allowed_player_ids: Optional[Iterable[int]] = None,
    ):
        self.host = host
        self.port = port
        self.tick_ms = tick_ms
        self.game = GameState(duration_round=duration_round, seed=seed)
        self.logger = setup_logging(log_dir, verbose)
        self.audit = AuditLogger(log_dir, self.game.match_id)
        self.replay = ReplayLogger(log_dir, self.game.match_id)
        self.allowed_player_ids = set(allowed_player_ids or DEFAULT_ALLOWED_PLAYER_IDS)
        self.sessions: Dict[int, ClientSession] = {}
        self.server: Optional[asyncio.AbstractServer] = None
        self.registration_done = asyncio.Event()
        self.ready_done = asyncio.Event()
        self.action_event = asyncio.Event()
        self.pending_actions: Dict[int, Dict[str, Any]] = {}
        self.received_rounds: set[Tuple[int, int]] = set()
        self.started = False
        self.ended = False

    async def run(self) -> None:
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in (self.server.sockets or []))
        self.logger.info("server listening on %s", sockets)
        self.logger.info("matchId=%s audit=%s replay=%s", self.game.match_id, self.audit.path, self.replay.path)
        async with self.server:
            game_task = asyncio.create_task(self.game_loop(), name="game_loop")
            try:
                await self.server.serve_forever()
            except asyncio.CancelledError:
                pass
            finally:
                game_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await game_task
                self.close()

    def close(self) -> None:
        self.audit.close()
        self.replay.close()
        close_logger_handlers(self.logger)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        session = ClientSession(reader=reader, writer=writer, address=str(peer))
        self.logger.info("client connected address=%s", session.address)
        await self.audit.write("client_connected", address=session.address)
        try:
            while not self.ended:
                try:
                    msg = await read_message(reader)
                except asyncio.IncompleteReadError:
                    break
                except ProtocolError as exc:
                    await self.send_error(session, 0, 0, exc.error_code, exc.message)
                    continue
                await self.audit.write(
                    "message_in",
                    matchId=self.game.match_id,
                    playerId=session.player_id,
                    address=session.address,
                    message=msg,
                )
                await self.handle_message(session, msg)
        finally:
            if session.player_id in self.sessions:
                player = self.game.players.get(session.player_id)
                if player:
                    player.online = False
                self.sessions.pop(session.player_id, None)
            self.logger.info("client disconnected label=%s", session.label())
            await self.audit.write("client_disconnected", playerId=session.player_id, address=session.address)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def handle_message(self, session: ClientSession, msg: Dict[str, Any]) -> None:
        msg_name = msg.get("msg_name")
        msg_data = msg.get("msg_data")
        if not isinstance(msg_name, str) or not isinstance(msg_data, dict):
            await self.send_error(session, 0, 0, "INVALID_JSON", "message requires msg_name and msg_data")
            return
        if msg_name == "registration":
            await self.handle_registration(session, msg_data)
        elif msg_name == "ready":
            await self.handle_ready(session, msg_data)
        elif msg_name == "action":
            await self.handle_action(session, msg_data)
        else:
            player_id = parse_wire_int(msg_data.get("playerId")) or 0
            await self.send_error(session, 0, player_id, "ACTION_REJECTED", "unknown msg_name")

    async def handle_registration(self, session: ClientSession, data: Dict[str, Any]) -> None:
        if self.started:
            await self.send_error(session, 0, 0, "MATCH_ALREADY_STARTED", "match already started")
            return
        if len(self.game.players) >= 2:
            await self.send_error(session, 0, 0, "PLAYER_LIMIT_EXCEEDED", "player limit exceeded")
            return
        player_id = parse_wire_int(data.get("playerId"))
        if player_id is None:
            await self.send_error(session, 0, 0, "PLAYER_NOT_ALLOWED", "registration requires integer playerId")
            return
        if self.allowed_player_ids and player_id not in self.allowed_player_ids:
            await self.send_error(session, 0, player_id, "PLAYER_NOT_ALLOWED", "playerId is not allowed in this match")
            return
        player_name = str(data.get("playerName", f"player-{player_id}"))
        if player_id in self.game.players:
            await self.send_error(session, 0, player_id, "PLAYER_ADDRESS_MISMATCH", "playerId already registered")
            return
        player = self.game.add_player(player_id, player_name)
        session.player_id = player_id
        session.player_name = player_name
        self.sessions[player_id] = session
        self.logger.info("registered playerId=%s team=%s name=%s version=%s", player_id, player.team_id, player_name, data.get("version"))
        await self.audit.write(
            "registration",
            matchId=self.game.match_id,
            playerId=player_id,
            playerName=player_name,
            teamId=player.team_id,
            version=data.get("version"),
        )
        if len(self.game.players) == 2:
            self.registration_done.set()

    async def handle_ready(self, session: ClientSession, data: Dict[str, Any]) -> None:
        player_id = parse_wire_int(data.get("playerId"))
        round_no = parse_wire_int(data.get("round"))
        if player_id is None or round_no is None:
            await self.send_error(session, round_no or 0, player_id or 0, "INVALID_JSON", "ready requires integer playerId and round")
            return
        if session.player_id != player_id:
            await self.send_error(session, self.game.round, player_id, "PLAYER_ADDRESS_MISMATCH", "ready playerId does not match connection")
            return
        if data.get("matchId") != self.game.match_id:
            await self.send_error(session, round_no, player_id, "MATCH_ID_MISMATCH", "matchId mismatch.")
            return
        if round_no != START_ROUND:
            await self.send_error(session, round_no, player_id, "ACTION_TOO_LATE", "ready round must be 1")
            return
        session.ready = True
        self.logger.info("ready playerId=%s", player_id)
        await self.audit.write("ready", matchId=self.game.match_id, playerId=player_id, message=data)
        if len(self.sessions) == 2 and all(s.ready for s in self.sessions.values()):
            self.ready_done.set()

    async def handle_action(self, session: ClientSession, data: Dict[str, Any]) -> None:
        player_id = parse_wire_int(data.get("playerId"))
        round_no = parse_wire_int(data.get("round"))
        if player_id is None or round_no is None:
            await self.send_error(session, round_no or 0, player_id or 0, "INVALID_JSON", "action requires integer playerId and round")
            return
        if session.player_id != player_id:
            await self.send_error(session, round_no, player_id, "PLAYER_ADDRESS_MISMATCH", "action playerId does not match connection")
            return
        if data.get("matchId") != self.game.match_id:
            await self.send_error(session, round_no, player_id, "MATCH_ID_MISMATCH", "matchId mismatch.")
            return
        if round_no != self.game.round:
            await self.send_error(session, round_no, player_id, "ACTION_TOO_LATE", "round is not current.")
            return
        if (player_id, round_no) in self.received_rounds:
            await self.send_error(session, round_no, player_id, "DUPLICATE_ACTION", "duplicate action for this round.")
            return
        actions = data.get("actions")
        if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
            await self.send_error(session, round_no, player_id, "INVALID_JSON", "actions must be an array of objects")
            return
        for action in actions:
            action_type = action.get("action")
            if not isinstance(action_type, str) or action_type not in ALL_ACTIONS:
                await self.send_error(session, round_no, player_id, "INVALID_ACTION_TYPE", "Unknown action.")
                return
        self.received_rounds.add((player_id, round_no))
        self.pending_actions[player_id] = data
        self.logger.debug("action received round=%s playerId=%s actions=%s", round_no, player_id, actions)
        await self.audit.write(
            "action_received",
            matchId=self.game.match_id,
            round=round_no,
            playerId=player_id,
            actions=actions,
        )
        if len(self.pending_actions) >= len(self.game.players):
            self.action_event.set()

    async def send_message(self, session: ClientSession, msg_name: str, data: Dict[str, Any]) -> None:
        payload = pack_message(msg_name, data)
        session.writer.write(payload)
        await session.writer.drain()
        await self.audit.write(
            "message_out",
            matchId=self.game.match_id,
            round=data.get("round") or data.get("overRound"),
            playerId=session.player_id,
            msg_name=msg_name,
            message={"msg_name": msg_name, "msg_data": data},
        )

    async def broadcast(self, msg_name: str, data: Dict[str, Any], record_replay: bool = True) -> None:
        if record_replay:
            await self.replay.write_message(msg_name, data)
        for session in list(self.sessions.values()):
            await self.send_message(session, msg_name, data)

    async def send_error(self, session: ClientSession, round_no: int, player_id: int, error_code: str, message: str) -> None:
        data = {"round": round_no, "playerId": player_id, "errorCode": error_code, "message": message}
        self.logger.warning("error to %s round=%s code=%s message=%s", session.label(), round_no, error_code, message)
        await self.replay.write_message("error", data)
        await self.send_message(session, "error", data)
        await self.audit.write(
            "protocol_error",
            matchId=self.game.match_id,
            round=round_no,
            playerId=player_id,
            errorCode=error_code,
            message=message,
        )

    async def game_loop(self) -> None:
        await self.registration_done.wait()
        self.started = True
        start = self.game.start_payload()
        self.logger.info("both players registered; sending start")
        await self.audit.write("start_payload", matchId=self.game.match_id, message=start)
        await self.broadcast("start", start)

        await self.ready_done.wait()
        self.logger.info("both players ready; starting round loop tick_ms=%s", self.tick_ms)
        await self.broadcast("inquire", self.game.inquire_payload())

        while not self.ended and not self.game.is_over():
            self.pending_actions = {}
            self.action_event.clear()
            deadline = self.tick_ms / 1000
            started_wait = time.monotonic()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.action_event.wait(), timeout=deadline)
            elapsed_ms = round((time.monotonic() - started_wait) * 1000, 2)
            packets = {player_id: self.pending_actions.get(player_id) for player_id in self.game.players}
            await self.audit.write(
                "round_actions_closed",
                matchId=self.game.match_id,
                round=self.game.round,
                elapsedMs=elapsed_ms,
                receivedPlayerIds=sorted(self.pending_actions),
                missingPlayerIds=sorted(pid for pid in self.game.players if pid not in self.pending_actions),
            )
            events, results = self.game.settle_round(packets)
            settled_round = self.game.round - 1
            self.logger.info(
                "round=%s events=%s results=%s scores=%s",
                settled_round,
                len(events),
                [
                    {
                        "playerId": result["playerId"],
                        "action": result["action"],
                        "accepted": result["accepted"],
                        "errorCode": result.get("errorCode"),
                    }
                    for result in results
                ],
                {p.team_id: self.game.calculate_score(p)["total"] for p in self.game.players.values()},
            )
            await self.audit.write(
                "round_settled",
                matchId=self.game.match_id,
                round=settled_round,
                events=events,
                actionResults=results,
                players=[self.game.player_wire(p) for p in self.game.players.values()],
                nodes=[node.to_wire(settled_round) for node in self.game.nodes.values()],
            )
            self.received_rounds = {(pid, rnd) for (pid, rnd) in self.received_rounds if rnd >= self.game.round}
            if self.game.is_over():
                break
            await self.broadcast("inquire", self.game.inquire_payload())

        self.ended = True
        over = self.game.over_payload()
        self.logger.info("match over result=%s winner=%s reason=%s", over["resultType"], over["winnerPlayerId"], over["overReason"])
        await self.audit.write("over", matchId=self.game.match_id, message=over)
        await self.broadcast("over", over)
        await asyncio.sleep(0.2)
        for session in list(self.sessions.values()):
            session.writer.close()
        if self.server:
            self.server.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python TCP match server for 一骑红尘：荔枝争运战")
    parser.add_argument("--host", default="0.0.0.0", help="host/IP to bind")
    parser.add_argument("--port", type=int, default=8081, help="TCP port to bind")
    parser.add_argument("--tick-ms", type=int, default=500, help="round action timeout in milliseconds")
    parser.add_argument("--duration-round", type=int, default=DEFAULT_DURATION_ROUND, help="maximum match rounds")
    parser.add_argument("--seed", type=int, default=20260630, help="deterministic local seed")
    parser.add_argument("--log-dir", default="logs", help="directory for server.log and audit JSONL")
    parser.add_argument("--allowed-player-ids", default="1001,1002", help="comma-separated allowed playerIds; empty allows any two")
    parser.add_argument("--verbose", action="store_true", help="print debug logs to console")
    return parser.parse_args(argv)


def parse_allowed_player_ids(value: str) -> Optional[set[int]]:
    text = value.strip()
    if not text:
        return None
    allowed: set[int] = set()
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            allowed.add(int(item))
        except ValueError as exc:
            raise SystemExit(f"invalid --allowed-player-ids entry: {item!r}") from exc
    return allowed


async def amain(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    server = MatchServer(
        host=args.host,
        port=args.port,
        tick_ms=args.tick_ms,
        duration_round=args.duration_round,
        seed=args.seed,
        log_dir=Path(args.log_dir),
        verbose=args.verbose,
        allowed_player_ids=parse_allowed_player_ids(args.allowed_player_ids),
    )
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)
    server_task = asyncio.create_task(server.run(), name="server")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")
    done, pending = await asyncio.wait({server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        if task is server_task:
            task.result()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
