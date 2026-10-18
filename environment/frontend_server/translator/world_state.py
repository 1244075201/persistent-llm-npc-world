import datetime
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from .npc_memory import (
  ALLOWED_MEMORY_NPCS,
  clear_live_interaction_memory,
  load_npc_memory,
  load_observations,
  load_reflections,
  project_root,
)


def world_state_dir():
  return project_root() / "experiments" / "player_intervention" / "world_state"


def agent_config_dir():
  return project_root() / "experiments" / "configs" / "agent_ablation"


def world_state_path():
  return world_state_dir() / "world.json"


def world_canon_path():
  return world_state_dir() / "canon.json"


def npc_beliefs_path():
  return world_state_dir() / "npc_beliefs.json"


def default_world_canon():
  return {
    "locations": {
      "Home": {"description": "Residential area for village residents", "available_items": [], "known_npcs": []},
      "Inn": {"description": "Village lodging and rest area", "available_items": [], "known_npcs": ["Lysa Vale"]},
      "Tea Shop": {"description": "Village tea shop and social gathering place", "available_items": ["tea"], "known_npcs": ["Mira Chen"]},
      "Market": {"description": "Village trading area", "available_items": ["grain", "tea", "cloth"], "known_npcs": ["Lysa Vale"]},
      "Guard Post": {"description": "Village security post", "available_items": [], "known_npcs": ["Tovan Reed"]},
      "Forest": {"description": "Mountain forest outside the village", "available_items": ["herbs", "wood"], "known_npcs": []},
    },
    "items": {
      "grain": {"category": "food", "location": "Market", "quantity": 30},
      "tea": {"category": "drink", "location": "Tea Shop", "quantity": 25},
      "cloth": {"category": "trade_good", "location": "Market", "quantity": 12},
      "herbs": {"category": "medicine", "location": "Forest", "quantity": 20},
      "wood": {"category": "material", "location": "Forest", "quantity": 40},
    },
    "trade_routes": {
      "north_route": {"status": "unstable", "connects": ["Market", "Forest"]},
      "south_route": {"status": "active", "connects": ["Market"]},
    },
    "facts": {
      "hidden_ruins": {
        "truth": "Ancient ruins exist in the forest.",
        "location": "Forest",
        "visibility": ["Elder", "Shrine Keeper"],
      },
      "market_sells_tea": {
        "truth": "The market sells tea.",
        "location": "Market",
        "visibility": ["Lysa Vale"],
      },
    },
  }


def load_world_canon():
  path = world_canon_path()
  if not path.is_file():
    return default_world_canon()
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return default_world_canon()
  if not isinstance(payload, dict):
    return default_world_canon()
  canon = default_world_canon()
  for key in ("locations", "items", "trade_routes", "facts"):
    if isinstance(payload.get(key), dict):
      merged = dict(canon.get(key, {}))
      merged.update(payload.get(key, {}))
      canon[key] = merged
  return canon


def default_npc_beliefs():
  return {
    "Lysa Vale": {
      "known_facts": [
        {
          "fact_id": "market_sells_tea",
          "content": "The market sells tea.",
          "source": "market_experience",
          "source_type": "observation",
          "confidence": "high",
        },
        {
          "fact_id": "north_route_unstable",
          "content": "The northern trade route is unstable.",
          "source": "vendor_conversation",
          "source_type": "conversation",
          "confidence": "medium",
        },
      ],
    },
    "Mira Chen": {
      "known_facts": [
        {
          "fact_id": "tea_shop_sells_tea",
          "content": "The tea shop serves tea.",
          "source": "workplace_knowledge",
          "source_type": "observation",
          "confidence": "high",
        }
      ],
    },
    "Tovan Reed": {
      "known_facts": [
        {
          "fact_id": "guard_post_security",
          "content": "The guard post is the village security post.",
          "source": "workplace_knowledge",
          "source_type": "observation",
          "confidence": "high",
        }
      ],
    },
    "Elder": {
      "known_facts": [
        {
          "fact_id": "hidden_ruins",
          "content": "Ancient ruins exist in the forest.",
          "source": "village_lore",
          "source_type": "world_fact",
          "confidence": "high",
        }
      ],
    },
  }


def load_npc_beliefs():
  path = npc_beliefs_path()
  if not path.is_file():
    return default_npc_beliefs()
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return default_npc_beliefs()
  if not isinstance(payload, dict):
    return default_npc_beliefs()
  beliefs = default_npc_beliefs()
  for npc_name, npc_payload in payload.items():
    if not isinstance(npc_payload, dict):
      continue
    known_facts = npc_payload.get("known_facts", [])
    if isinstance(known_facts, list):
      beliefs[npc_name] = {"known_facts": [item for item in known_facts if isinstance(item, dict)]}
  return beliefs


def load_npc_belief(npc_name):
  return load_npc_beliefs().get(npc_name, {"known_facts": []})


def default_agent_config():
  return {
    "name": "full_agent",
    "use_memory": True,
    "use_knowledge": True,
    "use_relationship": True,
    "use_world_grounding": True,
    "use_belief": True,
  }


def normalize_agent_config(payload, requested_name=""):
  config = default_agent_config()
  if isinstance(payload, dict):
    config.update(payload)
  if requested_name and not config.get("name"):
    config["name"] = requested_name
  for key in ("use_memory", "use_knowledge", "use_relationship", "use_world_grounding", "use_belief"):
    config[key] = bool(config.get(key))
  if not config.get("name"):
    config["name"] = "full_agent"
  return config


def load_agent_config(config_name=None):
  requested_name = str(config_name or os.environ.get("AGENT_ABLATION_CONFIG", "") or "full_agent").strip()
  safe_name = "".join(ch for ch in requested_name if ch.isalnum() or ch in {"_", "-"}).strip()
  if not safe_name:
    safe_name = "full_agent"
  path = agent_config_dir() / f"{safe_name}.json"
  fallback_path = agent_config_dir() / "full_agent.json"
  for candidate in (path, fallback_path):
    try:
      payload = json.loads(candidate.read_text(encoding="utf-8"))
      return normalize_agent_config(payload, requested_name=safe_name)
    except (OSError, json.JSONDecodeError):
      continue
  return default_agent_config()


def planner_debug_dir():
  return (
    project_root()
    / "experiments"
    / "player_intervention"
    / "player_intervention_summary_20260709_070418"
    / "debug"
  )


def llm_planner_raw_response_latest_path():
  return planner_debug_dir() / "llm_planner_raw_response_latest.json"


def save_llm_planner_raw_response(payload):
  path = llm_planner_raw_response_latest_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  return str(path)


def knowledge_interpretation_trace_path():
  return planner_debug_dir() / "knowledge_interpretation_trace.jsonl"


def trace_knowledge_interpretation(event, **payload):
  trace_payload = {
    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    "event": event,
  }
  trace_payload.update(payload)
  path = knowledge_interpretation_trace_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(trace_payload, ensure_ascii=False) + "\n")
  return str(path)


def relationship_debug_log_path():
  return planner_debug_dir() / "relationship_memory_trace.jsonl"


def trace_relationship_memory(trace_event, **payload):
  trace_payload = {
    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    "event": trace_event,
  }
  trace_payload.update(payload)
  path = relationship_debug_log_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(trace_payload, ensure_ascii=False) + "\n")
  return str(path)


def relationship_reasoning_trace_path():
  return planner_debug_dir() / "relationship_reasoning_trace.jsonl"


def trace_relationship_reasoning(trace_event, **payload):
  trace_payload = {
    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    "event": trace_event,
  }
  trace_payload.update(payload)
  path = relationship_reasoning_trace_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(trace_payload, ensure_ascii=False) + "\n")
  return str(path)


def default_simulation_result_path():
  return project_root() / "reverie" / "backend_server" / "simulation_result.json"


def default_npc_persistent_locations():
  return {
    "Mira Chen": {
      "home": "Home",
      "workplace": "Tea Shop",
    },
    "Tovan Reed": {
      "home": "Home",
      "workplace": "Guard Post",
    },
    "Lysa Vale": {
      "home": "Inn",
      "workplace": "Market",
    },
  }


def default_world_state():
  return {
    "current_day": 1,
    "current_time": "07:00",
    "time_step_minutes": 60,
    "last_tick": "",
    "completed_events": [],
    "recent_observations": [],
    "active_requests": [],
    "npc_schedules": [],
    "npc_daily_plans": {},
    "npc_goals": {},
    "npc_knowledge": {},
    "npc_relationships": {},
    "planner_mode": "deterministic",
    "active_actions": [],
    "completed_actions": [],
    "previous_days": [],
    "previous_day_summary": [],
    "npc_persistent_locations": default_npc_persistent_locations(),
    "time_catchup_log": [],
  }


def load_world_state():
  path = world_state_path()
  if not path.is_file():
    return default_world_state()
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return default_world_state()
  if not isinstance(payload, dict):
    return default_world_state()
  state = default_world_state()
  state.update(payload)
  for key in (
      "completed_events",
      "recent_observations",
      "active_requests",
      "active_actions",
      "completed_actions",
      "previous_days"):
    if not isinstance(state.get(key), list):
      state[key] = []
  if not isinstance(state.get("npc_schedules"), (list, dict)):
    state["npc_schedules"] = []
  if not isinstance(state.get("npc_daily_plans"), dict):
    state["npc_daily_plans"] = {}
  if not isinstance(state.get("npc_goals"), dict):
    state["npc_goals"] = {}
  if not isinstance(state.get("npc_knowledge"), dict):
    state["npc_knowledge"] = {}
  if not isinstance(state.get("npc_relationships"), dict):
    state["npc_relationships"] = {}
  if state.get("planner_mode") not in {"deterministic", "llm"}:
    state["planner_mode"] = "deterministic"
  if not isinstance(state.get("npc_persistent_locations"), dict):
    state["npc_persistent_locations"] = default_npc_persistent_locations()
  else:
    locations = default_npc_persistent_locations()
    locations.update(state.get("npc_persistent_locations", {}))
    state["npc_persistent_locations"] = locations
  if not isinstance(state.get("previous_day_summary"), list):
    state["previous_day_summary"] = []
  if not isinstance(state.get("time_catchup_log"), list):
    state["time_catchup_log"] = []
  try:
    state["current_day"] = int(state.get("current_day") or 1)
  except (TypeError, ValueError):
    state["current_day"] = 1
  try:
    state["time_step_minutes"] = int(state.get("time_step_minutes") or 60)
  except (TypeError, ValueError):
    state["time_step_minutes"] = 60
  if not state.get("current_time"):
    state["current_time"] = "08:00"
  return state


def save_world_state(state):
  path = world_state_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
  return state


def daily_plan_key(day):
  return f"day_{int(day or 1)}"


def normalize_schedule_collection(schedule_payload):
  if isinstance(schedule_payload, dict):
    normalized = {}
    for npc, items in schedule_payload.items():
      if not isinstance(items, list):
        continue
      clean_items = []
      for item in items:
        if not isinstance(item, dict):
          continue
        time_text = normalize_schedule_time(item.get("time") or item.get("start_time"))
        action = str(item.get("action") or item.get("description") or item.get("activity") or "").strip()
        location = str(item.get("location") or item.get("address") or "").strip()
        if time_text and action:
          clean_items.append(
            {
              "time": time_text,
              "action": action,
              "location": location,
            }
          )
      if clean_items:
        normalized[str(npc)] = clean_items
    return normalized
  if isinstance(schedule_payload, list):
    normalized = {}
    for item in schedule_payload:
      if not isinstance(item, dict):
        continue
      npc = str(item.get("npc") or item.get("npc_name") or "").strip()
      time_text = normalize_schedule_time(item.get("time") or item.get("start_time"))
      action = str(item.get("action") or item.get("description") or item.get("activity") or "").strip()
      location = str(item.get("location") or item.get("address") or "").strip()
      if npc and time_text and action:
        normalized.setdefault(npc, []).append(
          {
            "time": time_text,
            "action": action,
            "location": location,
          }
        )
    return normalized
  return {}


