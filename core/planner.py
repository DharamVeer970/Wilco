"""Planning and reasoning layer for Wilco - breaks complex requests into steps and validates outcomes."""
import re
from typing import List, Optional

from core import agent
from core.brain import llm, chat_model


PLANNING_PROMPT = """You are planning the steps to accomplish this user request. Break it down into clear, sequential steps.
User request: {query}
Format your plan as a numbered list. Keep it concise but complete."""

REFLECTION_PROMPT = """Evaluate whether the user's request was fully satisfied.
Original request: {query}
Steps taken: {steps}
Results: {results}
Did this accomplish what the user wanted? What's missing?"""

BACKTRACK_PROMPT = """The last action failed. Suggest an alternative approach.
Original request: {query}
Failed step: {step}
Error: {error}
What else could be attempted?"""


class Plan:
    """Represents a multi-step plan for accomplishing a task."""

    def __init__(self, steps: List[str], query: str):
        self.steps = steps
        self.query = query
        self.current_step = 0
        self.results = []
        self.failed_steps = []

    def next_step(self) -> Optional[str]:
        if self.current_step < len(self.steps):
            step = self.steps[self.current_step]
            self.current_step += 1
            return step
        return None

    def record_result(self, step: str, result: str, success: bool):
        self.results.append({"step": step, "result": result, "success": success})
        if not success:
            self.failed_steps.append(step)

    def is_complete(self) -> bool:
        return self.current_step >= len(self.steps)

    def has_failures(self) -> bool:
        return len(self.failed_steps) > 0


def create_plan(query: str) -> Plan:
    """Analyze a query and create a step-by-step plan if needed."""
    try:
        prompt = PLANNING_PROMPT.format(query=query)
        response = llm.chat.completions.create(
            model=chat_model, messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.1,
        ).choices[0].message.content

        steps = []
        for line in response.splitlines():
            line = line.strip()
            match = re.match(r'^\d+\.\s+(.+)', line)
            if match:
                steps.append(match.group(1).strip())

        if not steps:
            steps = [response.strip()]

        return Plan(steps, query)
    except Exception:
        return Plan([query], query)


def reflect_on_outcome(query: str, plan: Plan) -> str:
    """Evaluate whether the executed plan achieved the user's goal."""
    try:
        steps_text = "\n".join(f"{i+1}. {r['step']}" for i, r in enumerate(plan.results))
        results_text = "\n".join(f"{i+1}. {'✓' if r['success'] else '✗'} {r['result'][:200]}" for i, r in enumerate(plan.results))

        prompt = REFLECTION_PROMPT.format(query=query, steps=steps_text, results=results_text)
        return llm.chat.completions.create(
            model=chat_model, messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.1,
        ).choices[0].message.content.strip()
    except Exception as e:
        return f"Could not reflect: {e}"


def suggest_alternative(query: str, failed_step: str, error: str, context: str) -> str:
    """Suggest an alternative approach when a step fails."""
    try:
        prompt = BACKTRACK_PROMPT.format(query=query, step=failed_step, error=error, context=context)
        return llm.chat.completions.create(
            model=chat_model, messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.2,
        ).choices[0].message.content.strip()
    except Exception as e:
        return f"Could not suggest alternative: {e}"


def enhanced_respond(query: str, already_done=()):
    """Enhanced version of agent.respond() with planning and reflection.

    Optimization: previously called create_plan() for every >5-word query and
    discarded the result — one wasted LLM call (500 tokens) per turn.
    Now delegates straight to agent.respond; planning is done inside the
    Agentic Loop only when verification fails.
    """
    agent.respond(query, already_done)
