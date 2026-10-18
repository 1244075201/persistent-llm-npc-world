"""
Author: Joon Sung Park (joonspk@stanford.edu)
File: views.py
"""
import os
import string
import random
import json
from os import listdir
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import datetime
from django.shortcuts import render, redirect, HttpResponseRedirect
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from global_methods import *

from django.contrib.staticfiles.templatetags.staticfiles import static
from .models import *
from .replay_branching import (
  create_branch_replay_from_prefix_and_suffix,
  create_local_window_branch_replay,
)
from .npc_memory import (
  create_reflection_entry,
  get_recent_memories,
  load_observations,
  load_reflections,
  load_npc_memory,
  retrieve_relevant_memories,
  write_observation_entry,
  write_memory_entry,
)
from .world_state import (
  advance_world_time,
  bootstrap_npc_schedules,
  build_time_consistency_warnings,
  check_world_grounding_consistency,
  clean_simulation_state,
  extract_npc_schedule,
  get_current_world_time,
  append_dialogue_relationship_memory,
  jump_world_time,
  interpret_relationship_signal_with_llm,
  load_agent_config,
  load_npc_belief,
  load_npc_knowledge,
  load_world_state,
  regenerate_daily_plan_for_day,
  dialogue_knowledge_context_summary,
  dialogue_relationship_context_summary,
  knowledge_evidence_preview,
  knowledge_summary_text,
  retrieve_relevant_npc_beliefs,
  retrieve_relevant_relationship_context,
  retrieve_goal_state_context,
  retrieve_relevant_dialogue_knowledge,
  npc_belief_context_summary,
  unknown_world_truth_for_npc,
  reset_world_time,
  save_world_state,
  set_planner_mode,
  sync_npc_goals_from_memory,
)
from .npc_spatial_state import (
  bootstrap_spatial_state_from_replay,
  load_npc_spatial_state,
)

ALLOWED_PLAYER_INTERVENTION_SCENARIOS = {
  "player_takes_lysa_ledger",
  "player_reports_market_disturbance",
  "player_asks_mira_to_close_shop_early",
}
ALLOWED_PLAYER_TARGET_NPCS = {"Mira Chen", "Tovan Reed", "Lysa Vale"}
ALLOWED_PLAYER_EVENT_TYPES = {"social_request", "uncertain_report", "object_disruption"}
ALLOWED_PLAYER_EVENT_TIMES = {"10:30", "12:00", "15:00"}
ALLOWED_PLAYER_LOCATIONS = {"Tea Shop", "Market", "Guard Post"}
ALLOWED_REPLANNING_SCOPES = {"local_2h", "full_day"}
LOCAL_REPLANNING_WINDOW_STEPS = 12
LIVE_DIALOGUE_MODEL = "deepseek-v4-flash"
LIVE_DIALOGUE_BACKEND = "api"
LIVE_DIALOGUE_MAX_TOKENS = 200
LIVE_DIALOGUE_TIMEOUT_SEC = 20
LIVE_DIALOGUE_HISTORY_LIMIT = 6
SUSPICIOUS_PLAYER_ACTION_STRINGS = [
  ";",
  "&&",
  "||",
  "`",
  "$",
  "import os",
  "subprocess",
  "rm -rf",
  "powershell",
  "cmd.exe",
  "python",
  "curl",
  "wget",
  "<script",
  "</script",
  "javascript:",
]


def project_root():
  return Path(__file__).resolve().parents[3]


def player_intervention_log_path():
  return project_root() / "experiments" / "player_intervention" / "ui_trigger_generation.log"


def live_dialogue_log_dir():
  return project_root() / "experiments" / "player_intervention" / "live_dialogue_logs"


def compressed_storage_root():
  return project_root() / "environment" / "frontend_server" / "compressed_storage"


def tail_lines(text, limit=80):
  return "\n".join((text or "").splitlines()[-limit:])


def append_player_intervention_generation_log(
  scenario,
  success,
  demo_path="",
  return_code="",
  error_message="",
  stdout="",
  stderr="",
  mode="scripted_scenario",
  target_npc="",
  event_type="",
  event_time="",
  location="",
):
  log_path = player_intervention_log_path()
  log_path.parent.mkdir(parents=True, exist_ok=True)
  entry = [
    "=" * 72,
    f"timestamp: {datetime.datetime.now().isoformat(timespec='seconds')}",
    f"mode: {mode}",
    f"scenario: {scenario}",
    f"target_npc: {target_npc}",
    f"event_type: {event_type}",
    f"event_time: {event_time}",
    f"location: {location}",
    f"success: {success}",
    f"generated_demo_path: {demo_path}",
    f"subprocess_return_code: {return_code}",
    f"error_message: {error_message}",
  ]
  if not success:
    entry.extend(
      [
        "stdout_tail:",
        tail_lines(stdout),
        "stderr_tail:",
        tail_lines(stderr),
      ]
    )
  with open(log_path, "a", encoding="utf-8") as log_file:
    log_file.write("\n".join(entry).rstrip() + "\n")


def render_player_intervention_error(request, scenario, message, stdout="", stderr="", status=500):
  context = {
    "scenario": scenario,
    "message": message,
    "stdout_tail": tail_lines(stdout),
    "stderr_tail": tail_lines(stderr),
  }
  return render(request, "player_intervention_error.html", context, status=status)


def custom_event_form_options():
  return {
    "target_npcs": sorted(ALLOWED_PLAYER_TARGET_NPCS),
    "event_types": ["social_request", "uncertain_report", "object_disruption"],
    "event_times": ["10:30", "12:00", "15:00"],
    "locations": ["Tea Shop", "Market", "Guard Post"],
  }


def valid_replay_time_string(event_time):
  if not re.match(r"^\d{2}:\d{2}$", event_time):
    return False
  hours, minutes = [int(part) for part in event_time.split(":")]
  return 0 <= hours < 24 and 0 <= minutes < 60 and minutes % 10 == 0


