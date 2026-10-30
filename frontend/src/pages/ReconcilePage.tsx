import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronDown, Play } from 'lucide-react';
import { toast } from 'sonner';
import { ApprovalInbox } from '../components/recon/ApprovalInbox';
import { useBankTransactions, useCreateRun, useDatasets, useGlEntries, useRun, useRunItems, useStatement } from '../api/hooks';
import { keys } from '../api/keys';
import type { Dataset, EvidenceRef, Item } from '../api/types';
import { QueryState } from '../components/QueryState';
import { StatementCard } from '../components/StatementCard';
import { KpiStrip } from '../components/recon/KpiStrip';
import { ResetDemoButton } from '../components/recon/ResetDemoButton';
import { LearnedRulesButton } from '../components/LearnedRules';
import { RunPipeline } from '../components/recon/RunPipeline';
import { TransactionTable } from '../components/recon/TransactionTable';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { bankToRow, glToRow, type TxRow } from '../lib/tableModel';
import { defaultRange, isRunActive, itemsSignature, needsApproval, nextHighlight, shouldRefreshOnComplete } from '../lib/workspace';
import { Page } from './Pages';

const field = 'h-8 rounded-md border bg-card px-2 text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';

function Workspace({ datasets }: { datasets: Dataset[] }) {
    const client = useQueryClient();
    const [datasetId, setDatasetId] = useState(datasets[0].id);
    const dataset = datasets.find(d => d.id === datasetId) ?? datasets[0];
    const [range, setRange] = useState<{ from: string; to: string } | null>(null);
    const { from, to } = range ?? defaultRange(dataset);
    const [startedRunId, setStartedRunId] = useState<string | null>(null);
    const [highlight, setHighlight] = useState<string | null>(null);

    const statement = useStatement(dataset.id);
    // A reset deletes the run; the statement may still name it until it refetches, so that id stays dismissed.
    const [dismissedRunId, setDismissedRunId] = useState<string | null>(null);
    const statementRunId = statement.data?.run_id && statement.data.run_id !== dismissedRunId ? statement.data.run_id : undefined;
    const runId = startedRunId ?? statementRunId;
    const run = useRun(runId);
    const items = useRunItems(runId);
    const bank = useBankTransactions({ dataset: dataset.id, from, to });
    const gl = useGlEntries({ dataset: dataset.id, from, to });
    const createRun = useCreateRun();
    const running = createRun.isPending || isRunActive(run.data?.status);

    const refreshLedgerViews = useCallback(
        () => Promise.all([keys.statements, keys.banks, keys.gls].map(queryKey => client.invalidateQueries({ queryKey }))),
        [client],
    );

    // Live statement: refetch when a run completes, and when any item changes status.
    const refreshedRunId = useRef<string | null>(null);
    useEffect(() => {
        if (shouldRefreshOnComplete(startedRunId, run.data?.id, run.data?.status, refreshedRunId.current)) {
            refreshedRunId.current = run.data?.id ?? null;
            void refreshLedgerViews();
            void client.invalidateQueries({ queryKey: keys.runItems });
        }
    }, [startedRunId, run.data?.id, run.data?.status, client, refreshLedgerViews]);
    const signature = useMemo(() => (items.data ? itemsSignature(items.data) : null), [items.data]);
    const lastSignature = useRef<string | null>(null);
    useEffect(() => {
        if (signature !== null && lastSignature.current !== null && signature !== lastSignature.current) void refreshLedgerViews();
        if (signature !== null) lastSignature.current = signature;
    }, [signature, refreshLedgerViews]);

    const start = () => {
        setHighlight(null);
        createRun.mutate({ dataset: dataset.id, period_start: from, period_end: to }, {
            onSuccess: created => {
                refreshedRunId.current = null;
                setStartedRunId(created.id);
                void client.invalidateQueries({ queryKey: keys.run(created.id) });
                void refreshLedgerViews();
                void client.invalidateQueries({ queryKey: keys.runItems });
            },
            onError: error => toast.error(error.message),
        });
    };

    const bankRows = useMemo(() => (bank.data ?? []).map(bankToRow), [bank.data]);
    const glRows = useMemo(() => (gl.data ?? []).map(glToRow), [gl.data]);
    const rowsById = useMemo(() => new Map<string, TxRow>([...bankRows, ...glRows].map(r => [r.id, r])), [bankRows, glRows]);

    const onEvidence = (item: Item, evidence: EvidenceRef) => {
        setHighlight(item.id);
        requestAnimationFrame(() => document.querySelector(`[data-row-id="${CSS.escape(evidence.id)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    };
    const onRowClick = (row: TxRow) => setHighlight(current => nextHighlight(current, row.itemId));
    const pending = needsApproval(items.data ?? []);
    const reviewable = (items.data ?? []).filter(i => i.status !== 'matched');
    const report = run.data?.status === 'completed'
        ? <Button asChild className="mt-2"><Link to={`/report/${encodeURIComponent(run.data.id)}`}>Open report</Link></Button>
        : null;

    const controls = (
        <div className="flex flex-wrap items-end gap-2" role="group" aria-label="Run controls">
            {datasets.length > 1 && (
                <label className="flex flex-col gap-0.5 text-[11px] text-faint">Dataset
                    <select className={field} value={dataset.id} disabled={running} onChange={e => { setDatasetId(e.target.value); setRange(null); setStartedRunId(null); setHighlight(null); }}>
                        {datasets.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
                    </select>
                </label>
            )}
            <label className="flex flex-col gap-0.5 text-[11px] text-faint">From
                <input type="date" className={field} value={from} max={to} disabled={running} onChange={e => e.target.value && setRange({ from: e.target.value, to })} />
            </label>
            <label className="flex flex-col gap-0.5 text-[11px] text-faint">To
                <input type="date" className={field} value={to} min={from} disabled={running} onChange={e => e.target.value && setRange({ from, to: e.target.value })} />
            </label>
            <LearnedRulesButton />
            <ResetDemoButton disabled={running} onReset={() => { setDismissedRunId(runId ?? null); setStartedRunId(null); setHighlight(null); lastSignature.current = null; refreshedRunId.current = null; }} />
            <Button size="lg" className="px-4 font-semibold" disabled={running} onClick={start}><Play className="fill-current" aria-hidden="true" />{running ? 'Running…' : 'Run agents'}</Button>
        </div>
    );

    return (
        <Page title="Bank reconciliation" subtitle="Agents match what they can. You review the items they could not close." actions={controls}>
            <QueryState query={statement}>{s => <KpiStrip statement={s} run={run.data} pending={pending.length} />}</QueryState>

            {!runId && (
                <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-10 text-center">
                    <h2 className="text-base font-semibold">No run yet</h2>
                    <p className="max-w-[52ch] text-sm text-muted-foreground">Run the agents to match the bank statement to the ledger. Anything policy does not allow them to close lands in your approval queue with a draft entry.</p>
                    <Button className="mt-1" disabled={running} onClick={start}><Play className="fill-current" aria-hidden="true" />Run agents</Button>
                </div>
            )}
            {runId && run.isPending && <div role="status" aria-label="Loading run" className="space-y-2"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-24 w-full" /></div>}
            {run.data && <RunPipeline run={run.data} />}
            {run.isError && (
                <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
                    Could not load the run: {run.error.message}
                    <Button variant="outline" size="sm" onClick={() => void run.refetch()}>Try again</Button>
                </div>
            )}

            {runId && (
                <QueryState query={items}>
                    {() => <ApprovalInbox items={reviewable} rows={rowsById} onSelect={item => setHighlight(item.id)} onEvidence={onEvidence} footer={report} />}
                </QueryState>
            )}

            <details className="group rounded-lg border bg-card shadow-card">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
                    Statement detail
                    <span className="font-normal text-muted-foreground">Bank side, book side and every reconciling line</span>
                    <ChevronDown className="ml-auto size-4 transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <div className="border-t p-4"><QueryState query={statement}>{s => <StatementCard statement={s} />}</QueryState></div>
            </details>

            <div className="grid gap-4 xl:grid-cols-2">
                <section aria-label="Bank transactions" className="min-w-0 rounded-lg border bg-card shadow-card">
                    <h2 className="border-b px-4 py-3 text-sm font-semibold">Bank</h2>
                    <QueryState query={bank} isEmpty={list => list.length === 0} emptyMessage="No bank transactions in this range.">
                        {() => <TransactionTable rows={bankRows} typeLabel="Type" selectable={false} highlightItemId={highlight} onRowClick={onRowClick} />}
                    </QueryState>
                </section>
                <section aria-label="Ledger entries" className="min-w-0 rounded-lg border bg-card shadow-card">
                    <h2 className="border-b px-4 py-3 text-sm font-semibold">Ledger</h2>
                    <QueryState query={gl} isEmpty={list => list.length === 0} emptyMessage="No ledger entries in this range.">
                        {() => <TransactionTable rows={glRows} typeLabel="Method" selectable={false} highlightItemId={highlight} onRowClick={onRowClick} />}
                    </QueryState>
                </section>
            </div>
        </Page>
    );
}

export function ReconcilePage() {
    const datasets = useDatasets();
    return (
        <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
            {list => <Workspace datasets={list} />}
        </QueryState>
    );
}
