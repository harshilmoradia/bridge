export type TabId = 'dashboard' | 'bank-to-bill' | 'card-recon' | 'accruals' | 'exception-queue' | 'audit-trail';

export interface Transaction {
    id: number;
    type: 'Bank-to-Bill' | 'Card Recon' | 'Accrual';
    name: string;
    icon: string;
    amount: string;
    evidence: string;
    mappedTo: string;
    confidence: number;
    status: 'Ready to Approve' | 'Exception' | 'Approved';
    isException: boolean;
    selected: boolean;
    date: string;
    explanation?: string;
}

export interface AuditLog {
    id: string;
    action: string;
    user: string;
    time: string;
}

export interface Ledger {
    transactions: Transaction[];
    auditLogs: AuditLog[];
}

export const isValidMapping = (mapping: string) =>
    mapping.trim().length > 0 && !['Needs mapping', 'Pending'].includes(mapping.trim());

export const canBulkApprove = (tx: Transaction) =>
    !tx.isException && tx.status === 'Ready to Approve' && isValidMapping(tx.mappedTo);

export function filterTransactions(transactions: Transaction[], tab: TabId, query = '') {
    const search = query.trim().toLowerCase();
    return transactions.filter(tx => {
        const inTab = tab === 'exception-queue' ? tx.isException
            : tab === 'bank-to-bill' ? tx.type === 'Bank-to-Bill'
            : tab === 'card-recon' ? tx.type === 'Card Recon'
            : tab === 'accruals' ? tx.type === 'Accrual' : true;
        return inTab && (!search || [tx.name, tx.amount, tx.evidence].some(value => value.toLowerCase().includes(search)));
    });
}

export function selectVisible(transactions: Transaction[], tab: TabId, query: string, selected: boolean) {
    const visibleIds = new Set(filterTransactions(transactions, tab, query).filter(canBulkApprove).map(tx => tx.id));
    return transactions.map(tx => visibleIds.has(tx.id) ? { ...tx, selected } : tx);
}

export function approveOne(ledger: Ledger, id: number, mapping: string, log: AuditLog): Ledger {
    if (!isValidMapping(mapping) || !ledger.transactions.some(tx => tx.id === id && tx.status !== 'Approved')) return ledger;
    return {
        transactions: ledger.transactions.map(tx => tx.id === id
            ? { ...tx, mappedTo: mapping.trim(), status: 'Approved', isException: false, selected: false }
            : tx),
        auditLogs: [log, ...ledger.auditLogs],
    };
}

export function approveVisible(ledger: Ledger, tab: TabId, query: string, log: AuditLog): Ledger {
    const ids = new Set(filterTransactions(ledger.transactions, tab, query).filter(tx => tx.selected && canBulkApprove(tx)).map(tx => tx.id));
    if (!ids.size) return ledger;
    return {
        transactions: ledger.transactions.map(tx => ids.has(tx.id) ? { ...tx, status: 'Approved', selected: false } : tx),
        auditLogs: [log, ...ledger.auditLogs],
    };
}

export function getCounts(transactions: Transaction[]) {
    return {
        drafted: transactions.filter(tx => tx.status === 'Ready to Approve').length,
        exceptions: transactions.filter(tx => tx.isException).length,
        approved: transactions.filter(tx => tx.status === 'Approved').length,
    };
}

export function parseLedger(raw: string | null): Ledger | null {
    if (!raw) return null;
    try {
        const value: unknown = JSON.parse(raw);
        if (typeof value !== 'object' || value === null) return null;
        const ledger = value as Record<string, unknown>;
        if (!Array.isArray(ledger.transactions) || !Array.isArray(ledger.auditLogs)) return null;
        const valid = ledger.transactions.every((tx: unknown) => {
            if (typeof tx !== 'object' || tx === null) return false;
            const item = tx as Record<string, unknown>;
            return typeof item.id === 'number' && Number.isFinite(item.id)
                && ['Bank-to-Bill', 'Card Recon', 'Accrual'].includes(String(item.type))
                && ['Ready to Approve', 'Exception', 'Approved'].includes(String(item.status))
                && ['name', 'icon', 'amount', 'evidence', 'mappedTo', 'date'].every(key => typeof item[key] === 'string')
                && typeof item.confidence === 'number' && item.confidence >= 0 && item.confidence <= 100
                && typeof item.isException === 'boolean' && typeof item.selected === 'boolean'
                && (item.explanation === undefined || typeof item.explanation === 'string')
                && item.isException === (item.status === 'Exception');
        }) && ledger.auditLogs.every((log: unknown) => typeof log === 'object' && log !== null
            && ['id', 'action', 'user', 'time'].every(key => typeof (log as Record<string, unknown>)[key] === 'string'));
        if (!valid || new Set(ledger.transactions.map(tx => tx.id)).size !== ledger.transactions.length) return null;
        return { transactions: ledger.transactions.map(tx => ({ ...tx, selected: false })), auditLogs: ledger.auditLogs };
    } catch {
        return null;
    }
}
