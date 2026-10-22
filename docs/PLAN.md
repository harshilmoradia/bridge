# Bridge build plan

**Build complete by end of Tue Oct 27.** Buffer Wed Oct 28 to Thu Oct 29. **Submit Thu Oct 29.** The hard deadline is Fri Oct 30.
**Track:** Best Apps and Agents.
**Team:** Harshil plus Claude Code, covering backend, agents, UI and infra. Teammates are not on the critical path.

Tasks, with acceptance criteria and status, are in [`BACKLOG.md`](BACKLOG.md). Design is in [`architecture.md`](architecture.md). The demo script and the expected numbers are in [`../evals/scenarios.md`](../evals/scenarios.md).

## What we're building

An agentic bank reconciliation for a small business. Nemotron agents on Nebius Token Factory match a bank statement to the ledger, explain every mismatch, close what policy allows, and send the rest to a human with a draft journal entry. The hero screen is a **reconciliation statement whose difference animates to 0.00** as agents and the human clear items.

## Scope

**Must** (all of these ship):
- Rule-based matcher plus Nemotron agents in tiers: Nano (guard, fuzzy match, classify), Super (resolve with tools, critic), Ultra (report, hardest retries).
- An evaluator loop: code checks plus a critic, with retries before any escalation.
- An approval queue: reason, evidence and draft entry for each item, with approve or reject. The statement reaches 0.00.
- An interactive UI: Bank and Ledger tables, a Reconcile workspace with live per-step progress, the statement card, the approval drawer and the report.
- Guardrails: PII redaction before every model call and prompt-injection flagging, both visible in the UI.
- An eval harness scored against the ground truth, with **0 false auto-resolutions**.
- Live on a Nebius Serverless Endpoint, with Inngest Cloud and Supabase.

**Should:** learning from approvals ("remember this rule" makes the next run auto-resolve), the tier comparison chart, the run trace page.

**Stretch** (only if ahead on Mon Oct 26): PDF statement upload read by Nemotron Super VL, Tavily lookup for unknown payees (there's a $3k prize), similar past resolutions via pgvector, CSV export.

**Cut order if we slip:** stretch, then the tier chart, then the learning loop, then the run trace page. Never cut the statement, approvals, guardrails or the deploy.

## Schedule

| Day | Date | Goal by end of day |
|---|---|---|
| 2 | **Thu Oct 22** | v2 data in the repo ✅. Supabase schema applied and seeded. A single container (UI + API) running locally, then on Nebius, with Inngest Cloud invoking it. UI shell with mock API. |
| 3 | **Fri Oct 23** | Rule-based matcher and statement calculator under test (raw difference 864.09). Read API v1. Eval harness v0. Bank and Ledger tables on real data. |
| 4 | **Sat Oct 24** | Guardrails. Agents: fuzzy match, classify, resolve, review, decide, report. The `reconcile-run` Inngest workflow persisting steps and items. Run endpoints. |
| 5 | **Sun Oct 25** | Decision endpoint and `item-decided`. Reconcile workspace, progress stepper, approval drawer and live statement reaching 0.00 end to end. A full eval with 0 false auto-resolutions. |
| 6 | **Mon Oct 26** | Should items: learning loop, run trace, report page, guardrail callouts, tier comparison. Full deploy, `/demo/reset`, error states, fresh-browser check. |
| 7 | **Tue Oct 27** | **Feature freeze at noon.** README, architecture diagram, video script and first take, submission checklist. |
| Buffer | Wed Oct 28 to Thu Oct 29 | Bug fixes only. Re-record the video if needed. **Submit Thu Oct 29.** |

**Daily rule:** at the end of each day the deployed URL works. If a day's goal slips, take from the next day's Should items, never from Must items.

## Submission checklist (from the hackathon rules)

- [ ] Working project on Nebius Token Factory using NVIDIA Nemotron
- [ ] Track: Best Apps and Agents
- [ ] Project description: what, why, how
- [ ] Working demo URL, checked from a fresh browser
- [ ] Public YouTube video of 3 minutes or less, showing Token Factory and Nemotron in use
- [ ] Public GitHub repo with the Apache-2.0 license visible at the top
- [ ] README with setup steps and how to run, highlighting the Nemotron models used, where Token Factory helped, and the other Nebius services used (Serverless Endpoints)
