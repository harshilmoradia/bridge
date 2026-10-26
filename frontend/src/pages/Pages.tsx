import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import { QueryState } from '../components/QueryState';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import {
    useBankTransactions, useCreateRun, useDatasets, useDecideItem, useGlEntries, useResetDemo, useRun, useRunItems, useStatement,
} from '../api/hooks';
import type { Dataset, Item, ReconStatus, StatementLine } from '../api/types';
import { formatMoney, isNegative } from '../lib/money';
import { cn } from '../lib/utils';

function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children?: ReactNode }) {
    return (
        <section className="space-y-4">
            <header className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
                    {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
                </div>
                {actions}
            </header>
            {children}
        </section>
    );
}

const Money = ({ value }: { value: string }) => (
    <span className={cn('tabular-nums', isNegative(value) && 'text-red-600 dark:text-red-400')}>{formatMoney(value)}</span>
);

const StatusBadge = ({ status }: { status: ReconStatus }) => (
    <Badge variant={status === 'needs_approval' || status === 'rejected' ? 'destructive' : status === 'unmatched' ? 'outline' : 'secondary'}>
        {status.replaceAll('_', ' ')}
    </Badge>
);

// The demo ships one dataset; every page works on the first one the API lists.
function useDataset() {
    const query = useDatasets();
    return { query, dataset: query.data?.[0] as Dataset | undefined };
}

function Lines({ title, lines }: { title: string; lines: StatementLine[] }) {
    return (
        <div>
            <h3 className="mb-1 text-sm font-medium">{title}</h3>
            {lines.length === 0 ? <p className="text-sm text-muted-foreground">None</p> : (
                <ul className="space-y-1 text-sm">
                    {lines.map(line => (
                        <li key={line.item_id} className="flex justify-between gap-4">
                            <span className="truncate text-muted-foreground">{line.label}{line.applied ? '' : ' (pending)'}</span><Money value={line.amount} />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function ItemRow({ item }: { item: Item }) {
    const decide = useDecideItem();
    const canDecide = item.status === 'needs_approval';
    const submit = (decision: 'approve' | 'reject') =>
        decide.mutate({ itemId: item.id, decision, remember: false, note: '' }, {
            onSuccess: () => toast.success(`${item.id} ${decision === 'approve' ? 'approved' : 'rejected'}`),
            onError: error => toast.error(error.message),
        });
    return (
        <TableRow>
            <TableCell className="font-mono text-xs">{item.id}</TableCell>
            <TableCell>{item.kind.replaceAll('_', ' ')}</TableCell>
            <TableCell className="max-w-md whitespace-normal text-muted-foreground">{item.reasoning}</TableCell>
            <TableCell className="text-right"><Money value={item.amount_delta} /></TableCell>
            <TableCell><StatusBadge status={item.status} /></TableCell>
            <TableCell className="text-right">
                {canDecide && (
                    <span className="inline-flex gap-1">
                        <Button size="sm" disabled={decide.isPending} onClick={() => submit('approve')}>Approve</Button>
                        <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => submit('reject')}>Reject</Button>
                    </span>
                )}
            </TableCell>
        </TableRow>
    );
}

function ItemsTable({ runId }: { runId: string }) {
    const query = useRunItems(runId);
    return (
        <QueryState query={query} isEmpty={items => items.length === 0} emptyMessage="No items for this run.">
            {items => (
                <Table>
                    <TableHeader>
                        <TableRow><TableHead>Item</TableHead><TableHead>Kind</TableHead><TableHead>Reasoning</TableHead><TableHead className="text-right">Delta</TableHead><TableHead>Status</TableHead><TableHead /></TableRow>
                    </TableHeader>
                    <TableBody>{items.map(item => <ItemRow key={item.id} item={item} />)}</TableBody>
                </Table>
            )}
        </QueryState>
    );
}

export function ReconcilePage() {
    const { query: datasets, dataset } = useDataset();
    const statement = useStatement(dataset?.id);
    const createRun = useCreateRun();
    const navigate = useNavigate();
    const reset = useResetDemo();
    const start = () => dataset && createRun.mutate(
        { dataset: dataset.id, period_start: dataset.period_start, period_end: dataset.period_end },
        { onSuccess: run => { toast.success("Run started"); void navigate(`/runs/${run.id}`); }, onError: error => toast.error(error.message) },
    );
    return (
        <Page title="Reconcile" subtitle={dataset?.label}
            actions={
                <span className="flex gap-2">
                    <Button variant="outline" disabled={reset.isPending} onClick={() => reset.mutate(undefined, { onSuccess: () => toast.success('Demo reset') })}>Reset demo</Button>
                    <Button disabled={!dataset || createRun.isPending} onClick={start}>Run reconciliation</Button>
                </span>
            }>
            <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
                {() => (
                    <QueryState query={statement}>
                        {s => (
                            <>
                                <div className="grid gap-4 md:grid-cols-2">
                                    <Card>
                                        <CardHeader><CardTitle>Bank side</CardTitle></CardHeader>
                                        <CardContent className="space-y-3">
                                            <p className="flex justify-between text-sm"><span>Closing balance</span><Money value={s.bank.closing_balance} /></p>
                                            <Lines title="Reconciling items" lines={s.bank.lines} />
                                            <p className="flex justify-between border-t pt-2 text-sm font-medium"><span>Adjusted</span><Money value={s.bank.adjusted_balance} /></p>
                                        </CardContent>
                                    </Card>
                                    <Card>
                                        <CardHeader><CardTitle>Book side</CardTitle></CardHeader>
                                        <CardContent className="space-y-3">
                                            <p className="flex justify-between text-sm"><span>Closing balance</span><Money value={s.book.closing_balance} /></p>
                                            <Lines title="Adjustments" lines={s.book.lines} />
                                            <p className="flex justify-between border-t pt-2 text-sm font-medium"><span>Adjusted</span><Money value={s.book.adjusted_balance} /></p>
                                        </CardContent>
                                    </Card>
                                </div>
                                <p className="text-sm">
                                    Raw difference <Money value={s.raw_difference} />, unreconciled <strong data-testid="unreconciled"><Money value={s.unreconciled_difference} /></strong>
                                    {s.run_id && <> · <Link className="text-primary underline" to={`/runs/${s.run_id}`}>Run</Link> · <Link className="text-primary underline" to={`/report/${s.run_id}`}>Report</Link></>}
                                </p>
                                {s.run_id && <ItemsTable runId={s.run_id} />}
                            </>
                        )}
                    </QueryState>
                )}
            </QueryState>
        </Page>
    );
}

export function BankPage() {
    const { query: datasets, dataset } = useDataset();
    const rows = useBankTransactions(dataset && { dataset: dataset.id, from: dataset.period_start, to: dataset.period_end });
    return (
        <Page title="Bank transactions" subtitle={dataset?.label}>
            <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
                {() => (
                    <QueryState query={rows} isEmpty={list => list.length === 0} emptyMessage="No bank transactions in this period.">
                        {list => (
                            <Table>
                                <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Description</TableHead><TableHead>Type</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                                <TableBody>
                                    {list.map(r => (
                                        <TableRow key={r.txn_id}>
                                            <TableCell>{r.posted_date}</TableCell><TableCell>{r.description}</TableCell><TableCell>{r.type}</TableCell>
                                            <TableCell className="text-right"><Money value={r.amount} /></TableCell><TableCell><StatusBadge status={r.recon_status} /></TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </QueryState>
                )}
            </QueryState>
        </Page>
    );
}

export function LedgerPage() {
    const { query: datasets, dataset } = useDataset();
    const rows = useGlEntries(dataset && { dataset: dataset.id, from: dataset.period_start, to: dataset.period_end });
    return (
        <Page title="Ledger entries" subtitle={dataset?.label}>
            <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
                {() => (
                    <QueryState query={rows} isEmpty={list => list.length === 0} emptyMessage="No ledger entries in this period.">
                        {list => (
                            <Table>
                                <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Description</TableHead><TableHead>Method</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                                <TableBody>
                                    {list.map(r => (
                                        <TableRow key={r.entry_id}>
                                            <TableCell>{r.date}</TableCell><TableCell>{r.description}</TableCell><TableCell>{r.method}</TableCell>
                                            <TableCell className="text-right"><Money value={r.amount} /></TableCell><TableCell><StatusBadge status={r.recon_status} /></TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </QueryState>
                )}
            </QueryState>
        </Page>
    );
}

export function RunPage() {
    const { id } = useParams<{ id: string }>();
    const run = useRun(id);
    return (
        <Page title="Run" subtitle={id}>
            <QueryState query={run}>
                {r => (
                    <>
                        <p className="text-sm">Status <Badge variant="secondary">{r.status}</Badge> · {r.counts.matched} matched, {r.counts.reconciling_item} reconciling, {r.counts.needs_approval} need approval</p>
                        <Table>
                            <TableHeader><TableRow><TableHead>Step</TableHead><TableHead>Tier</TableHead><TableHead>Model</TableHead><TableHead className="text-right">Latency</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                            <TableBody>
                                {[...r.steps].sort((x, y) => x.position - y.position).map(step => (
                                    <TableRow key={step.id}>
                                        <TableCell>{step.position}. {step.label}</TableCell><TableCell>{step.tier}</TableCell>
                                        <TableCell className="font-mono text-xs">{step.model ?? 'code'}</TableCell>
                                        <TableCell className="text-right tabular-nums">{step.latency_ms ?? '-'} ms</TableCell><TableCell>{step.status}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </>
                )}
            </QueryState>
        </Page>
    );
}

export function ReportPage() {
    const { runId } = useParams<{ runId: string }>();
    const run = useRun(runId);
    const { dataset } = useDataset();
    const statement = useStatement(dataset?.id, runId);
    return (
        <Page title="Report" subtitle={runId}>
            <QueryState query={run}>
                {r => r.report
                    ? <Card><CardContent className="whitespace-pre-wrap pt-4 text-sm">{r.report}</CardContent></Card>
                    : <p className="text-sm text-muted-foreground">The report is not ready yet.</p>}
            </QueryState>
            {statement.data && <p className="text-sm">Unreconciled difference <Money value={statement.data.unreconciled_difference} /></p>}
        </Page>
    );
}

export const NotFoundPage = () => (
    <Page title="Page not found">
        <Link to="/reconcile" className="text-sm font-medium text-primary underline">Back to Reconcile</Link>
    </Page>
);
