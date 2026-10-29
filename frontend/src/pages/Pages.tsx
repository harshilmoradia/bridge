import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { QueryState } from '../components/QueryState';
import { Badge } from '../components/ui/badge';
import { Card, CardContent } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { useBankTransactions, useDatasets, useGlEntries, useRun, useStatement } from '../api/hooks';
import type { Dataset } from '../api/types';
import { Money } from '../components/Money';
import { TransactionTable } from '../components/recon/TransactionTable';
import { bankToRow, glToRow } from '../lib/tableModel';

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children?: ReactNode }) {
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

// The demo ships one dataset; every page works on the first one the API lists.
function useDataset() {
    const query = useDatasets();
    return { query, dataset: query.data?.[0] as Dataset | undefined };
}

export function BankPage() {
    const { query: datasets, dataset } = useDataset();
    const rows = useBankTransactions(dataset && { dataset: dataset.id, from: dataset.period_start, to: dataset.period_end });
    return (
        <Page title="Bank transactions" subtitle={dataset?.label}>
            <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
                {() => (
                    <QueryState query={rows} isEmpty={list => list.length === 0} emptyMessage="No bank transactions in this period.">
                        {list => <TransactionTable rows={list.map(bankToRow)} typeLabel="Type" />}
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
                        {list => <TransactionTable rows={list.map(glToRow)} typeLabel="Method" />}
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
