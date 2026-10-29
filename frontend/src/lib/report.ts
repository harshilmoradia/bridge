// Which view the report page shows for a run.
import type { RunStatus } from '../api/types.ts';

export type ReportView = 'waiting' | 'report' | 'empty' | 'failed';

export function reportView(run: { status: RunStatus; report: string | null }): ReportView {
    if (run.report?.trim()) return 'report';
    if (run.status === 'failed') return 'failed';
    if (run.status === 'queued' || run.status === 'running') return 'waiting';
    return 'empty';
}
