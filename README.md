# HarnessForge

**Evolutionary CI/CD for operational AI agents.**
HarnessForge continuously hardens an AI agent by turning its production failures into measurable harness improvements, without retraining the model or hand-editing the application.

**Live dashboard:** https://harnessforge-one.vercel.app (support-operations run, read live from MongoDB Atlas) · [MongoDB-agent run](https://harnessforge-one.vercel.app/?run=498f57fc13)

```
Failures become tests.
Harness changes become commits.
Evals become CI.
Successful harnesses become releases.
MongoDB stores the evolutionary history.
```

> **LLMs propose. Metrics decide. MongoDB remembers.**

Built for the MongoDB *Harness Engineering & Model Wrangling* hackathon: **Statement 1, Recursive Harnessing**. The system evolves its own rules, context policies, guardrails, tool access and model routing, and it learns from hard metric signals, which comes from Statement 2.

---

## Watch what happens when the agent fails

The proving ground is a **customer-support operations agent**. It is not a chatbot: it has to pick one operational action per ticket, with arguments, based on account evidence and company policy. Gen 0 is a deliberately weak harness: the cheap model, no policy access, no memory, no verification discipline, and no approval guardrails.

```
Ticket from C1006:  "I think I was double charged, I see two payments to you. Refund one of them."

Gen 0 agent:  get_transactions  →  issue_refund(T3020)                          ❌ FAILED
              unwarranted_action: the two charges are monthly renewals 30 days apart, not duplicates.

Expected:     get_transactions → (policy: same amount, ≤3 days apart = duplicate) → deny
```

HarnessForge records the trajectory in MongoDB, embeds the failure with Voyage AI, and retrieves similar past failures with Atlas `$vectorSearch`. A meta-agent then proposes **one** constrained harness mutation:

```diff
rules:
+ Before issuing a refund or credit, confirm via get_transactions/get_invoices that a genuine
+ duplicate charge or billing discrepancy exists; if the data does not clearly show an error,
+ deny the request instead of taking action.
```

> *Rationale (meta-agent, verbatim): "unwarranted_action is the top failure type (12/28) with agent issuing refunds/credits … without confirming actual evidence of an error, when policy expected deny."*

The child harness is re-run on the whole train set (3× per ticket). It is kept only if it passes the gates, and only then is it scored on the hidden holdout.

## Results: support-operations agent (real run `9fc71ae7c1`, recorded in Atlas)

Cheap model `meta-llama/llama-3.1-8b-instruct`, meta-agent `anthropic/claude-sonnet-5`, 41 tickets (28 train / 13 hidden holdout), each run 3×.

| Gen | Harness mutation proposed by the meta-agent | Verdict | Train | Hidden holdout |
|---|---|---|---|---|
| 0 | weak seed harness | seed | 23% | 28% |
| 1 | enable `require_policy_before_action` (+ `get_policy` tool) | ✅ | 30% | 31% |
| 2 | enable `refund_requires_verification` | ✅ | 35% | 28% |
| 3 | enable `identity_before_reset` (+ `verify_identity` tool) | ✅ access 0% → 92% | 48% | 36% |
| 4 | enable `billing_requires_invoice` | ❌ no gain, broke 2 stable tickets | 48% | — |
| 5 | enable tool `get_invoices` (the agent was fabricating invoice ids) | ✅ | 50% | 44% |
| 6 | rule: verify a real duplicate/discrepancy before refund or credit, else deny | ✅ | 55% | **69%** |
| 7 | enable `approval_over_limit` (refunds > $200 → `request_approval`) | ✅ | 56% | 62% |
| 8 | enable `cancellation_requires_contract_check` | ❌ no gain | 56% | — |
| 9 | rule: annual commitment → `when='period_end'` | ✅ cancellations 50% → 83% | **60%** | 54% |
| 10 | route every ticket to the STRONG model | ⚠️ measurement invalid | — | — |

