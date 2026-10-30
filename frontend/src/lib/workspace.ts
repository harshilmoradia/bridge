// Pure logic for the Reconcile workspace: highlight toggling, run polling, count-up. No floats for money.
import { fromCents, toCents } from './cents.ts';
import type { Item, ReconStatus, RunStatus } from '../api/types.ts';

export const RUN_POLL_MS = 1500;

export const isRunActive = (status: RunStatus | undefined) => status === 'queued' || status === 'running';

// Clicking the highlighted item again clears it; rows without an item leave the highlight alone.
export function nextHighlight(current: string | null, clicked: string | null): string | null {
    if (!clicked) return current;
    return current === clicked ? null : clicked;
}

// Changes whenever any item's id or status changes; used to know when to refetch the statement.
export const itemsSignature = (items: Pick<Item, 'id' | 'status'>[]) => items.map(i => `${i.id}:${i.status}`).sort().join('|');

export const needsApproval = <T extends { status: ReconStatus }>(items: T[]) => items.filter(i => i.status === 'needs_approval');

const MONEY_RE = /^[-+]?\d+(\.\d+)?$/;
// Malformed or empty strings are not zero.
export const isZeroMoney = (value: string) => MONEY_RE.test(value) && toCents(value) === 0n;

// True once, on the poll where a run goes from queued/running to a finished status; used for the final audit fetch.
export const runJustFinished = (prev: RunStatus | undefined, current: RunStatus | undefined) =>
    isRunActive(prev) && current !== undefined && !isRunActive(current);

// Refresh the statement and items the first time a run started on this page reports completed, even if no earlier poll was seen.
export function shouldRefreshOnComplete(startedRunId: string | null, runId: string | undefined, status: RunStatus | undefined, refreshedRunId: string | null): boolean {
    return status === 'completed' && startedRunId !== null && runId === startedRunId && refreshedRunId !== runId;
}

// Value between two decimal strings at progress t in [0, 1], computed on integer cents.
export function interpolateMoney(from: string, to: string, t: number): string {
    const p = Math.min(1, Math.max(0, t));
    if (p >= 1) return to;
    const a = toCents(from);
    const b = toCents(to);
    return fromCents(a + ((b - a) * BigInt(Math.round(p * 1000))) / 1000n);
}

// The Reconcile date range defaults to the selected dataset's period, so run, statement and report agree.
export const defaultRange = (d: { period_start: string; period_end: string }) => ({ from: d.period_start, to: d.period_end });

// Share of the raw difference closed so far, 0 to 100, for the progress meter. A zero raw difference counts as fully closed.
export function closedPercent(raw: string, unreconciled: string): number {
    const abs = (c: bigint) => (c < 0n ? -c : c);
    const total = abs(toCents(raw));
    if (total === 0n) return 100;
    const left = abs(toCents(unreconciled));
    if (left >= total) return 0;
    return Number(((total - left) * 100n) / total);
}
