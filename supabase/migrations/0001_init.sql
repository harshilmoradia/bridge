-- Bridge schema v1. Apply in the Supabase SQL editor or with:
--   psql "$DATABASE_URL_DIRECT" -f supabase/migrations/0001_init.sql
-- RLS is enabled with no policies: only the backend (direct connection / service role) can access data.

create extension if not exists pgcrypto;

-- ---------- inputs ----------
create table if not exists bank_transactions (
  dataset          text not null,
  txn_id           text not null,
  posted_date      date not null,
  description      text not null,
  amount           numeric(14,2) not null,   -- + into bank, - out of bank
  type             text not null,
  check_number     text,
  running_balance  numeric(14,2),
  primary key (dataset, txn_id)
);

create table if not exists gl_entries (
  dataset          text not null,
  entry_id         text not null,
  date             date not null,
  description      text not null,
  amount           numeric(14,2) not null,   -- same sign convention as bank
  method           text not null,
  check_number     text,
  account          text not null,
  counter_account  text not null,
  counterparty     text,
  primary key (dataset, entry_id)
);

create table if not exists balances (
  dataset               text primary key,
  company               text not null,
  cash_account          text not null,
  period_start          date not null,
  period_end            date not null,
  bank_opening_balance  numeric(14,2) not null,
  bank_closing_balance  numeric(14,2) not null,
  gl_opening_balance    numeric(14,2) not null,
  gl_closing_balance    numeric(14,2) not null
);

-- ---------- runs ----------
create table if not exists runs (
  id            uuid primary key default gen_random_uuid(),
  dataset       text not null,
  period_start  date not null,
  period_end    date not null,
  status        text not null default 'queued' check (status in ('queued','running','completed','failed')),
  counts        jsonb not null default '{}'::jsonb,
  report        text,
  error         jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists run_steps (
  run_id          uuid not null references runs(id) on delete cascade,
  step_key        text not null,
  position        int  not null,
  agent           text not null,
  label           text not null,
  model_tier      text check (model_tier in ('code','nano','super','ultra')),
  model           text,
  status          text not null default 'pending' check (status in ('pending','running','completed','failed')),
  started_at      timestamptz,
  finished_at     timestamptz,
  latency_ms      int,
  tokens_in       int,
  tokens_out      int,
  output_summary  text,
  error           jsonb,
  primary key (run_id, step_key)
);

-- ---------- reconciliation items ----------
create table if not exists items (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  kind          text not null,      -- exact | timing | check_number | one_to_many | rounding | nsf_pair | outstanding_check | deposit_in_transit | bank_fee_missing_in_gl | interest_missing_in_gl | duplicate_gl_entry | transposition | unidentified_receipt | unknown
  resolution    text not null check (resolution in ('auto_match','auto_match_with_writeoff','reconciling_item','escalate')),
  status        text not null check (status in ('matched','auto_resolved','reconciling_item','needs_approval','approved','rejected')),
  bank_ids      text[] not null default '{}',
  gl_ids        text[] not null default '{}',
  amount_delta  numeric(14,2) not null default 0,
  reasoning     text,
  evidence      jsonb not null default '[]'::jsonb,
  flags         text[] not null default '{}',   -- pii_redacted | injection_flagged | rule_applied
  model         text,
  confidence    numeric(4,3),                   -- display only, never a gate
  rule_id       int,
  created_at    timestamptz not null default now()
);
create index if not exists items_run_status_idx on items (run_id, status);

create table if not exists proposed_entries ( id              uuid primary key default gen_random_uuid(),
  item_id         uuid not null references items(id) on delete cascade,
  debit_account   text not null,
  credit_account  text not null,
  amount          numeric(14,2) not null check (amount > 0),
  memo            text not null,
  status          text not null default 'draft' check (status in ('draft','approved','rejected','posted')),
  created_at      timestamptz not null default now()
);

create table if not exists decisions (
  id          uuid primary key default gen_random_uuid(),
  item_id     uuid not null references items(id) on delete cascade,
  decision    text not null check (decision in ('approve','reject')),
  actor       text not null,
  note        text,
  remember    boolean not null default false,
  entry_override jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists rules (
  id           serial primary key,
  kind         text not null,
  pattern      jsonb not null,    -- e.g. {"description_regex": "MONTHLY SERVICE FEE"}
  action       jsonb not null,    -- e.g. {"debit": "6800", "credit": "1010"}
  source_item  uuid references items(id) on delete set null,
  created_by   text not null,
  dataset      text not null,     -- the dataset the rule was learned on (or seeded for)
  origin       text not null default 'learned' check (origin in ('learned', 'seeded')),
  active       boolean not null default true,
  created_at   timestamptz not null default now()
);

-- /demo/reset deletes a dataset's learned rules.
create index if not exists rules_dataset_origin_idx on rules (dataset, origin);

create table if not exists audit_log (
  id          bigserial primary key,
  -- Append-only: deleting a run (/demo/reset) keeps its history, run_id goes null.
  run_id      uuid references runs(id) on delete set null,
  entity_type text not null,      -- run | item | entry | rule | guardrail | dataset
  entity_id   text,
  action      text not null,
  actor       text not null,      -- agent:<name> | user:<name> | system
  model       text,
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

-- Indexes the FK, so deleting a run does not scan the whole log to null run_id.
create index if not exists audit_log_run_id_idx on audit_log (run_id);

alter table bank_transactions enable row level security;
alter table gl_entries        enable row level security;
alter table balances          enable row level security;
alter table runs              enable row level security;
alter table run_steps         enable row level security;
alter table items             enable row level security;
alter table proposed_entries  enable row level security;
alter table decisions         enable row level security;
alter table rules             enable row level security;
alter table audit_log         enable row level security;
