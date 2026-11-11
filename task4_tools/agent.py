"""Native function-calling agent for the tinyledger Task 4 exercise."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for import_root in (HERE, REPO_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from common.llm_client import LLMClient, message_to_dict  # noqa: E402
from tools import ToolRegistry  # noqa: E402


TASK_PROMPT = "Make all tests pass and fix the problem described in ISSUE.md. Do not modify tests."
MAX_STEPS = 40
MAX_TOOL_CALLS = 80
MAX_TOKEN_BUDGET = 100_000


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _log_trace(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def run(*, mock: bool = False, workspace: Path | None = None, trace: Path | None = None) -> int:
    workspace = (workspace or HERE / "workspace").resolve()
    trace_path = trace or HERE / "logs" / "trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")

    registry = ToolRegistry(workspace=workspace)
    openai_client = None
    if mock:
        from mock_model import MockOpenAIClient

        openai_client = MockOpenAIClient()
    llm = LLMClient(
        model="mock" if mock else None,
        log_path=HERE / "logs" / ("mock_llm.jsonl" if mock else "llm.jsonl"),
        openai_client=openai_client,
    )
    # Keep pytest and Python caches out of the generated workspace and pass only
    # non-secret settings required for deterministic subprocess behavior.
    messages = [{"role": "user", "content": TASK_PROMPT}]
    total_calls = 0
    answer = "Agent stopped because the step or token budget was exhausted."

    for _step in range(MAX_STEPS):
        try:
            message = llm.chat_with_tools(messages, tools=registry.schemas())
        except Exception as exc:
            answer = f"Model request failed ({type(exc).__name__})."
            break
        messages.append(message_to_dict(message))
        calls = _field(message, "tool_calls") or []
        if not calls:
            answer = _field(message, "content", "") or ""
            break

        for call in calls:
            if total_calls >= MAX_TOOL_CALLS:
                answer = "Agent stopped because the tool-call budget was exhausted."
                break
            total_calls += 1
            function = _field(call, "function", {})
            name = _field(function, "name", "")
            arguments = _field(function, "arguments", "")
            call_id = _field(call, "id", f"call_{total_calls}")
            started = time.perf_counter()
            result = registry.execute(name, arguments)
            duration = round(time.perf_counter() - started, 6)
            trace_entry = {
                "name": name,
                "arguments": arguments,
                "ok": result.ok,
                "error": result.error,
                "truncated": result.truncated,
                "duration": duration,
                "tool_call_id": call_id,
            }
            _log_trace(trace_path, trace_entry)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": result.to_content()})
        else:
            if llm.total_prompt_tokens + llm.total_completion_tokens >= MAX_TOKEN_BUDGET:
                answer = "Agent stopped because the token budget was exhausted."
                break
            continue
        break

    print(answer)
    print(f"Tool calls: {total_calls}")
    print(f"LLM usage: {llm.usage_summary()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Task 4 tinyledger tool-calling agent.")
    parser.add_argument("--mock", action="store_true", help="Use the scripted MockOpenAIClient.")
    args = parser.parse_args()
    try:
        return run(mock=args.mock)
    except Exception as exc:
        print(f"Agent failed ({type(exc).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
