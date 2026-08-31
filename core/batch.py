"""Performance & task-tracking helpers: parallel tool execution and sub-goal tracking.

  - run_parallel : run several independent tool calls concurrently with a thread pool,
    instead of one at a time. Independent calls are a common shape in a single turn
    ("what's the weather and the price"), so this multiplies throughput roughly by the
    core count. Limp along sequentially if threads are unavailable.

  - SubGoalTracker : minimal progress bookkeeping for a multi-step task — which steps are
    planned, which have started/completed/failed, and a one-line progress summary. This is
    the "sub-goal tracking with progress monitoring" piece.

Keep this dependency-free and safe: no import of the LLM, no side effects at import.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# --- parallel tool execution ----------------------------------------------------------
def run_parallel(calls, workers=None):
    """Run a list of zero-arg callables concurrently and return their results in order.

    Args:
        calls: list of (label, callable) pairs.
        workers: thread pool size (default: min(len, 4)).

    Returns:
        list of (label, result_text) in the same order as `calls`. Each callable should
        never raise (wrap it if it can't promise that) — this helper returns error strings
        for any that do, mirroring mcp_tool.call()'s contract.

    Optimization: fixed fallback bug where sequential path reassigned results each
    iteration (wrong length); now correctly fills in order.
    """
    if not calls:
        return []
    n = workers or min(len(calls), 4)
    results: list = [None] * len(calls)
    try:
        with ThreadPoolExecutor(max_workers=n) as pool:
            future_map = {pool.submit(_run_safely, fn): i
                          for i, (_label, fn) in enumerate(calls)}
            for future in as_completed(future_map):
                idx = future_map[future]
                results[idx] = (future.result(),)
    except (ImportError, OSError):  # no thread support / pool unavailable
        for idx, (_label, fn) in enumerate(calls):
            results[idx] = (_run_safely(fn),)
    return [(_label, r[0]) if isinstance(r, tuple) and len(r) == 1 else (_label, "(no result)")
            for (_label, _fn), r in zip(calls, results)]


def _run_safely(fn):
    try:
        return str(fn())
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# --- sub-goal tracking ----------------------------------------------------------------
class SubGoalTracker:
    """Tracks progress through a multi-step task so Wilco can report where it is."""

    def __init__(self, title=""):
        self.title = title or "task"
        self.steps = []  # list of [description, status]
        self.started = datetime.now()
        self._running_index = None

    def add_goal(self, description):
        """Register a planned sub-goal. Returns its index."""
        self.steps.append([description, "planned"])
        return len(self.steps) - 1

    def start(self, index):
        self.steps[index][1] = "running"
        self._running_index = index

    def complete(self, index):
        self.steps[index][1] = "done"

    def fail(self, index, _error=""):
        self.steps[index][1] = "failed"

    def progress(self):
        """Return {"done": n, "total": total, "failed": m, "summary": "2/4 done"}."""
        done = sum(1 for _d, s in self.steps if s == "done")
        failed = sum(1 for _d, s in self.steps if s == "failed")
        total = len(self.steps)
        return {
            "done": done,
            "total": total,
            "failed": failed,
            "remaining": total - done - failed,
            "summary": f"{done}/{total} done" + (f", {failed} failed" if failed else ""),
        }

    def update(self, index, status):
        """Convenience: start/complete/fail by status string."""
        if status == "running":
            self.start(index)
        elif status == "done":
            self.complete(index)
        elif status == "failed":
            self.fail(index)

    def report(self):
        """A short humanable progress line for logging or speech."""
        p = self.progress()
        running = [d for d, s in self.steps if s == "running"]
        line = f"[{self.title}] {p['summary']}"
        if running:
            line += f" — now: {running[0]}"
        return line
