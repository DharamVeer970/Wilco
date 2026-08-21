"""Analytics for Wilco - tracks tool usage, performance, and success rates."""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

STATS_FILE = Path.home() / ".wilco" / "analytics.json"


class ToolStats:
    """Tracks execution statistics for a single tool."""

    def __init__(self, name: str):
        self.name = name
        self.total_calls = 0
        self.successes = 0
        self.failures = 0
        self.total_duration = 0.0
        self.last_used = None
        self.recent_errors = []

    def record_call(self, success: bool, duration: float, error: str = None):
        self.total_calls += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self.total_duration += duration
        self.last_used = datetime.now()
        if error and len(self.recent_errors) < 5:
            self.recent_errors.append(error)

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_calls if self.total_calls else 0.0

    @property
    def avg_duration(self) -> float:
        return self.total_duration / self.total_calls if self.total_calls else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "total_calls": self.total_calls,
            "successes": self.successes, "failures": self.failures,
            "success_rate": self.success_rate, "avg_duration": self.avg_duration,
            "total_duration": self.total_duration,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "recent_errors": self.recent_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolStats":
        stats = cls(data["name"])
        stats.total_calls = data["total_calls"]
        stats.successes = data["successes"]
        stats.failures = data["failures"]
        stats.total_duration = data["total_duration"]
        if data.get("last_used"):
            stats.last_used = datetime.fromisoformat(data["last_used"])
        stats.recent_errors = data.get("recent_errors", [])
        return stats


class Analytics:
    """Central analytics tracker for all tool usage."""

    def __init__(self):
        self.tool_stats: Dict[str, ToolStats] = {}
        self.session_start = datetime.now()
        self._load()

    def _load(self):
        try:
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            for name, tool_data in data.get("tools", {}).items():
                self.tool_stats[name] = ToolStats.from_dict(tool_data)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self.tool_stats = {}

    def _save(self):
        try:
            data = {
                "session_start": self.session_start.isoformat(),
                "tools": {name: stats.to_dict() for name, stats in self.tool_stats.items()},
            }
            STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def record_execution(self, tool_name: str, success: bool, duration: float, error: str = None):
        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolStats(tool_name)
        self.tool_stats[tool_name].record_call(success, duration, error)
        self._save()

    def get_tool_stats(self, tool_name: str) -> Optional[ToolStats]:
        return self.tool_stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, ToolStats]:
        return self.tool_stats

    def get_most_used(self, limit: int = 10) -> List[ToolStats]:
        return sorted(self.tool_stats.values(), key=lambda s: s.total_calls, reverse=True)[:limit]

    def get_least_reliable(self, limit: int = 5) -> List[ToolStats]:
        reliable = [s for s in self.tool_stats.values() if s.total_calls >= 5]
        return sorted(reliable, key=lambda s: s.success_rate)[:limit]

    def get_slowest(self, limit: int = 5) -> List[ToolStats]:
        return sorted(self.tool_stats.values(), key=lambda s: s.avg_duration, reverse=True)[:limit]

    def get_session_summary(self) -> dict:
        total_calls = sum(s.total_calls for s in self.tool_stats.values())
        total_successes = sum(s.successes for s in self.tool_stats.values())
        total_duration = sum(s.total_duration for s in self.tool_stats.values())
        return {
            "session_duration": (datetime.now() - self.session_start).total_seconds(),
            "total_tool_calls": total_calls,
            "overall_success_rate": total_successes / total_calls if total_calls > 0 else 0,
            "avg_tool_duration": total_duration / total_calls if total_calls > 0 else 0,
            "unique_tools_used": len(self.tool_stats),
        }

    def clear(self):
        self.tool_stats = {}
        self.session_start = datetime.now()
        self._save()


analytics = Analytics()


def record_tool_call(tool_name: str, success: bool, duration: float, error: str = None):
    analytics.record_execution(tool_name, success, duration, error)


def get_analytics_summary() -> str:
    summary = analytics.get_session_summary()
    lines = [
        f"Session duration: {summary['session_duration']:.0f}s",
        f"Total tool calls: {summary['total_tool_calls']}",
        f"Overall success rate: {summary['overall_success_rate']:.1%}",
        f"Unique tools used: {summary['unique_tools_used']}",
    ]

    most_used = analytics.get_most_used(5)
    if most_used:
        lines.append("\nMost used tools:")
        for stats in most_used:
            lines.append(f"  {stats.name}: {stats.total_calls} calls ({stats.success_rate:.0%} success)")

    return "\n".join(lines)
