import datetime
import json
from pathlib import Path

from .npc_memory import ALLOWED_MEMORY_NPCS, project_root
from .world_state import get_current_world_time


DEFAULT_LOCATIONS = {
  "Mira Chen": "Home",
  "Tovan Reed": "Home",
  "Lysa Vale": "Inn",
}

MOVEMENT_TILES_PER_10_MINUTES = 12


def npc_spatial_state_path():
  return project_root() / "experiments" / "player_intervention" / "world_state" / "npc_spatial_state.json"


def _default_entry(npc_name):
  world_time = get_current_world_time()
  return {
    "current_location": DEFAULT_LOCATIONS.get(npc_name, "Village"),
    "current_tile": None,
    "target_location": None,
    "target_tile": None,
    "current_action": None,
    "movement_status": "idle",
    "from_location": None,
    "route": [],
    "route_index": 0,
    "route_progress": 0,
    "movement_start_time": None,
    "estimated_arrival_time": None,
    "world_day": world_time["day"],
    "world_time": world_time["time"],
  }


def default_spatial_state():
  return {npc: _default_entry(npc) for npc in sorted(ALLOWED_MEMORY_NPCS)}


def load_npc_spatial_state():
  path = npc_spatial_state_path()
  if not path.is_file():
    return default_spatial_state()
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return default_spatial_state()
  if not isinstance(payload, dict):
    return default_spatial_state()
  state = default_spatial_state()
  for npc, entry in payload.items():
    if isinstance(entry, dict):
      merged = _default_entry(npc)
      merged.update(entry)
      state[npc] = merged
  return state


def save_npc_spatial_state(state):
  path = npc_spatial_state_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
  return state


