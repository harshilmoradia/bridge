import type { FC } from 'react';
import type { TabId } from '../lib/transactions';
import { useTheme } from '../context/theme';

interface SidebarProps {
    activeTab: TabId;
    setActiveTab: (tab: TabId) => void;
    exceptionCount: number;
    userName: string;
    userEmailInput: string;
    userInitials: string;
    isCollapsed: boolean;
    toggleCollapse: () => void;
}

export const Sidebar: FC<SidebarProps> = ({
    activeTab,
    setActiveTab,
    exceptionCount,
    userName,
    userEmailInput,
    userInitials,
    isCollapsed,
    toggleCollapse
}) => {
    const { theme, toggleTheme } = useTheme();

    const navItems: { id: TabId; icon: string; label: string; badge?: number }[] = [
        { id: 'dashboard', icon: 'ri-dashboard-line', label: 'Overview' },
        { id: 'bank-to-bill', icon: 'ri-arrow-left-right-line', label: 'Bank-to-Bill' },
        { id: 'card-recon', icon: 'ri-bank-card-line', label: 'Card Recon' },
        { id: 'accruals', icon: 'ri-scales-3-line', label: 'Accrual Drafts' },
        { id: 'exception-queue', icon: 'ri-alert-line', label: 'Exception Queue', badge: exceptionCount },
        { id: 'audit-trail', icon: 'ri-history-line', label: 'Audit Trail' },
    ];

    return (
        <aside className={`${isCollapsed ? 'w-[72px]' : 'w-[72px] md:w-64'} bg-card border-r border-border flex flex-col z-30 transition-all duration-300 flex-shrink-0`}>
            <div className={`p-5 flex items-center ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
                <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center shadow-md flex-shrink-0">
                        <i aria-hidden="true" className="ri-infinity-line text-primary-foreground font-bold text-lg"></i>
                    </div>
                    {!isCollapsed && <span className="hidden md:block font-bold text-xl tracking-tight">Bridge</span>}
                </div>
                {!isCollapsed && (
                    <button aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={toggleCollapse} className="hidden md:block text-muted-foreground hover:bg-muted p-1 rounded transition-colors">
                        <i aria-hidden="true" className="ri-menu-fold-line text-lg"></i>
                    </button>
                )}
            </div>

            {isCollapsed && (
                <div className="flex justify-center mb-4">
                    <button aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={toggleCollapse} className="hidden md:block text-muted-foreground hover:bg-muted p-1 rounded transition-colors">
                        <i aria-hidden="true" className="ri-menu-unfold-line text-lg"></i>
                    </button>
                </div>
            )}

            <nav className="flex-1 px-3 space-y-1 mt-2 overflow-y-auto">
                {!isCollapsed && <div className="hidden md:block text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-3 ml-3 mt-4">Reconciliation</div>}

                {navItems.map(item => (
                    <button
                        key={item.id}
                        onClick={() => setActiveTab(item.id)}
                        aria-label={item.label} aria-current={activeTab === item.id ? "page" : undefined} title={isCollapsed ? item.label : undefined}
                        className={`w-full flex items-center ${isCollapsed ? 'justify-center p-2.5' : 'gap-3 px-3 py-2.5'} rounded-xl font-medium text-sm transition-all ${activeTab === item.id ? 'bg-primary/5 dark:bg-primary/10 text-primary font-bold shadow-sm border border-primary/10' : 'text-muted-foreground hover:text-foreground hover:bg-muted'}`}
                    >
                        <div className="relative">
                            <i aria-hidden="true" className={`${item.icon} text-lg ${activeTab === item.id ? '' : 'opacity-70'}`}></i>
                            {isCollapsed && (item.badge ?? 0) > 0 && (
                                <span className="absolute -top-1.5 -right-1.5 w-3 h-3 bg-orange-500 rounded-full border border-card"></span>
                            )}
                        </div>

                        {!isCollapsed && (
                            <>
                                <span className="hidden md:block flex-1 text-left">{item.label}</span>
                                {(item.badge ?? 0) > 0 ? (
                                    <span className={`hidden md:block text-[10px] px-2 py-0.5 rounded-full font-bold shadow-sm ${activeTab === item.id ? 'bg-primary text-primary-foreground' : 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400 border border-orange-200 dark:border-orange-900/50'}`}>
                                        {item.badge}
                                    </span>
                                ) : null}
                            </>
                        )}
                    </button>
                ))}
            </nav>

            <div className={`p-3 border-t border-border bg-muted/10`}>
                <div className={`flex items-center ${isCollapsed ? 'flex-col gap-3' : 'flex-col md:flex-row gap-3 md:justify-between md:px-1'}`}>
                    <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-xs shadow-sm border border-primary/20 flex-shrink-0">
                            {userInitials}
                        </div>
                        {!isCollapsed && (
                            <div className="hidden md:flex flex-col text-left overflow-hidden">
                                <span className="text-xs font-bold truncate max-w-[100px] text-foreground">{userName}</span>
                                <span className="text-[10px] text-muted-foreground truncate max-w-[100px]">{userEmailInput}</span>
                            </div>
                        )}
                    </div>
                    <button aria-label="Toggle theme" onClick={toggleTheme} className="w-8 h-8 rounded-full flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors border border-transparent hover:border-border flex-shrink-0" title="Toggle Theme">
                        <i aria-hidden="true" className={theme === 'dark' ? 'ri-sun-line text-base' : 'ri-moon-line text-base'}></i>
                    </button>
                </div>
            </div>
        </aside>
    );
};