def bootstrap_npc_schedules(simulation_result_path=None, force=False):
  state = load_world_state()
  existing = normalize_schedule_collection(state.get("npc_schedules", []))
  if existing and not force:
    return state
  source_path = Path(simulation_result_path) if simulation_result_path else default_simulation_result_path()
  if not source_path.is_file():
    return state
  try:
    result = json.loads(source_path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return state
  schedules = {}
  for tick in result.get("timeline", []):
    if not isinstance(tick, dict):
      continue
    time_text = normalize_schedule_time(tick.get("time"))
    if not time_text:
      continue
    for item in tick.get("states", []):
      if not isinstance(item, dict):
        continue
      npc = str(item.get("npc") or "").strip()
      action = str(item.get("action") or "").strip()
      location = str(item.get("location") or "").strip()
      if not npc or not action:
        continue
      schedule_item = {
        "time": time_text,
        "action": action,
        "location": location,
        "source": "simulation_result_timeline",
      }
      bucket = schedules.setdefault(npc, [])
      if not any(
          existing_item.get("time") == time_text
          and existing_item.get("action") == action
          for existing_item in bucket):
        bucket.append(schedule_item)
  if not schedules:
    return state
  state["npc_schedules"] = schedules
  state["npc_schedule_source"] = str(source_path)
  state["npc_schedule_bootstrapped_at"] = datetime.datetime.now().isoformat(timespec="seconds")
  return save_world_state(state)


def time_to_minutes(time_text):
  try:
    hour_text, minute_text = str(time_text or "00:00").split(":", 1)
    return int(hour_text) * 60 + int(minute_text)
  except (TypeError, ValueError):
    return 0


def minutes_to_time(total_minutes):
  total_minutes = max(0, int(total_minutes))
  hour = total_minutes // 60
  minute = total_minutes % 60
  return f"{hour:02d}:{minute:02d}"


def get_current_world_time():
  state = load_world_state()
  day = int(state.get("current_day") or 1)
  time_text = str(state.get("current_time") or "08:00")
  return {
    "day": day,
    "time": time_text,
    "display": f"Day {day} {time_text}",
  }


def record_world_time_display(record):
  if not isinstance(record, dict):
    return ""
  world_day = record.get("world_day") or record.get("completed_world_day")
  world_time = record.get("world_time") or record.get("completed_world_time")
  if world_day and world_time:
    return f"Day {world_day} {world_time}"
  time_text = str(record.get("time") or record.get("completed_time") or "").strip()
  if time_text.startswith("Day "):
    return time_text
  return ""


def build_time_consistency_warnings(
    current_world_time,
    live_memories=None,
    live_reflections=None,
    live_observations=None,
    npc_knowledge=None,
    active_actions=None,
    completed_actions=None,
    relationship_memories=None,
    max_warnings=12):
  reference = current_world_time or get_current_world_time()
  reference_display = str(reference.get("display") or "").strip()
  warnings = []

  def add_warning(label, item):
    if len(warnings) >= max_warnings or not isinstance(item, dict):
      return
    item_time = record_world_time_display(item)
    if not item_time:
      if item.get("legacy_replay_time") or item.get("time") or item.get("completed_time"):
        warnings.append(
          f"{label} has no structured world_day/world_time; display should treat its time as legacy/debug only."
        )
      return
    if reference_display and item_time != reference_display:
      warnings.append(f"{label} timestamp {item_time} differs from current world time {reference_display}.")

  for memory in live_memories or []:
    add_warning("Live memory", memory)
  for reflection in live_reflections or []:
    add_warning("Reflection", reflection)
  for observation in live_observations or []:
    add_warning("Observation", observation)
  for knowledge in npc_knowledge or []:
    add_warning("NPC knowledge", knowledge)
  for action in active_actions or []:
    add_warning("Active action", action)
  for action in completed_actions or []:
    add_warning("Completed action", action)
  for memory in relationship_memories or []:
    add_warning("Relationship memory", memory)
  return warnings


def timed_summary_line(prefix, item, text_key="content"):
  text = str(item.get(text_key, "")).strip()
  if not text:
    return ""
  world_time = str(item.get("world_time") or "").strip()
  world_day = item.get("world_day")
  if world_time:
    if world_day:
      return f"Day {world_day} {world_time} {prefix}: {text}"
    return f"{world_time} {prefix}: {text}"
  legacy_time = str(item.get("time") or item.get("completed_time") or "").strip()
  if legacy_time:
    return f"{prefix}: {text} (legacy replay time: {legacy_time})"
  return f"{prefix}: {text}"


def normalize_schedule_time(time_text):
  text = str(time_text or "").strip()
  if not text:
    return ""
  try:
    hour_text, minute_text = text.split(":", 1)
    return f"{int(hour_text):02d}:{int(minute_text):02d}"
  except (TypeError, ValueError):
    return ""


def extract_npc_schedule(planning_result):
  if not planning_result:
    return []
  if isinstance(planning_result, dict):
    if any(isinstance(value, list) for value in planning_result.values()):
      schedule = []
      for npc, items in planning_result.items():
        if not isinstance(items, list):
          continue
        for item in items:
          if not isinstance(item, dict):
            continue
          time_text = normalize_schedule_time(item.get("time") or item.get("start_time"))
          action = str(item.get("action") or item.get("description") or item.get("activity") or "").strip()
          location = str(item.get("location") or item.get("address") or "").strip()
          if npc and time_text and action:
            schedule_item = dict(item)
            schedule_item.update(
              {
                "npc": str(npc),
                "time": time_text,
                "action": action,
                "location": location,
              }
            )
            schedule.append(schedule_item)
      return schedule
    raw_items = (
      planning_result.get("schedule")
      or planning_result.get("daily_schedule")
      or planning_result.get("actions")
      or planning_result.get("plan")
      or []
    )
    default_npc = planning_result.get("npc", "")
  elif isinstance(planning_result, list):
    raw_items = planning_result
    default_npc = ""
  else:
    return []
  if isinstance(raw_items, dict):
    raw_items = [
      {"time": key, **(value if isinstance(value, dict) else {"action": value})}
      for key, value in raw_items.items()
    ]
  if not isinstance(raw_items, list):
    return []
  schedule = []
  for item in raw_items:
    if not isinstance(item, dict):
      continue
    time_text = normalize_schedule_time(item.get("time") or item.get("start_time"))
    action = str(item.get("action") or item.get("description") or item.get("activity") or "").strip()
    npc = str(item.get("npc") or item.get("npc_name") or default_npc or "").strip()
    location = str(item.get("location") or item.get("address") or "").strip()
    if not npc or not time_text or not action:
      continue
    schedule_item = dict(item)
    schedule_item.update(
      {
        "npc": npc,
        "time": time_text,
        "action": action,
        "location": location,
      }
    )
    schedule.append(schedule_item)
  return schedule


def _memory_text(items, *keys):
  chunks = []
  for item in items:
    for key in keys:
      text = str(item.get(key, "")).strip()
      if text:
        chunks.append(text)
  return " ".join(chunks).lower()


def npc_profile(npc_name, state=None):
  locations = default_npc_persistent_locations()
  if state and isinstance(state.get("npc_persistent_locations"), dict):
    merged = default_npc_persistent_locations()
    merged.update(state.get("npc_persistent_locations", {}))
    locations = merged
  profile_locations = locations.get(npc_name, {})
  profiles = {
    "Mira Chen": {
      "personality": "Warm, practical, community-minded tea shop owner.",
      "goals": [
        "Keep the tea shop running smoothly.",
        "Maintain friendly relationships with customers.",
        "Help with local market information when it does not disrupt her responsibilities.",
      ],
    },
    "Tovan Reed": {
      "personality": "Observant, steady, protective village guard.",
      "goals": [
        "Keep public spaces orderly.",
        "Follow up on suspicious or uncertain reports.",
        "Balance patrol duties with calm communication.",
      ],
    },
    "Lysa Vale": {
      "personality": "Curious, trade-focused, socially aware merchant.",
      "goals": [
        "Track merchant activity and trade conditions.",
        "Maintain useful relationships with market vendors.",
        "Notice disruptions that affect commerce.",
      ],
    },
  }
  profile = profiles.get(
    npc_name,
    {
      "personality": "A grounded village resident with normal daily responsibilities.",
      "goals": ["Maintain a normal routine.", "Respond to relevant local events."],
    },
  )
  profile = dict(profile)
  profile["home"] = profile_locations.get("home", "Home")
  profile["workplace"] = profile_locations.get("workplace", "Village")
  return profile


def _summarize_items(items, keys):
  lines = []
  for item in items:
    if not isinstance(item, dict):
      continue
    parts = []
    for key in keys:
      text = str(item.get(key, "")).strip()
      if text:
        parts.append(text)
    if parts:
      lines.append(" / ".join(parts))
  return lines


def deduplicate_context_items(items, key_fields, max_items=None):
  seen = set()
  deduped_reversed = []
  for item in reversed(items or []):
    if not isinstance(item, dict):
      continue
    key = tuple(str(item.get(field, "")).strip().lower() for field in key_fields)
    if key in seen:
      continue
    seen.add(key)
    deduped_reversed.append(item)
    if max_items and len(deduped_reversed) >= max_items:
      break
  return list(reversed(deduped_reversed))


def goal_id_for_memory(npc_name, memory):
  memory_id = str(memory.get("id") or memory.get("memory_id") or "").strip()
  if memory_id:
    return f"goal_{memory_id}"
  topic = str(memory.get("topic") or "request").strip().lower().replace(" ", "_")
  topic = "".join(ch for ch in topic if ch.isalnum() or ch == "_") or "request"
  npc_key = npc_name.replace(" ", "_")
  return f"goal_{npc_key}_{topic}"


def infer_goal_from_memory(npc_name, memory):
  text = " ".join(
    [
      str(memory.get("content", "")),
      str(memory.get("action", "")),
      str(memory.get("topic", "")),
    ]
  ).lower()
  source_memory_id = str(memory.get("id") or memory.get("memory_id") or "").strip()
  if any(term in text for term in ("market", "vendor", "vendors", "stall", "merchant")):
    return {
      "id": goal_id_for_memory(npc_name, memory),
      "goal": "Investigate market conditions",
      "source": "player_request",
      "source_memory_id": source_memory_id,
      "reason": str(memory.get("content") or "Player asked for market information.").strip(),
      "target_location": "Market",
      "location": "Market",
      "actions": ["talk to vendors", "collect market information"],
      "priority": "medium",
      "deadline": "tomorrow",
      "status": str(memory.get("status") or "pending").strip().lower() or "pending",
    }
  if any(term in text for term in ("suspicious", "rumor", "uncertain", "report")):
    return {
      "id": goal_id_for_memory(npc_name, memory),
      "goal": "Verify reported information",
      "source": "player_request",
      "source_memory_id": source_memory_id,
      "reason": str(memory.get("content") or "Player shared an uncertain report.").strip(),
      "target_location": "Market" if "market" in text else "Guard Post",
      "location": "Market" if "market" in text else "Guard Post",
      "actions": ["check the reported information", "ask nearby witnesses"],
      "priority": "medium",
      "deadline": "tomorrow",
      "status": str(memory.get("status") or "pending").strip().lower() or "pending",
    }
  if any(term in text for term in ("crate", "blocked", "missing", "lost", "object", "disruption")):
    return {
      "id": goal_id_for_memory(npc_name, memory),
      "goal": "Investigate reported disruption",
      "source": "player_request",
      "source_memory_id": source_memory_id,
      "reason": str(memory.get("content") or "Player reported a local disruption.").strip(),
      "target_location": "Market" if "market" in text else "Village",
      "location": "Market" if "market" in text else "Village",
      "actions": ["inspect the affected area", "resolve the disruption if possible"],
      "priority": "medium",
      "deadline": "tomorrow",
      "status": str(memory.get("status") or "pending").strip().lower() or "pending",
    }
  return {
    "id": goal_id_for_memory(npc_name, memory),
    "goal": "Follow up on player request",
    "source": "player_request",
    "source_memory_id": source_memory_id,
    "reason": str(memory.get("content") or "Player made a request.").strip(),
    "target_location": str(memory.get("location") or memory.get("target_location") or "Village").strip() or "Village",
    "location": str(memory.get("location") or memory.get("target_location") or "Village").strip() or "Village",
    "actions": [str(memory.get("action") or "follow up on the request").strip()],
    "priority": "medium",
    "deadline": "tomorrow",
    "status": str(memory.get("status") or "pending").strip().lower() or "pending",
  }


def extract_player_goals(npc_name, completed_requests=None, pending_requests=None, recent_memories=None):
  candidate_memories = []
  candidate_memories.extend(pending_requests or [])
  candidate_memories.extend(completed_requests or [])
  for memory in recent_memories or []:
    memory_type = str(memory.get("type", "")).lower()
    if memory_type in {"request", "report"}:
      candidate_memories.append(memory)
  goals = []
  seen = set()
  for memory in candidate_memories:
    if not isinstance(memory, dict):
      continue
    goal = infer_goal_from_memory(npc_name, memory)
    if memory.get("completed_time"):
      goal["completed_time"] = memory.get("completed_time", "")
    if memory.get("completed_world_day"):
      goal["completed_world_day"] = memory.get("completed_world_day", "")
    if memory.get("completed_world_time"):
      goal["completed_world_time"] = memory.get("completed_world_time", "")
    goal_key = goal.get("id") or (goal.get("goal"), goal.get("reason"))
    if goal_key in seen:
      continue
    seen.add(goal_key)
    goals.append(goal)
  return goals


def sync_npc_goals_from_memory(npc_name, state=None, save=True):
  state = state or load_world_state()
  memories = deduplicate_context_items(load_npc_memory(npc_name), ["type", "content"], max_items=None)
  completed_requests = [
    memory for memory in memories
    if str(memory.get("type", "")).lower() == "request"
    and str(memory.get("status", "")).lower() == "completed"
  ]
  pending_requests = [
    memory for memory in memories
    if str(memory.get("type", "")).lower() in {"request", "report"}
    and str(memory.get("status", "")).lower() == "pending"
  ]
  extracted_goals = extract_player_goals(
    npc_name,
    completed_requests=completed_requests[-5:],
    pending_requests=pending_requests,
    recent_memories=memories[-5:],
  )
  npc_goals = state.get("npc_goals", {})
  existing = {
    str(goal.get("id") or ""): goal
    for goal in npc_goals.get(npc_name, [])
    if isinstance(goal, dict)
  }
  for goal in extracted_goals:
    existing_goal = existing.get(goal.get("id", ""))
    if existing_goal:
      merged = dict(existing_goal)
      merged.update(goal)
      existing[goal.get("id", "")] = merged
    else:
      existing[goal.get("id", "")] = goal
  npc_goals[npc_name] = list(existing.values())
  state["npc_goals"] = npc_goals
  if save:
    save_world_state(state)
  return npc_goals.get(npc_name, [])


def active_npc_goals(npc_name, state=None):
  state = state or load_world_state()
  goals = state.get("npc_goals", {}).get(npc_name, [])
  return [
    goal for goal in goals
    if isinstance(goal, dict)
    and str(goal.get("status", "pending")).lower() == "pending"
  ]


def knowledge_id_for_result(npc_name, action_text, source_memory_id=""):
  npc_key = npc_name.replace(" ", "_")
  if source_memory_id:
    suffix = str(source_memory_id).replace("request_", "")
    return f"knowledge_{suffix}"
  topic = "task"
  lowered = str(action_text or "").lower()
  if "market" in lowered or "vendor" in lowered or "merchant" in lowered:
    topic = "market"
  elif "guard" in lowered or "patrol" in lowered:
    topic = "guard"
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  return f"knowledge_{npc_key}_{topic}_{timestamp}"


def task_result_findings_for_action(action_text, location=""):
  lowered = " ".join([str(action_text or ""), str(location or "")]).lower()
  findings = []
  if "ask vendor" in lowered or "ask vendors" in lowered or "talk with vendor" in lowered or "talk to vendor" in lowered:
    findings.extend(["Talked to vendors", "Collected market information from vendors"])
  elif "market" in lowered and ("investigate" in lowered or "review" in lowered or "collect" in lowered):
    findings.extend(["Investigated market conditions", "Collected market information"])
  elif "help player" in lowered or "assist" in lowered or "favor" in lowered or "favour" in lowered:
    findings.append("Provided requested assistance")
  elif "investigate" in lowered or "check" in lowered or "verify" in lowered:
    findings.append("Collected observations about the reported target")
  elif "talk" in lowered or "ask" in lowered or "collect information" in lowered:
    findings.append("Collected information through conversation")
  return findings


def completed_player_goal_for_action(state, npc_name, source_memory_id="", action_text=""):
  goals = sync_npc_goals_from_memory(npc_name, state=state, save=True)
  for goal in goals:
    if not isinstance(goal, dict):
      continue
    if str(goal.get("source", "")).lower() != "player_request":
      continue
    if str(goal.get("status", "")).lower() != "completed":
      continue
    if source_memory_id and source_memory_id == str(goal.get("source_memory_id") or ""):
      return goal
  action_terms = knowledge_keywords(action_text)
  for goal in goals:
    if not isinstance(goal, dict):
      continue
    if str(goal.get("source", "")).lower() != "player_request":
      continue
    if str(goal.get("status", "")).lower() != "completed":
      continue
    goal_text = " ".join(
      [
        str(goal.get("goal", "")),
        str(goal.get("target_location", "")),
        " ".join(str(action) for action in goal.get("actions", []) if action),
      ]
    )
    if action_terms and action_terms.intersection(knowledge_keywords(goal_text)):
      return goal
  return {}


def relationship_memory_id(npc_name, source_memory_id="", goal_text=""):
  source_id = str(source_memory_id or "").strip()
  if source_id:
    return f"relationship_{source_id}"
  topic = "_".join(sorted(knowledge_keywords(goal_text))[:4]) or "player_interaction"
  npc_key = str(npc_name or "NPC").replace(" ", "_")
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  return f"relationship_{npc_key}_{topic}_{timestamp}"


RELATIONSHIP_EVENT_DEFAULTS = {
  "task_assistance": {"signal": "positive", "strength": "small"},
  "gratitude": {"signal": "positive", "strength": "small"},
  "cooperation": {"signal": "positive", "strength": "medium"},
  "negative_feedback": {"signal": "negative", "strength": "small"},
  "trust_building": {"signal": "positive", "strength": "medium"},
}


RELATIONSHIP_IMPACT = {
  "task_assistance": 0.05,
  "gratitude": 0.03,
  "cooperation": 0.08,
  "trust_building": 0.10,
  "negative_feedback": -0.05,
}


RELATIONSHIP_STATE_THRESHOLDS = {
  "distrustful": -0.05,
  "friendly": 0.08,
  "trusted": 0.18,
}


def normalize_relationship_event_type(event_type, signal=""):
  event_type = str(event_type or "").lower().strip()
  aliases = {
    "npc_helped_player": "task_assistance",
    "positive_dialogue": "gratitude",
    "negative_dialogue": "negative_feedback",
    "collaboration": "cooperation",
  }
  event_type = aliases.get(event_type, event_type)
  if event_type in RELATIONSHIP_EVENT_DEFAULTS:
    return event_type
  signal = str(signal or "").lower()
  if signal == "negative":
    return "negative_feedback"
  if signal == "positive":
    return "gratitude"
  return "cooperation"


def relationship_event_defaults(event_type, signal="", strength=""):
  event_type = normalize_relationship_event_type(event_type, signal)
  defaults = RELATIONSHIP_EVENT_DEFAULTS.get(event_type, {"signal": "positive", "strength": "small"})
  normalized_signal = str(signal or defaults.get("signal") or "positive").lower()
  if normalized_signal not in {"positive", "negative", "neutral"}:
    normalized_signal = defaults.get("signal", "positive")
  normalized_strength = str(strength or defaults.get("strength") or "small").lower()
  if normalized_strength not in {"small", "medium", "strong"}:
    normalized_strength = defaults.get("strength", "small")
  return event_type, normalized_signal, normalized_strength


def relationship_impact_value(event_type):
  return float(RELATIONSHIP_IMPACT.get(normalize_relationship_event_type(event_type), 0.0))


def relationship_state_from_score(score):
  try:
    score = float(score)
  except (TypeError, ValueError):
    score = 0.0
  if score >= RELATIONSHIP_STATE_THRESHOLDS["trusted"]:
    return "trusted"
  if score >= RELATIONSHIP_STATE_THRESHOLDS["friendly"]:
    return "friendly"
  if score < RELATIONSHIP_STATE_THRESHOLDS["distrustful"]:
    return "distrustful"
  return "neutral"


def normalize_relationship_state_label(state):
  state = str(state or "neutral").lower().strip()
  if state == "helpful":
    return "friendly"
  if state in {"neutral", "friendly", "trusted", "distrustful"}:
    return state
  return "neutral"


def relationship_score_from_memories(player_relationship):
  score = 0.0
  memories = []
  memories.extend(player_relationship.get("positive_memories", []) or [])
  memories.extend(player_relationship.get("negative_memories", []) or [])
  for memory in memories:
    if not isinstance(memory, dict):
      continue
    impact = memory.get("impact")
    if isinstance(impact, (int, float)):
      score += float(impact)
      continue
    event_type = memory.get("event_type") or memory.get("relationship_event") or memory.get("relationship_event_type")
    if event_type:
      score += relationship_impact_value(event_type)
      continue
    if str(impact).lower() == "positive":
      score += RELATIONSHIP_IMPACT["gratitude"]
    elif str(impact).lower() == "negative":
      score += RELATIONSHIP_IMPACT["negative_feedback"]
  return round(score, 4)


def load_player_relationship(state, npc_name):
  relationships = state.setdefault("npc_relationships", {})
  npc_bucket = relationships.setdefault(npc_name, {})
  player_relationship = npc_bucket.setdefault(
    "player",
    {
      "relationship_state": "neutral",
      "positive_memories": [],
      "negative_memories": [],
    },
  )
  player_relationship["relationship_state"] = normalize_relationship_state_label(
    player_relationship.get("relationship_state")
  )
  if not isinstance(player_relationship.get("positive_memories"), list):
    player_relationship["positive_memories"] = []
  if not isinstance(player_relationship.get("negative_memories"), list):
    player_relationship["negative_memories"] = []
  if not isinstance(player_relationship.get("relationship_events"), list):
    player_relationship["relationship_events"] = []
  if not isinstance(player_relationship.get("relationship_score"), (int, float)):
    player_relationship["relationship_score"] = relationship_score_from_memories(player_relationship)
  player_relationship["relationship_state"] = relationship_state_from_score(player_relationship.get("relationship_score", 0.0))
  return player_relationship


def relationship_event_text(npc_name, related_goal, completed_action):
  goal_text = str((related_goal or {}).get("goal") or completed_action or "a player request").strip()
  if "market" in goal_text.lower():
    return f"{npc_name} helped the player investigate market conditions."
  return f"Player requested help from {npc_name} to complete: {goal_text}."


def update_relationship_state(player_relationship):
  if not isinstance(player_relationship.get("relationship_score"), (int, float)):
    player_relationship["relationship_score"] = relationship_score_from_memories(player_relationship)
  player_relationship["relationship_state"] = relationship_state_from_score(player_relationship.get("relationship_score", 0.0))
  return player_relationship["relationship_state"]


def apply_relationship_transition(player_relationship, impact, impact_strength="small", confidence=1.0):
  try:
    confidence_value = float(confidence)
  except (TypeError, ValueError):
    confidence_value = 1.0
  if confidence_value < 0.5:
    return update_relationship_state(player_relationship)
  if isinstance(impact, (int, float)):
    delta = float(impact)
  else:
    impact = str(impact or "").lower()
    if impact in RELATIONSHIP_IMPACT:
      delta = relationship_impact_value(impact)
    elif impact == "positive":
      delta = RELATIONSHIP_IMPACT["gratitude"]
    elif impact == "negative":
      delta = RELATIONSHIP_IMPACT["negative_feedback"]
    else:
      delta = 0.0
  if str(impact_strength or "").lower() == "strong":
    delta *= 1.5
  player_relationship["relationship_score"] = round(float(player_relationship.get("relationship_score") or 0.0) + delta, 4)
  player_relationship["relationship_state"] = relationship_state_from_score(player_relationship["relationship_score"])
  return player_relationship["relationship_state"]


def relationship_event_record(
  event_id,
  event_type,
  target_npc,
  reason,
  timestamp,
  signal="",
  strength="",
  impact=None,
):
  event_type, signal, strength = relationship_event_defaults(event_type, signal, strength)
  if impact is None:
    impact = relationship_impact_value(event_type)
  return {
    "id": event_id,
    "event_type": event_type,
    "target_npc": target_npc,
    "signal": signal,
    "strength": strength,
    "impact": round(float(impact), 4),
    "reason": str(reason or "").strip(),
    "timestamp": timestamp,
  }


def append_relationship_event(player_relationship, event):
  if not isinstance(event, dict):
    return False
  events = player_relationship.get("relationship_events", [])
  event_id = str(event.get("id") or "")
  if event_id and any(str(existing.get("id") or "") == event_id for existing in events if isinstance(existing, dict)):
    return False
  events.append(event)
  player_relationship["relationship_events"] = events[-40:]
  apply_relationship_transition(
    player_relationship,
    event.get("impact", 0.0),
    impact_strength=event.get("strength", "small"),
    confidence=1.0,
  )
  return True


def maybe_append_trust_building_event(player_relationship, npc_name, timestamp):
  events = [event for event in player_relationship.get("relationship_events", []) if isinstance(event, dict)]
  if any(event.get("event_type") == "trust_building" for event in events):
    return None
  positive_events = [
    event for event in events
    if event.get("signal") == "positive" and event.get("event_type") in {"task_assistance", "gratitude", "cooperation"}
  ]
  if len(positive_events) < 3:
    return None
  event_id = "relationship_trust_building_" + npc_name.replace(" ", "_") + "_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  event = relationship_event_record(
    event_id,
    "trust_building",
    npc_name,
    f"Repeated positive interactions built trust between the player and {npc_name}.",
    timestamp,
  )
  append_relationship_event(player_relationship, event)
  return event


