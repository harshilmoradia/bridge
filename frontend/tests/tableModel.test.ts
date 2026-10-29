import assert from 'node:assert/strict';
import { test } from 'node:test';
import { emptyFilters, filterRows, sortRows, trimSelection, type TxRow } from '../src/lib/tableModel.ts';

const row = (id: string, date: string, amount: string, over: Partial<TxRow> = {}): TxRow =>
    ({ id, date, description: `desc ${id}`, amount, type: 'ACH', status: 'unmatched', itemId: null, extra: '', ...over });

const rows = [
    row('A', '2026-10-03', '-1850.00', { type: 'CHECK', extra: 'check 2847' }),
    row('B', '2026-10-01', '9.99', { status: 'matched' }),
    row('C', '2026-10-05', '-25.00', { description: 'MONTHLY SERVICE FEE', type: 'FEE' }),
    row('D', '2026-10-05', '100000.00'),
];

test('sorts amounts numerically via cents, not as strings', () => {
    assert.deepEqual(sortRows(rows, { key: 'amount', dir: 'asc' }).map(r => r.id), ['A', 'C', 'B', 'D']);
    assert.deepEqual(sortRows(rows, { key: 'amount', dir: 'desc' }).map(r => r.id), ['D', 'B', 'C', 'A']);
});

test('sorts by date with id tie-break', () => {
    assert.deepEqual(sortRows(rows, { key: 'date', dir: 'asc' }).map(r => r.id), ['B', 'A', 'C', 'D']);
    assert.deepEqual(sortRows(rows, { key: 'date', dir: 'desc' }).map(r => r.id), ['C', 'D', 'A', 'B']);
});

test('date range is inclusive', () => {
    assert.deepEqual(filterRows(rows, { ...emptyFilters, from: '2026-10-03', to: '2026-10-05' }).map(r => r.id), ['A', 'C', 'D']);
    assert.deepEqual(filterRows(rows, { ...emptyFilters, to: '2026-10-01' }).map(r => r.id), ['B']);
});

test('type and status filters combine', () => {
    assert.deepEqual(filterRows(rows, { ...emptyFilters, type: 'ACH', status: 'matched' }).map(r => r.id), ['B']);
    assert.deepEqual(filterRows(rows, { ...emptyFilters, status: 'approved' }), []);
});

test('search matches description, amount, id and extra, case-insensitively', () => {
    assert.deepEqual(filterRows(rows, { ...emptyFilters, search: 'service fee' }).map(r => r.id), ['C']);
    assert.deepEqual(filterRows(rows, { ...emptyFilters, search: '1850' }).map(r => r.id), ['A']);
    assert.deepEqual(filterRows(rows, { ...emptyFilters, search: '2847' }).map(r => r.id), ['A']);
    assert.deepEqual(filterRows(rows, { ...emptyFilters, search: 'zzz' }), []);
});

test('search matches amounts typed as displayed', () => {
    const one = [row('X', '2026-10-01', '-1850.00')];
    assert.equal(filterRows(one, { ...emptyFilters, search: '1,850' }).length, 1);
    assert.equal(filterRows(one, { ...emptyFilters, search: '$1,850.00' }).length, 1);
    assert.equal(filterRows(one, { ...emptyFilters, search: '-$1,850' }).length, 1);
    assert.equal(filterRows(one, { ...emptyFilters, search: '1,900' }).length, 0);
});

test('trimSelection drops rows hidden by filters', () => {
    const visible = filterRows(rows, { ...emptyFilters, type: 'ACH' });
    assert.deepEqual([...trimSelection(new Set(['A', 'B', 'D']), visible)].sort(), ['B', 'D']);
    assert.equal(trimSelection(new Set(['A']), []).size, 0);
});
