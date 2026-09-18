create table if not exists public.raw_reviews (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  source text not null,
  external_id text not null,
  author text not null default 'Unknown',
  text_content text not null check (length(text_content) > 0),
  rating numeric(2,1) check (rating is null or rating between 0 and 5),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  language text not null default 'unknown',
  url text,
  metadata jsonb not null default '{}'::jsonb,
  unique (business_id, source, external_id)
);

create index if not exists raw_reviews_business_created_idx
  on public.raw_reviews (business_id, created_at desc);

alter table public.raw_reviews enable row level security;
drop policy if exists "raw reviews workspace isolation" on public.raw_reviews;
create policy "raw reviews workspace isolation" on public.raw_reviews
  for all using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));

grant select, insert, update, delete on public.raw_reviews to authenticated;
grant all privileges on public.raw_reviews to service_role;