def append_player_relationship_memory(state, npc_name, related_goal, action_state=None):
  if npc_name not in ALLOWED_MEMORY_NPCS:
    return None
  action_state = action_state or {}
  source_memory_id = str(
    action_state.get("source_memory_id")
    or (related_goal or {}).get("source_memory_id")
    or ""
  ).strip()
  goal_text = str((related_goal or {}).get("goal") or action_state.get("action") or "").strip()
  memory_id = relationship_memory_id(npc_name, source_memory_id, goal_text)
  player_relationship = load_player_relationship(state, npc_name)
  positive_memories = player_relationship.get("positive_memories", [])
  if any(str(item.get("id") or "") == memory_id for item in positive_memories if isinstance(item, dict)):
    return None
  world_day = (
    action_state.get("completed_world_day")
    or action_state.get("world_day")
    or (related_goal or {}).get("completed_world_day")
  )
  world_time = (
    action_state.get("completed_world_time")
    or action_state.get("world_time")
    or (related_goal or {}).get("completed_world_time")
  )
  current = get_current_world_time()
  if not world_day:
    world_day = current.get("day")
  if not world_time:
    world_time = current.get("time")
  event = relationship_event_text(npc_name, related_goal, action_state.get("action", ""))
  event_type = "task_assistance"
  event_signal, event_strength = (
    RELATIONSHIP_EVENT_DEFAULTS[event_type]["signal"],
    RELATIONSHIP_EVENT_DEFAULTS[event_type]["strength"],
  )
  event_impact = relationship_impact_value(event_type)
  timestamp_display = f"Day {world_day} {world_time}"
  memory = {
    "id": memory_id,
    "npc": npc_name,
    "event_type": event_type,
    "event": event,
    "relationship_event": event_type,
    "relationship_event_type": "npc_helped_player",
    "source": "player_request_completion",
    "source_memory_id": source_memory_id,
    "related_goal": goal_text,
    "action": str(action_state.get("action") or "").strip(),
    "world_day": world_day,
    "world_time": world_time,
    "time": timestamp_display,
    "signal": event_signal,
    "strength": event_strength,
    "impact": event_impact,
    "relationship_impact": "positive",
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  positive_memories.append(memory)
  player_relationship["positive_memories"] = positive_memories[-20:]
  event_record = relationship_event_record(
    memory_id,
    event_type,
    npc_name,
    event,
    timestamp_display,
    signal=event_signal,
    strength=event_strength,
    impact=event_impact,
  )
  append_relationship_event(player_relationship, event_record)
  maybe_append_trust_building_event(player_relationship, npc_name, timestamp_display)
  player_relationship["last_relationship_update"] = memory
  trace_relationship_memory(
    "relationship_memory_created",
    npc=npc_name,
    goal_id=source_memory_id or str((related_goal or {}).get("id") or ""),
    relationship_event=event,
    time=memory.get("time", ""),
    event_type=event_type,
    signal=event_signal,
    strength=event_strength,
    impact=event_impact,
    relationship_score=player_relationship.get("relationship_score", 0.0),
    relationship_state=player_relationship.get("relationship_state", "neutral"),
  )
  return memory


def interpret_player_social_signal(player_message, npc_name="", conversation_context=None):
  text = " ".join(str(player_message or "").lower().split())
  if not text:
    return {
      "sentiment": "neutral",
      "reason": "Empty player message.",
      "relationship_impact": "none",
    }
  positive_patterns = (
    "thank you",
    "thanks",
    "you helped",
    "really helped",
    "i appreciate",
    "appreciate it",
    "good job",
    "well done",
    "i trust you",
    "glad you",
  )
  negative_patterns = (
    "don't trust",
    "do not trust",
    "i distrust",
    "bad job",
    "great job losing",
    "great job losing all",
    "losing all our supplies",
    "you failed",
    "useless",
    "not helpful",
    "your fault",
    "i don't believe you",
    "i do not believe you",
    "terrible",
  )
  if any(pattern in text for pattern in negative_patterns):
    return {
      "sentiment": "negative",
      "reason": f"Player expressed distrust or criticism toward {npc_name or 'the NPC'}.",
      "relationship_impact": "negative",
    }
  if any(pattern in text for pattern in positive_patterns):
    return {
      "sentiment": "positive",
      "reason": f"Player expressed appreciation toward {npc_name or 'the NPC'}.",
      "relationship_impact": "positive",
    }
  return {
    "sentiment": "neutral",
    "reason": "Normal conversation without a clear relationship impact.",
    "relationship_impact": "none",
  }


def relationship_reasoning_triggered(player_message, conversation_context=None):
  text_parts = [str(player_message or "")]
  for item in conversation_context or []:
    if isinstance(item, dict):
      text_parts.append(str(item.get("text") or item.get("content") or ""))
    else:
      text_parts.append(str(item))
  text = " ".join(text_parts).lower()
  triggers = (
    "thank",
    "thanks",
    "appreciate",
    "helped",
    "trust",
    "don't trust",
    "do not trust",
    "distrust",
    "sorry",
    "apolog",
    "good job",
    "great job",
    "bad job",
    "blame",
    "fault",
    "failed",
    "useless",
    "not helpful",
    "losing",
    "lost",
    "supplies",
    "lie",
    "lied",
    "believe you",
  )
  return any(trigger in text for trigger in triggers)


def relationship_reasoning_on_cooldown(player_relationship, cooldown_minutes=30):
  current = get_current_world_time()
  last_day = player_relationship.get("last_relationship_reasoning_world_day")
  last_time = str(player_relationship.get("last_relationship_reasoning_world_time") or "")
  if not last_day or not last_time:
    return False
  try:
    if int(last_day) != int(current.get("day") or 1):
      return False
  except (TypeError, ValueError):
    return False
  elapsed = time_to_minutes(current.get("time")) - time_to_minutes(last_time)
  return 0 <= elapsed < cooldown_minutes


def relationship_reasoning_context(player_relationship, max_results=3):
  positive = [
    memory for memory in reversed(player_relationship.get("positive_memories", []) or [])
    if isinstance(memory, dict)
  ][:max_results]
  negative = [
    memory for memory in reversed(player_relationship.get("negative_memories", []) or [])
    if isinstance(memory, dict)
  ][:max_results]
  return {
    "relationship_state": player_relationship.get("relationship_state", "neutral"),
    "positive_memories": positive,
    "negative_memories": negative,
    "last_relationship_reasoning": player_relationship.get("last_relationship_reasoning", {}),
  }


def build_relationship_reasoning_prompt(npc_name, player_message, npc_reply="", conversation_context=None, relationship_context=None):
  relationship_context = relationship_context or {}
  recent_conversation = []
  for item in (conversation_context or [])[-6:]:
    if isinstance(item, dict):
      speaker = item.get("speaker") or item.get("role") or "unknown"
      text = item.get("text") or item.get("content") or ""
      recent_conversation.append({"speaker": speaker, "text": str(text)[:300]})
  if player_message:
    recent_conversation.append({"speaker": "player", "text": str(player_message)[:300]})
  if npc_reply:
    recent_conversation.append({"speaker": "npc", "text": str(npc_reply)[:300]})
  payload = {
    "task": "Interpret whether this conversation contains a relationship-impacting social signal.",
    "rules": [
      "Return valid JSON only.",
      "Do not include markdown or explanations outside JSON.",
      "Focus on the player's relationship with the NPC, not general topic sentiment.",
      "Detect appreciation, apology, praise, blame, distrust, complaints, and sarcasm.",
      "Neutral factual questions should use relationship_change=none and memory_type=none.",
      "Do not invent events or relationship history.",
    ],
    "schema": {
      "relationship_signal": "positive | negative | neutral",
      "relationship_change": "increase | decrease | none",
      "impact_strength": "small | medium | strong",
      "reason": "short explanation",
      "memory_type": "positive_dialogue | negative_dialogue | collaboration | none",
      "confidence": "0.0-1.0",
    },
    "npc": npc_name,
    "current_relationship_state": relationship_context.get("relationship_state", "neutral"),
    "recent_positive_relationship_memories": [
      memory.get("event", "")
      for memory in relationship_context.get("positive_memories", [])
      if isinstance(memory, dict)
    ],
    "recent_negative_relationship_memories": [
      memory.get("event", "")
      for memory in relationship_context.get("negative_memories", [])
      if isinstance(memory, dict)
    ],
    "recent_conversation": recent_conversation[-8:],
  }
  return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_relationship_reasoning(reasoning):
  reasoning = reasoning if isinstance(reasoning, dict) else {}
  signal = str(reasoning.get("relationship_signal") or reasoning.get("sentiment") or "neutral").lower()
  if signal not in {"positive", "negative", "neutral"}:
    signal = "neutral"
  change = str(reasoning.get("relationship_change") or "").lower()
  if change not in {"increase", "decrease", "none"}:
    change = "increase" if signal == "positive" else "decrease" if signal == "negative" else "none"
  strength = str(reasoning.get("impact_strength") or "small").lower()
  if strength not in {"small", "medium", "strong"}:
    strength = "small"
  memory_type = str(reasoning.get("memory_type") or "none").lower()
  if memory_type not in {"positive_dialogue", "negative_dialogue", "collaboration", "none"}:
    memory_type = "none"
  if signal == "positive" and memory_type == "none":
    memory_type = "positive_dialogue"
  if signal == "negative" and memory_type == "none":
    memory_type = "negative_dialogue"
  try:
    confidence = float(reasoning.get("confidence", 0.0))
  except (TypeError, ValueError):
    confidence = 0.0
  confidence = max(0.0, min(1.0, confidence))
  impact = "positive" if change == "increase" else "negative" if change == "decrease" else "none"
  return {
    "relationship_signal": signal,
    "relationship_change": change,
    "impact_strength": strength,
    "reason": str(reasoning.get("reason") or "").strip()[:300],
    "memory_type": memory_type,
    "confidence": confidence,
    "relationship_impact": impact,
    "sentiment": signal,
  }


def fallback_relationship_reasoning(player_message, npc_name="", conversation_context=None, fallback_reason=""):
  social_signal = interpret_player_social_signal(player_message, npc_name, conversation_context)
  impact = social_signal.get("relationship_impact", "none")
  reasoning = normalize_relationship_reasoning(
    {
      "relationship_signal": social_signal.get("sentiment", "neutral"),
      "relationship_change": "increase" if impact == "positive" else "decrease" if impact == "negative" else "none",
      "impact_strength": "small",
      "reason": social_signal.get("reason", ""),
      "memory_type": "positive_dialogue" if impact == "positive" else "negative_dialogue" if impact == "negative" else "none",
      "confidence": 0.58 if impact in {"positive", "negative"} else 0.45,
    }
  )
  reasoning.update(
    {
      "backend": "deterministic_fallback",
      "llm_failed": bool(fallback_reason),
      "fallback_reason": fallback_reason,
    }
  )
  return reasoning


def interpret_relationship_signal_with_llm(npc_name, player_message, npc_reply="", conversation_context=None, state=None):
  state = state or load_world_state()
  player_relationship = load_player_relationship(state, npc_name)
  if not relationship_reasoning_triggered(player_message, conversation_context):
    reasoning = normalize_relationship_reasoning(
      {
        "relationship_signal": "neutral",
        "relationship_change": "none",
        "impact_strength": "small",
        "reason": "No clear relationship-impacting social signal was detected.",
        "memory_type": "none",
        "confidence": 0.75,
      }
    )
    reasoning.update({"backend": "trigger_filter", "skipped": True})
    return reasoning
  if relationship_reasoning_on_cooldown(player_relationship):
    reasoning = fallback_relationship_reasoning(
      player_message,
      npc_name,
      conversation_context,
      "Relationship reasoning cooldown is active; skipped API call.",
    )
    reasoning.update({"backend": "cooldown_deterministic", "skipped_api": True})
    return reasoning
  relationship_context = relationship_reasoning_context(player_relationship)
  trace_relationship_reasoning(
    "relationship_reasoning_started",
    npc=npc_name,
    relationship_state=relationship_context.get("relationship_state", "neutral"),
    player_message=str(player_message or "")[:240],
    recent_positive_count=len(relationship_context.get("positive_memories", [])),
    recent_negative_count=len(relationship_context.get("negative_memories", [])),
  )
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    reasoning = fallback_relationship_reasoning(
      player_message,
      npc_name,
      conversation_context,
      "DEEPSEEK_API_KEY is not set.",
    )
    trace_relationship_reasoning(
      "relationship_reasoning_fallback",
      npc=npc_name,
      reason=reasoning.get("fallback_reason", ""),
      relationship_signal=reasoning.get("relationship_signal", "neutral"),
    )
    return reasoning
  prompt = build_relationship_reasoning_prompt(
    npc_name,
    player_message,
    npc_reply=npc_reply,
    conversation_context=conversation_context,
    relationship_context=relationship_context,
  )
  model = os.environ.get("DEEPSEEK_RELATIONSHIP_MODEL", "deepseek-v4-flash")
  request_payload = {
    "model": model,
    "messages": [
      {
        "role": "system",
        "content": "You reason about NPC/player relationship changes. Return JSON only.",
      },
      {"role": "user", "content": prompt},
    ],
    "temperature": 0.2,
    "max_tokens": 300,
  }
  request_data = json.dumps(request_payload).encode("utf-8")
  request = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=request_data,
    headers={
      "Content-Type": "application/json",
      "Authorization": f"Bearer {api_key}",
    },
    method="POST",
  )
  started = datetime.datetime.now()
  try:
    with urllib.request.urlopen(request, timeout=20) as response:
      response_status = response.status
      response_body = response.read().decode("utf-8")
    elapsed_sec = round((datetime.datetime.now() - started).total_seconds(), 3)
    parsed = json.loads(response_body)
    choice = (parsed.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or "").strip()
    finish_reason = choice.get("finish_reason", "")
    if not content:
      raise RuntimeError(f"DeepSeek relationship reasoner returned empty content. finish_reason={finish_reason}")
    reasoning = normalize_relationship_reasoning(extract_json_object(content))
    reasoning.update(
      {
        "backend": "api",
        "model": model,
        "llm_failed": False,
        "elapsed_sec": elapsed_sec,
        "finish_reason": finish_reason,
        "response_status": response_status,
      }
    )
    trace_relationship_reasoning(
      "relationship_reasoning_completed",
      npc=npc_name,
      success=True,
      relationship_signal=reasoning.get("relationship_signal", "neutral"),
      relationship_change=reasoning.get("relationship_change", "none"),
      confidence=reasoning.get("confidence", 0.0),
      elapsed_sec=elapsed_sec,
      finish_reason=finish_reason,
    )
    return reasoning
  except Exception as exc:
    reasoning = fallback_relationship_reasoning(player_message, npc_name, conversation_context, str(exc))
    reasoning.update({"model": model})
    trace_relationship_reasoning(
      "relationship_reasoning_fallback",
      npc=npc_name,
      reason=str(exc),
      relationship_signal=reasoning.get("relationship_signal", "neutral"),
      relationship_change=reasoning.get("relationship_change", "none"),
    )
    return reasoning


