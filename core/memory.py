"""Persistent memory for Wilco - conversation history, preferences, and learned patterns.

This module provides long-term memory across sessions, so Wilco remembers user preferences,
conversation context, and successful tool chains. Nothing here is critical for operation -
if the memory file is deleted, Wilco starts fresh but still works.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from config import MAX_MESSAGES

MEMORY_FILE = Path.home() / ".wilco" / "memory.json"
PREFERENCE_DEFAULTS = {
    "voice": "ava",
    "speed": 25,
    "pause": 2.5,
}


def _load():
    """Load memory from disk, or return a fresh structure if missing/corrupt."""
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        # Validate structure
        if not isinstance(data, dict):
            return _fresh()
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _fresh()


def _fresh():
    return {
        "preferences": PREFERENCE_DEFAULTS.copy(),
        "conversations": [],
        "tool_stats": {},
        "learned_patterns": [],
        "last_pruned": None,
    }


def _save(data):
    """Persist memory to disk, creating the directory if needed."""
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass  # Don't crash the assistant over a write failure


def get_preference(key, default=None):
    """Get a user preference, falling back to default if not set."""
    data = _load()
    return data["preferences"].get(key, default if default is not None else PREFERENCE_DEFAULTS.get(key))


def set_preference(key, value):
    """Set a user preference persistently."""
    data = _load()
    data["preferences"][key] = value
    _save(data)


def add_conversation_turn(user_utterance, assistant_response, tools_used=None):
    """Record one turn of conversation for future reference.
    
    Keeps only the last MAX_MESSAGES turns to avoid unbounded growth.
    """
    data = _load()
    turn = {
        "timestamp": datetime.now().isoformat(),
        "user": user_utterance,
        "assistant": assistant_response,
        "tools": tools_used or [],
    }
    data["conversations"].append(turn)
    # Keep only recent turns
    data["conversations"] = data["conversations"][-MAX_MESSAGES:]
    _save(data)


def get_recent_conversations(limit=None):
    """Get recent conversation turns for context."""
    data = _load()
    conversations = data["conversations"]
    if limit:
        conversations = conversations[-limit:]
    return conversations


def record_tool_usage(tool_name, success, duration=None):
    """Track tool execution for analytics and learning."""
    data = _load()
    stats = data["tool_stats"].get(tool_name, {"calls": 0, "successes": 0, "failures": 0, "total_duration": 0})
    stats["calls"] += 1
    if success:
        stats["successes"] += 1
    else:
        stats["failures"] += 1
    if duration is not None:
        stats["total_duration"] += duration
    data["tool_stats"][tool_name] = stats
    _save(data)


def get_tool_stats():
    """Get statistics about tool usage."""
    data = _load()
    return data["tool_stats"]


def learn_pattern(query_pattern, tool_chain, success=True):
    """Learn that a certain query pattern leads to a successful tool chain.
    
    This enables Wilco to suggest or auto-suggest tool chains for similar queries.
    """
    data = _load()
    pattern = {
        "query_pattern": query_pattern,
        "tool_chain": tool_chain,
        "success": success,
        "learned_at": datetime.now().isoformat(),
    }
    data["learned_patterns"].append(pattern)
    # Keep only recent patterns
    data["learned_patterns"] = data["learned_patterns"][-50:]
    _save(data)


def find_similar_patterns(query, threshold=0.7):
    """Find learned patterns similar to the given query using fuzzy matching."""
    from rapidfuzz import fuzz
    
    data = _load()
    matches = []
    for pattern in data["learned_patterns"]:
        score = fuzz.ratio(query.lower(), pattern["query_pattern"].lower())
        if score >= threshold * 100:
            matches.append((score, pattern))
    matches.sort(reverse=True)
    return matches


def clear_memory():
    """Reset all memory to fresh state."""
    data = _fresh()
    _save(data)


def prune_old_data(days=30):
    """Remove data older than the specified number of days."""
    data = _load()
    cutoff = datetime.now() - timedelta(days=days)
    
    # Prune conversations
    data["conversations"] = [
        conv for conv in data["conversations"]
        if datetime.fromisoformat(conv["timestamp"]) > cutoff
    ]
    
    # Prune learned patterns
    data["learned_patterns"] = [
        pattern for pattern in data["learned_patterns"]
        if datetime.fromisoformat(pattern["learned_at"]) > cutoff
    ]
    
    data["last_pruned"] = datetime.now().isoformat()
    _save(data)