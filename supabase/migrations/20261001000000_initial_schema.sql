-- Autonomous Quant Trader — initial schema.
-- Bulk historical market data lives in Parquet + DuckDB, NOT here. Postgres stores metadata,
-- strategies, experiments, decisions, orders and metrics.
--
-- Security model:
--   * RLS is enabled on every table.
--   * Python services (research, trader) write with the service_role key, which bypasses RLS.
--   * The dashboard (authenticated users) is read-only, except the `configuration` table
--     (aggressiveness slider, kill switch) — every change is audited by trigger.
--   * The AI analyst writes only to ai_reviews / ai_hypotheses / lessons via its own role and
--     never has access to broker secrets, order placement or risk configuration.
--
-- Safe to re-run: every object is created idempotently, and a preflight check aborts with a
-- clear message if a table with one of our names already exists but was not created by this
-- migration (our tables are marked with COMMENT 'aqt').

begin;

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------- preflight
do $$
declare
    t text;
    conflicts text[] := '{}';
begin
    foreach t in array array[
        'strategies',
        'strategy_versions',
        'strategy_promotions',
        'experiments',
        'backtests',
        'walk_forward_runs',
        'paper_runs',
        'market_regimes',
        'signals',
        'orders',
        'fills',
        'positions',
        'portfolio_snapshots',
        'risk_events',
        'daily_metrics',
        'hypotheses',
        'trade_reviews',
        'lessons',
        'ai_reviews',
        'ai_hypotheses',
        'configuration',
        'config_audit_log'
    ] loop
        if to_regclass('public.' || t) is not null
           and coalesce(obj_description(to_regclass('public.' || t), 'pg_class'), '') <> 'aqt' then
            conflicts := conflicts || t;
        end if;
    end loop;
    if array_length(conflicts, 1) > 0 then
        raise exception 'Tablas ya existentes que no pertenecen a Autonomous Quant Trader: %', conflicts
            using hint = 'Usa un proyecto Supabase vacío o renombra/elimina esas tablas antes de aplicar la migración.';
    end if;
end;
$$;