def append_dialogue_relationship_memory(state, npc_name, player_message, social_signal):
  social_signal = social_signal or {}
  impact = str(social_signal.get("relationship_impact") or "none").lower()
  if impact not in {"positive", "negative"}:
    relationship_change = str(social_signal.get("relationship_change") or "none").lower()
    impact = "positive" if relationship_change == "increase" else "negative" if relationship_change == "decrease" else "none"
  if impact not in {"positive", "negative"}:
    return None
  if npc_name not in ALLOWED_MEMORY_NPCS:
    return None
  player_relationship = load_player_relationship(state, npc_name)
  current = get_current_world_time()
  event_type = str(social_signal.get("memory_type") or "").lower()
  if event_type not in {"positive_dialogue", "negative_dialogue", "collaboration"}:
    event_type = "positive_dialogue" if impact == "positive" else "negative_dialogue"
  if event_type == "positive_dialogue":
    relationship_event = "gratitude"
  elif event_type == "negative_dialogue":
    relationship_event = "negative_feedback"
  elif event_type == "collaboration":
    relationship_event = "cooperation"
  else:
    relationship_event = normalize_relationship_event_type(event_type, impact)
  relationship_event, event_signal, event_strength = relationship_event_defaults(
    relationship_event,
    signal=impact,
    strength="" if relationship_event in {"gratitude", "negative_feedback", "cooperation", "trust_building"} else social_signal.get("impact_strength", ""),
  )
  event_impact = relationship_impact_value(relationship_event)
  if impact == "positive":
    if relationship_event == "cooperation":
      event = f"Player continued a cooperative interaction with {npc_name}."
    else:
      event = f"Player expressed appreciation toward {npc_name}."
    bucket_name = "positive_memories"
  else:
    event = f"Player expressed distrust or criticism toward {npc_name}."
    bucket_name = "negative_memories"
  memory_id = "relationship_" + "_".join(
    [
      event_type,
      npc_name.replace(" ", "_"),
      datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
    ]
  )
  memory = {
    "id": memory_id,
    "npc": npc_name,
    "event_type": event_type,
    "relationship_event": relationship_event,
    "relationship_event_type": event_type,
    "event": event,
    "source": "live_dialogue",
    "player_message": str(player_message or "").strip()[:240],
    "reason": str((social_signal or {}).get("reason") or "").strip(),
    "signal": event_signal,
    "strength": event_strength,
    "sentiment": str((social_signal or {}).get("sentiment") or social_signal.get("relationship_signal") or "neutral"),
    "relationship_signal": str(social_signal.get("relationship_signal") or social_signal.get("sentiment") or "neutral"),
    "relationship_change": str(social_signal.get("relationship_change") or ("increase" if impact == "positive" else "decrease")),
    "impact_strength": event_strength,
    "confidence": social_signal.get("confidence", ""),
    "relationship_impact": impact,
    "reasoning_backend": social_signal.get("backend", ""),
    "reasoning_model": social_signal.get("model", ""),
    "world_day": current.get("day"),
    "world_time": current.get("time"),
    "time": current.get("display"),
    "impact": event_impact,
    "relationship_impact": impact,
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  bucket = player_relationship.get(bucket_name, [])
  bucket.append(memory)
  player_relationship[bucket_name] = bucket[-20:]
  event_record = relationship_event_record(
    memory_id,
    relationship_event,
    npc_name,
    memory.get("reason") or event,
    memory.get("time", ""),
    signal=event_signal,
    strength=event_strength,
    impact=event_impact,
  )
  append_relationship_event(player_relationship, event_record)
  maybe_append_trust_building_event(player_relationship, npc_name, memory.get("time", ""))
  player_relationship["last_relationship_update"] = memory
  player_relationship["last_relationship_reasoning"] = {
    "relationship_signal": memory.get("relationship_signal", "neutral"),
    "relationship_change": memory.get("relationship_change", "none"),
    "impact_strength": memory.get("impact_strength", "small"),
    "confidence": memory.get("confidence", ""),
    "reason": memory.get("reason", ""),
    "memory_type": event_type,
    "backend": memory.get("reasoning_backend", ""),
    "model": memory.get("reasoning_model", ""),
    "time": memory.get("time", ""),
  }
  player_relationship["last_relationship_reasoning_world_day"] = current.get("day")
  player_relationship["last_relationship_reasoning_world_time"] = current.get("time")
  trace_relationship_memory(
    "relationship_memory_created",
    npc=npc_name,
    goal_id="",
    relationship_event=event,
    time=memory.get("time", ""),
    event_type=event_type,
    typed_relationship_event=relationship_event,
    relationship_impact=impact,
    impact=event_impact,
    relationship_score=player_relationship.get("relationship_score", 0.0),
    relationship_state=player_relationship.get("relationship_state", "neutral"),
    confidence=memory.get("confidence", ""),
    reason=memory.get("reason", ""),
  )
  return memory


def append_relationship_for_completed_request(npc_name, completed_request, observation=None):
  if not isinstance(completed_request, dict):
    return None
  if str(completed_request.get("type", "")).lower() != "request":
    return None
  if str(completed_request.get("status", "")).lower() != "completed":
    return None
  state = load_world_state()
  memory_id = str(completed_request.get("id") or completed_request.get("memory_id") or "").strip()
  related_goal = infer_goal_from_memory(npc_name, completed_request)
  related_goal["source"] = "player_request"
  related_goal["status"] = "completed"
  related_goal["source_memory_id"] = memory_id
  if completed_request.get("completed_world_day"):
    related_goal["completed_world_day"] = completed_request.get("completed_world_day")
  if completed_request.get("completed_world_time"):
    related_goal["completed_world_time"] = completed_request.get("completed_world_time")
  action_state = {
    "npc": npc_name,
    "action": completed_request.get("action") or (observation or {}).get("action") or "",
    "source_memory_id": memory_id,
    "world_day": completed_request.get("world_day") or (observation or {}).get("world_day"),
    "world_time": completed_request.get("world_time") or (observation or {}).get("world_time"),
    "completed_world_day": completed_request.get("completed_world_day") or (observation or {}).get("world_day"),
    "completed_world_time": completed_request.get("completed_world_time") or (observation or {}).get("world_time"),
  }
  relationship_memory = append_player_relationship_memory(state, npc_name, related_goal, action_state)
  if relationship_memory:
    save_world_state(state)
  return relationship_memory


def merge_latest_relationships(state):
  try:
    latest = load_world_state()
    latest_relationships = latest.get("npc_relationships", {})
    if isinstance(latest_relationships, dict):
      state["npc_relationships"] = latest_relationships
  except Exception:
    if not isinstance(state.get("npc_relationships"), dict):
      state["npc_relationships"] = {}
  return state


def retrieve_relevant_relationship_memory(npc_name, player_message="", max_results=3, state=None):
  state = state or load_world_state()
  relationship = (
    state.get("npc_relationships", {})
    .get(npc_name, {})
    .get("player", {})
  )
  if not isinstance(relationship, dict):
    return {"relationship_state": "neutral", "relationship_score": 0.0, "positive_memories": [], "negative_memories": [], "relationship_events": []}
  query_terms = knowledge_keywords(player_message)
  scored_positive = []
  for index, memory in enumerate(relationship.get("positive_memories", []) or []):
    if not isinstance(memory, dict):
      continue
    text = " ".join(
      [
        str(memory.get("event", "")),
        str(memory.get("related_goal", "")),
        str(memory.get("action", "")),
      ]
    )
    terms = knowledge_keywords(text)
    score = len(query_terms.intersection(terms)) * 3 if query_terms else 0
    if any(token in str(player_message or "").lower() for token in ("again", "help", "trust", "remember", "before")):
      score += 3
    score += min(index, 5) * 0.1
    if score > 0 or not query_terms:
      scored_positive.append((score, index, memory))
  scored_positive.sort(key=lambda item: (item[0], item[1]), reverse=True)
  positive = [item for _, _, item in scored_positive[:max_results]]
  negative = [
    item for item in reversed(relationship.get("negative_memories", []) or [])
    if isinstance(item, dict)
  ][:max_results]
  return {
    "relationship_state": relationship.get("relationship_state", "neutral"),
    "relationship_score": relationship.get("relationship_score", 0.0),
    "positive_memories": positive,
    "negative_memories": negative,
    "relationship_events": [
      item for item in reversed(relationship.get("relationship_events", []) or [])
      if isinstance(item, dict)
    ][:max_results],
  }


def retrieve_relevant_relationship_context(
    npc_name,
    player_message="",
    current_relationship_state="",
    max_results=3,
    state=None):
  context = retrieve_relevant_relationship_memory(
    npc_name,
    player_message=player_message,
    max_results=max_results,
    state=state,
  )
  if current_relationship_state:
    context["relationship_state"] = normalize_relationship_state_label(current_relationship_state)
  memories = []
  for memory in context.get("positive_memories", [])[:max_results]:
    if isinstance(memory, dict) and memory.get("event"):
      memories.append(memory)
  for memory in context.get("negative_memories", [])[:max_results]:
    if isinstance(memory, dict) and memory.get("event"):
      memories.append(memory)
  context["memories"] = memories[:max_results]
  relationship = (
    (state or load_world_state()).get("npc_relationships", {})
    .get(npc_name, {})
    .get("player", {})
  )
  if isinstance(relationship, dict):
    context["last_relationship_reasoning"] = relationship.get("last_relationship_reasoning", {})
    context["relationship_score"] = relationship.get("relationship_score", context.get("relationship_score", 0.0))
    context["relationship_events"] = [
      item for item in reversed(relationship.get("relationship_events", []) or [])
      if isinstance(item, dict)
    ][:max_results]
  return context


def dialogue_relationship_context_summary(relationship_context):
  relationship_context = relationship_context or {}
  memories = relationship_context.get("memories")
  if not isinstance(memories, list):
    memories = []
    memories.extend(relationship_context.get("positive_memories") or [])
    memories.extend(relationship_context.get("negative_memories") or [])
  memory_ids = []
  memory_events = []
  typed_events = []
  reasoning = relationship_context.get("last_relationship_reasoning")
  for memory in memories:
    if not isinstance(memory, dict):
      continue
    memory_id = str(memory.get("id") or "").strip()
    event = str(memory.get("event") or "").strip()
    if memory_id:
      memory_ids.append(memory_id)
    if event:
      memory_events.append(event)
  for event in relationship_context.get("relationship_events", []) or []:
    if not isinstance(event, dict):
      continue
    typed_events.append(
      {
        "event_type": event.get("event_type", ""),
        "impact": event.get("impact", 0.0),
        "reason": event.get("reason", ""),
        "timestamp": event.get("timestamp", ""),
      }
    )
  return {
    "relationship_state": relationship_context.get("relationship_state", "neutral"),
    "relationship_score": relationship_context.get("relationship_score", 0.0),
    "relationship_memory_ids": memory_ids,
    "relationship_memories_used": memory_events,
    "relationship_events_used": typed_events,
    "memory_ids": memory_ids,
    "memories_used": memory_events,
    "recent_relationship_reasoning": reasoning if isinstance(reasoning, dict) else {},
  }


def is_player_related_completed_action(action_state, observation=None):
  source_memory_id = str(action_state.get("source_memory_id") or "").strip()
  if source_memory_id:
    return True
  action_text = " ".join(
    [
      str(action_state.get("action", "")),
      str(action_state.get("location", "")),
      str(action_state.get("to_location", "")),
      str((observation or {}).get("content", "")),
    ]
  ).lower()
  return any(
    token in action_text
    for token in (
      "ask vendor",
      "ask vendors",
      "investigate",
      "collect information",
      "market information",
      "talk with",
      "talk to",
      "help player",
      "assist",
      "favor",
      "favour",
    )
  )


def _related_experience_item(item, query_terms, source_memory_id=""):
  if not isinstance(item, dict):
    return False
  if source_memory_id and source_memory_id == str(item.get("source_memory_id") or item.get("related_memory_id") or ""):
    return True
  text = " ".join(
    str(item.get(key, ""))
    for key in ("content", "reflection", "action", "topic", "location", "time")
  )
  if not query_terms:
    return False
  return bool(query_terms.intersection(knowledge_keywords(text)))


def _minutes_or_none(time_text):
  normalized = normalize_schedule_time(time_text)
  if not normalized:
    return None
  return time_to_minutes(normalized)


def _within_task_time_window(item, completed_world_day=None, completed_world_time="", goal=None):
  if not isinstance(item, dict):
    return False
  item_day = item.get("world_day")
  item_time = item.get("world_time")
  if not item_day or not item_time:
    return True
  try:
    item_day = int(item_day)
  except (TypeError, ValueError):
    return True
  try:
    completed_day = int(completed_world_day) if completed_world_day else None
  except (TypeError, ValueError):
    completed_day = None
  goal_day = None
  if isinstance(goal, dict):
    try:
      goal_day = int(goal.get("world_day") or 0) or None
    except (TypeError, ValueError):
      goal_day = None
  if goal_day and item_day < goal_day:
    return False
  if completed_day and item_day > completed_day:
    return False
  if completed_day and item_day == completed_day:
    item_minutes = _minutes_or_none(item_time)
    completed_minutes = _minutes_or_none(completed_world_time)
    if item_minutes is not None and completed_minutes is not None and item_minutes > completed_minutes + 120:
      return False
  return True


def collect_task_experience_context(
    npc_name,
    completed_goal,
    completed_action,
    location,
    world_day,
    world_time,
    source_memory_id="",
    related_goal=None):
  query_text = " ".join(
    [
      str(completed_goal or ""),
      str(completed_action or ""),
      str(location or ""),
    ]
  )
  query_terms = knowledge_keywords(query_text)
  observations = [
    observation for observation in load_observations(npc_name)
    if _related_experience_item(observation, query_terms, source_memory_id)
    and _within_task_time_window(observation, world_day, world_time, related_goal)
  ][-5:]
  reflections = [
    reflection for reflection in load_reflections(npc_name)
    if _related_experience_item(reflection, query_terms, source_memory_id)
    and _within_task_time_window(reflection, world_day, world_time, related_goal)
  ][-5:]
  conversation_memories = [
    memory for memory in load_npc_memory(npc_name)
    if str(memory.get("type", "")).lower() in {"conversation", "report", "request", "knowledge", "completion"}
    and _related_experience_item(memory, query_terms, source_memory_id)
    and _within_task_time_window(memory, world_day, world_time, related_goal)
  ][-5:]
  return {
    "npc": npc_name,
    "completed_goal": str(completed_goal or "").strip(),
    "completed_action": str(completed_action or "").strip(),
    "location": str(location or "").strip(),
    "world_day": world_day,
    "world_time": world_time,
    "source_memory_id": str(source_memory_id or "").strip(),
    "related_goal_record": related_goal if isinstance(related_goal, dict) else {},
    "observations": observations,
    "reflections": reflections,
    "conversation_history": conversation_memories,
  }


def _experience_text(context):
  parts = [
    str(context.get("completed_goal", "")),
    str(context.get("location", "")),
  ]
  for collection_name in ("observations", "reflections", "conversation_history"):
    for item in context.get(collection_name, []):
      if not isinstance(item, dict):
        continue
      parts.extend(
        str(item.get(key, ""))
        for key in ("content", "reflection", "action", "topic", "location")
      )
  return " ".join(parts).lower()


def extract_task_result_findings(context):
  text = _experience_text(context)
  goal_text = str(context.get("completed_goal", "")).lower()
  location_text = str(context.get("location", "")).strip()
  location_label = location_text or "the target location"
  findings = []
  if "market" in text or "vendor" in text or "merchant" in text or "trade" in text:
    findings.append("Visited the market and talked with vendors.")
    findings.append("Collected information about current trade conditions.")
  elif location_text:
    findings.append(f"Visited {location_label} and gathered local information.")
  else:
    findings.append("Completed the player-related task and gathered local information.")
  if any(token in text for token in ("route", "road", "trader", "merchant", "price", "prices", "jittery", "disruption", "quiet")):
    findings.append("Observed concerns related to trader activity and routes.")
  if "investigate" in goal_text and not any("observ" in finding.lower() for finding in findings):
    findings.append("Collected observations related to the investigation goal.")
  deduped = []
  for finding in findings:
    if finding and finding not in deduped:
      deduped.append(finding)
  return deduped[:4]


def collect_task_evidence(context):
  evidence = []
  action_text = str(context.get("completed_action") or "").strip()
  if action_text:
    evidence.append(
      {
        "type": "action",
        "content": action_text,
        "time": context.get("world_time", ""),
        "location": context.get("location", ""),
      }
    )
  for item in context.get("conversation_history", [])[:5]:
    if not isinstance(item, dict):
      continue
    content = str(item.get("content") or "").strip()
    if not content:
      continue
    evidence.append(
      {
        "type": "conversation",
        "content": content,
        "time": item.get("time", ""),
        "location": item.get("location", "") or item.get("topic", ""),
        "source_npc": item.get("npc") or item.get("target") or context.get("npc", ""),
      }
    )
  for item in context.get("observations", [])[:5]:
    if not isinstance(item, dict):
      continue
    content = str(item.get("content") or "").strip()
    if not content:
      continue
    evidence.append(
      {
        "type": "observation",
        "content": content,
        "time": item.get("time", ""),
        "location": item.get("location", ""),
      }
    )
  for item in context.get("reflections", [])[:5]:
    if not isinstance(item, dict):
      continue
    content = str(item.get("reflection") or "").strip()
    if not content:
      continue
    evidence.append(
      {
        "type": "reflection",
        "content": content,
        "time": item.get("time", ""),
        "location": item.get("location", ""),
      }
    )
  deduped = []
  seen = set()
  for item in evidence:
    key = (item.get("type", ""), item.get("content", ""))
    if key in seen:
      continue
    seen.add(key)
    deduped.append(item)
  return deduped[:12]


def fallback_knowledge_interpretation(findings, error_message=""):
  summary = " ".join(str(finding) for finding in (findings or []) if finding).strip()
  if not summary:
    summary = "Insufficient evidence."
  interpretation = {
    "summary": summary,
    "implications": [],
    "confidence": "low",
  }
  if error_message:
    interpretation["llm_failed"] = True
    interpretation["error"] = str(error_message)
  return interpretation


def build_knowledge_interpretation_prompt(npc_name, profile, related_goal, evidence):
  profile = profile or {}
  evidence_payload = [
    {
      "type": item.get("type", ""),
      "content": item.get("content", ""),
      "time": item.get("time", ""),
      "location": item.get("location", ""),
      "source_npc": item.get("source_npc", ""),
    }
    for item in evidence
    if isinstance(item, dict) and item.get("content")
  ]
  return (
    "You are interpreting an NPC's experiences.\n"
    "You must only use the provided evidence.\n"
    "Do not invent events, people, locations, or facts.\n"
    "If evidence is insufficient, set summary to \"Insufficient evidence.\" and confidence to \"low\".\n"
    "Consider the NPC personality, occupation, and current goal, but do not add facts beyond evidence.\n"
    "Return valid JSON only. Do not include markdown or explanation.\n"
    "Schema:\n"
    "{\n"
    "  \"summary\": \"string\",\n"
    "  \"implications\": [\"string\"],\n"
    "  \"confidence\": \"low|medium|high\"\n"
    "}\n\n"
    f"NPC: {npc_name}\n"
    f"Personality: {profile.get('personality', '')}\n"
    f"Role / occupation: {profile.get('workplace', '')}\n"
    f"Current goal: {related_goal}\n"
    "Evidence JSON:\n"
    f"{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}\n"
  )


def normalize_knowledge_interpretation(payload):
  if not isinstance(payload, dict):
    raise ValueError("Knowledge interpretation response was not a JSON object.")
  summary = str(payload.get("summary") or "").strip()
  implications = payload.get("implications", [])
  if not isinstance(implications, list):
    implications = []
  implications = [
    str(item).strip()
    for item in implications
    if str(item or "").strip()
  ][:5]
  confidence = str(payload.get("confidence") or "medium").strip().lower()
  if confidence not in {"low", "medium", "high"}:
    confidence = "medium"
  if not summary:
    summary = "Insufficient evidence."
    confidence = "low"
  return {
    "summary": summary[:500],
    "implications": [item[:240] for item in implications],
    "confidence": confidence,
  }


def interpret_knowledge_with_llm(npc_name, related_goal, evidence, fallback_findings=None):
  evidence_count = len(evidence or [])
  trace_knowledge_interpretation(
    "E8821 interpretation started",
    npc_name=npc_name,
    goal=related_goal,
    evidence_count=evidence_count,
  )
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    trace_knowledge_interpretation(
      "E8821 interpretation completed",
      npc_name=npc_name,
      goal=related_goal,
      evidence_count=evidence_count,
      success=False,
      fallback=True,
      error="DEEPSEEK_API_KEY is not set.",
    )
    return fallback_knowledge_interpretation(fallback_findings, "DEEPSEEK_API_KEY is not set.")
  state = load_world_state()
  profile = npc_profile(npc_name, state)
  prompt = build_knowledge_interpretation_prompt(npc_name, profile, related_goal, evidence)
  model = os.environ.get("DEEPSEEK_KNOWLEDGE_MODEL", "deepseek-v4-flash")
  payload = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.2,
    "max_tokens": 500,
  }
  request = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
      "Content-Type": "application/json",
      "Authorization": f"Bearer {api_key}",
    },
    method="POST",
  )
  try:
    started = datetime.datetime.now()
    with urllib.request.urlopen(request, timeout=25) as response:
      response_payload = json.loads(response.read().decode("utf-8"))
    elapsed = (datetime.datetime.now() - started).total_seconds()
    choice = (response_payload.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if not content:
      raise ValueError("Knowledge interpretation LLM returned empty content.")
    interpretation = normalize_knowledge_interpretation(extract_json_object(content))
    interpretation["llm_failed"] = False
    interpretation["model"] = model
    interpretation["elapsed_sec"] = round(elapsed, 3)
    interpretation["finish_reason"] = choice.get("finish_reason", "")
    trace_knowledge_interpretation(
      "E8821 interpretation completed",
      npc_name=npc_name,
      goal=related_goal,
      evidence_count=evidence_count,
      success=True,
      fallback=False,
      error="",
      finish_reason=choice.get("finish_reason", ""),
      elapsed_sec=round(elapsed, 3),
    )
    return interpretation
  except Exception as exc:
    trace_knowledge_interpretation(
      "E8821 interpretation completed",
      npc_name=npc_name,
      goal=related_goal,
      evidence_count=evidence_count,
      success=False,
      fallback=True,
      error=str(exc),
    )
    return fallback_knowledge_interpretation(fallback_findings, str(exc))


def related_goal_for_action(state, npc_name, source_memory_id="", action_text=""):
  goals = state.get("npc_goals", {}).get(npc_name, [])
  for goal in goals:
    if not isinstance(goal, dict):
      continue
    if source_memory_id and source_memory_id == str(goal.get("source_memory_id") or ""):
      return goal
  action_lower = str(action_text or "").lower()
  for goal in goals:
    if not isinstance(goal, dict):
      continue
    goal_text = " ".join(
      [
        str(goal.get("goal", "")),
        str(goal.get("target_location", "")),
        " ".join(str(action) for action in goal.get("actions", []) if action),
      ]
    ).lower()
    if "market" in action_lower and "market" in goal_text:
      return goal
  return {}


def append_npc_knowledge(state, npc_name, knowledge_entry):
  npc_knowledge = state.get("npc_knowledge", {})
  entries = [
    item for item in npc_knowledge.get(npc_name, [])
    if isinstance(item, dict)
  ]
  knowledge_id = str(knowledge_entry.get("knowledge_id") or "").strip()
  if knowledge_id and any(str(item.get("knowledge_id") or "") == knowledge_id for item in entries):
    npc_knowledge[npc_name] = entries
    state["npc_knowledge"] = npc_knowledge
    return None
  entries.append(knowledge_entry)
  npc_knowledge[npc_name] = entries[-30:]
  state["npc_knowledge"] = npc_knowledge
  return knowledge_entry


def generate_task_result_knowledge(
    npc_name,
    completed_goal,
    completed_action,
    location,
    world_day,
    world_time,
    source_memory_id="",
    experience_context=None):
  experience_context = experience_context or collect_task_experience_context(
    npc_name=npc_name,
    completed_goal=completed_goal,
    completed_action=completed_action,
    location=location,
    world_day=world_day,
    world_time=world_time,
    source_memory_id=source_memory_id,
  )
  findings = extract_task_result_findings(experience_context)
  if not findings:
    return None
  evidence = collect_task_evidence(experience_context)
  interpretation = interpret_knowledge_with_llm(
    npc_name=npc_name,
    related_goal=completed_goal,
    evidence=evidence,
    fallback_findings=findings,
  )
  goal_name = str(completed_goal or completed_action or "Completed task").strip()
  if world_day and world_time:
    time_display = f"Day {world_day} {world_time}"
  else:
    current = get_current_world_time()
    world_day = current.get("day")
    world_time = current.get("time")
    time_display = current.get("display")
  return {
    "knowledge_id": knowledge_id_for_result(npc_name, completed_action, source_memory_id),
    "npc": npc_name,
    "source": "task_result",
    "source_type": "observation",
    "source_memory_id": str(source_memory_id or "").strip(),
    "related_goal": goal_name,
    "time": time_display,
    "world_day": world_day,
    "world_time": world_time,
    "location": str(location or "").strip(),
    "findings": findings,
    "importance": "medium",
    "action": str(completed_action or "").strip(),
    "evidence": evidence,
    "interpretation": interpretation,
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }


def create_task_result_knowledge(state, action_state, observation=None):
  npc_name = str(action_state.get("npc", "")).strip()
  if npc_name not in ALLOWED_MEMORY_NPCS:
    return None
  action_text = str(action_state.get("action", "")).strip()
  location = (
    str(action_state.get("to_location") or action_state.get("location") or "")
    or str((observation or {}).get("location", ""))
  )
  source_memory_id = str(action_state.get("source_memory_id") or (observation or {}).get("source_memory_id") or "").strip()
  related_goal = completed_player_goal_for_action(state, npc_name, source_memory_id, action_text)
  if not related_goal:
    return None
  world_day = action_state.get("completed_world_day") or action_state.get("world_day") or (observation or {}).get("world_day")
  world_time = action_state.get("completed_world_time") or action_state.get("world_time") or (observation or {}).get("world_time")
  goal_name = str(related_goal.get("goal") or action_text or "Completed task").strip()
  experience_context = collect_task_experience_context(
    npc_name=npc_name,
    completed_goal=goal_name,
    completed_action=action_text,
    location=location or str(related_goal.get("target_location") or ""),
    world_day=world_day,
    world_time=world_time,
    source_memory_id=source_memory_id,
    related_goal=related_goal,
  )
  knowledge_entry = generate_task_result_knowledge(
    npc_name=npc_name,
    completed_goal=goal_name,
    completed_action=action_text,
    location=location or str(related_goal.get("target_location") or ""),
    world_day=world_day,
    world_time=world_time,
    source_memory_id=source_memory_id,
    experience_context=experience_context,
  )
  if not knowledge_entry:
    return None
  appended = append_npc_knowledge(state, npc_name, knowledge_entry)
  if not appended:
    merge_latest_relationships(state)
    return None
  merge_latest_relationships(state)
  relationship_memory = append_player_relationship_memory(state, npc_name, related_goal, action_state)
  if relationship_memory:
    knowledge_entry["relationship_memory"] = relationship_memory
  try:
    from .npc_memory import write_memory_entry
    memory_content = (
      f"{npc_name} completed {goal_name} and learned: "
      + "; ".join(knowledge_entry.get("findings", []))
      + "."
    )
    memory_entry = write_memory_entry(
      npc=npc_name,
      memory_type="knowledge",
      time_text=knowledge_entry.get("time", ""),
      content=memory_content,
      source="task_result",
      importance="medium",
      action=action_text,
      topic=knowledge_entry.get("location") or related_goal.get("target_location") or "",
      target=npc_name,
      status="completed",
      metadata={
        "knowledge_id": knowledge_entry["knowledge_id"],
        "related_goal": goal_name,
        "findings": knowledge_entry.get("findings", []),
        "source_memory_id": source_memory_id,
        "source_type": knowledge_entry.get("source_type", ""),
        "evidence": knowledge_entry.get("evidence", {}),
        "interpretation": knowledge_entry.get("interpretation", {}),
      },
    )
    knowledge_entry["memory_entry_id"] = memory_entry.get("id") or memory_entry.get("memory_id", "")
  except Exception as exc:
    knowledge_entry["memory_error"] = str(exc)
  return knowledge_entry


def load_npc_knowledge(npc_name, state=None):
  state = state or load_world_state()
  return [
    item for item in state.get("npc_knowledge", {}).get(npc_name, [])
    if isinstance(item, dict)
  ]


def knowledge_keywords(text):
  stopwords = {
    "the",
    "are",
    "you",
    "can",
    "where",
    "there",
    "what",
    "did",
    "from",
    "with",
    "about",
    "this",
    "that",
    "and",
    "for",
    "your",
    "have",
    "has",
    "how",
    "why",
    "who",
    "when",
  }
  return {
    part.strip(".,!?;:()[]{}\"'").lower()
    for part in str(text or "").split()
    if len(part.strip(".,!?;:()[]{}\"'")) > 2
    and part.strip(".,!?;:()[]{}\"'").lower() not in stopwords
  }


def canon_known_items(canon=None):
  canon = canon or load_world_canon()
  items = set(str(item).lower() for item in (canon.get("items") or {}).keys())
  for location in (canon.get("locations") or {}).values():
    if not isinstance(location, dict):
      continue
    for item in location.get("available_items", []) or []:
      items.add(str(item).lower())
  expanded = set(items)
  for item in items:
    if item.endswith("s"):
      expanded.add(item[:-1])
    else:
      expanded.add(item + "s")
  return expanded


def canon_known_locations(canon=None):
  canon = canon or load_world_canon()
  locations = set(str(location).lower() for location in (canon.get("locations") or {}).keys())
  expanded = set(locations)
  for location in locations:
    expanded.add(location.replace(" ", ""))
  return expanded


def world_fact_text(fact):
  if not isinstance(fact, dict):
    return ""
  fact_type = fact.get("type")
  if fact_type == "item":
    plural = str(fact.get("item", "")).lower().endswith("s")
    verb = "are" if plural else "is"
    category = str(fact.get("category", "resource")).replace("_", " ")
    noun = "resources" if plural else "resource"
    return (
      f"{fact.get('item')} {verb} {category} {noun} "
      f"available at {fact.get('location')}."
    )
  if fact_type == "location":
    items = fact.get("available_items") or []
    item_text = ", ".join(items) if items else "no listed items"
    return f"{fact.get('location')}: {fact.get('description', '')}. Available items: {item_text}."
  if fact_type == "trade_route":
    return f"{fact.get('route')} trade route status: {fact.get('status')}."
  return str(fact.get("content") or "").strip()


def normalize_belief_fact(npc_name, fact):
  if not isinstance(fact, dict):
    return None
  content = str(fact.get("content") or fact.get("truth") or "").strip()
  if not content:
    return None
  fact_id = str(fact.get("fact_id") or fact.get("id") or "").strip()
  if not fact_id:
    fact_id = "belief_" + "_".join(content.lower().split()[:6])
  return {
    "id": fact_id,
    "fact_id": fact_id,
    "type": "npc_belief",
    "npc": npc_name,
    "content": content,
    "source": str(fact.get("source") or "npc_belief").strip(),
    "source_type": str(fact.get("source_type") or "world_fact").strip(),
    "confidence": str(fact.get("confidence") or "medium").strip(),
    "location": str(fact.get("location") or "").strip(),
  }


def visible_canon_beliefs_for_npc(npc_name, canon=None):
  canon = canon or load_world_canon()
  visible = []
  for fact_id, fact in (canon.get("facts") or {}).items():
    if not isinstance(fact, dict):
      continue
    visibility = fact.get("visibility", [])
    if not isinstance(visibility, list):
      visibility = []
    if npc_name not in visibility and "*" not in visibility:
      continue
    visible.append(
      {
        "fact_id": fact_id,
        "content": str(fact.get("truth") or "").strip(),
        "source": "world_canon_visibility",
        "source_type": "world_fact",
        "confidence": "high",
        "location": fact.get("location", ""),
      }
    )
  return visible


def retrieve_relevant_npc_beliefs(
    npc_name,
    query,
    current_location="",
    current_goal="",
    max_results=5,
    canon=None,
    beliefs=None):
  canon = canon or load_world_canon()
  beliefs = beliefs or load_npc_beliefs()
  npc_belief = beliefs.get(npc_name, {"known_facts": []})
  candidates = []
  for fact in npc_belief.get("known_facts", []) or []:
    normalized = normalize_belief_fact(npc_name, fact)
    if normalized:
      candidates.append(normalized)
  for fact in visible_canon_beliefs_for_npc(npc_name, canon=canon):
    normalized = normalize_belief_fact(npc_name, fact)
    if normalized:
      candidates.append(normalized)
  query_text = " ".join([str(query or ""), str(current_location or ""), str(current_goal or "")])
  query_terms = knowledge_keywords(query_text)
  query_lower = query_text.lower()
  if not query_terms:
    return []
  scored = []
  confidence_bonus = {"high": 3, "medium": 2, "low": 1}
  for index, fact in enumerate(candidates):
    text = " ".join(
      [
        str(fact.get("fact_id", "")),
        str(fact.get("content", "")),
        str(fact.get("source", "")),
        str(fact.get("source_type", "")),
        str(fact.get("location", "")),
      ]
    )
    terms = knowledge_keywords(text)
    overlap = query_terms.intersection(terms)
    score = len(overlap) * 4
    matched = bool(overlap)
    if str(fact.get("location", "")).lower() and str(fact.get("location", "")).lower() in query_lower:
      matched = True
      score += 2
    if any(term in query_lower for term in ("where", "buy", "find", "route", "trade", "ruins", "forest", "market")) and overlap:
      score += 2
    if matched:
      score += confidence_bonus.get(str(fact.get("confidence", "medium")).lower(), 1)
      score += min(index, 5) * 0.1
      scored.append((score, index, fact))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  seen = set()
  results = []
  for _, _, fact in scored:
    fact_id = fact.get("fact_id", "")
    if fact_id in seen:
      continue
    seen.add(fact_id)
    results.append(fact)
    if len(results) >= max_results:
      break
  return results


def npc_belief_context_summary(npc_beliefs):
  facts = [fact for fact in npc_beliefs or [] if isinstance(fact, dict)]
  return {
    "belief_count": len(facts),
    "belief_ids": [fact.get("fact_id", "") for fact in facts if fact.get("fact_id")],
    "beliefs_used": [fact.get("content", "") for fact in facts if fact.get("content")],
    "belief_sources": [
      {
        "fact_id": fact.get("fact_id", ""),
        "source": fact.get("source", ""),
        "source_type": fact.get("source_type", ""),
        "confidence": fact.get("confidence", ""),
      }
      for fact in facts
    ],
  }


def unknown_world_truth_for_npc(npc_name, max_results=5, canon=None, beliefs=None):
  canon = canon or load_world_canon()
  known_ids = {
    str(fact.get("fact_id") or fact.get("id") or "")
    for fact in (load_npc_belief(npc_name).get("known_facts", []) or [])
    if isinstance(fact, dict)
  }
  known_ids.update(fact.get("fact_id", "") for fact in visible_canon_beliefs_for_npc(npc_name, canon=canon))
  unknown = []
  for fact_id, fact in (canon.get("facts") or {}).items():
    if fact_id in known_ids:
      continue
    if not isinstance(fact, dict):
      continue
    unknown.append(
      {
        "fact_id": fact_id,
        "truth": fact.get("truth", ""),
        "location": fact.get("location", ""),
        "visibility": fact.get("visibility", []),
      }
    )
    if len(unknown) >= max_results:
      break
  return unknown


def retrieve_relevant_world_facts(query, current_location="", current_goal="", max_results=5, canon=None):
  canon = canon or load_world_canon()
  query_text = " ".join([str(query or ""), str(current_location or ""), str(current_goal or "")])
  query_terms = knowledge_keywords(query_text)
  query_lower = query_text.lower()
  if not query_terms:
    return []
  scored = []
  for item_name, item in (canon.get("items") or {}).items():
    if not isinstance(item, dict):
      continue
    text = " ".join(
      [
        item_name,
        str(item.get("category", "")),
        str(item.get("location", "")),
      ]
    )
    terms = knowledge_keywords(text)
    score = len(query_terms.intersection(terms)) * 4
    if item_name.lower() in query_lower:
      score += 8
    if "where" in query_lower and item_name.lower() in query_lower:
      score += 3
    if score > 0:
      scored.append(
        (
          score,
          f"item:{item_name}",
          {
            "id": f"item:{item_name}",
            "type": "item",
            "item": item_name,
            "category": item.get("category", ""),
            "location": item.get("location", ""),
            "quantity": item.get("quantity", ""),
            "source": "world_state",
            "confidence": "high",
            "content": world_fact_text(
              {
                "type": "item",
                "item": item_name,
                "category": item.get("category", ""),
                "location": item.get("location", ""),
              }
            ),
          },
        )
      )
  for location_name, location in (canon.get("locations") or {}).items():
    if not isinstance(location, dict):
      continue
    text = " ".join(
      [
        location_name,
        str(location.get("description", "")),
        " ".join(str(item) for item in location.get("available_items", []) or []),
        " ".join(str(npc) for npc in location.get("known_npcs", []) or []),
      ]
    )
    terms = knowledge_keywords(text)
    score = len(query_terms.intersection(terms)) * 3
    if location_name.lower() in query_lower:
      score += 6
    if current_location and location_name.lower() == str(current_location).lower():
      score += 1
    if score > 0:
      fact = {
        "id": f"location:{location_name}",
        "type": "location",
        "location": location_name,
        "description": location.get("description", ""),
        "available_items": location.get("available_items", []),
        "known_npcs": location.get("known_npcs", []),
        "source": "world_state",
        "confidence": "high",
      }
      fact["content"] = world_fact_text(fact)
      scored.append((score, f"location:{location_name}", fact))
  for route_name, route in (canon.get("trade_routes") or {}).items():
    if not isinstance(route, dict):
      continue
    text = " ".join([route_name, str(route.get("status", "")), "trade route", " ".join(route.get("connects", []) or [])])
    terms = knowledge_keywords(text)
    score = len(query_terms.intersection(terms)) * 3
    if any(term in query_lower for term in ("trade", "route", "routes", "merchant", "market")):
      score += 2
    if score > 0:
      fact = {
        "id": f"trade_route:{route_name}",
        "type": "trade_route",
        "route": route_name,
        "status": route.get("status", ""),
        "connects": route.get("connects", []),
        "source": "world_state",
        "confidence": "high",
      }
      fact["content"] = world_fact_text(fact)
      scored.append((score, f"trade_route:{route_name}", fact))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  seen = set()
  results = []
  for _, fact_id, fact in scored:
    if fact_id in seen:
      continue
    seen.add(fact_id)
    results.append(fact)
    if len(results) >= max_results:
      break
  return results


def world_grounding_context_summary(world_facts):
  facts = [fact for fact in world_facts or [] if isinstance(fact, dict)]
  return {
    "world_fact_count": len(facts),
    "world_fact_ids": [fact.get("id", "") for fact in facts if fact.get("id")],
    "world_facts_used": [fact.get("content") or world_fact_text(fact) for fact in facts],
  }


def check_world_grounding_consistency(text, relevant_world_facts=None, canon=None):
  canon = canon or load_world_canon()
  response = str(text or "")
  response_lower = response.lower()
  known_items = canon_known_items(canon)
  known_locations = canon_known_locations(canon)
  warnings = []
  if "dragon tooth" in response_lower or "dragon teeth" in response_lower:
    warnings.append("Unknown item: dragon teeth")
  explicit_unknown_items = (
    "phoenix feather",
    "unicorn horn",
    "moon crystal",
  )
  for item in explicit_unknown_items:
    if item in response_lower and item not in known_items:
      warnings.append(f"Unknown item: {item}")
  if "blacksmith" in response_lower and "blacksmith" not in known_locations:
    warnings.append("Unknown location: blacksmith")
  response_sentences = [
    sentence.strip().lower()
    for sentence in response.replace("!", ".").replace("?", ".").split(".")
    if sentence.strip()
  ]
  for item_name, item in (canon.get("items") or {}).items():
    if not isinstance(item, dict):
      continue
    item_lower = item_name.lower()
    item_location = str(item.get("location") or "").lower()
    if item_lower not in response_lower:
      continue
    for location_name in (canon.get("locations") or {}).keys():
      location_lower = str(location_name).lower()
      if location_lower == item_location:
        continue
      if any(
          item_lower in sentence
          and location_lower in sentence
          and any(verb in sentence for verb in ("sell", "sells", "buy", "find", "available", "contains"))
          for sentence in response_sentences):
        warnings.append(
          f"Possible contradiction: {item_name} is canonically at {item.get('location')}, not {location_name}."
        )
  if not relevant_world_facts and any(term in response_lower for term in ("definitely", "certainly", "i know")):
    warnings.append("Grounding caution: confident factual answer without relevant world facts.")
  return {
    "grounded": len(warnings) == 0,
    "warnings": warnings,
    "checked_text": response[:500],
    "relevant_world_fact_ids": [
      fact.get("id", "")
      for fact in relevant_world_facts or []
      if isinstance(fact, dict) and fact.get("id")
    ],
  }


def retrieve_relevant_knowledge(npc_name, query, max_results=3, state=None):
  entries = load_npc_knowledge(npc_name, state=state)
  query_terms = knowledge_keywords(query)
  if not query_terms:
    return []
  scored = []
  for index, entry in enumerate(entries):
    text = " ".join(
      [
        str(entry.get("related_goal", "")),
        str(entry.get("location", "")),
        str(entry.get("action", "")),
        " ".join(str(finding) for finding in entry.get("findings", []) if finding),
      ]
    )
    terms = knowledge_keywords(text)
    score = len(query_terms.intersection(terms))
    query_lower = str(query or "").lower()
    if any(token in query_lower for token in ("what did you find", "what did you learn", "find anything", "did you find")):
      score += 2
    if "market" in query_lower and "market" in text.lower():
      score += 2
    if score > 0:
      scored.append((score, index, entry))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  return [entry for _, _, entry in scored[:max_results]]


def knowledge_summary_text(knowledge):
  if not isinstance(knowledge, dict):
    return ""
  interpretation = knowledge.get("interpretation", {})
  if isinstance(interpretation, dict) and interpretation.get("summary"):
    return str(interpretation.get("summary", "")).strip()
  findings = knowledge.get("findings", [])
  if isinstance(findings, list):
    finding_text = "; ".join(str(item) for item in findings if item)
    if finding_text:
      return finding_text
  return str(knowledge.get("related_goal") or knowledge.get("action") or "").strip()


def retrieve_relevant_npc_knowledge(
    npc_name,
    current_goal="",
    current_location="",
    current_task="",
    max_results=3,
    state=None):
  state = state or load_world_state()
  entries = load_npc_knowledge(npc_name, state=state)
  if not entries:
    return []
  query_text = " ".join(
    [
      str(current_goal or ""),
      str(current_location or ""),
      str(current_task or ""),
    ]
  )
  query_terms = knowledge_keywords(query_text)
  location_terms = knowledge_keywords(current_location)
  importance_bonus = {"high": 3, "medium": 2, "low": 1}
  scored = []
  for index, entry in enumerate(entries):
    text = " ".join(
      [
        str(entry.get("related_goal", "")),
        str(entry.get("location", "")),
        str(entry.get("action", "")),
        knowledge_summary_text(entry),
        " ".join(str(finding) for finding in entry.get("findings", []) if finding),
      ]
    )
    terms = knowledge_keywords(text)
    score = 0
    matched = False
    if query_terms:
      overlap = query_terms.intersection(terms)
      if overlap:
        matched = True
        score += len(overlap) * 3
    if location_terms and location_terms.intersection(terms):
      matched = True
      score += 2
    if current_goal and knowledge_keywords(current_goal).intersection(terms):
      matched = True
      score += 4
    score += importance_bonus.get(str(entry.get("importance", "medium")).lower(), 1)
    score += min(index, 5) * 0.1
    if matched:
      scored.append((score, index, entry))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  return [entry for _, _, entry in scored[:max_results]]


def knowledge_evidence_preview(knowledge, limit=4):
  evidence = knowledge.get("evidence", []) if isinstance(knowledge, dict) else []
  if not isinstance(evidence, list):
    return []
  lines = []
  for item in evidence:
    if not isinstance(item, dict):
      continue
    content = str(item.get("content") or "").strip()
    if not content:
      continue
    evidence_type = str(item.get("type") or "evidence").strip()
    source_npc = str(item.get("source_npc") or "").strip()
    prefix = evidence_type
    if source_npc:
      prefix = f"{prefix} from {source_npc}"
    lines.append(f"{prefix}: {content}")
    if len(lines) >= limit:
      break
  return lines


def dialogue_knowledge_context_summary(knowledge_entries):
  knowledge_ids = []
  knowledge_used = []
  for item in knowledge_entries or []:
    if not isinstance(item, dict):
      continue
    knowledge_id = str(item.get("knowledge_id") or "").strip()
    if knowledge_id:
      knowledge_ids.append(knowledge_id)
    summary = knowledge_summary_text(item)
    if summary:
      knowledge_used.append(summary)
  return {
    "knowledge_count": len(knowledge_used),
    "knowledge_ids": knowledge_ids,
    "knowledge_used": knowledge_used,
  }


def retrieve_relevant_dialogue_knowledge(
    npc_name,
    player_message,
    current_goal="",
    current_location="",
    max_results=3,
    state=None):
  state = state or load_world_state()
  entries = load_npc_knowledge(npc_name, state=state)
  if not entries:
    return []
  message_lower = str(player_message or "").lower()
  message_terms = knowledge_keywords(player_message)
  goal_terms = knowledge_keywords(current_goal)
  location_terms = knowledge_keywords(current_location)
  asks_about_findings = any(
    phrase in message_lower
    for phrase in (
      "what did you find",
      "what did you learn",
      "did you find",
      "find anything",
      "from the vendors",
      "from vendors",
      "why are you worried",
      "why should we care",
      "trade issues",
    )
  )
  scored = []
  importance_bonus = {"high": 3, "medium": 2, "low": 1}
  for index, entry in enumerate(entries):
    interpretation = entry.get("interpretation", {})
    implications = []
    if isinstance(interpretation, dict) and isinstance(interpretation.get("implications"), list):
      implications = interpretation.get("implications", [])
    text = " ".join(
      [
        str(entry.get("related_goal", "")),
        str(entry.get("location", "")),
        str(entry.get("action", "")),
        knowledge_summary_text(entry),
        " ".join(str(finding) for finding in entry.get("findings", []) if finding),
        " ".join(str(implication) for implication in implications if implication),
        " ".join(knowledge_evidence_preview(entry, limit=6)),
      ]
    )
    terms = knowledge_keywords(text)
    score = 0
    matched = False
    if goal_terms:
      overlap = goal_terms.intersection(terms)
      if overlap:
        matched = True
        score += len(overlap) * 5
    if message_terms:
      overlap = message_terms.intersection(terms)
      if overlap:
        matched = True
        score += len(overlap) * 4
    if location_terms:
      overlap = location_terms.intersection(terms)
      if overlap:
        matched = True
        score += len(overlap) * 2
    if asks_about_findings and entry.get("findings"):
      matched = True
      score += 6
    score += importance_bonus.get(str(entry.get("importance", "medium")).lower(), 1)
    score += min(index, 5) * 0.1
    if matched:
      scored.append((score, index, entry))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  return [entry for _, _, entry in scored[:max_results]]


def retrieve_goal_state_context(npc_name, query="", max_results=5, state=None):
  state = state or load_world_state()
  goals = sync_npc_goals_from_memory(npc_name, state=state, save=False)
  query_terms = knowledge_keywords(query)
  query_lower = str(query or "").lower()
  scored = []
  for index, goal in enumerate(goals):
    if not isinstance(goal, dict):
      continue
    goal_text = " ".join(
      [
        str(goal.get("goal", "")),
        str(goal.get("reason", "")),
        str(goal.get("target_location", "")),
        " ".join(str(action) for action in goal.get("actions", []) if action),
      ]
    )
    goal_terms = knowledge_keywords(goal_text)
    score = len(query_terms.intersection(goal_terms))
    if "market" in query_lower and "market" in goal_text.lower():
      score += 3
    if any(token in query_lower for token in ("what did you find", "did you find", "what did you learn", "vendors")):
      score += 2
    if str(goal.get("status", "")).lower() == "completed":
      score += 2
    if score > 0 or str(goal.get("status", "")).lower() == "completed":
      scored.append((score, index, goal))
  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  return [goal for _, _, goal in scored[:max_results]]


def collect_planning_context(npc_name, agent_config=None):
  agent_config = agent_config or load_agent_config()
  state = load_world_state()
  raw_memories = deduplicate_context_items(load_npc_memory(npc_name), ["type", "content"], max_items=None)
  memories = raw_memories if agent_config.get("use_memory", True) else []
  reflections = deduplicate_context_items(load_reflections(npc_name), ["reflection"], max_items=5) if agent_config.get("use_memory", True) else []
  observations = deduplicate_context_items(load_observations(npc_name), ["type", "content"], max_items=5) if agent_config.get("use_memory", True) else []
  completed_requests = [
    memory for memory in memories
    if str(memory.get("type", "")).lower() == "request"
    and str(memory.get("status", "")).lower() == "completed"
  ]
  pending_requests = [
    memory for memory in memories
    if str(memory.get("type", "")).lower() in {"request", "report"}
    and str(memory.get("status", "")).lower() == "pending"
  ]
  npc_goals = sync_npc_goals_from_memory(npc_name, state=state, save=True)
  profile = npc_profile(npc_name, state)
  active_goals = [
    goal for goal in npc_goals
    if str(goal.get("status", "pending")).lower() == "pending"
  ]
  goal_query = " ".join(
    " ".join(
      [
        str(goal.get("goal", "")),
        str(goal.get("target_location", "")),
        " ".join(str(action) for action in goal.get("actions", []) if action),
      ]
    )
    for goal in active_goals
    if isinstance(goal, dict)
  )
  relevant_knowledge = retrieve_relevant_npc_knowledge(
    npc_name=npc_name,
    current_goal=goal_query,
    current_location=profile.get("workplace", ""),
    current_task=" ".join(profile.get("goals", [])),
    max_results=3,
    state=state,
  ) if agent_config.get("use_knowledge", True) else []
  relevant_npc_beliefs = []
  if agent_config.get("use_world_grounding", True) and agent_config.get("use_belief", True):
    relevant_npc_beliefs = retrieve_relevant_npc_beliefs(
      npc_name=npc_name,
      query=" ".join(
        [
          goal_query,
          profile.get("workplace", ""),
          " ".join(profile.get("goals", [])),
        ]
      ),
      current_location=profile.get("workplace", ""),
      current_goal=goal_query,
      max_results=5,
    )
  return {
    "agent_config": agent_config,
    "npc_profile": profile,
    "recent_memories": memories[-5:],
    "reflections": reflections[-5:],
    "observations": observations[-5:],
    "completed_requests": deduplicate_context_items(completed_requests, ["type", "content"], max_items=5),
    "pending_requests": deduplicate_context_items(pending_requests, ["type", "content"], max_items=None),
    "npc_goals": active_goals,
    "relevant_knowledge": relevant_knowledge,
    "relevant_npc_beliefs": relevant_npc_beliefs,
    "world_state": {
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "07:00"),
      "previous_day_summary": state.get("previous_day_summary", []),
      "completed_events": state.get("completed_events", [])[-5:],
      "recent_observations": state.get("recent_observations", [])[-5:],
      "active_requests": state.get("active_requests", [])[-5:],
    },
  }


