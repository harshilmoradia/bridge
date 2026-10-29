import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildSummary, extractSummary, isResultFile } from '../scripts/evalExtract.mjs';

const ratio = (hit, total) => ({ hit, total, value: hit / total });
const report = (pipeline, created_at, extra = {}) => ({
    pipeline, created_at, dataset: 'd', git_sha: 'abc',
    scores: {
        match_precision: ratio(10, 10), match_recall: ratio(9, 10), kind_accuracy: ratio(8, 10), correct_escalations: ratio(1, 5), entry_correctness: ratio(2, 6),
        kind_accuracy_by_kind: { exact: ratio(1, 1) }, false_auto_resolutions: [], missed_truth_ids: ['T001'], final_difference: '1.50',
    },
    ...extra,
});

test('keeps aggregates only and nulls absent latency and cost', () => {
    const s = extractSummary(report('rules', '2026-10-27T00:00:00Z'));
    assert.equal(s.match_recall.hit, 9);
    assert.equal(s.false_auto_resolutions, 0);
    assert.equal(s.final_difference, '1.50');
    assert.deepEqual([s.latency_ms, s.tokens_in, s.tokens_out, s.cost_usd], [null, null, null, null]);
    assert.equal('missed_truth_ids' in s, false);
    assert.equal('kind_accuracy_by_kind' in s, false);
});
test('counts false auto-resolutions from the list', () => {
    const r = report('nano', '2026-10-27T00:00:00Z');
    r.scores.false_auto_resolutions = ['a', 'b'];
    assert.equal(extractSummary(r).false_auto_resolutions, 2);
});
test('reads latency, tokens and cost from top level or scores', () => {
    const top = extractSummary(report('super', '2026-10-27T00:00:00Z', { latency_ms: 1200, tokens_in: 5, tokens_out: 6, cost_usd: '0.0420' }));
    assert.deepEqual([top.latency_ms, top.tokens_in, top.tokens_out, top.cost_usd], [1200, 5, 6, '0.0420']);
    const r = report('super', '2026-10-27T00:00:00Z');
    r.scores.latency_ms = 90; r.scores.cost_usd = '0.5';
    const nested = extractSummary(r);
    assert.equal(nested.latency_ms, 90);
    assert.equal(nested.cost_usd, '0.5');
});
test('money fields accept decimal strings only', () => {
    const r = report('x', '2026-10-27T00:00:00Z', { cost_usd: 0.5 });
    r.scores.difference_after_approvals = 0;
    const s = extractSummary(r);
    assert.equal(s.cost_usd, null);
    assert.equal(s.difference_after_approvals, null);
    assert.equal(extractSummary(report('x', 't', { cost_usd: '0.05' })).cost_usd, '0.05');
    const bad = report('x', 't');
    bad.scores.final_difference = 1.5;
    assert.equal(extractSummary(bad), null);
});
test('carries difference_after_approvals and expected_difference, else null', () => {
    const s0 = extractSummary(report('x', 't'));
    assert.equal(s0.difference_after_approvals, null);
    assert.equal(s0.expected_difference, null);
    const r = report('x', 't');
    r.scores.final_difference = '120.00';
    r.scores.difference_after_approvals = '0.00';
    r.scores.expected_difference = '0.00';
    const s = extractSummary(r);
    assert.deepEqual([s.final_difference, s.difference_after_approvals, s.expected_difference], ['120.00', '0.00', '0.00']);
});
test('counts and tokens must be integers', () => {
    const s = extractSummary(report('x', 't', { tokens_in: 1.5, tokens_out: 7, latency_ms: 1200.5 }));
    assert.equal(s.tokens_in, null);
    assert.equal(s.tokens_out, 7);
    assert.equal(s.latency_ms, 1200.5);
    const r = report('x', 't');
    r.scores.false_auto_resolutions = 1.5;
    assert.equal(extractSummary(r), null);
});
test('a good date beats garbage, missing is skipped, ties break by filename', () => {
    const out = buildSummary([
        { file: 'a.json', report: report('rules', '2026-10-27T10:00:00Z') },
        { file: 'b.json', report: report('rules', 'garbage', { cost_usd: '9.00' }) },
        { file: 'c.json', report: report('nano', undefined) },
        { file: 'd.json', report: report('super', '2026-10-27T10:00:00Z', { cost_usd: '1.00' }) },
        { file: 'e.json', report: report('super', '2026-10-27T10:00:00Z', { cost_usd: '2.00' }) },
    ]);
    assert.equal(out.pipelines.rules.cost_usd, null);
    assert.equal('nano' in out.pipelines, false);
    assert.equal(out.pipelines.super.cost_usd, '2.00');
});
test('pipeline names like __proto__ do not pollute', () => {
    const out = buildSummary([{ file: 'a', report: report('__proto__', '2026-10-27T10:00:00Z') }]);
    assert.equal(Object.keys(out.pipelines).length, 1);
    assert.equal(({}).dataset, undefined);
});
test('rejects malformed reports', () => {
    assert.equal(extractSummary({ pipeline: 'x' }), null);
    const r = report('x', 't');
    delete r.scores.match_recall;
    assert.equal(extractSummary(r), null);
});
test('latest result per pipeline wins, and the pipeline key is not repeated inside', () => {
    const out = buildSummary([
        { file: 'a', report: report('rules', '2026-10-27T10:00:00Z') },
        { file: 'b', report: report('rules', '2026-10-27T23:00:00Z', { cost_usd: '1.00' }) },
        { file: 'c', report: report('nano', '2026-10-26T10:00:00Z') },
        { file: 'd', report: { junk: true } },
    ]);
    assert.deepEqual(Object.keys(out.pipelines).sort(), ['nano', 'rules']);
    assert.equal(out.pipelines.rules.created_at, '2026-10-27T23:00:00Z');
    assert.equal(out.pipelines.rules.cost_usd, '1.00');
    assert.equal('pipeline' in out.pipelines.rules, false);
});
test('no reports gives an empty summary', () => {
    assert.deepEqual(Object.keys(buildSummary([]).pipelines), []);
});

