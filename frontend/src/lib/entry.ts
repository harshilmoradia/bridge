// Draft journal entry editing: validation and the entry_override payload. Amounts stay decimal strings.
import { toCents } from './cents.ts';
import type { DecisionRequest, ProposedEntry } from '../api/types.ts';

export type EntryDraft = Pick<ProposedEntry, 'debit_account' | 'credit_account' | 'amount' | 'memo'>;

const AMOUNT_RE = /^\d{1,12}(\.\d{1,2})?$/; // numeric(14,2): up to 12 integer digits

export function validateEntry(d: EntryDraft): string | null {
    if (!d.debit_account.trim() || !d.credit_account.trim()) return 'Both accounts are required.';
    if (d.debit_account.trim() === d.credit_account.trim()) return 'Debit and credit accounts must differ.';
    if (!AMOUNT_RE.test(d.amount.trim()) || /^0+(\.0+)?$/.test(d.amount.trim())) return 'Amount must be positive, up to 12 digits and 2 decimals.';
    if (!d.memo.trim()) return 'A memo is required.';
    return null;
}

const normalize = (d: EntryDraft): EntryDraft => ({ debit_account: d.debit_account.trim(), credit_account: d.credit_account.trim(), amount: d.amount.trim(), memo: d.memo.trim() });

// Only send an override when the user actually changed something.
export function buildOverride(original: EntryDraft, draft: EntryDraft): DecisionRequest['entry_override'] {
    const next = normalize(draft);
    const o = normalize(original);
    const same = next.debit_account === o.debit_account && next.credit_account === o.credit_account && (AMOUNT_RE.test(next.amount) && AMOUNT_RE.test(o.amount) ? toCents(next.amount) === toCents(o.amount) : next.amount === o.amount) && next.memo === o.memo;
    return same ? undefined : next;
}
