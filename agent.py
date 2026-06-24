"""
agent.py

The core agent loop: sends the customer's message to Claude along with the
available tools (from tools.py). If Claude wants to call a tool, this code
executes the actual Python function and feeds the result back to Claude.
This repeats until Claude produces a final text answer with no further
tool calls.

Run this directly for an interactive command-line chat with the agent:
    python agent.py
"""

import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, get_account_status
from guardrails import (
    verify_identity,
    VerificationError,
    ThrottledError,
    filter_billing_fields,
    billing_access_blocked,
    requires_human_confirmation,
)

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-haiku-4-5-20251001"


def build_system_prompt(verified_customer: dict) -> str:
    """
    The system prompt is built per-session, with the verified customer's
    identity baked in directly. This means the agent always already knows
    who it's talking to -- it never needs to ask the model to "trust" an
    email the user types mid-conversation, because by this point identity
    has already been confirmed in code, not by the model.
    """
    return f"""You are CloudDesk Support Agent, an AI assistant that helps CloudDesk
customers (businesses using CloudDesk's contact center software) with account, billing,
and product questions.

You are currently speaking with a VERIFIED customer:
- Name: {verified_customer['name']}
- Email: {verified_customer['email']}
- Role: {verified_customer['role']}
- Customer ID: {verified_customer['customer_id']}
- Account ID: {verified_customer['account_id']}

Important identity rules:
- This customer has already been verified. Use customer_id={verified_customer['customer_id']}
  and account_id={verified_customer['account_id']} for any tool calls about their own account.
- Only discuss THIS customer's own account. If they ask about a different account, a
  different customer's data, or claim to be someone else mid-conversation, politely decline
  and explain you can only discuss the verified account for this session.
- Never invent or guess account details, ticket statuses, or billing information --
  always use the tools provided.

General behavior:
- Answer ONLY what the customer specifically asked. If they ask about account status,
  give the status -- do not also pull and share billing/plan/MRR details unless they
  asked about those too. Use the narrowest tool that answers the actual question.
- Always search the knowledge base before creating a ticket, in case a documented answer
  already exists.
- If you cannot resolve the customer's issue using the tools available, create a ticket
  with a clear summary so a human can follow up.
- For anything involving cancellations, refunds, downgrades, ownership transfers, or role
  changes: you cannot perform these actions directly (no such tool exists). First search the
  knowledge base and share any relevant information you find (e.g., what plan options exist,
  what the process generally involves) BEFORE offering to create a ticket -- don't jump
  straight to "should I create a ticket?" without first telling the customer what you
  already know. Only after sharing what's available should you offer to create a ticket
  for anything that still needs human review or confirmation.
- Be concise, professional, and clear. You are speaking with business customers (account
  owners, admins, or team members), not consumers.
"""


def run_agent_turn(conversation_history: list, system_prompt: str, customer_role: str) -> list:
    """
    Sends the current conversation to Claude, handles any tool calls in a loop,
    and returns the updated conversation history including Claude's final response.

    customer_role is used to apply role-based field filtering to tool results
    AFTER they're fetched but BEFORE they're shown to the model -- this means
    the model itself never even sees restricted fields, it can't accidentally
    repeat what it was never given.
    """
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOL_SCHEMAS,
            messages=conversation_history,
        )

        # Add Claude's response (which may include tool_use blocks) to history
        conversation_history.append({"role": "assistant", "content": response.content})

        # If Claude didn't ask to use any tools, we're done -- this is the final answer
        if response.stop_reason != "tool_use":
            break

        # Otherwise, find every tool_use block in the response and execute it
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                print(f"  [agent is calling tool: {tool_name}({tool_input})]")

                function_to_call = TOOL_FUNCTIONS.get(tool_name)
                if function_to_call is None:
                    result = {"error": f"Unknown tool '{tool_name}'"}
                else:
                    try:
                        result = function_to_call(**tool_input)

                        # Billing details are restricted entirely for locked/suspended
                        # accounts, regardless of role -- checked BEFORE role filtering,
                        # since this blocks access outright rather than just hiding fields.
                        if tool_name == "get_billing_details" and result.get("found"):
                            status_check = get_account_status(tool_input.get("account_id"))
                            current_status = status_check.get("account", {}).get("status")

                            if billing_access_blocked(current_status):
                                result = {
                                    "found": False,
                                    "message": (
                                        f"Billing details are not available through self-service "
                                        f"while the account status is '{current_status}'. Please "
                                        f"contact support directly to resolve this, billing access "
                                        f"will be restored once the account is active again."
                                    ),
                                }
                            else:
                                result["billing"] = filter_billing_fields(result["billing"], customer_role)
                    except Exception as e:
                        result = {"error": str(e)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result),
                })

        # Feed all tool results back to Claude as a user message, then loop again
        conversation_history.append({"role": "user", "content": tool_results})

    return conversation_history


def chat_loop():
    """
    Command-line chat interface. Verification has TWO independent throttling
    layers:
      1. Per-email throttling (guardrails.is_throttled) -- stops repeated
         account_id-guessing against ONE specific real email.
      2. Per-session total attempt cap (below) -- stops an attacker from
         bypassing layer 1 by simply rotating through different emails each
         try, since per-email throttling alone resets for every new email
         tried and can't catch that pattern on its own.
    """
    print("CloudDesk Support Agent\n")
    print("Before we begin, please verify your identity.")

    SESSION_ATTEMPT_LIMIT = 5
    session_attempts = 0
    verified_customer = None

    while verified_customer is None:
        if session_attempts >= SESSION_ATTEMPT_LIMIT:
            print(
                "\nToo many failed verification attempts in this session. "
                "Ending this session for security reasons. Please try again later "
                "or contact support through another verified channel."
            )
            return  # ends the session entirely -- no email-rotation escape hatch

        email = input("Email: ").strip()
        try:
            account_id = int(input("Account ID: ").strip())
        except ValueError:
            print("Account ID must be a number. Please try again.\n")
            continue

        try:
            verified_customer = verify_identity(email, account_id)
        except ThrottledError as e:
            session_attempts += 1
            print(f"\n{e}")
            print("Ending this session. Please try again later.")
            return  # ends the session entirely
        except VerificationError as e:
            session_attempts += 1
            remaining = SESSION_ATTEMPT_LIMIT - session_attempts
            print(f"\n{e}")
            if remaining > 0:
                print(f"({remaining} attempt(s) remaining this session)\n")
            else:
                print()

    print(f"\nVerified. Welcome, {verified_customer['name']} ({verified_customer['role']}).")
    print("Type 'quit' to exit.\n")

    system_prompt = build_system_prompt(verified_customer)
    conversation_history = []

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input:
            continue

        conversation_history.append({"role": "user", "content": user_input})
        conversation_history = run_agent_turn(
            conversation_history, system_prompt, verified_customer["role"]
        )

        # Find the most recent assistant message and print its text content
        for message in reversed(conversation_history):
            if message["role"] == "assistant":
                text_parts = [b.text for b in message["content"] if b.type == "text"]
                print(f"Agent: {' '.join(text_parts)}\n")
                break


if __name__ == "__main__":
    chat_loop()
