import { useEffect, useRef, type FC } from 'react';
import { canBulkApprove, type Transaction, type TabId } from '../lib/transactions';

interface TransactionTableProps {
    activeTab: TabId;
    transactions: Transaction[];
    searchQuery: string;
    setSearchQuery: (query: string) => void;
    bulkApprove: () => void;
    toggleSelectAll: (selected: boolean) => void;
    toggleSelect: (id: number) => void;
    handleReview: (tx: Transaction) => void;
}

export const TransactionTable: FC<TransactionTableProps> = ({
    activeTab,
    transactions,
    searchQuery,
    setSearchQuery,
    bulkApprove,
    toggleSelectAll,
    toggleSelect,
    handleReview
}) => {
    const filteredTx = transactions;
    const eligible = filteredTx.filter(canBulkApprove);
    const selectedCount = eligible.filter(tx => tx.selected).length;
    const allSelected = eligible.length > 0 && selectedCount === eligible.length;
    const selectAllRef = useRef<HTMLInputElement>(null);
    useEffect(() => {
        if (selectAllRef.current) selectAllRef.current.indeterminate = selectedCount > 0 && !allSelected;
    }, [selectedCount, allSelected]);

    return (
        <div className="bg-card rounded-2xl border border-border overflow-hidden shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)] animate-in">
            <div className="p-4 border-b border-border flex flex-col md:flex-row gap-4 justify-between items-center bg-muted/20">
                <h2 className="font-semibold text-sm text-foreground flex items-center gap-2">
                    {activeTab === 'exception-queue' ? <><i aria-hidden="true" className="ri-alert-line text-orange-500"></i> Exceptions requiring review</> : 'Drafted Entries'}
                </h2>

                <div className="flex items-center gap-3 w-full md:w-auto">
                    <div className="relative w-full md:w-64">
                        <i aria-hidden="true" className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm"></i>
                        <input
                            type="text"
                            aria-label="Search transactions"
                            placeholder="Search vendor, amount..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full pl-9 pr-4 py-2 text-xs bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/40 text-foreground"
                        />
                    </div>
                    {selectedCount > 0 && (
                        <button onClick={bulkApprove} className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-xs font-bold hover:opacity-90 transition-all shadow-sm flex items-center gap-1 flex-shrink-0">
                            <i aria-hidden="true" className="ri-check-double-line"></i> Approve Selected ({selectedCount})
                        </button>
                    )}
                </div>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-left text-sm whitespace-nowrap">
                    <thead className="text-muted-foreground bg-muted/40 border-b border-border text-xs uppercase tracking-wider font-bold">
                        <tr>
                            <th className="px-5 py-4 w-10">
                                <input type="checkbox" ref={selectAllRef} aria-label="Select all eligible visible transactions" checked={allSelected} disabled={!eligible.length} onChange={e => toggleSelectAll(e.target.checked)} className="rounded border-border focus:ring-primary" />
                            </th>
                            <th className="px-5 py-4">Task / Item</th>
                            <th className="px-5 py-4">Amount</th>
                            <th className="px-5 py-4">Evidence</th>
                            <th className="px-5 py-4">AI Confidence</th>
                            <th className="px-5 py-4">Status</th>
                            <th className="px-5 py-4 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {filteredTx.map(tx => (
                            <tr key={tx.id} className={`hover:bg-muted/30 transition-colors ${tx.isException ? 'bg-orange-50/30 dark:bg-orange-500/5' : ''}`}>
                                <td className="px-5 py-4">
                                    <input
                                        type="checkbox"
                                        aria-label={`Select ${tx.name}`}
                                        checked={tx.selected && canBulkApprove(tx)}
                                        onChange={() => toggleSelect(tx.id)}
                                        disabled={!canBulkApprove(tx)}
                                        className="rounded border-border focus:ring-primary disabled:opacity-50"
                                    />
                                </td>
                                <td className="px-5 py-4">
                                    <div className="flex items-center gap-3">
                                        <div className={`w-9 h-9 rounded-xl flex items-center justify-center border shadow-sm ${tx.isException ? 'bg-orange-100/50 border-orange-200 text-orange-600 dark:bg-orange-500/10 dark:border-orange-500/20 dark:text-orange-500' : 'bg-background border-border text-foreground'}`}>
                                            <i aria-hidden="true" className={tx.icon + " text-lg"}></i>
                                        </div>
                                        <div>
                                            <div className="font-semibold text-foreground text-sm">{tx.name}</div>
                                            <div className="text-[10px] text-muted-foreground uppercase mt-0.5">{tx.date} • {tx.type}</div>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-5 py-4 font-bold text-foreground">{tx.amount}</td>
                                <td className="px-5 py-4">
                                    <span className="text-xs text-muted-foreground font-medium flex items-center gap-1">
                                        <i aria-hidden="true" className="ri-file-text-line"></i> {tx.evidence}
                                    </span>
                                </td>
                                <td className="px-5 py-4">
                                    <div className="flex items-center gap-3 w-32 group cursor-help relative" title={`Sample confidence: ${tx.confidence}%`}>
                                        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden shadow-inner">
                                            <div className={`h-full rounded-full transition-all duration-1000 ${tx.confidence > 90 ? 'bg-green-500' : tx.confidence > 70 ? 'bg-yellow-500' : 'bg-orange-500'}`} style={{ width: `${tx.confidence}%` }}></div>
                                        </div>
                                        <span className={`text-[10px] font-bold ${tx.confidence > 90 ? 'text-green-600 dark:text-green-500' : tx.confidence > 70 ? 'text-yellow-600 dark:text-yellow-500' : 'text-orange-600 dark:text-orange-500'}`}>{tx.confidence}%</span>
                                    </div>
                                </td>
                                <td className="px-5 py-4">
                                    <span className={`text-xs font-bold px-2.5 py-1.5 rounded-lg border shadow-sm ${tx.status === 'Approved' ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/20' : tx.isException ? 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500/20' : 'bg-background text-muted-foreground border-border'}`}>
                                        {tx.status}
                                    </span>
                                </td>
                                <td className="px-5 py-4 text-right">
                                    {tx.status !== 'Approved' && (
                                        <button onClick={() => handleReview(tx)} className="px-4 py-2 bg-background border border-border text-foreground rounded-lg text-xs font-bold hover:bg-muted transition-colors shadow-sm active:scale-95">
                                            {tx.isException ? 'Resolve' : 'Review'}
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                        {filteredTx.length === 0 && (
                            <tr>
                                <td colSpan={7} className="px-6 py-16 text-center text-muted-foreground">
                                    <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center mx-auto mb-4 border border-border shadow-sm">
                                        <i aria-hidden="true" className={searchQuery ? "ri-search-line text-3xl" : "ri-check-line text-3xl"}></i>
                                    </div>
                                    <p className="font-bold text-foreground text-lg">
                                        {searchQuery ? "No matching records found" : "Queue is empty"}
                                    </p>
                                    <p className="text-sm mt-1">
                                        {searchQuery ? "Try adjusting your search terms." : "All items in this category are completed."}
                                    </p>
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
