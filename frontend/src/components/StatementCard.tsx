import { Link } from 'react-router';
import type { Statement, StatementLine, StatementSide } from '../api/types';
import { Money } from './Money';
import { StatusChip } from './StatusChip';
import { useCountUp } from '../hooks/useCountUp';
import { isZeroMoney } from '../lib/workspace';
import { cn } from '../lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

function Lines({ title, lines }: { title: string; lines: StatementLine[] }) {
    return (
        <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
            {lines.length === 0 ? <p className="text-sm text-muted-foreground">None yet</p> : (
                <ul className="space-y-1 text-sm">
                    {lines.map(line => (
                        <li key={line.item_id} data-item-id={line.item_id} className={`flex items-center justify-between gap-3 ${line.applied ? '' : 'opacity-70'}`}>
                            <span className="flex min-w-0 items-center gap-2"><span className="truncate">{line.label}{!line.applied && <span className="sr-only"> (pending)</span>}</span><StatusChip status={line.status} /></span>
                            <Money value={line.amount} />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function Side({ title, linesTitle, side, testId }: { title: string; linesTitle: string; side: StatementSide; testId: string }) {
    return (
        <Card data-testid={testId}>
            <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
                <p className="flex justify-between text-sm"><span>Closing balance</span><Money value={side.closing_balance} /></p>
                <Lines title={linesTitle} lines={side.lines} />
                <p className="flex justify-between border-t pt-2 text-sm font-medium"><span>Adjusted balance</span><Money value={side.adjusted_balance} /></p>
            </CardContent>
        </Card>
    );
}

// The difference counts up/down between values and turns green at 0.00.
function Difference({ value }: { value: string }) {
    const shown = useCountUp(value);
    const balanced = isZeroMoney(value) && shown === value;
    return (
        <strong data-testid="unreconciled" data-balanced={balanced} aria-live="polite"
            className={cn('text-base transition-colors', balanced && 'text-emerald-600 dark:text-emerald-400')}>
            <Money value={shown} className={balanced ? 'text-emerald-600 dark:text-emerald-400' : undefined} />
        </strong>
    );
}

// Live view of GET /statement: bank side, book side, raw and unreconciled difference. The parent refetches it as items resolve.
export function StatementCard({ statement: s }: { statement: Statement }) {
    return (
        <div className="space-y-3" data-testid="statement-card">
            <p className="text-sm text-muted-foreground">{s.company} · cash account {s.cash_account} · {s.period_start} to {s.period_end}</p>
            <div className="grid gap-4 md:grid-cols-2">
                <Side title="Bank side" linesTitle="Reconciling items" side={s.bank} testId="statement-bank" />
                <Side title="Book side" linesTitle="Adjustments" side={s.book} testId="statement-book" />
            </div>
            <Card>
                <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-2 pt-4 text-sm">
                    <p>Raw difference <strong data-testid="raw-difference"><Money value={s.raw_difference} /></strong></p>
                    <p>Unreconciled difference <Difference value={s.unreconciled_difference} /></p>
                    {s.run_id && <p className="ml-auto"><Link className="text-primary underline" to={`/runs/${s.run_id}`}>Run</Link> · <Link className="text-primary underline" to={`/report/${s.run_id}`}>Report</Link></p>}
                </CardContent>
            </Card>
        </div>
    );
}
