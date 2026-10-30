import assert from 'node:assert/strict';
import { test } from 'node:test';
import { afterReset, resetErrorText, resetKeepsText, resetSuccessText } from '../src/lib/demoReset.ts';

test('success text uses rules_kept with plurals', () => {
    assert.equal(resetSuccessText({ runs_deleted: 3, rules_kept: 1 }), 'Demo reset: 3 runs deleted. 1 learned rule kept for the next run.');
    assert.equal(resetSuccessText({ runs_deleted: 1, rules_kept: 2 }), 'Demo reset: 1 run deleted. 2 learned rules kept for the next run.');
    assert.equal(resetSuccessText({ runs_deleted: 1, rules_kept: 0 }), 'Demo reset: 1 run deleted. No learned rules to keep.');
});

test('reset dialog says learned rules are kept', () => {
    assert.equal(resetKeepsText(3), 'Your 3 learned rules are kept. The next run will use them.');
    assert.equal(resetKeepsText(1), 'Your 1 learned rule is kept. The next run will use it.');
    assert.match(resetKeepsText(0), /no learned rules yet/);
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
