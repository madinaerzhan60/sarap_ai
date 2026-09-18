-- Restore PostgREST privileges for authenticated workspace users.
-- RLS policies still restrict every row to the caller's workspace.
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
