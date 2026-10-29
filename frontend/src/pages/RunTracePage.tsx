import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { keys, useRules, useRun, useRunAudit } from '../api/hooks';
import type { AuditEntry, Run } from '../api/types';
import { QueryState } from '../components/QueryState';
import { StepCard } from '../components/recon/StepCard';
import { Badge } from '../components/ui/badge';
import { cn } from '../lib/utils';
import { isRunActive, runJustFinished } from '../lib/workspace';
import { COLUMNS, groupSteps, stepsDone } from '../lib/stepper';
import { ruleRows } from '../lib/rules';
import { actorLabel, auditView, formatDuration, runDurationMs, sortAudit, traceTotals } from '../lib/trace';
import { Page } from './Pages';

function Summary({ run }: { run: Run }) {
    const totals = traceTotals(run.steps);
    const duration = runDurationMs(run);
    const facts: [string, string][] = [
        ['Steps', `${stepsDone(run.steps)} of ${totals.steps} done`],
        ['Model calls', String(totals.modelSteps)],
        ['Tokens', `${totals.tokensIn.toLocaleString('en-US')} in / ${totals.tokensOut.toLocaleString('en-US')} out`],
        ['Model time', formatDuration(totals.modelLatencyMs)],
        ['Run time', duration === null ? '-' : formatDuration(duration)],
    ];
    return (
        <div className="space-y-2" data-testid="trace-summary">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="secondary">{run.status}</Badge>
                <span className="text-muted-foreground">{run.dataset}, {run.period_start} to {run.period_end}</span>
                {run.status === 'completed' && <Link to={`/report/${encodeURIComponent(run.id)}`} className="font-medium text-primary underline">Report</Link>}
            </div>
            {run.status === 'failed' && <p role="alert" className="text-sm text-destructive">{run.error?.message ?? 'The run failed.'}</p>}
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
                {facts.map(([label, value]) => (
                    <div key={label} className="rounded-md border px-3 py-2"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="tabular-nums">{value}</dd></div>
                ))}
            </dl>
        </div>
    );
}

function Timeline({ run }: { run: Run }) {
    const groups = groupSteps(run.steps);
    if (groups.length === 0) return <p className="text-sm text-muted-foreground">No steps recorded for this run yet.</p>;
    return (
        <ol className="space-y-3" data-testid="trace-timeline">
            {groups.map(group => (
                <li key={group.position} className="flex gap-3" data-testid="trace-group" data-parallel={group.steps.length > 1}>
                    <span className="mt-2 flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium tabular-nums" aria-label={`Stage ${group.position}`}>{group.position}</span>
                    <ul className={cn('grid min-w-0 flex-1 gap-2', COLUMNS[Math.min(group.steps.length, 3)])}>
                        {group.steps.map(step => <StepCard key={step.id} step={step} showModel />)}
                    </ul>
                </li>
            ))}
        </ol>
    );
}

function AuditLog({ entries }: { entries: AuditEntry[] }) {
    if (entries.length === 0) return <p className="text-sm text-muted-foreground" data-testid="audit-empty">No audit entries for this run yet.</p>;
    return (
        <ol className="divide-y rounded-md border text-sm" data-testid="audit-list">
            {sortAudit(entries).map(entry => {
                const view = auditView(entry);
                return (
                    <li key={entry.id} className="space-y-1 px-3 py-2" data-testid="audit-entry" data-action={entry.action}>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="font-medium">{view.title}</span>
                            {entry.model && <Badge variant="outline" data-testid="audit-model">{entry.model}</Badge>}
                            <span className="text-xs text-muted-foreground">{actorLabel(entry.actor)}</span>
                            <time className="ml-auto text-xs text-muted-foreground" dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
                        </div>
                        {view.fields.length > 0 && (
                            <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                                {view.fields.map(([key, value]) => (
                                    <div key={key} className="contents"><dt className="text-muted-foreground">{key}</dt><dd className="min-w-0 break-words">{value}</dd></div>
                                ))}
                            </dl>
                        )}
                    </li>
                );
            })}
        </ol>
    );
}

function RulesTable({ rules }: { rules: Parameters<typeof ruleRows>[0] }) {
    if (rules.length === 0) return <p className="text-sm text-muted-foreground" data-testid="rules-empty">No rules learned yet. Approve an item with "remember" checked to teach one.</p>;
    return (
        <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-sm" data-testid="rules-table">
                <thead className="text-xs text-muted-foreground"><tr>{['Rule', 'Kind', 'Pattern', 'Accounts', 'Created by', 'Created at'].map(h => <th key={h} className="px-3 py-1.5 font-medium">{h}</th>)}</tr></thead>
                <tbody className="divide-y">
                    {ruleRows(rules).map(r => (
                        <tr key={r.id} data-testid="rule-row">
                            <td className="px-3 py-1.5">#{r.id}{!r.active && <span className="ml-1 text-xs text-muted-foreground">(inactive)</span>}</td>
                            <td className="px-3 py-1.5">{r.kind}</td>
                            <td className="px-3 py-1.5 font-mono text-xs break-all">{r.pattern}</td>
                            <td className="px-3 py-1.5">{r.accounts}</td>
                            <td className="px-3 py-1.5">{r.createdBy}</td>
                            <td className="px-3 py-1.5 text-xs text-muted-foreground"><time dateTime={r.createdAt}>{new Date(r.createdAt).toLocaleString()}</time></td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

export function RunTracePage() {
    const rules = useRules();
    const { id } = useParams<{ id: string }>();
    const run = useRun(id);
    const audit = useRunAudit(id, isRunActive(run.data?.status));
    const client = useQueryClient();
    const prevStatus = useRef(run.data?.status);
    const status = run.data?.status;
    // Polling stops when the run finishes, so fetch the audit once more to pick up the last rows.
    useEffect(() => {
        if (id && runJustFinished(prevStatus.current, status)) void client.invalidateQueries({ queryKey: keys.audit(id) });
        prevStatus.current = status;
    }, [id, status, client]);
    return (
        <Page title="Run trace" subtitle={id} actions={<Link to="/reconcile" className="text-sm font-medium text-primary underline">Back to Reconcile</Link>}>
            <QueryState query={run}>
                {r => (
                    <div className="space-y-6">
                        <Summary run={r} />
                        <section aria-label="Steps" className="space-y-2">
                            <h2 className="text-sm font-medium">Steps</h2>
                            <Timeline run={r} />
                        </section>
                    </div>
                )}
            </QueryState>
            <section aria-label="Audit log" className="space-y-2">
                <h2 className="text-sm font-medium">Audit log</h2>
                <QueryState query={audit}>{entries => <AuditLog entries={entries} />}</QueryState>
            </section>
            <section aria-label="Learned rules" className="space-y-2">
                <h2 className="text-sm font-medium">Learned rules</h2>
                <QueryState query={rules}>{list => <RulesTable rules={list} />}</QueryState>
            </section>
        </Page>
    );
}
