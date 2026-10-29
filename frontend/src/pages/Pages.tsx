import { lazy, Suspense, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { QueryState } from '../components/QueryState';
import { Card, CardContent } from '../components/ui/card';
import { Skeleton } from '../components/ui/skeleton';
import { useBankTransactions, useDatasets, useGlEntries, useRun, useStatement } from '../api/hooks';
import type { Dataset, Run } from '../api/types';
import { reportView } from '../lib/report';
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

const ReportMarkdown = lazy(() => import('../components/ReportMarkdown'));

export function ReportBody({ run }: { run: Run }) {
    const view = reportView(run);
    if (view === 'failed') {
        return <p role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{run.error?.message ?? 'The run failed, so there is no report.'}</p>;
    }
    if (view === 'waiting') return <p role="status" className="text-sm text-muted-foreground">Report will appear when the run completes.</p>;
    if (view === 'empty') return <p className="text-sm text-muted-foreground">This run finished without a report.</p>;
    const template = run.steps.some(s => s.agent === 'report' && s.status === 'failed');
    return (
        <div className="space-y-2">
            {run.status === 'failed' && run.error && <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">{run.error.message}</p>}
            {template && <p className="text-xs text-muted-foreground">Template report: the report step failed, so this was written by code instead of the model. See the trace for why.</p>}
            <Card><CardContent className="pt-4">
                <Suspense fallback={<div role="status" aria-label="Loading report" className="space-y-2"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /></div>}>
                    <ReportMarkdown source={run.report ?? ''} />
                </Suspense>
            </CardContent></Card>
        </div>
    );
}

export function ReportPage() {
    const { runId } = useParams<{ runId: string }>();
    const run = useRun(runId);
    const { query: datasets, dataset } = useDataset();
    const statement = useStatement(dataset?.id, runId);
    return (
        <Page title="Report" subtitle={runId} actions={runId && <Link to={`/runs/${encodeURIComponent(runId)}`} className="text-sm font-medium text-primary underline">View trace</Link>}>
            <QueryState query={run}>{r => <ReportBody run={r} />}</QueryState>
            <QueryState query={datasets}>
                {() => dataset && (
                    <QueryState query={statement}>
                        {s => <p className="text-sm">Unreconciled difference <Money value={s.unreconciled_difference} /></p>}
                    </QueryState>
                )}
            </QueryState>
        </Page>
    );
}

export const NotFoundPage = () => (
    <Page title="Page not found">
        <Link to="/reconcile" className="text-sm font-medium text-primary underline">Back to Reconcile</Link>
    </Page>
);
