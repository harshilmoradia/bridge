// Pure logic for the approval inbox: tabs, titles, selection after a decision, account names, model tiers.
import type { Item, ModelTier, ReconStatus } from '../api/types.ts';

export type InboxTab = 'pending' | 'policy' | 'decided';

const TAB_STATUSES: Record<InboxTab, ReconStatus[]> = {
    pending: ['needs_approval'],
    policy: ['auto_resolved', 'reconciling_item'],
    decided: ['approved', 'rejected'],
};

export const inTab = <T extends Pick<Item, 'status'>>(items: T[], tab: InboxTab) => items.filter(i => TAB_STATUSES[tab].includes(i.status));

export function focusInboxItem(items: Pick<Item, 'id' | 'status'>[], id: string): { tab: InboxTab; index: number } | null {
    const item = items.find(candidate => candidate.id === id);
    if (!item) return null;
    const tab: InboxTab = item.status === 'needs_approval' ? 'pending'
        : item.status === 'auto_resolved' || item.status === 'reconciling_item' ? 'policy' : 'decided';
    const index = inTab(items, tab).findIndex(candidate => candidate.id === id);
    return index < 0 ? null : { tab, index };
}

const KIND_TITLE: Record<string, string> = {
    exact: 'Exact match',
    timing: 'Timing difference',
    check_number: 'Check number match',
    one_to_many: 'One-to-many match',
    rounding: 'Rounding difference',
    nsf_pair: 'Returned deposit (NSF)',
    outstanding_check: 'Outstanding check',
    deposit_in_transit: 'Deposit in transit',
    bank_fee_missing_in_gl: 'Bank fee missing in ledger',
    interest_missing_in_gl: 'Interest missing in ledger',
    duplicate_gl_entry: 'Duplicate ledger entry',
    transposition: 'Transposed amount',
    unidentified_receipt: 'Unidentified receipt',
    unknown: 'Unclassified item',
};

export const kindTitle = (kind: string) => KIND_TITLE[kind] ?? kind.replaceAll('_', ' ');

// Keep the cursor at the same position when the selected item leaves the list, clamped to the new end.
export function nextSelection(ids: string[], selected: string | null, lastIndex: number): string | null {
    if (ids.length === 0) return null;
    if (selected && ids.includes(selected)) return selected;
    return ids[Math.min(Math.max(lastIndex, 0), ids.length - 1)]!;
}

// J/K movement through the list; stops at either end.
export function stepSelection(ids: string[], selected: string | null, step: 1 | -1): string | null {
    if (ids.length === 0) return null;
    const at = selected ? ids.indexOf(selected) : -1;
    if (at === -1) return ids[0]!;
    return ids[Math.min(ids.length - 1, Math.max(0, at + step))]!;
}

// Mirrors demo-data/chart_of_accounts.csv, for display labels only. Unknown accounts show their number alone.
const ACCOUNT_NAMES: Record<string, string> = {
    '1010': 'Operating Cash', '1020': 'Savings', '1200': 'Accounts Receivable', '1300': 'Prepaid Expenses',
    '1350': 'Employee Advances', '1500': 'Equipment', '2000': 'Accounts Payable', '2300': 'Customer Deposits',
    '2400': 'Suspense - Unapplied Cash', '4000': 'Sales Revenue', '4100': 'Interest Income', '4200': 'Other Income',
    '4900': 'Sales Returns & Refunds', '5000': 'Inventory Purchases', '6000': 'Rent & Lease', '6100': 'Utilities',
    '6150': 'Phone & Internet', '6200': 'Payroll Expense', '6210': 'Payroll Taxes', '6300': 'Professional Fees',
    '6400': 'Marketing', '6500': 'Office Supplies', '6510': 'Software & Subscriptions', '6600': 'Repairs & Maintenance',
    '6700': 'Insurance', '6750': 'Travel & Meals', '6760': 'Training & Development', '6800': 'Bank Fees',
    '6850': 'Freight & Shipping', '6900': 'Charitable Contributions', '6950': 'Late Fees & Penalties', '6990': 'Rounding & Miscellaneous',
};

export const accountName = (account: string) => ACCOUNT_NAMES[account.trim()] ?? null;

// Model ids name their tier (nano, super, ultra); items without a model were handled by code.
export function modelTier(model: string | null): ModelTier {
    const m = (model ?? '').toLowerCase();
    if (m.includes('nano')) return 'nano';
    if (m.includes('ultra')) return 'ultra';
    if (m.includes('super')) return 'super';
    return 'code';
}

const NON_TEXT_INPUTS = ['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'];

// Shortcuts only fire when focus is not in a text field and no dialog is open. Checkboxes and switches are not text fields.
export function isTypingTarget(target: { tagName?: string; type?: string; isContentEditable?: boolean } | null): boolean {
    if (!target) return false;
    if (target.isContentEditable === true || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return true;
    return target.tagName === 'INPUT' && !NON_TEXT_INPUTS.includes((target.type ?? 'text').toLowerCase());
}
