import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildOverride, validateEntry } from '../src/lib/entry.ts';

const base = { debit_account: '6800', credit_account: '1010', amount: '25.00', memo: 'Fee' };

test('validateEntry accepts a good draft', () => assert.equal(validateEntry(base), null));
test('validateEntry rejects bad drafts', () => {
    for (const bad of [{ amount: '' }, { amount: '0.00' }, { amount: '-5' }, { amount: '1.234' }, { amount: '1e3' }, { amount: '1000000000000' }, { debit_account: '' }, { credit_account: '6800' }, { memo: ' ' }]) {
        assert.notEqual(validateEntry({ ...base, ...bad }), null, JSON.stringify(bad));
    }
});
test('buildOverride is undefined when unchanged and trimmed when changed', () => {
    assert.equal(buildOverride(base, { ...base, memo: ' Fee ' }), undefined);
    assert.deepEqual(buildOverride(base, { ...base, amount: ' 30.00 ' }), { ...base, amount: '30.00' });
});
test('buildOverride compares amounts as cents', () => {
    assert.equal(buildOverride(base, { ...base, amount: '25' }), undefined);
    assert.equal(buildOverride(base, { ...base, amount: '25.0' }), undefined);
    assert.notEqual(buildOverride(base, { ...base, amount: '25.01' }), undefined);
});
test('validateEntry accepts the largest numeric(14,2) amount', () => assert.equal(validateEntry({ ...base, amount: '999999999999.99' }), null));
