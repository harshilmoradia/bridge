-- Account profiles: one row per Supabase Auth user, created by trigger at signup.
-- Clients (anon / authenticated) can read their own row and change only display_name.
-- Apply after 0001_init.sql, in the Supabase SQL editor or with psql.

create table if not exists public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  display_name text not null default 'Accountant'
               check (btrim(display_name) <> '' and char_length(display_name) <= 100),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Supabase grants new tables to anon/authenticated by default; start from nothing.
revoke all on public.profiles from anon, authenticated;
grant select on public.profiles to authenticated;
grant update (display_name) on public.profiles to authenticated;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select to authenticated
  using (id = auth.uid());

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- Keep updated_at honest; clients cannot write it directly.
create or replace function public.bridge_touch_profile()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = clock_timestamp();
  return new;
end;
$$;

drop trigger if exists bridge_touch_profile on public.profiles;
create trigger bridge_touch_profile
  before update on public.profiles
  for each row execute function public.bridge_touch_profile();

-- Signup trigger. SECURITY DEFINER so it can insert past RLS; not callable by clients.
create or replace function public.bridge_create_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  name text := left(btrim(coalesce(new.raw_user_meta_data ->> 'display_name', '')), 100);
begin
  insert into public.profiles (id, display_name)
  values (new.id, case when name = '' then 'Accountant' else name end)
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke all on function public.bridge_create_profile() from public, anon, authenticated;

-- Backfill users that signed up before this migration.
insert into public.profiles (id, display_name)
select u.id,
       coalesce(nullif(left(btrim(coalesce(u.raw_user_meta_data ->> 'display_name', '')), 100), ''), 'Accountant')
from auth.users u
on conflict (id) do nothing;

drop trigger if exists bridge_create_profile on auth.users;
create trigger bridge_create_profile
  after insert on auth.users
  for each row execute function public.bridge_create_profile();
