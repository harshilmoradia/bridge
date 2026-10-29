import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    chartData, costLatencyData, differenceGates, falseAutoGates, formatCost, formatLatency, formatRatio, hasRunMetrics, isZeroDecimal, metricRows, orderedPipelines, placeholderTiers, hasRunMetrics as hrm,
    type EvalSummary, type PipelineSummary,
} from '../src/lib/evalSummary.ts';

const r = (hit: number, total: number) => ({ hit, total, value: hit / total });
const pipe = (over: Partial<PipelineSummary> = {}): PipelineSummary => ({
    created_at: 't', dataset: 'd', git_sha: 's',
    match_precision: r(10, 10), match_recall: r(9, 10), kind_accuracy: r(8, 10), correct_escalations: r(1, 5), entry_correctness: r(2, 6),
    false_auto_resolutions: 0, final_difference: '0.00', difference_after_approvals: '0.00', expected_difference: '0.00', latency_ms: null, tokens_in: null, tokens_out: null, cost_usd: null, calls: null, price_placeholder_tiers: null, ...over,
});
const summary: EvalSummary = { pipelines: { rules: pipe({ final_difference: '864.10', difference_after_approvals: '864.10' }), tiered: pipe({ latency_ms: 2500, cost_usd: '0.12' }) } };

test('orders the five pipelines and marks missing ones null', () => {
    const o = orderedPipelines(summary);
    assert.deepEqual(o.map(p => p.name), ['rules', 'nano', 'super', 'tiered', 'ultra']);
    assert.deepEqual(o.map(p => p.data !== null), [true, false, false, true, false]);
});
test('metric rows map each metric to a ratio per pipeline', () => {
    const rows = metricRows(summary);
    assert.equal(rows.length, 5);
    assert.deepEqual(rows[1].values.rules, r(9, 10));
    assert.equal(rows[1].values.nano, null);
});
test('a null ratio value is skipped in the chart and shown as N/A', () => {
    const s: EvalSummary = { pipelines: { rules: pipe({ match_precision: { hit: 0, total: 0, value: null } }) } };
    assert.equal('rules' in chartData(s)[0], false);
    assert.equal(formatRatio({ hit: 0, total: 0, value: null }), 'N/A');
});
test('chart data holds percentages only for pipelines that ran', () => {
    const d = chartData(summary);
    assert.equal(d[0].metric, 'Match precision');
    assert.equal(d[1].rules, 90);
    assert.equal('nano' in d[1], false);
    assert.equal(d[3].tiered, 20);
});
test('gates: false auto-resolutions must be 0, difference must be 0.00', () => {
    const s: EvalSummary = { pipelines: { nano: pipe({ false_auto_resolutions: 2 }), super: pipe() } };
    assert.deepEqual(falseAutoGates(s).map(g => [g.pipeline, g.pass]), [['nano', false], ['super', true]]);
    assert.deepEqual(differenceGates(summary).map(g => [g.pipeline, g.pass, g.display]), [['rules', false, '864.10'], ['tiered', true, '0.00']]);
});
test('difference gate uses the after-approvals figure, not the pending one', () => {
    const s: EvalSummary = { pipelines: {
        nano: pipe({ final_difference: '120.00', difference_after_approvals: '0.00' }),
        super: pipe({ final_difference: '0.00', difference_after_approvals: '5.00' }),
        rules: pipe({ difference_after_approvals: null }),
    } };
    assert.deepEqual(differenceGates(s).map(g => [g.pipeline, g.pass, g.display]), [['rules', false, 'n/a'], ['nano', true, '0.00'], ['super', false, '5.00']]);
});
test('latency and cost chart data only for pipelines that have them', () => {
    const d = costLatencyData(summary);
    assert.deepEqual(d.latency, [{ pipeline: 'tiered', value: 2.5 }]);
    assert.deepEqual(d.cost, [{ pipeline: 'tiered', value: 0.12 }]);
    assert.deepEqual(costLatencyData({ pipelines: { rules: pipe() } }), { latency: [], cost: [] });
});
test('isZeroDecimal reads strings without floats', () => {
    for (const z of ['0', '0.00', '-0.00', '00.0']) assert.equal(isZeroDecimal(z), true);
    for (const n of ['0.01', '864.10', '-0.10', '10']) assert.equal(isZeroDecimal(n), false);
});
test('formatters', () => {
    assert.equal(formatRatio(r(105, 111)), '105/111 (94.6%)');
    assert.equal(formatLatency(null), null);
    assert.equal(formatLatency(850), '850 ms');
    assert.equal(formatLatency(2500), '2.5 s');
    assert.equal(formatCost('0.12'), '$0.12');
    assert.equal(formatCost(null), null);
});
test('latency and cost columns show only when some pipeline has them', () => {
    assert.deepEqual(hasRunMetrics({ pipelines: { rules: pipe() } }), { latency: false, cost: false, tokens: false, calls: false });
    assert.deepEqual(hasRunMetrics(summary), { latency: true, cost: true, tokens: false, calls: false });
});

test('difference gate passes when it equals expected_difference', () => {
    const s: EvalSummary = { pipelines: {
        nano: pipe({ difference_after_approvals: '5.00', expected_difference: '5.00' }),
        super: pipe({ difference_after_approvals: '5.00', expected_difference: '0.00' }),
        rules: pipe({ difference_after_approvals: '0.00', expected_difference: null }),
    } };
    assert.deepEqual(differenceGates(s).map(g => [g.pipeline, g.pass]), [['rules', true], ['nano', true], ['super', false]]);
});

test('total 0 is N/A whatever the value, with no chart bar', () => {
    const z = { hit: 0, total: 0, value: 1 };
    assert.equal(formatRatio(z), 'N/A');
    const rows = chartData({ pipelines: { rules: pipe({ match_precision: z }) } });
    assert.equal(rows[0].rules, undefined);
});

test('placeholder tiers come from the data, with an ultra fallback only for old reports', () => {
    assert.deepEqual(placeholderTiers({ pipelines: { ultra: pipe({ cost_usd: '1.00', price_placeholder_tiers: ['ultra'] }), tiered: pipe({ cost_usd: '0.1', price_placeholder_tiers: [] }) } }), ['ultra']);
    assert.deepEqual(placeholderTiers({ pipelines: { ultra: pipe({ cost_usd: '1.00', price_placeholder_tiers: [] }) } }), []);
    assert.deepEqual(placeholderTiers({ pipelines: { ultra: pipe({ cost_usd: '1.00' }) } }), ['ultra']);
    assert.deepEqual(placeholderTiers({ pipelines: { tiered: pipe({ cost_usd: '1.00' }) } }), []);
});
test('model calls row shows only when a report has calls', () => {
    assert.equal(hrm({ pipelines: { rules: pipe() } }).calls, false);
    assert.equal(hrm({ pipelines: { rules: pipe({ calls: 12 }) } }).calls, true);
});