def reset_npc_spatial_movements(world_day=1, world_time="08:00"):
  state = load_npc_spatial_state()
  for npc, entry in state.items():
    entry["target_location"] = None
    entry["target_tile"] = None
    entry["current_action"] = None
    entry["current_location"] = DEFAULT_LOCATIONS.get(npc, entry.get("current_location") or "Village")
    entry["from_location"] = None
    entry["movement_status"] = "idle"
    entry["route"] = []
    entry["route_index"] = 0
    entry["route_progress"] = 0
    entry["movement_start_time"] = None
    entry["estimated_arrival_time"] = None
    entry["source_memory_id"] = ""
    entry["world_day"] = int(world_day or 1)
    entry["world_time"] = str(world_time or "08:00")
    entry["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    state[npc] = entry
  return save_npc_spatial_state(state)


def bootstrap_spatial_state_from_replay(raw_all_movement, world_state=None):
  state = load_npc_spatial_state()
  changed = False
  world_time = get_current_world_time()
  first_step = raw_all_movement.get("0", {}) if isinstance(raw_all_movement, dict) else {}
  for npc in sorted(ALLOWED_MEMORY_NPCS):
    entry = state.get(npc, _default_entry(npc))
    if entry.get("current_tile"):
      continue
    replay_record = first_step.get(npc, {}) if isinstance(first_step, dict) else {}
    movement = replay_record.get("movement") if isinstance(replay_record, dict) else None
    if isinstance(movement, list) and len(movement) >= 2:
      entry["current_tile"] = [int(movement[0]), int(movement[1])]
      description = str(replay_record.get("description", ""))
      if "@" in description:
        entry["current_address"] = description.split("@", 1)[1].strip()
      entry["world_day"] = world_time["day"]
      entry["world_time"] = world_time["time"]
      state[npc] = entry
      changed = True
  if changed:
    save_npc_spatial_state(state)
  return state


def _progress_for_route(route, route_index):
  if not route:
    return 100
  if len(route) == 1:
    return 100
  return int(round((max(0, route_index) / (len(route) - 1)) * 100))


def _time_to_minutes(time_text):
  try:
    hour_text, minute_text = str(time_text or "00:00").split(":", 1)
    return int(hour_text) * 60 + int(minute_text)
  except (TypeError, ValueError):
    return 0


def _minutes_to_time(total_minutes):
  total_minutes = max(0, int(total_minutes)) % (24 * 60)
  return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _estimated_arrival_time(start_time, route):
  route_len = max(1, len(route or []))
  route_steps = max(0, route_len - 1)
  ticks_needed = max(1, int((route_steps + MOVEMENT_TILES_PER_10_MINUTES - 1) / MOVEMENT_TILES_PER_10_MINUTES))
  minutes_needed = ticks_needed * 10
  return _minutes_to_time(_time_to_minutes(start_time) + minutes_needed)


def start_spatial_movement(action_state, route_payload):
  state = load_npc_spatial_state()
  npc = action_state.get("npc") or route_payload.get("npc")
  if not npc:
    return state
  current_world_time = get_current_world_time()
  world_day = action_state.get("world_day") or current_world_time["day"]
  world_time_text = action_state.get("world_time") or current_world_time["time"]
  route = route_payload.get("route") or []
  route_index = 0
  entry = state.get(npc, _default_entry(npc))
  entry.update(
    {
      "current_location": entry.get("current_location") or route_payload.get("location"),
      "current_tile": route_payload.get("start_tile") or entry.get("current_tile"),
      "target_location": route_payload.get("target_location") or route_payload.get("location"),
      "target_address": route_payload.get("target_address"),
      "target_tile": route_payload.get("target_tile"),
      "current_action": action_state.get("action") or route_payload.get("action"),
      "movement_status": "moving" if route else "idle",
      "from_location": action_state.get("from_location") or entry.get("current_location"),
      "route": route,
      "route_index": route_index,
      "route_progress": _progress_for_route(route, route_index),
      "movement_start_time": world_time_text,
      "estimated_arrival_time": _estimated_arrival_time(world_time_text, route) if route else None,
      "source_memory_id": action_state.get("source_memory_id", ""),
      "world_day": world_day,
      "world_time": world_time_text,
      "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
  )
  state[npc] = entry
  return save_npc_spatial_state(state)


def advance_spatial_movements(step_minutes=10, world_day=None, world_time_text=None):
  state = load_npc_spatial_state()
  current_world_time = get_current_world_time()
  world_day = world_day if world_day is not None else current_world_time["day"]
  world_time_text = world_time_text or current_world_time["time"]
  arrivals = []
  changed = False
  try:
    minutes = max(1, int(step_minutes or 10))
  except (TypeError, ValueError):
    minutes = 10
  route_increment = max(1, int(round((minutes / 10.0) * MOVEMENT_TILES_PER_10_MINUTES)))
  for npc, entry in state.items():
    if entry.get("movement_status") != "moving":
      continue
    route = entry.get("route") or []
    if not route:
      entry["movement_status"] = "idle"
      changed = True
      continue
    route_index = int(entry.get("route_index") or 0)
    next_index = min(route_index + route_increment, len(route) - 1)
    entry["route_index"] = next_index
    entry["current_tile"] = route[next_index]
    entry["route_progress"] = _progress_for_route(route, next_index)
    entry["world_day"] = world_day
    entry["world_time"] = world_time_text
    entry["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if next_index >= len(route) - 1:
      entry["movement_status"] = "completed"
      entry["current_location"] = entry.get("target_location")
      entry["estimated_arrival_time"] = world_time_text
      arrivals.append(
        {
          "npc": npc,
          "action": entry.get("current_action", ""),
          "target_location": entry.get("target_location", ""),
          "target_tile": entry.get("target_tile"),
          "source_memory_id": entry.get("source_memory_id", ""),
          "world_day": world_day,
          "world_time": world_time_text,
        }
      )
    state[npc] = entry
    changed = True
  if changed:
    save_npc_spatial_state(state)
  return state, arrivals


def arrival_observation_text(npc, target_location):
  if target_location:
    return f"{npc} arrived at {target_location}."
  return f"{npc} arrived at the scheduled destination."
