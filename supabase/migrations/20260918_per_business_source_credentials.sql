-- OAuth credentials are backend-only and cryptographically bound to both the
-- workspace and source connection. Plaintext tokens never enter PostgreSQL.
alter table public.source_credentials
  add column if not exists business_id uuid references public.businesses on delete cascade,
  add column if not exists provider text;

update public.source_credentials credential
set business_id = source.business_id,
    provider = case
      when lower(source.source) like 'instagram%' then 'instagram'
      else 'google_business'
    end
from public.source_connections source
where source.id = credential.source_connection_id
  and (credential.business_id is null or credential.provider is null);

alter table public.source_credentials
  alter column business_id set not null,
  alter column provider set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.source_credentials'::regclass
      and conname = 'source_credentials_provider_check'
  ) then
    alter table public.source_credentials
      add constraint source_credentials_provider_check
      check (provider in ('google_business', 'instagram'));
  end if;
end $$;

create unique index if not exists source_credentials_source_connection_uidx
  on public.source_credentials (source_connection_id);
create index if not exists source_credentials_business_idx
  on public.source_credentials (business_id);

alter table public.source_credentials enable row level security;
revoke all on public.source_credentials from public, anon, authenticated;
grant select, insert, update, delete on public.source_credentials to service_role;
