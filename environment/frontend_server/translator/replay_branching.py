import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def read_json(path):
  with open(path, encoding="utf-8") as json_file:
    return json.load(json_file)


def write_json(path, payload):
  with open(path, "w", encoding="utf-8") as json_file:
    json.dump(payload, json_file, ensure_ascii=False, indent=2)


def copy_tree_contents(source_dir, target_dir):
  for item in source_dir.iterdir():
    target = target_dir / item.name
    if item.is_dir():
      shutil.copytree(item, target)
    else:
      shutil.copy2(item, target)


def combine_step_indexed_json(source_payload, suffix_payload, source_step):
  combined = {}
  all_steps = sorted(
    {int(step) for step in source_payload.keys()}
    | {int(step) for step in suffix_payload.keys()}
  )
  for step in all_steps:
    key = str(step)
    if step < source_step and key in source_payload:
      combined[key] = source_payload[key]
    elif key in suffix_payload:
      combined[key] = suffix_payload[key]
    elif key in source_payload:
      combined[key] = source_payload[key]
  return combined


def combine_step_indexed_lists(source_payload, suffix_payload, source_step):
  combined = {}
  all_steps = sorted(
    {int(step) for step in source_payload.keys()}
    | {int(step) for step in suffix_payload.keys()}
  )
  for step in all_steps:
    key = str(step)
    source_value = source_payload.get(key, [])
    suffix_value = suffix_payload.get(key, [])
    if step < source_step:
      combined[key] = source_value
    elif step > source_step:
      combined[key] = suffix_value
    else:
      merged = []
      if isinstance(source_value, list):
        merged.extend(source_value)
      if isinstance(suffix_value, list):
        merged.extend(suffix_value)
      combined[key] = merged
  return {key: value for key, value in combined.items() if value}


def combine_step_indexed_json_local_window(source_payload, suffix_payload, source_step, local_window_steps):
  combined = {}
  source_step = int(source_step)
  local_window_end = source_step + int(local_window_steps)
  all_steps = sorted(
    {int(step) for step in source_payload.keys()}
    | {int(step) for step in suffix_payload.keys()}
  )
  for step in all_steps:
    key = str(step)
    if source_step <= step < local_window_end and key in suffix_payload:
      combined[key] = suffix_payload[key]
    elif key in source_payload:
      combined[key] = source_payload[key]
    elif key in suffix_payload:
      combined[key] = suffix_payload[key]
  return combined


def combine_step_indexed_lists_local_window(source_payload, suffix_payload, source_step, local_window_steps):
  combined = {}
  source_step = int(source_step)
  local_window_end = source_step + int(local_window_steps)
  all_steps = sorted(
    {int(step) for step in source_payload.keys()}
    | {int(step) for step in suffix_payload.keys()}
  )
  for step in all_steps:
    key = str(step)
    source_value = source_payload.get(key, [])
    suffix_value = suffix_payload.get(key, [])
    if source_step <= step < local_window_end:
      merged = []
      if isinstance(source_value, list):
        merged.extend(source_value)
      if isinstance(suffix_value, list):
        merged.extend(suffix_value)
      combined[key] = merged
    elif isinstance(source_value, list):
      combined[key] = source_value
    elif isinstance(suffix_value, list):
      combined[key] = suffix_value
  return {key: value for key, value in combined.items() if value}


def parse_node_created(node):
  value = node.get("created")
  if not value:
    return None
  for fmt in ("%Y-%m-%d %H:%M:%S", "%B %d, %Y, %H:%M:%S"):
    try:
      return datetime.strptime(str(value), fmt)
    except ValueError:
      continue
  return None


def branch_datetime_from_meta(meta, source_step):
  start_date = str(meta.get("start_date", "June 27, 2026"))
  start_time = str(meta.get("start_time", "00:00:00"))
  sec_per_step = int(meta.get("sec_per_step", 600))
  start = datetime.strptime(f"{start_date} {start_time}", "%B %d, %Y %H:%M:%S")
  return start + timedelta(seconds=int(source_step) * sec_per_step)