def deterministic_daily_planner(npc_name, context, day=None):
  combined = " ".join(
    [
      _memory_text(context.get("recent_memories", []), "content", "action", "topic"),
      _memory_text(context.get("reflections", []), "reflection"),
      _memory_text(context.get("observations", []), "content", "action"),
      _memory_text(context.get("completed_requests", []), "content", "action", "topic"),
      _memory_text(context.get("pending_requests", []), "content", "action", "topic"),
      _memory_text(context.get("npc_goals", []), "goal", "target_location", "reason"),
      _memory_text(context.get("relevant_knowledge", []), "related_goal", "location", "action"),
      " ".join(knowledge_summary_text(item).lower() for item in context.get("relevant_knowledge", [])),
    ]
  )
  locations = default_npc_persistent_locations().get(npc_name, {})
  home = locations.get("home", "Home")
  workplace = locations.get("workplace", "Village")
  if npc_name == "Mira Chen":
    afternoon_action = "visit market"
    if "completed" in combined and "market" in combined:
      afternoon_action = "review market information"
    return [
      {"time": "07:00", "action": "wake up", "location": home, "duration": 30, "from_location": home, "to_location": home, "life_state": "sleep_to_awake"},
      {"time": "08:00", "action": "open tea shop", "location": workplace, "duration": 60, "from_location": home, "to_location": workplace, "life_state": "travel_to_work"},
      {"time": "10:00", "action": "serve tea shop customers", "location": workplace, "duration": 180, "from_location": workplace, "to_location": workplace, "life_state": "work"},
      {"time": "14:00", "action": afternoon_action, "location": "Market", "duration": 60, "from_location": workplace, "to_location": "Market", "life_state": "social_activity"},
      {"time": "17:00", "action": "return home", "location": home, "duration": 90, "from_location": "Market", "to_location": home, "life_state": "return_home"},
      {"time": "22:00", "action": "sleep", "location": home, "duration": 480, "from_location": home, "to_location": home, "life_state": "sleep"},
    ]
  if npc_name == "Tovan Reed":
    afternoon_action = "market patrol"
    if any(term in combined for term in ("suspicious", "rumor", "uncertain")):
      afternoon_action = "investigate suspicious market report"
    return [
      {"time": "07:00", "action": "wake up", "location": home, "duration": 30, "from_location": home, "to_location": home, "life_state": "sleep_to_awake"},
      {"time": "08:00", "action": "guard post patrol", "location": workplace, "duration": 180, "from_location": home, "to_location": workplace, "life_state": "work"},
      {"time": "14:00", "action": afternoon_action, "location": "Market", "duration": 60, "from_location": workplace, "to_location": "Market", "life_state": "patrol"},
      {"time": "17:00", "action": "return to guard post", "location": workplace, "duration": 60, "from_location": "Market", "to_location": workplace, "life_state": "return_to_work"},
      {"time": "20:00", "action": "write evening guard notes", "location": workplace, "duration": 60, "from_location": workplace, "to_location": workplace, "life_state": "evening_work"},
      {"time": "22:00", "action": "return home and sleep", "location": home, "duration": 60, "from_location": workplace, "to_location": home, "life_state": "sleep"},
    ]
  if npc_name == "Lysa Vale":
    afternoon_action = "visit merchants"
    if any(term in combined for term in ("trade", "vendor", "merchant")):
      afternoon_action = "visit merchants about trade conditions"
    return [
      {"time": "07:00", "action": "wake up", "location": home, "duration": 30, "from_location": home, "to_location": home, "life_state": "sleep_to_awake"},
      {"time": "08:00", "action": "visit market stalls", "location": workplace, "duration": 180, "from_location": home, "to_location": workplace, "life_state": "work"},
      {"time": "14:00", "action": afternoon_action, "location": workplace, "duration": 60, "from_location": workplace, "to_location": workplace, "life_state": "trade_activity"},
      {"time": "18:00", "action": "review trade notes", "location": home, "duration": 60, "from_location": workplace, "to_location": home, "life_state": "return_home"},
      {"time": "22:00", "action": "sleep", "location": home, "duration": 480, "from_location": home, "to_location": home, "life_state": "sleep"},
    ]
  return [
    {"time": "07:00", "action": "wake up", "location": home, "duration": 30, "from_location": home, "to_location": home, "life_state": "sleep_to_awake"},
    {"time": "08:00", "action": "start daily routine", "location": workplace, "duration": 180, "from_location": home, "to_location": workplace, "life_state": "work"},
    {"time": "17:00", "action": "return home", "location": home, "duration": 60, "from_location": workplace, "to_location": home, "life_state": "return_home"},
    {"time": "22:00", "action": "sleep", "location": home, "duration": 480, "from_location": home, "to_location": home, "life_state": "sleep"},
  ]