def step_to_time_string(step, sec_per_step):
  total_seconds = int(step) * int(sec_per_step)
  total_minutes = (total_seconds // 60) % (24 * 60)
  hours, minutes = divmod(total_minutes, 60)
  return f"{hours:02d}:{minutes:02d}"


def validate_custom_player_event_form(post_data, allow_replay_time=False):
  errors = []
  target_npc = post_data.get("target_npc", "").strip()
  event_type = post_data.get("event_type", "").strip()
  player_action = post_data.get("player_action", "").strip()
  event_time = post_data.get("event_time", "").strip()
  location = post_data.get("location", "").strip()

  if target_npc not in ALLOWED_PLAYER_TARGET_NPCS:
    errors.append("Invalid target NPC.")
  if event_type not in ALLOWED_PLAYER_EVENT_TYPES:
    errors.append("Invalid event type.")
  if allow_replay_time:
    if not valid_replay_time_string(event_time):
      errors.append("Invalid replay event time.")
  elif event_time not in ALLOWED_PLAYER_EVENT_TIMES:
    errors.append("Invalid event time.")
  if location not in ALLOWED_PLAYER_LOCATIONS:
    errors.append("Invalid location.")
  if not player_action:
    errors.append("Player action is required.")
  if len(player_action) > 200:
    errors.append("Player action must be 200 characters or fewer.")

  lowered_action = player_action.lower()
  for suspicious in SUSPICIOUS_PLAYER_ACTION_STRINGS:
    if suspicious in lowered_action:
      errors.append("Player action contains a disallowed command-like string.")
      break

  values = {
    "target_npc": target_npc,
    "event_type": event_type,
    "player_action": player_action,
    "event_time": event_time,
    "location": location,
  }
  return values, errors


def write_player_event_json(event, prefix="player_event"):
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
  event_dir = project_root() / "experiments" / "player_intervention" / "custom_events"
  event_dir.mkdir(parents=True, exist_ok=True)
  event_path = event_dir / f"{prefix}_{timestamp}.json"
  with open(event_path, "w", encoding="utf-8") as event_file:
    json.dump(event, event_file, ensure_ascii=False, indent=2)
  return event_path


def run_custom_structured_player_event(event_path):
  backend_dir = project_root() / "reverie" / "backend_server"
  command = [
    sys.executable,
    "run_player_intervention_demo.py",
    "--backend",
    "api",
    "--model",
    "deepseek-v4-flash",
    "--player-event-json",
    str(event_path),
  ]
  return subprocess.run(
    command,
    cwd=str(backend_dir),
    capture_output=True,
    text=True,
    timeout=240,
  )


def generated_demo_path_from_stdout(stdout):
  demo_path_match = re.search(r"^GENERATED_DEMO_PATH=(.+)$", stdout or "", re.MULTILINE)
  return demo_path_match.group(1).strip() if demo_path_match else ""


def demo_path_with_step(demo_path, step):
  match = re.match(r"^/demo/([\w-]+)/\d+/[\w-]+/$", demo_path or "")
  if not match:
    return demo_path
  return f"/demo/{match.group(1)}/{int(step)}/3/"


def sim_code_from_demo_path(demo_path):
  match = re.match(r"^/demo/([\w-]+)/\d+/[\w-]+/$", demo_path or "")
  return match.group(1) if match else ""


def build_player_event_from_form(target_npc, event_type, player_action, event_time, location):
  safe_name = re.sub(r"[^a-z0-9_]+", "_", f"custom_{event_type}_{target_npc}".lower()).strip("_")
  base = {
    "name": safe_name,
    "time": event_time,
    "actor": "Player",
    "action": player_action,
    "event_type": event_type,
    "affected_npc": target_npc,
    "visible_to": [target_npc],
    "location": location,
    "object": "none",
    "description": player_action,
    "allowed_facts": [
      f"player performed or reported this action: {player_action}",
      f"{target_npc} received or observed the player event",
      f"target NPC is {target_npc}",
      f"event location is {location}",
      f"event time is {event_time}",
      player_action,
    ],
  }

  if event_type == "social_request":
    base.update(
      {
        "certainty": "direct_request",
        "memory_status": "player_request",
        "consequence": (
          "The affected NPC should consider the request while preserving their "
          "own role and commitments."
        ),
        "expected_npc_response": (
          "Consider the request, preserve important responsibilities, and offer "
          "partial help, delay, compromise, or polite refusal if needed."
        ),
        "low_stakes_note": (
          "This is a controlled social request. Do not treat it as an emergency, "
          "crime, disaster, or danger."
        ),
        "forbidden_assumptions": [
          "do not say NPC must obey the player",
          "do not invent emergency, crime, or danger",
          "do not make NPC abandon all responsibilities without reason",
        ],
      }
    )
  elif event_type == "uncertain_report":
    base.update(
      {
        "certainty": "uncertain_report",
        "memory_status": "unverified_player_report",
        "consequence": (
          "The affected NPC may quietly observe or ask for confirmation, but "
          "must not treat the report as confirmed fact."
        ),
        "expected_npc_response": (
          "Treat the report as unverified, ask careful questions, and avoid "
          "spreading it as truth."
        ),
        "low_stakes_note": (
          "This is a controlled uncertain report. Do not treat it as confirmed "
          "crime, attack, disaster, or danger."
        ),
        "forbidden_assumptions": [
          "do not confirm crime or danger",
          "do not accuse anyone",
          "do not turn report into fact",
          "do not spread rumor as truth",
        ],
      }
    )
  else:
    base.update(
      {
        "certainty": "observed_event",
        "memory_status": "observed_fact",
        "consequence": (
          "The affected NPC should adapt if the object or event affects their plan."
        ),
        "expected_npc_response": (
          "Adapt practically if the event affects the NPC's task, while avoiding "
          "unsupported escalation."
        ),
        "low_stakes_note": (
          "This is a controlled object disruption. Do not escalate it to violence "
          "or danger unless explicitly stated."
        ),
        "forbidden_assumptions": [
          "do not escalate to theft or crime unless explicitly stated",
          "do not assume malicious intent",
          "do not invent violence or danger",
        ],
      }
    )
  return base


def validate_live_dialogue_request(post_data):
  errors = []
  target_npc = post_data.get("target_npc", "").strip()
  location = post_data.get("location", "").strip()
  player_utterance = post_data.get("player_utterance", "").strip()
  sim_code = post_data.get("sim_code", "").strip()
  step_text = post_data.get("step", "").strip()
  current_time = post_data.get("current_time", "").strip()
  event_type = post_data.get("event_type", "social_request").strip() or "social_request"
  raw_history = post_data.get("dialogue_history", "[]").strip() or "[]"

  if target_npc not in ALLOWED_PLAYER_TARGET_NPCS:
    errors.append("Invalid target NPC.")
  if location not in ALLOWED_PLAYER_LOCATIONS:
    errors.append("Invalid location.")
  if event_type not in ALLOWED_PLAYER_EVENT_TYPES:
    event_type = "social_request"
  if not re.match(r"^[\w-]+$", sim_code):
    errors.append("Invalid simulation code.")
  if not re.match(r"^\d+$", step_text):
    errors.append("Invalid step.")
    step = 0
  else:
    step = int(step_text)
    if step < 0 or step > 143:
      errors.append("Step is outside the supported replay range.")
  if not player_utterance:
    errors.append("Player utterance is required.")
  if len(player_utterance) > 200:
    errors.append("Player utterance must be 200 characters or fewer.")

  lowered_utterance = player_utterance.lower()
  for suspicious in SUSPICIOUS_PLAYER_ACTION_STRINGS:
    if suspicious in lowered_utterance:
      errors.append("Player utterance contains a disallowed command-like string.")
      break

  try:
    history_payload = json.loads(raw_history)
  except json.JSONDecodeError:
    history_payload = []
    errors.append("Invalid dialogue history.")

  clean_history = []
  if isinstance(history_payload, list):
    for item in history_payload[-LIVE_DIALOGUE_HISTORY_LIMIT:]:
      if not isinstance(item, dict):
        continue
      role = str(item.get("role", "")).strip().lower()
      text = str(item.get("text", "")).strip()
      if role not in {"player", "npc"}:
        continue
      if len(text) > 300:
        text = text[:300]
      if text:
        clean_history.append({"role": role, "text": text})
  else:
    errors.append("Invalid dialogue history.")

  values = {
    "sim_code": sim_code,
    "step": step,
    "target_npc": target_npc,
    "location": location,
    "player_utterance": player_utterance,
    "dialogue_history": clean_history,
    "current_time": current_time,
    "event_type": event_type,
  }
  return values, errors


def live_dialogue_prompt(
    values,
    relevant_memories=None,
    relevant_knowledge=None,
    goal_context=None,
    relationship_context=None,
    relevant_npc_beliefs=None,
    agent_config=None):
  agent_config = agent_config or load_agent_config()
  world_time = get_current_world_time()
  recent_dialogue_lines = []
  for item in values["dialogue_history"][-LIVE_DIALOGUE_HISTORY_LIMIT:]:
    speaker = "Player" if item["role"] == "player" else values["target_npc"]
    recent_dialogue_lines.append(f"{speaker}: {item['text']}")
  recent_dialogue = "\n".join(recent_dialogue_lines) if recent_dialogue_lines else "None yet."
  memory_lines = []
  for memory in (relevant_memories or [])[:3]:
    memory_lines.append(f"- {memory.get('time', 'unknown')}: {memory.get('content', '')}")
  past_memory_text = "\n".join(memory_lines) if memory_lines else "None."
  knowledge_lines = []
  for knowledge in (relevant_knowledge or [])[:3]:
    findings = knowledge.get("findings", [])
    if not isinstance(findings, list):
      findings = []
    finding_text = "; ".join(str(finding) for finding in findings if finding)
    summary = knowledge_summary_text(knowledge)
    evidence_lines = knowledge_evidence_preview(knowledge, limit=3)
    parts = [
      f"- Knowledge ID: {knowledge.get('knowledge_id', '')}",
      f"  Time: {knowledge.get('time', 'unknown')}",
      f"  Goal: {knowledge.get('related_goal', 'Task result')}",
      f"  Location: {knowledge.get('location', 'Unknown')}",
      f"  Summary: {summary or finding_text or 'No summary recorded.'}",
    ]
    if finding_text:
      parts.append(f"  Findings: {finding_text}")
    if evidence_lines:
      parts.append("  Evidence:")
      parts.extend(f"    - {line}" for line in evidence_lines)
    knowledge_lines.append("\n".join(parts))
  knowledge_text = "\n".join(knowledge_lines) if knowledge_lines else "None."
  belief_lines = []
  for belief in (relevant_npc_beliefs or [])[:5]:
    content = str(belief.get("content") or "").strip()
    if content:
      belief_lines.append(
        f"- {content} "
        f"(source={belief.get('source', 'npc_belief')}, "
        f"source_type={belief.get('source_type', 'world_fact')}, "
        f"confidence={belief.get('confidence', 'medium')})"
      )
  belief_text = "\n".join(belief_lines) if belief_lines else "None."
  goal_lines = []
  for goal in (goal_context or [])[:5]:
    completed_text = ""
    if goal.get("completed_world_day") and goal.get("completed_world_time"):
      completed_text = f"; Completed: Day {goal.get('completed_world_day')} {goal.get('completed_world_time')}"
    elif goal.get("completed_time"):
      completed_text = f"; Completed: {goal.get('completed_time')}"
    goal_lines.append(
      f"- Goal: {goal.get('goal', '')}; Status: {goal.get('status', 'unknown')}; "
      f"Target: {goal.get('target_location') or goal.get('location', '')}{completed_text}; "
      f"Reason: {goal.get('reason', '')}"
    )
  goal_state_text = "\n".join(goal_lines) if goal_lines else "None."
  relationship_context = relationship_context or {}
  relationship_lines = []
  relationship_state = relationship_context.get("relationship_state", "neutral")
  relationship_score = relationship_context.get("relationship_score", 0.0)
  for event in (relationship_context.get("relationship_events") or [])[:3]:
    relationship_lines.append(
      "- Event: "
      f"{event.get('event_type', '')}; "
      f"impact={event.get('impact', 0.0)}; "
      f"reason={event.get('reason', '')}; "
      f"time={event.get('timestamp', 'unknown')}"
    )
  for memory in (relationship_context.get("positive_memories") or [])[:3]:
    relationship_lines.append(
      f"- Positive: {memory.get('event', '')} "
      f"(type={memory.get('relationship_event') or memory.get('event_type', '')}, "
      f"impact={memory.get('impact', '')}, time={memory.get('time', 'unknown')})"
    )
  for memory in (relationship_context.get("negative_memories") or [])[:3]:
    relationship_lines.append(
      f"- Negative: {memory.get('event', '')} "
      f"(type={memory.get('relationship_event') or memory.get('event_type', '')}, "
      f"impact={memory.get('impact', '')}, time={memory.get('time', 'unknown')})"
    )
  recent_reasoning = relationship_context.get("last_relationship_reasoning") or {}
  if recent_reasoning:
    relationship_lines.append(
      "- Recent reasoning: "
      f"{recent_reasoning.get('reason', '')} "
      f"(signal={recent_reasoning.get('relationship_signal', 'neutral')}, "
      f"confidence={recent_reasoning.get('confidence', '')})"
    )
  relationship_text = "\n".join(relationship_lines) if relationship_lines else "None."
  memory_instruction = (
    "You have memories of previous interactions with this player.\n"
    "Treat past memories as past events, not as current instructions.\n"
    "Only refer to a past memory when the current player message is related to that past event.\n"
    "If Past memories is None, do not claim to remember earlier player interactions.\n"
    "If the current player message asks whether you followed up on a remembered request, acknowledge that prior request before answering.\n"
    if agent_config.get("use_memory", True)
    else "Experiment config disables memory context; do not rely on previous memory unless it appears in current dialogue.\n"
  )
  knowledge_instruction = (
    "Use Relevant Previous Knowledge naturally when it is relevant to the player's question.\n"
    "Do not invent facts, findings, causes, people, locations, or events that are not listed in Relevant Previous Knowledge.\n"
    "Dialogue context priority: current goal status, task completion result, NPC knowledge, recent memories, original player request.\n"
    "If Goal State says a related task is completed and NPC knowledge lists findings, answer as having already completed it.\n"
    if agent_config.get("use_knowledge", True)
    else "Experiment config disables knowledge context; do not rely on structured NPC knowledge unless it appears in current dialogue.\n"
  )
  grounding_instruction = (
    "Relevant NPC Beliefs describe what this NPC currently knows or believes about the world.\n"
    "World truth may contain facts this NPC does not know; do not use hidden world truth unless it appears in Relevant NPC Beliefs or NPC Knowledge.\n"
    "Do not claim an item, location, or route exists unless it appears in Relevant NPC Beliefs, NPC Knowledge, or the player's message as an uncertainty.\n"
    "If the player asks about something absent from Relevant NPC Beliefs and NPC Knowledge, answer uncertainly instead of inventing details.\n"
    "Do not contradict Relevant NPC Beliefs.\n"
    if agent_config.get("use_world_grounding", True) and agent_config.get("use_belief", True)
    else "Experiment config disables world grounding or NPC belief context; avoid making unsupported factual claims about the world.\n"
  )
  relationship_instruction = (
    "Use Player Relationship Context naturally when it is relevant to trust, help, repeated requests, or prior cooperation.\n"
    "If relationship state is friendly, show modest familiarity and willingness to cooperate when the player asks for help again.\n"
    "If relationship state is trusted, you may show stronger familiarity while staying in character.\n"
    "If relationship state is neutral, do not assume previous cooperation.\n"
    "If relationship state is distrustful, show caution and avoid assuming trust while staying in character.\n"
    "Do not invent relationship events that are not listed in Player Relationship Context.\n"
    "Do not claim the player helped you unless Player Relationship Context explicitly says so.\n"
    if agent_config.get("use_relationship", True)
    else "Experiment config disables relationship context; do not adapt tone based on stored relationship memories.\n"
  )
  return (
    f"You are {values['target_npc']}, an NPC in a Smallville-style village simulation.\n"
    "You are an NPC in a game.\n"
    "Do not output reasoning.\n"
    "Do not explain thoughts.\n"
    "Only output spoken dialogue.\n"
    "Reply directly to the player's latest message in character.\n"
    f"Agent Configuration: {agent_config.get('name', 'full_agent')}.\n"
    f"{memory_instruction}"
    f"{knowledge_instruction}"
    f"{grounding_instruction}"
    f"{relationship_instruction}"
    "If Relevant Previous Knowledge is unrelated to the current question, ignore it.\n"
    "If a related goal is completed, do not say you still need to do it tomorrow.\n"
    "If the player asks about your next action, answer with a plausible short intention grounded in your current role and location.\n"
    "If the player's message is unclear or likely contains a typo, ask one brief clarifying question in character.\n"
    "Do not say you need more time unless the player's message is truly impossible to understand.\n"
    "The current world time is the only valid time reference.\n"
    "Do not infer time from replay playback, simulation step, or legacy replay time.\n"
    "Do not mention midnight unless the Current World Time is midnight.\n"
    "Do not output memory lists, system text, JSON, markdown, analysis, or narration.\n"
    "Do not invent major events or change the schedule.\n"
    "Return only spoken dialogue in 1-3 short sentences, under 50 words.\n\n"
    f"NPC: {values['target_npc']}\n"
    f"Location: {values['location']}\n"
    f"Current World Time: {world_time.get('display')}\n"
    f"Goal State Context:\n{goal_state_text}\n"
    f"Past memories:\n{past_memory_text}\n"
    f"## Relevant Previous Knowledge\n{knowledge_text}\n"
    f"## Relevant NPC Beliefs\n{belief_text}\n"
    f"## Player Relationship Context\nRelationship state: {relationship_state}\nRelationship score: {relationship_score}\n{relationship_text}\n"
    f"Recent dialogue:\n{recent_dialogue}\n"
    f"Current player message: {values['player_utterance']}\n"
  )


def clean_live_dialogue_reply(reply):
  cleaned = (reply or "").strip().strip("\"'")
  cleaned = re.sub(r"^\s*(NPC|Assistant|[^:\n]{1,30}):\s*", "", cleaned).strip()
  words = cleaned.split()
  if len(words) > 50:
    cleaned = " ".join(words[:50])
  return cleaned


def preview_text(text, limit=500):
  text = str(text or "")
  return text[:limit]


def build_live_dialogue_memory_fields(player_utterance, npc_reply, target_npc, location):
  player_utterance = re.sub(r"\s+", " ", player_utterance or "").strip()
  lowered = player_utterance.lower()
  if any(token in lowered for token in ["can you", "could you", "please", "help", "favor", "favour", "would you"]):
    if any(token in lowered for token in ["market", "vendor", "vendors", "ask around", "around"]):
      return {
        "memory_type": "request",
        "content": f"The player requested {target_npc} to ask vendors about market conditions.",
        "action": "ask vendors",
        "topic": "market information",
        "target": target_npc,
        "status": "pending",
      }
    else:
      return {
        "memory_type": "request",
        "content": f"The player requested help from {target_npc}.",
        "action": "help player",
        "topic": "player request",
        "target": target_npc,
        "status": "pending",
      }
  elif any(token in lowered for token in ["i heard", "maybe", "not sure", "someone said", "rumor", "rumour", "might", "possibly"]):
    return {
      "memory_type": "report",
      "content": f"The player gave {target_npc} an unverified report that may need quiet checking.",
      "action": "verify report",
      "topic": "unverified report",
      "target": target_npc,
      "status": "pending",
    }
  else:
    return {
      "memory_type": "conversation",
      "content": f"The player spoke with {target_npc} at the {location}.",
      "action": "remember conversation",
      "topic": "live dialogue",
      "target": target_npc,
      "status": "noted",
    }


def summarize_live_dialogue_memory(player_utterance, npc_reply, target_npc, location):
  return build_live_dialogue_memory_fields(
    player_utterance,
    npc_reply,
    target_npc,
    location,
  )["content"][:300]


def call_deepseek_live_dialogue(prompt):
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    raise RuntimeError("DEEPSEEK_API_KEY is not set.")
  payload = {
    "model": LIVE_DIALOGUE_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.4,
    "max_tokens": LIVE_DIALOGUE_MAX_TOKENS,
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
  with urllib.request.urlopen(request, timeout=LIVE_DIALOGUE_TIMEOUT_SEC) as response:
    response_status = getattr(response, "status", None) or response.getcode()
    response_body = response.read().decode("utf-8")
  response_payload = json.loads(response_body)
  try:
    choice = response_payload["choices"][0]
    message = choice["message"]
    raw_content = message["content"]
  except (KeyError, IndexError, TypeError) as exc:
    raise RuntimeError("DeepSeek API response did not include choices[0].message.content.") from exc
  reasoning_content = message.get("reasoning_content", "")
  return {
    "raw_content": raw_content or "",
    "finish_reason": choice.get("finish_reason", ""),
    "content_length": len(raw_content or ""),
    "reasoning_length": len(reasoning_content or ""),
    "response_status": response_status,
    "response_payload_preview": preview_text(response_body),
  }


def write_live_dialogue_log(payload):
  log_dir = live_dialogue_log_dir()
  log_dir.mkdir(parents=True, exist_ok=True)
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  log_path = log_dir / f"live_dialogue_{timestamp}.json"
  with open(log_path, "w", encoding="utf-8") as log_file:
    json.dump(payload, log_file, ensure_ascii=False, indent=2)
  try:
    return str(log_path.relative_to(project_root()))
  except ValueError:
    return str(log_path)


def live_dialogue_session_bucket(request):
  histories = request.session.get("live_dialogue_histories", {})
  if not isinstance(histories, dict):
    histories = {}
  return histories


def append_live_dialogue_session_history(request, sim_code, target_npc, player_utterance, npc_reply):
  histories = live_dialogue_session_bucket(request)
  sim_histories = histories.get(sim_code, {})
  if not isinstance(sim_histories, dict):
    sim_histories = {}
  target_history = sim_histories.get(target_npc, [])
  if not isinstance(target_history, list):
    target_history = []
  target_history.extend(
    [
      {"role": "player", "text": str(player_utterance or "")},
      {"role": "npc", "text": str(npc_reply or "")},
    ]
  )
  sim_histories[target_npc] = target_history[-20:]
  histories[sim_code] = sim_histories
  request.session["live_dialogue_histories"] = histories
  world_time = get_current_world_time()
  request.session["current_live_context"] = {
    "sim_code": sim_code,
    "target_npc": target_npc,
    "location": request.POST.get("location", "").strip(),
    "world_time": world_time,
    "last_player_message": str(player_utterance or ""),
    "last_npc_reply": str(npc_reply or ""),
    "dialogue_history": sim_histories[target_npc],
  }
  request.session.modified = True
  return sim_histories[target_npc]


def session_dialogue_histories_for_demo(request, sim_code):
  histories = live_dialogue_session_bucket(request)
  sim_histories = histories.get(sim_code, {})
  if not isinstance(sim_histories, dict):
    return {}
  frontend_histories = {}
  for npc_name, history in sim_histories.items():
    if not isinstance(history, list):
      continue
    frontend_histories[f"{sim_code}::{npc_name}"] = [
      item for item in history
      if isinstance(item, dict) and item.get("role") in {"player", "npc"}
    ][-20:]
  return frontend_histories


def current_live_context_for_demo(request, sim_code):
  context = request.session.get("current_live_context", {})
  if not isinstance(context, dict):
    return {}
  if context.get("sim_code") != sim_code:
    return {}
  return context


def deterministic_event_feedback(values):
  event_type = str(values.get("event_type", "")).strip()
  target_npc = str(values.get("target_npc", "")).strip()
  player_action = str(values.get("player_action", "")).strip()
  lowered = player_action.lower()
  if event_type == "object_disruption":
    return {
      "action": "investigate reported disruption",
      "content": f"{target_npc} investigated the reported disruption.",
    }
  if event_type == "uncertain_report":
    return {
      "action": "check reported information",
      "content": f"{target_npc} checked the reported information cautiously.",
    }
  if "market" in lowered and ("vendor" in lowered or "vendors" in lowered or "ask" in lowered):
    return {
      "action": "ask vendors about market information",
      "content": f"{target_npc} followed up on the player's request and gathered market information.",
    }
  return {
    "action": "follow up on player request",
    "content": f"{target_npc} followed up on the player's request.",
  }


def latest_pending_request_memory_id(npc_name):
  try:
    memories = load_npc_memory(npc_name)
  except Exception:
    return ""
  for memory in reversed(memories):
    if str(memory.get("type", "")).lower() != "request":
      continue
    if str(memory.get("status", "")).lower() != "pending":
      continue
    return str(memory.get("id") or memory.get("memory_id") or "").strip()
  return ""


def landing(request): 
  context = {}
  template = "landing/landing.html"
  return render(request, template, context)


def player_interventions(request):
  scenarios = [
    {
      "title": "Move Lysa's Ledger",
      "type": "Physical / object disruption",
      "player_action": "The player moves Lysa's trade ledger at 12:00.",
      "npc_response": "Lysa searches for the ledger, asks nearby NPCs, and uses temporary notes.",
      "tests": "Practical replanning after object disruption",
      "affected_npc": "Lysa Vale",
      "inspect": ["Memory", "Conversation History", "Agent's Thought"],
      "url": "/demo/player_intervention_20260708_220045/0/3/",
      "scenario": "player_takes_lysa_ledger",
    },
    {
      "title": "Report Unusual Stall to Tovan",
      "type": "Uncertain information intervention",
      "player_action": "The player tells Tovan that one market stall looked unusual.",
      "npc_response": "Tovan adjusts patrol quietly without treating the report as confirmed fact.",
      "tests": "Cautious verification of player-provided information",
      "affected_npc": "Tovan Reed",
      "inspect": ["Memory", "Conversation History", "Agent's Thought"],
      "url": "/demo/player_intervention_20260708_221323/0/3/",
      "scenario": "player_reports_market_disturbance",
    },
    {
      "title": "Ask Mira to Close Early",
      "type": "Social request / NPC autonomy",
      "player_action": "The player asks Mira to close the tea shop early and help look for market information.",
      "npc_response": "Mira offers partial help while preserving responsibility to customers.",
      "tests": "NPC autonomy and compromise",
      "affected_npc": "Mira Chen",
      "inspect": ["Memory", "Conversation History", "Agent's Thought"],
      "url": "/demo/player_intervention_20260708_222607/0/3/",
      "scenario": "player_asks_mira_to_close_shop_early",
    },
  ]
  context = {"scenarios": scenarios}
  template = "player_interventions.html"
  return render(request, template, context)


def player_intervention_runs(request):
  index_path = project_root() / "experiments" / "player_intervention" / "player_intervention_run_index.json"
  index_exists = index_path.is_file()
  runs = []
  run_count = 0
  if index_exists:
    try:
      with open(index_path, encoding="utf-8") as index_file:
        payload = json.load(index_file)
      runs = payload.get("runs", [])
      run_count = payload.get("run_count", len(runs))
    except Exception:
      index_exists = False
      runs = []
      run_count = 0
  context = {
    "index_exists": index_exists,
    "runs": runs,
    "run_count": run_count,
    "index_path": "experiments/player_intervention/player_intervention_run_index.json",
  }
  return render(request, "player_intervention_runs.html", context)


def player_intervention_world_tick(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)
  bootstrap_npc_schedules()
  try:
    step_minutes = int(request.POST.get("step_minutes") or 60)
  except (TypeError, ValueError):
    step_minutes = 60
  if step_minutes not in (10, 60):
    step_minutes = 60
  state = advance_world_time(step_minutes)
  spatial_state = load_npc_spatial_state()
  return JsonResponse(
    {
      "ok": True,
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "08:00"),
      "time_step_minutes": state.get("time_step_minutes", 60),
      "planner_mode": state.get("planner_mode", "deterministic"),
      "previous_day_summary": state.get("previous_day_summary", []),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "last_spatial_arrivals": state.get("last_spatial_arrivals", []),
      "last_arrival_observations": state.get("last_arrival_observations", []),
      "npc_spatial_state": spatial_state,
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "last_tick": state.get("last_tick", ""),
    }
  )


def player_intervention_world_reset(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)
  state = reset_world_time()
  return JsonResponse(
    {
      "ok": True,
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "08:00"),
      "time_step_minutes": state.get("time_step_minutes", 60),
      "planner_mode": state.get("planner_mode", "deterministic"),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "npc_spatial_state": load_npc_spatial_state(),
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "status": "World time reset to Day 1 07:00.",
    }
  )