def filter_nodes_by_time(nodes, branch_dt, keep_before):
  filtered = []
  for key in sorted(nodes.keys(), key=lambda item: int(item.split("_")[-1])):
    node = dict(nodes[key])
    created = parse_node_created(node)
    if created is None:
      # Keep undated source context and suffix thoughts conservatively.
      if keep_before:
        filtered.append(node)
      continue
    if keep_before and created < branch_dt:
      filtered.append(node)
    elif not keep_before and created >= branch_dt:
      filtered.append(node)
  return filtered


def filter_nodes_in_window(nodes, start_dt, end_dt):
  filtered = []
  for key in sorted(nodes.keys(), key=lambda item: int(item.split("_")[-1])):
    node = dict(nodes[key])
    created = parse_node_created(node)
    if created is not None and start_dt <= created < end_dt:
      filtered.append(node)
  return filtered


def node_identity(node):
  return (
    str(node.get("type", "")),
    str(node.get("created", "")),
    str(node.get("description") or node.get("embedding_key") or ""),
  )


def renumber_nodes(nodes):
  renumbered = {}
  type_counts = {}
  for index, node in enumerate(nodes, start=1):
    node = dict(node)
    node_type = str(node.get("type", "event"))
    type_counts[node_type] = type_counts.get(node_type, 0) + 1
    node["node_count"] = index
    node["type_count"] = type_counts[node_type]
    renumbered[f"node_{index}"] = node
  return renumbered


