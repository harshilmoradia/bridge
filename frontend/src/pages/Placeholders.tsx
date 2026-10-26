import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router';

function Page({ title, children }: { title: string; children?: ReactNode }) {
    return (
        <section className="space-y-2">
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">Placeholder. Content arrives in a later U-* task.</p>
            {children}
        </section>
    );
}

export const ReconcilePage = () => <Page title="Reconcile" />;
export const BankPage = () => <Page title="Bank transactions" />;
export const LedgerPage = () => <Page title="Ledger entries" />;

export function RunPage() {
    const { id } = useParams<{ id: string }>();
    return <Page title="Run"><p className="text-sm">Run ID: <code data-testid="param">{id}</code></p></Page>;
}

export function ReportPage() {
    const { runId } = useParams<{ runId: string }>();
    return <Page title="Report"><p className="text-sm">Run ID: <code data-testid="param">{runId}</code></p></Page>;
}

export const NotFoundPage = () => (
    <Page title="Page not found">
        <Link to="/reconcile" className="text-sm font-medium text-primary underline">Back to Reconcile</Link>
    </Page>
);
