-- Generate useful search aliases when onboarding does not provide them.
create or replace function public.default_brand_aliases(p_name text)
returns text[] language plpgsql immutable set search_path = public
as $$
declare
  clean_name text := regexp_replace(trim(coalesce(p_name, '')), '\s+', ' ', 'g');
  abbreviation text;
  aliases text[];
begin
  if clean_name = '' then return '{}'::text[]; end if;
  select string_agg(upper(left(word, 1)), '') into abbreviation
  from regexp_split_to_table(clean_name, '\s+') as word
  where lower(word) not in ('university','college','school','company','restaurant','cafe','café','hotel','clinic','shop');
  aliases := array[clean_name];
  if length(coalesce(abbreviation, '')) >= 2 then aliases := aliases || abbreviation; end if;
  if lower(clean_name) in ('sdu', 'sdu university') then
    aliases := aliases || array['SDU University','Suleyman Demirel University','СДУ','Сулейман Демирель университеті','Сулейман Демирель университет'];
  end if;
  return array(select distinct value from unnest(aliases) value where nullif(trim(value), '') is not null);
end;
$$;

create or replace function public.complete_workspace(p_name text, p_website text default null, p_industry text default null, p_country text default 'Kazakhstan', p_city text default null, p_location_count integer default 1, p_aliases text[] default '{}')
returns uuid language plpgsql security definer set search_path = public
as $$
declare workspace_id uuid; brand_alias text; effective_aliases text[];
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
  effective_aliases := case when coalesce(cardinality(p_aliases), 0) = 0 then public.default_brand_aliases(p_name) else p_aliases end;
  delete from public.brand_aliases where business_id=workspace_id;
  foreach brand_alias in array effective_aliases loop
    if nullif(trim(brand_alias), '') is not null then insert into public.brand_aliases (business_id,alias) values (workspace_id,trim(brand_alias)) on conflict do nothing; end if;
  end loop;
  return workspace_id;
end;
$$;

revoke all on function public.default_brand_aliases(text) from public, anon;
grant execute on function public.default_brand_aliases(text) to authenticated;
revoke all on function public.complete_workspace(text,text,text,text,text,integer,text[]) from public, anon;
grant execute on function public.complete_workspace(text,text,text,text,text,integer,text[]) to authenticated;
