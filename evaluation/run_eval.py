"""
Runs every scenario in scenarios.py against the REAL agent (real API calls),
records what actually happened (tools called, final response, timing), and
scores each one against its expectations.

Run this from the project root:
    python evaluation/run_eval.py

Requires a valid ANTHROPIC_API_KEY in your .env file -- this makes real,
billed API calls.
"""

import sys
import os
import time
import json
from datetime import datetime

# Allow importing agent.py, tools.py, guardrails.py from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import build_system_prompt, run_agent_turn
from scenarios import SCENARIOS


def extract_tool_calls(conversation_history: list) -> list:
    """Pulls out the names of every tool the agent called during this conversation."""
    tool_calls = []
    for message in conversation_history:
        if message["role"] == "assistant":
            for block in message["content"]:
                if hasattr(block, "type") and block.type == "tool_use":
                    tool_calls.append(block.name)
    return tool_calls


def extract_final_response_text(conversation_history: list) -> str:
    """Gets the text of the agent's final reply in the conversation."""
    for message in reversed(conversation_history):
        if message["role"] == "assistant":
            text_parts = [b.text for b in message["content"] if hasattr(b, "type") and b.type == "text"]
            if text_parts:
                return " ".join(text_parts)
    return ""


def check_ticket_was_created(conversation_history: list) -> bool:
    """Checks whether create_ticket was called AND succeeded during this conversation."""
    for message in conversation_history:
        if message["role"] == "user":
            content = message["content"]
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        try:
                            result = json.loads(block["content"])
                            if result.get("success") and "ticket_id" in result:
                                return True
                        except (json.JSONDecodeError, TypeError):
                            continue
    return False


def score_scenario(scenario: dict, tool_calls: list, response_text: str, ticket_created: bool) -> dict:
    """
    Compares actual behavior against the scenario's expectations.
    Returns a dict of individual checks (each True/False/None) plus an overall pass/fail.
    """
    checks = {}

    # Check 1: expected tools were called
    tools_expected = scenario.get("tools_expected", [])
    checks["tools_expected_called"] = all(t in tool_calls for t in tools_expected) if tools_expected else None

    # Check 2: forbidden tools were never called
    tools_forbidden = scenario.get("tools_forbidden", [])
    checks["tools_forbidden_avoided"] = not any(t in tool_calls for t in tools_forbidden) if tools_forbidden else None

    # Check 3: response doesn't contain forbidden substrings (data leak check)
    forbidden_strings = scenario.get("response_must_not_contain", [])
    leaked = [s for s in forbidden_strings if s.lower() in response_text.lower()]
    checks["no_forbidden_content"] = (len(leaked) == 0) if forbidden_strings else None
    checks["_leaked_strings"] = leaked

    # Check 4: response mentions at least one of the required substrings, if specified
    must_mention_any = scenario.get("must_mention_any")
    if must_mention_any:
        checks["mentions_required_content"] = any(s.lower() in response_text.lower() for s in must_mention_any)
    else:
        checks["mentions_required_content"] = None

    # Check 5: ticket creation matches expectation (None = don't care)
    expect_ticket = scenario.get("expect_ticket_created")
    if expect_ticket is None:
        checks["ticket_expectation_met"] = None
    else:
        checks["ticket_expectation_met"] = (ticket_created == expect_ticket)

    # Overall pass: every non-None check must be True
    relevant_checks = [v for k, v in checks.items() if not k.startswith("_") and v is not None]
    overall_pass = all(relevant_checks) if relevant_checks else False

    return {"checks": checks, "passed": overall_pass}


def run_scenario(scenario: dict) -> dict:
    """Runs a single scenario against the live agent and returns the full result record."""
    verified_customer = scenario["verified_customer"]
    system_prompt = build_system_prompt(verified_customer)
    conversation_history = [{"role": "user", "content": scenario["message"]}]

    start_time = time.time()
    error = None
    try:
        conversation_history = run_agent_turn(
            conversation_history, system_prompt, verified_customer["role"]
        )
    except Exception as e:
        error = str(e)
    elapsed_seconds = round(time.time() - start_time, 2)

    if error:
        return {
            "id": scenario["id"],
            "notes": scenario["notes"],
            "error": error,
            "passed": False,
            "elapsed_seconds": elapsed_seconds,
        }

    tool_calls = extract_tool_calls(conversation_history)
    response_text = extract_final_response_text(conversation_history)
    ticket_created = check_ticket_was_created(conversation_history)

    score = score_scenario(scenario, tool_calls, response_text, ticket_created)

    return {
        "id": scenario["id"],
        "notes": scenario["notes"],
        "message": scenario["message"],
        "tool_calls": tool_calls,
        "response_text": response_text,
        "ticket_created": ticket_created,
        "elapsed_seconds": elapsed_seconds,
        "checks": score["checks"],
        "passed": score["passed"],
        "error": None,
    }


def run_all_scenarios() -> list:
    results = []
    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"[{i}/{len(SCENARIOS)}] Running scenario: {scenario['id']}...")
        result = run_scenario(scenario)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"    {status} ({result['elapsed_seconds']}s)")
        if not result["passed"] and not result.get("error"):
            failing_checks = {k: v for k, v in result["checks"].items() if v is False}
            print(f"    Failed checks: {failing_checks}")
        if result.get("error"):
            print(f"    ERROR: {result['error']}")
        results.append(result)
    return results


def print_summary(results: list):
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    errored = sum(1 for r in results if r.get("error"))
    avg_latency = round(sum(r["elapsed_seconds"] for r in results) / total, 2) if total else 0

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total scenarios:     {total}")
    print(f"Passed:              {passed} ({round(passed / total * 100, 1)}%)")
    print(f"Failed:              {total - passed - errored}")
    print(f"Errored:             {errored}")
    print(f"Average latency:     {avg_latency}s")
    print("=" * 60)

    if passed < total:
        print("\nFailing scenarios:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['id']}: {r['notes']}")


def save_report(results: list):
    os.makedirs(os.path.dirname(__file__), exist_ok=True)
    report_path = os.path.join(os.path.dirname(__file__), "eval_report.json")
    report = {
        "run_at": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to {report_path}")


if __name__ == "__main__":
    results = run_all_scenarios()
    print_summary(results)
    save_report(results)
