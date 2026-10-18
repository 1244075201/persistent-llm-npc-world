import datetime
import importlib.util
import sys
from pathlib import Path


def project_root():
  return Path(__file__).resolve().parents[3]


def _load_smallville_adapter():
  module_name = "_persistent_world_smallville_frontend_adapter"
  if module_name in sys.modules:
    return sys.modules[module_name]
  adapter_path = project_root() / "reverie" / "backend_server" / "smallville_frontend_adapter.py"
  spec = importlib.util.spec_from_file_location(module_name, adapter_path)
  if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load Smallville adapter from {adapter_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = module
  spec.loader.exec_module(module)
  return module


def location_for_action(action, fallback_location="Village"):
  text = f"{action} {fallback_location}".lower()
  if "market" in text or "vendor" in text or "stall" in text:
    return "Market"
  if "tea" in text or "shop" in text or "cafe" in text:
    return "Tea Shop"
  if "guard" in text or "patrol" in text:
    return "Guard Post"
  return fallback_location or "Village"


def create_persistent_route(npc_name, action, location, current_tile, role="persistent world NPC"):
  adapter = _load_smallville_adapter()
  address_tiles = adapter.load_valid_address_tiles()
  category_pools = adapter.build_category_pools(address_tiles)
  _, _, walkable_set = adapter.load_walkable_grid()
  walkable_tiles = sorted(walkable_set)
  nearest_cache = {}
  current = tuple(current_tile or adapter.choose_central_tile(walkable_tiles))
  current = adapter.nearest_walkable_tile(current, walkable_tiles, walkable_set, nearest_cache)
  resolved_location = location_for_action(action, location)
  state = {
    "npc": npc_name,
    "action": action,
    "location": resolved_location,
  }
  decision = adapter.map_semantic_state(npc_name, role, state, category_pools)
  route = adapter.find_transition_route(
    current,
    decision.target.tile,
    walkable_tiles,
    walkable_set,
    nearest_cache,
  )
  route_tiles = [list(tile) for tile in route.path]
  return {
    "npc": npc_name,
    "action": action,
    "location": resolved_location,
    "start_tile": list(current),
    "target_location": resolved_location,
    "target_address": decision.target.address,
    "target_tile": list(decision.target.tile),
    "route": route_tiles,
    "route_algorithm": route.algorithm,
    "route_fallback": route.fallback,
    "route_length": len(route_tiles),
    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
  }
