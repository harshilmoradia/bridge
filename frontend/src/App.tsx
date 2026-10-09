import { useState, useEffect, useSyncExternalStore, lazy, Suspense, type ChangeEvent, type FormEvent } from 'react';
import { useKeyboardShortcuts, useToast, useTimeouts } from './hooks/useAppHooks';
import { ToastContainer } from './components/ToastContainer';
import { AuthGate } from './components/AuthGate';
import { getInitials, type Identity } from './lib/auth';
import { Sidebar } from './components/Sidebar';
import { ChatPanel, type ChatMessage } from './components/ChatPanel';
import { ExceptionModal } from './components/ExceptionModal';
import { TransactionTable } from './components/TransactionTable';
import { initialTransactions } from './lib/demoData';
import { saveDemoLedger, storageIsAvailable, subscribeToStorage } from './lib/demoStorage';
import { approveOne, approveVisible, canBulkApprove, filterTransactions, getCounts, parseLedger, selectVisible, type Ledger, type Transaction, type TabId } from './lib/transactions';

const Dashboard = lazy(() => import('./components/Dashboard'));

interface WorkspaceProps {
    identity: Identity;
    signOut: () => Promise<void>;
    signingOut: boolean;
}

const Workspace = ({ identity, signOut, signingOut }: WorkspaceProps) => {
    const userName = identity.displayName;
    const userEmailInput = identity.email;
    const userInitials = getInitials(userName);

    // UI Layout State
    const [activeTab, setActiveTab] = useState<TabId>('dashboard');
    const [chatWidth, setChatWidth] = useState(380);
    const [isDragging, setIsDragging] = useState(false);
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [selectedTx, setSelectedTx] = useState<Transaction | null>(null);

    // Chat State
    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([{ role: 'agent', content: 'Welcome to Bridge. This workspace currently uses sample transactions and simulated replies. Approvals are saved in this browser; no entries are posted to an ERP.' }]);
    const [chatInput, setChatInput] = useState('');
    const [agentTyping, setAgentTyping] = useState(false);

    // Data State
    const [ledger, setLedger] = useState<Ledger>(() => {
        try {
            const saved = parseLedger(localStorage.getItem('bridge-demo-ledger-v1'));
            if (saved) return saved;
        } catch { /* Storage can be unavailable in private browsing. */ }
        return { transactions: initialTransactions, auditLogs: [
            { id: crypto.randomUUID(), action: 'Demo initialized with sample data.', user: 'System', time: 'Just now' }
        ] };
    });
    const { transactions, auditLogs } = ledger;
    const storageAvailable = useSyncExternalStore(subscribeToStorage, storageIsAvailable);
    const [searchQuery, setSearchQuery] = useState('');
    const { drafted: draftedCount, exceptions: exceptionCount, approved: approvedCount } = getCounts(transactions);
    const filteredTx = filterTransactions(transactions, activeTab, searchQuery);

    useEffect(() => {
        saveDemoLedger(ledger);
    }, [ledger]);

    const { toasts, addToast } = useToast();
    const schedule = useTimeouts();

    useKeyboardShortcuts({
        'ctrl+k': () => { if (!showModal) document.getElementById('chat-input')?.focus(); },
    });

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isDragging) return;
            const newWidth = window.innerWidth - e.clientX;
            if (newWidth >= 300 && newWidth <= 800) setChatWidth(newWidth);
        };
        const handleMouseUp = () => {
            setIsDragging(false);
            document.body.style.cursor = 'default';
        };
        if (isDragging) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = 'col-resize';
        }
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = '';
        };
    }, [isDragging]);

    const handleTabChange = (tabId: TabId) => {
        setActiveTab(tabId);
        setSearchQuery('');
        setLedger(prev => ({ ...prev, transactions: prev.transactions.map(tx => ({ ...tx, selected: false })) }));
    };

    const handleHeaderFileUpload = (e: ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setUploading(true);
        schedule(() => {
            setUploading(false);
            setChatMessages(prev => [...prev, { role: 'agent', content: `Received "${file.name}". Demo: added a sample entry using this filename. File contents were not parsed.` }]);

            // Add a new mock transaction based on upload
            const newTx: Transaction = { id: Date.now(), type: 'Bank-to-Bill', name: 'New Uploaded Vendor', icon: 'ri-file-upload-line', amount: '-$340.00', evidence: file.name, mappedTo: 'Pending', confidence: 85, status: 'Ready to Approve', isException: false, selected: false, date: 'Just now' };
            setLedger(prev => ({ transactions: [newTx, ...prev.transactions], auditLogs: [{ id: crypto.randomUUID(), action: `Added demo entry for ${file.name}`, user: 'Demo Agent', time: 'Just now' }, ...prev.auditLogs] }));

            addToast(`Added demo entry for ${file.name}`, 'success');
        }, 1500);
        e.target.value = '';
    };

    const handleChatFileUpload = (e: ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || agentTyping) return;

        setChatMessages(prev => [...prev, {
            role: 'user',
            content: `Attached document: ${file.name}`
        }]);
        setAgentTyping(true);

        schedule(() => {
            setAgentTyping(false);
            setChatMessages(prev => [...prev, {
                role: 'agent',
                content: `Demo attachment: "${file.name}". File contents were not parsed and no transaction was changed.`
            }]);
        }, 2000);

        e.target.value = '';
    };

    const sendChatMessage = (e: FormEvent) => {
        e.preventDefault();
        if (!chatInput.trim() || agentTyping) return;
        setChatMessages(prev => [...prev, { role: 'user', content: chatInput }]);
        setChatInput('');
        setAgentTyping(true);
        schedule(() => {
            setAgentTyping(false);
            setChatMessages(prev => [...prev, { role: 'agent', content: "This is a simulated demo reply. Open a transaction's Review or Resolve action to inspect its sample evidence and ledger mapping." }]);
        }, 1500);
    };

    const handleReview = (tx: Transaction) => {
        setSelectedTx(tx);
        setShowModal(true);
    };

    const approveTransaction = (mapping: string) => {
        if (!selectedTx) return;
        const tx = selectedTx;
        const log = { id: crypto.randomUUID(), action: `Demo approval: ${tx.name} → ${mapping}`, user: userName, time: 'Just now' };
        setLedger(prev => approveOne(prev, tx.id, mapping, log));
        setShowModal(false);
        setSelectedTx(null);
        addToast(`Approved ${tx.name} in demo`, 'success');
    };

    const bulkApprove = () => {
        const selectedCount = filteredTx.filter(tx => tx.selected && canBulkApprove(tx)).length;
        if (!selectedCount) return;
        const log = { id: crypto.randomUUID(), action: `Demo bulk approval: ${selectedCount} entries`, user: userName, time: 'Just now' };
        setLedger(prev => approveVisible(prev, activeTab, searchQuery, log));
        addToast(`Approved ${selectedCount} demo entries`, 'success');
    };

    const toggleSelectAll = (selected: boolean) => {
        setLedger(prev => ({ ...prev, transactions: selectVisible(prev.transactions, activeTab, searchQuery, selected) }));
    };

    const toggleSelect = (id: number) => {
        setLedger(prev => ({ ...prev, transactions: prev.transactions.map(tx =>
            tx.id === id && canBulkApprove(tx) ? { ...tx, selected: !tx.selected } : tx) }));
    };

    const renderMainContent = () => {
        if (activeTab === 'dashboard') {
            return (
                <Suspense fallback={<p role="status">Loading overview...</p>}>
                <Dashboard
                    setActiveTab={handleTabChange}
                    draftedCount={draftedCount}
                    approvedCount={approvedCount}
                    exceptionCount={exceptionCount}
                    auditLogs={auditLogs}
                />
                </Suspense>
            );
        }

        if (activeTab === 'audit-trail') {
            return (
                <div className="bg-card rounded-2xl border border-border shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)] p-6 animate-in">
                    <h2 className="font-semibold text-lg mb-6 flex items-center gap-2">
                        <i className="ri-history-line text-indigo-500"></i> Complete Audit Trail
                    </h2>
                    {auditLogs.length === 0 ? (
                        <div className="text-center py-12 text-muted-foreground">
                            <i className="ri-history-line text-4xl mb-4 opacity-50"></i>
                            <p className="font-bold text-foreground">No activity yet</p>
                            <p className="text-sm">Actions will be recorded here.</p>
                        </div>
                    ) : (
                        <div className="space-y-0">
                            {auditLogs.map((log) => (
                                <div key={log.id} className="flex items-start gap-4 p-4 border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
                                    <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-foreground flex-shrink-0 shadow-sm border border-border">
                                        <i className={log.user === 'Bridge AI' ? 'ri-robot-2-fill text-indigo-500' : 'ri-user-fill text-foreground'}></i>
                                    </div>
                                    <div className="flex-1 pt-1">
                                        <p className="text-sm font-semibold text-foreground">{log.action}</p>
                                        <div className="flex gap-3 text-xs text-muted-foreground mt-1.5 font-medium">
                                            <span className="flex items-center gap-1"><i className="ri-account-circle-line"></i> {log.user}</span>
                                            <span className="flex items-center gap-1"><i className="ri-time-line"></i> {log.time}</span>
                                            <span className="flex items-center gap-1"><i className="ri-fingerprint-line"></i> ID: {log.id.toString().slice(-6)}</span>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )
        }

        return (
            <TransactionTable
                activeTab={activeTab}
                transactions={filteredTx}
                searchQuery={searchQuery}
                setSearchQuery={setSearchQuery}
                bulkApprove={bulkApprove}
                toggleSelectAll={toggleSelectAll}
                toggleSelect={toggleSelect}
                handleReview={handleReview}
            />
        );
    };

    return (
        <div className="h-screen flex overflow-hidden bg-background text-foreground transition-colors duration-300 fade-in">

            <Sidebar
                activeTab={activeTab}
                setActiveTab={handleTabChange}
                exceptionCount={exceptionCount}
                userName={userName}
                userEmailInput={userEmailInput}
                userInitials={userInitials}
                isCollapsed={isSidebarCollapsed}
                toggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                signOut={() => void signOut()}
                signingOut={signingOut}
            />

            <main className="min-w-0 flex-1 flex flex-col h-full relative overflow-y-auto z-10 transition-colors duration-300">
                <header className="h-16 border-b border-border bg-card/80 backdrop-blur-md sticky top-0 z-20 flex items-center justify-between px-4 sm:px-8">
                    <h1 className="min-w-0 truncate text-sm sm:text-lg font-bold tracking-tight capitalize flex items-center gap-2 text-foreground">
                        {activeTab.replace(/-/g, ' ')}
                    </h1>
                    <div className="flex items-center gap-4">
                        <label className="bg-background border border-border text-foreground px-2 sm:px-4 py-2 rounded-lg text-xs sm:text-sm font-bold whitespace-nowrap hover:bg-muted transition-all active:scale-[0.98] shadow-sm flex items-center gap-2 cursor-pointer">
                            {uploading ? <i className="ri-loader-4-line animate-spin"></i> : <i className="ri-file-add-line"></i>}
                            {uploading ? 'Adding...' : 'Add Demo Doc'}
                            <input type="file" aria-label="Add demo document" className="sr-only" onChange={handleHeaderFileUpload} accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx,.xls,.txt" disabled={uploading} />
                        </label>
                    </div>
                </header>

                <div className="p-4 sm:p-8 max-w-6xl mx-auto w-full space-y-6">
                    <p role="status" className="text-xs text-muted-foreground border border-border rounded-lg p-3">
                        {identity.isDemo ? 'Demo access' : 'Signed in'} — sample data, simulated chat and uploads. {storageAvailable ? 'Demo approvals are saved in this browser.' : 'Browser storage is unavailable; demo approvals last for this session only.'} No ERP posting. Transactions are not yet stored in your account.
                    </p>
                    {activeTab !== 'dashboard' && activeTab !== 'audit-trail' && transactions.length > 0 && (
                        <div className="bg-primary/5 dark:bg-primary/10 border border-primary/10 rounded-2xl p-4 flex items-start gap-4 shadow-sm animate-in">
                            <div className="mt-0.5 text-primary"><i className="ri-information-line text-xl"></i></div>
                            <div>
                                <h4 className="text-sm font-bold text-foreground">Human-in-the-Loop Active</h4>
                                <p className="text-xs text-muted-foreground mt-1 font-medium">Review the sample evidence and choose a ledger account before approving. Approvals update this demo only.</p>
                            </div>
                        </div>
                    )}

                    {renderMainContent()}
                </div>
            </main>

            <ChatPanel
                chatWidth={chatWidth}
                setChatWidth={setChatWidth}
                isDragging={isDragging}
                setIsDragging={setIsDragging}
                chatMessages={chatMessages}
                setChatMessages={setChatMessages}
                chatInput={chatInput}
                setChatInput={setChatInput}
                handleChatFileUpload={handleChatFileUpload}
                sendChatMessage={sendChatMessage}
                agentTyping={agentTyping}
            />

            {showModal && <ExceptionModal
                showModal={showModal}
                setShowModal={setShowModal}
                key={selectedTx?.id}
                selectedTx={selectedTx}
                approveTransaction={approveTransaction}
            />}

            <ToastContainer toasts={toasts} />
        </div>
    );
};

export default function App() {
    return <AuthGate>{(identity, signOut, signingOut) => <Workspace key={identity.id} identity={identity} signOut={signOut} signingOut={signingOut} />}</AuthGate>;
}
