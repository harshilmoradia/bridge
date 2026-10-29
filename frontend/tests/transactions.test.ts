import assert from 'node:assert/strict';
import { test } from 'node:test';
import { approveOne, approveVisible, filterTransactions, getCounts, parseLedger, selectVisible, type Ledger, type Transaction } from '../src/lib/transactions.ts';

const transaction = (id: number, values: Partial<Transaction> = {}): Transaction => ({
    id, type: 'Bank-to-Bill', name: 'AWS', icon: 'ri-file-line', amount: '-$100', evidence: 'Invoice',
    mappedTo: 'Software Subscriptions', confidence: 98, status: 'Ready to Approve', isException: false,
    selected: false, date: 'Oct 08, 2026', ...values,
});
const log = { id: 'approval-1', action: 'Approved', user: 'Demo', time: 'Just now' };

test('select all only selects eligible search results in the current tab', () => {
    const rows = [transaction(1), transaction(2, { name: 'Coffee' }), transaction(3, { type: 'Card Recon' }),
        transaction(4, { status: 'Approved' }), transaction(5, { status: 'Exception', isException: true }),
        transaction(6, { mappedTo: 'Pending' })];
    assert.deepEqual(selectVisible(rows, 'bank-to-bill', ' aws ', true).filter(tx => tx.selected).map(tx => tx.id), [1]);
    assert.equal(rows[0].selected, false);
});

test('bulk approval cannot approve hidden selections, exceptions, or approved rows', () => {
    const ledger: Ledger = { transactions: [transaction(1, { selected: true }), transaction(2, { selected: true, name: 'Coffee' }),
        transaction(3, { selected: true, type: 'Card Recon' }), transaction(4, { selected: true, isException: true, status: 'Exception' }),
        transaction(5, { selected: true, status: 'Approved' })], auditLogs: [] };
    const result = approveVisible(ledger, 'bank-to-bill', 'AWS', log);
    assert.deepEqual(result.transactions.map(tx => tx.status), ['Approved', 'Ready to Approve', 'Ready to Approve', 'Exception', 'Approved']);
    assert.equal(result.transactions[4].selected, true);
    assert.equal(result.auditLogs.length, 1);
    assert.equal(approveVisible(result, 'bank-to-bill', 'AWS', log), result);
});

test('manual approval preserves the chosen account and original confidence', () => {
    const ledger: Ledger = { transactions: [transaction(1, { status: 'Exception', isException: true, confidence: 45 })], auditLogs: [] };
    const result = approveOne(ledger, 1, 'Travel & Entertainment', log);
    assert.equal(result.transactions[0].mappedTo, 'Travel & Entertainment');
    assert.equal(result.transactions[0].confidence, 45);
    assert.equal(result.transactions[0].isException, false);
    assert.equal(approveOne(result, 1, 'Office Supplies', log), result);
    assert.equal(approveOne(ledger, 1, 'Needs mapping', log), ledger);
});

test('dashboard counts track approvals and exceptions including a completed queue', () => {
    const rows = [transaction(1), transaction(2, { status: 'Exception', isException: true }), transaction(3, { status: 'Approved' })];
    assert.deepEqual(getCounts(rows), { drafted: 1, exceptions: 1, approved: 1 });
    assert.deepEqual(getCounts([transaction(1, { status: 'Approved' })]), { drafted: 0, exceptions: 0, approved: 1 });
    assert.equal(filterTransactions(rows, 'exception-queue').length, 1);
});

test('saved demo ledger restores approvals and audit history without stale selections', () => {
    const ledger: Ledger = { transactions: [transaction(1, { selected: true }), transaction(2, { status: 'Approved' })], auditLogs: [log] };
    const restored = parseLedger(JSON.stringify(ledger));
    assert.equal(restored?.transactions[0].selected, false);
    assert.equal(restored?.transactions[1].status, 'Approved');
    assert.deepEqual(restored?.auditLogs, [log]);
    for (const raw of [null, 'invalid', '{}', JSON.stringify({ ...ledger, transactions: [transaction(1), transaction(1)] }),
        JSON.stringify({ ...ledger, transactions: [{ id: 1 }] })]) assert.equal(parseLedger(raw), null);
});
