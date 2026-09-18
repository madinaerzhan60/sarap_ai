alter table public.raw_reviews
  add column if not exists collected_by text not null default 'unknown';

create index if not exists raw_reviews_collected_by_idx
  on public.raw_reviews (business_id, collected_by, created_at desc);
