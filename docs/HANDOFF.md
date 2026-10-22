# Handoff

Update this at the end of every session: what changed, decisions made, what's next. Keep it short. Older detail belongs in git history.

## State as of Thu Oct 22, 2026 (morning)

**Branch:** `feature/setup`. Nothing on it is committed yet (Day 1 work plus this setup). Doing that is X-01.

**Done:**
- Day 1: Nemotron model ids verified on Token Factory (see `.env.example`). Inngest wired in, and the local smoke test **passed** (plan, parallel agents, synthesize). API contract v0 and fixtures. 8 tests passing.
- v2 demo data generated from the team's spreadsheets: `demo-data/` (inputs) and `evals/` (answer key, scenarios, source). Expected statement: raw difference 864.09, closing to 0.00 after 5 approvals. See `evals/scenarios.md`.
- Planning docs: `PLAN.md`, `BACKLOG.md`, `architecture.md`, `CLAUDE.md`. Supabase schema in `supabase/migrations/0001_init.sql`.

**Decisions:**
- Scope is bank-to-GL reconciliation for one cash account (Northbrook Goods Co., Oct 1–10 2026). The older `bridge-data/` set (Sep, AP and cards) is unused and gitignored.
- Agents auto-close only the kinds `policy.json` allows. Everything else is escalated with a draft journal entry. Nothing posts without approval, except rounding of $1.00 or less.
- DB is Supabase Postgres. The backend alone connects, through the transaction pooler with psycopg 3. The browser never talks to Supabase.
- One container serves both UI and API. Hosted on a Nebius Serverless Endpoint, with Inngest Cloud for workflows.
- Harshil plus Claude Code build everything, UI included.
- Track: Best Apps and Agents.

**Next:** `BACKLOG.md`, Thu Oct 22: X-01, then X-02, B-01, X-03, X-04, U-01.

**Open questions:**
- Does Token Factory tool calling work for Super? (B-07)
- Which container registry will the Nebius Serverless Endpoint pull from? (X-04)

**Deployed URL:** not yet.