test('a NaN or out-of-range ratio value makes the report unusable', () => {
    const ok = { hit: 1, total: 2, value: 0.5 };
    const mk = bad => ({ pipeline: 'rules', scores: { match_precision: bad, match_recall: ok, kind_accuracy: ok, correct_escalations: ok, entry_correctness: ok } });
    assert.equal(extractSummary(mk({ hit: 1, total: 2, value: NaN })), null);
    assert.equal(extractSummary(mk({ hit: 3, total: 2, value: 0.5 })), null);
    assert.equal(extractSummary(mk({ hit: 1, total: 2, value: 1.5 })), null);
    assert.equal(extractSummary(mk({ hit: 1, total: 2, value: 1 })), null);
    assert.equal(extractSummary(mk({ hit: 0, total: 0, value: 0.5 })), null);
});
test('an empty ratio (total 0) keeps value null, as scoring.py reports it', () => {
    const ok = { hit: 1, total: 2, value: 0.5 };
    const mk = bad => ({ pipeline: 'rules', scores: { match_precision: bad, match_recall: ok, kind_accuracy: ok, correct_escalations: ok, entry_correctness: ok, false_auto_resolutions: 0, final_difference: '0.00' } });
    assert.deepEqual(extractSummary(mk({ hit: 0, total: 0, value: null })).match_precision, { hit: 0, total: 0, value: null });
    assert.equal(extractSummary(mk({ hit: 0, total: 0, value: 0 })).match_precision.value, 0);
    assert.equal(extractSummary(mk({ hit: 1, total: 2, value: null })), null);
});

test('carries calls and price_placeholder_tiers, null when absent', () => {
    const a = extractSummary(report('ultra', '2026-10-27T00:00:00Z', { calls: 40, price_placeholder_tiers: ['ultra'] }));
    assert.equal(a.calls, 40);
    assert.deepEqual(a.price_placeholder_tiers, ['ultra']);
    const b = extractSummary(report('rules', '2026-10-27T00:00:00Z', { calls: null, calls_by_tier: null, steps: null }));
    assert.equal(b.calls, null);
    assert.equal(b.price_placeholder_tiers, null);
    assert.equal('steps' in b, false);
});
test('only timestamped result filenames are read', () => {
    for (const ok of ['20261029T092220Z-ultra.json', '20261027T233650Z-rules.json', '20261029T091551Z-some_tier.json']) assert.equal(isResultFile(ok), true, ok);
    for (const bad of ['ground_truth.json', 'notes.json', '20261029T092220Z-ultra.md', '20261029T092220Z-Ultra.json', '20261029T092220Z-ultra.json.bak', 'x20261029T092220Z-ultra.json', '20261029T092220Z-.json']) assert.equal(isResultFile(bad), false, bad);
});
