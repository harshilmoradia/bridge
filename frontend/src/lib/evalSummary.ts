export const PIPELINES = ['rules', 'nano', 'super', 'tiered', 'ultra'] as const;
export type PipelineName = (typeof PIPELINES)[number];

export const RATIO_METRICS = [
    { key: 'match_precision', label: 'Match precision' },
    { key: 'match_recall', label: 'Match recall' },
    { key: 'kind_accuracy', label: 'Kind accuracy' },
    { key: 'correct_escalations', label: 'Correct escalations' },
    { key: 'entry_correctness', label: 'Entry correctness' },
] as const;
export type RatioKey = (typeof RATIO_METRICS)[number]['key'];

export interface Ratio { hit: number; total: number; value: number | null }

export interface PipelineSummary {
    created_at: string; dataset: string; git_sha: string;
    match_precision: Ratio; match_recall: Ratio; kind_accuracy: Ratio; correct_escalations: Ratio; entry_correctness: Ratio;
    false_auto_resolutions: number;
    /** Decimal string, e.g. "864.10". Never parsed to a float. */
    final_difference: string;
    /** Difference once every escalation is approved as drafted. This is the gate. Null if the report predates the field. */
    difference_after_approvals: string | null;
    expected_difference: string | null;
    latency_ms: number | null; tokens_in: number | null; tokens_out: number | null;
    /** Decimal string in USD, or null before the eval records cost. */
    cost_usd: string | null;
    /** Model calls made in the run; null when the report does not record it. */
    calls: number | null;
    /** Tiers whose price is a placeholder; null when the report predates the field. */
    price_placeholder_tiers: string[] | null;
}

export interface EvalSummary { pipelines: Partial<Record<string, PipelineSummary>> }

const lookup = (summary: EvalSummary, name: string): PipelineSummary | null => {
    const map = new Map(Object.entries(summary.pipelines));
    return map.get(name) ?? null;
};

/** Known pipelines in display order; `data` is null for pipelines not run yet. */
export function orderedPipelines(summary: EvalSummary): { name: PipelineName; data: PipelineSummary | null }[] {
    return PIPELINES.map(name => ({ name, data: lookup(summary, name) }));
}

export interface MetricRow { key: RatioKey; label: string; values: Record<string, Ratio | null> }

/** One row per metric; each pipeline's ratio or null when that pipeline has not run. */
export function metricRows(summary: EvalSummary): MetricRow[] {
    return RATIO_METRICS.map(({ key, label }) => ({
        key, label,
        values: Object.fromEntries(PIPELINES.map(p => [p, lookup(summary, p)?.[key] ?? null])),
    }));
}

/** Chart rows: value as a 0-100 percentage per pipeline that has run. */
export function chartData(summary: EvalSummary): Record<string, string | number>[] {
    return metricRows(summary).map(row => {
        const out: Record<string, string | number> = { metric: row.label };
        for (const p of PIPELINES) {
            const r = row.values[p];
            if (r && r.value !== null && r.total !== 0) out[p] = Math.round(r.value * 1000) / 10;
        }
        return out;
    });
}

export const isZeroDecimal = (s: string) => /^-?0+(\.0+)?$/.test(s.trim());

/** Compares decimal strings by scaled integers, never floats. */
export function sameDecimal(a: string, b: string): boolean {
    const parse = (s: string): [bigint, number] | null => {
        const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(s.trim());
        if (!m) return null;
        const frac = (m[3] ?? '').replace(/0+$/, '');
        return [BigInt(`${m[1]}${m[2]}${frac}`), frac.length];
    };
    const x = parse(a), y = parse(b);
    if (!x || !y) return false;
    const scale = Math.max(x[1], y[1]);
    return x[0] * 10n ** BigInt(scale - x[1]) === y[0] * 10n ** BigInt(scale - y[1]);
}

export interface Gate { pipeline: PipelineName; pass: boolean; display: string }

export function falseAutoGates(summary: EvalSummary): Gate[] {
    return orderedPipelines(summary).flatMap(({ name, data }) =>
        data ? [{ pipeline: name, pass: data.false_auto_resolutions === 0, display: String(data.false_auto_resolutions) }] : []);
}

export function differenceGates(summary: EvalSummary): Gate[] {
    return orderedPipelines(summary).flatMap(({ name, data }) =>
        data ? [{
            pipeline: name,
            pass: data.difference_after_approvals !== null
                && (data.expected_difference === null ? isZeroDecimal(data.difference_after_approvals) : sameDecimal(data.difference_after_approvals, data.expected_difference)),
            display: data.difference_after_approvals ?? 'n/a',
        }] : []);
}

export const formatRatio = (r: Ratio) => (r.value === null || r.total === 0 ? 'N/A' : `${r.hit}/${r.total} (${(Math.round(r.value * 1000) / 10).toFixed(1)}%)`);
export const formatLatency = (ms: number | null) => (ms === null ? null : ms < 1000 ? `${ms} ms` : `${(Math.round(ms / 100) / 10).toFixed(1)} s`);
export const formatCost = (usd: string | null) => (usd === null ? null : `$${usd}`);

export function hasRunMetrics(summary: EvalSummary): { latency: boolean; cost: boolean; tokens: boolean; calls: boolean } {
    const all = [...new Map(Object.entries(summary.pipelines)).values()].filter((p): p is PipelineSummary => Boolean(p));
    return { latency: all.some(p => p.latency_ms !== null), cost: all.some(p => p.cost_usd !== null), tokens: all.some(p => formatTokens(p) !== null), calls: all.some(p => p.calls !== null) };
}

/** Bar chart rows: latency in seconds, cost in USD. Chart-only numbers; the table keeps the exact strings. */
export function costLatencyData(summary: EvalSummary): { latency: { pipeline: PipelineName; value: number }[]; cost: { pipeline: PipelineName; value: number }[] } {
    const latency: { pipeline: PipelineName; value: number }[] = [];
    const cost: { pipeline: PipelineName; value: number }[] = [];
    for (const { name, data } of orderedPipelines(summary)) {
        if (!data) continue;
        if (data.latency_ms !== null) latency.push({ pipeline: name, value: data.latency_ms / 1000 });
        if (data.cost_usd !== null) cost.push({ pipeline: name, value: Number(data.cost_usd) });
    }
    return { latency, cost };
}

export const formatTokens = (p: PipelineSummary) => (p.tokens_in === null && p.tokens_out === null ? null : `${p.tokens_in ?? 0} in / ${p.tokens_out ?? 0} out`);

export const formatCalls = (p: PipelineSummary) => (p.calls === null ? null : String(p.calls));

/** Tiers priced with a placeholder. Uses the data; falls back to ultra only when no report carries the field. */
export function placeholderTiers(summary: EvalSummary): string[] {
    const all = [...new Map(Object.entries(summary.pipelines)).values()].filter((p): p is PipelineSummary => Boolean(p));
    if (all.some(p => p.price_placeholder_tiers !== null)) return [...new Set(all.flatMap(p => p.price_placeholder_tiers ?? []))];
    return all.length > 0 && Object.keys(summary.pipelines).includes('ultra') && all.some(p => p.cost_usd !== null) ? ['ultra'] : [];
}