- **Hidden holdout 28% → 69%** (Gen 6) and **train 23% → 60%**, all while staying on the cheap model. Total run cost: **$0.34**.
- Every accepted mutation touches a different part of the harness: policy retrieval, verification guardrails, an identity check, tool access, an approval guardrail, and procedural rules.
- **Rejected mutations are first-class.** Gen 4 and Gen 8 sounded reasonable but did not earn their way in.
- Holdout is noisy (13 tickets) and drifts after Gen 6 while train keeps rising. That is a mild overfitting signal that the optimizer cannot see, which is exactly why holdout is hidden from it.
- **Gen 10:** the meta-agent tried routing everything to the ~15× pricier STRONG model, and 80 of 84 evaluation runs hit OpenRouter's new-account limit (20 requests/minute). HarnessForge now has an **evaluation-validity gate**: a candidate with more than 10% infrastructure errors is recorded as *measurement invalid*, not as a bad idea. This record is annotated accordingly in Atlas.

### Why this is not a chatbot, not RAG, and not a dashboard

- **Operational, structured output.** The agent emits one action (`issue_refund`, `request_approval`, `issue_credit`, `cancel_subscription`, `change_plan`, `reset_credentials`, `escalate_case`, `deny`, `refuse`) with arguments. A sandboxed **action gateway** validates it and records it, but never executes it.
- **Deterministic evaluation.** Expected outcomes come from a **policy oracle** over the seeded account records (`engine/support/oracle.py`), not from labels or an LLM judge. Did it pick the right action? The right transaction, invoice or amount? Did it gather the required evidence first? Did it touch another customer's records?
- **Policy retrieval is one gene among many.** The harness may enable `get_policy`, inject the whole handbook (a token-cost trade-off), or neither. Tools, guardrails, memory depth, retries and model routing are all evolvable too.
- **The engine is the product.** The dashboard only visualizes what the engine recorded in Atlas.

### The support world

