import datetime
import json
import re
from pathlib import Path

from .memory_importance import (
  assign_memory_importance,
  ensure_importance_score,
  memory_retrieval_score,
)


ALLOWED_MEMORY_NPCS = {"Mira Chen", "Tovan Reed", "Lysa Vale"}
STOPWORDS = {
  "a", "an", "and", "are", "as", "at", "be", "but", "can", "could",
  "do", "for", "from", "help", "i", "if", "in", "is", "it", "me",
  "my", "of", "on", "or", "please", "player", "the", "them", "to",
  "you", "your", "with", "would",
}


def project_root():
  return Path(__file__).resolve().parents[3]


def live_memory_dir():
  return project_root() / "experiments" / "player_intervention" / "live_memory"


def npc_memory_path(npc):
  if npc not in ALLOWED_MEMORY_NPCS:
    raise ValueError("Unsupported NPC for live memory.")
  filename = npc.replace(" ", "_") + ".json"
  return live_memory_dir() / filename


def npc_reflection_path(npc):
  if npc not in ALLOWED_MEMORY_NPCS:
    raise ValueError("Unsupported NPC for live reflections.")
  filename = npc.replace(" ", "_") + ".json"
  return live_memory_dir() / "reflections" / filename


def npc_observation_path(npc):
  if npc not in ALLOWED_MEMORY_NPCS:
    raise ValueError("Unsupported NPC for live observations.")
  filename = npc.replace(" ", "_") + ".json"
  return live_memory_dir() / "observations" / filename


def _write_json_list(path, items):
  path.parent.mkdir(parents=True, exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(items, output_file, ensure_ascii=False, indent=2)


def clear_live_interaction_memory():
  """Clear the additive player-interaction memory layer without touching persona memory."""
  cleared = {
    "live_memories": 0,
    "reflections": 0,
    "observations": 0,
  }
  for npc in sorted(ALLOWED_MEMORY_NPCS):
    memory_path = npc_memory_path(npc)
    reflection_path = npc_reflection_path(npc)
    observation_path = npc_observation_path(npc)
    cleared["live_memories"] += len(load_raw_npc_memory(npc))
    cleared["reflections"] += len(load_reflections(npc))
    cleared["observations"] += len(load_observations(npc))
    _write_json_list(memory_path, [])
    _write_json_list(reflection_path, [])
    _write_json_list(observation_path, [])
  return cleared


def sanitize_memory_id_part(value):
  value = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip())
  value = re.sub(r"_+", "_", value).strip("_")
  return value or "unknown"


def generate_memory_id(npc, memory_type, topic=""):
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  return "_".join(
    [
      sanitize_memory_id_part(memory_type).lower(),
      sanitize_memory_id_part(npc),
      sanitize_memory_id_part(topic).lower(),
      timestamp,
    ]
  )


def generate_observation_id(npc, action=""):
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  return "_".join(
    [
      "observation",
      sanitize_memory_id_part(npc),
      sanitize_memory_id_part(action).lower(),
      timestamp,
    ]
  )


def temporary_memory_id(npc, index):
  return f"legacy_{sanitize_memory_id_part(npc)}_{index + 1:06d}"


def with_memory_identity(npc, memory, index):
  item = dict(memory)
  memory_id = str(item.get("id") or item.get("memory_id") or "").strip()
  if not memory_id:
    memory_id = temporary_memory_id(npc, index)
    item["_temporary_id"] = True
  item["id"] = memory_id
  item["memory_id"] = memory_id
  if not item.get("world_day") and not item.get("world_time") and item.get("time"):
    item["legacy_replay_time"] = item.get("legacy_replay_time") or item.get("time")
  return ensure_importance_score(item)


def with_legacy_time_marker(item):
  entry = dict(item)
  if not entry.get("world_day") and not entry.get("world_time") and entry.get("time"):
    entry["legacy_replay_time"] = entry.get("legacy_replay_time") or entry.get("time")
  return ensure_importance_score(entry)


