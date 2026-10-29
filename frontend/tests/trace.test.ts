import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { actorLabel, auditView, formatDuration, runDurationMs, sortAudit, traceTotals } from '../src/lib/trace.ts';
import type { AuditEntry, Run } from '../src/api/types.ts';

const done = JSON.parse(readFileSync(new URL('../src/api/fixtures/run-completed.json', import.meta.url), 'utf8')) as Run;
const entry = (id: number, created_at: string): AuditEntry => ({ id, run_id: 'r', entity_type: 'item', entity_id: 'i1', action: 'decision_approved', actor: 'user:demo', model: null, detail: {}, created_at });

test('totals add tokens and model latency, ignoring code steps', () => {
    const totals = traceTotals(done.steps);
    assert.equal(totals.steps, done.steps.length);
    assert.equal(totals.modelSteps, 6);
    assert.equal(totals.tokensIn, 32080);
    assert.equal(totals.tokensOut, 5816);
    assert.equal(totals.modelLatencyMs, 70920);
    assert.equal(totals.failed, 0);
});

test('totals treat null tokens as zero and count failures', () => {
    const steps = [{ ...done.steps[0], status: 'failed' as const, tokens_in: null, tokens_out: null }];
    const totals = traceTotals(steps);
    assert.equal(totals.tokensIn, 0);
    assert.equal(totals.failed, 1);
    assert.deepEqual(traceTotals([]), { steps: 0, modelSteps: 0, tokensIn: 0, tokensOut: 0, modelLatencyMs: 0, failed: 0 });
});

test('durations format as ms, seconds and minutes', () => {
    assert.equal(formatDuration(412), '412 ms');
    assert.equal(formatDuration(2500), '2.5 s');
    assert.equal(formatDuration(135_000), '2 min 15 s');
    assert.equal(formatDuration(999), '999 ms');
    assert.equal(formatDuration(1000), '1.0 s');
    assert.equal(formatDuration(119_600), '2 min 0 s');
    assert.equal(formatDuration(59_960), '1 min 0 s');
});

test('run duration is null while in flight or when dates are bad', () => {
    const base = { created_at: '2026-10-26T15:00:00Z', updated_at: '2026-10-26T15:00:30Z' };
    assert.equal(runDurationMs({ ...base, status: 'completed' }), 30_000);
    assert.equal(runDurationMs({ ...base, status: 'running' }), null);
    assert.equal(runDurationMs({ created_at: 'x', updated_at: 'y', status: 'failed' }), null);
    assert.equal(runDurationMs({ created_at: base.updated_at, updated_at: base.created_at, status: 'completed' }), null);
});

test('audit rows: actor label and ordering', () => {
    assert.equal(actorLabel('agent:resolver'), 'resolver');
    assert.equal(actorLabel('system'), 'system');
    const sorted = sortAudit([entry(3, '2026-10-26T15:02:00Z'), entry(2, '2026-10-26T15:01:00Z'), entry(1, '2026-10-26T15:01:00Z')]);
    assert.deepEqual(sorted.map(e => e.id), [1, 2, 3]);
});

const fixtureAudit = JSON.parse(readFileSync(new URL('../src/api/fixtures/run-audit.json', import.meta.url), 'utf8')) as AuditEntry[];

test('audit view: human labels for the known actions', () => {
    const [flag, scan, plain, remembered] = fixtureAudit.map(auditView);
    assert.equal(flag.title, 'Injection flagged on BANK074: addresses ai, blanket action, override instructions, role marker');
    assert.equal(scan.title, 'Guard scan: 12 rows masked, 1 flagged');
    assert.equal(plain.title, 'Approved item 10904d8a');
    assert.deepEqual(plain.fields, []);
    assert.equal(remembered.title, 'Approved item 2effafb6 (remembered rule)');
    assert.deepEqual(remembered.fields, [['Note', 'Confirmed with the bank on [PHONE]'], ['Entry', 'DR 6800 / CR 1010, 25.00, Monthly service fee']]);
});

test('audit view: reject, singular counts and unknown actions fall back to key/value text', () => {
    const base = fixtureAudit[2];
    assert.equal(auditView({ ...base, action: 'reject' }).title, 'Rejected item 10904d8a');
    assert.equal(auditView({ ...fixtureAudit[1], detail: { masked_rows: 1, flagged_rows: [] } }).title, 'Guard scan: 1 row masked, 0 flagged');
    const unknown = auditView({ ...base, entity_type: 'rule', action: 'rule_created', entity_id: '7', detail: { n: 2, tags: ['a', 'b'], nested: { x: '<b>hi</b>' }, none: null } });
    assert.equal(unknown.title, 'rule rule created (7)');
    assert.deepEqual(unknown.fields, [['n', '2'], ['tags', 'a, b'], ['nested', '{"x":"<b>hi</b>"}'], ['none', '-']]);
    // malformed detail on a known action also falls back instead of throwing
    assert.equal(auditView({ ...base, detail: {} }).title, 'Approved item 10904d8a');
    assert.equal(auditView({ ...fixtureAudit[0], detail: {} }).title, 'Injection flagged on BANK074');
});

test('a malformed detail or entity_id falls back instead of throwing', () => {
    const base = entry(1, '2026-10-26T15:00:00Z');
    for (const [type, action] of [['guardrail', 'injection_flagged'], ['run', 'guard_scan'], ['item', 'approve'], ['x', 'y']]) {
        const e = { ...base, entity_type: type, action };
        assert.equal(typeof auditView({ ...e, detail: null as never }).title, 'string');
        assert.equal(typeof auditView({ ...e, detail: undefined as never, entity_id: 42 as never }).title, 'string');
    }
});
test('generic fields cap long arrays and strings', () => {
    const e = { ...entry(1, '2026-10-26T15:00:00Z'), entity_type: 'x', action: 'y' };
    const big = auditView({ ...e, detail: { ids: Array.from({ length: 5000 }, (_, i) => `id${i}`) } }).fields[0][1];
    assert.ok(big.length < 1000);
    assert.ok(big.endsWith('more)'));
    const long = auditView({ ...e, detail: { s: 'a'.repeat(5000) } }).fields[0][1];
    assert.ok(long.length < 600);
});

test('audit view bounds hostile detail: huge note, 5000 reasons, 5000 keys, long id and action', () => {
    const base = { ...entry(1, '2026-01-01T00:00:00Z') };
    const note = auditView({ ...base, action: 'approve', detail: { note: 'x'.repeat(100_000) } });
    assert.ok(note.fields[0][1].length <= 501);
    const reasons = auditView({ ...base, entity_type: 'guardrail', action: 'injection_flagged', detail: { reasons: Array.from({ length: 5000 }, (_, i) => `r${i}`) } });
    assert.ok(reasons.title.length < 600);
    assert.match(reasons.title, /\+4980 more/);
    const detail = Object.fromEntries(Array.from({ length: 5000 }, (_, i) => [`k${i}`, i]));
    const generic = auditView({ ...base, entity_type: 'thing', action: 'x'.repeat(5000), entity_id: 'i'.repeat(5000), detail });
    assert.equal(generic.fields.length, 21);
    assert.match(generic.fields[20][0], /\+4980 more/);
    assert.ok(generic.title.length < 1200);
});
