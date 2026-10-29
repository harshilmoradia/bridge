import assert from 'node:assert/strict';
import { test } from 'node:test';
import { afterReset, resetErrorText, resetSuccessText } from '../src/lib/demoReset.ts';

test('success text shows both counts with plurals', () => {
    assert.equal(resetSuccessText({ runs_deleted: 3, rules_deleted: 1 }), 'Demo reset: 3 runs and 1 learned rule deleted.');
    assert.equal(resetSuccessText({ runs_deleted: 1, rules_deleted: 0 }), 'Demo reset: 1 run and 0 learned rules deleted.');
});

test('error codes map to friendly text', () => {
    assert.match(resetErrorText({ code: 'demo_reset_disabled', message: 'x' }), /turned off/);
    assert.match(resetErrorText({ code: 'network_error', message: 'x' }), /Could not reach/);
    assert.equal(resetErrorText({ code: 'boom', message: 'bad' }), 'Could not reset the demo: bad');
    assert.equal(resetErrorText({ message: 'bad' }), 'Could not reset the demo: bad');
});

test('unauthenticated maps to a sign-in prompt', () => {
    assert.equal(resetErrorText({ code: 'unauthenticated', message: 'x' }), 'Sign in to reset the demo.');
});

test('afterReset clears page state before invalidating', () => {
    const calls: string[] = [];
    afterReset(() => calls.push('clear'), () => calls.push('invalidate'));
    assert.deepEqual(calls, ['clear', 'invalidate']);
});