def current_world_time_fields():
  try:
    from .world_state import get_current_world_time
    world_time = get_current_world_time()
  except Exception:
    world_time = {"day": 1, "time": "08:00", "display": "Day 1 08:00"}
  return {
    "world_day": world_time.get("day", 1),
    "world_time": world_time.get("time", "08:00"),
    "display": world_time.get("display", "Day 1 08:00"),
  }


def load_raw_npc_memory(npc):
  path = npc_memory_path(npc)
  if not path.is_file():
    return []
  try:
    with open(path, encoding="utf-8") as memory_file:
      payload = json.load(memory_file)
  except (json.JSONDecodeError, OSError):
    return []
  if not isinstance(payload, list):
    return []
  return [item for item in payload if isinstance(item, dict)]


def load_npc_memory(npc):
  return [
    with_memory_identity(npc, item, index)
    for index, item in enumerate(load_raw_npc_memory(npc))
  ]


def load_reflections(npc):
  path = npc_reflection_path(npc)
  if not path.is_file():
    return []
  try:
    with open(path, encoding="utf-8") as reflection_file:
      payload = json.load(reflection_file)
  except (json.JSONDecodeError, OSError):
    return []
  if not isinstance(payload, list):
    return []
  return [with_legacy_time_marker(item) for item in payload if isinstance(item, dict)]


def load_observations(npc):
  path = npc_observation_path(npc)
  if not path.is_file():
    return []
  try:
    with open(path, encoding="utf-8") as observation_file:
      payload = json.load(observation_file)
  except (json.JSONDecodeError, OSError):
    return []
  if not isinstance(payload, list):
    return []
  return [with_legacy_time_marker(item) for item in payload if isinstance(item, dict)]


