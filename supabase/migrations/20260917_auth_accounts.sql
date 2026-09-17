create table if not exists public.profiles (
  id uuid primary key references auth.users on delete cascade,
  full_name text,
  email text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.businesses add column if not exists location_count integer not null default 1 check (location_count > 0);
alter table public.businesses add column if not exists onboarding_completed boolean not null default false;
alter table public.profiles enable row level security;
alter table public.source_jobs enable row level security;
alter table public.alert_deliveries enable row level security;

drop policy if exists "members update businesses" on public.businesses;
create policy "members update businesses" on public.businesses for update using (public.is_business_member(id)) with check (public.is_business_member(id));
drop policy if exists "users read own profile" on public.profiles;
create policy "users read own profile" on public.profiles for select using (id = auth.uid());
drop policy if exists "users update own profile" on public.profiles;
create policy "users update own profile" on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());
drop policy if exists "source job isolation" on public.source_jobs;
create policy "source job isolation" on public.source_jobs for all using (exists (select 1 from public.source_connections s where s.id = source_connection_id and public.is_business_member(s.business_id))) with check (exists (select 1 from public.source_connections s where s.id = source_connection_id and public.is_business_member(s.business_id)));
drop policy if exists "alert delivery isolation" on public.alert_deliveries;
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

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert or update of email on auth.users for each row execute function public.handle_new_user();

insert into public.profiles (id, full_name, email)
select id, raw_user_meta_data ->> 'full_name', email from auth.users
on conflict (id) do nothing;

create or replace function public.complete_workspace(p_name text, p_website text default null, p_industry text default null, p_country text default 'Kazakhstan', p_city text default null, p_location_count integer default 1, p_aliases text[] default '{}')
returns uuid language plpgsql security definer set search_path = public
as $$
declare workspace_id uuid; brand_alias text;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if nullif(trim(p_name), '') is null then raise exception 'Business name is required'; end if;
  select business_id into workspace_id from public.business_members where user_id = auth.uid() order by created_at limit 1;
  if workspace_id is null then
    insert into public.businesses (name, website, industry, country, city, location_count, onboarding_completed) values (trim(p_name), nullif(trim(p_website), ''), p_industry, coalesce(nullif(trim(p_country), ''), 'Kazakhstan'), nullif(trim(p_city), ''), greatest(coalesce(p_location_count, 1), 1), true) returning id into workspace_id;
    insert into public.business_members (business_id, user_id, role) values (workspace_id, auth.uid(), 'owner');
  else
    update public.businesses set name=trim(p_name), website=nullif(trim(p_website), ''), industry=p_industry, country=coalesce(nullif(trim(p_country), ''), 'Kazakhstan'), city=nullif(trim(p_city), ''), location_count=greatest(coalesce(p_location_count, 1), 1), onboarding_completed=true, updated_at=now() where id=workspace_id;
  end if;
  delete from public.brand_aliases where business_id=workspace_id;
  foreach brand_alias in array p_aliases loop
    if nullif(trim(brand_alias), '') is not null then insert into public.brand_aliases (business_id,alias) values (workspace_id,trim(brand_alias)) on conflict do nothing; end if;
  end loop;
  return workspace_id;
end;
$$;

create or replace function public.get_my_workspace()
returns jsonb language sql stable security definer set search_path = public
as $$
  select jsonb_build_object('profile',(select to_jsonb(p) from public.profiles p where p.id=auth.uid()),'business',(select to_jsonb(b) from public.businesses b where b.id=bm.business_id),'role',bm.role,'aliases',coalesce((select jsonb_agg(a.alias order by a.created_at) from public.brand_aliases a where a.business_id=bm.business_id),'[]'::jsonb),'sources',coalesce((select jsonb_agg(to_jsonb(s) order by s.created_at) from public.source_connections s where s.business_id=bm.business_id),'[]'::jsonb)) from public.business_members bm where bm.user_id=auth.uid() order by bm.created_at limit 1
$$;

revoke all on function public.complete_workspace(text,text,text,text,text,integer,text[]) from public, anon;
revoke all on function public.get_my_workspace() from public, anon;
grant execute on function public.complete_workspace(text,text,text,text,text,integer,text[]) to authenticated;
grant execute on function public.get_my_workspace() to authenticated;
