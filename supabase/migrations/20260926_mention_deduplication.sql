-- Migration: Mention deduplication fields and partial unique index
alter table public.mentions
  add column if not exists dedupe_key text,
  add column if not exists is_duplicate boolean not null default false,
  add column if not exists duplicate_group_id uuid,
  add column if not exists canonical_mention_id uuid references public.mentions(id) on delete set null;

-- Partial unique index for strict race condition protection at DB level
create unique index if not exists idx_mentions_dedupe_key_unique on public.mentions (business_id, dedupe_key) where dedupe_key is not null;
create index if not exists idx_mentions_is_duplicate on public.mentions (business_id, is_duplicate);
