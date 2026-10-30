import type { LucideIcon } from 'lucide-react';
import { BookOpen, ChartColumn, Landmark, LogIn, LogOut, MessageSquareText, Moon, Scale, Sun } from 'lucide-react';
import { NavLink, Outlet } from 'react-router';
import { useDatasets } from '../api/hooks';
import { useTheme } from '../context/theme';
import { cn } from '../lib/utils';
import { LearnedRulesSheet } from './LearnedRules';
import { Button } from './ui/button';

const NAV: { to: string; icon: LucideIcon; label: string }[] = [
    { to: '/reconcile', icon: Scale, label: 'Reconcile' },
    { to: '/chat', icon: MessageSquareText, label: 'Ask Bridge' },
    { to: '/bank', icon: Landmark, label: 'Bank' },
    { to: '/ledger', icon: BookOpen, label: 'Ledger' },
    { to: '/evals', icon: ChartColumn, label: 'Model tiers' },
];

function BrandMark() {
    return (
        <div aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-[7px] bg-foreground text-background">
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M2 17c4-8 16-8 20 0M6 17v-4.5M12 17v-6.5M18 17v-4.5M2 17h20" />
            </svg>
        </div>
    );
}

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]!.toUpperCase()).join('') || '?';

interface AppLayoutProps {
    userName: string;
    userEmail: string;
    isDemo: boolean;
    signOut: () => void;
    signingOut: boolean;
    onSignIn?: () => void; // absent when sign-in is not configured
}

export function AppLayout({ userName, userEmail, isDemo, signOut, signingOut, onSignIn }: AppLayoutProps) {
    const { theme, toggleTheme } = useTheme();
    const datasets = useDatasets();
    const dataset = datasets.data?.[0];
    return (
        <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground md:flex-row">
            <aside aria-label="Main" className="flex shrink-0 items-center gap-1 overflow-x-auto border-b bg-card px-3 py-1.5 md:w-54 md:flex-col md:items-stretch md:gap-1 md:overflow-visible md:border-r md:border-b-0 md:px-2.5 md:py-3.5">
                <div className="flex items-center gap-2.5 pr-2 md:px-2 md:pt-1 md:pb-4">
                    <BrandMark />
                    <span className="hidden text-base font-bold tracking-tight md:block">Bridge</span>
                </div>
                <nav className="flex gap-0.5 md:flex-col">
                    {NAV.map(({ to, icon: Icon, label }) => (
                        <NavLink key={to} to={to} aria-label={label} title={label}
                            className={({ isActive }) => cn(
                                'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors',
                                isActive ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                            )}>
                            <Icon className="size-[17px] shrink-0" aria-hidden="true" />
                            <span className="hidden md:inline">{label}</span>
                        </NavLink>
                    ))}
                </nav>
                <div className="mt-auto hidden items-center gap-2.5 border-t px-2 pt-3 md:flex">
                    <div aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full bg-primary-soft text-[11px] font-bold text-primary">{initials(userName)}</div>
                    <div className="min-w-0">
                        <p className="truncate text-[13px] font-semibold">{userName}</p>
                        <p className="truncate text-[11px] text-faint">{isDemo ? 'Demo workspace' : userEmail}</p>
                    </div>
                </div>
            </aside>

            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <header className="flex items-center gap-2.5 border-b bg-card px-4 py-2.5 sm:px-5">
                    <p className="flex min-w-0 items-center gap-2 font-semibold">
                        <span className="truncate">{dataset?.label ?? 'Bridge'}</span>
                        {dataset && <span className="hidden text-sm font-normal text-muted-foreground sm:inline">· {dataset.period_start} to {dataset.period_end}</span>}
                    </p>
                    {isDemo && <span data-testid="demo-pill" className="shrink-0 rounded-full bg-violet-soft px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap text-violet">Demo data</span>}
                    <span className="flex-1" />
                    <Button variant="ghost" size="icon" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={toggleTheme}>
                        {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
                    </Button>
                    {isDemo
                        ? onSignIn && <Button variant="outline" className="shrink-0" onClick={onSignIn}><LogIn aria-hidden="true" />Sign in</Button>
                        : <Button variant="outline" disabled={signingOut} onClick={signOut}><LogOut aria-hidden="true" />{signingOut ? 'Signing out…' : 'Sign out'}</Button>}
                </header>
                <main className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto w-full max-w-[1240px] px-4 pt-5 pb-12 sm:px-5">
                        <Outlet />
                    </div>
                </main>
            </div>
            <LearnedRulesSheet />
        </div>
    );
}
