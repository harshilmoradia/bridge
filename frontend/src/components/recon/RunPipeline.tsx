import { Check, X } from 'lucide-react';
import { Link } from 'react-router';
import type { Run, RunStep } from '../../api/types';
import { fallbackWarning, formatLatency, groupSteps, STEP_STATUS_LABEL, stepDetail, stepsDone } from '../../lib/stepper';
import { isRunActive } from '../../lib/workspace';
import { cn } from '../../lib/utils';
import { TierTag } from './ApprovalInbox';

function Step({ step }: { step: RunStep }) {
    const detail = stepDetail(step);
    return (
        <li data-testid="run-step" data-step-id={step.id} data-step-status={step.status} className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[12.5px] font-semibold" title={step.label}>{step.label}</span>
            <span className="flex items-center gap-1.5 text-[11px] text-faint">
                <TierTag tier={step.tier} title={step.model ?? 'No model: runs as code'} />
                {step.status !== 'pending' && <span className="tabular-nums">{formatLatency(step)}</span>}
            </span>
            <span className={cn('line-clamp-2 text-[11.5px]', step.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>
                {step.status === 'running' ? 'Working…' : detail}
            </span>
        </li>
    );
}

// One column per pipeline position; steps that run in parallel stack inside their column.
function Column({ steps, last }: { steps: RunStep[]; last: boolean }) {
    const done = steps.every(s => s.status === 'completed');
    const failed = steps.some(s => s.status === 'failed');
    const running = !failed && steps.some(s => s.status === 'running');
    const label = failed ? STEP_STATUS_LABEL.failed : running ? STEP_STATUS_LABEL.running : done ? STEP_STATUS_LABEL.completed : STEP_STATUS_LABEL.pending;
    return (
        <li data-testid="run-step-group" data-parallel={steps.length > 1} className="relative flex min-w-[108px] flex-1 flex-col gap-2 pr-2.5">
            <span role="img" aria-label={label}
                className={cn('relative z-10 grid size-[22px] place-items-center rounded-full border-[1.5px] bg-card transition-all',
                    done && 'border-good bg-good text-card', failed && 'border-destructive bg-destructive text-card',
                    running && 'border-primary shadow-[0_0_0_4px_var(--primary-soft)]', !done && !failed && !running && 'border-input')}>
                {done && <Check className="size-3" strokeWidth={3} aria-hidden="true" />}
                {failed && <X className="size-3" strokeWidth={3} aria-hidden="true" />}
                {running && <i className="pulse-dot size-2 rounded-full bg-primary" />}
            </span>
            {!last && <i aria-hidden="true" className={cn('absolute top-[10.5px] right-0 left-[22px] h-[1.5px] transition-colors duration-300', done ? 'bg-good' : 'bg-border')} />}
            <ul className="flex flex-col gap-2.5">{steps.map(s => <Step key={s.id} step={s} />)}</ul>
        </li>
    );
}

export function RunPipeline({ run }: { run: Run }) {
    const groups = groupSteps(run.steps);
    const current = run.steps.find(s => s.status === 'running');
    const total = run.steps.length;
    const done = stepsDone(run.steps);
    const warning = fallbackWarning(run);
    const tone = run.status === 'completed' ? 'bg-good-soft text-good' : run.status === 'failed' ? 'bg-destructive-soft text-destructive' : 'bg-primary-soft text-primary';
    return (
        <section aria-label="Agent run" data-testid="run-stepper" className="min-w-0 rounded-lg border bg-card shadow-card">
            <div className="flex flex-wrap items-center gap-2.5 border-b px-4 py-3" role="status" data-testid="run-status" data-run-status={run.status}>
                <h2 className="text-sm font-semibold">Agent run</h2>
                <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold capitalize', tone)}>
                    <i className={cn('size-1.5 rounded-full bg-current', isRunActive(run.status) && 'pulse-dot')} />{run.status}
                </span>
                <span className="text-[12.5px] text-muted-foreground">
                    {total > 0 ? `${done} of ${total} steps` : 'Waiting for the first step…'}
                    {current && ` · ${current.label}…`}
                    {run.status === 'completed' && ` · ${run.counts.matched} matched, ${run.counts.auto_resolved} auto-resolved, ${run.counts.needs_approval} need approval`}
                </span>
                {run.status === 'failed' && <span className="text-[12.5px] text-destructive">{run.error?.message ?? 'The run failed.'}</span>}
                {warning && <span role="alert" data-testid="run-fallback-warning" className="text-[12.5px] text-destructive">{warning}</span>}
                <span className="ml-auto flex gap-4 text-[13px] font-semibold">
                    <Link to={`/runs/${encodeURIComponent(run.id)}`} className="text-primary hover:underline">View trace</Link>
                    {run.status === 'completed' && <Link to={`/report/${encodeURIComponent(run.id)}`} className="text-primary hover:underline">Report</Link>}
                </span>
            </div>
            <div className="overflow-x-auto">
                <ol className="flex min-w-[900px] px-4 pt-3.5 pb-4">
                    {groups.map((g, i) => <Column key={g.position} steps={g.steps} last={i === groups.length - 1} />)}
                </ol>
            </div>
        </section>
    );
}
