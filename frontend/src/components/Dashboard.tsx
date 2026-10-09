import type { FC } from 'react';
import type { AuditLog, TabId } from '../lib/transactions';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

interface DashboardProps {
    setActiveTab: (tab: TabId) => void;
    draftedCount: number;
    approvedCount: number;
    exceptionCount: number;
    auditLogs: AuditLog[];
}

export const Dashboard: FC<DashboardProps> = ({ setActiveTab, draftedCount, approvedCount, exceptionCount, auditLogs }) => {

    // Empty state logic
    const totalTransactions = draftedCount + approvedCount + exceptionCount;
    const isInitialEmptyState = totalTransactions === 0;

    if (isInitialEmptyState) {
        return (
            <div className="h-full flex flex-col items-center justify-center animate-in text-center p-12 bg-card rounded-2xl border border-border shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
                <div className="w-20 h-20 bg-primary/10 text-primary rounded-full flex items-center justify-center mb-6 shadow-inner border border-primary/20">
                    <i aria-hidden="true" className="ri-file-upload-line text-4xl"></i>
                </div>
                <h2 className="text-2xl font-bold text-foreground mb-2">Welcome to Bridge</h2>
                <p className="text-muted-foreground max-w-md mb-8">
                    Your queue is empty. Upload a bank statement, receipt, or invoice using the "Add Demo Doc" button above to add a sample entry.
                </p>
                <div className="flex gap-4">
                    <div className="bg-muted px-4 py-3 rounded-xl flex items-center gap-3 border border-border">
                        <i aria-hidden="true" className="ri-file-pdf-line text-red-500 text-xl"></i>
                        <span className="text-sm font-semibold">PDF Receipts</span>
                    </div>
                    <div className="bg-muted px-4 py-3 rounded-xl flex items-center gap-3 border border-border">
                        <i aria-hidden="true" className="ri-file-excel-2-line text-green-500 text-xl"></i>
                        <span className="text-sm font-semibold">CSV Bank Feeds</span>
                    </div>
                </div>
            </div>
        );
    }

    const chartData = [
        { name: 'Drafted', value: draftedCount, color: '#22c55e' },
        { name: 'Approved', value: approvedCount, color: '#6366f1' },
        { name: 'Exceptions', value: exceptionCount, color: '#f97316' }
    ];

    return (
        <div className="space-y-6 animate-in">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <button type="button" onClick={() => setActiveTab('bank-to-bill')} className="bg-card p-6 rounded-2xl border border-border hover:-translate-y-1 transition-transform text-left cursor-pointer shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
                    <div className="text-muted-foreground text-sm font-semibold mb-2 flex justify-between items-center">
                        Drafted Entries <i aria-hidden="true" className="ri-check-double-line text-green-500 bg-green-500/10 dark:bg-green-500/20 p-1.5 rounded-lg"></i>
                    </div>
                    <div className="text-3xl font-bold text-foreground">{draftedCount}</div>
                    <div className="mt-3 text-xs text-green-600 dark:text-green-400 font-semibold flex items-center gap-1">
                        <i aria-hidden="true" className="ri-arrow-up-line"></i> Ready for bulk approval
                    </div>
                </button>
                <button type="button" onClick={() => setActiveTab('exception-queue')} className="bg-card p-6 rounded-2xl border border-border hover:-translate-y-1 transition-transform text-left cursor-pointer shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)] relative overflow-hidden">
                    {exceptionCount > 0 && <div className="absolute top-0 right-0 w-24 h-24 bg-orange-500/10 rounded-bl-full blur-xl"></div>}
                    <div className="text-muted-foreground text-sm font-semibold mb-2 flex justify-between items-center relative z-10">
                        Pending Exceptions <i aria-hidden="true" className="ri-alert-line text-orange-500 bg-orange-500/10 dark:bg-orange-500/20 p-1.5 rounded-lg"></i>
                    </div>
                    <div className="text-3xl font-bold text-orange-600 dark:text-orange-500 relative z-10">{exceptionCount}</div>
                    <div className="mt-3 text-xs text-muted-foreground font-medium relative z-10">Requires human review</div>
                </button>
                <div className="bg-card p-6 rounded-2xl border border-border transition-transform shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
                    <div className="text-muted-foreground text-sm font-semibold mb-2 flex justify-between items-center">
                        Approved Entries <i aria-hidden="true" className="ri-robot-2-line text-primary bg-primary/10 p-1.5 rounded-lg"></i>
                    </div>
                    <div className="text-3xl font-bold text-primary">
                        {approvedCount}
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground font-medium">Approved in this demo workspace</div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="md:col-span-2 bg-card rounded-2xl border border-border shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)] p-6">
                    <h2 className="font-semibold text-lg mb-4">Recent Activity</h2>
                    <div className="space-y-4">
                        {auditLogs.slice(0, 4).map((log) => (
                            <div key={log.id} className="flex items-start gap-4 p-3 hover:bg-muted/50 rounded-xl transition-colors">
                                <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-foreground flex-shrink-0">
                                    <i aria-hidden="true" className={log.user === 'Bridge AI' ? 'ri-robot-2-line' : 'ri-user-line'}></i>
                                </div>
                                <div className="flex-1">
                                    <p className="text-sm font-medium text-foreground">{log.action}</p>
                                    <div className="flex gap-2 text-xs text-muted-foreground mt-1">
                                        <span>{log.user}</span> • <span>{log.time}</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="bg-card rounded-2xl border border-border shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)] p-6 flex flex-col">
                    <h2 className="font-semibold text-lg mb-4">Reconciliation Status</h2>
                    <div className="flex-1 min-h-[200px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={chartData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={60}
                                    outerRadius={80}
                                    paddingAngle={5}
                                    dataKey="value"
                                >
                                    {chartData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.color} />
                                    ))}
                                </Pie>
                                <Tooltip
                                    contentStyle={{ borderRadius: '12px', border: '1px solid var(--border)', backgroundColor: 'var(--card)', color: 'var(--foreground)' }}
                                    itemStyle={{ fontWeight: 'bold' }}
                                />
                                <Legend verticalAlign="bottom" height={36} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Dashboard;
