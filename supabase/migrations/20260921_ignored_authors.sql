create table if not exists public.ignored_authors (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  source text not null,
  author_key text not null,
  created_at timestamptz not null default now(),
  unique (business_id, source, author_key)
);
alter table public.ignored_authors enable row level security;
create policy "ignored authors business isolation" on public.ignored_authors for select using (public.is_business_member(business_id));
revoke insert, update, delete on public.ignored_authors from anon, authenticated;
grant select on public.ignored_authors to authenticated;
