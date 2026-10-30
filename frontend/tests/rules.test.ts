import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    accountsText, appliedRuleLabel, applyRules, decisionToastText, isRuleAutoResolved, isSeeded, learnableReason, learnedOnly, mockLearnable, notLearnedNote, patternText, rulePreview, ruleRows,
} from '../src/lib/rules.ts';
import { readFileSync } from 'node:fs';
import { postToStatement, settleRuleItems } from '../src/lib/statementPost.ts';
import { MOCK_EXTRA_ROWS } from '../src/api/mockExtras.ts';
import type { Item, Rule, Statement } from '../src/api/types.ts';

const item = (over: Partial<Item> = {}): Item => ({
    id: 'i1', run_id: 'r', kind: 'bank_fee_missing_in_gl', resolution: 'escalate', status: 'needs_approval', bank_ids: [], gl_ids: [], amount_delta: '-25.00', reasoning: '', evidence: [{ type: 'policy', id: 'p', note: null }],
    flags: [], model: null, confidence: null, rule_id: null, proposed_entry: null, created_at: 't', learnable: false, ...over,
});
const rule = (over: Partial<Rule> = {}): Rule => ({ id: 1, kind: 'bank_fee_missing_in_gl', pattern: { description_regex: 'FEE' }, action: { debit: '6800', credit: '1010' }, source_item: null, created_by: 'user:harshil', active: true, created_at: 't', ...over });

test('chip label needs the rule_applied flag', () => {
    assert.equal(appliedRuleLabel(item({ rule_id: 3 })), null);
    assert.equal(appliedRuleLabel(item({ flags: ['pii_redacted', 'rule_applied'], rule_id: 3 })), 'Applied rule #3');
    assert.equal(appliedRuleLabel(item({ flags: ['rule_applied'] })), 'Applied rule');
});

test('rule auto-resolved needs both status and flag', () => {
    assert.equal(isRuleAutoResolved(item({ status: 'auto_resolved', flags: ['rule_applied'] })), true);
    assert.equal(isRuleAutoResolved(item({ status: 'auto_resolved' })), false);
    assert.equal(isRuleAutoResolved(item({ flags: ['rule_applied'] })), false);
});

test('pattern and accounts text', () => {
    assert.equal(patternText({ description_regex: 'FEE' }), 'FEE');
    assert.equal(patternText({ a: 1, b: { c: 2 } }), 'a=1, b={"c":2}');
    assert.equal(patternText({}), '-');
    assert.ok(patternText({ description_regex: 'x'.repeat(5000) }).length <= 121);
    assert.equal(accountsText({ debit: '6800', credit: '1010' }), 'DR 6800 / CR 1010');
    assert.equal(accountsText({}), '-');
});

test('rule rows are sorted by id with readable fields', () => {
    const rows = ruleRows([rule({ id: 2 }), rule({ id: 1 })]);
    assert.deepEqual(rows.map(r => r.id), [1, 2]);
    assert.equal(rows[0].kind, 'bank fee missing in gl');
    assert.equal(rows[0].createdBy, 'harshil');
});

test('applyRules auto-resolves matching open items only', () => {
    const out = applyRules([item(), item({ id: 'i2', kind: 'check_number' }), item({ id: 'i3', status: 'approved' })], [rule({ id: 1 }), rule({ id: 9, kind: 'x', active: false })]);
    assert.equal(out[0].status, 'auto_resolved');
    assert.deepEqual(out[0].flags, ['rule_applied']);
    assert.equal(out[0].rule_id, 1);
    assert.ok(out[0].evidence.some(e => e.type === 'rule' && e.id === '1'));
    assert.equal(out[1].status, 'needs_approval');
    assert.equal(out[2].status, 'approved');
});

const learned = (over: Record<string, unknown> = {}) => ({ id: 1, kind: 'bank_fee_missing_in_gl', active: true, amount_sign: -1 as const, ...over });

test('applyRules skips never-by-rule kinds', () => {
    for (const kind of ['unknown', 'duplicate_gl_entry', 'unidentified_receipt', 'transposition']) {
        const [out] = applyRules([item({ kind })], [learned({ kind })]);
        assert.equal(out.status, 'needs_approval', kind);
    }
});

test('applyRules needs the amount sign to match', () => {
    const [opposite] = applyRules([item({ amount_delta: '25.00' })], [learned()]);
    assert.equal(opposite.status, 'needs_approval');
    const [same] = applyRules([item({ amount_delta: '-25.00' })], [learned()]);
    assert.equal(same.status, 'auto_resolved');
});