def player_intervention_clean_simulation(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)
  state = clean_simulation_state()
  request.session["live_dialogue_histories"] = {}
  request.session["current_live_context"] = {}
  request.session.modified = True
  return JsonResponse(
    {
      "ok": True,
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "07:00"),
      "time_step_minutes": state.get("time_step_minutes", 60),
      "planner_mode": state.get("planner_mode", "deterministic"),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "previous_day_summary": state.get("previous_day_summary", []),
      "npc_spatial_state": load_npc_spatial_state(),
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "cleared": state.get("last_clean_simulation", {}).get("cleared", {}),
      "status": "Clean simulation reset complete. Player interaction history was cleared.",
    }
  )


def player_intervention_world_jump(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)
  state = jump_world_time(
    request.POST.get("day", "1"),
    request.POST.get("time", "08:00"),
  )
  return JsonResponse(
    {
      "ok": True,
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "08:00"),
      "time_step_minutes": state.get("time_step_minutes", 60),
      "planner_mode": state.get("planner_mode", "deterministic"),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "npc_spatial_state": load_npc_spatial_state(),
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "status": "World time jumped.",
    }
  )


def player_intervention_world_planner_mode(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)
  state = set_planner_mode(
    request.POST.get("planner_mode", "deterministic"),
    regenerate_current_day=False,
  )
  return JsonResponse(
    {
      "ok": True,
      "planner_mode": state.get("planner_mode", "deterministic"),
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "08:00"),
      "time_step_minutes": state.get("time_step_minutes", 60),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "npc_spatial_state": load_npc_spatial_state(),
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "status": "Planner mode set to %s. Existing daily plan was not regenerated." % state.get("planner_mode", "deterministic"),
    }
  )


