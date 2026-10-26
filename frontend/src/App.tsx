import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { QueryClientProvider } from '@tanstack/react-query';
import { AuthGate } from './components/AuthGate';
import { AppLayout } from './components/AppLayout';
import { queryClient } from './lib/queryClient';
import { BankPage, LedgerPage, NotFoundPage, ReconcilePage, ReportPage, RunPage } from './pages/Placeholders';

export default function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <AuthGate>
                {(identity, signOut, signingOut) => (
                    <BrowserRouter>
                        <Routes>
                            <Route element={<AppLayout key={identity.id} userName={identity.displayName} userEmail={identity.email} signOut={() => void signOut()} signingOut={signingOut} />}>
                                <Route index element={<Navigate to="/reconcile" replace />} />
                                <Route path="reconcile" element={<ReconcilePage />} />
                                <Route path="bank" element={<BankPage />} />
                                <Route path="ledger" element={<LedgerPage />} />
                                <Route path="runs/:id" element={<RunPage />} />
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
