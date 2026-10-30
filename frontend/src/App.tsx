import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router';
import { QueryClientProvider } from '@tanstack/react-query';
import { AuthGate } from './components/AuthGate';
import { AppLayout } from './components/AppLayout';
import { queryClient } from './lib/queryClient';
import { BankPage, LedgerPage, NotFoundPage, ReportPage } from './pages/Pages';
import { RunTracePage } from './pages/RunTracePage';
import { ReconcilePage } from './pages/ReconcilePage';
import { Skeleton } from './components/ui/skeleton';

const EvalsPage = lazy(() => import('./pages/EvalsPage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));

export default function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <AuthGate>
                {(identity, signOut, signingOut, signIn) => (
                    <BrowserRouter key={identity.id}>
                        <Routes>
                            <Route index element={<Suspense fallback={null}><LandingPage onSignIn={signIn} /></Suspense>} />
                            <Route element={<AppLayout key={identity.id} userName={identity.displayName} userEmail={identity.email} isDemo={identity.isDemo}
                                signOut={() => void signOut()} signingOut={signingOut} onSignIn={signIn} />}>
                                <Route path="reconcile" element={<ReconcilePage />} />
                                <Route path="bank" element={<BankPage />} />
                                <Route path="ledger" element={<LedgerPage />} />
                                <Route path="evals" element={<Suspense fallback={<div role="status" aria-label="Loading" className="space-y-2"><Skeleton className="h-8 w-1/3" /><Skeleton className="h-64 w-full" /></div>}><EvalsPage /></Suspense>} />
                                <Route path="runs/:id" element={<RunTracePage />} />
                                <Route path="report/:runId" element={<ReportPage />} />
                                <Route path="*" element={<NotFoundPage />} />
                            </Route>
                        </Routes>
                    </BrowserRouter>
                )}
            </AuthGate>
        </QueryClientProvider>
    );
}
