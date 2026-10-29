import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApprovalDrawer } from '../components/recon/ApprovalDrawer';
import { useBankTransactions, useCreateRun, useDatasets, useGlEntries, useResetDemo, useRun, useRunItems, useStatement } from '../api/hooks';
import { keys } from '../api/keys';
import type { Dataset, EvidenceRef, Item, Run } from '../api/types';
import { Money } from '../components/Money';
import { QueryState } from '../components/QueryState';
import { StatementCard } from '../components/StatementCard';
import { StatusChip } from '../components/StatusChip';
import { TransactionTable } from '../components/recon/TransactionTable';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { cn } from '../lib/utils';
import { bankToRow, glToRow, type TxRow } from '../lib/tableModel';
import { isRunActive, itemsSignature, needsApproval, nextHighlight, shouldRefreshOnComplete } from '../lib/workspace';
import { Page } from './Pages';

const field = 'h-8 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';

function RunStatusLine({ run }: { run: Run }) {
    const total = run.steps.length;
    const done = run.steps.filter(s => s.status === 'completed').length;
    const current = run.steps.find(s => s.status === 'running');
    return (
        <div className="flex flex-wrap items-center gap-2 text-sm" role="status" data-testid="run-status" data-run-status={run.status}>
            <Badge variant="secondary">{run.status}</Badge>
            {isRunActive(run.status) && <span className="text-muted-foreground">{current ? `${current.label}...` : 'Waiting for the first step...'}</span>}
            {total > 0 && <span className="text-muted-foreground">{done} of {total} steps done</span>}
            {run.status === 'completed' && <span className="text-muted-foreground">{run.counts.matched} matched, {run.counts.auto_resolved} auto-resolved, {run.counts.needs_approval} need approval</span>}
            {run.status === 'failed' && <span className="text-destructive">{run.error?.message ?? 'The run failed.'}</span>}
        </div>
    );
}

function ItemButton({ item, active, onSelect }: { item: Item; active: boolean; onSelect: () => void }) {
    return (
        <li data-item-id={item.id}>
            <button type="button" aria-pressed={active} onClick={onSelect}
                className={cn('flex w-full flex-wrap items-center gap-2 rounded-md border px-2 py-1 text-left text-sm', active && 'border-primary bg-primary/10')}>
                <span className="font-medium">{item.kind.replaceAll('_', ' ')}</span>
                <StatusChip status={item.status} />
                <Money value={item.amount_delta} />
            </button>
        </li>
    );
}

function Workspace({ datasets }: { datasets: Dataset[] }) {
    const client = useQueryClient();
    const [datasetId, setDatasetId] = useState(datasets[0].id);
    const dataset = datasets.find(d => d.id === datasetId) ?? datasets[0];
    const [range, setRange] = useState<{ from: string; to: string } | null>(null);
    const from = range?.from ?? dataset.period_start;
    const to = range?.to ?? dataset.period_end;
    const [startedRunId, setStartedRunId] = useState<string | null>(null);
    const [highlight, setHighlight] = useState<string | null>(null);
    const [approvalOpen, setApprovalOpen] = useState(false);

    const statement = useStatement(dataset.id);
    const runId = startedRunId ?? statement.data?.run_id ?? undefined;
    const run = useRun(runId);
    const items = useRunItems(runId);
    const bank = useBankTransactions({ dataset: dataset.id, from, to });
    const gl = useGlEntries({ dataset: dataset.id, from, to });
    const createRun = useCreateRun();
    const reset = useResetDemo();
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

    const onEvidence = (item: Item, evidence: EvidenceRef) => {
        setHighlight(item.id);
        setApprovalOpen(false);
        toast(`Highlighted ${item.kind.replaceAll('_', ' ')} item for ${evidence.id}`);
    };
    const onRowClick = (row: TxRow) => setHighlight(current => nextHighlight(current, row.itemId));
    const pending = needsApproval(items.data ?? []);
    const shown = (items.data ?? []).filter(i => i.status !== 'matched');

    return (
        <>
            <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Run controls">
                <label className="flex flex-col text-xs text-muted-foreground">Dataset
                    <select className={field} value={dataset.id} disabled={running} onChange={e => { setDatasetId(e.target.value); setRange(null); setStartedRunId(null); setHighlight(null); }}>
                        {datasets.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
                    </select>
                </label>
                <label className="flex flex-col text-xs text-muted-foreground">From
                    <input type="date" className={field} value={from} max={to} disabled={running} onChange={e => e.target.value && setRange({ from: e.target.value, to })} />
                </label>
                <label className="flex flex-col text-xs text-muted-foreground">To
                    <input type="date" className={field} value={to} min={from} disabled={running} onChange={e => e.target.value && setRange({ from, to: e.target.value })} />
                </label>
                <Button disabled={running} onClick={start}>{running ? 'Running...' : 'Run agents'}</Button>
                <Button variant="outline" disabled={running || reset.isPending} onClick={() => reset.mutate(undefined, { onSuccess: () => { setStartedRunId(null); setHighlight(null); toast.success('Demo reset'); } })}>Reset demo</Button>
                <Button variant="secondary" className="ml-auto" disabled={pending.length === 0} data-slot="approval-drawer-trigger" data-open={approvalOpen}
                    onClick={() => setApprovalOpen(true)}>Needs approval ({pending.length})</Button>
            </div>

            <ApprovalDrawer open={approvalOpen} onOpenChange={setApprovalOpen} items={pending} onEvidence={onEvidence} />

            {run.data && <RunStatusLine run={run.data} />}
            {run.isError && <p role="alert" className="text-sm text-destructive">Could not load the run: {run.error.message}</p>}

            <QueryState query={statement}>{s => <StatementCard statement={s} />}</QueryState>

            {runId && (
                <section aria-label="Items" className="space-y-2">
                    <h2 className="text-sm font-medium">Items to review <span className="font-normal text-muted-foreground">(click one to highlight its rows; decide in the approval drawer)</span></h2>
                    <QueryState query={items} isEmpty={() => shown.length === 0} emptyMessage="No items need attention.">
                        {() => <ul className="grid gap-2 md:grid-cols-2">{shown.map(item => <ItemButton key={item.id} item={item} active={highlight === item.id} onSelect={() => setHighlight(h => nextHighlight(h, item.id))} />)}</ul>}
                    </QueryState>
                </section>
            )}

            <div className="grid gap-4 xl:grid-cols-2">
                <section aria-label="Bank transactions" className="min-w-0 space-y-2">
                    <h2 className="text-sm font-medium">Bank</h2>
                    <QueryState query={bank} isEmpty={list => list.length === 0} emptyMessage="No bank transactions in this range.">
                        {list => <TransactionTable rows={list.map(bankToRow)} typeLabel="Type" selectable={false} highlightItemId={highlight} onRowClick={onRowClick} />}
                    </QueryState>
                </section>
                <section aria-label="Ledger entries" className="min-w-0 space-y-2">
                    <h2 className="text-sm font-medium">Ledger</h2>
                    <QueryState query={gl} isEmpty={list => list.length === 0} emptyMessage="No ledger entries in this range.">
                        {list => <TransactionTable rows={list.map(glToRow)} typeLabel="Method" selectable={false} highlightItemId={highlight} onRowClick={onRowClick} />}
                    </QueryState>
                </section>
            </div>
        </>
    );
}

export function ReconcilePage() {
    const datasets = useDatasets();
    return (
        <Page title="Reconcile" subtitle="Run the agents, then review what needs a decision.">
            <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets available.">
                {list => <Workspace datasets={list} />}
            </QueryState>
        </Page>
    );
}
