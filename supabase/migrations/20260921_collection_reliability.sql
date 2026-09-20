alter table public.source_connections
  add column if not exists last_seen_published_at timestamptz;

create table if not exists public.provider_usage_daily (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  provider text not null,
  usage_date date not null default current_date,
  calls integer not null default 0,
  failures integer not null default 0,
  last_success_at timestamptz,
  estimated_cost numeric(12,6) not null default 0,
  disabled_until timestamptz,
  updated_at timestamptz not null default now(),
  unique (business_id, provider, usage_date)
);

alter table public.provider_usage_daily enable row level security;
drop policy if exists "provider usage business isolation" on public.provider_usage_daily;
create policy "provider usage business isolation" on public.provider_usage_daily
for select using (public.is_business_member(business_id));
revoke insert, update, delete on public.provider_usage_daily from anon, authenticated;
grant select on public.provider_usage_daily to authenticated;
