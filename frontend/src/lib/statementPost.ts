// Mock only: posting an item to the statement, as the backend does for approved and auto_resolved items.
import type { Item, Statement } from '../api/types.ts';
import { fromCents, toCents } from './cents.ts';

/** Adds the item's adjustment to the book side and moves the unreconciled difference toward 0.00. */
export function postToStatement(statement: Statement, item: Item, delta: string): void {
    statement.book.lines.push({ item_id: item.id, kind: item.kind, label: item.proposed_entry?.memo ?? item.kind, amount: delta, status: item.status, applied: true, bank_ids: item.bank_ids, gl_ids: item.gl_ids });
    statement.book.adjusted_balance = fromCents(toCents(statement.book.adjusted_balance) + toCents(delta));
    statement.unreconciled_difference = fromCents(toCents(statement.unreconciled_difference) - toCents(delta));
}

/** Posts every rule-resolved item of a fresh run; the backend counts auto_resolved as posted. */
export function settleRuleItems(statement: Statement, items: Item[]): void {
    for (const item of items) if (item.status === 'auto_resolved' && item.flags.includes('rule_applied')) postToStatement(statement, item, item.amount_delta);
}
