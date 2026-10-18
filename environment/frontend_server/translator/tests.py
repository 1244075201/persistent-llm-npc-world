from django.test import SimpleTestCase
from unittest.mock import patch

from .memory_importance import assign_memory_importance
from .npc_memory import retrieve_relevant_memories
from .world_state import (
  append_dialogue_relationship_memory,
  append_player_relationship_memory,
  load_player_relationship,
)


class RelationshipEventModelTests(SimpleTestCase):
  def test_task_assistance_event_for_completed_player_request(self):
    state = {}
    memory = append_player_relationship_memory(
      state,
      "Lysa Vale",
      {
        "goal": "Investigate market conditions",
        "source": "player_request",
        "status": "completed",
        "source_memory_id": "request_Lysa_market_001",
      },
      {
        "action": "investigate market conditions",
        "source_memory_id": "request_Lysa_market_001",
        "completed_world_day": 1,
        "completed_world_time": "10:00",
      },
    )

    relationship = load_player_relationship(state, "Lysa Vale")

    self.assertIsNotNone(memory)
    self.assertEqual(memory["relationship_event"], "task_assistance")
    self.assertEqual(memory["impact"], 0.05)
    self.assertEqual(relationship["relationship_events"][0]["event_type"], "task_assistance")
    self.assertEqual(relationship["relationship_state"], "neutral")

  def test_gratitude_event_for_player_thanks(self):
    state = {}
    memory = append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Thank you, you really helped me.",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "positive_dialogue",
        "reason": "Player expressed appreciation",
        "confidence": 0.8,
      },
    )

    relationship = load_player_relationship(state, "Lysa Vale")

    self.assertIsNotNone(memory)
    self.assertEqual(memory["relationship_event"], "gratitude")
    self.assertEqual(memory["strength"], "small")
    self.assertEqual(memory["impact"], 0.03)
    self.assertEqual(relationship["relationship_events"][0]["event_type"], "gratitude")
    self.assertEqual(relationship["relationship_events"][0]["strength"], "small")

  def test_task_assistance_and_gratitude_create_friendly_state(self):
    state = {}
    append_player_relationship_memory(
      state,
      "Lysa Vale",
      {
        "goal": "Investigate market conditions",
        "source": "player_request",
        "status": "completed",
        "source_memory_id": "request_Lysa_market_friendly",
      },
      {
        "action": "investigate market conditions",
        "source_memory_id": "request_Lysa_market_friendly",
        "completed_world_day": 1,
        "completed_world_time": "10:00",
      },
    )
    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Thank you, you really helped me.",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "positive_dialogue",
        "reason": "Player expressed appreciation",
        "confidence": 0.8,
        "impact_strength": "medium",
      },
    )

    relationship = load_player_relationship(state, "Lysa Vale")

    self.assertEqual(relationship["relationship_state"], "friendly")
    self.assertNotEqual(relationship["relationship_state"], "helpful")

  def test_multiple_positive_events_progress_neutral_friendly_trusted(self):
    state = {}
    append_player_relationship_memory(
      state,
      "Lysa Vale",
      {
        "goal": "Investigate market conditions",
        "source": "player_request",
        "status": "completed",
        "source_memory_id": "request_Lysa_market_progression",
      },
      {
        "action": "investigate market conditions",
        "source_memory_id": "request_Lysa_market_progression",
        "completed_world_day": 1,
        "completed_world_time": "10:00",
      },
    )
    relationship = load_player_relationship(state, "Lysa Vale")
    self.assertEqual(relationship["relationship_state"], "neutral")

    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Thank you, you really helped me.",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "positive_dialogue",
        "reason": "Player expressed appreciation",
        "confidence": 0.8,
      },
    )
    relationship = load_player_relationship(state, "Lysa Vale")
    self.assertEqual(relationship["relationship_state"], "friendly")

    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Can we work together again?",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "collaboration",
        "reason": "Player proposed repeated cooperation",
        "confidence": 0.8,
      },
    )
    relationship = load_player_relationship(state, "Lysa Vale")
    self.assertEqual(relationship["relationship_state"], "trusted")

  def test_repeated_positive_interactions_add_trust_building_event(self):
    state = {}
    append_player_relationship_memory(
      state,
      "Lysa Vale",
      {
        "goal": "Investigate market conditions",
        "source": "player_request",
        "status": "completed",
        "source_memory_id": "request_Lysa_market_002",
      },
      {
        "action": "investigate market conditions",
        "source_memory_id": "request_Lysa_market_002",
        "completed_world_day": 1,
        "completed_world_time": "10:00",
      },
    )
    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Thank you, you really helped me.",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "positive_dialogue",
        "reason": "Player expressed appreciation",
        "confidence": 0.8,
      },
    )
    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "Can we work together again?",
      {
        "relationship_impact": "positive",
        "relationship_change": "increase",
        "memory_type": "collaboration",
        "reason": "Player proposed repeated cooperation",
        "confidence": 0.8,
      },
    )

    relationship = load_player_relationship(state, "Lysa Vale")
    event_types = [event["event_type"] for event in relationship["relationship_events"]]

    self.assertIn("trust_building", event_types)
    self.assertEqual(relationship["relationship_state"], "trusted")

  def test_multiple_negative_feedback_events_create_distrustful_state(self):
    state = {}
    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "I don't trust your decision.",
      {
        "relationship_impact": "negative",
        "relationship_change": "decrease",
        "memory_type": "negative_dialogue",
        "reason": "Player expressed distrust",
        "confidence": 0.8,
      },
    )
    relationship = load_player_relationship(state, "Lysa Vale")
    self.assertEqual(relationship["relationship_state"], "neutral")

    append_dialogue_relationship_memory(
      state,
      "Lysa Vale",
      "You failed me again.",
      {
        "relationship_impact": "negative",
        "relationship_change": "decrease",
        "memory_type": "negative_dialogue",
        "reason": "Player expressed repeated negative feedback",
        "confidence": 0.8,
      },
    )
    relationship = load_player_relationship(state, "Lysa Vale")
    event_types = [event["event_type"] for event in relationship["relationship_events"]]

    self.assertIn("negative_feedback", event_types)
    self.assertEqual(relationship["relationship_state"], "distrustful")