def build_llm_daily_planner_prompt(npc_name, context, day):
  profile = context.get("npc_profile") or npc_profile(npc_name)
  world_state = context.get("world_state", {})
  agent_config = context.get("agent_config") or load_agent_config()
  prompt = {
    "instruction": (
      "You are planning the next day for an NPC in a persistent game world. "
      "Generate a realistic daily schedule. Your response must be valid JSON only. "
      "Do not include markdown, explanations, code fences, or comments. "
      "The first character must be { and the last character must be }."
    ),
    "schema": {
      "day": "integer",
      "schedule": [
        {
          "time": "HH:MM",
          "action": "string",
          "location": "string",
          "duration": "integer minutes",
          "from_location": "string",
          "to_location": "string",
          "life_state": "string",
        }
      ],
    },
    "character": {
      "name": npc_name,
      "personality": profile.get("personality", ""),
      "goals": profile.get("goals", []),
      "home": profile.get("home", "Home"),
      "workplace": profile.get("workplace", "Village"),
    },
    "agent_configuration": agent_config,
    "previous_memories": _summarize_items(
      context.get("recent_memories", []),
      ["type", "content", "action", "topic", "status"],
    ),
    "recent_observations": _summarize_items(
      context.get("observations", []),
      ["content", "action", "world_time"],
    ),
    "reflections": _summarize_items(
      context.get("reflections", []),
      ["reflection", "importance"],
    ),
    "completed_requests": _summarize_items(
      context.get("completed_requests", []),
      ["content", "action", "topic", "status"],
    ),
    "pending_requests": _summarize_items(
      context.get("pending_requests", []),
      ["content", "action", "topic", "status"],
    ),
    "active_player_goals": _summarize_items(
      context.get("npc_goals", []),
      ["goal", "source", "reason", "target_location", "actions", "deadline", "status"],
    ),
    "relevant_previous_knowledge": _summarize_items(
      [
        {
          "knowledge_id": item.get("knowledge_id", ""),
          "summary": knowledge_summary_text(item),
          "related_goal": item.get("related_goal", ""),
          "location": item.get("location", ""),
          "importance": item.get("importance", ""),
        }
        for item in context.get("relevant_knowledge", [])
      ],
      ["knowledge_id", "summary", "related_goal", "location", "importance"],
    ),
    "relevant_npc_belief_context": _summarize_items(
      context.get("relevant_npc_beliefs", []),
      ["fact_id", "content", "source", "source_type", "confidence"],
    ),
    "world_state": world_state,
    "target_day": int(day or 1),
    "allowed_locations": ["Home", "Tea Shop", "Market", "Guard Post", "Inn", "Village"],
    "rules": [
      "Maintain NPC personality.",
      "Use memories only when relevant.",
      "Unfinished requests should influence future plans.",
      "Do not ignore normal life routines.",
      "Include home, work, and social or activity periods.",
      "Do not invent impossible locations.",
      "Do not control low-level movement or pathfinding.",
      "When the NPC has active player goals, convert them into concrete schedule actions.",
      "Consider Relevant Previous Knowledge when creating today's schedule.",
      "Consider Relevant NPC Belief Context when choosing locations, resources, and trade actions.",
      "Do not ignore important previous knowledge.",
      "Do not invent new facts from previous knowledge.",
      "Do not schedule the NPC based on world truth that is not present in Relevant NPC Belief Context or the NPC's own memories.",
      "If a needed resource is not in NPC belief context, plan to ask or investigate rather than assert it exists.",
      "Use appropriate locations for active player goals.",
      "Include travel if a goal destination differs from the NPC's workplace or current routine.",
      "Do not only write vague actions like help player, assist request, or follow up.",
      "Generate executable actions such as travel to market and talk with vendors.",
      "Return JSON only with keys: day, schedule.",
      "Do not include ``` fences.",
      "Do not include trailing comments.",
      "Each schedule item needs time, action, location, duration, from_location, to_location, and life_state.",
    ],
    "bad_goal_action_example": {
      "time": "10:00",
      "action": "assist player request",
      "location": "Tea Shop",
    },
    "good_goal_action_example": {
      "time": "10:00",
      "action": "travel to market and talk with vendors",
      "location": "Market",
      "duration": 90,
      "from_location": "Tea Shop",
      "to_location": "Market",
      "life_state": "player_goal_followup",
    },
  }
  return json.dumps(prompt, ensure_ascii=False, indent=2)


