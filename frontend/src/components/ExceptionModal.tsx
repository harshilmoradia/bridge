import { useLayoutEffect, useRef, useState, type FC } from 'react';
import { isValidMapping, type Transaction } from '../lib/transactions';

interface ExceptionModalProps {
    showModal: boolean;
    setShowModal: (val: boolean) => void;
    selectedTx: Transaction | null;
    approveTransaction: (mapping: string) => void;
}

export const ExceptionModal: FC<ExceptionModalProps> = ({
    showModal,
    setShowModal,
    selectedTx,
    approveTransaction
}) => {
    const dialogRef = useRef<HTMLDialogElement>(null);
    const [mapping, setMapping] = useState(selectedTx?.mappedTo ?? '');
    useLayoutEffect(() => {
        const dialog = dialogRef.current;
        if (!showModal || !dialog) return;
        const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        dialog.showModal();
        return () => {
            if (dialog.open) dialog.close();
            if (previousFocus?.isConnected) previousFocus.focus();
        };
    }, [showModal]);

    if (!showModal || !selectedTx) return null;

    return (
        <dialog ref={dialogRef} aria-labelledby="resolution-title" onCancel={e => { e.preventDefault(); setShowModal(false); }} className="fixed inset-0 m-auto h-fit p-0 w-[calc(100%-2rem)] max-w-4xl bg-transparent text-foreground border-0 overflow-visible backdrop:bg-black/30 backdrop:backdrop-blur-sm">
            <div className="bg-card border border-border rounded-[24px] shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] w-full max-w-4xl relative z-10 overflow-hidden animate-in flex flex-col max-h-[90vh]">

                <div className="p-6 border-b border-border flex justify-between items-center bg-card">
                    <h3 id="resolution-title" className="font-bold text-xl text-foreground flex items-center gap-2">
                        <i aria-hidden="true" className="ri-shield-check-line text-primary"></i> Document Resolution
                    </h3>
                    <button aria-label="Close transaction review" onClick={() => setShowModal(false)} className="text-muted-foreground hover:bg-muted w-9 h-9 rounded-full flex items-center justify-center transition-colors border border-transparent hover:border-border">
                        <i aria-hidden="true" className="ri-close-line text-2xl"></i>
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-4 sm:p-8 bg-muted/20">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div className="space-y-4">
                            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Source Data</h4>
                            <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
                                <div className="flex items-center gap-4 mb-5 pb-5 border-b border-border">
                                    <div className="w-12 h-12 rounded-xl bg-muted text-foreground flex items-center justify-center border border-border shadow-sm">
                                        <i aria-hidden="true" className={selectedTx.icon + " text-2xl"}></i>
                                    </div>
                                    <div>
                                        <div className="font-bold text-base text-foreground">{selectedTx.name}</div>
                                        <div className="text-xs font-semibold text-muted-foreground mt-1 uppercase">{selectedTx.type}</div>
                                    </div>
                                </div>
                                <div className="space-y-3 text-sm font-medium">
                                    <div className="flex justify-between"><span className="text-muted-foreground">Amount:</span> <span className="font-bold text-foreground text-base">{selectedTx.amount}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Date:</span> <span>{selectedTx.date}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Account:</span> <span>Checking *8821</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Reference:</span> <span className="font-mono text-xs bg-muted px-2 py-1 rounded border border-border">TRX-{selectedTx.id}A</span></div>
                                </div>
                            </div>
                        </div>

                        <div className="space-y-4">
                            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Agent Explainability</h4>
                            <div className="bg-primary/5 dark:bg-primary/10 border border-primary/20 rounded-2xl p-6 shadow-sm h-full flex flex-col">
                                <div className="flex items-center gap-2 mb-4">
                                    <i aria-hidden="true" className="ri-robot-2-fill text-primary text-lg"></i>
                                    <span className="font-bold text-sm text-foreground">Sample Analysis</span>
                                    <span className="ml-auto text-xs font-bold bg-background text-foreground px-3 py-1.5 rounded-lg border border-border shadow-sm">
                                        Confidence: <span className={selectedTx.confidence > 90 ? 'text-green-500' : 'text-orange-500'}>{selectedTx.confidence}%</span>
                                    </span>
                                </div>
                                <p className="text-sm text-foreground/90 font-medium leading-relaxed mb-6 flex-1">
                                    {selectedTx.explanation || "This sample transaction includes a proposed account. Verify the evidence and mapping before approving in the demo."}
                                </p>

                                <div className="bg-card border border-border rounded-xl p-4 shadow-sm">
                                    <label htmlFor="ledger-mapping" className="text-xs font-bold text-muted-foreground uppercase mb-2 block">Proposed Ledger Mapping</label>
                                    <select id="ledger-mapping" value={mapping} onChange={e => setMapping(e.target.value)} className="w-full bg-background border border-border rounded-lg px-4 py-3 text-sm font-bold focus:outline-none focus:ring-2 focus:ring-primary/50 text-foreground cursor-pointer shadow-sm appearance-none">
                                        <option>{selectedTx.mappedTo}</option>
                                        <option>Meals & Entertainment</option>
                                        <option>Software Subscriptions</option>
                                        <option>Travel</option>
                                        <option>Office Supplies</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="p-6 border-t border-border bg-card flex flex-col sm:flex-row gap-3 justify-between items-center">
                    <div className="text-xs font-bold text-muted-foreground flex items-center gap-1.5">
                        <i aria-hidden="true" className="ri-history-line text-base"></i> Approval will be recorded in the demo audit trail.
                    </div>
                    <div className="flex gap-3">
                        <button onClick={() => setShowModal(false)} className="px-6 py-2.5 bg-background border border-border text-foreground rounded-xl text-sm font-bold hover:bg-muted transition-colors shadow-sm active:scale-95">Cancel (Esc)</button>
                        <button disabled={!isValidMapping(mapping)} onClick={() => approveTransaction(mapping)} className="px-6 py-2.5 bg-primary text-primary-foreground rounded-xl text-sm font-bold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md active:scale-95 flex items-center gap-2">
                            Approve in Demo <i aria-hidden="true" className="ri-check-line text-lg"></i>
                        </button>
                    </div>
                </div>
            </div>
        </dialog>
    );
};
