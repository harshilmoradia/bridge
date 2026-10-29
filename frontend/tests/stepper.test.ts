import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { formatLatency, formatTokens, groupSteps, stepDetail, stepsDone, STEP_STATUS_LABEL } from '../src/lib/stepper.ts';
import { MockRunPoller, mockStageCount, runAtStage } from '../src/api/mockProgress.ts';
import type { Run } from '../src/api/types.ts';

const done = JSON.parse(readFileSync(new URL('../src/api/fixtures/run-completed.json', import.meta.url), 'utf8')) as Run;

test('status labels cover every step status', () => {
    assert.deepEqual(STEP_STATUS_LABEL, { pending: 'Pending', running: 'Running', completed: 'Complete', failed: 'Failed' });
});

test('null latency shows "code" for code tier, never 0 ms', () => {
    assert.equal(formatLatency({ status: 'completed', tier: 'code', latency_ms: null }), 'code');
    assert.equal(formatLatency({ status: 'completed', tier: 'nano', latency_ms: null }), '-');
    assert.equal(formatLatency({ status: 'pending', tier: 'code', latency_ms: null }), '-');
    assert.equal(formatLatency({ status: 'running', tier: 'super', latency_ms: null }), 'running');
});

test('latency formats as ms under a second and seconds above', () => {
    assert.equal(formatLatency({ status: 'completed', tier: 'code', latency_ms: 412 }), '412 ms');
    assert.equal(formatLatency({ status: 'completed', tier: 'nano', latency_ms: 2830 }), '2.8 s');
});

test('tokens are null when absent and formatted when present', () => {
    assert.equal(formatTokens({ tokens_in: null, tokens_out: null }), null);
    assert.equal(formatTokens({ tokens_in: 14200, tokens_out: 3900 }), '14,200 in / 3,900 out');
});

test('failed steps show their error message', () => {
    assert.equal(stepDetail({ status: 'failed', output_summary: null, error: { code: 'x', message: 'boom' } }), 'boom');
    assert.equal(stepDetail({ status: 'failed', output_summary: null, error: null }), 'This step failed.');
    assert.equal(stepDetail({ status: 'completed', output_summary: '9 items', error: null }), '9 items');
});

test('steps sharing a position group together, in position order', () => {
    const groups = groupSteps([...done.steps].reverse());
    assert.deepEqual(groups.map(g => g.position), [1, 2, 3, 4, 5, 6, 7, 8]);
    assert.deepEqual(groups[3].steps.map(s => s.id), ['classify', 'match-fuzzy']);
    assert.equal(groups.filter(g => g.steps.length > 1).length, 1);
});

test('a run with no steps has no groups', () => {
    assert.deepEqual(groupSteps([]), []);
});

test('mock progression advances one stage at a time and ends completed', () => {
    const total = mockStageCount(done);
    assert.equal(total, 8);
    const start = runAtStage(done, 0);
    assert.equal(start.status, 'running');
    assert.equal(stepsDone(start.steps), 0);
    assert.equal(start.steps.find(s => s.id === 'load')?.status, 'running');
    assert.equal(start.steps.find(s => s.id === 'guard')?.status, 'pending');
    assert.equal(start.steps.every(s => s.latency_ms === null && s.output_summary === null), true);

    const mid = runAtStage(done, 3);
    assert.deepEqual(mid.steps.filter(s => s.status === 'completed').map(s => s.id), ['load', 'guard', 'match-rules']);
    assert.deepEqual(mid.steps.filter(s => s.status === 'running').map(s => s.id), ['classify', 'match-fuzzy']);
    assert.equal(mid.steps.find(s => s.id === 'load')?.latency_ms, 412);
    assert.equal(mid.steps.find(s => s.id === 'resolve')?.status, 'pending');

    let previous = -1;
    for (let n = 0; n <= total; n++) {
        const count = stepsDone(runAtStage(done, n).steps);
        assert.ok(count > previous);
        previous = count;
    }
    const finished = runAtStage(done, total);
    assert.equal(finished.status, 'completed');
    assert.equal(stepsDone(finished.steps), done.steps.length);
    assert.equal(finished.counts.needs_approval, 5);
});

test('mock progression does not mutate the fixture', () => {
    const before = JSON.stringify(done);
    runAtStage(done, 2);
    assert.equal(JSON.stringify(done), before);
});

test('only polls for the current run id advance the mock stages', () => {
    const poller = new MockRunPoller(done.id, mockStageCount(done));
    poller.start('new-run');
    const old = poller.poll(done, done.id);
    assert.equal(old.status, 'completed');
    assert.equal(old.id, done.id);
    const first = poller.poll(done, 'new-run');
    assert.equal(first.id, 'new-run');
    assert.equal(first.status, 'running');
    assert.equal(stepsDone(first.steps), 0); // still stage 0 after the old id was read
    assert.equal(stepsDone(poller.poll(done, 'new-run').steps), 1);
});

test('the mock run finishes after one poll per stage, then stays completed', () => {
    const poller = new MockRunPoller(done.id, mockStageCount(done));
    poller.start('r');
    for (let n = 0; n < mockStageCount(done); n++) assert.equal(poller.poll(done, 'r').status, 'running');
    assert.equal(poller.active, false);
    assert.equal(poller.poll(done, 'r').status, 'completed');
});
