# Bridge API contract (v0)

Source of truth: `backend/app/schemas/runs.py` (also visible at `/docs`).
Mock data for the UI: `docs/fixtures/run-running.json`, `docs/fixtures/run-completed.json`.

Base path: `/api/v1`. Errors use the existing shape `{"detail": {"code": "...", "message": "..."}}`.
Money is a decimal **string** (`"642.18"`). Timestamps are ISO 8601 UTC.

| Method | Path | Purpose |
|---|---|---|
| GET | `/inputs` | Pinned demo inputs the user can pick |
| POST | `/runs` | Start a run. Returns `202 {id, status: "queued"}` |
| GET | `/runs/{id}` | Current state of a run. The UI polls this |

## Flow

1. `GET /inputs` returns `[{id, label, description}]`, e.g. `day-2026-09-23`, `month-end-2026-09`.
2. `POST /runs` with `{"input_id": "day-2026-09-23"}`. Unknown id gives `404 {code: "unknown_input"}`.
3. Poll `GET /runs/{id}` about once a second until `status` is `completed` or `failed`. Unknown run gives `404 {code: "run_not_found"}`.

## Run

- `status`: `queued | running | completed | failed`
- `steps[]`: `{id, agent, label, model_tier, status, started_at, finished_at, output_summary, error}`
  - `status`: `pending | running | completed | failed`; `model_tier`: `nano | super | ultra`
  - Steps are listed in display order. Parallel agents appear as sibling steps that are both `running`.
  - **The UI must render `steps` generically** (agent names are not fixed yet) and must not hardcode ids.
- `result` is `null` until `completed`, then `{summary, findings[], proposed_entries[]}`.
- `error` is set when `status` is `failed`; a failed step also carries its own `error`.

### Finding

`{id, kind, severity: low|medium|high, needs_human, title, reasoning, confidence 0..1, proposed_action, evidence[]}`

`evidence[]` items are `{type: bank_transaction|bill|card_transaction|receipt, id}` using the ids in the synthetic data (`B-0023`, `BT-0027`, `CT-0052`).
`needs_human: true` goes to the exception queue.

### ProposedEntry

`{id, debit_account, credit_account, amount, memo, confidence, auto_post, evidence[]}`

## Changing this contract

Edit `schemas/runs.py` and the fixtures together; `tests/test_run_contract.py` fails if they drift. Tell the UI owner before renaming a field.