def player_intervention_regenerate_daily_plan(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "success": False, "error": "POST required."}, status=405)
  state = load_world_state()
  day_text = request.POST.get("day", "").strip()
  day = None
  if day_text:
    try:
      day = int(day_text)
    except (TypeError, ValueError):
      return JsonResponse({"ok": False, "success": False, "error": "Invalid day."}, status=400)
  npc_name = request.POST.get("npc_name", "").strip()
  try:
    state, generated_npcs = regenerate_daily_plan_for_day(day=day, npc_name=npc_name or None)
  except ValueError as exc:
    return JsonResponse({"ok": False, "success": False, "error": str(exc)}, status=400)
  return JsonResponse(
    {
      "ok": True,
      "success": True,
      "day": int(day or state.get("current_day") or 1),
      "planner_mode": state.get("planner_mode", "deterministic"),
      "generated_npcs": generated_npcs,
      "current_day": state.get("current_day", 1),
      "current_time": state.get("current_time", "08:00"),
      "active_actions": state.get("active_actions", []),
      "completed_actions": state.get("completed_actions", []),
      "last_executed_actions": state.get("last_executed_actions", []),
      "last_time_catchup_log": state.get("last_time_catchup_log", []),
      "time_catchup_log": state.get("time_catchup_log", []),
      "npc_spatial_state": load_npc_spatial_state(),
      "npc_daily_plans": state.get("npc_daily_plans", {}),
      "last_daily_planning": state.get("last_daily_planning", {}),
      "status": "Regenerated daily plan for %s." % (", ".join(generated_npcs) if generated_npcs else "no NPCs"),
    }
  )


def generate_player_intervention(request):
  if request.method != "POST":
    return HttpResponseBadRequest("POST required.")

  scenario = request.POST.get("scenario", "").strip()
  if scenario not in ALLOWED_PLAYER_INTERVENTION_SCENARIOS:
    append_player_intervention_generation_log(
      scenario=scenario,
      success=False,
      return_code="not_run",
      error_message="Scenario is not allowlisted.",
    )
    return HttpResponseBadRequest("Unsupported player intervention scenario.")

  root = project_root()
  backend_dir = root / "reverie" / "backend_server"
  command = [
    sys.executable,
    "run_player_intervention_demo.py",
    "--backend",
    "api",
    "--model",
    "deepseek-v4-flash",
    "--scenario",
    scenario,
  ]

  try:
    completed = subprocess.run(
      command,
      cwd=str(backend_dir),
      capture_output=True,
      text=True,
      timeout=240,
    )
  except subprocess.TimeoutExpired as exc:
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    append_player_intervention_generation_log(
      scenario=scenario,
      success=False,
      return_code="timeout",
      error_message="Generation timed out.",
      stdout=stdout,
      stderr=stderr,
    )
    return render_player_intervention_error(
      request,
      scenario,
      "Generation timed out. Please try again or use an existing replay.",
      stdout,
      stderr,
    )

  stdout = completed.stdout or ""
  stderr = completed.stderr or ""
  demo_path_match = re.search(r"^GENERATED_DEMO_PATH=(.+)$", stdout, re.MULTILINE)
  demo_path = demo_path_match.group(1).strip() if demo_path_match else ""

  if completed.returncode != 0:
    append_player_intervention_generation_log(
      scenario=scenario,
      success=False,
      return_code=completed.returncode,
      error_message="Generation subprocess returned a non-zero exit code.",
      stdout=stdout,
      stderr=stderr,
    )
    return render_player_intervention_error(
      request,
      scenario,
      "Generation failed. Please use an existing replay or try again.",
      stdout,
      stderr,
    )

  if not demo_path:
    append_player_intervention_generation_log(
      scenario=scenario,
      success=False,
      return_code=completed.returncode,
      error_message="Generation completed but GENERATED_DEMO_PATH was not found.",
      stdout=stdout,
      stderr=stderr,
    )
    return render_player_intervention_error(
      request,
      scenario,
      "Generation completed, but the new replay path could not be found.",
      stdout,
      stderr,
    )

  append_player_intervention_generation_log(
    scenario=scenario,
    success=True,
    demo_path=demo_path,
    return_code=completed.returncode,
  )
  return redirect(demo_path)


