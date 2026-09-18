create extension if not exists pgcrypto;

create type public.connection_type as enum ('official', 'monitored', 'provider', 'imported');
create type public.collection_mode as enum ('auto', 'api', 'scraper');
create type public.mention_type as enum ('review', 'social_post', 'social_comment', 'news_article', 'blog', 'forum', 'web_page', 'video_comment');

create table public.profiles (
  id uuid primary key references auth.users on delete cascade,
  full_name text,
  email text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.businesses (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  website text,
  industry text,
  country text default 'Kazakhstan',
  city text,
  location_count integer not null default 1 check (location_count > 0),
  onboarding_completed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.business_members (
  business_id uuid not null references public.businesses on delete cascade,
  user_id uuid not null references auth.users on delete cascade,
  role text not null default 'owner',
  created_at timestamptz not null default now(),
  primary key (business_id, user_id)
);

create table public.business_locations (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  name text not null,
  city text,
  address text,
  created_at timestamptz not null default now()
);

create table public.brand_aliases (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  alias text not null,
  alias_type text not null default 'alternative',
  created_at timestamptz not null default now(),
  unique (business_id, alias)
);

create table public.source_connections (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  source text not null,
  connection_type public.connection_type not null,
  collection_mode public.collection_mode not null default 'auto',
  active_collection_method text,
  source_url text,
  external_business_id text,
  status text not null default 'pending',
  last_seen_item_id text,
  last_checked_at timestamptz,
  next_check_at timestamptz,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.source_credentials (
  id uuid primary key default gen_random_uuid(),
  source_connection_id uuid not null references public.source_connections on delete cascade,
  encrypted_token text not null,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
revoke all on public.source_credentials from anon, authenticated;

create table public.source_jobs (
  id uuid primary key default gen_random_uuid(),
  source_connection_id uuid not null references public.source_connections on delete cascade,
  job_type text not null,
  status text not null default 'queued',
  run_after timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  attempts integer not null default 0,
  error text,
  created_at timestamptz not null default now()
);

create table public.mentions (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  source text not null,
  source_type public.mention_type not null,
  external_id text not null,
  external_url text,
  author_name text,
  text text not null,
  rating numeric(2,1),
  published_at timestamptz,
  collected_at timestamptz not null default now(),
  language text,
  content_hash text not null,
  metadata jsonb not null default '{}',
  unique (business_id, source, external_id, content_hash)
);

create table public.mention_revisions (
  id uuid primary key default gen_random_uuid(),
  mention_id uuid not null references public.mentions on delete cascade,
  text text not null,
  content_hash text not null,
  created_at timestamptz not null default now()
);

create table public.ai_analysis (
  id uuid primary key default gen_random_uuid(),
  mention_id uuid not null unique references public.mentions on delete cascade,
  language text not null,
  sentiment text not null,
  summary text not null default '',
  sentiment_score numeric(5,4),
  severity text not null,
  confidence numeric(5,4),
  model text,
  escalated boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.mention_aspects (
  id uuid primary key default gen_random_uuid(),
  mention_id uuid not null references public.mentions on delete cascade,
  aspect text not null,
  sentiment text not null,
  confidence numeric(5,4),
  created_at timestamptz not null default now()
);

create table public.risk_scores (
  id uuid primary key default gen_random_uuid(),
  mention_id uuid not null unique references public.mentions on delete cascade,
  score integer not null check (score between 0 and 100),
  level text not null,
  reasons jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table public.alerts (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  mention_id uuid references public.mentions on delete cascade,
  severity text not null,
  status text not null default 'new',
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table public.alert_deliveries (
  id uuid primary key default gen_random_uuid(),
  alert_id uuid not null references public.alerts on delete cascade,
  channel text not null,
  status text not null,
  provider_message_id text,
  error text,
  created_at timestamptz not null default now()
);

create table public.search_queries (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  query text not null,
  intent text,
  language text,
  last_run_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.web_discoveries (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses on delete cascade,
  url text not null,
  title text,
  snippet text,
  relevance numeric(5,4),
  mention_id uuid references public.mentions on delete set null,
  discovered_at timestamptz not null default now(),
  unique (business_id, url)
);

create table public.daily_metrics (
  business_id uuid not null references public.businesses on delete cascade,
  day date not null,
  total_mentions integer not null default 0,
  positive_count integer not null default 0,
  neutral_count integer not null default 0,
  negative_count integer not null default 0,
  primary key (business_id, day)
);

create table public.aspect_metrics (
  business_id uuid not null references public.businesses on delete cascade,
  day date not null,
  aspect text not null,
  positive_count integer not null default 0,
  negative_count integer not null default 0,
  primary key (business_id, day, aspect)
);

create table public.business_recommendations (
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

create table public.telegram_connections (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null unique references public.businesses on delete cascade,
  encrypted_chat_id text not null,
  enabled boolean not null default true,
  threshold integer not null default 60,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index mentions_business_published_idx on public.mentions (business_id, published_at desc);
create index mentions_source_external_idx on public.mentions (source, external_id);
create index mentions_hash_idx on public.mentions (content_hash);
create index business_recommendations_lookup_idx on public.business_recommendations (business_id, period_end desc);
create index ai_analysis_sentiment_idx on public.ai_analysis (sentiment);
create index risk_scores_score_idx on public.risk_scores (score desc);
create index source_jobs_ready_idx on public.source_jobs (status, run_after);

alter table public.businesses enable row level security;
alter table public.profiles enable row level security;
alter table public.business_members enable row level security;
alter table public.business_locations enable row level security;
alter table public.brand_aliases enable row level security;
alter table public.source_connections enable row level security;
alter table public.mentions enable row level security;
alter table public.mention_revisions enable row level security;
alter table public.ai_analysis enable row level security;
alter table public.mention_aspects enable row level security;
alter table public.risk_scores enable row level security;
alter table public.alerts enable row level security;
alter table public.search_queries enable row level security;
alter table public.web_discoveries enable row level security;
alter table public.daily_metrics enable row level security;
alter table public.aspect_metrics enable row level security;
alter table public.telegram_connections enable row level security;
alter table public.source_jobs enable row level security;
alter table public.alert_deliveries enable row level security;

create function public.is_business_member(target_business_id uuid)
returns boolean language sql stable security definer set search_path = public
as $$ select exists (select 1 from public.business_members where business_id = target_business_id and user_id = auth.uid()) $$;

create policy "members read businesses" on public.businesses for select using (public.is_business_member(id));
create policy "members update businesses" on public.businesses for update using (public.is_business_member(id)) with check (public.is_business_member(id));
create policy "users read memberships" on public.business_members for select using (user_id = auth.uid());
create policy "users read own profile" on public.profiles for select using (id = auth.uid());
create policy "users update own profile" on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());

do $$
declare table_name text;
begin
  foreach table_name in array array['business_locations','brand_aliases','source_connections','mentions','alerts','search_queries','web_discoveries','daily_metrics','aspect_metrics','telegram_connections']
  loop
    execute format('create policy "business isolation" on public.%I for all using (public.is_business_member(business_id)) with check (public.is_business_member(business_id))', table_name);
  end loop;
end $$;

create policy "mention revision isolation" on public.mention_revisions for all using (exists (select 1 from public.mentions m where m.id = mention_id and public.is_business_member(m.business_id)));
create policy "analysis isolation" on public.ai_analysis for all using (exists (select 1 from public.mentions m where m.id = mention_id and public.is_business_member(m.business_id)));
create policy "aspect isolation" on public.mention_aspects for all using (exists (select 1 from public.mentions m where m.id = mention_id and public.is_business_member(m.business_id)));
create policy "risk isolation" on public.risk_scores for all using (exists (select 1 from public.mentions m where m.id = mention_id and public.is_business_member(m.business_id)));
create policy "source job isolation" on public.source_jobs for all using (exists (select 1 from public.source_connections s where s.id = source_connection_id and public.is_business_member(s.business_id))) with check (exists (select 1 from public.source_connections s where s.id = source_connection_id and public.is_business_member(s.business_id)));
create policy "alert delivery isolation" on public.alert_deliveries for all using (exists (select 1 from public.alerts a where a.id = alert_id and public.is_business_member(a.business_id))) with check (exists (select 1 from public.alerts a where a.id = alert_id and public.is_business_member(a.business_id)));

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, email)
  values (new.id, new.raw_user_meta_data ->> 'full_name', new.email)
  on conflict (id) do update set email = excluded.email, full_name = coalesce(excluded.full_name, public.profiles.full_name), updated_at = now();
  return new;
end;
$$;

create trigger on_auth_user_created
after insert or update of email on auth.users
for each row execute function public.handle_new_user();

create or replace function public.complete_workspace(
  p_name text,
  p_website text default null,
  p_industry text default null,
  p_country text default 'Kazakhstan',
  p_city text default null,
  p_location_count integer default 1,
  p_aliases text[] default '{}'
)
returns uuid language plpgsql security definer set search_path = public
as $$
declare
  workspace_id uuid;
  brand_alias text;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if nullif(trim(p_name), '') is null then raise exception 'Business name is required'; end if;

  select business_id into workspace_id from public.business_members where user_id = auth.uid() order by created_at limit 1;
  if workspace_id is null then
    insert into public.businesses (name, website, industry, country, city, location_count, onboarding_completed)
    values (trim(p_name), nullif(trim(p_website), ''), p_industry, coalesce(nullif(trim(p_country), ''), 'Kazakhstan'), nullif(trim(p_city), ''), greatest(coalesce(p_location_count, 1), 1), true)
    returning id into workspace_id;
    insert into public.business_members (business_id, user_id, role) values (workspace_id, auth.uid(), 'owner');
  else
    update public.businesses set name = trim(p_name), website = nullif(trim(p_website), ''), industry = p_industry, country = coalesce(nullif(trim(p_country), ''), 'Kazakhstan'), city = nullif(trim(p_city), ''), location_count = greatest(coalesce(p_location_count, 1), 1), onboarding_completed = true, updated_at = now() where id = workspace_id;
  end if;

  delete from public.brand_aliases where business_id = workspace_id;
  foreach brand_alias in array p_aliases loop
    if nullif(trim(brand_alias), '') is not null then
      insert into public.brand_aliases (business_id, alias) values (workspace_id, trim(brand_alias)) on conflict do nothing;
    end if;
  end loop;
  return workspace_id;
end;
$$;

create or replace function public.get_my_workspace()
returns jsonb language sql stable security definer set search_path = public
as $$
  select jsonb_build_object(
    'profile', (select to_jsonb(p) from public.profiles p where p.id = auth.uid()),
    'business', (select to_jsonb(b) from public.businesses b where b.id = bm.business_id),
    'role', bm.role,
    'aliases', coalesce((select jsonb_agg(a.alias order by a.created_at) from public.brand_aliases a where a.business_id = bm.business_id), '[]'::jsonb),
    'sources', coalesce((select jsonb_agg(to_jsonb(s) order by s.created_at) from public.source_connections s where s.business_id = bm.business_id), '[]'::jsonb)
  )
  from public.business_members bm
  where bm.user_id = auth.uid()
  order by bm.created_at
  limit 1
$$;

revoke all on function public.complete_workspace(text,text,text,text,text,integer,text[]) from public, anon;
revoke all on function public.get_my_workspace() from public, anon;
grant execute on function public.complete_workspace(text,text,text,text,text,integer,text[]) to authenticated;
grant execute on function public.get_my_workspace() to authenticated;
