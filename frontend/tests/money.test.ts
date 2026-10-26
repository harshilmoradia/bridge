import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fromCents, toCents } from '../src/lib/cents.ts';
import { formatMoney, isNegative } from '../src/lib/money.ts';

test('formatMoney edge values', () => {
    assert.equal(formatMoney('0.00'), '$0.00');
    assert.equal(formatMoney('1234567.89'), '$1,234,567.89');
    assert.equal(formatMoney('-1000'), '-$1,000.00');
    assert.equal(formatMoney('999.9'), '$999.90');
    assert.equal(formatMoney('+12.00'), '$12.00');
    assert.equal(formatMoney('-0.00'), '$0.00');
});

test('isNegative treats negative zero as zero', () => {
    assert.equal(isNegative('-0.00'), false);
    assert.equal(isNegative('-0.01'), true);
    assert.equal(isNegative('5.00'), false);
});

test('cents arithmetic matches the approve flow (864.09 -> 889.09)', () => {
    assert.equal(fromCents(toCents('864.09') - toCents('-25.00')), '889.09');
    assert.equal(fromCents(toCents('47683.90') + toCents('-25.00')), '47658.90');
    assert.equal(fromCents(toCents('-0.05')), '-0.05');
    assert.equal(fromCents(0n), '0.00');
});
