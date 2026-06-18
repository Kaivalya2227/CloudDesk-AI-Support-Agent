# CloudDesk AI Support Agent

An AI support agent for a fictional B2B contact-center SaaS company ("CloudDesk"),
built to demonstrate tool-calling, multi-step orchestration, guardrails, and
evaluation rigor — the core engineering patterns behind production AI agent
deployments (e.g., Zoom Virtual Agent, Five9 AI, Decagon, Sierra).

> **Status:** Work in progress. This README will be updated as each phase is completed.

## What is CloudDesk?

CloudDesk is a fictional B2B SaaS company that sells cloud contact-center software —
similar in concept to Zoom Contact Center or Five9. Its customers are businesses
(e.g., a 15-person insurance brokerage) that run their own support/sales phone
operations on top of CloudDesk's platform: call routing, IVR menus, agent desktops,
and reporting.

This project is **not** a customer-facing storefront chatbot. It's the internal
support layer CloudDesk uses to help its own paying customers when something in
their CloudDesk setup is broken, confusing, or needs a billing/account change —
the same category of work as Zoom's Applied AI Engineer team, which takes AI agents
from proof-of-concept to live production use in customer environments.

## What the agent does

1. Looks up a customer's account, role, and subscription status
2. Answers product/billing questions by searching a knowledge base
3. Checks the status of existing support tickets
4. Creates new tickets (with full context) when it can't resolve an issue
5. Requires explicit human confirmation before any destructive or account-level
   action (cancellations, refunds, plan changes) — it drafts the action, never
   executes it unilaterally
6. Refuses to fabricate information when its tools return no answer
7. Enforces role-based access (`owner` / `admin` / `member`) before allowing
   certain actions

## Why these design choices

- **Mocked data instead of real CRM/telephony integrations** — the goal is to
  demonstrate agent reasoning, tool design, and evaluation rigor, not to prove
  API access to a real CRM. A SQLite database with realistic schema and
  synthetic data stands in for "real customer data."
- **Simplified role-based access** (3 fixed roles, not a full custom-permissions
  system) — captures the realistic multi-user-account structure of real B2B SaaS
  products (Zoom, AWS, etc.) without the time cost of building a full RBAC system.
- **Text-only agent, voice stack deferred** — agent orchestration, tool use, and
  guardrails are a distinct (and more foundational) skill set from voice
  engineering (ASR/TTS/turn-taking). Building the core well first, rather than
  rushing a shallow voice demo, produces a stronger and more honestly-described
  result.

## Tech stack

- Python
- SQLite (database)
- Claude or OpenAI API (LLM with native tool-calling)
- *(planned, phase 3)* pytest for testing, GitHub Actions for CI, Docker for
  containerization

## Project structure

```
clouddesk_agent/
├── PROJECT_NOTES.md        # design reasoning and decisions log
├── README.md               # this file
├── schema.sql               # database schema (planned)
├── generate_data.py         # synthetic data generator (planned)
├── tools.py                  # agent tool definitions (planned)
├── agent.py                  # agent loop / orchestration (planned)
├── guardrails.py             # guardrail logic (planned)
├── evaluation/
│   ├── test_scenarios.json   # evaluation test set (planned)
│   └── run_eval.py           # evaluation harness (planned)
└── tests/                    # unit tests (planned, phase 3)
```

## Database schema

See `PROJECT_NOTES.md` for full schema and design rationale. Summary: `accounts`
(one per company) → `customers` (multiple per account, role-based) →
`subscriptions`, `invoices`, `tickets`; plus `knowledge_base_articles` and
`agent_logs` (the observability/evaluation backbone).

## Roadmap

- [x] Define project scope and fictional company domain
- [x] Design database schema
- [ ] Build SQLite database + synthetic data generator
- [ ] Build agent core with tool-calling
- [ ] Implement guardrails (no fabrication, confirmation-before-action, RBAC checks)
- [ ] Multi-step orchestration scenarios
- [ ] Evaluation harness with measurable metrics
- [ ] Documentation and polish
- [ ] *(future)* Voice stack: ASR, TTS, turn-taking/barge-in
- [ ] *(future)* CI/CD pipeline + Docker containerization
- [ ] *(future)* Real telephony/CRM integration (Twilio, Salesforce)

## What this project demonstrates

LLM agent design with tool use and multi-step orchestration; guardrail design for
safe, non-destructive agent behavior; database schema design for realistic B2B
multi-tenant data; structured logging and evaluation methodology for validating
agent performance against measurable targets before "go-live."