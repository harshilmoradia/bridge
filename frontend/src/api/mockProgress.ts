// Mock mode: replays a finished run as stages advancing one position per poll, so the stepper shows live progress.
import { groupSteps } from '../lib/stepper.ts';
import type { Run, RunStep } from './types.ts';

export const mockStageCount = (done: Run) => groupSteps(done.steps).length;

// `completed` is how many position groups have finished. The next group is running, the rest pending.
// A finished position carries the fixture's latency, tokens and summary; unfinished ones carry none.
export function runAtStage(done: Run, completed: number): Run {
    const groups = groupSteps(done.steps);
    if (completed >= groups.length) return structuredClone(done);
    const steps: RunStep[] = groups.flatMap((group, index) => group.steps.map((step): RunStep => {
        if (index < completed) return { ...step };
        const running = index === completed;
        return { ...step, status: running ? 'running' : 'pending', started_at: running ? step.started_at : null, finished_at: null, latency_ms: null, tokens_in: null, tokens_out: null, output_summary: null, error: null };
    }));
    return { ...structuredClone(done), status: 'running', steps, counts: { ...done.counts, items: 0, matched: 0, auto_resolved: 0, reconciling_item: 0, needs_approval: 0 }, report: null };
}

// Tracks which mock run is in flight. Only a GET for the current run id advances the stages; other ids (the old fixture run) get the finished run.
export class MockRunPoller {
    currentId: string;
    private remaining = 0;
    private readonly stages: number;
    constructor(initialId: string, stages: number) { this.currentId = initialId; this.stages = stages; }
    get active() { return this.remaining > 0; }
    start(id: string) { this.currentId = id; this.remaining = this.stages; }
    reset(id: string) { this.currentId = id; this.remaining = 0; }
    poll(done: Run, requestedId: string): Run {
        if (requestedId !== this.currentId || this.remaining === 0) return { ...structuredClone(done), id: requestedId };
        const stage = this.stages - this.remaining;
        this.remaining -= 1;
        return { ...runAtStage(done, stage), id: requestedId };
    }
}
