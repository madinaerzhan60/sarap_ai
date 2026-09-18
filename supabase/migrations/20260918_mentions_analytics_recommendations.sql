alter table public.ai_analysis add column if not exists summary text not null default '';

create table if not exists public.business_recommendations (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  period_start date not null,
  period_end date not null,
  score numeric(3,1) not null check (score between 0 and 10),
  summary text not null default '',
  recommendations jsonb not null default '{"urgent_fix":[],"improve":[],"keep_doing":[]}'::jsonb,
  generated_at timestamptz not null default now(),
  unique (business_id, period_start, period_end)
);

create index if not exists business_recommendations_lookup_idx
  on public.business_recommendations (business_id, period_end desc);

alter table public.business_recommendations enable row level security;
drop policy if exists "business recommendations isolation" on public.business_recommendations;
create policy "business recommendations isolation" on public.business_recommendations
  for all using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));

grant select, insert, update, delete on public.business_recommendations to authenticated;
grant all privileges on public.business_recommendations to service_role;
