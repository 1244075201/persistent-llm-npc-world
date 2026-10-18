import re


DEFAULT_IMPORTANCE_SCORE = 0.5


IMPORTANCE_LABEL_SCORES = {
  "high": 0.85,
  "medium": 0.6,
  "low": 0.2,
}


HIGH_IMPORTANCE_EVENTS = {
  "negative_feedback",
  "trust_building",
  "major_relationship_change",
  "player_betrayal",
  "important_belief_update",
  "major_world_event",
  "apology",
}


MEDIUM_IMPORTANCE_EVENTS = {
  "task_assistance",
  "gratitude",
  "cooperation",
  "task_completion",
  "player_requested_help",
  "completion",
  "important_knowledge_acquisition",
  "knowledge_acquisition",
  "vendor_investigation_result",
  "vendor_investigation",
  "completed_player_goal",
  "knowledge",
}


LOW_IMPORTANCE_EVENTS = {
  "daily_routine",
  "movement",
  "normal_observation",
  "ordinary_observation",
  "small_talk",
  "greeting",
  "normal_conversation",
}


POSITIVE_SOCIAL_PATTERNS = (
  "thank",
  "appreciate",
  "trust",
  "helpful",
  "grateful",
)


NEGATIVE_SOCIAL_PATTERNS = (
  "liar",
  "distrust",
  "disappointed",
  "angry",
  "blame",
)


GREETING_PATTERNS = (
  "hi",
  "hello",
  "hey",
  "good morning",
  "good afternoon",
  "how are you",
)


def clamp_importance_score(value):
  try:
    score = float(value)
  except (TypeError, ValueError):
    score = DEFAULT_IMPORTANCE_SCORE
  return max(0.0, min(1.0, round(score, 3)))


def normalize_importance_text(value):
  return re.sub(r"\s+", "_", str(value or "").strip().lower())


def infer_event_tokens(memory):
  memory = memory if isinstance(memory, dict) else {}
  metadata = memory.get("metadata", {}) if isinstance(memory.get("metadata"), dict) else {}
  fields = [
    memory.get("type", ""),
    memory.get("memory_type", ""),
    memory.get("source", ""),
    memory.get("importance", ""),
    memory.get("action", ""),
    memory.get("topic", ""),
    memory.get("relationship_event", ""),
    memory.get("relationship_event_type", ""),
    memory.get("event_type", ""),
    metadata.get("relationship_event", ""),
    metadata.get("relationship_event_type", ""),
    metadata.get("source_type", ""),
    metadata.get("related_memory_id", ""),
  ]
  content = str(memory.get("content") or memory.get("reflection") or "").lower()
  tokens = {normalize_importance_text(field) for field in fields if str(field or "").strip()}
  memory_type = normalize_importance_text(memory.get("type") or memory.get("memory_type") or "")
  source = normalize_importance_text(memory.get("source") or "")

  if memory_type in {"conversation", "dialogue"} or source == "live_dialogue":
    if any(pattern in content for pattern in NEGATIVE_SOCIAL_PATTERNS):
      tokens.add("negative_feedback")
    if any(pattern in content for pattern in POSITIVE_SOCIAL_PATTERNS):
      tokens.add("gratitude")
    if any(pattern in content for pattern in GREETING_PATTERNS):
      tokens.add("greeting")
    if (
        any(pattern in content for pattern in GREETING_PATTERNS)
        and not any(pattern in content for pattern in POSITIVE_SOCIAL_PATTERNS)
        and not any(pattern in content for pattern in NEGATIVE_SOCIAL_PATTERNS)):
      tokens.add("small_talk")

  if "betray" in content or "betrayed" in content:
    tokens.add("player_betrayal")
  if "sorry" in content or "apologize" in content or "apology" in content:
    tokens.add("apology")
  if "negative" in content and ("feedback" in content or "distrust" in content or "betray" in content):
    tokens.add("negative_feedback")
  if "trust" in content and ("built" in content or "building" in content):
    tokens.add("trust_building")
  if "trust" in content and ("you" in content or "player" in content):
    tokens.add("gratitude")
  if "completed" in content and ("request" in content or "task" in content):
    tokens.add("task_completion")
  if "requested" in content and ("help" in content or "investigate" in content or "request" in content):
    tokens.add("player_requested_help")
  if "vendor" in content and ("market" in content or "information" in content):
    tokens.add("vendor_investigation")
  if "walked" in content or "arrived at" in content or "moved" in content:
    tokens.add("movement")
  if "small talk" in content:
    tokens.add("small_talk")
  if "ordinary observation" in content or "normal observation" in content:
    tokens.add("ordinary_observation")
  return tokens


def assign_memory_importance(memory):
  memory = memory if isinstance(memory, dict) else {}
  if "importance_score" in memory:
    return clamp_importance_score(memory.get("importance_score"))

  tokens = infer_event_tokens(memory)
  if tokens.intersection(HIGH_IMPORTANCE_EVENTS):
    return 0.85
  if "gratitude" in tokens and ("trust" in str(memory.get("content", "")).lower() or "appreciate" in str(memory.get("content", "")).lower()):
    return 0.8
  if tokens.intersection(MEDIUM_IMPORTANCE_EVENTS):
    return 0.6
  if tokens.intersection(LOW_IMPORTANCE_EVENTS):
    return 0.2

  label = normalize_importance_text(memory.get("importance", ""))
  if label in IMPORTANCE_LABEL_SCORES:
    return IMPORTANCE_LABEL_SCORES[label]
  return DEFAULT_IMPORTANCE_SCORE


def importance_label(score):
  score = clamp_importance_score(score)
  if score >= 0.8:
    return "High"
  if score >= 0.4:
    return "Medium"
  return "Low"


def ensure_importance_score(memory):
  item = dict(memory or {})
  item["importance_score"] = assign_memory_importance(item)
  item["importance_label"] = importance_label(item["importance_score"])
  return item


def memory_retrieval_score(relevance, importance_score, recency):
  return (
    0.5 * float(relevance or 0.0)
    + 0.3 * clamp_importance_score(importance_score)
    + 0.2 * float(recency or 0.0)
  )
