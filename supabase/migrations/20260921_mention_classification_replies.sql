alter table public.mentions
  add column if not exists content_type text not null default 'review'
    check (content_type in ('review','comment','question','post','news','other')),
  add column if not exists author_type text not null default 'unknown'
    check (author_type in ('customer','employee','company','unknown')),
  add column if not exists include_in_analysis boolean not null default true,
  add column if not exists reply_draft text,
  add column if not exists reply_generated_at timestamptz,
  add column if not exists reply_status text not null default 'none'
    check (reply_status in ('none','draft','answered'));

create index if not exists mentions_analysis_scope_idx
  on public.mentions (business_id, include_in_analysis, published_at desc);
