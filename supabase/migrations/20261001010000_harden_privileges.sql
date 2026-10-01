-- Defence in depth on top of RLS (idempotent, safe to re-run).
--
-- * The audit trigger function must not be callable through /rest/v1/rpc.
--   (Trigger execution does not require EXECUTE on the function.)
-- * Supabase grants broad table privileges to anon/authenticated by default; RLS already
--   blocks writes, but we also remove the grants so a future policy mistake cannot open them.
--   anon gets nothing; authenticated keeps SELECT, plus UPDATE on the two dashboard columns.

begin;

revoke execute on function public.audit_configuration() from public, anon, authenticated;

do $$
declare t text;
begin
    foreach t in array array[
        'strategies', 'strategy_versions', 'strategy_promotions', 'experiments', 'backtests',
        'walk_forward_runs', 'paper_runs', 'market_regimes', 'signals', 'orders', 'fills',
        'positions', 'portfolio_snapshots', 'risk_events', 'daily_metrics', 'hypotheses',
        'trade_reviews', 'lessons', 'ai_reviews', 'ai_hypotheses', 'configuration',
        'config_audit_log'
    ] loop
        if to_regclass('public.' || t) is not null then
            if exists (select 1 from pg_roles where rolname = 'anon') then
                execute format('revoke all on public.%I from anon', t);
            end if;
            execute format(
                'revoke insert, update, delete, truncate, references, trigger on public.%I from authenticated',
                t
            );
            execute format('grant select on public.%I to authenticated', t);
        end if;
    end loop;
end;
$$;

grant update (aggressiveness, kill_switch) on public.configuration to authenticated;

commit;
