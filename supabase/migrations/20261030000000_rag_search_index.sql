-- RAG search index foundation. Apply after the existing Bridge migrations.
-- Source records remain authoritative; this table stores screened text and derived embeddings only.
-- Chat has no write path to source tables. These triggers only enqueue index maintenance when
-- existing authorized database processes modify bank_transactions or gl_entries.
--
-- Uses 1,536 output dimensions from the configured Nebius embedding model. Changing vector
-- dimensions requires a deliberate rebuild/migration because pgvector dimensions are fixed per column.

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists public.bridge_rag_search_documents (
  dataset          text not null,
  source_type      text not null check (source_type in ('bank_transaction', 'gl_entry')),
  source_id        text not null,
  search_text      text not null,
  search_tsv       tsvector generated always as (to_tsvector('simple'::regconfig, search_text)) stored,
  embedding        extensions.vector(1536),
  embedding_model  text,
  content_hash     text not null,
  indexed_at       timestamptz not null default now(),
  primary key (dataset, source_type, source_id),
  check ((embedding is null) = (embedding_model is null))
);

create index if not exists bridge_rag_search_documents_fts_idx
  on public.bridge_rag_search_documents using gin (search_tsv);

create index if not exists bridge_rag_search_documents_dataset_idx
  on public.bridge_rag_search_documents (dataset, source_type);

create index if not exists bridge_rag_search_documents_embedding_hnsw_idx
  on public.bridge_rag_search_documents
  using hnsw (embedding extensions.vector_cosine_ops)
  where embedding is not null;

create index if not exists bridge_rag_search_documents_embedding_missing_idx
  on public.bridge_rag_search_documents (dataset, source_type, source_id)
  where embedding is null;

-- Keep queued work to identifiers and operation metadata only: raw transaction text and vectors
-- must not be copied into an asynchronous queue or Inngest step output.
create table if not exists public.bridge_rag_search_outbox (
  id               bigserial primary key,
  dataset          text not null,
  source_type      text not null check (source_type in ('bank_transaction', 'gl_entry')),
  source_id        text not null,
  operation        text not null check (operation in ('refresh', 'delete')),
  queued_at        timestamptz not null default now(),
  attempts         integer not null default 0 check (attempts >= 0),
  locked_at        timestamptz,
  claim_token      uuid,
  processed_at     timestamptz,
  last_error_code  text,
  unique (dataset, source_type, source_id)
);

create index if not exists bridge_rag_search_outbox_pending_idx
  on public.bridge_rag_search_outbox (queued_at, id)
  where processed_at is null;

alter table public.bridge_rag_search_documents enable row level security;
alter table public.bridge_rag_search_outbox enable row level security;

-- Finance data and the derived search index remain backend-only, consistent with 0001_init.sql.
revoke all on public.bridge_rag_search_documents from anon, authenticated;
revoke all on public.bridge_rag_search_outbox from anon, authenticated;
revoke all on sequence public.bridge_rag_search_outbox_id_seq from anon, authenticated;

create or replace function public.bridge_rag_enqueue_source_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  old_dataset text;
  old_id text;
  new_dataset text;
  new_id text;
  source_kind text;
begin
  if tg_table_name = 'bank_transactions' then
    source_kind := 'bank_transaction';
    if tg_op <> 'INSERT' then
      old_dataset := old.dataset;
      old_id := old.txn_id;
    end if;
    if tg_op <> 'DELETE' then
      new_dataset := new.dataset;
      new_id := new.txn_id;
    end if;
  elsif tg_table_name = 'gl_entries' then
    source_kind := 'gl_entry';
    if tg_op <> 'INSERT' then
      old_dataset := old.dataset;
      old_id := old.entry_id;
    end if;
    if tg_op <> 'DELETE' then
      new_dataset := new.dataset;
      new_id := new.entry_id;
    end if;
  else
    raise exception 'Unsupported source table for RAG indexing';
  end if;

  if old_dataset is not null and (new_dataset is null or old_dataset <> new_dataset or old_id <> new_id) then
    insert into public.bridge_rag_search_outbox (dataset, source_type, source_id, operation)
    values (old_dataset, source_kind, old_id, 'delete')
    on conflict (dataset, source_type, source_id) do update
      set operation = excluded.operation,
          queued_at = clock_timestamp(),
          attempts = 0,
          locked_at = null,
          claim_token = null,
          processed_at = null,
          last_error_code = null;
  end if;

  if new_dataset is not null then
    insert into public.bridge_rag_search_outbox (dataset, source_type, source_id, operation)
    values (new_dataset, source_kind, new_id, 'refresh')
    on conflict (dataset, source_type, source_id) do update
      set operation = excluded.operation,
          queued_at = clock_timestamp(),
          attempts = 0,
          locked_at = null,
          claim_token = null,
          processed_at = null,
          last_error_code = null;
  end if;

  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

revoke all on function public.bridge_rag_enqueue_source_change() from public, anon, authenticated;

drop trigger if exists bridge_rag_bank_transaction_change on public.bank_transactions;
create trigger bridge_rag_bank_transaction_change
after insert or update or delete on public.bank_transactions
for each row execute function public.bridge_rag_enqueue_source_change();

drop trigger if exists bridge_rag_gl_entry_change on public.gl_entries;
create trigger bridge_rag_gl_entry_change
after insert or update or delete on public.gl_entries
for each row execute function public.bridge_rag_enqueue_source_change();

-- Backfill identifiers only. The worker reads current source rows, applies screen_text(), and writes
-- masked searchable text; no raw description is copied into this migration or the outbox.
insert into public.bridge_rag_search_outbox (dataset, source_type, source_id, operation)
select dataset, 'bank_transaction', txn_id, 'refresh'
from public.bank_transactions
on conflict (dataset, source_type, source_id) do update
  set operation = excluded.operation,
      queued_at = clock_timestamp(),
      attempts = 0,
      locked_at = null,
      claim_token = null,
      processed_at = null,
      last_error_code = null;

insert into public.bridge_rag_search_outbox (dataset, source_type, source_id, operation)
select dataset, 'gl_entry', entry_id, 'refresh'
from public.gl_entries
on conflict (dataset, source_type, source_id) do update
  set operation = excluded.operation,
      queued_at = clock_timestamp(),
      attempts = 0,
      locked_at = null,
      claim_token = null,
      processed_at = null,
      last_error_code = null;