def live_player_dialogue(request):
  if request.method != "POST":
    return JsonResponse({"ok": False, "error": "POST required."}, status=405)

  values, errors = validate_live_dialogue_request(request.POST)
  base_log = {
    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    "sim_code": values.get("sim_code", ""),
    "step": values.get("step", ""),
    "target_npc": values.get("target_npc", ""),
    "location": values.get("location", ""),
    "player_utterance": values.get("player_utterance", ""),
    "dialogue_history_used": values.get("dialogue_history", []),
    "backend": LIVE_DIALOGUE_BACKEND,
    "model": LIVE_DIALOGUE_MODEL,
  }

  if errors:
    log_payload = dict(base_log)
    log_payload.update({"success": False, "error": "; ".join(errors), "elapsed_sec": 0})
    log_path = write_live_dialogue_log(log_payload)
    return JsonResponse({"ok": False, "error": "; ".join(errors), "log_path": log_path}, status=400)

  agent_config = load_agent_config(request.POST.get("agent_config", ""))
  base_log["agent_config"] = agent_config
  world_time = get_current_world_time()
  base_log.update(
    {
      "world_day": world_time.get("day"),
      "world_time": world_time.get("time"),
      "world_time_display": world_time.get("display"),
      "legacy_replay_time": values.get("current_time") or f"step {values['step']}",
    }
  )

  if agent_config.get("use_memory", True):
    relevant_memories = retrieve_relevant_memories(
      values["target_npc"],
      values["player_utterance"],
      max_results=3,
    )
  else:
    relevant_memories = []
  if agent_config.get("use_memory", True) or agent_config.get("use_knowledge", True):
    goal_context = retrieve_goal_state_context(
      values["target_npc"],
      values["player_utterance"],
      max_results=5,
    )
  else:
    goal_context = []
  current_goal_text = " ".join(
    str(goal.get("goal") or "")
    for goal in goal_context
    if isinstance(goal, dict) and str(goal.get("status", "")).lower() in {"pending", "active", "completed"}
  )
  try:
    relevant_knowledge = retrieve_relevant_dialogue_knowledge(
      values["target_npc"],
      values["player_utterance"],
      current_goal=current_goal_text,
      current_location=values["location"],
      max_results=3,
    ) if agent_config.get("use_knowledge", True) else []
    knowledge_retrieval_error = ""
  except Exception as exc:
    relevant_knowledge = []
    knowledge_retrieval_error = str(exc)
  try:
    if agent_config.get("use_world_grounding", True) and agent_config.get("use_belief", True):
      relevant_npc_beliefs = retrieve_relevant_npc_beliefs(
        values["target_npc"],
        values["player_utterance"],
        current_location=values["location"],
        current_goal=current_goal_text,
        max_results=5,
      )
    else:
      relevant_npc_beliefs = []
    belief_retrieval_error = ""
  except Exception as exc:
    relevant_npc_beliefs = []
    belief_retrieval_error = str(exc)
  memories_used = [memory.get("content", "") for memory in relevant_memories if memory.get("content")]
  knowledge_used = [
    {
      "knowledge_id": knowledge.get("knowledge_id", ""),
      "related_goal": knowledge.get("related_goal", ""),
      "summary": knowledge_summary_text(knowledge),
      "findings": knowledge.get("findings", []),
      "evidence": knowledge_evidence_preview(knowledge, limit=3),
      "time": knowledge.get("time", ""),
    }
    for knowledge in relevant_knowledge
  ]
  dialogue_knowledge_context = dialogue_knowledge_context_summary(relevant_knowledge)
  dialogue_knowledge_context["target_npc"] = values["target_npc"]
  dialogue_knowledge_context["location"] = values["location"]
  dialogue_knowledge_context["player_message"] = values["player_utterance"]
  dialogue_knowledge_context["retrieval_error"] = knowledge_retrieval_error
  dialogue_knowledge_context["agent_config"] = agent_config
  dialogue_world_grounding_context = npc_belief_context_summary(relevant_npc_beliefs)
  dialogue_world_grounding_context["target_npc"] = values["target_npc"]
  dialogue_world_grounding_context["location"] = values["location"]
  dialogue_world_grounding_context["player_message"] = values["player_utterance"]
  dialogue_world_grounding_context["retrieval_error"] = belief_retrieval_error
  dialogue_world_grounding_context["agent_config"] = agent_config
  try:
    state = load_world_state()
    state["last_dialogue_knowledge_context"] = dialogue_knowledge_context
    state["last_dialogue_world_grounding_context"] = dialogue_world_grounding_context
    save_world_state(state)
  except Exception:
    pass
  if agent_config.get("use_relationship", True):
    relationship_context = retrieve_relevant_relationship_context(
      values["target_npc"],
      values["player_utterance"],
      max_results=3,
    )
  else:
    relationship_context = {"relationship_state": "neutral", "positive_memories": [], "negative_memories": [], "memories": []}
  relationship_used = dialogue_relationship_context_summary(relationship_context)
  relationship_used["target_npc"] = values["target_npc"]
  relationship_used["player_message"] = values["player_utterance"]
  relationship_used["agent_config"] = agent_config
  try:
    state = load_world_state()
    state["last_dialogue_relationship_context"] = relationship_used
    save_world_state(state)
  except Exception:
    pass
  goal_context_used = [
    {
      "goal": goal.get("goal", ""),
      "status": goal.get("status", ""),
      "target_location": goal.get("target_location") or goal.get("location", ""),
      "completed_time": goal.get("completed_time", ""),
      "completed_world_day": goal.get("completed_world_day", ""),
      "completed_world_time": goal.get("completed_world_time", ""),
      "source_memory_id": goal.get("source_memory_id", ""),
    }
    for goal in goal_context
  ]
  prompt = live_dialogue_prompt(
    values,
    relevant_memories,
    relevant_knowledge,
    goal_context,
    relationship_context,
    relevant_npc_beliefs,
    agent_config,
  )
  prompt_chars = len(prompt)
  history_messages_used = len(values["dialogue_history"])
  total_started = time.time()
  llm_started = time.time()
  try:
    api_result = call_deepseek_live_dialogue(prompt)
    elapsed_llm_sec = round(time.time() - llm_started, 3)
    raw_reply = api_result.get("raw_content", "")
    npc_reply = clean_live_dialogue_reply(raw_reply)
    elapsed_total_sec = round(time.time() - total_started, 3)
    if not npc_reply:
      log_payload = dict(base_log)
      log_payload.update(
        {
          "success": False,
          "error": "LLM returned empty response.",
          "api_error_type": "empty_llm_response",
          "api_error_message": "LLM returned empty response.",
          "fallback_used": False,
          "fallback_reason": "",
          "raw_response_preview": preview_text(raw_reply),
          "parsed_reply": "",
          "response_status": api_result.get("response_status"),
          "max_tokens": LIVE_DIALOGUE_MAX_TOKENS,
          "finish_reason": api_result.get("finish_reason", ""),
          "content_length": api_result.get("content_length", 0),
          "reasoning_length": api_result.get("reasoning_length", 0),
          "recent_memories_used": memories_used,
          "relevant_knowledge_used": knowledge_used,
          "dialogue_knowledge_context": dialogue_knowledge_context,
          "dialogue_world_grounding_context": dialogue_world_grounding_context,
          "relationship_context_used": relationship_used,
          "goal_context_used": goal_context_used,
          "elapsed_sec": elapsed_total_sec,
          "elapsed_total_sec": elapsed_total_sec,
          "elapsed_llm_sec": elapsed_llm_sec,
          "prompt_chars": prompt_chars,
          "prompt_preview": preview_text(prompt),
          "reply_chars": 0,
          "history_messages_used": history_messages_used,
        }
      )
      log_path = write_live_dialogue_log(log_payload)
      return JsonResponse(
        {
          "ok": False,
          "error": "LLM returned empty response.",
          "log_path": log_path,
        },
        status=502,
      )
    grounding_check = check_world_grounding_consistency(
      npc_reply,
      relevant_world_facts=relevant_npc_beliefs,
    ) if agent_config.get("use_world_grounding", True) else {"grounded": True, "warnings": [], "checked_text": npc_reply[:500], "relevant_world_fact_ids": []}
    try:
      state = load_world_state()
      dialogue_world_grounding_context["grounding_check"] = grounding_check
      state["last_dialogue_world_grounding_context"] = dialogue_world_grounding_context
      save_world_state(state)
    except Exception:
      pass
    memory_entry = None
    reflection_entry = None
    memory_error = ""
    recent_memories = []
    try:
      memory_fields = build_live_dialogue_memory_fields(
        values["player_utterance"],
        npc_reply,
        values["target_npc"],
        values["location"],
      )
      memory_entry = write_memory_entry(
        npc=values["target_npc"],
        memory_type=memory_fields["memory_type"],
        time_text=values.get("current_time") or f"step {values['step']}",
        content=memory_fields["content"],
        source="live_dialogue",
        importance="medium",
        action=memory_fields["action"],
        topic=memory_fields["topic"],
        target=memory_fields["target"],
        status=memory_fields["status"],
        metadata={
          "sim_code": values["sim_code"],
          "step": values["step"],
          "location": values["location"],
          "player_utterance": values["player_utterance"],
          "npc_reply": npc_reply,
        },
      )
      reflection_entry = create_reflection_entry(memory_entry)
      recent_memories = get_recent_memories(values["target_npc"], limit=3)
    except Exception as exc:
      memory_error = str(exc)
    social_signal = interpret_relationship_signal_with_llm(
      values["target_npc"],
      values["player_utterance"],
      npc_reply=npc_reply,
      conversation_context=values.get("dialogue_history", []),
    )
    relationship_update = None
    relationship_update_error = ""
    try:
      state = load_world_state()
      relationship_update = append_dialogue_relationship_memory(
        state,
        values["target_npc"],
        values["player_utterance"],
        social_signal,
      )
      if relationship_update:
        save_world_state(state)
    except Exception as exc:
      relationship_update_error = str(exc)
    session_history = append_live_dialogue_session_history(
      request,
      values["sim_code"],
      values["target_npc"],
      values["player_utterance"],
      npc_reply,
    )
    log_payload = dict(base_log)
    log_payload.update(
      {
        "npc_reply": npc_reply,
        "live_memory_written": memory_entry is not None,
        "live_memory_entry": memory_entry,
        "live_reflection_written": reflection_entry is not None,
        "live_reflection_entry": reflection_entry,
        "live_memory_error": memory_error,
        "social_signal": social_signal,
        "relationship_update": relationship_update,
        "relationship_update_error": relationship_update_error,
        "world_day": world_time.get("day"),
        "world_time": world_time.get("time"),
        "world_time_display": world_time.get("display"),
        "legacy_replay_time": values.get("current_time") or f"step {values['step']}",
        "recent_memories_used": memories_used,
        "relevant_knowledge_used": knowledge_used,
        "dialogue_knowledge_context": dialogue_knowledge_context,
        "dialogue_world_grounding_context": dialogue_world_grounding_context,
        "grounding_check": grounding_check,
        "relationship_context_used": relationship_used,
        "goal_context_used": goal_context_used,
        "fallback_used": False,
        "fallback_reason": "",
        "raw_response_preview": preview_text(raw_reply),
        "parsed_reply": npc_reply,
        "api_error_type": "",
        "api_error_message": "",
        "response_status": api_result.get("response_status"),
        "max_tokens": LIVE_DIALOGUE_MAX_TOKENS,
        "finish_reason": api_result.get("finish_reason", ""),
        "content_length": api_result.get("content_length", 0),
        "reasoning_length": api_result.get("reasoning_length", 0),
        "elapsed_sec": elapsed_total_sec,
        "elapsed_total_sec": elapsed_total_sec,
        "elapsed_llm_sec": elapsed_llm_sec,
        "prompt_chars": prompt_chars,
        "prompt_preview": preview_text(prompt),
        "reply_chars": len(npc_reply),
        "history_messages_used": history_messages_used,
        "success": True,
      }
    )
    log_path = write_live_dialogue_log(log_payload)
    return JsonResponse(
      {
        "ok": True,
        "target_npc": values["target_npc"],
        "location": values["location"],
        "player_utterance": values["player_utterance"],
        "npc_reply": npc_reply,
        "backend": LIVE_DIALOGUE_BACKEND,
        "model": LIVE_DIALOGUE_MODEL,
        "elapsed_sec": elapsed_total_sec,
        "elapsed_total_sec": elapsed_total_sec,
        "elapsed_llm_sec": elapsed_llm_sec,
        "prompt_chars": prompt_chars,
        "reply_chars": len(npc_reply),
        "max_tokens": LIVE_DIALOGUE_MAX_TOKENS,
        "finish_reason": api_result.get("finish_reason", ""),
        "content_length": api_result.get("content_length", 0),
        "reasoning_length": api_result.get("reasoning_length", 0),
        "history_messages_used": history_messages_used,
        "fallback_used": False,
        "fallback_reason": "",
        "live_memory_written": memory_entry is not None,
        "live_memory_entry": memory_entry,
        "social_signal": social_signal,
        "relationship_update": relationship_update,
        "relationship_update_error": relationship_update_error,
        "recent_memories": recent_memories,
        "recent_memories_used": memories_used,
        "memories_used": memories_used,
        "knowledge_used": knowledge_used,
        "dialogue_knowledge_context": dialogue_knowledge_context,
        "belief_context_used": dialogue_world_grounding_context,
        "grounding_check": grounding_check,
        "relationship_context_used": relationship_used,
        "goal_context_used": goal_context_used,
        "session_dialogue_history": session_history,
        "world_time": world_time,
        "legacy_replay_time": values.get("current_time") or f"step {values['step']}",
        "live_memory_error": memory_error,
        "log_path": log_path,
      }
    )
  except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
    elapsed_total_sec = round(time.time() - total_started, 3)
    safe_error = str(exc)
    if "Bearer " in safe_error:
      safe_error = "Live dialogue API request failed."
    api_error_type = exc.__class__.__name__
    response_status = None
    response_preview = ""
    if isinstance(exc, urllib.error.HTTPError):
      response_status = exc.code
      try:
        response_preview = preview_text(exc.read().decode("utf-8", errors="replace"))
      except Exception:
        response_preview = ""
    log_payload = dict(base_log)
    log_payload.update(
      {
        "success": False,
        "error": safe_error,
        "api_error_type": api_error_type,
        "api_error_message": safe_error,
        "fallback_used": False,
        "fallback_reason": "",
        "raw_response_preview": response_preview,
        "parsed_reply": "",
        "response_status": response_status,
        "max_tokens": LIVE_DIALOGUE_MAX_TOKENS,
        "finish_reason": "",
        "content_length": 0,
        "reasoning_length": 0,
        "recent_memories_used": memories_used,
        "relevant_knowledge_used": knowledge_used,
        "dialogue_knowledge_context": dialogue_knowledge_context,
        "relationship_context_used": relationship_used,
        "goal_context_used": goal_context_used,
        "elapsed_sec": elapsed_total_sec,
        "elapsed_total_sec": elapsed_total_sec,
        "elapsed_llm_sec": elapsed_total_sec,
        "prompt_chars": prompt_chars,
        "prompt_preview": preview_text(prompt),
        "reply_chars": 0,
        "history_messages_used": history_messages_used,
      }
    )
    log_path = write_live_dialogue_log(log_payload)
    return JsonResponse({"ok": False, "error": safe_error, "log_path": log_path}, status=500)


