// Pure logic for the run progress stepper: grouping parallel steps, status labels, latency and token text.
import type { Run, RunStep, StepStatus } from '../api/types.ts';

export interface StepGroup { position: number; steps: RunStep[] }

// Steps sharing a `position` run in parallel; groups come back in position order, steps in id order within a group.
export function groupSteps(steps: RunStep[]): StepGroup[] {
    const byPosition = new Map<number, RunStep[]>();
    for (const step of steps) byPosition.set(step.position, [...(byPosition.get(step.position) ?? []), step]);
    return [...byPosition.entries()]
        .sort(([a], [b]) => a - b)
        .map(([position, group]) => ({ position, steps: group.sort((a, b) => a.id.localeCompare(b.id)) }));
}

export const STEP_STATUS_LABEL: Record<StepStatus, string> = { pending: 'Pending', running: 'Running', completed: 'Complete', failed: 'Failed' };

// Code-tier stages may report null latency: show "code", never 0 ms. Unfinished model stages show a dash.
export function formatLatency(step: Pick<RunStep, 'status' | 'tier' | 'latency_ms'>): string {
    if (step.latency_ms !== null) return step.latency_ms < 1000 ? `${step.latency_ms} ms` : `${(step.latency_ms / 1000).toFixed(1)} s`;
    if (step.status === 'pending') return '-';
    if (step.status === 'running') return 'running';
    return step.tier === 'code' ? 'code' : '-';
}

export function formatTokens(step: Pick<RunStep, 'tokens_in' | 'tokens_out'>): string | null {
    if (step.tokens_in === null && step.tokens_out === null) return null;
    return `${(step.tokens_in ?? 0).toLocaleString('en-US')} in / ${(step.tokens_out ?? 0).toLocaleString('en-US')} out`;
}

export function stepDetail(step: Pick<RunStep, 'status' | 'output_summary' | 'error'>): string | null {
    if (step.status === 'failed') return step.error?.message ?? step.output_summary ?? 'This step failed.';
    return step.output_summary;
}

// A completed run can still have failed stages: a dead model leaves its rows to code defaults
// (more escalations, a template report). A failed run already shows its own error.
export function fallbackWarning(run: Pick<Run, 'status' | 'steps'>): string | null {
    if (run.status !== 'completed') return null;
    const failed = run.steps.filter(s => s.status === 'failed').map(s => s.label);
    return failed.length ? `Model fallback in ${failed.join(', ')}: more items may need approval than usual.` : null;
}

export const stepsDone =(steps: Pick<RunStep, 'status'>[]) => steps.filter(s => s.status === 'completed').length;

// Fixed class names so Tailwind sees them; more than 3 parallel steps wrap onto a second line.
export const COLUMNS: Record<number, string> = { 1: 'sm:grid-cols-1', 2: 'sm:grid-cols-2', 3: 'sm:grid-cols-3' };