def merge_persona_state_for_branch(source_dir, suffix_dir, branch_dir, source_step, source_meta):
  branch_dt = branch_datetime_from_meta(source_meta, int(source_step))
  source_personas = source_dir / "personas"
  suffix_personas = suffix_dir / "personas"
  branch_personas = branch_dir / "personas"
  if not source_personas.is_dir() or not suffix_personas.is_dir():
    return []

  merge_records = []
  persona_names = sorted(
    {p.name for p in source_personas.iterdir() if p.is_dir()}
    | {p.name for p in suffix_personas.iterdir() if p.is_dir()}
  )
  for persona_name in persona_names:
    source_nodes_path = (
      source_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    suffix_nodes_path = (
      suffix_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    branch_nodes_path = (
      branch_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    if not source_nodes_path.exists() or not suffix_nodes_path.exists() or not branch_nodes_path.parent.is_dir():
      continue

    source_nodes = read_json(source_nodes_path)
    suffix_nodes = read_json(suffix_nodes_path)
    source_kept = filter_nodes_by_time(source_nodes, branch_dt, keep_before=True)
    suffix_kept = filter_nodes_by_time(suffix_nodes, branch_dt, keep_before=False)
    merged_nodes = renumber_nodes(source_kept + suffix_kept)
    write_json(branch_nodes_path, merged_nodes)
    merge_records.append(
      {
        "persona": persona_name,
        "source_nodes_total": len(source_nodes),
        "suffix_nodes_total": len(suffix_nodes),
        "source_nodes_kept": len(source_kept),
        "suffix_nodes_kept": len(suffix_kept),
        "merged_nodes": len(merged_nodes),
      }
    )
  return merge_records


def merge_persona_state_for_local_branch(
  source_dir,
  suffix_dir,
  branch_dir,
  source_step,
  local_window_steps,
  source_meta,
):
  branch_dt = branch_datetime_from_meta(source_meta, int(source_step))
  sec_per_step = int(source_meta.get("sec_per_step", 600))
  window_end_dt = branch_dt + timedelta(seconds=int(local_window_steps) * sec_per_step)
  source_personas = source_dir / "personas"
  suffix_personas = suffix_dir / "personas"
  branch_personas = branch_dir / "personas"
  if not source_personas.is_dir() or not suffix_personas.is_dir():
    return []

  merge_records = []
  persona_names = sorted(
    {p.name for p in source_personas.iterdir() if p.is_dir()}
    | {p.name for p in suffix_personas.iterdir() if p.is_dir()}
  )
  for persona_name in persona_names:
    source_nodes_path = (
      source_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    suffix_nodes_path = (
      suffix_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    branch_nodes_path = (
      branch_personas
      / persona_name
      / "bootstrap_memory"
      / "associative_memory"
      / "nodes.json"
    )
    if not source_nodes_path.exists() or not suffix_nodes_path.exists() or not branch_nodes_path.parent.is_dir():
      continue

    source_nodes = read_json(source_nodes_path)
    suffix_nodes = read_json(suffix_nodes_path)
    source_kept = [dict(source_nodes[key]) for key in sorted(source_nodes.keys(), key=lambda item: int(item.split("_")[-1]))]
    suffix_window_nodes = filter_nodes_in_window(suffix_nodes, branch_dt, window_end_dt)
    seen = {node_identity(node) for node in source_kept}
    suffix_kept = []
    for node in suffix_window_nodes:
      identity = node_identity(node)
      if identity in seen:
        continue
      seen.add(identity)
      suffix_kept.append(node)
    merged_nodes = renumber_nodes(source_kept + suffix_kept)
    write_json(branch_nodes_path, merged_nodes)
    merge_records.append(
      {
        "persona": persona_name,
        "source_nodes_total": len(source_nodes),
        "suffix_nodes_total": len(suffix_nodes),
        "source_nodes_kept": len(source_kept),
        "suffix_window_nodes_kept": len(suffix_kept),
        "merged_nodes": len(merged_nodes),
      }
    )
  return merge_records


def marker_step(marker):
  if "start_step" in marker:
    try:
      return int(marker["start_step"])
    except (TypeError, ValueError):
      return 0
  return 0


def merge_player_event_markers(source_meta, suffix_meta, source_step):
  source_markers = [
    marker
    for marker in source_meta.get("player_event_markers", [])
    if marker_step(marker) < int(source_step)
  ]
  suffix_markers = [
    marker
    for marker in suffix_meta.get("player_event_markers", [])
    if marker_step(marker) >= int(source_step)
  ]
  return source_markers + suffix_markers


def merge_player_event_markers_local_window(source_meta, suffix_meta, source_step, local_window_steps):
  source_step = int(source_step)
  local_window_end = source_step + int(local_window_steps)
  merged = list(source_meta.get("player_event_markers", []))
  seen = {
    (
      marker_step(marker),
      str(marker.get("event_type", "")),
      str(marker.get("affected_npc", "")),
      str(marker.get("action", "")),
    )
    for marker in merged
  }
  for marker in suffix_meta.get("player_event_markers", []):
    step = marker_step(marker)
    identity = (
      step,
      str(marker.get("event_type", "")),
      str(marker.get("affected_npc", "")),
      str(marker.get("action", "")),
    )
    if source_step <= step < local_window_end and identity not in seen:
      merged.append(marker)
      seen.add(identity)
  return sorted(merged, key=marker_step)


def create_branch_replay_from_prefix_and_suffix(
  compressed_storage_root,
  source_sim_code,
  generated_sim_code,
  source_step,
  branch_sim_code,
  player_event_json_path=None,
  branch_metadata=None,
):
  """Create a replay that preserves source prefix and uses generated suffix."""
  compressed_storage_root = Path(compressed_storage_root)
  source_dir = compressed_storage_root / source_sim_code
  suffix_dir = compressed_storage_root / generated_sim_code
  branch_dir = compressed_storage_root / branch_sim_code

  if not source_dir.is_dir():
    raise FileNotFoundError(f"Source replay not found: {source_dir}")
  if not suffix_dir.is_dir():
    raise FileNotFoundError(f"Generated suffix replay not found: {suffix_dir}")
  if branch_dir.exists():
    raise FileExistsError(f"Branch replay already exists: {branch_dir}")

  branch_dir.mkdir(parents=True)

  # Copy suffix non-step files first so persona state reflects the injected event.
  copy_tree_contents(suffix_dir, branch_dir)

  source_movement = read_json(source_dir / "master_movement.json")
  suffix_movement = read_json(suffix_dir / "master_movement.json")
  branch_movement = combine_step_indexed_json(
    source_movement,
    suffix_movement,
    int(source_step),
  )
  write_json(branch_dir / "master_movement.json", branch_movement)

  source_conversation_path = source_dir / "conversation_timeline.json"
  suffix_conversation_path = suffix_dir / "conversation_timeline.json"
  source_conversation = read_json(source_conversation_path) if source_conversation_path.exists() else {}
  suffix_conversation = read_json(suffix_conversation_path) if suffix_conversation_path.exists() else {}
  branch_conversation = combine_step_indexed_lists(
    source_conversation,
    suffix_conversation,
    int(source_step),
  )
  if branch_conversation:
    write_json(branch_dir / "conversation_timeline.json", branch_conversation)

  source_meta = read_json(source_dir / "meta.json")
  suffix_meta = read_json(suffix_dir / "meta.json")
  branch_info = {
    "mode": "replay_branch_continuation",
    "source_sim_code": source_sim_code,
    "source_step": int(source_step),
    "generated_suffix_sim_code": generated_sim_code,
    "branch_sim_code": branch_sim_code,
    "player_event_json_path": str(player_event_json_path or ""),
    "prefix_source": source_sim_code,
    "suffix_source": generated_sim_code,
    "branch_behavior": "steps before source_step use source replay; source_step and later use generated suffix replay",
    "created_at": datetime.now().isoformat(timespec="seconds"),
  }
  if branch_metadata:
    branch_info.update(branch_metadata)

  branch_meta = dict(suffix_meta)
  for key, default_value in (
    ("start_date", "June 27, 2026"),
    ("start_time", "00:00:00"),
    ("sec_per_step", 600),
    ("step", 144),
  ):
    branch_meta[key] = source_meta.get(key, default_value)
  branch_meta["curr_time"] = source_meta.get("curr_time", branch_meta.get("curr_time", "June 27, 2026, 23:50:00"))
  branch_meta["fork_sim_code"] = source_meta.get("fork_sim_code", source_sim_code)
  branch_meta["player_event_markers"] = merge_player_event_markers(
    source_meta,
    suffix_meta,
    int(source_step),
  )
  merge_records = merge_persona_state_for_branch(
    source_dir,
    suffix_dir,
    branch_dir,
    int(source_step),
    source_meta,
  )
  branch_info["memory_merge"] = {
    "strategy": "source nodes before branch time plus suffix nodes at or after branch time",
    "branch_time": branch_datetime_from_meta(source_meta, int(source_step)).strftime("%Y-%m-%d %H:%M:%S"),
    "persona_records": merge_records,
  }
  branch_meta["branch_info"] = branch_info
  run_info = dict(branch_meta.get("run_info", {}))
  run_info["mode"] = "replay_branch_continuation"
  run_info["source_sim_code"] = source_sim_code
  run_info["source_step"] = int(source_step)
  run_info["generated_suffix_sim_code"] = generated_sim_code
  run_info["visual_steps"] = branch_meta.get("step", 144)
  run_info["visual_step_minutes"] = int(branch_meta.get("sec_per_step", 600)) / 60
  branch_meta["run_info"] = run_info
  write_json(branch_dir / "meta.json", branch_meta)
  write_json(branch_dir / "branch_metadata.json", branch_info)

  return branch_dir


def create_local_window_branch_replay(
  compressed_storage_root,
  source_sim_code,
  generated_sim_code,
  source_step,
  branch_sim_code,
  local_window_steps=12,
  player_event_json_path=None,
  branch_metadata=None,
):
  """Create a branch replay whose generated suffix is limited to a short window."""
  compressed_storage_root = Path(compressed_storage_root)
  source_dir = compressed_storage_root / source_sim_code
  suffix_dir = compressed_storage_root / generated_sim_code
  branch_dir = compressed_storage_root / branch_sim_code
  source_step = int(source_step)
  local_window_steps = int(local_window_steps)
  local_window_end_step = source_step + local_window_steps

  if not source_dir.is_dir():
    raise FileNotFoundError(f"Source replay not found: {source_dir}")
  if not suffix_dir.is_dir():
    raise FileNotFoundError(f"Generated suffix replay not found: {suffix_dir}")
  if branch_dir.exists():
    raise FileExistsError(f"Branch replay already exists: {branch_dir}")

  branch_dir.mkdir(parents=True)
  copy_tree_contents(source_dir, branch_dir)

  source_movement = read_json(source_dir / "master_movement.json")
  suffix_movement = read_json(suffix_dir / "master_movement.json")
  branch_movement = combine_step_indexed_json_local_window(
    source_movement,
    suffix_movement,
    source_step,
    local_window_steps,
  )
  write_json(branch_dir / "master_movement.json", branch_movement)

  source_conversation_path = source_dir / "conversation_timeline.json"
  suffix_conversation_path = suffix_dir / "conversation_timeline.json"
  source_conversation = read_json(source_conversation_path) if source_conversation_path.exists() else {}
  suffix_conversation = read_json(suffix_conversation_path) if suffix_conversation_path.exists() else {}
  branch_conversation = combine_step_indexed_lists_local_window(
    source_conversation,
    suffix_conversation,
    source_step,
    local_window_steps,
  )
  if branch_conversation:
    write_json(branch_dir / "conversation_timeline.json", branch_conversation)

  source_meta = read_json(source_dir / "meta.json")
  suffix_meta = read_json(suffix_dir / "meta.json")
  branch_dt = branch_datetime_from_meta(source_meta, source_step)
  sec_per_step = int(source_meta.get("sec_per_step", 600))
  local_window_end_dt = branch_dt + timedelta(seconds=local_window_steps * sec_per_step)
  branch_info = {
    "mode": "replay_branch_local_window",
    "source_sim_code": source_sim_code,
    "source_step": source_step,
    "generated_suffix_sim_code": generated_sim_code,
    "branch_sim_code": branch_sim_code,
    "player_event_json_path": str(player_event_json_path or ""),
    "prefix_source": source_sim_code,
    "local_window_source": generated_sim_code,
    "resume_source": source_sim_code,
    "local_window_steps": local_window_steps,
    "local_window_end_step": local_window_end_step,
    "branch_behavior": "steps before source_step use source replay; local window uses generated suffix; later steps resume source replay",
    "branch_time": branch_dt.strftime("%Y-%m-%d %H:%M:%S"),
    "local_window_end_time": local_window_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    "created_at": datetime.now().isoformat(timespec="seconds"),
  }
  if branch_metadata:
    branch_info.update(branch_metadata)

  branch_meta = dict(source_meta)
  for key, default_value in (
    ("start_date", "June 27, 2026"),
    ("start_time", "00:00:00"),
    ("sec_per_step", 600),
    ("step", 144),
  ):
    branch_meta[key] = source_meta.get(key, default_value)
  branch_meta["curr_time"] = source_meta.get("curr_time", branch_meta.get("curr_time", "June 27, 2026, 23:50:00"))
  branch_meta["fork_sim_code"] = source_meta.get("fork_sim_code", source_sim_code)
  branch_meta["player_event_markers"] = merge_player_event_markers_local_window(
    source_meta,
    suffix_meta,
    source_step,
    local_window_steps,
  )
  merge_records = merge_persona_state_for_local_branch(
    source_dir,
    suffix_dir,
    branch_dir,
    source_step,
    local_window_steps,
    source_meta,
  )
  branch_info["memory_merge"] = {
    "strategy": "all source nodes plus suffix nodes inside local window",
    "branch_time": branch_dt.strftime("%Y-%m-%d %H:%M:%S"),
    "local_window_end_time": local_window_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    "persona_records": merge_records,
  }
  branch_meta["branch_info"] = branch_info
  run_info = dict(branch_meta.get("run_info", {}))
  run_info["mode"] = "replay_branch_local_window"
  run_info["source_sim_code"] = source_sim_code
  run_info["source_step"] = source_step
  run_info["generated_suffix_sim_code"] = generated_sim_code
  run_info["local_window_steps"] = local_window_steps
  run_info["local_window_minutes"] = local_window_steps * int(branch_meta.get("sec_per_step", 600)) / 60
  run_info["visual_steps"] = branch_meta.get("step", 144)
  run_info["visual_step_minutes"] = int(branch_meta.get("sec_per_step", 600)) / 60
  branch_meta["run_info"] = run_info
  write_json(branch_dir / "meta.json", branch_meta)
  write_json(branch_dir / "branch_metadata.json", branch_info)

  return branch_dir
