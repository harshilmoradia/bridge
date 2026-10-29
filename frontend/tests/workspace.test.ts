import assert from 'node:assert/strict';
import { test } from 'node:test';
import { interpolateMoney, isRunActive, isZeroMoney, itemsSignature, shouldRefreshOnComplete, needsApproval, nextHighlight } from '../src/lib/workspace.ts';

test('nextHighlight toggles and ignores rows without an item', () => {
    assert.equal(nextHighlight(null, 'i1'), 'i1');
    assert.equal(nextHighlight('i1', 'i1'), null);
    assert.equal(nextHighlight('i1', 'i2'), 'i2');
    assert.equal(nextHighlight('i1', null), 'i1');
});

test('isRunActive is true only while queued or running', () => {
    assert.equal(isRunActive('queued'), true);
    assert.equal(isRunActive('running'), true);
    assert.equal(isRunActive('completed'), false);
    assert.equal(isRunActive('failed'), false);
    assert.equal(isRunActive(undefined), false);
});

test('itemsSignature changes with a status change, not with order', () => {
    const a = [{ id: 'a', status: 'needs_approval' as const }, { id: 'b', status: 'matched' as const }];
    assert.equal(itemsSignature(a), itemsSignature([...a].reverse()));
    assert.notEqual(itemsSignature(a), itemsSignature([{ id: 'a', status: 'approved' }, a[1]]));
});

test('needsApproval filters by status', () => {
    assert.deepEqual(needsApproval([{ status: 'matched' as const }, { status: 'needs_approval' as const }]), [{ status: 'needs_approval' }]);
});

test('interpolateMoney works on cents and hits the endpoints exactly', () => {
    assert.equal(interpolateMoney('864.09', '0.00', 0), '864.09');
    assert.equal(interpolateMoney('864.09', '0.00', 1), '0.00');
    assert.equal(interpolateMoney('100.00', '0.00', 0.5), '50.00');
    assert.equal(interpolateMoney('0.00', '-25.00', 0.5), '-12.50');
    assert.equal(interpolateMoney('10.00', '20.00', 7), '20.00');
});

test('isZeroMoney rejects empty and malformed strings', () => {
    for (const bad of ['', ' ', '-', '.', 'abc', '0.0.0']) assert.equal(isZeroMoney(bad), false, bad);
});

test('shouldRefreshOnComplete fires once when the first poll is already completed', () => {
    assert.equal(shouldRefreshOnComplete('r1', 'r1', 'completed', null), true);
    assert.equal(shouldRefreshOnComplete('r1', 'r1', 'completed', 'r1'), false);
    assert.equal(shouldRefreshOnComplete('r1', 'r1', 'running', null), false);
    assert.equal(shouldRefreshOnComplete('r1', 'old', 'completed', null), false);
    assert.equal(shouldRefreshOnComplete(null, 'r1', 'completed', null), false);
});

test('isZeroMoney', () => {
    assert.equal(isZeroMoney('0.00'), true);
    assert.equal(isZeroMoney('-0.00'), true);
    assert.equal(isZeroMoney('0.01'), false);
});