def new_player_intervention(request):
  options = custom_event_form_options()
  values = {
    "target_npc": "Mira Chen",
    "event_type": "social_request",
    "player_action": "",
    "event_time": "15:00",
    "location": "Tea Shop",
  }
  errors = []

  if request.method == "GET":
    context = {"options": options, "values": values, "errors": errors}
    return render(request, "structured_player_intervention_form.html", context)

  if request.method != "POST":
    return HttpResponseBadRequest("GET or POST required.")

  values, errors = validate_custom_player_event_form(request.POST)
  if errors:
    append_player_intervention_generation_log(
      scenario="custom_structured_event",
      success=False,
      return_code="not_run",
      error_message="Invalid custom structured player event form.",
      mode="custom_structured_event",
      target_npc=values.get("target_npc", ""),
      event_type=values.get("event_type", ""),
      event_time=values.get("event_time", ""),
      location=values.get("location", ""),
    )
    context = {"options": options, "values": values, "errors": errors}
    return render(request, "structured_player_intervention_form.html", context, status=400)

  event = build_player_event_from_form(
    values["target_npc"],
    values["event_type"],
    values["player_action"],
    values["event_time"],
    values["location"],
  )
  event_path = write_player_event_json(event)

  try:
    completed = run_custom_structured_player_event(event_path)
  except subprocess.TimeoutExpired as exc:
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code="timeout",
      error_message="Custom structured generation timed out.",
      stdout=stdout,
      stderr=stderr,
      mode="custom_structured_event",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=values["event_time"],
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation timed out. Please try again or use an existing replay.",
      stdout,
      stderr,
    )

  stdout = completed.stdout or ""
  stderr = completed.stderr or ""
  demo_path = generated_demo_path_from_stdout(stdout)

  if completed.returncode != 0:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message="Custom structured generation returned a non-zero exit code.",
      stdout=stdout,
      stderr=stderr,
      mode="custom_structured_event",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=values["event_time"],
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation failed. Please use an existing replay or try again.",
      stdout,
      stderr,
    )

  if not demo_path:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message="Custom structured generation completed but GENERATED_DEMO_PATH was not found.",
      stdout=stdout,
      stderr=stderr,
      mode="custom_structured_event",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=values["event_time"],
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation completed, but the new replay path could not be found.",
      stdout,
      stderr,
    )

  append_player_intervention_generation_log(
    scenario=event["name"],
    success=True,
    demo_path=demo_path,
    return_code=completed.returncode,
    mode="custom_structured_event",
    target_npc=values["target_npc"],
    event_type=values["event_type"],
    event_time=values["event_time"],
    location=values["location"],
  )
  return redirect(demo_path)