def extract_json_object(text):
  raw = str(text or "").strip()
  if not raw:
    raise ValueError("LLM planner returned empty text.")
  start = raw.find("{")
  end = raw.rfind("}")
  if start < 0 or end < start:
    raise ValueError("LLM planner output did not contain a JSON object.")
  extracted = raw[start:end + 1]
  try:
    return json.loads(extracted)
  except json.JSONDecodeError as exc:
    raise ValueError(f"LLM planner JSON parse failed: {exc}") from exc


def planner_goal_warnings(schedule, active_goals):
  warnings = []
  schedule_text = " ".join(
    str(item.get(field, ""))
    for item in schedule or []
    for field in ("action", "location", "from_location", "to_location", "life_state")
  ).lower()
  for goal in active_goals or []:
    if not isinstance(goal, dict):
      continue
    goal_name = str(goal.get("goal") or "player goal").strip()
    target_location = str(goal.get("target_location") or goal.get("location") or "").strip().lower()
    actions = " ".join(str(action) for action in goal.get("actions", []) if action)
    goal_text = " ".join(
      [
        goal_name,
        str(goal.get("reason", "")),
        target_location,
        actions,
      ]
    ).lower()
    if "market" in goal_text and "market" not in schedule_text:
      warnings.append(f"Planner ignored active player goal: {goal_name}")
      continue
    meaningful_terms = [
      term for term in goal_text.replace("_", " ").split()
      if len(term) > 4 and term not in {"player", "request", "requested", "conditions"}
    ]
    if meaningful_terms and not any(term in schedule_text for term in meaningful_terms[:8]):
      warnings.append(f"Planner may have ignored active player goal: {goal_name}")
    if target_location and target_location not in schedule_text:
      warnings.append(f"Planner did not schedule the target location for active player goal: {goal_name}")
  return warnings


def validate_daily_plan(payload, npc_name, day, active_goals=None):
  if not isinstance(payload, dict):
    raise ValueError("LLM planner JSON is not an object.")
  if "day" not in payload:
    raise ValueError("LLM planner JSON missing day.")
  try:
    parsed_day = int(payload.get("day"))
  except (TypeError, ValueError) as exc:
    raise ValueError("LLM planner day must be an integer.") from exc
  raw_schedule = payload.get("schedule")
  if not isinstance(raw_schedule, list):
    raise ValueError("LLM planner JSON missing schedule list.")
  schedule = []
  for item in raw_schedule:
    if not isinstance(item, dict):
      continue
    time_text = normalize_schedule_time(item.get("time"))
    action = str(item.get("action", "")).strip()
    location = str(item.get("location") or item.get("to_location") or "").strip()
    if not time_text or not action or not location:
      continue
    clean = dict(item)
    clean.update(
      {
        "time": time_text,
        "action": action,
        "location": location,
        "life_state": str(item.get("life_state") or "activity").strip(),
      }
    )
    if clean.get("duration") in (None, ""):
      clean["duration"] = 60
    try:
      clean["duration"] = int(clean.get("duration"))
    except (TypeError, ValueError):
      clean["duration"] = 60
    if not clean.get("from_location"):
      clean["from_location"] = location
    if not clean.get("to_location"):
      clean["to_location"] = location
    schedule.append(clean)
  if not schedule:
    raise ValueError("LLM planner schedule had no usable actions.")
  schedule.sort(key=lambda entry: time_to_minutes(entry.get("time", "00:00")))
  return {
    "day": parsed_day or int(day or 1),
    "schedule": schedule,
    "warnings": planner_goal_warnings(schedule, active_goals or []),
  }


def validate_daily_schedule_payload(payload, npc_name, day):
  return validate_daily_plan(payload, npc_name, day)


def llm_daily_planner(npc_name, context, day=None):
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    raise RuntimeError("DEEPSEEK_API_KEY is not set.")
  prompt = build_llm_daily_planner_prompt(npc_name, context, day)
  payload = {
    "model": os.environ.get("DEEPSEEK_DAILY_PLANNER_MODEL", "deepseek-v4-flash"),
    "messages": [
      {
        "role": "system",
        "content": (
          "You generate NPC daily plans for a persistent game world. "
          "Return valid JSON only. Do not include reasoning, markdown, or commentary."
        ),
      },
      {"role": "user", "content": prompt},
    ],
    "thinking": {"type": "disabled"},
    "temperature": 0.4,
    "max_tokens": 4096,
  }
  started = datetime.datetime.now()
  request = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json",
    },
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=60) as response:
      response_payload = json.loads(response.read().decode("utf-8"))
  except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    raise RuntimeError(f"DeepSeek planner request failed: HTTP {exc.code}: {body[:500]}") from exc
  except urllib.error.URLError as exc:
    raise RuntimeError(f"DeepSeek planner request failed: {exc}") from exc
  try:
    choice = response_payload["choices"][0]
    content = str(choice["message"].get("content") or "").strip()
  except (KeyError, IndexError, TypeError) as exc:
    raise RuntimeError("DeepSeek planner response did not include choices[0].message.content.") from exc
  finish_reason = ""
  usage = {}
  try:
    finish_reason = response_payload["choices"][0].get("finish_reason", "")
  except (KeyError, IndexError, TypeError):
    finish_reason = ""
  if isinstance(response_payload.get("usage"), dict):
    usage = response_payload.get("usage", {})
  debug_log_path = save_llm_planner_raw_response(
    {
      "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
      "npc": npc_name,
      "day": int(day or 1),
      "model": payload["model"],
      "max_tokens": payload["max_tokens"],
      "finish_reason": finish_reason,
      "content": content,
      "content_length": len(content),
      "usage": usage,
    }
  )
  if not content:
    raise RuntimeError(
      "DeepSeek planner returned empty content. "
      f"finish_reason={finish_reason}; max_tokens={payload['max_tokens']}; "
      f"debug_log={debug_log_path}"
    )
  parsed = validate_daily_plan(
    extract_json_object(content),
    npc_name,
    day,
    active_goals=context.get("npc_goals", []),
  )
  elapsed_sec = (datetime.datetime.now() - started).total_seconds()
  return {
    "schedule": parsed["schedule"],
    "metadata": {
      "planner_attempt": True,
      "requested_planner": "llm",
      "planner": "llm",
      "model": payload["model"],
      "prompt_chars": len(prompt),
      "raw_response_length": len(content),
      "raw_reply_chars": len(content),
      "finish_reason": finish_reason,
      "usage": usage,
      "max_tokens": payload["max_tokens"],
      "debug_log_path": debug_log_path,
      "parsed_successfully": True,
      "validation_warnings": parsed.get("warnings", []),
      "elapsed_sec": elapsed_sec,
    },
  }


def generate_daily_plan(npc_name, context, day=None, planner_mode="deterministic"):
  if planner_mode == "llm":
    try:
      llm_result = llm_daily_planner(npc_name, context, day=day)
      return {
        "schedule": llm_result["schedule"],
        "planner": "llm",
        "planner_error": "",
        "planner_metadata": llm_result.get("metadata", {}),
      }
    except Exception as exc:
      return {
        "schedule": deterministic_daily_planner(npc_name, context, day=day),
        "planner": "deterministic_fallback",
        "planner_error": str(exc),
        "planner_metadata": {
          "planner_attempt": True,
          "requested_planner": "llm",
          "model": os.environ.get("DEEPSEEK_DAILY_PLANNER_MODEL", "deepseek-v4-flash"),
          "max_tokens": 4096,
          "parsed_successfully": False,
          "fallback_reason": str(exc),
        },
      }
  return {
    "schedule": deterministic_daily_planner(npc_name, context, day=day),
    "planner": "deterministic",
    "planner_error": "",
    "planner_metadata": {
      "planner_attempt": False,
      "requested_planner": "deterministic",
      "parsed_successfully": False,
    },
  }


def planner_context_summary(context):
  agent_config = context.get("agent_config") or load_agent_config()
  knowledge = [
    item for item in context.get("relevant_knowledge", [])
    if isinstance(item, dict)
  ]
  npc_beliefs = [
    item for item in context.get("relevant_npc_beliefs", [])
    if isinstance(item, dict)
  ]
  return {
    "agent_config": agent_config.get("name", "full_agent"),
    "use_memory": agent_config.get("use_memory", True),
    "use_knowledge": agent_config.get("use_knowledge", True),
    "use_relationship": agent_config.get("use_relationship", True),
    "use_world_grounding": agent_config.get("use_world_grounding", True),
    "use_belief": agent_config.get("use_belief", True),
    "recent_memory_count": len(context.get("recent_memories", [])),
    "reflection_count": len(context.get("reflections", [])),
    "observation_count": len(context.get("observations", [])),
    "completed_request_count": len(context.get("completed_requests", [])),
    "pending_request_count": len(context.get("pending_requests", [])),
    "npc_goal_count": len(context.get("npc_goals", [])),
    "knowledge_count": len(knowledge),
    "knowledge_ids": [
      str(item.get("knowledge_id") or "")
      for item in knowledge
      if item.get("knowledge_id")
    ],
    "knowledge_used": [
      knowledge_summary_text(item)
      for item in knowledge
      if knowledge_summary_text(item)
    ],
    "belief_count": len(npc_beliefs),
    "belief_ids": [
      str(item.get("fact_id") or item.get("id") or "")
      for item in npc_beliefs
      if item.get("fact_id") or item.get("id")
    ],
    "beliefs_used": [
      str(item.get("content") or "")
      for item in npc_beliefs
      if item.get("content")
    ],
  }


def generate_daily_plans_for_day(day, planner_mode=None):
  state = load_world_state()
  mode = planner_mode or state.get("planner_mode", "deterministic")
  if mode not in {"deterministic", "llm"}:
    mode = "deterministic"
  plans = {}
  metadata = {}
  for npc in sorted(ALLOWED_MEMORY_NPCS):
    context = collect_planning_context(npc)
    plan_result = generate_daily_plan(npc, context, day=day, planner_mode=mode)
    context_counts = planner_context_summary(context)
    planner_metadata = dict(plan_result.get("planner_metadata", {}))
    planner_metadata["planner_context_summary"] = context_counts
    plans[npc] = {
      "day": int(day or 1),
      "schedule": plan_result["schedule"],
      "planning_context": context_counts,
      "planner": plan_result["planner"],
      "planner_error": plan_result.get("planner_error", ""),
      "planner_metadata": planner_metadata,
      "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    metadata[npc] = {
      "planning_context": context_counts,
      "planner": plan_result["planner"],
      "planner_error": plan_result.get("planner_error", ""),
      "planner_metadata": planner_metadata,
    }
  return plans, metadata