-- ---------------------------------------------------------------------------- strategies
create table if not exists public.strategies (
    id              uuid primary key default gen_random_uuid(),
    name            text not null unique,
    family          text not null,
    description     text,
    status          text not null default 'research'
                    check (status in ('research', 'challenger', 'paper', 'champion', 'retired')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table if not exists public.strategy_versions (
    id              uuid primary key default gen_random_uuid(),
    strategy_id     uuid not null references public.strategies (id) on delete cascade,
    version         integer not null,
    config_hash     text not null,
    spec            jsonb not null,           -- Strategy DSL
    params          jsonb not null default '{}',
    created_by      text not null default 'research_engine',
    created_at      timestamptz not null default now(),
    unique (strategy_id, version),
    unique (config_hash)
);

create table if not exists public.strategy_promotions (
    id                  uuid primary key default gen_random_uuid(),
    strategy_version_id uuid not null references public.strategy_versions (id),
    from_status         text not null,
    to_status           text not null,
    evidence            jsonb not null,       -- OOS, walk-forward, paper results, comparison
    approved_by         text not null,
    created_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------------------- research
create table if not exists public.experiments (
    id              uuid primary key default gen_random_uuid(),
    hypothesis_id   uuid,
    name            text not null,
    symbol_universe text[] not null default '{}',
    timeframe       text not null,
    n_hypotheses    integer not null default 1,
    fdr_q           numeric,
    config          jsonb not null default '{}',
    data_hash       text,
    code_version    text,
    status          text not null default 'running'
                    check (status in ('running', 'completed', 'failed')),
    started_at      timestamptz not null default now(),
    finished_at     timestamptz
);

create table if not exists public.backtests (
    id                  uuid primary key default gen_random_uuid(),
    experiment_id       uuid references public.experiments (id) on delete cascade,
    strategy_version_id uuid references public.strategy_versions (id),
    symbol              text not null,
    timeframe           text not null,
    sample              text not null check (sample in ('in_sample', 'out_of_sample', 'full')),
    period_start        timestamptz not null,
    period_end          timestamptz not null,
    n_trades            integer not null,
    win_rate            numeric,
    avg_win             numeric,
    avg_loss            numeric,
    expected_value      numeric,
    profit_factor       numeric,
    max_drawdown        numeric,
    sharpe              numeric,
    sortino             numeric,
    p_value             numeric,
    adjusted_p_value    numeric,
    edge_score          numeric,
    costs               jsonb not null default '{}',
    report              jsonb not null default '{}',
    created_at          timestamptz not null default now()
);

create table if not exists public.walk_forward_runs (
    id                  uuid primary key default gen_random_uuid(),
    experiment_id       uuid references public.experiments (id) on delete cascade,
    strategy_id         uuid references public.strategies (id),
    n_windows           integer not null,
    anchored            boolean not null default true,
    oos_trades          integer not null,
    oos_ev              numeric,
    efficiency          numeric,
    windows             jsonb not null default '[]',
    created_at          timestamptz not null default now()
);

create table if not exists public.paper_runs (
    id                  uuid primary key default gen_random_uuid(),
    strategy_version_id uuid references public.strategy_versions (id),
    portfolio_kind      text not null default 'shadow'
                        check (portfolio_kind in ('real', 'shadow', 'paper', 'benchmark')),
    label               text not null,        -- champion / challenger_a / buy_and_hold / cash
    started_at          timestamptz not null default now(),
    ended_at            timestamptz,
    metrics             jsonb not null default '{}'
);

create table if not exists public.market_regimes (
    id              bigint generated always as identity primary key,
    symbol          text not null,
    timeframe       text not null,
    ts              timestamptz not null,
    trend_regime    text,
    vol_regime      text,
    regime          text,
    unique (symbol, timeframe, ts)
);

-- ---------------------------------------------------------------------------- trading
create table if not exists public.signals (
    id                  uuid primary key default gen_random_uuid(),
    strategy_version_id uuid references public.strategy_versions (id),
    symbol              text not null,
    side                text not null check (side in ('BUY', 'SELL')),
    entry_price         numeric not null,
    stop_price          numeric,
    target_price        numeric,
    edge_score          numeric,
    evidence            jsonb not null default '{}',
    -- Every decision is logged, including NO TRADE and rejections.
    decision            text not null
                        check (decision in ('APPROVE', 'REJECT', 'ADJUST_SIZE', 'NO_TRADE')),
    risk_checks         jsonb not null default '[]',
    requested_notional  numeric,
    approved_notional   numeric,
    -- Counterfactual learning: what would have happened with the opposite decision.
    counterfactual      jsonb,
    created_at          timestamptz not null default now()
);

create table if not exists public.orders (
    id                  uuid primary key default gen_random_uuid(),
    signal_id           uuid references public.signals (id),
    client_order_id     text not null unique,   -- idempotency key
    broker              text not null,
    broker_order_id     text,
    environment         text not null check (environment in ('DEV', 'PAPER', 'LIVE')),
    symbol              text not null,
    side                text not null check (side in ('BUY', 'SELL')),
    order_type          text not null default 'MARKET',
    quantity            numeric not null check (quantity > 0),
    limit_price         numeric,
    stop_price          numeric,
    status              text not null,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create table if not exists public.fills (
    id              uuid primary key default gen_random_uuid(),
    order_id        uuid not null references public.orders (id) on delete cascade,
    quantity        numeric not null,
    price           numeric not null,
    fee             numeric not null default 0,
    fx_cost         numeric not null default 0,
    filled_at       timestamptz not null default now()
);

create table if not exists public.positions (
    id              uuid primary key default gen_random_uuid(),
    environment     text not null check (environment in ('DEV', 'PAPER', 'LIVE')),
    portfolio       text not null default 'real',
    symbol          text not null,
    quantity        numeric not null,
    avg_price       numeric not null,
    market_price    numeric,
    opened_at       timestamptz not null default now(),
    closed_at       timestamptz,
    realized_pnl    numeric
);

create table if not exists public.portfolio_snapshots (
    id              bigint generated always as identity primary key,
    environment     text not null check (environment in ('DEV', 'PAPER', 'LIVE')),
    portfolio       text not null default 'real',
    ts              timestamptz not null default now(),
    cash            numeric not null,
    equity          numeric not null,
    exposure_pct    numeric not null,
    drawdown        numeric not null,
    positions       jsonb not null default '[]'
);

create table if not exists public.risk_events (
    id              uuid primary key default gen_random_uuid(),
    severity        text not null check (severity in ('info', 'warning', 'critical')),
    kind            text not null,            -- kill_switch, reconciliation_mismatch, ...
    detail          jsonb not null default '{}',
    created_at      timestamptz not null default now()
);

create table if not exists public.daily_metrics (
    id              bigint generated always as identity primary key,
    environment     text not null,
    portfolio       text not null default 'real',
    day             date not null,
    pnl             numeric,
    pnl_pct         numeric,
    trades          integer not null default 0,
    rejected        integer not null default 0,
    metrics         jsonb not null default '{}',
    unique (environment, portfolio, day)
);

-- ---------------------------------------------------------------------------- learning / AI
create table if not exists public.hypotheses (
    id              uuid primary key default gen_random_uuid(),
    source          text not null default 'human' check (source in ('human', 'ai', 'research')),
    claim           text not null,
    evidence_level  text check (evidence_level in ('low', 'medium', 'high')),
    suggested_experiment text,
    status          text not null default 'open'
                    check (status in ('open', 'testing', 'confirmed', 'rejected')),
    created_at      timestamptz not null default now()
);

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'experiments_hypothesis_fk') then
        alter table public.experiments
            add constraint experiments_hypothesis_fk
            foreign key (hypothesis_id) references public.hypotheses (id);
    end if;
end;
$$;

create table if not exists public.trade_reviews (
    id              uuid primary key default gen_random_uuid(),
    signal_id       uuid references public.signals (id),
    order_id        uuid references public.orders (id),
    outcome         jsonb not null default '{}',
    review          text,
    created_at      timestamptz not null default now()
);

create table if not exists public.lessons (
    id              uuid primary key default gen_random_uuid(),
    title           text not null,
    body            text not null,
    source          text not null default 'ai',
    related         jsonb not null default '{}',
    created_at      timestamptz not null default now()
);

create table if not exists public.ai_reviews (
    id              uuid primary key default gen_random_uuid(),
    kind            text not null,            -- daily_trade_review, degradation_analysis, ...
    model           text not null,
    input_ref       jsonb not null default '{}',
    output          jsonb not null,           -- structured output only
    cost_usd        numeric,
    created_at      timestamptz not null default now()
);

create table if not exists public.ai_hypotheses (
    id              uuid primary key default gen_random_uuid(),
    ai_review_id    uuid references public.ai_reviews (id),
    hypothesis_id   uuid references public.hypotheses (id),
    claim           text not null,
    evidence_level  text,
    suggested_experiment text,
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------- configuration
create table if not exists public.configuration (
    environment         text primary key check (environment in ('DEV', 'PAPER', 'LIVE')),
    aggressiveness      numeric not null default 20 check (aggressiveness between 0 and 100),
    kill_switch         boolean not null default false,
    live_trading_enabled boolean not null default false,
    settings            jsonb not null default '{}',
    updated_by          uuid,
    updated_at          timestamptz not null default now()
);

insert into public.configuration (environment) values ('DEV'), ('PAPER'), ('LIVE')
    on conflict (environment) do nothing;

create table if not exists public.config_audit_log (
    id              bigint generated always as identity primary key,
    table_name      text not null,
    row_key         text,
    action          text not null,
    old_row         jsonb,
    new_row         jsonb,
    actor           uuid,
    created_at      timestamptz not null default now()
);

create or replace function public.audit_configuration() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    new.updated_at := now();
    new.updated_by := auth.uid();
    insert into public.config_audit_log (table_name, row_key, action, old_row, new_row, actor)
    values ('configuration', new.environment, tg_op, to_jsonb(old), to_jsonb(new), auth.uid());
    return new;
end;
$$;

drop trigger if exists configuration_audit on public.configuration;
create trigger configuration_audit
    before update on public.configuration
    for each row execute function public.audit_configuration();

-- ---------------------------------------------------------------------------- indexes
create index if not exists signals_created_at_idx on public.signals (created_at desc);
create index if not exists signals_symbol_created_at_idx on public.signals (symbol, created_at desc);
create index if not exists orders_status_idx on public.orders (status);
create index if not exists portfolio_snapshots_environment_portfolio_ts_idx on public.portfolio_snapshots (environment, portfolio, ts desc);
create index if not exists backtests_strategy_version_id_idx on public.backtests (strategy_version_id);
create index if not exists risk_events_created_at_idx on public.risk_events (created_at desc);

-- ---------------------------------------------------------------------------- RLS
do $$
declare t text;
begin
    foreach t in array array[
        'strategies', 'strategy_versions', 'strategy_promotions', 'experiments', 'backtests',
        'walk_forward_runs', 'paper_runs', 'market_regimes', 'signals', 'orders', 'fills',
        'positions', 'portfolio_snapshots', 'risk_events', 'daily_metrics', 'hypotheses',
        'trade_reviews', 'lessons', 'ai_reviews', 'ai_hypotheses', 'configuration', 'config_audit_log'
    ] loop
        execute format('alter table public.%I enable row level security', t);
        execute format('comment on table public.%I is %L', t, 'aqt');
        execute format('drop policy if exists "authenticated read" on public.%I', t);
        execute format(
            'create policy "authenticated read" on public.%I for select to authenticated using (true)',
            t
        );
    end loop;
end;
$$;

-- Dashboard may change the slider / kill switch. It can never enable LIVE trading:
-- that requires the runtime env flags as well, and this column is not writable here.
drop policy if exists "authenticated update configuration" on public.configuration;
create policy "authenticated update configuration" on public.configuration
    for update to authenticated using (true) with check (true);
revoke update on public.configuration from authenticated;
grant update (aggressiveness, kill_switch) on public.configuration to authenticated;

commit;
