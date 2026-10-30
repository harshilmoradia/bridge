import type { LucideIcon } from 'lucide-react';
import { ArrowRight, Moon, ShieldCheck, Sparkles, Sun, UserCheck, Workflow } from 'lucide-react';
import { Link } from 'react-router';
import { BrandMark } from '../components/BrandMark';
import { Button } from '../components/ui/button';
import { useTheme } from '../context/theme';

const FEATURES: { icon: LucideIcon; title: string; body: string }[] = [
    { icon: Workflow, title: 'Agents match the books', body: 'Nemotron agents compare your bank statement to the ledger and close every item they can prove.' },
    { icon: ShieldCheck, title: 'Policy-gated, not guesswork', body: 'Auto-close depends on your policy and passing code checks. Model confidence is never the gate.' },
    { icon: UserCheck, title: 'Humans approve the rest', body: 'Anything left lands in your queue with the evidence and a draft journal entry.' },
    { icon: Sparkles, title: 'Learns from your decisions', body: 'Approve once, remember the rule, and the next run closes similar items on its own.' },
];

export default function LandingPage({ onSignIn }: { onSignIn?: () => void }) {
    const { theme, toggleTheme } = useTheme();
    return (
        <div className="min-h-dvh bg-background text-foreground">
            <header className="mx-auto flex max-w-5xl items-center gap-2.5 px-5 py-4">
                <BrandMark />
                <span className="text-base font-bold tracking-tight">Bridge</span>
                <span className="flex-1" />
                <Button variant="ghost" size="icon" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={toggleTheme}>
                    {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
                </Button>
                {onSignIn && <Button variant="outline" onClick={onSignIn}>Sign in</Button>}
            </header>

            <main className="mx-auto max-w-5xl px-5">
                <section className="flex flex-col items-center py-16 text-center sm:py-24">
                    <BrandMark size="lg" />
                    <h1 className="mt-6 max-w-[20ch] text-4xl font-semibold tracking-tight text-balance sm:text-5xl">Bank reconciliation, finished by agents.</h1>
                    <p className="mt-4 max-w-[56ch] text-base text-balance text-muted-foreground">
                        Bridge matches your bank statement to the ledger, closes what policy allows, and sends the rest to you with a draft journal entry.
                    </p>
                    <Button asChild size="lg" className="mt-8 px-5 font-semibold">
                        <Link to="/reconcile">Explore Demo<ArrowRight aria-hidden="true" /></Link>
                    </Button>
                    <p className="mt-3 text-xs text-muted-foreground">Sample data only. Nothing posts to an ERP.</p>
                </section>

                <section aria-label="Features" className="grid gap-4 pb-20 sm:grid-cols-2 lg:grid-cols-4">
                    {FEATURES.map(({ icon: Icon, title, body }) => (
                        <div key={title} className="rounded-lg border bg-card p-4 shadow-card">
                            <div aria-hidden="true" className="grid size-9 place-items-center rounded-md bg-primary-soft text-primary">
                                <Icon className="size-[18px]" />
                            </div>
                            <h2 className="mt-3 text-sm font-semibold">{title}</h2>
                            <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{body}</p>
                        </div>
                    ))}
                </section>
            </main>
        </div>
    );
}
