import type { RangeParams, ReconStatus } from './types';

export const keys = {
    datasets: ['datasets'] as const,
    bank: (p: RangeParams) => ['bank-transactions', p] as const,
    gl: (p: RangeParams) => ['gl-entries', p] as const,
    statements: ['statement'] as const,
    runItems: ['run-items'] as const,
    banks: ['bank-transactions'] as const,
    gls: ['gl-entries'] as const,
    statement: (dataset: string, runId?: string) => ['statement', dataset, runId ?? null] as const,
    run: (id: string) => ['run', id] as const,
    items: (id: string, status?: ReconStatus) => ['run-items', id, status ?? null] as const,
    rules: ['rules'] as const,
};

export interface StatementCache {
    setQueryData(queryKey: readonly unknown[], updater: unknown): unknown;
}

// A decision response carries the fresh statement: write it to the live statement and its own run's entry only, so older runs' cached statements stay as they were.
export function writeStatement(client: StatementCache, statement: { dataset: string; run_id: string | null }) {
    client.setQueryData(keys.statement(statement.dataset), statement);
    if (statement.run_id) client.setQueryData(keys.statement(statement.dataset, statement.run_id), statement);
}
