import { NavLink, Outlet } from 'react-router';
import { useTheme } from '../context/theme';
import { cn } from '../lib/utils';

const NAV = [
    { to: '/reconcile', icon: 'ri-scales-3-line', label: 'Reconcile' },
    { to: '/bank', icon: 'ri-bank-line', label: 'Bank' },
    { to: '/ledger', icon: 'ri-book-2-line', label: 'Ledger' },
];

interface AppLayoutProps {
    userName: string;
    userEmail: string;
    signOut: () => void;
    signingOut: boolean;
}

export function AppLayout({ userName, userEmail, signOut, signingOut }: AppLayoutProps) {
    const { theme, toggleTheme } = useTheme();
    return (
        <div className="h-screen flex overflow-hidden bg-background text-foreground">
            <aside className="w-[72px] md:w-60 shrink-0 bg-card border-r border-border flex flex-col">
                <div className="p-5 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center shrink-0">
                        <i aria-hidden="true" className="ri-infinity-line text-primary-foreground text-lg" />
                    </div>
                    <span className="hidden md:block font-bold text-xl tracking-tight">Bridge</span>
                </div>
                <nav aria-label="Main" className="flex-1 px-3 space-y-1 overflow-y-auto">
                    {NAV.map(item => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            aria-label={item.label}
                            className={({ isActive }) => cn(
                                'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors justify-center md:justify-start',
                                isActive ? 'bg-primary/10 text-primary font-bold' : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                            )}
                        >
                            <i aria-hidden="true" className={cn(item.icon, 'text-lg')} />
                            <span className="hidden md:block">{item.label}</span>
                        </NavLink>
                    ))}
                </nav>
                <div className="p-3 border-t border-border space-y-2">
                    <div className="hidden md:block px-1 min-w-0">
                        <p className="text-xs font-bold truncate">{userName}</p>
                        <p className="text-[10px] text-muted-foreground truncate">{userEmail}</p>
                    </div>
                    <div className="flex flex-col md:flex-row items-center gap-1">
                        <button type="button" aria-label="Sign out" disabled={signingOut} onClick={signOut} className="flex-1 w-full flex items-center justify-center gap-2 rounded-lg py-2 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50">
                            <i aria-hidden="true" className="ri-logout-box-r-line" />
                            <span className="hidden md:inline">{signingOut ? 'Signing out…' : 'Sign out'}</span>
                        </button>
                        <button type="button" aria-label="Toggle theme" onClick={toggleTheme} className="w-8 h-8 rounded-full flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted shrink-0">
                            <i aria-hidden="true" className={theme === 'dark' ? 'ri-sun-line' : 'ri-moon-line'} />
                        </button>
                    </div>
                </div>
            </aside>
            <main className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-8">
                <div className="max-w-6xl mx-auto w-full">
                    <Outlet />
                </div>
            </main>
        </div>
    );
}