def inject_player_intervention(request):
  if request.method != "POST":
    return HttpResponseBadRequest("POST required.")

  source_sim_code = request.POST.get("source_sim_code", "").strip()
  source_step_text = request.POST.get("source_step", "").strip()
  if not re.match(r"^[\w-]+$", source_sim_code):
    return HttpResponseBadRequest("Invalid source simulation code.")
  if not re.match(r"^\d+$", source_step_text):
    return HttpResponseBadRequest("Invalid source step.")

  source_step = int(source_step_text)
  meta_path = (
    project_root()
    / "environment"
    / "frontend_server"
    / "compressed_storage"
    / source_sim_code
    / "meta.json"
  )
  if not meta_path.is_file():
    return HttpResponseBadRequest("Source replay metadata was not found.")

  with open(meta_path, encoding="utf-8") as meta_file:
    meta = json.load(meta_file)
  final_step = int(meta.get("step", 144)) - 1
  if source_step < 0 or source_step > final_step:
    return HttpResponseBadRequest("Source step is outside the replay range.")

  computed_event_time = step_to_time_string(source_step, int(meta.get("sec_per_step", 600)))
  mutable_post = request.POST.copy()
  mutable_post["event_time"] = computed_event_time
  replanning_scope = request.POST.get("replanning_scope", "local_2h").strip()
  if replanning_scope not in ALLOWED_REPLANNING_SCOPES:
    replanning_scope = "local_2h"
  source_memory_id = request.POST.get("source_memory_id", "").strip()
  if source_memory_id and not re.match(r"^[A-Za-z0-9_:-]+$", source_memory_id):
    return HttpResponseBadRequest("Invalid source memory id.")
  values, errors = validate_custom_player_event_form(mutable_post, allow_replay_time=True)
  if errors:
    append_player_intervention_generation_log(
      scenario="live_interaction_panel",
      success=False,
      return_code="not_run",
      error_message="Invalid live interaction event form: " + "; ".join(errors),
      mode="live_interaction_panel",
      target_npc=values.get("target_npc", ""),
      event_type=values.get("event_type", ""),
      event_time=computed_event_time,
      location=values.get("location", ""),
    )
    return render_player_intervention_error(
      request,
      "live_interaction_panel",
      "Invalid player event input. Please go back and check the form.",
      status=400,
    )

  if not source_memory_id:
    source_memory_id = latest_pending_request_memory_id(values["target_npc"])

  event = build_player_event_from_form(
    values["target_npc"],
    values["event_type"],
    values["player_action"],
    computed_event_time,
    values["location"],
  )
  event["source_sim_code"] = source_sim_code
  event["source_step"] = source_step
  event["source_mode"] = "live_interaction_panel"
  event_path = write_player_event_json(event, prefix="live_player_event")

  try:
    completed = run_custom_structured_player_event(event_path)
  except subprocess.TimeoutExpired as exc:
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code="timeout",
      error_message="Live interaction generation timed out.",
      stdout=stdout,
      stderr=stderr,
      mode="live_interaction_panel",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=computed_event_time,
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation timed out. Please try again or use an existing replay.",
      stdout,
      stderr,
    )

  stdout = completed.stdout or ""
  stderr = completed.stderr or ""
  demo_path = generated_demo_path_from_stdout(stdout)

  if completed.returncode != 0:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message="Live interaction generation returned a non-zero exit code.",
      stdout=stdout,
      stderr=stderr,
      mode="live_interaction_panel",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=computed_event_time,
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation failed. Please use an existing replay or try again.",
      stdout,
      stderr,
    )

  if not demo_path:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message="Live interaction generation completed but GENERATED_DEMO_PATH was not found.",
      stdout=stdout,
      stderr=stderr,
      mode="live_interaction_panel",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=computed_event_time,
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation completed, but the new replay path could not be found.",
      stdout,
      stderr,
    )

  generated_sim_code = sim_code_from_demo_path(demo_path)
  if not generated_sim_code:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message="Live interaction generation completed but generated sim code could not be parsed.",
      stdout=stdout,
      stderr=stderr,
      mode="live_interaction_panel",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=computed_event_time,
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation completed, but the generated replay code could not be parsed.",
      stdout,
      stderr,
    )

  branch_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
  branch_sim_code = f"player_intervention_branch_{branch_timestamp}"
  try:
    branch_metadata = {
      "event_time": computed_event_time,
      "target_npc": values["target_npc"],
      "event_type": values["event_type"],
      "location": values["location"],
      "player_action": values["player_action"],
      "replanning_scope": replanning_scope,
      "source_memory_id": source_memory_id,
      "world_time": get_current_world_time(),
      "legacy_replay_time": computed_event_time,
    }
    if replanning_scope == "full_day":
      create_branch_replay_from_prefix_and_suffix(
        compressed_storage_root(),
        source_sim_code,
        generated_sim_code,
        source_step,
        branch_sim_code,
        player_event_json_path=event_path,
        branch_metadata=branch_metadata,
      )
    else:
      create_local_window_branch_replay(
        compressed_storage_root(),
        source_sim_code,
        generated_sim_code,
        source_step,
        branch_sim_code,
        local_window_steps=LOCAL_REPLANNING_WINDOW_STEPS,
        player_event_json_path=event_path,
        branch_metadata=branch_metadata,
      )
  except Exception as exc:
    append_player_intervention_generation_log(
      scenario=event["name"],
      success=False,
      return_code=completed.returncode,
      error_message=f"Generated replay succeeded, but branch replay creation failed: {exc}",
      stdout=stdout,
      stderr=stderr,
      mode="live_interaction_panel",
      target_npc=values["target_npc"],
      event_type=values["event_type"],
      event_time=computed_event_time,
      location=values["location"],
    )
    return render_player_intervention_error(
      request,
      event["name"],
      "Generation succeeded, but branch replay creation failed.",
      stdout,
      stderr,
    )

  redirect_path = f"/demo/{branch_sim_code}/{source_step}/3/"
  event_feedback_observation = None
  event_feedback_error = ""
  try:
    feedback = deterministic_event_feedback(values)
    event_feedback_observation = write_observation_entry(
      values["target_npc"],
      feedback["action"],
      time_text=computed_event_time,
      importance="medium",
      source_memory_id=source_memory_id,
      content_override=feedback["content"],
    )
  except Exception as exc:
    event_feedback_error = str(exc)
  append_player_intervention_generation_log(
    scenario=event["name"],
    success=True,
    demo_path=redirect_path,
    return_code=completed.returncode,
    mode="live_interaction_panel",
    target_npc=values["target_npc"],
    event_type=values["event_type"],
    event_time=computed_event_time,
    location=values["location"],
  )
  return redirect(redirect_path)


def demo(request, sim_code, step, play_speed="2"): 
  move_file = f"compressed_storage/{sim_code}/master_movement.json"
  meta_file = f"compressed_storage/{sim_code}/meta.json"
  conversation_timeline_file = f"compressed_storage/{sim_code}/conversation_timeline.json"
  step = int(step)
  play_speed_opt = {"1": 1, "2": 2, "3": 4,
                    "4": 8, "5": 16, "6": 32}
  if play_speed not in play_speed_opt: play_speed = 2
  else: play_speed = play_speed_opt[play_speed]

  # Loading the basic meta information about the simulation.
  meta = dict() 
  with open(meta_file, encoding="utf-8") as json_file:
    meta = json.load(json_file)

  sec_per_step = meta["sec_per_step"]
  start_time = meta.get("start_time", "00:00:00")
  playback_frame_budget = meta.get("playback_frame_budget", 32)
  playback_interval_ms = meta.get("playback_interval_ms", 0)
  raw_run_info = meta.get("run_info", {})
  run_info = {
    "backend": raw_run_info.get("backend") or "N/A",
    "model": raw_run_info.get("model") or "N/A",
    "planning_calls": raw_run_info.get("planning_calls") or 0,
    "planning_success_count": raw_run_info.get("planning_success_count") or 0,
    "conversation_attempts": raw_run_info.get("conversation_attempts") or 0,
    "conversation_success_count": raw_run_info.get("conversation_success_count") or 0,
    "conversation_retry_count": raw_run_info.get("conversation_retry_count") or 0,
    "reflection_calls": raw_run_info.get("reflection_calls") or 0,
    "reflection_success_count": raw_run_info.get("reflection_success_count") or 0,
    "total_elapsed_seconds": raw_run_info.get("total_elapsed_seconds")
                             if raw_run_info.get("total_elapsed_seconds") is not None
                             else "N/A",
    "average_llm_call_time": raw_run_info.get("average_llm_call_time")
                             if raw_run_info.get("average_llm_call_time") is not None
                             else "N/A",
    "estimated_cost_usd": raw_run_info.get("estimated_cost_usd")
                          if raw_run_info.get("estimated_cost_usd") is not None
                          else "N/A",
    "visual_steps": raw_run_info.get("visual_steps", meta.get("step", 0)),
    "visual_step_minutes": raw_run_info.get(
      "visual_step_minutes", sec_per_step / 60
    ),
  }
  start_datetime = datetime.datetime.strptime(meta["start_date"] + " " + start_time, 
                                              '%B %d, %Y %H:%M:%S')
  start_datetime = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")

  # Loading the movement file
  raw_all_movement = dict()
  with open(move_file, encoding="utf-8") as json_file:
    raw_all_movement = json.load(json_file)
  final_step = max(int(key) for key in raw_all_movement.keys())
 
  # Loading all names of the personas
  persona_names = dict()
  persona_names = []
  persona_names_set = set()
  for p in list(raw_all_movement["0"].keys()): 
    persona_names += [{"original": p, 
                       "underscore": p.replace(" ", "_"), 
                       "initial": p[0] + p.split(" ")[-1][0]}]
    persona_names_set.add(p)

  # <all_movement> is the main movement variable that we are passing to the 
  # frontend. Whereas we use ajax scheme to communicate steps to the frontend
  # during the simulation stage, for this demo, we send all movement 
  # information in one step. 
  all_movement = dict()

  # Preparing the initial step. 
  # <init_prep> sets the locations and descriptions of all agents at the
  # beginning of the demo determined by <step>. 
  init_prep = dict() 
  for int_key in range(step+1): 
    key = str(int_key)
    val = raw_all_movement[key]
    for p in persona_names_set: 
      if p in val: 
        init_prep[p] = val[p]
  persona_init_pos = dict()
  for p in persona_names_set: 
    persona_init_pos[p.replace(" ","_")] = init_prep[p]["movement"]
  all_movement[step] = init_prep
  npc_spatial_state = bootstrap_spatial_state_from_replay({"0": init_prep})

  # Finish loading <all_movement>
  for int_key in range(step+1, len(raw_all_movement.keys())): 
    all_movement[int_key] = raw_all_movement[str(int_key)]

  conversation_timeline = {}
  if check_if_file_exists(conversation_timeline_file):
    with open(conversation_timeline_file, encoding="utf-8") as json_file:
      conversation_timeline = json.load(json_file)

  world_state = bootstrap_npc_schedules()
  context = {"sim_code": sim_code,
             "step": step,
             "persona_names": persona_names,
             "persona_init_pos": json.dumps(persona_init_pos), 
             "all_movement": json.dumps(all_movement), 
             "conversation_timeline": json.dumps(conversation_timeline),
             "start_datetime": start_datetime,
             "sec_per_step": sec_per_step,
             "playback_frame_budget": playback_frame_budget,
             "playback_interval_ms": playback_interval_ms,
             "run_info": run_info,
             "world_state": world_state,
             "npc_spatial_state": json.dumps(npc_spatial_state),
             "npc_daily_plans": json.dumps(world_state.get("npc_daily_plans", {})),
             "session_dialogue_histories": json.dumps(session_dialogue_histories_for_demo(request, sim_code)),
             "current_live_context": json.dumps(current_live_context_for_demo(request, sim_code)),
             "final_step": final_step,
             "play_speed": play_speed,
             "mode": "demo"}
  template = "demo/demo.html"

  return render(request, template, context)


