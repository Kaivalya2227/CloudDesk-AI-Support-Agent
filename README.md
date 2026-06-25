# CloudDesk AI Support Agent

An AI support agent for a fictional B2B contact-center SaaS company ("CloudDesk"),
built to demonstrate tool-calling, multi-step orchestration, layered guardrails, and
measurable evaluation, the core engineering patterns behind production AI agent
deployments.

> **Status:** Core agent, guardrails, and evaluation harness complete (10/10 passing
> on the current scenario set). Voice stack, CI/CD, and containerization are planned
> next phases.

## What is CloudDesk?

CloudDesk is a fictional B2B SaaS company that sells cloud contact-center software (similar in concept to Zoom Contact Center or Five9). Its customers are businesses
(e.g., a 15-person insurance brokerage) that run their own support/sales phone
operations on top of CloudDesk's platform: call routing, IVR menus, agent desktops,
and reporting.

This project is **not** a customer-facing storefront chatbot. It's the internal
support layer CloudDesk uses to help its own paying customers when something in
their CloudDesk setup is broken, confusing, or needs a billing/account change, the same category of work as any company's Applied AI Engineer team, which takes AI agents
from proof-of-concept to live production use in customer environments.

## What the agent does

1. Verifies customer identity (email + account ID) before any account-specific
   tool can be used, verification runs in code, not as a model instruction
2. Looks up account status, billing details, and invoice history with
   least-privilege scoping (only fetches what the specific question requires)
3. Answers product/billing questions by searching a knowledge base
4. Checks the status of existing support tickets without fabricating answers
   for tickets that don't exist
5. Creates new tickets, carrying forward relevant context, when it can't
   resolve an issue directly
6. Never executes destructive or account-changing actions (cancellations,
   refunds, plan changes, role changes), no such tools exist at all, so the
   agent can only draft the request for human review, never perform it
7. Enforces role-based access (`owner` / `admin` / `member`): some data is
   filtered field-by-field (e.g., MRR hidden from `member`), other data is
   blocked tool-wide (e.g., itemized invoices are owner/admin only)
8. Restricts self-service billing access entirely for locked/suspended
   accounts, regardless of role, since the lock itself is often billing-related
9. Throttles repeated failed identity-verification attempts at two independent
   layers (per-email and per-session)

## Guardrails

Manual adversarial testing surfaced several real gaps during development, each
fixed and documented. A few worth highlighting are:

- **Identity verification runs in code, not as a model instruction.** An
  instruction can be argued around by a confused or clever model; a code path
  that blocks tool access without a verified session cannot.
- **Failed-attempt throttling never locks the actual account.** Locking the
  real account after failed login attempts is a known anti-pattern, it lets
  an attacker weaponize failed guesses into denying a legitimate customer
  access. Throttling is scoped to the *attempted identifier* instead.
- **Found and fixed a throttle bypass during testing**: per-email throttling
  alone could be bypassed by simply rotating through different emails each
  attempt. Fixed with an independent per-session attempt cap.
- **Two different access-restriction styles, chosen deliberately per data
  shape**: field-level filtering where a partial view still makes sense
  (billing summary), full tool-blocking where it doesn't (itemized invoices,
  there's no meaningful way to redact just the dollar amount).
- **Destructive actions have no corresponding tool at all** this is treated
  as the strongest guardrail in the system, stronger than a prompt instruction.

## Evaluation

A scenario-based evaluation harness (`evaluation/`) runs the real agent against
10 scripted scenarios covering scope discipline, role-based restrictions,
account-status restrictions, multi-step tool chaining, duplicate-charge
detection (against a deliberately seeded test case), destructive-action
handling, and fabrication checks on non-existent tickets. Each scenario is
scored on objective, code-checkable criteria, correct tools called, forbidden
tools avoided, no sensitive data leaked into the response, required content
present, ticket-creation outcome matched, not subjective read-through.

**Current result: 10/10 scenarios passing.** The first run scored 9/10; the one
failure turned out to be a bug in the test's expected-phrase matching, not the
agent, a good example of evaluation work needing to distinguish "the system
is wrong" from "the test is wrong."

Reports are saved to `evaluation/eval_report.json` after each run.

## Tech stack

- Python 3.11
- SQLite (database)
- Anthropic Claude API (Haiku model) with native tool-calling
- Hand-written agent loop (no LangChain), so every step is explainable, not
  framework magic

## Project structure

```
clouddesk_agent/
├── PROJECT_NOTES.md            # full design reasoning, decisions, and testing history
├── README.md                   
├── create_database.py          # schema creation (SQLite)
├── generate_data.py             # synthetic accounts/customers/subscriptions
├── generate_invoices_tickets.py # synthetic invoices/tickets
├── load_kb_articles.py          # knowledge base content (hand-written)
├── seed_eval_fixtures.py        # seeds a deliberate duplicate-charge test case
├── peek_data.py                  # quick helper to browse sample data for testing
├── tools.py                      # tool implementations + schemas for the LLM
├── guardrails.py                 # verification, throttling, access-control logic
├── agent.py                      # the core tool-calling agent loop
└── evaluation/
    ├── scenarios.py               # test scenario definitions
    ├── run_eval.py                 # evaluation runner + scorer
    └── eval_report.json            # latest evaluation results
```

## Running this project

```bash
pip install anthropic python-dotenv
# create a .env file with: ANTHROPIC_API_KEY=your-key-here

python create_database.py
python generate_data.py
python generate_invoices_tickets.py
python load_kb_articles.py
python seed_eval_fixtures.py

python agent.py                 # interactive chat with the agent
python evaluation/run_eval.py   # run the full evaluation suite
```

## Database schema

Summary:
`accounts` (one per company) -> `customers` (multiple per account, role-based:
owner/admin/member) -> `subscriptions`, `invoices`, `tickets`; plus
`knowledge_base_articles`, `agent_logs`, and `verification_attempts`
(throttling support).

## Roadmap

- Define project scope and fictional company domain
- Design database schema
- Build SQLite database + synthetic data generator (200 accounts, ~2,900
      customers, invoices, tickets, KB articles)
- Build agent core with tool-calling (7 tools)
- Implement layered guardrails (verification, throttling, RBAC, status-based
      restrictions, least-privilege tool scoping)
- Multi-step orchestration scenarios (tested manually + in eval harness)
- Evaluation harness with measurable, code-checked metrics (10/10 passing)
- **Next: CI/CD pipeline** -- pytest unit tests for `tools.py`/`guardrails.py`,
      GitHub Actions running them on every push
- **Next: Docker containerization** -- reproducible one-command setup
- **Future: Voice stack** -- ASR, TTS, turn-taking/barge-in (e.g., ElevenLabs)
- **Future: Real telephony/CRM integration** (Twilio, Salesforce) in place
      of the current mocked SQLite data

## What this project demonstrates

LLM agent design with tool use and multi-step orchestration; layered guardrail
design (code-level verification, throttling, least-privilege access, role- and
status-based restrictions) for safe agent behavior around real account data
database schema design for realistic B2B multi-tenant data and a measurable,
code-checked evaluation methodology, including catching and correcting a flaw
in the evaluation itself, not just the system under test.
