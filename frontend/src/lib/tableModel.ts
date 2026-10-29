// Pure filter/sort logic for the reconciliation tables. Money stays a decimal string; compared as integer cents.
import { toCents } from './cents.ts';
import type { BankTransaction, GlEntry, ReconStatus } from '../api/types.ts';

export interface TxRow {
    id: string;
    date: string; // YYYY-MM-DD
    description: string;
    amount: string; // decimal string, signed
    type: string;
    status: ReconStatus;
    itemId: string | null;
    extra: string; // check number, counterparty... shown small and searchable
}

export type SortKey = 'date' | 'description' | 'type' | 'amount' | 'status';
export interface SortState { key: SortKey; dir: 'asc' | 'desc' }
export interface TableFilters { search: string; from: string; to: string; type: string; status: string }

export const emptyFilters: TableFilters = { search: '', from: '', to: '', type: '', status: '' };

export function filterRows(rows: TxRow[], f: TableFilters): TxRow[] {
    const q = f.search.trim().toLowerCase();
    return rows.filter(r => {
        if (f.from && r.date < f.from) return false;
        if (f.to && r.date > f.to) return false;
        if (f.type && r.type !== f.type) return false;
        if (f.status && r.status !== f.status) return false;
        if (!q) return true;
        const bare = q.replace(/[$,]/g, ''); // amounts typed as displayed: "1,850" or "$1,850.00"
        return [r.id, r.description, r.type, r.extra].some(s => s.toLowerCase().includes(q))
            || r.amount.includes(q) || (bare !== '' && r.amount.includes(bare));
    });
}

function compare(a: TxRow, b: TxRow, key: SortKey): number {
    if (key === 'amount') {
        const x = toCents(a.amount), y = toCents(b.amount);
        return x < y ? -1 : x > y ? 1 : 0;
    }
    return a[key].localeCompare(b[key]);
}

export function sortRows(rows: TxRow[], sort: SortState): TxRow[] {
    const sign = sort.dir === 'asc' ? 1 : -1;
    // Tie-break on id so the order is stable and deterministic.
    return [...rows].sort((a, b) => sign * compare(a, b, sort.key) || a.id.localeCompare(b.id));
}

export const distinct = (values: string[]) => [...new Set(values)].sort();

export const bankToRow = (r: BankTransaction): TxRow => ({
    id: r.txn_id, date: r.posted_date, description: r.description, amount: r.amount, type: r.type,
    status: r.recon_status, itemId: r.item_id, extra: r.check_number ? `check ${r.check_number}` : '',
});

export const glToRow = (r: GlEntry): TxRow => ({
    id: r.entry_id, date: r.date, description: r.description, amount: r.amount, type: r.method,
    status: r.recon_status, itemId: r.item_id, extra: [r.check_number && `check ${r.check_number}`, r.counterparty].filter(Boolean).join(' · '),
});

// Keep only selected ids that are still visible, so hidden rows never count as selected.
export function trimSelection(selected: ReadonlySet<string>, visible: TxRow[]): Set<string> {
    const ids = new Set(visible.map(r => r.id));
    return new Set([...selected].filter(id => ids.has(id)));
}