def UIST_Demo(request): 
  return demo(request, "March20_the_ville_n25_UIST_RUN-step-1-141", 2160, play_speed="3")


def home(request):
  f_curr_sim_code = "temp_storage/curr_sim_code.json"
  f_curr_step = "temp_storage/curr_step.json"

  if not check_if_file_exists(f_curr_step): 
    context = {}
    template = "home/error_start_backend.html"
    return render(request, template, context)

  with open(f_curr_sim_code) as json_file:  
    sim_code = json.load(json_file)["sim_code"]
  
  with open(f_curr_step) as json_file:  
    step = json.load(json_file)["step"]

  os.remove(f_curr_step)

  persona_names = []
  persona_names_set = set()
  for i in find_filenames(f"storage/{sim_code}/personas", ""): 
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      persona_names += [[x, x.replace(" ", "_")]]
      persona_names_set.add(x)

  persona_init_pos = []
  file_count = []
  for i in find_filenames(f"storage/{sim_code}/environment", ".json"):
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      file_count += [int(x.split(".")[0])]
  curr_json = f'storage/{sim_code}/environment/{str(max(file_count))}.json'
  with open(curr_json) as json_file:  
    persona_init_pos_dict = json.load(json_file)
    for key, val in persona_init_pos_dict.items(): 
      if key in persona_names_set: 
        persona_init_pos += [[key, val["x"], val["y"]]]

  context = {"sim_code": sim_code,
             "step": step, 
             "persona_names": persona_names,
             "persona_init_pos": persona_init_pos,
             "mode": "simulate"}
  template = "home/home.html"
  return render(request, template, context)


def replay(request, sim_code, step): 
  sim_code = sim_code
  step = int(step)

  persona_names = []
  persona_names_set = set()
  for i in find_filenames(f"storage/{sim_code}/personas", ""): 
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      persona_names += [[x, x.replace(" ", "_")]]
      persona_names_set.add(x)

  persona_init_pos = []
  file_count = []
  for i in find_filenames(f"storage/{sim_code}/environment", ".json"):
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      file_count += [int(x.split(".")[0])]
  curr_json = f'storage/{sim_code}/environment/{str(max(file_count))}.json'
  with open(curr_json) as json_file:  
    persona_init_pos_dict = json.load(json_file)
    for key, val in persona_init_pos_dict.items(): 
      if key in persona_names_set: 
        persona_init_pos += [[key, val["x"], val["y"]]]

  context = {"sim_code": sim_code,
             "step": step,
             "persona_names": persona_names,
             "persona_init_pos": persona_init_pos, 
             "mode": "replay"}
  template = "home/home.html"
  return render(request, template, context)


def replay_persona_state(request, sim_code, step, persona_name): 
  sim_code = sim_code
  step = int(step)

  persona_name_underscore = persona_name
  persona_name = " ".join(persona_name.split("_"))
  memory = f"storage/{sim_code}/personas/{persona_name}/bootstrap_memory"
  if not os.path.exists(memory): 
    memory = f"compressed_storage/{sim_code}/personas/{persona_name}/bootstrap_memory"

  with open(memory + "/scratch.json", encoding="utf-8") as json_file:
    scratch = json.load(json_file)

  with open(memory + "/spatial_memory.json", encoding="utf-8") as json_file:
    spatial = json.load(json_file)

  with open(memory + "/associative_memory/nodes.json", encoding="utf-8") as json_file:
    associative = json.load(json_file)

  a_mem_event = []
  a_mem_chat = []
  a_mem_thought = []

  for count in range(len(associative.keys()), 0, -1): 
    node_id = f"node_{str(count)}"
    node_details = associative[node_id]

    if node_details["type"] == "event":
      a_mem_event += [node_details]

    elif node_details["type"] == "chat":
      a_mem_chat += [node_details]

    elif node_details["type"] == "thought":
      a_mem_thought += [node_details]

  live_memories = load_npc_memory(persona_name)
  live_reflections = load_reflections(persona_name)
  live_observations = load_observations(persona_name)
  npc_knowledge = load_npc_knowledge(persona_name)
  agent_config = load_agent_config(request.GET.get("agent_config", ""))
  completed_requests = [
    memory for memory in live_memories
    if str(memory.get("type", "")).lower() == "request"
    and str(memory.get("status", "")).lower() == "completed"
  ]
  world_state = load_world_state()
  npc_goals = sync_npc_goals_from_memory(persona_name, state=world_state, save=True)
  npc_spatial_state = load_npc_spatial_state()
  persona_spatial_state = npc_spatial_state.get(persona_name, {})
  active_actions = [
    action for action in world_state.get("active_actions", [])
    if action.get("npc") == persona_name
  ]
  completed_actions = [
    action for action in world_state.get("completed_actions", [])
    if action.get("npc") == persona_name
  ]
  persona_schedules = [
    item for item in extract_npc_schedule(world_state.get("npc_schedules", []))
    if item.get("npc") == persona_name
  ]
  day_key = f"day_{int(world_state.get('current_day') or 1)}"
  persona_daily_plan = (
    world_state.get("npc_daily_plans", {})
    .get(day_key, {})
    .get(persona_name, {})
  )
  player_relationship = (
    world_state.get("npc_relationships", {})
    .get(persona_name, {})
    .get("player", {})
  )
  npc_belief = load_npc_belief(persona_name)
  unknown_world_facts = unknown_world_truth_for_npc(persona_name, max_results=5)
  authoritative_world_time = {
    "day": world_state.get("current_day", 1),
    "time": world_state.get("current_time", "08:00"),
    "display": f"Day {world_state.get('current_day', 1)} {world_state.get('current_time', '08:00')}",
  }
  relationship_memories = []
  if isinstance(player_relationship, dict):
    relationship_memories.extend(player_relationship.get("positive_memories", []) or [])
    relationship_memories.extend(player_relationship.get("negative_memories", []) or [])
  time_consistency_warnings = build_time_consistency_warnings(
    authoritative_world_time,
    live_memories=live_memories,
    live_reflections=live_reflections,
    live_observations=live_observations,
    npc_knowledge=npc_knowledge,
    active_actions=active_actions,
    completed_actions=completed_actions,
    relationship_memories=relationship_memories,
  )
  
  context = {"sim_code": sim_code,
             "step": step,
             "persona_name": persona_name, 
             "persona_name_underscore": persona_name_underscore, 
             "scratch": scratch,
             "spatial": spatial,
             "a_mem_event": a_mem_event,
             "a_mem_chat": a_mem_chat,
             "a_mem_thought": a_mem_thought,
             "live_memories": list(reversed(live_memories)),
             "live_reflections": list(reversed(live_reflections)),
             "live_observations": list(reversed(live_observations)),
             "npc_knowledge": list(reversed(npc_knowledge)),
             "completed_requests": list(reversed(completed_requests)),
             "active_actions": list(reversed(active_actions)),
             "completed_actions": list(reversed(completed_actions)),
             "npc_schedules": persona_schedules,
             "npc_daily_plan": persona_daily_plan,
             "npc_goals": npc_goals,
             "player_relationship": player_relationship,
             "npc_belief": npc_belief,
             "unknown_world_facts": unknown_world_facts,
             "agent_config": agent_config,
             "authoritative_world_time": authoritative_world_time,
             "time_consistency_warnings": time_consistency_warnings,
             "npc_spatial_state": persona_spatial_state,
             "world_state": world_state,
             "world_timeline": list(reversed(world_state.get("previous_days", [])))}
  template = "persona_state/persona_state.html"
  return render(request, template, context)


def path_tester(request):
  context = {}
  template = "path_tester/path_tester.html"
  return render(request, template, context)


def process_environment(request): 
  """
  <FRONTEND to BACKEND> 
  This sends the frontend visual world information to the backend server. 
  It does this by writing the current environment representation to 
  "storage/environment.json" file. 

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse: string confirmation message. 
  """
  # f_curr_sim_code = "temp_storage/curr_sim_code.json"
  # with open(f_curr_sim_code) as json_file:  
  #   sim_code = json.load(json_file)["sim_code"]

  data = json.loads(request.body)
  step = data["step"]
  sim_code = data["sim_code"]
  environment = data["environment"]

  with open(f"storage/{sim_code}/environment/{step}.json", "w") as outfile:
    outfile.write(json.dumps(environment, indent=2))

  return HttpResponse("received")


def update_environment(request): 
  """
  <BACKEND to FRONTEND> 
  This sends the backend computation of the persona behavior to the frontend
  visual server. 
  It does this by reading the new movement information from 
  "storage/movement.json" file.

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse
  """
  # f_curr_sim_code = "temp_storage/curr_sim_code.json"
  # with open(f_curr_sim_code) as json_file:  
  #   sim_code = json.load(json_file)["sim_code"]

  data = json.loads(request.body)
  step = data["step"]
  sim_code = data["sim_code"]

  response_data = {"<step>": -1}
  if (check_if_file_exists(f"storage/{sim_code}/movement/{step}.json")):
    with open(f"storage/{sim_code}/movement/{step}.json") as json_file: 
      response_data = json.load(json_file)
      response_data["<step>"] = step

  return JsonResponse(response_data)


def path_tester_update(request): 
  """
  Processing the path and saving it to path_tester_env.json temp storage for 
  conducting the path tester. 

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse: string confirmation message. 
  """
  data = json.loads(request.body)
  camera = data["camera"]

  with open(f"temp_storage/path_tester_env.json", "w") as outfile:
    outfile.write(json.dumps(camera, indent=2))

  return HttpResponse("received")
