"""Convert a simplified NPC simulation result into Smallville demo files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import shutil
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent.parent
FRONTEND_DIR = REPO_ROOT / "environment" / "frontend_server"
MATRIX_DIR = FRONTEND_DIR / "static_dirs" / "assets" / "the_ville" / "matrix"
CHARACTER_DIR = FRONTEND_DIR / "static_dirs" / "assets" / "characters"
PROFILE_DIR = FRONTEND_DIR / "static_dirs" / "assets" / "characters" / "profile"
DEFAULT_INPUT = BACKEND_DIR / "simulation_result.json"
DEFAULT_SIM_CODE = "simplified_pipeline_demo"
AVAILABLE_ADDRESSES_PATH = BACKEND_DIR / "smallville_available_addresses.txt"
START_DATE = "June 27, 2026"
VISUAL_STEP_MINUTES = 10
PLAYBACK_INTERVAL_MS = 300
CHAT_HOLD_STEPS = 2
PLAYER_NAME = "Player"
PLAYER_MARKER_HOLD_STEPS = 2
MINUTES_PER_DAY = 24 * 60
PRE_DAY_TRAVEL_MINUTES = 120
EVENING_RETURN_HOME_TIME = "20:00"
LATE_NIGHT_SLEEP_TIME = "21:00"

LOCATION_ADDRESSES = {
    "Tea Shop": "the Ville:Hobbs Cafe:cafe",
    "Market": "the Ville:The Willows Market and Pharmacy:store",
    "Village": "the Ville:Johnson Park:park",
    "Guard Post": "the Ville:The Willows Market and Pharmacy:store",
    "Shrine": "the Ville:Johnson Park:park",
    "Farm": "the Ville:Johnson Park:park",
}

NPC_EMOJI = {
    "Mira Chen": "\u2615",
    "Tovan Reed": "\U0001f6e1\ufe0f",
    "Lysa Vale": "\U0001f9f3",
    PLAYER_NAME: "\U0001f9cd",
}
DEFAULT_EMOJI = "\U0001f642"
PROFILE_PLACEHOLDERS = {
    "Mira Chen": "Abigail_Chen.png",
    "Tovan Reed": "Adam_Smith.png",
    "Lysa Vale": "Carmen_Ortiz.png",
    PLAYER_NAME: "Player.png",
}
RESTING_STATES = {
    "Mira Chen": ("Resting before opening the tea shop", "Tea Shop"),
    "Tovan Reed": ("Resting before morning patrol", "Guard Post"),
    "Lysa Vale": ("Resting before visiting the market", "Village"),
}

NPC_HOME_ADDRESSES = {
    "Mira Chen": "the Ville:Ryan Park's apartment:main room",
    "Tovan Reed": "the Ville:Dorm for Oak Hill College:common room",
    "Lysa Vale": "the Ville:Arthur Burton's apartment:main room",
}

CATEGORY_ADDRESSES = {
    "cafe": [
        "the Ville:Hobbs Cafe:cafe",
    ],
    "market": [
        "the Ville:The Willows Market and Pharmacy:store",
    ],
    "park": [
        "the Ville:Johnson Park:park",
    ],
    "residential": [
        "the Ville:Isabella Rodriguez's apartment:main room",
        "the Ville:Arthur Burton's apartment:main room",
        "the Ville:Ryan Park's apartment:main room",
        "the Ville:Adam Smith's house:main room",
        "the Ville:Yuriko Yamamoto's house:main room",
        "the Ville:Dorm for Oak Hill College:common room",
    ],
    "street_or_public": [
        "the Ville:Johnson Park:park",
        "the Ville:Oak Hill College:hallway",
        "the Ville:The Rose and Crown Pub:pub",
    ],
    "quiet": [
        "the Ville:Johnson Park:park",
        "the Ville:Oak Hill College:library",
    ],
    "outdoor": [
        "the Ville:Johnson Park:park",
        "the Ville:Dorm for Oak Hill College:garden",
        "the Ville:Moreno family's house:garden",
        "the Ville:Lin family's house:garden",
    ],
    "work": [
        "the Ville:Hobbs Cafe:cafe",
        "the Ville:The Willows Market and Pharmacy:store",
        "the Ville:Harvey Oak Supply Store:supply store",
        "the Ville:Oak Hill College:library",
    ],
}


@dataclass(frozen=True)
class LocationTarget:
    label: str
    address: str
    tile: Tuple[int, int]


@dataclass(frozen=True)
class MappingDecision:
    category: str
    target: LocationTarget


@dataclass(frozen=True)
class TransitionRoute:
    path: Tuple[Tuple[int, int], ...]
    algorithm: str
    fallback: bool = False


def read_csv_rows(path: Path) -> List[List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [[cell.strip() for cell in row] for row in csv.reader(handle) if row]


def read_flat_matrix(path: Path) -> List[str]:
    rows = read_csv_rows(path)
    return [cell for row in rows for cell in row]


def block_lookup(path: Path) -> Dict[str, str]:
    return {row[0]: row[-1] for row in read_csv_rows(path)}


def choose_central_tile(tiles: Sequence[Tuple[int, int]]) -> Tuple[int, int]:
    if not tiles:
        raise ValueError("Cannot choose a tile from an empty candidate list.")
    mean_x = sum(tile[0] for tile in tiles) / len(tiles)
    mean_y = sum(tile[1] for tile in tiles) / len(tiles)
    return min(
        tiles,
        key=lambda tile: (
            math.dist(tile, (mean_x, mean_y)),
            tile[1],
            tile[0],
        ),
    )


def load_valid_address_tiles() -> Dict[str, List[Tuple[int, int]]]:
    meta = json.loads((MATRIX_DIR / "maze_meta_info.json").read_text(encoding="utf-8"))
    width = int(meta["maze_width"])
    world_rows = read_csv_rows(MATRIX_DIR / "special_blocks" / "world_blocks.csv")
    world = world_rows[0][-1]
    sectors = block_lookup(MATRIX_DIR / "special_blocks" / "sector_blocks.csv")
    arenas = block_lookup(MATRIX_DIR / "special_blocks" / "arena_blocks.csv")

    sector_matrix = read_flat_matrix(MATRIX_DIR / "maze" / "sector_maze.csv")
    arena_matrix = read_flat_matrix(MATRIX_DIR / "maze" / "arena_maze.csv")
    collision_matrix = read_flat_matrix(MATRIX_DIR / "maze" / "collision_maze.csv")
    if not (
        len(sector_matrix) == len(arena_matrix) == len(collision_matrix)
    ):
        raise ValueError("Smallville matrix files have inconsistent dimensions.")

    address_tiles: Dict[str, List[Tuple[int, int]]] = {}
    for index, collision in enumerate(collision_matrix):
        if collision != "0":
            continue
        sector = sectors.get(sector_matrix[index], "")
        arena = arenas.get(arena_matrix[index], "")
        if not sector:
            continue

        x = index % width
        y = index // width
        sector_address = f"{world}:{sector}"
        address_tiles.setdefault(sector_address, []).append((x, y))
        if arena:
            arena_address = f"{sector_address}:{arena}"
            address_tiles.setdefault(arena_address, []).append((x, y))

    return address_tiles


def load_walkable_grid() -> Tuple[int, int, set[Tuple[int, int]]]:
    meta = json.loads((MATRIX_DIR / "maze_meta_info.json").read_text(encoding="utf-8"))
    width = int(meta["maze_width"])
    height = int(meta["maze_height"])
    collision_matrix = read_flat_matrix(MATRIX_DIR / "maze" / "collision_maze.csv")
    if len(collision_matrix) != width * height:
        raise ValueError("Smallville collision matrix dimensions do not match metadata.")
    walkable_set = {
        (index % width, index // width)
        for index, collision in enumerate(collision_matrix)
        if collision == "0"
    }
    return width, height, walkable_set


def load_walkable_tiles() -> List[Tuple[int, int]]:
    _, _, walkable_set = load_walkable_grid()
    return sorted(walkable_set)


def build_location_targets() -> Dict[str, LocationTarget]:
    valid_address_tiles = load_valid_address_tiles()
    targets: Dict[str, LocationTarget] = {}
    for label, address in LOCATION_ADDRESSES.items():
        candidates = valid_address_tiles.get(address, [])
        if not candidates:
            raise ValueError(f"No walkable Smallville tiles found for {label}: {address}")
        targets[label] = LocationTarget(
            label=label,
            address=address,
            tile=choose_central_tile(candidates),
        )
    return targets


def write_available_addresses(
    address_tiles: Mapping[str, Sequence[Tuple[int, int]]],
    output_path: Path = AVAILABLE_ADDRESSES_PATH,
) -> Path:
    lines = ["address | walkable_tile_count | representative_tile"]
    for address in sorted(address_tiles):
        tiles = address_tiles[address]
        representative = choose_central_tile(tiles)
        lines.append(
            f"{address} | {len(tiles)} | [{representative[0]}, {representative[1]}]"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def pool_targets(
    addresses: Sequence[str],
    address_tiles: Mapping[str, Sequence[Tuple[int, int]]],
) -> List[LocationTarget]:
    targets: List[LocationTarget] = []
    for address in addresses:
        if address not in address_tiles:
            raise ValueError(f"Category pool address is unavailable: {address}")
        targets.extend(
            LocationTarget(label=address, address=address, tile=tile)
            for tile in sorted(address_tiles[address])
        )
    return targets


def build_category_pools(
    address_tiles: Mapping[str, Sequence[Tuple[int, int]]],
) -> Dict[str, List[LocationTarget]]:
    pools = {
        category: pool_targets(addresses, address_tiles)
        for category, addresses in CATEGORY_ADDRESSES.items()
    }

    market_address = CATEGORY_ADDRESSES["market"][0]
    market_tiles = set(address_tiles[market_address])
    market_edge = sorted(
        tile
        for tile in market_tiles
        if any(
            (tile[0] + dx, tile[1] + dy) not in market_tiles
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
    )
    market_core = sorted(market_tiles.difference(market_edge))
    pools["market"] = [
        LocationTarget("market_core", market_address, tile)
        for tile in (market_core or sorted(market_tiles))
    ]
    pools["guard"] = [
        LocationTarget("market_edge", market_address, tile)
        for tile in (market_edge or sorted(market_tiles))
    ]

    for category, targets in pools.items():
        if len(targets) < 2:
            raise ValueError(f"Semantic category pool is too small: {category}")
    return pools


def stable_pool_index(key: str, pool_size: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % pool_size


def semantic_category(
    action: str,
    location: str,
    role: str,
) -> str:
    action_text = action.lower()
    combined = f"{action} {location}".lower()
    role_text = role.lower()

    if any(term in action_text for term in ("rest", "sleep", "at home", "winding down")):
        return "residential"
    if any(
        term in combined
        for term in (
            "patrol",
            "guard",
            "suspicious",
            "dispute",
            "inspect",
            "inspection",
            "entrance",
            "security",
            "surveillance",
            "perimeter",
            "captain",
        )
    ):
        return "guard"
    if any(
        term in combined
        for term in (
            "tea",
            "cafe",
            "coffee",
            "customer",
            "regular",
            "serve",
            "shop",
        )
    ):
        return "cafe"
    if any(
        term in action_text
        for term in ("review notes", "record", "journal", "ledger", "personal log")
    ):
        return "residential"
    if any(
        term in combined
        for term in (
            "market",
            "vendor",
            "stall",
            "trade",
            "goods",
            "merchant",
            "negotiate",
            "supplier",
            "buy",
            "sell",
        )
    ):
        return "market"
    if any(term in combined for term in ("shrine", "reflect", "quiet", "pray")):
        return "quiet"
    if any(term in combined for term in ("farm", "produce", "crop", "field", "outdoor")):
        return "outdoor"
    if any(
        term in combined
        for term in ("news", "locals", "community", "social", "meet", "bulletin")
    ):
        return "street_or_public"

    if "tea" in role_text or "cafe" in role_text:
        return "cafe"
    if "guard" in role_text:
        return "guard"
    if "merchant" in role_text or "trader" in role_text:
        return "market"
    if "farmer" in role_text:
        return "outdoor"
    if "shrine" in role_text:
        return "quiet"
    return "work"


def map_semantic_state(
    npc_name: str,
    role: str,
    state: Mapping[str, object],
    pools: Mapping[str, Sequence[LocationTarget]],
) -> MappingDecision:
    action = str(state["action"])
    location = str(state.get("location", ""))
    category = semantic_category(action, location, role)
    pool = pools[category]
    index = stable_pool_index(
        f"{npc_name}|{action}|{category}",
        len(pool),
    )
    return MappingDecision(category=category, target=pool[index])


def home_target_for(
    npc_name: str,
    address_tiles: Mapping[str, Sequence[Tuple[int, int]]],
) -> LocationTarget:
    address = NPC_HOME_ADDRESSES.get(
        npc_name,
        "the Ville:Dorm for Oak Hill College:common room",
    )
    if address not in address_tiles:
        address = "the Ville:Dorm for Oak Hill College:common room"
    return LocationTarget(
        label="home",
        address=address,
        tile=choose_central_tile(address_tiles[address]),
    )


def home_decision_for(
    npc_name: str,
    address_tiles: Mapping[str, Sequence[Tuple[int, int]]],
) -> MappingDecision:
    return MappingDecision(
        category="home",
        target=home_target_for(npc_name, address_tiles),
    )


def completed_home_state(action: str) -> Dict[str, object]:
    return {
        "action": action,
        "location": "Home",
        "schedule_completion": True,
    }


def complete_semantic_day_for_npc(
    npc_name: str,
    entries: Sequence[Tuple[int, Mapping[str, object], MappingDecision]],
    home_decision: MappingDecision,
) -> List[Tuple[int, Mapping[str, object], MappingDecision]]:
    completed = list(entries)
    if not completed:
        return completed

    last_minutes, _, last_decision = completed[-1]
    return_home_minutes = max(
        time_to_minutes(EVENING_RETURN_HOME_TIME),
        last_minutes + VISUAL_STEP_MINUTES,
    )
    sleep_minutes = max(
        time_to_minutes(LATE_NIGHT_SLEEP_TIME),
        return_home_minutes + VISUAL_STEP_MINUTES,
    )

    if return_home_minutes < MINUTES_PER_DAY:
        if last_decision.target.address != home_decision.target.address:
            completed.append(
                (
                    return_home_minutes,
                    completed_home_state("Returning home for the evening"),
                    home_decision,
                )
            )
        else:
            completed.append(
                (
                    return_home_minutes,
                    completed_home_state("Settling in at home for the evening"),
                    home_decision,
                )
            )

    if sleep_minutes < MINUTES_PER_DAY:
        completed.append(
            (
                sleep_minutes,
                completed_home_state("Sleeping at home"),
                home_decision,
            )
        )

    return sorted(completed, key=lambda item: item[0])


def escape_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def validate_result(result: Mapping[str, object]) -> None:
    for key in ("metadata", "npcs", "timeline", "conversations"):
        if key not in result:
            raise ValueError(f"simulation_result.json is missing required key: {key}")
    if not result["timeline"]:
        raise ValueError("simulation_result.json must contain at least one timeline step.")


def build_run_info(
    metadata: Mapping[str, object],
    *,
    visual_steps: int,
    sec_per_step: int,
) -> Dict[str, object]:
    count_fields = (
        "planning_calls",
        "planning_success_count",
        "conversation_attempts",
        "conversation_success_count",
        "conversation_retry_count",
        "reflection_calls",
        "reflection_success_count",
    )
    run_info: Dict[str, object] = {
        "backend": metadata.get("backend") or "N/A",
        "model": metadata.get("model") or "N/A",
        "total_elapsed_seconds": metadata.get(
            "total_elapsed_seconds", "N/A"
        ),
        "average_llm_call_time": metadata.get(
            "average_llm_call_time", "N/A"
        ),
        "estimated_cost_usd": metadata.get(
            "estimated_total_cost_usd",
            metadata.get("estimated_cost_usd", "N/A"),
        ),
        "visual_steps": visual_steps,
        "visual_step_minutes": sec_per_step / 60,
    }
    for field in count_fields:
        run_info[field] = metadata.get(field, 0)
    return run_info


def parse_time_on_start_date(time_text: str) -> datetime:
    return datetime.strptime(f"{START_DATE} {time_text}", "%B %d, %Y %H:%M")


def formatted_time(time_text: str) -> str:
    return parse_time_on_start_date(time_text).strftime("%B %d, %Y, %H:%M:%S")


def time_to_minutes(time_text: str) -> int:
    parsed = datetime.strptime(time_text, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def minutes_to_time(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def conversations_by_time(
    conversations: Iterable[Mapping[str, object]],
) -> Dict[str, List[Mapping[str, object]]]:
    indexed: Dict[str, List[Mapping[str, object]]] = {}
    for conversation in conversations:
        indexed.setdefault(str(conversation["time"]), []).append(conversation)
    return indexed


def chat_for_state(
    state: Mapping[str, object],
    step_conversations: Sequence[Mapping[str, object]],
) -> List[List[str]] | None:
    npc_name = str(state["npc"])
    location = str(state["location"])
    matching_lines: List[List[str]] = []
    for conversation in step_conversations:
        participants = [str(name) for name in conversation.get("participants", [])]
        if npc_name not in participants or str(conversation.get("location")) != location:
            continue
        for line in conversation.get("lines", []):
            matching_lines.append(
                [
                    escape_text(line["speaker"]),
                    escape_text(line["text"]),
                ]
            )
    return matching_lines or None


def validate_timeline_npcs(
    timeline: Sequence[Mapping[str, object]],
    known_npcs: set[str],
) -> None:
    for step_index, tick in enumerate(timeline):
        state_names = {str(state["npc"]) for state in tick["states"]}
        if state_names != known_npcs:
            raise ValueError(
                f"Timeline step {step_index} NPCs do not match the npcs list: "
                f"{sorted(state_names)}"
            )


def movement_entry(
    npc_name: str,
    action: str,
    target: LocationTarget,
    tile: Tuple[int, int],
    chat: List[List[str]] | None,
    visible: bool = True,
) -> Dict[str, object]:
    return {
        "movement": list(tile),
        "pronunciatio": NPC_EMOJI.get(npc_name, DEFAULT_EMOJI),
        "description": f"{escape_text(action)} @ {escape_text(target.address)}",
        "chat": chat,
        "visible": visible,
    }


def player_events(result: Mapping[str, object]) -> List[Mapping[str, object]]:
    events = result.get("player_events", [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, Mapping)]


def player_marker_target(
    event: Mapping[str, object],
    category_pools: Mapping[str, Sequence[LocationTarget]],
) -> MappingDecision:
    action = str(
        event.get("action")
        or event.get("description")
        or "Player event"
    )
    location = str(event.get("location") or "Village")
    location_category = {
        "Tea Shop": "cafe",
        "Market": "market",
        "Guard Post": "guard",
        "Village": "park",
    }.get(location)
    if location_category and location_category in category_pools:
        pool = category_pools[location_category]
        index = stable_pool_index(
            f"{PLAYER_NAME}|{location}|{action}|{location_category}",
            len(pool),
        )
        return MappingDecision(category=location_category, target=pool[index])
    state = {"action": action, "location": location}
    return map_semantic_state(PLAYER_NAME, "player event marker", state, category_pools)


def marker_action(event: Mapping[str, object]) -> str:
    action = str(event.get("action") or event.get("description") or "Player event")
    return f"Player event: {action}"


def add_player_marker_to_full_day_movement(
    movement: Dict[str, object],
    result: Mapping[str, object],
    category_pools: Mapping[str, Sequence[LocationTarget]],
    visual_step_minutes: int,
    visual_step_count: int,
) -> List[Dict[str, object]]:
    events = player_events(result)
    if not events:
        return []

    marker_records: List[Dict[str, object]] = []
    event_windows: List[Tuple[int, int, Mapping[str, object], MappingDecision]] = []
    for event in events:
        event_step = round(time_to_minutes(str(event.get("time", "00:00"))) / visual_step_minutes)
        start_step = max(0, min(event_step, visual_step_count - 1))
        end_step = min(visual_step_count - 1, start_step + PLAYER_MARKER_HOLD_STEPS - 1)
        decision = player_marker_target(event, category_pools)
        event_windows.append((start_step, end_step, event, decision))
        marker_records.append(
            {
                "event_time": str(event.get("time", "N/A")),
                "start_step": start_step,
                "end_step": end_step,
                "location": str(event.get("location", "N/A")),
                "affected_npc": str(event.get("affected_npc", "N/A")),
                "event_type": str(event.get("event_type", "N/A")),
                "action": str(event.get("action", event.get("description", "Player event"))),
                "address": decision.target.address,
                "tile": list(decision.target.tile),
                "visible_steps": PLAYER_MARKER_HOLD_STEPS,
            }
        )

    default_event = event_windows[0][2]
    default_decision = event_windows[0][3]
    for visual_step in range(visual_step_count):
        active_window = next(
            (
                (event, decision)
                for start_step, end_step, event, decision in event_windows
                if start_step <= visual_step <= end_step
            ),
            None,
        )
        if active_window:
            event, decision = active_window
            visible = True
            action = marker_action(event)
        else:
            event, decision = default_event, default_decision
            visible = False
            action = "Waiting off-screen"
        step_data = movement.setdefault(str(visual_step), {})
        step_data[PLAYER_NAME] = movement_entry(
            PLAYER_NAME,
            action,
            decision.target,
            decision.target.tile,
            None,
            visible=visible,
        )
    return marker_records


def build_compact_demo_payload(
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    timeline = result["timeline"]
    npc_names = [str(npc["name"]) for npc in result["npcs"]]
    known_npcs = set(npc_names)
    indexed_conversations = conversations_by_time(result["conversations"])
    validate_timeline_npcs(timeline, known_npcs)

    movement: Dict[str, object] = {}
    for step_index, tick in enumerate(timeline):
        states = tick["states"]
        step_data: Dict[str, object] = {}
        for state in states:
            location = str(state["location"])
            if location not in targets:
                raise ValueError(f"Unknown simplified location: {location}")
            target = targets[location]
            npc_name = str(state["npc"])
            step_data[npc_name] = movement_entry(
                npc_name,
                str(state["action"]),
                target,
                target.tile,
                chat_for_state(
                    state,
                    indexed_conversations.get(str(tick["time"]), []),
                ),
            )
        movement[str(step_index)] = step_data

    final_time = parse_time_on_start_date(str(timeline[-1]["time"]))
    meta = {
        "fork_sim_code": "simplified_pipeline",
        "start_date": START_DATE,
        "start_time": f"{timeline[0]['time']}:00",
        "curr_time": final_time.strftime("%B %d, %Y, %H:%M:%S"),
        "sec_per_step": 7200,
        "playback_frame_budget": 240,
        "playback_interval_ms": 0,
        "maze_name": "the_ville",
        "persona_names": npc_names,
        # The original server stores the next step number, so N states means step N.
        "step": len(timeline),
    }
    return meta, movement


def nearest_walkable_tile(
    candidate: Tuple[int, int],
    walkable_tiles: Sequence[Tuple[int, int]],
    walkable_set: set[Tuple[int, int]],
    cache: Dict[Tuple[int, int], Tuple[int, int]],
) -> Tuple[int, int]:
    if candidate in walkable_set:
        return candidate
    if candidate not in cache:
        cache[candidate] = min(
            walkable_tiles,
            key=lambda tile: (
                (tile[0] - candidate[0]) ** 2 + (tile[1] - candidate[1]) ** 2,
                tile[1],
                tile[0],
            ),
        )
    return cache[candidate]


def interpolated_tile(
    start: Tuple[int, int],
    end: Tuple[int, int],
    fraction: float,
    walkable_tiles: Sequence[Tuple[int, int]],
    walkable_set: set[Tuple[int, int]],
    cache: Dict[Tuple[int, int], Tuple[int, int]],
) -> Tuple[int, int]:
    candidate = (
        round(start[0] + (end[0] - start[0]) * fraction),
        round(start[1] + (end[1] - start[1]) * fraction),
    )
    return nearest_walkable_tile(candidate, walkable_tiles, walkable_set, cache)


def reconstruct_path(
    parents: Mapping[Tuple[int, int], Tuple[int, int] | None],
    end: Tuple[int, int],
) -> List[Tuple[int, int]]:
    path = [end]
    current = end
    while parents[current] is not None:
        current = parents[current]  # type: ignore[assignment]
        path.append(current)
    path.reverse()
    return path


def bfs_path(
    start: Tuple[int, int],
    end: Tuple[int, int],
    walkable_set: set[Tuple[int, int]],
    *,
    allow_diagonal: bool = False,
) -> List[Tuple[int, int]] | None:
    if start not in walkable_set or end not in walkable_set:
        return None
    if start == end:
        return [start]

    cardinal_neighbors = ((0, -1), (-1, 0), (1, 0), (0, 1))
    diagonal_neighbors = ((-1, -1), (1, -1), (-1, 1), (1, 1))
    queue = deque([start])
    parents: Dict[Tuple[int, int], Tuple[int, int] | None] = {start: None}

    while queue:
        current = queue.popleft()
        for dx, dy in cardinal_neighbors + (
            diagonal_neighbors if allow_diagonal else ()
        ):
            neighbor = (current[0] + dx, current[1] + dy)
            if neighbor not in walkable_set or neighbor in parents:
                continue
            if dx and dy:
                # A diagonal may not squeeze through the corner of two walls.
                adjacent_x = (current[0] + dx, current[1])
                adjacent_y = (current[0], current[1] + dy)
                if adjacent_x not in walkable_set or adjacent_y not in walkable_set:
                    continue
            parents[neighbor] = current
            if neighbor == end:
                return reconstruct_path(parents, end)
            queue.append(neighbor)
    return None


def find_transition_route(
    start: Tuple[int, int],
    end: Tuple[int, int],
    walkable_tiles: Sequence[Tuple[int, int]],
    walkable_set: set[Tuple[int, int]],
    nearest_cache: Dict[Tuple[int, int], Tuple[int, int]],
) -> TransitionRoute:
    valid_start = nearest_walkable_tile(
        start, walkable_tiles, walkable_set, nearest_cache
    )
    valid_end = nearest_walkable_tile(
        end, walkable_tiles, walkable_set, nearest_cache
    )
    if valid_start == valid_end:
        return TransitionRoute((valid_start,), "same_tile")

    path = bfs_path(valid_start, valid_end, walkable_set)
    if path:
        return TransitionRoute(tuple(path), "bfs_4")

    path = bfs_path(valid_start, valid_end, walkable_set, allow_diagonal=True)
    if path:
        return TransitionRoute(tuple(path), "bfs_8")

    print(
        "WARNING: no collision-aware path found from "
        f"{list(valid_start)} to {list(valid_end)}; using linear fallback.",
        file=sys.stderr,
    )
    return TransitionRoute((valid_start, valid_end), "linear_fallback", True)


def sample_transition_route(
    route: TransitionRoute,
    fraction: float,
    walkable_tiles: Sequence[Tuple[int, int]],
    walkable_set: set[Tuple[int, int]],
    nearest_cache: Dict[Tuple[int, int], Tuple[int, int]],
) -> Tuple[int, int]:
    bounded_fraction = min(1.0, max(0.0, fraction))
    if route.algorithm == "linear_fallback":
        return interpolated_tile(
            route.path[0],
            route.path[-1],
            bounded_fraction,
            walkable_tiles,
            walkable_set,
            nearest_cache,
        )
    if len(route.path) == 1:
        return route.path[0]
    path_index = int(bounded_fraction * (len(route.path) - 1) + 0.5)
    return route.path[path_index]


def build_visual_chat_index(
    conversations: Sequence[Mapping[str, object]],
    visual_step_minutes: int,
    chat_hold_steps: int,
    visual_step_count: int,
) -> Dict[Tuple[int, str], List[List[str]]]:
    chat_index: Dict[Tuple[int, str], List[List[str]]] = {}
    for conversation in conversations:
        conversation_step = round(
            time_to_minutes(str(conversation["time"])) / visual_step_minutes
        )
        chat_lines = [
            [escape_text(line["speaker"]), escape_text(line["text"])]
            for line in conversation.get("lines", [])
        ]
        for offset in range(chat_hold_steps):
            visual_step = conversation_step + offset
            if visual_step >= visual_step_count:
                break
            for participant in conversation.get("participants", []):
                chat_index[(visual_step, str(participant))] = chat_lines
    return chat_index


def build_conversation_timeline(
    conversations: Sequence[Mapping[str, object]],
    visual_step_minutes: int,
    visual_step_count: int,
    hold_steps: int = 3,
) -> Dict[str, List[Dict[str, str]]]:
    timeline: Dict[str, List[Dict[str, str]]] = {}
    if hold_steps < 1:
        hold_steps = 1
    for conversation in conversations:
        conversation_step = round(
            time_to_minutes(str(conversation.get("time", "00:00"))) / visual_step_minutes
        )
        participants = [str(name) for name in conversation.get("participants", [])]
        lines: List[Dict[str, str]] = []
        for index, line in enumerate(conversation.get("lines", [])):
            if not isinstance(line, Mapping):
                continue
            speaker = str(line.get("speaker", "Unknown"))
            target = ""
            if participants:
                others = [name for name in participants if name != speaker]
                target = others[0] if others else participants[0]
            lines.append(
                {
                    "speaker": speaker,
                    "text": str(line.get("text", "")),
                    "target": target,
                    "line_index": str(index),
                    "time": str(conversation.get("time", "")),
                    "location": str(conversation.get("location", "")),
                }
            )
        if not lines:
            continue
        for offset in range(hold_steps):
            visual_step = conversation_step + offset
            if 0 <= visual_step < visual_step_count:
                timeline[str(visual_step)] = lines
    return timeline


def build_full_day_demo_payload(
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
    visual_step_minutes: int,
    chat_hold_steps: int,
    mapping_diagnostics: List[Dict[str, object]] | None = None,
    pathfinding_diagnostics: Dict[str, object] | None = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    if visual_step_minutes <= 0 or MINUTES_PER_DAY % visual_step_minutes:
        raise ValueError("visual_step_minutes must divide evenly into 1440.")
    if chat_hold_steps < 1:
        raise ValueError("chat_hold_steps must be at least 1.")

    timeline = sorted(
        result["timeline"],
        key=lambda tick: time_to_minutes(str(tick["time"])),
    )
    npc_names = [str(npc["name"]) for npc in result["npcs"]]
    known_npcs = set(npc_names)
    validate_timeline_npcs(timeline, known_npcs)
    npc_profiles = {
        str(npc["name"]): npc
        for npc in result["npcs"]
    }
    address_tiles = load_valid_address_tiles()
    category_pools = build_category_pools(address_tiles)
    home_decisions = {
        npc_name: home_decision_for(npc_name, address_tiles)
        for npc_name in npc_names
    }

    semantic_by_npc: Dict[
        str,
        List[Tuple[int, Mapping[str, object], MappingDecision]],
    ] = {
        npc_name: [] for npc_name in npc_names
    }
    for tick in timeline:
        tick_minutes = time_to_minutes(str(tick["time"]))
        for state in tick["states"]:
            npc_name = str(state["npc"])
            decision = map_semantic_state(
                npc_name,
                str(npc_profiles[npc_name].get("role", "")),
                state,
                category_pools,
            )
            semantic_by_npc[npc_name].append((tick_minutes, state, decision))
            if mapping_diagnostics is not None:
                mapping_diagnostics.append(
                    {
                        "time": str(tick["time"]),
                        "npc": npc_name,
                        "role": str(npc_profiles[npc_name].get("role", "")),
                        "action": str(state["action"]),
                        "input_location": str(state["location"]),
                        "category": decision.category,
                        "address": decision.target.address,
                        "tile": list(decision.target.tile),
                    }
                )

    for npc_name in npc_names:
        semantic_by_npc[npc_name] = complete_semantic_day_for_npc(
            npc_name,
            semantic_by_npc[npc_name],
            home_decisions[npc_name],
        )
        if mapping_diagnostics is not None:
            for tick_minutes, state, decision in semantic_by_npc[npc_name]:
                if state.get("schedule_completion"):
                    mapping_diagnostics.append(
                        {
                            "time": minutes_to_time(tick_minutes),
                            "npc": npc_name,
                            "role": str(npc_profiles[npc_name].get("role", "")),
                            "action": str(state["action"]),
                            "input_location": str(state["location"]),
                            "category": decision.category,
                            "address": decision.target.address,
                            "tile": list(decision.target.tile),
                            "schedule_completion": True,
                        }
                    )

    resting_decisions: Dict[str, Tuple[str, MappingDecision]] = {}
    for npc_name in npc_names:
        resting_action = "Sleeping at home"
        resting_decisions[npc_name] = (
            resting_action,
            home_decisions[npc_name],
        )

    visual_step_count = MINUTES_PER_DAY // visual_step_minutes
    chat_index = build_visual_chat_index(
        result["conversations"],
        visual_step_minutes,
        chat_hold_steps,
        visual_step_count,
    )
    _, _, walkable_set = load_walkable_grid()
    walkable_tiles = sorted(walkable_set)
    collision_fallback_cache: Dict[Tuple[int, int], Tuple[int, int]] = {}
    transition_routes: Dict[Tuple[str, int], TransitionRoute] = {}
    transition_records: List[Dict[str, object]] = []
    for npc_name, entries in semantic_by_npc.items():
        first_minutes, _, first_decision = entries[0]
        _, resting_decision = resting_decisions[npc_name]
        pre_day_route = find_transition_route(
            resting_decision.target.tile,
            first_decision.target.tile,
            walkable_tiles,
            walkable_set,
            collision_fallback_cache,
        )
        transition_routes[(npc_name, -1)] = pre_day_route
        departure_minutes = max(0, first_minutes - PRE_DAY_TRAVEL_MINUTES)
        transition_records.append(
            {
                "npc": npc_name,
                "transition_type": "day_start",
                "start_time": minutes_to_time(departure_minutes),
                "end_time": minutes_to_time(first_minutes),
                "start_tile": list(resting_decision.target.tile),
                "end_tile": list(first_decision.target.tile),
                "algorithm": pre_day_route.algorithm,
                "path_length": len(pre_day_route.path),
                "fallback": pre_day_route.fallback,
            }
        )
        for current_index in range(len(entries) - 1):
            current_minutes, _, current_decision = entries[current_index]
            next_minutes, _, next_decision = entries[current_index + 1]
            route = find_transition_route(
                current_decision.target.tile,
                next_decision.target.tile,
                walkable_tiles,
                walkable_set,
                collision_fallback_cache,
            )
            transition_routes[(npc_name, current_index)] = route
            transition_records.append(
                {
                    "npc": npc_name,
                    "transition_type": "semantic",
                    "start_time": minutes_to_time(current_minutes),
                    "end_time": minutes_to_time(next_minutes),
                    "start_tile": list(current_decision.target.tile),
                    "end_tile": list(next_decision.target.tile),
                    "algorithm": route.algorithm,
                    "path_length": len(route.path),
                    "fallback": route.fallback,
                }
            )

    movement: Dict[str, object] = {}
    for visual_step in range(visual_step_count):
        current_minutes = visual_step * visual_step_minutes
        step_data: Dict[str, object] = {}
        for npc_name in npc_names:
            entries = semantic_by_npc[npc_name]
            first_minutes, _, _ = entries[0]
            last_minutes, last_state, last_decision = entries[-1]

            if current_minutes < first_minutes:
                resting_action, resting_decision = resting_decisions[npc_name]
                target = resting_decision.target
                action = resting_action
                tile = target.tile
                departure_minutes = max(
                    0, first_minutes - PRE_DAY_TRAVEL_MINUTES
                )
                if current_minutes >= departure_minutes:
                    travel_duration = first_minutes - departure_minutes
                    fraction = (
                        (current_minutes - departure_minutes) / travel_duration
                        if travel_duration
                        else 1.0
                    )
                    tile = sample_transition_route(
                        transition_routes[(npc_name, -1)],
                        fraction,
                        walkable_tiles,
                        walkable_set,
                        collision_fallback_cache,
                    )
            elif current_minutes > last_minutes:
                target = last_decision.target
                action = str(last_state.get("action") or "Winding down after the day's activities")
                tile = target.tile
            else:
                current_index = max(
                    index
                    for index, (tick_minutes, _, _) in enumerate(entries)
                    if tick_minutes <= current_minutes
                )
                current_tick_minutes, current_state, current_decision = entries[
                    current_index
                ]
                target = current_decision.target
                action = str(current_state["action"])
                tile = target.tile

                if current_index + 1 < len(entries):
                    next_tick_minutes, _, next_decision = entries[current_index + 1]
                    if next_tick_minutes > current_tick_minutes:
                        fraction = (
                            (current_minutes - current_tick_minutes)
                            / (next_tick_minutes - current_tick_minutes)
                        )
                        tile = sample_transition_route(
                            transition_routes[(npc_name, current_index)],
                            fraction,
                            walkable_tiles,
                            walkable_set,
                            collision_fallback_cache,
                        )

            step_data[npc_name] = movement_entry(
                npc_name,
                action,
                target,
                tile,
                chat_index.get((visual_step, npc_name)),
            )
        movement[str(visual_step)] = step_data

    player_marker_records = add_player_marker_to_full_day_movement(
        movement,
        result,
        category_pools,
        visual_step_minutes,
        visual_step_count,
    )
    if player_marker_records and PLAYER_NAME not in npc_names:
        npc_names = [*npc_names, PLAYER_NAME]

    end_minutes = (visual_step_count - 1) * visual_step_minutes
    meta = {
        "fork_sim_code": "simplified_pipeline",
        "start_date": START_DATE,
        "start_time": "00:00:00",
        "curr_time": parse_time_on_start_date(
            minutes_to_time(end_minutes)
        ).strftime("%B %d, %Y, %H:%M:%S"),
        "sec_per_step": visual_step_minutes * 60,
        "playback_interval_ms": PLAYBACK_INTERVAL_MS,
        "maze_name": "the_ville",
        "persona_names": npc_names,
        "step": visual_step_count,
    }
    if player_marker_records:
        meta["player_event_markers"] = player_marker_records
    if pathfinding_diagnostics is not None:
        unique_visual_tiles = {
            tuple(state["movement"])
            for step_data in movement.values()
            for state in step_data.values()
        }
        max_jump = 0
        max_jump_detail: Dict[str, object] | None = None
        for npc_name in npc_names:
            previous_tile: Tuple[int, int] | None = None
            for visual_step in range(visual_step_count):
                tile = tuple(movement[str(visual_step)][npc_name]["movement"])
                if previous_tile is not None:
                    jump = (
                        abs(tile[0] - previous_tile[0])
                        + abs(tile[1] - previous_tile[1])
                    )
                    if jump > max_jump:
                        max_jump = jump
                        max_jump_detail = {
                            "npc": npc_name,
                            "from_step": visual_step - 1,
                            "to_step": visual_step,
                            "from_tile": list(previous_tile),
                            "to_tile": list(tile),
                        }
                previous_tile = tile
        pathfinding_diagnostics.update(
            {
                "algorithm": "4-neighbor BFS, then corner-safe 8-neighbor BFS",
                "transition_count": len(transition_records),
                "same_tile_count": sum(
                    record["algorithm"] == "same_tile"
                    for record in transition_records
                ),
                "path_found_count": sum(
                    str(record["algorithm"]).startswith("bfs_")
                    for record in transition_records
                ),
                "bfs_4_count": sum(
                    record["algorithm"] == "bfs_4"
                    for record in transition_records
                ),
                "bfs_8_count": sum(
                    record["algorithm"] == "bfs_8"
                    for record in transition_records
                ),
                "fallback_count": sum(
                    bool(record["fallback"]) for record in transition_records
                ),
                "maximum_step_manhattan_distance": max_jump,
                "maximum_step_jump": max_jump_detail,
                "unique_visual_movement_tiles": len(unique_visual_tiles),
                "transitions": transition_records,
            }
        )
    return meta, movement


def build_demo_payload(
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
    *,
    full_day: bool = True,
    visual_step_minutes: int = VISUAL_STEP_MINUTES,
    chat_hold_steps: int = CHAT_HOLD_STEPS,
    mapping_diagnostics: List[Dict[str, object]] | None = None,
    pathfinding_diagnostics: Dict[str, object] | None = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    if full_day:
        return build_full_day_demo_payload(
            result,
            targets,
            visual_step_minutes,
            chat_hold_steps,
            mapping_diagnostics,
            pathfinding_diagnostics,
        )
    return build_compact_demo_payload(result, targets)


def daily_plan_items(npc: Mapping[str, object]) -> List[str]:
    plan = npc.get("daily_plan", [])
    if isinstance(plan, Mapping):
        return [str(plan[phase]) for phase in ("morning", "afternoon", "evening") if phase in plan]
    return [str(item) for item in plan]


def final_state_for(
    result: Mapping[str, object],
    npc_name: str,
) -> Tuple[Mapping[str, object], str]:
    for tick in reversed(result["timeline"]):
        for state in tick["states"]:
            if str(state["npc"]) == npc_name:
                return state, str(tick["time"])
    raise ValueError(f"No timeline state found for NPC: {npc_name}")


def memory_created_at(memory: str) -> str:
    match = re.match(r"At\s+(\d{2}:\d{2})", memory)
    time_text = match.group(1) if match else "07:00"
    return parse_time_on_start_date(time_text).strftime("%Y-%m-%d %H:%M:%S")


def add_memory_node(
    nodes: Dict[str, object],
    type_counts: Dict[str, int],
    *,
    node_type: str,
    created: str,
    subject: str,
    predicate: str,
    object_value: str,
    description: str,
    filling: object,
    depth: int = 0,
    poignancy: int = 1,
) -> None:
    type_counts[node_type] += 1
    node_count = len(nodes) + 1
    nodes[f"node_{node_count}"] = {
        "node_count": node_count,
        "type_count": type_counts[node_type],
        "type": node_type,
        "depth": depth,
        "created": created,
        "expiration": None,
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "description": description,
        "embedding_key": description,
        "poignancy": poignancy,
        "keywords": [subject, object_value],
        "filling": filling,
    }


def build_associative_nodes(
    npc: Mapping[str, object],
    conversations: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    npc_name = str(npc["name"])
    nodes: Dict[str, object] = {}
    type_counts = {"event": 0, "chat": 0, "thought": 0}

    for memory in npc.get("memory_stream", []):
        description = str(memory)
        add_memory_node(
            nodes,
            type_counts,
            node_type="event",
            created=memory_created_at(description),
            subject=npc_name,
            predicate="experienced",
            object_value="simulation event",
            description=description,
            filling=[],
            poignancy=1,
        )

    for conversation in conversations:
        participants = [str(name) for name in conversation.get("participants", [])]
        if npc_name not in participants:
            continue
        others = [name for name in participants if name != npc_name]
        other_name = others[0] if others else "another NPC"
        location = str(conversation.get("location", "Village"))
        filling = [
            [str(line["speaker"]), str(line["text"])]
            for line in conversation.get("lines", [])
        ]
        add_memory_node(
            nodes,
            type_counts,
            node_type="chat",
            created=parse_time_on_start_date(str(conversation["time"])).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            subject=npc_name,
            predicate="talked with",
            object_value=other_name,
            description=f"{npc_name} talked with {other_name} at {location}.",
            filling=filling,
            poignancy=3,
        )

    reflections = npc.get(
        "reflections",
        npc.get("reflection_questions", []),
    )
    for question in reflections:
        description = str(question)
        add_memory_node(
            nodes,
            type_counts,
            node_type="thought",
            created=parse_time_on_start_date("19:00").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            subject=npc_name,
            predicate="reflects on",
            object_value="recent events",
            description=description,
            filling=[],
            depth=1,
            poignancy=4,
        )
    return nodes


def build_scratch(
    npc: Mapping[str, object],
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
) -> Dict[str, object]:
    npc_name = str(npc["name"])
    name_parts = npc_name.split(maxsplit=1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    final_state, final_time = final_state_for(result, npc_name)
    final_location = str(final_state["location"])
    target = targets[final_location]
    if npc_name in NPC_HOME_ADDRESSES:
        target = home_target_for(npc_name, load_valid_address_tiles())
        final_time = "23:50"
    plan_items = daily_plan_items(npc)
    role = str(npc.get("role", "villager"))
    traits = str(npc.get("traits", ""))
    goal = str(npc.get("goal", ""))
    final_action = (
        "Sleeping at home after the day's activities"
        if npc_name in NPC_HOME_ADDRESSES
        else str(final_state["action"])
    )

    return {
        "vision_r": 8,
        "att_bandwidth": 8,
        "retention": 8,
        "curr_time": formatted_time(final_time),
        "curr_tile": list(target.tile),
        "curr_arena": target.address.split(":")[-1],
        "curr_sector": target.address.split(":")[-2],
        "curr_address": target.address,
        "daily_plan_req": "; ".join(plan_items),
        "name": npc_name,
        "first_name": first_name,
        "last_name": last_name,
        "age": 30,
        "innate": traits,
        "learned": f"{npc_name} is a {role}. Goal: {goal}",
        "currently": f"{npc_name} is currently {final_action.lower()}.",
        "lifestyle": f"{npc_name} follows a morning, afternoon, and evening routine.",
        "living_area": target.address,
        "daily_req": plan_items,
        "f_daily_schedule": [[item, 240] for item in plan_items],
        "f_daily_schedule_hourly_org": [[item, 240] for item in plan_items],
        "act_address": target.address,
        "act_start_time": formatted_time(final_time),
        "act_duration": 120,
        "act_description": final_action,
        "act_pronunciatio": NPC_EMOJI.get(npc_name, DEFAULT_EMOJI),
        "act_event": [npc_name, "is", final_action],
        "act_obj_description": None,
        "act_obj_pronunciatio": None,
        "act_obj_event": [None, None, None],
        "chatting_with": None,
        "chat": None,
        "chatting_with_buffer": {},
        "chatting_end_time": None,
        "act_path_set": True,
        "planned_path": [],
    }


def build_player_marker_scratch(
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
) -> Dict[str, object]:
    events = player_events(result)
    event = events[0] if events else {}
    event_time = str(event.get("time", "07:00"))
    event_location = str(event.get("location", "Village"))
    target = targets.get(event_location, targets.get("Village"))
    if target is None:
        target = next(iter(targets.values()))
    action = marker_action(event)
    return {
        "vision_r": 8,
        "att_bandwidth": 8,
        "retention": 8,
        "curr_time": formatted_time(event_time),
        "curr_tile": list(target.tile),
        "curr_arena": target.address.split(":")[-1],
        "curr_sector": target.address.split(":")[-2],
        "curr_address": target.address,
        "daily_plan_req": "Player event marker",
        "name": PLAYER_NAME,
        "first_name": PLAYER_NAME,
        "last_name": "",
        "age": 0,
        "innate": "Player event marker",
        "learned": "Player represents a structured intervention event in the replay.",
        "currently": action,
        "lifestyle": "Player is not a simulated autonomous NPC in this replay.",
        "living_area": target.address,
        "daily_req": ["Player event marker"],
        "f_daily_schedule": [["Player event marker", 20]],
        "f_daily_schedule_hourly_org": [["Player event marker", 20]],
        "act_address": target.address,
        "act_start_time": formatted_time(event_time),
        "act_duration": PLAYER_MARKER_HOLD_STEPS * VISUAL_STEP_MINUTES,
        "act_description": action,
        "act_pronunciatio": NPC_EMOJI[PLAYER_NAME],
        "act_event": [PLAYER_NAME, "marks", "player event"],
        "act_obj_description": None,
        "act_obj_pronunciatio": None,
        "act_obj_event": [None, None, None],
        "chatting_with": None,
        "chat": None,
        "chatting_with_buffer": {},
        "chatting_end_time": None,
        "act_path_set": True,
        "planned_path": [],
    }


def build_player_marker_nodes(result: Mapping[str, object]) -> Dict[str, object]:
    nodes: Dict[str, object] = {}
    type_counts = {"event": 0, "chat": 0, "thought": 0}
    for event in player_events(result):
        time_text = str(event.get("time", "07:00"))
        description = (
            f"At {time_text}, Player event: "
            f"{event.get('action', event.get('description', 'structured player event'))}"
        )
        add_memory_node(
            nodes,
            type_counts,
            node_type="event",
            created=parse_time_on_start_date(time_text).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            subject=PLAYER_NAME,
            predicate="triggered",
            object_value=str(event.get("affected_npc", "NPC")),
            description=description,
            filling=[],
            poignancy=1,
        )
    return nodes


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def write_persona_memory_stubs(
    output_dir: Path,
    result: Mapping[str, object],
    targets: Mapping[str, LocationTarget],
) -> List[Path]:
    written: List[Path] = []
    conversations = result["conversations"]
    for npc in result["npcs"]:
        memory_dir = (
            output_dir
            / "personas"
            / str(npc["name"])
            / "bootstrap_memory"
        )
        files = {
            memory_dir / "scratch.json": build_scratch(npc, result, targets),
            memory_dir / "spatial_memory.json": {},
            memory_dir / "associative_memory" / "nodes.json": (
                build_associative_nodes(npc, conversations)
            ),
        }
        for path, payload in files.items():
            write_json(path, payload)
            written.append(path)
    if player_events(result):
        memory_dir = (
            output_dir
            / "personas"
            / PLAYER_NAME
            / "bootstrap_memory"
        )
        files = {
            memory_dir / "scratch.json": build_player_marker_scratch(result, targets),
            memory_dir / "spatial_memory.json": {},
            memory_dir / "associative_memory" / "nodes.json": (
                build_player_marker_nodes(result)
            ),
        }
        for path, payload in files.items():
            write_json(path, payload)
            written.append(path)
    return written


def ensure_profile_placeholders(npc_names: Sequence[str]) -> List[Path]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    fallback_source = PROFILE_DIR / "Abigail_Chen.png"
    for npc_name in npc_names:
        output_path = PROFILE_DIR / f"{npc_name.replace(' ', '_')}.png"
        source_name = PROFILE_PLACEHOLDERS.get(npc_name)
        source_path = PROFILE_DIR / source_name if source_name else fallback_source
        if not source_path.exists():
            raise FileNotFoundError(f"Profile placeholder source not found: {source_path}")
        if not output_path.exists():
            shutil.copyfile(source_path, output_path)
        written.append(output_path)
    return written


def ensure_character_sprite_placeholders(npc_names: Sequence[str]) -> List[Path]:
    CHARACTER_DIR.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    fallback_source = CHARACTER_DIR / "Adam_Smith.png"
    for npc_name in npc_names:
        output_path = CHARACTER_DIR / f"{npc_name.replace(' ', '_')}.png"
        source_name = PROFILE_PLACEHOLDERS.get(npc_name)
        source_path = CHARACTER_DIR / source_name if source_name else fallback_source
        if not source_path.exists():
            raise FileNotFoundError(f"Character sprite source not found: {source_path}")
        if not output_path.exists():
            shutil.copyfile(source_path, output_path)
        written.append(output_path)
    return written


def write_demo(
    input_path: Path,
    sim_code: str,
    include_memory: bool = True,
    full_day: bool = True,
    visual_step_minutes: int = VISUAL_STEP_MINUTES,
    chat_hold_steps: int = CHAT_HOLD_STEPS,
    mapping_diagnostics: List[Dict[str, object]] | None = None,
    pathfinding_diagnostics: Dict[str, object] | None = None,
) -> Tuple[Path, Path, Dict[str, LocationTarget], Dict[str, object], Dict[str, object]]:
    result = json.loads(input_path.read_text(encoding="utf-8"))
    validate_result(result)
    write_available_addresses(load_valid_address_tiles())
    targets = build_location_targets()
    meta, movement = build_demo_payload(
        result,
        targets,
        full_day=full_day,
        visual_step_minutes=visual_step_minutes,
        chat_hold_steps=chat_hold_steps,
        mapping_diagnostics=mapping_diagnostics,
        pathfinding_diagnostics=pathfinding_diagnostics,
    )
    meta["run_info"] = build_run_info(
        result.get("metadata", {}),
        visual_steps=len(movement),
        sec_per_step=int(meta["sec_per_step"]),
    )

    output_dir = FRONTEND_DIR / "compressed_storage" / sim_code
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / "meta.json"
    movement_path = output_dir / "master_movement.json"
    conversation_timeline_path = output_dir / "conversation_timeline.json"
    write_json(meta_path, meta)
    write_json(movement_path, movement)
    conversation_timeline = build_conversation_timeline(
        result.get("conversations", []),
        visual_step_minutes if full_day else max(1, int(meta["sec_per_step"] / 60)),
        len(movement),
        hold_steps=max(chat_hold_steps, 3),
    )
    if conversation_timeline:
        write_json(conversation_timeline_path, conversation_timeline)
    if include_memory:
        write_persona_memory_stubs(output_dir, result, targets)
        ensure_profile_placeholders(meta["persona_names"])
        ensure_character_sprite_placeholders(meta["persona_names"])
    return meta_path, movement_path, targets, meta, movement


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert simulation_result.json to a Smallville compressed demo."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input simulation JSON (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--sim-code",
        default=DEFAULT_SIM_CODE,
        help=f"Output simulation code (default: {DEFAULT_SIM_CODE})",
    )
    parser.add_argument(
        "--skip-memory",
        action="store_true",
        help="Generate only meta.json and master_movement.json.",
    )
    playback_mode = parser.add_mutually_exclusive_group()
    playback_mode.add_argument(
        "--full-day",
        dest="full_day",
        action="store_true",
        default=True,
        help="Expand semantic ticks into a full 24-hour visual timeline (default).",
    )
    playback_mode.add_argument(
        "--no-full-day",
        dest="full_day",
        action="store_false",
        help="Keep one frontend step per semantic timeline tick.",
    )
    parser.add_argument(
        "--visual-step-minutes",
        type=int,
        default=VISUAL_STEP_MINUTES,
        help=f"Minutes per visual step (default: {VISUAL_STEP_MINUTES}).",
    )
    parser.add_argument(
        "--chat-hold-steps",
        type=int,
        default=CHAT_HOLD_STEPS,
        help=f"Visual steps to show each conversation (default: {CHAT_HOLD_STEPS}).",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    mapping_diagnostics: List[Dict[str, object]] = []
    pathfinding_diagnostics: Dict[str, object] = {}
    meta_path, movement_path, targets, meta, movement = write_demo(
        args.input.resolve(),
        args.sim_code,
        include_memory=not args.skip_memory,
        full_day=args.full_day,
        visual_step_minutes=args.visual_step_minutes,
        chat_hold_steps=args.chat_hold_steps,
        mapping_diagnostics=mapping_diagnostics,
        pathfinding_diagnostics=pathfinding_diagnostics,
    )
    result = json.loads(args.input.resolve().read_text(encoding="utf-8"))

    print(f"sim_code: {args.sim_code}")
    print(f"meta.json path: {meta_path}")
    print(f"master_movement.json path: {movement_path}")
    print(f"persona count: {len(meta['persona_names'])}")
    print(f"semantic tick count: {len(result['timeline'])}")
    print(f"step count: {len(movement)}")
    print(f"full-day mode: {args.full_day}")
    print(f"start time: {meta['start_time']}")
    print(f"end time: {meta['curr_time']}")
    print(f"seconds per step: {meta['sec_per_step']}")
    print(f"playback interval ms: {meta.get('playback_interval_ms', 0)}")
    address_tiles = load_valid_address_tiles()
    category_pools = build_category_pools(address_tiles)
    print(f"available address count: {len(address_tiles)}")
    print(f"available addresses path: {AVAILABLE_ADDRESSES_PATH}")
    print("category pool sizes:")
    for category, pool in category_pools.items():
        print(f"  {category}: {len(pool)}")
    print("location mappings:")
    for label, target in targets.items():
        print(f"  {label} -> {target.address} -> {list(target.tile)}")
    print(f"conversation count: {len(result['conversations'])}")
    if mapping_diagnostics:
        print("semantic location mapping v2:")
        for item in mapping_diagnostics:
            print(
                f"  {item['time']} | {item['npc']} | {item['category']} | "
                f"{item['address']} | {item['tile']} | {item['action']}"
            )
        semantic_tiles = {
            tuple(item["tile"])
            for item in mapping_diagnostics
        }
        visual_tiles = {
            tuple(state["movement"])
            for step_data in movement.values()
            for state in step_data.values()
        }
        print(f"unique semantic tiles: {len(semantic_tiles)}")
        print(f"unique visual tiles: {len(visual_tiles)}")
    if pathfinding_diagnostics:
        print("pathfinding movement:")
        for key in (
            "algorithm",
            "transition_count",
            "same_tile_count",
            "path_found_count",
            "bfs_4_count",
            "bfs_8_count",
            "fallback_count",
            "maximum_step_manhattan_distance",
            "unique_visual_movement_tiles",
        ):
            print(f"  {key}: {pathfinding_diagnostics[key]}")
        if pathfinding_diagnostics["maximum_step_jump"]:
            print(
                "  maximum_step_jump: "
                + json.dumps(
                    pathfinding_diagnostics["maximum_step_jump"],
                    ensure_ascii=False,
                )
            )
        print("  transitions:")
        for transition in pathfinding_diagnostics["transitions"]:
            print(
                f"    {transition['npc']} | {transition['start_time']} -> "
                f"{transition['end_time']} | {transition['algorithm']} | "
                f"path length {transition['path_length']} | "
                f"{transition['start_tile']} -> {transition['end_tile']}"
            )
    if not args.skip_memory:
        print(
            "persona memory root: "
            f"{meta_path.parent / 'personas'}"
        )
        print(f"profile placeholders: {len(meta['persona_names'])}")
    print("first step preview:")
    print(json.dumps(movement["0"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