test('an inactive rule of the same kind leaves the item open', () => {
    const [out] = applyRules([item()], [learned({ active: false })]);
    assert.equal(out.status, 'needs_approval');
});

const dir = new URL('../src/api/fixtures/', import.meta.url);
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(new URL(name, dir), 'utf8'));
const mockItems = (): Item[] => [...fixture<Item[]>('items.json'), ...MOCK_EXTRA_ROWS.map(([n, kind, delta, account, memo]) => item({
    id: `x${n}`, kind, amount_delta: delta, proposed_entry: { id: `e${n}`, debit_account: account, credit_account: '1010', amount: delta.replace('-', ''), memo, status: 'draft' },
}))];

test('rule-resolved items post to the statement so the demo reaches 0.00', () => {
    const statement = fixture<Statement>('statement.json');
    assert.equal(statement.unreconciled_difference, '864.09');
    const items = applyRules(mockItems(), [learned({ kind: 'interest_missing_in_gl', amount_sign: 1 })]);
    settleRuleItems(statement, items);
    assert.equal(statement.unreconciled_difference, '845.00');
    for (const i of items.filter(i => i.status === 'needs_approval')) postToStatement(statement, i, i.amount_delta);
    assert.equal(statement.unreconciled_difference, '0.00');
});

const entry = { id: 'e', debit_account: '6800', credit_account: '1010', amount: '25.00', memo: 'fee', status: 'draft' };

test('learnable reason: none when learnable, else one line by cause', () => {
    assert.equal(learnableReason(item({ learnable: true, proposed_entry: entry })), null);
    assert.equal(learnableReason(item({ kind: 'duplicate_gl_entry', proposed_entry: entry })), "Duplicates and transpositions are one-off corrections, so Bridge won't learn a rule from them.");
    assert.equal(learnableReason(item({ kind: 'transposition', proposed_entry: entry })), "Duplicates and transpositions are one-off corrections, so Bridge won't learn a rule from them.");
    assert.match(learnableReason(item({ kind: 'unidentified_receipt', proposed_entry: entry }))!, /unidentified receipt/);
    assert.equal(learnableReason(item({ flags: ['injection_flagged'], kind: 'transposition' })), 'Flagged text never becomes a rule.');
    assert.match(learnableReason(item({ proposed_entry: null }))!, /no journal entry/);
    assert.match(learnableReason(item({ proposed_entry: entry }))!, /no bank or ledger text/);
});

test('mockLearnable mirrors the backend rule', () => {
    const open = item({ proposed_entry: entry, bank_ids: ['BANK032'] });
    assert.equal(mockLearnable(open), true);
    assert.equal(mockLearnable({ ...open, flags: ['injection_flagged'] }), false);
    assert.equal(mockLearnable({ ...open, kind: 'duplicate_gl_entry' }), false);
    assert.equal(mockLearnable({ ...open, proposed_entry: null }), false);
    assert.equal(mockLearnable({ ...open, bank_ids: [] }), false);
    assert.equal(mockLearnable({ ...open, status: 'approved' }), false);
});

test('rule preview keeps the decimal strings and reads the direction from the delta sign', () => {
    assert.deepEqual(rulePreview(item(), entry), { kind: 'bank_fee_missing_in_gl', direction: 'out', debit: '6800', credit: '1010', amount: '25.00' });
    assert.equal(rulePreview(item({ amount_delta: '12.50' }), entry)!.direction, 'in');
    assert.equal(rulePreview(item(), null), null);
});

test('decision toast claims a rule only when rule_id is set', () => {
    assert.equal(decisionToastText('Bank fee', 'approve', 3), 'Bank fee approved · Rule #3 saved');
    assert.equal(decisionToastText('Bank fee', 'approve', null), 'Bank fee approved');
    assert.equal(decisionToastText('Transposed amount', 'reject', null), 'Transposed amount rejected');
    assert.equal(notLearnedNote(true, 'approve', null), 'No rule was saved for this item.');
    assert.equal(notLearnedNote(true, 'approve', 3), null);
    assert.equal(notLearnedNote(false, 'approve', null), null);
});

test('seeded rules are kept apart from learned ones', () => {
    const list = [rule({ id: 1, origin: 'seeded' }), rule({ id: 2, origin: 'learned' }), rule({ id: 3 })];
    assert.equal(isSeeded(list[0]), true);
    assert.deepEqual(learnedOnly(list).map(r => r.id), [2, 3]);
});
