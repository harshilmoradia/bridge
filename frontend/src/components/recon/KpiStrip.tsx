import type { ReactNode } from 'react';
import type { Run, Statement } from '../../api/types';
import { useCountUp } from '../../hooks/useCountUp';
import { cn } from '../../lib/utils';
import { closedPercent, isZeroMoney } from '../../lib/workspace';
import { Money } from '../Money';

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub: ReactNode }) {
    return (
        <div className="flex min-w-0 flex-col gap-1 bg-card px-4 py-3.5">
            <span className="eyebrow">{label}</span>
            <span className="text-xl font-semibold tabular-nums">{value}</span>
            <span className="text-xs text-muted-foreground">{sub}</span>
        </div>
    );
}

// The headline numbers of the workspace. The difference counts toward zero as items are approved and turns green at 0.00.
export function KpiStrip({ statement: s, run, pending }: { statement: Statement; run: Run | undefined; pending: number }) {
    const shown = useCountUp(s.unreconciled_difference);
    const balanced = isZeroMoney(s.unreconciled_difference) && shown === s.unreconciled_difference;
    const percent = closedPercent(s.raw_difference, s.unreconciled_difference);
    const finished = run?.status === 'completed';
    const policy = run ? run.counts.auto_resolved + run.counts.reconciling_item : 0;
    return (
        <section aria-label="Reconciliation summary" className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border shadow-card lg:grid-cols-[1.5fr_repeat(4,1fr)]">
            <div className="col-span-2 flex min-w-0 flex-col gap-1 bg-card px-4 py-3.5 lg:col-span-1">
                <span className="eyebrow">Unreconciled difference</span>
                <strong data-testid="kpi-difference" data-balanced={balanced} aria-live="polite" className="text-3xl leading-tight font-semibold tabular-nums">
                    <Money value={shown} className={balanced ? 'text-good' : 'text-foreground'} />
                </strong>
                <span className="text-xs text-muted-foreground">
                    {balanced ? 'Reconciled. Bank and book agree.' : <>Started at <Money value={s.raw_difference} className="text-muted-foreground" /> · closes as you approve</>}
                </span>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Difference closed" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
                    <i className={cn('block h-full rounded-full transition-[width] duration-700', balanced ? 'bg-good' : 'bg-primary')} style={{ width: `${percent}%` }} />
                </div>
            </div>
            <Tile label="Bank balance" value={<Money value={s.bank.closing_balance} className="text-foreground" />} sub={<>Closing, {s.period_end}</>} />
            <Tile label="Book balance" value={<Money value={s.book.adjusted_balance} className="text-foreground" />} sub={<>GL {s.cash_account} adjusted</>} />
            <Tile label="Matched" value={finished ? run.counts.matched : '—'} sub={finished ? `match groups · ${policy} closed by policy` : 'Run the agents to match'} />
            <Tile label="Needs you" value={<span className={cn(pending > 0 && 'text-warn')}>{run ? pending : '—'}</span>}
                sub={!run ? 'Nothing yet' : pending > 0 ? 'Draft entries waiting' : 'All caught up'} />
        </section>
    );
}