def regenerate_daily_plan_for_day(day=None, npc_name=None):
  state = load_world_state()
  target_day = int(day or state.get("current_day") or 1)
  mode = state.get("planner_mode", "deterministic")
  if mode not in {"deterministic", "llm"}:
    mode = "deterministic"
  key = daily_plan_key(target_day)
  daily_plans = state.get("npc_daily_plans", {})
  existing_day_plans = daily_plans.get(key, {})
  generated_npcs = []
  metadata = {}
  if npc_name:
    npc = str(npc_name).replace("_", " ").strip()
    if npc not in ALLOWED_MEMORY_NPCS:
      raise ValueError(f"Unsupported NPC for daily plan regeneration: {npc_name}")
    context = collect_planning_context(npc)
    plan_result = generate_daily_plan(npc, context, day=target_day, planner_mode=mode)
    context_counts = planner_context_summary(context)
    planner_metadata = dict(plan_result.get("planner_metadata", {}))
    planner_metadata["planner_context_summary"] = context_counts
    existing_day_plans[npc] = {
      "day": target_day,
      "schedule": plan_result["schedule"],
      "planning_context": context_counts,
      "planner": plan_result["planner"],
      "planner_error": plan_result.get("planner_error", ""),
      "planner_metadata": planner_metadata,
      "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    generated_npcs.append(npc)
    metadata[npc] = {
      "planning_context": context_counts,
      "planner": plan_result["planner"],
      "planner_error": plan_result.get("planner_error", ""),
      "planner_metadata": planner_metadata,
    }
    daily_plans[key] = existing_day_plans
  else:
    plans, metadata = generate_daily_plans_for_day(target_day, planner_mode=mode)
    daily_plans[key] = plans
    generated_npcs = sorted(plans.keys())
  planner_counts = {}
  planner_sources = {}
  planner_errors = {}
  for npc, entry in metadata.items():
    planner_counts[npc] = entry.get("planning_context", {})
    planner_sources[npc] = entry.get("planner", "")
    if entry.get("planner_error"):
      planner_errors[npc] = entry.get("planner_error")
  state["npc_daily_plans"] = daily_plans
  state["last_daily_planning"] = {
    "day": target_day,
    "planner": mode,
    "planner_sources": planner_sources,
    "planner_errors": planner_errors,
    "context_counts": planner_counts,
    "generated_npcs": generated_npcs,
    "manual_regeneration": True,
    "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  return save_world_state(state), generated_npcs


def ensure_daily_plan_for_current_day(state=None, force=False):
  state = state or load_world_state()
  day = int(state.get("current_day") or 1)
  key = daily_plan_key(day)
  daily_plans = state.get("npc_daily_plans", {})
  if key in daily_plans and not force:
    return state
  plans, metadata = generate_daily_plans_for_day(day)
  daily_plans[key] = plans
  state["npc_daily_plans"] = daily_plans
  planner_counts = {}
  planner_sources = {}
  planner_errors = {}
  for npc, entry in metadata.items():
    planner_counts[npc] = entry.get("planning_context", {})
    planner_sources[npc] = entry.get("planner", "")
    if entry.get("planner_error"):
      planner_errors[npc] = entry.get("planner_error")
  state["last_daily_planning"] = {
    "day": day,
    "planner": state.get("planner_mode", "deterministic"),
    "planner_sources": planner_sources,
    "planner_errors": planner_errors,
    "context_counts": planner_counts,
    "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  return save_world_state(state)


def set_planner_mode(planner_mode, regenerate_current_day=True):
  state = load_world_state()
  mode = str(planner_mode or "deterministic").strip().lower()
  if mode not in {"deterministic", "llm"}:
    mode = "deterministic"
  state["planner_mode"] = mode
  state = save_world_state(state)
  if regenerate_current_day:
    state = ensure_daily_plan_for_current_day(state, force=True)
  return state


def schedules_for_current_day(state):
  state = ensure_daily_plan_for_current_day(state)
  day = int(state.get("current_day") or 1)
  day_plans = state.get("npc_daily_plans", {}).get(daily_plan_key(day), {})
  grouped = {}
  for npc, plan in day_plans.items():
    schedule = plan.get("schedule", []) if isinstance(plan, dict) else []
    grouped[npc] = schedule
  return grouped


def observation_for_scheduled_action(npc, action):
  lowered = str(action or "").lower()
  if "visit market" in lowered or ("market" in lowered and "vendor" in lowered):
    return f"{npc} visited the market and gathered market information."
  if "open shop" in lowered or "open tea shop" in lowered or "open the tea shop" in lowered:
    return f"{npc} opened the tea shop."
  if "close shop" in lowered or "close the tea shop" in lowered:
    return f"{npc} closed the tea shop."
  if "return home" in lowered or "sleep" in lowered:
    return f"{npc} returned home and settled into the evening routine."
  return f"{npc} completed the scheduled action: {action}."


def observation_for_arrival(npc, action, location):
  if location:
    return f"{npc} arrived at {location} to {action}."
  return f"{npc} arrived to continue the scheduled action: {action}."


def source_memory_id_for_schedule_action(npc, action):
  action_terms = {part for part in str(action or "").lower().split() if len(part) > 2}
  try:
    memories = load_npc_memory(npc)
  except Exception:
    return ""
  for memory in reversed(memories):
    if str(memory.get("type", "")).lower() != "request":
      continue
    if str(memory.get("status", "")).lower() != "pending":
      continue
    memory_text = " ".join(
      [
        str(memory.get("action", "")),
        str(memory.get("topic", "")),
        str(memory.get("content", "")),
      ]
    ).lower()
    if action_terms and any(term in memory_text for term in action_terms):
      return str(memory.get("id") or memory.get("memory_id") or "").strip()
  return ""


def execute_scheduled_actions(state=None):
  state = state or load_world_state()
  state = ensure_daily_plan_for_current_day(state)
  current_time = normalize_schedule_time(state.get("current_time", ""))
  current_day = int(state.get("current_day") or 1)
  schedules = extract_npc_schedule(schedules_for_current_day(state))
  active_actions = list(state.get("active_actions", []))
  completed_actions = list(state.get("completed_actions", []))
  existing_keys = {
    (
      str(action.get("npc", "")),
      int(action.get("world_day") or 0),
      str(action.get("world_time", "")),
      str(action.get("action", "")),
    )
    for action in active_actions + completed_actions
  }
  executed = []
  for item in schedules:
    if normalize_schedule_time(item.get("time")) != current_time:
      continue
    key = (item["npc"], current_day, current_time, item["action"])
    if key in existing_keys:
      continue
    action_state = {
      "npc": item["npc"],
      "action": item["action"],
      "location": item.get("location", ""),
      "from_location": item.get("from_location", ""),
      "to_location": item.get("to_location") or item.get("location", ""),
      "duration": item.get("duration", ""),
      "life_state": item.get("life_state", ""),
      "status": "executing",
      "world_day": current_day,
      "world_time": current_time,
      "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    source_memory_id = source_memory_id_for_schedule_action(item["npc"], item["action"])
    action_state["source_memory_id"] = source_memory_id
    spatial_route = None
    spatial_error = ""
    try:
      from .npc_spatial_state import load_npc_spatial_state, start_spatial_movement
      from .persistent_movement_adapter import create_persistent_route
      spatial_state = load_npc_spatial_state()
      current_tile = (spatial_state.get(item["npc"], {}) or {}).get("current_tile")
      spatial_route = create_persistent_route(
        item["npc"],
        item["action"],
        item.get("to_location") or item.get("location", ""),
        current_tile,
      )
      start_spatial_movement(action_state, spatial_route)
    except Exception as exc:
      spatial_error = str(exc)
    action_state["spatial_route"] = spatial_route
    action_state["spatial_error"] = spatial_error
    observation = None
    observation_error = ""
    if spatial_error or not spatial_route or not spatial_route.get("route"):
      try:
        from .npc_memory import write_observation_entry
        observation = write_observation_entry(
          item["npc"],
          item["action"],
          time_text="",
          importance="medium",
          source_memory_id=source_memory_id,
          content_override=observation_for_scheduled_action(item["npc"], item["action"]),
        )
      except Exception as exc:
        observation_error = str(exc)
    action_state["observation"] = observation
    action_state["observation_error"] = observation_error
    active_actions.append(action_state)
    if observation:
      completed_action = dict(action_state)
      completed_action["status"] = "completed"
      completed_action["completed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
      knowledge_entry = create_task_result_knowledge(state, completed_action, observation)
      if knowledge_entry:
        completed_action["knowledge_entry"] = knowledge_entry
      completed_actions.append(completed_action)
    executed.append(action_state)
  state["active_actions"] = active_actions[-20:]
  state["completed_actions"] = completed_actions[-50:]
  state["last_executed_actions"] = executed
  return state


def record_spatial_arrival_observations(arrivals):
  recorded = []
  if not arrivals:
    return recorded
  for arrival in arrivals:
    try:
      from .npc_memory import write_observation_entry
      from .npc_spatial_state import arrival_observation_text
      observation = write_observation_entry(
        arrival.get("npc", ""),
        arrival.get("action", ""),
        time_text="",
        importance="medium",
        source_memory_id=arrival.get("source_memory_id", ""),
        content_override=observation_for_arrival(
          arrival.get("npc", "NPC"),
          arrival.get("action", "continue the scheduled action"),
          arrival.get("target_location", ""),
        ),
      )
      recorded.append(observation)
    except Exception as exc:
      recorded.append(
        {
          "npc": arrival.get("npc", ""),
          "error": str(exc),
        }
      )
  return recorded


def complete_arrived_actions(state, arrivals):
  if not arrivals:
    return state
  active_actions = list(state.get("active_actions", []))
  completed_actions = list(state.get("completed_actions", []))
  remaining_actions = []
  for action in active_actions:
    matched_arrival = None
    for arrival in arrivals:
      if (
          str(action.get("npc", "")) == str(arrival.get("npc", ""))
          and str(action.get("action", "")) == str(arrival.get("action", ""))):
        matched_arrival = arrival
        break
    if not matched_arrival:
      remaining_actions.append(action)
      continue
    completed_action = dict(action)
    completed_action["status"] = "completed"
    completed_action["completed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    completed_action["completed_world_day"] = matched_arrival.get("world_day", "")
    completed_action["completed_world_time"] = matched_arrival.get("world_time", "")
    knowledge_entry = create_task_result_knowledge(state, completed_action)
    if knowledge_entry:
      completed_action["knowledge_entry"] = knowledge_entry
    completed_actions.append(completed_action)
  state["active_actions"] = remaining_actions[-20:]
  state["completed_actions"] = completed_actions[-50:]
  return state


def _action_key(action):
  return (
    str(action.get("npc", "")),
    int(action.get("world_day") or 0),
    str(action.get("world_time", "")),
    str(action.get("action", "")),
  )


def _update_spatial_state_for_catchup(action_state, route_payload=None):
  try:
    from .npc_spatial_state import load_npc_spatial_state, save_npc_spatial_state
    spatial_state = load_npc_spatial_state()
    npc = action_state.get("npc", "")
    entry = spatial_state.get(npc, {})
    target_location = action_state.get("to_location") or action_state.get("location") or entry.get("current_location")
    target_tile = None
    if route_payload:
      target_tile = route_payload.get("target_tile")
    entry.update(
      {
        "current_location": target_location,
        "current_tile": target_tile or entry.get("current_tile"),
        "target_location": None,
        "target_tile": None,
        "current_action": action_state.get("action", ""),
        "from_location": action_state.get("from_location", ""),
        "movement_status": "idle",
        "route": [],
        "route_index": 0,
        "route_progress": 100,
        "movement_start_time": action_state.get("world_time", ""),
        "estimated_arrival_time": action_state.get("world_time", ""),
        "source_memory_id": action_state.get("source_memory_id", ""),
        "world_day": action_state.get("world_day", ""),
        "world_time": action_state.get("world_time", ""),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
      }
    )
    spatial_state[npc] = entry
    save_npc_spatial_state(spatial_state)
  except Exception:
    return


def process_missed_world_actions(previous_world_time, new_world_time, current_day, state=None):
  state = state or load_world_state()
  state = ensure_daily_plan_for_current_day(state)
  previous_minutes = time_to_minutes(previous_world_time)
  new_minutes = time_to_minutes(new_world_time)
  if new_minutes <= previous_minutes:
    state["last_time_catchup_log"] = []
    return state
  schedules = sorted(
    extract_npc_schedule(schedules_for_current_day(state)),
    key=lambda item: (time_to_minutes(item.get("time", "00:00")), str(item.get("npc", ""))),
  )
  active_actions = list(state.get("active_actions", []))
  completed_actions = list(state.get("completed_actions", []))
  existing_keys = {_action_key(action) for action in active_actions + completed_actions}
  catchup_log = []
  for item in schedules:
    action_time = normalize_schedule_time(item.get("time"))
    action_minutes = time_to_minutes(action_time)
    if not (previous_minutes < action_minutes <= new_minutes):
      continue
    key = (item["npc"], int(current_day or 1), action_time, item["action"])
    if key in existing_keys:
      continue
    source_memory_id = source_memory_id_for_schedule_action(item["npc"], item["action"])
    action_state = {
      "npc": item["npc"],
      "action": item["action"],
      "location": item.get("location", ""),
      "from_location": item.get("from_location", ""),
      "to_location": item.get("to_location") or item.get("location", ""),
      "duration": item.get("duration", ""),
      "life_state": item.get("life_state", ""),
      "status": "completed",
      "catch_up": True,
      "source_memory_id": source_memory_id,
      "world_day": int(current_day or 1),
      "world_time": action_time,
      "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
      "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
      "completed_world_day": int(current_day or 1),
      "completed_world_time": action_time,
    }
    route_payload = None
    spatial_error = ""
    try:
      from .npc_spatial_state import load_npc_spatial_state
      from .persistent_movement_adapter import create_persistent_route
      spatial_state = load_npc_spatial_state()
      current_tile = (spatial_state.get(item["npc"], {}) or {}).get("current_tile")
      route_payload = create_persistent_route(
        item["npc"],
        item["action"],
        item.get("to_location") or item.get("location", ""),
        current_tile,
      )
    except Exception as exc:
      spatial_error = str(exc)
    action_state["spatial_route"] = route_payload
    action_state["spatial_error"] = spatial_error
    observation = None
    observation_error = ""
    try:
      from .npc_memory import write_observation_entry
      observation = write_observation_entry(
        item["npc"],
        item["action"],
        time_text="",
        importance="medium",
        source_memory_id=source_memory_id,
        content_override=observation_for_scheduled_action(item["npc"], item["action"]),
      )
    except Exception as exc:
      observation_error = str(exc)
    action_state["observation"] = observation
    action_state["observation_error"] = observation_error
    knowledge_entry = create_task_result_knowledge(state, action_state, observation)
    if knowledge_entry:
      action_state["knowledge_entry"] = knowledge_entry
    _update_spatial_state_for_catchup(action_state, route_payload)
    completed_actions.append(action_state)
    existing_keys.add(key)
    catchup_log.append(
      {
        "day": int(current_day or 1),
        "time": action_time,
        "npc": item["npc"],
        "action": item["action"],
        "location": item.get("to_location") or item.get("location", ""),
        "observation": observation.get("content", "") if isinstance(observation, dict) else "",
      }
    )
  state["active_actions"] = []
  state["completed_actions"] = completed_actions[-80:]
  state["last_executed_actions"] = catchup_log
  state["last_time_catchup_log"] = catchup_log
  time_catchup_log = list(state.get("time_catchup_log", []))
  if catchup_log:
    time_catchup_log.append(
      {
        "day": int(current_day or 1),
        "from_time": previous_world_time,
        "to_time": new_world_time,
        "actions": catchup_log,
        "processed_at": datetime.datetime.now().isoformat(timespec="seconds"),
      }
    )
  state["time_catchup_log"] = time_catchup_log[-20:]
  return state


def collect_live_memory_world_snapshot():
  completed_events = []
  recent_observations = []
  active_requests = []
  reflections = []

  for npc in sorted(ALLOWED_MEMORY_NPCS):
    memories = load_npc_memory(npc)
    for memory in memories:
      memory_type = str(memory.get("type", "")).lower()
      status = str(memory.get("status", "")).lower()
      if memory_type == "request" and status == "completed":
        completed_events.append(
          {
            "npc": npc,
            "memory_id": memory.get("id") or memory.get("memory_id", ""),
            "content": memory.get("content", ""),
            "completed_time": memory.get("completed_time", ""),
            "world_day": memory.get("world_day", ""),
            "world_time": memory.get("world_time", ""),
            "legacy_replay_time": memory.get("legacy_replay_time", ""),
          }
        )
      elif memory_type == "request" and status == "pending":
        active_requests.append(
          {
            "npc": npc,
            "memory_id": memory.get("id") or memory.get("memory_id", ""),
            "content": memory.get("content", ""),
            "action": memory.get("action", ""),
            "topic": memory.get("topic", ""),
            "time": memory.get("time", ""),
            "world_day": memory.get("world_day", ""),
            "world_time": memory.get("world_time", ""),
            "legacy_replay_time": memory.get("legacy_replay_time", ""),
          }
        )

    recent_observations.extend(
      {
        "npc": npc,
        "content": observation.get("content", ""),
        "action": observation.get("action", ""),
        "time": observation.get("time", ""),
        "world_day": observation.get("world_day", ""),
        "world_time": observation.get("world_time", ""),
        "legacy_replay_time": observation.get("legacy_replay_time", ""),
      }
      for observation in load_observations(npc)[-5:]
      if observation.get("content")
    )
    reflections.extend(
      {
        "npc": npc,
        "reflection": reflection.get("reflection", ""),
        "time": reflection.get("time", ""),
        "world_day": reflection.get("world_day", ""),
        "world_time": reflection.get("world_time", ""),
        "legacy_replay_time": reflection.get("legacy_replay_time", ""),
      }
      for reflection in load_reflections(npc)[-5:]
      if reflection.get("reflection")
    )

  return {
    "completed_events": completed_events,
    "recent_observations": recent_observations[-10:],
    "active_requests": active_requests,
    "recent_reflections": reflections[-10:],
  }


def summarize_previous_day(day, snapshot):
  lines = []
  for request in snapshot.get("active_requests", []):
    line = timed_summary_line("Active request", request)
    if line:
      lines.append(line)
  for event in snapshot.get("completed_events", []):
    line = timed_summary_line("Completed request", event)
    if line:
      lines.append(line)
  for observation in snapshot.get("recent_observations", []):
    line = timed_summary_line("Observation", observation)
    if line:
      lines.append(line)
  for reflection in snapshot.get("recent_reflections", []):
    line = timed_summary_line("Reflection", reflection, text_key="reflection")
    if line:
      lines.append(line)
  return {
    "day": day,
    "summary": lines,
    "completed_events": snapshot.get("completed_events", []),
    "recent_observations": snapshot.get("recent_observations", []),
    "active_requests": snapshot.get("active_requests", []),
    "recent_reflections": snapshot.get("recent_reflections", []),
    "advanced_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }


def advance_day(current_time="23:50"):
  state = load_world_state()
  snapshot = collect_live_memory_world_snapshot()
  previous_day = summarize_previous_day(state.get("current_day", 1), snapshot)
  previous_days = list(state.get("previous_days", []))
  previous_days.append(previous_day)
  next_state = {
    "current_day": int(state.get("current_day") or 1) + 1,
    "current_time": str(current_time or ""),
    "time_step_minutes": int(state.get("time_step_minutes") or 60),
    "last_tick": datetime.datetime.now().isoformat(timespec="seconds"),
    "completed_events": snapshot.get("completed_events", []),
    "recent_observations": snapshot.get("recent_observations", []),
    "active_requests": snapshot.get("active_requests", []),
    "npc_schedules": state.get("npc_schedules", []),
    "npc_daily_plans": state.get("npc_daily_plans", {}),
    "npc_goals": state.get("npc_goals", {}),
    "npc_knowledge": state.get("npc_knowledge", {}),
    "npc_relationships": state.get("npc_relationships", {}),
    "planner_mode": state.get("planner_mode", "deterministic"),
    "npc_persistent_locations": state.get("npc_persistent_locations", default_npc_persistent_locations()),
    "active_actions": [],
    "completed_actions": state.get("completed_actions", []),
    "time_catchup_log": state.get("time_catchup_log", []),
    "previous_days": previous_days,
    "previous_day_summary": previous_day.get("summary", []),
  }
  next_state = save_world_state(next_state)
  return ensure_daily_plan_for_current_day(next_state, force=True)


def reset_world_runtime_fields(state, day=1, time_text="07:00", force_daily_plan=True):
  state["current_day"] = 1
  try:
    state["current_day"] = max(1, int(day or 1))
  except (TypeError, ValueError):
    state["current_day"] = 1
  state["current_time"] = normalize_schedule_time(time_text) or "07:00"
  state["active_actions"] = []
  state["completed_actions"] = []
  state["last_executed_actions"] = []
  state["last_time_catchup_log"] = []
  state["last_spatial_arrivals"] = []
  state["last_arrival_observations"] = []
  state["last_tick"] = datetime.datetime.now().isoformat(timespec="seconds")
  if force_daily_plan:
    state = ensure_daily_plan_for_current_day(state, force=True)
  try:
    from .npc_spatial_state import reset_npc_spatial_movements
    reset_npc_spatial_movements(state["current_day"], state["current_time"])
  except Exception as exc:
    state["last_spatial_error"] = str(exc)
  return state


def reset_world_time():
  state = load_world_state()
  state = reset_world_runtime_fields(state, day=1, time_text="07:00", force_daily_plan=True)
  return save_world_state(state)


def clean_simulation_state():
  state = load_world_state()
  cleared_files = clear_live_interaction_memory()
  preserved = {
    "planner_mode": state.get("planner_mode", "deterministic"),
    "npc_persistent_locations": state.get("npc_persistent_locations", default_npc_persistent_locations()),
    "npc_schedules": state.get("npc_schedules", []),
    "time_step_minutes": state.get("time_step_minutes", 60),
  }
  state["npc_goals"] = {}
  state["npc_knowledge"] = {}
  state["npc_relationships"] = {}
  state["active_requests"] = []
  state["completed_events"] = []
  state["recent_observations"] = []
  state["previous_days"] = []
  state["previous_day_summary"] = []
  state["npc_daily_plans"] = {}
  state["time_catchup_log"] = []
  state["last_daily_planning"] = {}
  state["last_time_catchup_log"] = []
  state["last_spatial_arrivals"] = []
  state["last_arrival_observations"] = []
  state["last_executed_actions"] = []
  state["active_actions"] = []
  state["completed_actions"] = []
  state["planner_mode"] = preserved["planner_mode"]
  state["npc_persistent_locations"] = preserved["npc_persistent_locations"]
  state["npc_schedules"] = preserved["npc_schedules"]
  state["time_step_minutes"] = preserved["time_step_minutes"]
  state = reset_world_runtime_fields(state, day=1, time_text="07:00", force_daily_plan=True)
  state["last_clean_simulation"] = {
    "cleaned_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "cleared": {
      "npc_goals": True,
      "npc_knowledge": True,
      "npc_relationships": True,
      "active_requests": True,
      "completed_events": True,
      "recent_observations": True,
      "previous_days": True,
      "npc_daily_plans": True,
      "completed_actions": True,
      "live_memory_files": cleared_files,
    },
  }
  return save_world_state(state)


def jump_world_time(day, time_text):
  state = load_world_state()
  previous_day = int(state.get("current_day") or 1)
  previous_time = normalize_schedule_time(state.get("current_time", "07:00")) or "07:00"
  try:
    target_day = max(1, int(day or 1))
  except (TypeError, ValueError):
    target_day = 1
  normalized_time = normalize_schedule_time(time_text) or "08:00"
  state["current_day"] = target_day
  state["current_time"] = normalized_time
  state["active_actions"] = []
  state["last_executed_actions"] = []
  state["last_spatial_arrivals"] = []
  state["last_arrival_observations"] = []
  state["last_tick"] = datetime.datetime.now().isoformat(timespec="seconds")
  state = ensure_daily_plan_for_current_day(state)
  try:
    from .npc_spatial_state import reset_npc_spatial_movements
    reset_npc_spatial_movements(state["current_day"], normalized_time)
  except Exception as exc:
    state["last_spatial_error"] = str(exc)
  if previous_day == target_day:
    state = process_missed_world_actions(previous_time, normalized_time, target_day, state)
  else:
    state["last_time_catchup_log"] = []
  state = execute_scheduled_actions(state)
  return save_world_state(state)


def advance_world_time(step_minutes=None):
  state = load_world_state()
  state = ensure_daily_plan_for_current_day(state)
  state["last_time_catchup_log"] = []
  step = int(step_minutes or state.get("time_step_minutes") or 60)
  current_minutes = time_to_minutes(state.get("current_time", "08:00"))
  next_minutes = current_minutes + step
  if next_minutes >= 24 * 60:
    try:
      from .npc_spatial_state import advance_spatial_movements
      spatial_state, arrivals = advance_spatial_movements(step, state.get("current_day", 1), "00:00")
      state["last_spatial_arrivals"] = arrivals
      state["last_arrival_observations"] = record_spatial_arrival_observations(arrivals)
      state = complete_arrived_actions(state, arrivals)
    except Exception as exc:
      state["last_spatial_error"] = str(exc)
    next_state = advance_day("00:00")
    next_state["time_step_minutes"] = step
    next_state["last_tick"] = datetime.datetime.now().isoformat(timespec="seconds")
    next_state = execute_scheduled_actions(next_state)
    return save_world_state(next_state)
  next_time = minutes_to_time(next_minutes)
  try:
    from .npc_spatial_state import advance_spatial_movements
    spatial_state, arrivals = advance_spatial_movements(step, state.get("current_day", 1), next_time)
    state["last_spatial_arrivals"] = arrivals
    state["last_arrival_observations"] = record_spatial_arrival_observations(arrivals)
    state = complete_arrived_actions(state, arrivals)
  except Exception as exc:
    state["last_spatial_error"] = str(exc)
  state["current_time"] = next_time
  state["time_step_minutes"] = step
  state["last_tick"] = datetime.datetime.now().isoformat(timespec="seconds")
  state = execute_scheduled_actions(state)
  return save_world_state(state)
