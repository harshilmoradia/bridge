// Pure helpers for the /runs/:id trace page: totals, durations and audit log rows.
import type { AuditEntry, Run, RunStep } from '../api/types.ts';

export interface TraceTotals { steps: number; modelSteps: number; tokensIn: number; tokensOut: number; modelLatencyMs: number; failed: number }

export function traceTotals(steps: RunStep[]): TraceTotals {
    const totals: TraceTotals = { steps: steps.length, modelSteps: 0, tokensIn: 0, tokensOut: 0, modelLatencyMs: 0, failed: 0 };
    for (const step of steps) {
        if (step.tier !== 'code') totals.modelSteps += 1;
        totals.tokensIn += step.tokens_in ?? 0;
        totals.tokensOut += step.tokens_out ?? 0;
        if (step.tier !== 'code') totals.modelLatencyMs += step.latency_ms ?? 0;
        if (step.status === 'failed') totals.failed += 1;
    }
    return totals;
}

export function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms} ms`;
    if (ms < 59_950) return `${(ms / 1000).toFixed(1)} s`;
    const total = Math.round(ms / 1000);
    return `${Math.floor(total / 60)} min ${total % 60} s`;
}

// Wall-clock time of the run, from created to last update. null while it is still running or the dates are bad.
export function runDurationMs(run: Pick<Run, 'status' | 'created_at' | 'updated_at'>): number | null {
    if (run.status === 'queued' || run.status === 'running') return null;
    const ms = Date.parse(run.updated_at) - Date.parse(run.created_at);
    return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

export const actorLabel = (actor: string) => actor.replace(/^(agent|user):/, '');

export interface AuditView { title: string; fields: [string, string][] }

const humanize = (value: string) => value.replaceAll('_', ' ');
const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const MAX_ITEMS = 20;
const MAX_CHARS = 500;
const clip = (s: string) => (s.length > MAX_CHARS ? `${s.slice(0, MAX_CHARS)}…` : s);
const text = (v: unknown): string => {
    if (v === null || v === undefined) return '-';
    if (Array.isArray(v)) return v.length > MAX_ITEMS ? `${v.slice(0, MAX_ITEMS).map(text).join(', ')}, … (+${v.length - MAX_ITEMS} more)` : v.map(text).join(', ');
    if (typeof v === 'object') return clip(JSON.stringify(v));
    return clip(String(v));
};
const capList = (shown: string[], total: number) => `${shown.join(', ')}${total > MAX_ITEMS ? ` (+${total - MAX_ITEMS} more)` : ''}`;
const count = (v: unknown): number | null => (Array.isArray(v) ? v.length : typeof v === 'number' && Number.isFinite(v) ? v : null);
const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

// A readable title and key/value fields for one audit row. Everything returned is plain text: the page renders it as text nodes.
export function auditView(entry: AuditEntry): AuditView {
    const { entity_type: type, action } = entry;
    const id = typeof entry.entity_id === 'string' ? entry.entity_id : null;
    const detail: Record<string, unknown> = isRecord(entry.detail) ? entry.detail : {};
    if (type === 'guardrail' && action === 'injection_flagged') {
        const reasons = Array.isArray(detail.reasons) ? capList(detail.reasons.slice(0, MAX_ITEMS).map(r => humanize(text(r))), detail.reasons.length) : '';
        return { title: `Injection flagged on ${id ? clip(id) : 'a row'}${reasons ? `: ${reasons}` : ''}`, fields: [] };
    }
    if (type === 'run' && action === 'guard_scan') {
        const masked = count(detail.masked_rows);
        const flagged = count(detail.flagged_rows);
        if (masked !== null && flagged !== null) return { title: `Guard scan: ${plural(masked, 'row')} masked, ${flagged} flagged`, fields: [] };
    }
    if (type === 'item' && (action === 'approve' || action === 'reject')) {
        const fields: [string, string][] = [];
        if (typeof detail.note === 'string' && detail.note) fields.push(['Note', clip(detail.note)]);
        const o = detail.entry_override;
        if (isRecord(o)) {
            fields.push(['Entry', [`DR ${text(o.debit_account)} / CR ${text(o.credit_account)}`, o.amount, o.memo].filter(v => v !== undefined && v !== null && v !== '').map(text).join(', ')]);
        }
        const remembered = action === 'approve' && detail.remember === true ? ' (remembered rule)' : '';
        return { title: `${action === 'approve' ? 'Approved' : 'Rejected'} item ${id ? id.slice(0, 8) : ''}${remembered}`.replace(/ +/g, ' ').trim(), fields };
    }
    const base = clip(`${type} ${humanize(action)}`);
    const entries = Object.entries(detail);
    const fields: [string, string][] = entries.slice(0, MAX_ITEMS).map(([k, v]) => [clip(k), text(v)]);
    if (entries.length > MAX_ITEMS) fields.push([`+${entries.length - MAX_ITEMS} more`, '']);
    return { title: id ? `${base} (${clip(id)})` : base, fields };
}

// Newest last, so the log reads like the timeline above it.
export const sortAudit = (entries: AuditEntry[]) => [...entries].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id);
