-- SARAP persistent product data and server-only administration.
alter table public.profiles add column if not exists role text not null default 'user' check (role in ('user', 'admin'));
-- Prevent a normal authenticated user from promoting their own profile through
-- the existing self-update RLS policy. Role changes are service-role only.
revoke update on public.profiles from authenticated;
grant update (full_name, updated_at) on public.profiles to authenticated;
grant select, update on public.profiles to service_role;
alter table public.businesses add column if not exists plan text not null default 'starter';
alter table public.businesses add column if not exists last_activity_at timestamptz;
alter table public.mentions add column if not exists reviewed boolean not null default false;
alter table public.mentions add column if not exists reviewed_at timestamptz;
alter table public.mentions add column if not exists reviewed_by uuid references auth.users on delete set null;

-- Return the account profile even when the user has no workspace yet. This is
-- required for clean onboarding accounts and workspace-less platform admins.
create or replace function public.get_my_workspace()
returns jsonb language sql stable security definer set search_path = public
as $$
  select jsonb_build_object(
    'profile', (select to_jsonb(p) from public.profiles p where p.id = auth.uid()),
    'business', (select to_jsonb(b) from public.businesses b join public.business_members bm on bm.business_id=b.id where bm.user_id=auth.uid() order by bm.created_at limit 1),
    'role', (select bm.role from public.business_members bm where bm.user_id=auth.uid() order by bm.created_at limit 1),
    'aliases', coalesce((select jsonb_agg(a.alias order by a.created_at) from public.brand_aliases a where a.business_id=(select bm.business_id from public.business_members bm where bm.user_id=auth.uid() order by bm.created_at limit 1)), '[]'::jsonb),
    'sources', coalesce((select jsonb_agg(to_jsonb(s) order by s.created_at) from public.source_connections s where s.business_id=(select bm.business_id from public.business_members bm where bm.user_id=auth.uid() order by bm.created_at limit 1)), '[]'::jsonb)
  )
$$;
revoke all on function public.get_my_workspace() from public, anon;
grant execute on function public.get_my_workspace() to authenticated;

create table if not exists public.workspace_settings (
  business_id uuid primary key references public.businesses on delete cascade,
  alert_threshold integer not null default 60 check (alert_threshold between 0 and 100),
  reply_tone text not null default 'Warm and professional',
  custom_aspects text not null default '',
  email_alerts boolean not null default false,
  telegram_alerts boolean not null default false,
  retention_months integer not null default 12 check (retention_months between 1 and 84),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_usage (
  id uuid primary key default gen_random_uuid(),
  business_id uuid references public.businesses on delete set null,
  provider text not null,
  model text,
  operation text not null default 'mention_analysis',
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  estimated_cost_usd numeric(12,6) not null default 0,
  status text not null default 'success',
  created_at timestamptz not null default now()
);

create table if not exists public.feature_flags (
  key text primary key,
  description text,
  enabled boolean not null default false,
  updated_by uuid references auth.users on delete set null,
  updated_at timestamptz not null default now()
);

create table if not exists public.system_settings (
  key text primary key,
  value jsonb not null,
  updated_by uuid references auth.users on delete set null,
  updated_at timestamptz not null default now()
);

create table if not exists public.admin_audit_log (
  id uuid primary key default gen_random_uuid(),
  admin_user_id uuid references auth.users on delete set null,
  action text not null,
  target_type text,
  target_id text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

alter table public.workspace_settings enable row level security;
alter table public.ai_usage enable row level security;
alter table public.feature_flags enable row level security;
alter table public.system_settings enable row level security;
alter table public.admin_audit_log enable row level security;

-- PostgREST requires SQL grants in addition to RLS. RLS still limits every
-- authenticated request to the caller's own business workspace.
grant usage on schema public to authenticated, service_role;
grant select on public.profiles to authenticated;
grant update (full_name, updated_at) on public.profiles to authenticated;
grant select on public.businesses, public.business_members to authenticated;
grant update on public.businesses to authenticated;
grant select, insert, update, delete on
  public.business_locations,
  public.brand_aliases,
  public.source_connections,
  public.source_jobs,
  public.mentions,
  public.mention_revisions,
  public.ai_analysis,
  public.mention_aspects,
  public.risk_scores,
  public.alerts,
  public.alert_deliveries,
  public.search_queries,
  public.web_discoveries,
  public.daily_metrics,
  public.aspect_metrics,
  public.telegram_connections,
  public.workspace_settings
to authenticated;
grant select on public.ai_usage to authenticated;
grant all privileges on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Keep encrypted provider credentials and platform controls server-only.
revoke all on public.source_credentials from anon, authenticated;

drop policy if exists "workspace settings isolation" on public.workspace_settings;
create policy "workspace settings isolation" on public.workspace_settings for all
  using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));
drop policy if exists "members read ai usage" on public.ai_usage;
create policy "members read ai usage" on public.ai_usage for select
  using (business_id is not null and public.is_business_member(business_id));

-- Admin-only tables intentionally have no authenticated policies. The protected
-- FastAPI admin API accesses them with the backend-only service role.
revoke all on public.feature_flags, public.system_settings, public.admin_audit_log from anon, authenticated;
grant select, insert, update, delete on public.feature_flags, public.system_settings, public.admin_audit_log to service_role;

insert into public.system_settings(key, value) values
  ('default_risk_threshold', '{"value":60}'::jsonb),
  ('local_analysis_fallback', '{"enabled":true}'::jsonb)
on conflict (key) do nothing;

insert into public.feature_flags(key, description, enabled) values
  ('smart_reply', 'Generate reviewable reply suggestions', true),
  ('web_discovery', 'Run free web and news discovery', true),
  ('telegram_alerts', 'Deliver threshold alerts through Telegram', false),
  ('source_2gis', 'Allow new 2GIS source connections', true),
  ('source_yandex', 'Allow new Yandex Maps source connections', false),
  ('source_instagram', 'Allow new Instagram source connections', false)
on conflict (key) do nothing;

create index if not exists ai_usage_business_created_idx on public.ai_usage (business_id, created_at desc);
create index if not exists admin_audit_created_idx on public.admin_audit_log (created_at desc);