class MemoryImportanceTests(SimpleTestCase):
  def test_small_talk_memory_has_low_importance(self):
    score = assign_memory_importance(
      {
        "type": "conversation",
        "source": "live_dialogue",
        "content": "Hi, how are you?",
      }
    )

    self.assertLessEqual(score, 0.3)

  def test_task_assistance_memory_has_medium_or_higher_importance(self):
    score = assign_memory_importance(
      {
        "type": "relationship",
        "relationship_event": "task_assistance",
        "content": "Lysa Vale helped the player investigate market conditions.",
      }
    )

    self.assertGreaterEqual(score, 0.5)
    self.assertLessEqual(score, 0.6)

  def test_gratitude_and_trust_memory_has_high_importance(self):
    score = assign_memory_importance(
      {
        "type": "conversation",
        "source": "live_dialogue",
        "content": "Thank you, I really trust you.",
      }
    )

    self.assertGreaterEqual(score, 0.8)

  def test_negative_feedback_memory_has_high_importance(self):
    score = assign_memory_importance(
      {
        "type": "relationship",
        "relationship_event": "negative_feedback",
        "content": "Player expressed distrust toward Lysa Vale.",
      }
    )

    self.assertGreaterEqual(score, 0.8)

  def test_daily_routine_memory_has_low_importance(self):
    score = assign_memory_importance(
      {
        "type": "observation",
        "action": "daily_routine",
        "content": "Lysa Vale followed her daily routine at the market.",
      }
    )

    self.assertLessEqual(score, 0.3)

  def test_retrieval_can_prioritise_older_high_importance_memory(self):
    memories = [
      {
        "id": "older_high",
        "type": "relationship",
        "source": "live_dialogue",
        "content": "Player gave negative feedback about market trust.",
        "relationship_event": "negative_feedback",
        "importance_score": 0.9,
      },
      {
        "id": "recent_low",
        "type": "observation",
        "source": "action_feedback",
        "content": "Lysa made small talk about market trust.",
        "action": "small_talk",
        "importance_score": 0.2,
      },
    ]

    with patch("translator.npc_memory.load_npc_memory", return_value=memories):
      results = retrieve_relevant_memories("Lysa Vale", "market trust", max_results=2)

    self.assertEqual(results[0]["id"], "older_high")
