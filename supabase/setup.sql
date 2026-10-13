-- OmniStore AI Manager cloud activity + sales aggregates.
-- Run once in the Supabase SQL Editor for the project configured in the app.
-- These policies scope all client-visible rows to the authenticated owner.

create table if not exists public.agent_activity (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    event_type text not null check (event_type in ('system', 'ai', 'bulk')),
    message text not null check (char_length(message) between 1 and 300),
    created_at timestamptz not null default now()
);

create index if not exists agent_activity_owner_time_idx
    on public.agent_activity (user_id, created_at desc);

alter table public.agent_activity enable row level security;
revoke all on table public.agent_activity from public, anon, authenticated;
grant select, insert, update on table public.agent_activity to authenticated;

drop policy if exists "read own agent activity" on public.agent_activity;
create policy "read own agent activity"
    on public.agent_activity for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "insert own agent activity" on public.agent_activity;
create policy "insert own agent activity"
    on public.agent_activity for insert to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "update own agent activity" on public.agent_activity;
create policy "update own agent activity"
    on public.agent_activity for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create table if not exists public.daily_analytics (
    user_id uuid not null references auth.users(id) on delete cascade,
    sales_date date not null,
    currency text not null check (char_length(currency) between 1 and 8),
    orders_count integer not null check (orders_count >= 0),
    gross_sales numeric(16, 2) not null check (gross_sales >= 0),
    updated_at timestamptz not null default now(),
    primary key (user_id, sales_date, currency)
);

create index if not exists daily_analytics_owner_date_idx
    on public.daily_analytics (user_id, sales_date desc);

alter table public.daily_analytics enable row level security;
revoke all on table public.daily_analytics from public, anon, authenticated;
grant select, insert, update on table public.daily_analytics to authenticated;

drop policy if exists "read own daily analytics" on public.daily_analytics;
create policy "read own daily analytics"
    on public.daily_analytics for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "insert own daily analytics" on public.daily_analytics;
create policy "insert own daily analytics"
    on public.daily_analytics for insert to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "update own daily analytics" on public.daily_analytics;
create policy "update own daily analytics"
    on public.daily_analytics for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);
