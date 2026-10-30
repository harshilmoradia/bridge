import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { accountName, inTab, isTypingTarget, kindTitle, modelTier, nextSelection, stepSelection } from '../src/lib/inbox.ts';
import type { ReconStatus } from '../src/api/types.ts';

const withStatus = (status: ReconStatus, id = status) => ({ id, status });

test('tabs split items by status', () => {
    const items = (['needs_approval', 'auto_resolved', 'reconciling_item', 'approved', 'rejected', 'matched'] as ReconStatus[]).map(s => withStatus(s));
    assert.deepEqual(inTab(items, 'pending').map(i => i.id), ['needs_approval']);
    assert.deepEqual(inTab(items, 'policy').map(i => i.id), ['auto_resolved', 'reconciling_item']);
    assert.deepEqual(inTab(items, 'decided').map(i => i.id), ['approved', 'rejected']);
});

test('kind titles are readable, unknown kinds fall back to spaced text', () => {
    assert.equal(kindTitle('bank_fee_missing_in_gl'), 'Bank fee missing in ledger');
    assert.equal(kindTitle('brand_new_kind'), 'brand new kind');
});

test('selection stays put, then takes the next item at the same position', () => {
    assert.equal(nextSelection(['a', 'b', 'c'], 'b', 1), 'b');
    assert.equal(nextSelection(['a', 'c'], 'b', 1), 'c');
    assert.equal(nextSelection(['a'], 'c', 2), 'a');
    assert.equal(nextSelection([], 'a', 0), null);
    assert.equal(nextSelection(['a', 'b'], null, -1), 'a');
});

test('J/K movement clamps at the ends', () => {
    assert.equal(stepSelection(['a', 'b'], 'a', 1), 'b');
    assert.equal(stepSelection(['a', 'b'], 'b', 1), 'b');
    assert.equal(stepSelection(['a', 'b'], 'a', -1), 'a');
    assert.equal(stepSelection(['a', 'b'], 'zzz', 1), 'a');
    assert.equal(stepSelection([], 'a', 1), null);
});

test('account names match the demo chart of accounts', () => {
    const csv = readFileSync(new URL('../../demo-data/chart_of_accounts.csv', import.meta.url), 'utf8').trim().split('\n').slice(1);
    for (const line of csv) {
        const [account, name] = line.split(',');
        assert.equal(accountName(account!), name, account);
    }
    assert.equal(accountName('9999'), null);
});

test('model tier comes from the model id', () => {
    assert.equal(modelTier('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'), 'nano');
    assert.equal(modelTier('nvidia/nemotron-3-super-120b-a12b'), 'super');
    assert.equal(modelTier('nvidia/Nemotron-3-Ultra-550b-a55b'), 'ultra');
    assert.equal(modelTier(null), 'code');
});

test('shortcuts are suppressed while typing', () => {
    assert.equal(isTypingTarget({ tagName: 'INPUT' }), true);
    assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'date' }), true);
    assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'checkbox' }), false);
    assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'radio' }), false);
    assert.equal(isTypingTarget({ tagName: 'DIV', isContentEditable: true }), true);
    assert.equal(isTypingTarget({ tagName: 'BUTTON' }), false);
    assert.equal(isTypingTarget(null), false);
});