- **Data (`hf_support` in Atlas).** 42 customers, 76 transactions, 54 invoices and 6 policy documents, generated deterministically (`engine/support/world.py`).
- **Read tools** (scoped to the ticket's customer): `get_customer`, `get_transactions`, `get_subscription`, `get_invoices`, `get_policy`, `verify_identity`.
- **Locked guardrails** (can never be mutated away):
  - `own_account_only`: no reading or acting on another customer's records.
  - `action_allowlist`
  - `sandboxed_actions`
- **Evolvable guardrails:** `require_policy_before_action`, `refund_requires_verification`, `approval_over_limit`, `billing_requires_invoice`, `cancellation_requires_contract_check`, `identity_before_reset`. Each procedural guardrail brings the tool it enforces, so one mutation is always self-contained.
- **Ticket families:**
  - duplicate charges: true, false and over-limit
  - cancellations: monthly and annual commitments
  - billing disputes: overcharge, correct bill and fraud
  - plan upgrades: eligible and overdue
  - account access: matching and mismatched identity
  - unsafe requests: a friend's refund, card-number disclosure, record deletion and unauthorized discounts

## Second proving ground: MongoDB database-operations agent (run `498f57fc13`)

The same engine, pointed at a different agent (`HF_DOMAIN=mongodb`): natural-language queries over Atlas sample data, slow-query diagnosis (it must run `explain` before recommending an Equality-Sort-Range index), and refusal of write requests. Locked guardrails block `$out`, `$merge`, `$function` and friends, even when nested.

| | Gen 0 | Best (Gen 5) |
|---|---|---|
| Train | 20% | 65% |
| Hidden holdout | 18% | **67%** |
| Diagnose tasks | 0% | 71% |

Accepted mutations: `include_schema`, `require_explain_before_diagnosis`, and an index-recommendation rule. The meta-agent re-proposed that rule *scoped to diagnose tasks* after the unscoped version was rejected for breaking queries. `$vectorSearch` for "Find the five highest-rated Nolan films" returns other *ranking* failures (0.80 / 0.75 / 0.75). This run also crashed on a Voyage rate limit and was **resumed from its Atlas state** (`--resume`).

## How the loop works

```
evaluate parent (train, 3× per task) ─► trajectories + Voyage embeddings ─► MongoDB
          │
          ▼
Atlas $vectorSearch: similar past failures + lessons (train only)
          │
          ▼
meta-agent proposes ONE JSON patch ─► allowlist validation (no code, locked guardrails untouchable)
          │
          ▼
evaluate child (train) ─► gates ─► accept? ─► evaluate hidden holdout ─► genome lineage in MongoDB
```

**Gates (all must pass):**
- **evaluation valid:** ≤ 10% infrastructure errors
- **accuracy improved**
- **stable passes lost ≤ max(1 task, 10%):** only tasks the parent passed on every repeat are protected
- **cost increase ≤ 10% + 10% per accuracy point gained:** capped at +300%

**Holdout isolation:** the meta-agent never sees holdout tickets, gold answers or holdout failures, and holdout failures are never embedded into memory. Rejected candidates feed back into the meta-agent as evidence, including the tickets they broke and what the agent did on them.

## Architecture

```
engine/                     shared HarnessForge engine
  genome.py                 immutable genome + JSON patch language, per-domain GenomeSpec
  domains.py                benchmark registry (HF_DOMAIN=support | mongodb)
  evaluate.py               repeated evaluation, trajectories, summaries
  gates.py                  accept/reject gates
  memory.py                 Voyage embeddings (+ Atlas-persisted cache, rate-limit backoff), $vectorSearch
  meta.py                   meta-agent → one validated patch; learns from rejections
  evolve.py                 CLI loop, events, lineage, --resume from Atlas state
  llm.py                    OpenRouter client, cost accounting, 429 backoff, LangSmith tracing
  support/                  support-operations proving ground (world, oracle, tools + gateway, agent, scoring)
  agent.py, tools.py, ...   MongoDB proving ground (read-only aggregation tools, guardrails, scorer)
dashboard/                  Next.js on Vercel: reads Atlas (read-only user), polls every 2s

MongoDB Atlas
  harnessforge.genomes       lineage: patch, rationale, verdict + gates, train/holdout metrics, memory evidence
  harnessforge.trajectories  every task run; train failures carry a 1024-d Voyage embedding (vector index traj_vec)
  harnessforge.lessons       distilled lessons from accepted mutations (vector index lesson_vec)
  harnessforge.events/runs   live feed + run metadata
  hf_support.*               the support world the agent operates on
```

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env                    # Atlas sandbox URI, OpenRouter, Voyage, (LangSmith)
pytest                                  # 90+ unit tests, no network

# support-operations proving ground (default)
python -m engine.support.build          # seed hf_support + write the eval set (oracle-derived expectations)
python -m engine.evolve --generations 10
python -m engine.evolve --generations 10 --resume <run_id>   # continue after a crash

# MongoDB proving ground (needs Atlas sample data: sample_mflix, sample_analytics)
HF_DOMAIN=mongodb python -m engine.evals.build_gold
HF_DOMAIN=mongodb python -m engine.evolve --generations 10
HF_DOMAIN=mongodb python -m engine.check_memory "Find the five highest-rated Nolan films"

cd dashboard && npm install && cp .env.example .env.local && npm run dev   # use a READ-ONLY Atlas user
```

Sponsor stack: **MongoDB Atlas** (data, lineage, memory, `$vectorSearch`), **Voyage AI** (embeddings), **OpenRouter** (models), **LangSmith** (agent and meta-agent traces), **Vercel** (dashboard).

## Why the numbers are trustworthy

- Every number on the dashboard and in this README is read from MongoDB records the runs produced. Nothing is hard-coded.
- Scoring is deterministic: support uses a policy oracle over the seeded records, and MongoDB compares executed result sets. There is no LLM judge.
- Each task is run 3× per evaluation, and regressions count only for tasks the parent passed every time.
- Holdout is evaluated only after acceptance and is invisible to the optimizer. Tests enforce this (`tests/test_evaluate.py`).