def write_memory_entry(
    npc,
    memory_type,
    time_text,
    content,
    source="live_dialogue",
    importance="medium",
    action="",
    topic="",
    target="",
    status="",
    memory_id="",
    metadata=None):
  content = re.sub(r"\s+", " ", str(content or "")).strip()
  if not content:
    raise ValueError("Memory content is required.")
  if len(content) > 300:
    content = content[:297].rstrip() + "..."
  entry_id = str(memory_id or "").strip() or generate_memory_id(
    npc,
    memory_type,
    topic or memory_type,
  )
  world_time = current_world_time_fields()
  legacy_replay_time = str(time_text or "").strip()
  entry = {
    "id": entry_id,
    "memory_id": entry_id,
    "npc": npc,
    "type": memory_type,
    "time": world_time["display"],
    "world_day": world_time["world_day"],
    "world_time": world_time["world_time"],
    "content": content,
    "action": re.sub(r"\s+", " ", str(action or "")).strip(),
    "topic": re.sub(r"\s+", " ", str(topic or "")).strip(),
    "target": re.sub(r"\s+", " ", str(target or npc)).strip(),
    "status": re.sub(r"\s+", " ", str(status or "noted")).strip(),
    "source": source,
    "importance": importance,
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  entry["importance_score"] = assign_memory_importance(entry)
  if legacy_replay_time and legacy_replay_time != world_time["display"]:
    entry["legacy_replay_time"] = legacy_replay_time
  if metadata:
    entry["metadata"] = metadata

  path = npc_memory_path(npc)
  path.parent.mkdir(parents=True, exist_ok=True)
  memories = load_raw_npc_memory(npc)
  memories.append(entry)
  with open(path, "w", encoding="utf-8") as memory_file:
    json.dump(memories, memory_file, ensure_ascii=False, indent=2)
  return entry


def observation_content_for_action(npc, action):
  action_text = re.sub(r"\s+", " ", str(action or "")).strip()
  lowered = action_text.lower()
  if not action_text:
    return ""
  if "visit market" in lowered or ("market" in lowered and "vendor" in lowered):
    return f"{npc} visited the market and talked with vendors."
  if "check inventory" in lowered or ("inventory" in lowered and ("check" in lowered or "update" in lowered)):
    return f"{npc} checked supplies and updated inventory notes."
  return f"{npc} completed the planned action: {action_text}."


def write_observation_entry(
    npc,
    action,
    time_text="",
    importance="medium",
    source_memory_id="",
    content_override=""):
  content = re.sub(r"\s+", " ", str(content_override or "")).strip()
  if not content:
    content = observation_content_for_action(npc, action)
  if not content:
    raise ValueError("Observation action is required.")
  world_time = current_world_time_fields()
  legacy_replay_time = str(time_text or "").strip()
  observation_id = generate_observation_id(npc, action)
  entry = {
    "observation_id": observation_id,
    "npc": npc,
    "npc_name": npc,
    "type": "observation",
    "source": "action_feedback",
    "action": re.sub(r"\s+", " ", str(action or "")).strip(),
    "content": content,
    "importance": importance,
    "time": world_time["display"],
    "world_day": world_time["world_day"],
    "world_time": world_time["world_time"],
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  entry["importance_score"] = assign_memory_importance(entry)
  if legacy_replay_time and legacy_replay_time != world_time["display"]:
    entry["legacy_replay_time"] = legacy_replay_time
  if source_memory_id:
    entry["source_memory_id"] = str(source_memory_id).strip()
  path = npc_observation_path(npc)
  path.parent.mkdir(parents=True, exist_ok=True)
  observations = load_observations(npc)
  observations.append(entry)
  with open(path, "w", encoding="utf-8") as observation_file:
    json.dump(observations, observation_file, ensure_ascii=False, indent=2)
  entry["lifecycle_updates"] = update_memory_lifecycle_from_observation(npc, entry)
  return entry


def find_matching_pending_requests(npc, observation):
  if npc not in ALLOWED_MEMORY_NPCS:
    raise ValueError("Unsupported NPC for live memory lifecycle.")
  matches = []
  memories = load_npc_memory(npc)
  source_memory_id = str(observation.get("source_memory_id") or "").strip()
  if source_memory_id:
    for index, memory in enumerate(memories):
      if str(memory.get("type", "")).lower() != "request":
        continue
      if str(memory.get("status", "")).lower() != "pending":
        continue
      if source_memory_id in {str(memory.get("id", "")), str(memory.get("memory_id", ""))}:
        matched = dict(memory)
        matched["_memory_index"] = index
        matched["_match_type"] = "id"
        return [matched]

  observation_text = " ".join(
    [
      str(observation.get("action", "")),
      str(observation.get("content", "")),
    ]
  )
  observation_terms = memory_keywords(observation_text)
  if not observation_terms:
    return []

  for index, memory in enumerate(memories):
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
    )
    memory_terms = memory_keywords(memory_text)
    overlap = observation_terms.intersection(memory_terms)
    action_terms = memory_keywords(memory.get("action", ""))
    topic_terms = memory_keywords(memory.get("topic", ""))
    if (
        action_terms
        and topic_terms
        and observation_terms.intersection(action_terms)
        and observation_terms.intersection(topic_terms)):
      matched = dict(memory)
      matched["_memory_index"] = index
      matched["_match_type"] = "keywords"
      matched["_match_terms"] = sorted(overlap)
      matches.append(matched)
  return matches


def mark_memory_completed(npc, pending_memory, completed_time):
  path = npc_memory_path(npc)
  raw_memories = load_raw_npc_memory(npc)
  memories = [
    with_memory_identity(npc, item, index)
    for index, item in enumerate(raw_memories)
  ]
  target_index = pending_memory.get("_memory_index")
  if isinstance(target_index, int) and 0 <= target_index < len(memories):
    candidate_indexes = [target_index]
  else:
    candidate_indexes = range(len(memories))

  for index in candidate_indexes:
    memory = memories[index]
    if str(memory.get("type", "")).lower() != "request":
      continue
    if str(memory.get("status", "")).lower() != "pending":
      continue
    pending_id = str(pending_memory.get("id") or pending_memory.get("memory_id") or "").strip()
    memory_id = str(memory.get("id") or memory.get("memory_id") or "").strip()
    if pending_id and memory_id and pending_id == memory_id:
      raw_memories[index]["id"] = memory_id
      raw_memories[index]["memory_id"] = memory_id
      raw_memories[index]["status"] = "completed"
      raw_memories[index]["completed_time"] = str(completed_time or "unknown")
      world_time = current_world_time_fields()
      raw_memories[index]["completed_world_day"] = world_time["world_day"]
      raw_memories[index]["completed_world_time"] = world_time["world_time"]
      raw_memories[index]["importance_score"] = assign_memory_importance(raw_memories[index])
      with open(path, "w", encoding="utf-8") as memory_file:
        json.dump(raw_memories, memory_file, ensure_ascii=False, indent=2)
      return with_memory_identity(npc, raw_memories[index], index)
    same_content = memory.get("content") == pending_memory.get("content")
    same_action = memory.get("action") == pending_memory.get("action")
    same_topic = memory.get("topic") == pending_memory.get("topic")
    if same_content and same_action and same_topic:
      raw_memories[index]["id"] = memory_id or pending_id or generate_memory_id(
        npc,
        raw_memories[index].get("type", "request"),
        raw_memories[index].get("topic", "request"),
      )
      raw_memories[index]["memory_id"] = raw_memories[index]["id"]
      raw_memories[index]["status"] = "completed"
      raw_memories[index]["completed_time"] = str(completed_time or "unknown")
      world_time = current_world_time_fields()
      raw_memories[index]["completed_world_day"] = world_time["world_day"]
      raw_memories[index]["completed_world_time"] = world_time["world_time"]
      raw_memories[index]["importance_score"] = assign_memory_importance(raw_memories[index])
      with open(path, "w", encoding="utf-8") as memory_file:
        json.dump(raw_memories, memory_file, ensure_ascii=False, indent=2)
      return with_memory_identity(npc, raw_memories[index], index)
  return None


def create_completion_memory(npc, completed_memory, observation):
  related = str(completed_memory.get("content", "")).strip()
  related_memory_id = str(completed_memory.get("id") or completed_memory.get("memory_id") or "").strip()
  action = str(completed_memory.get("action") or observation.get("action") or "").strip()
  topic = str(completed_memory.get("topic", "")).strip()
  content = f"{npc} completed the requested action."
  if action:
    content = f"{npc} completed the requested action: {action}."
  entry = write_memory_entry(
    npc=npc,
    memory_type="completion",
    time_text=observation.get("time") or completed_memory.get("completed_time") or "unknown",
    content=content,
    source="action_feedback",
    importance=str(completed_memory.get("importance") or observation.get("importance") or "medium"),
    action=action,
    topic=topic,
    target=npc,
    status="completed",
    metadata={
      "related_memory_id": related_memory_id,
      "related_memory": related,
      "observation": observation.get("content", ""),
    },
  )
  entry["related_memory"] = related
  entry["related_memory_id"] = related_memory_id
  path = npc_memory_path(npc)
  memories = load_raw_npc_memory(npc)
  if memories and memories[-1].get("content") == entry["content"]:
    memories[-1]["related_memory"] = related
    memories[-1]["related_memory_id"] = related_memory_id
    with open(path, "w", encoding="utf-8") as memory_file:
      json.dump(memories, memory_file, ensure_ascii=False, indent=2)
    entry = memories[-1]
  return entry


def update_memory_lifecycle_from_observation(npc, observation):
  updates = []
  for pending in find_matching_pending_requests(npc, observation):
    completed = mark_memory_completed(npc, pending, observation.get("time"))
    if not completed:
      continue
    completion_memory = create_completion_memory(npc, completed, observation)
    completion_reflection = create_reflection_entry(completion_memory)
    relationship_memory = None
    try:
      from .world_state import append_relationship_for_completed_request
      relationship_memory = append_relationship_for_completed_request(npc, completed, observation)
    except Exception as exc:
      relationship_memory = {"error": str(exc)}
    updates.append(
      {
        "completed_memory": completed,
        "relationship_memory": relationship_memory,
        "completion_memory": completion_memory,
        "completion_reflection": completion_reflection,
      }
    )
  return updates


def reflection_text_for_memory(memory):
  memory_type = str(memory.get("type", "")).lower()
  action = str(memory.get("action", "")).strip()
  topic = str(memory.get("topic", "")).strip()
  npc = str(memory.get("npc") or memory.get("target") or "").strip()
  if memory_type == "request":
    if topic and action:
      return (
        f"The player seems interested in {topic}. "
        f"I should follow up by {action} when it fits my responsibilities."
      )
    if topic:
      return (
        f"The player seems interested in {topic}. "
        "I should consider a small follow-up that fits my responsibilities."
      )
    return "The player made a request. I should consider it without ignoring my own responsibilities."
  if memory_type == "report":
    if topic:
      return (
        f"The player shared an unverified report about {topic}. "
        "I should treat it cautiously and check quietly before assuming it is true."
      )
    return (
      "The player shared an unverified report. "
      "I should treat it cautiously and check quietly before assuming it is true."
    )
  if memory_type == "completion":
    npc_label = npc or "The NPC"
    return f"{npc_label} completed the player's previous request."
  return ""


def create_reflection_entry(memory):
  if not isinstance(memory, dict):
    return None
  memory_type = str(memory.get("type", "")).lower()
  if memory_type not in {"request", "report", "completion"}:
    return None
  npc = str(memory.get("npc") or memory.get("target") or "").strip()
  if npc not in ALLOWED_MEMORY_NPCS:
    return None
  reflection = reflection_text_for_memory(memory)
  if not reflection:
    return None
  world_time = current_world_time_fields()
  entry = {
    "npc": npc,
    "source_memory": str(memory.get("content", "")).strip(),
    "reflection": reflection,
    "time": world_time["display"],
    "importance": str(memory.get("importance") or "medium"),
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
  entry["importance_score"] = assign_memory_importance(entry)
  entry["world_day"] = world_time["world_day"]
  entry["world_time"] = world_time["world_time"]
  if memory.get("time") and memory.get("time") != world_time["display"]:
    entry["legacy_replay_time"] = memory.get("time")
  path = npc_reflection_path(npc)
  path.parent.mkdir(parents=True, exist_ok=True)
  reflections = load_reflections(npc)
  reflections.append(entry)
  with open(path, "w", encoding="utf-8") as reflection_file:
    json.dump(reflections, reflection_file, ensure_ascii=False, indent=2)
  return entry


def get_recent_memories(npc, limit=3):
  memories = load_npc_memory(npc)
  return list(reversed(memories[-limit:]))


def get_recent_reflections(npc, limit=3):
  reflections = load_reflections(npc)
  return list(reversed(reflections[-limit:]))


def get_recent_observations(npc, limit=3):
  observations = load_observations(npc)
  return list(reversed(observations[-limit:]))


def memory_keywords(text):
  words = re.findall(r"[a-zA-Z0-9_']+", str(text or "").lower())
  return {word for word in words if len(word) > 2 and word not in STOPWORDS}


def retrieve_relevant_memories(npc_name, query, max_results=3):
  memories = load_npc_memory(npc_name)
  query_terms = memory_keywords(query)
  if not query_terms:
    return []

  scored = []
  total = len(memories)
  for index, memory in enumerate(memories):
    content = memory.get("content", "")
    metadata = memory.get("metadata", {}) if isinstance(memory.get("metadata", {}), dict) else {}
    searchable = " ".join(
      [
        str(content),
        str(memory.get("type", "")),
        str(memory.get("source", "")),
        str(metadata.get("player_utterance", "")),
      ]
    )
    terms = memory_keywords(searchable)
    overlap = query_terms.intersection(terms)
    if not overlap:
      continue
    recency = index / max(total - 1, 1)
    relevance = len(overlap) / max(len(query_terms), 1)
    importance_score = assign_memory_importance(memory)
    score = memory_retrieval_score(relevance, importance_score, recency)
    scored.append((score, index, memory))

  scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
  return [item[2] for item in scored[:max_results]]
