import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { CreateRunRequest, DecisionRequest, RangeParams, ReconStatus } from './types';

export const keys = {
    datasets: ['datasets'] as const,
    bank: (p: RangeParams) => ['bank-transactions', p] as const,
    gl: (p: RangeParams) => ['gl-entries', p] as const,
    statement: (dataset: string, runId?: string) => ['statement', dataset, runId ?? null] as const,
    run: (id: string) => ['run', id] as const,
    items: (id: string, status?: ReconStatus) => ['run-items', id, status ?? null] as const,
    rules: ['rules'] as const,
};

export const useDatasets = () => useQuery({ queryKey: keys.datasets, queryFn: ({ signal }) => api.datasets(signal) });

export const useBankTransactions = (params: RangeParams | undefined) =>
    useQuery({ queryKey: keys.bank(params ?? { dataset: '' }), queryFn: ({ signal }) => api.bankTransactions(params!, signal), enabled: Boolean(params) });

export const useGlEntries = (params: RangeParams | undefined) =>
    useQuery({ queryKey: keys.gl(params ?? { dataset: '' }), queryFn: ({ signal }) => api.glEntries(params!, signal), enabled: Boolean(params) });

export const useStatement = (dataset: string | undefined, runId?: string) =>
    useQuery({ queryKey: keys.statement(dataset ?? '', runId), queryFn: ({ signal }) => api.statement(dataset!, runId, signal), enabled: Boolean(dataset) });

// Polls every 2s while the run is in flight so the step list updates live.
export const useRun = (id: string | undefined) =>
    useQuery({
        queryKey: keys.run(id ?? ''), queryFn: ({ signal }) => api.run(id!, signal), enabled: Boolean(id),
        refetchInterval: query => (query.state.data?.status === 'queued' || query.state.data?.status === 'running' ? 2000 : false),
    });

export const useRunItems = (id: string | undefined, status?: ReconStatus) =>
    useQuery({ queryKey: keys.items(id ?? '', status), queryFn: ({ signal }) => api.runItems(id!, status, signal), enabled: Boolean(id) });

export const useRules = () => useQuery({ queryKey: keys.rules, queryFn: ({ signal }) => api.rules(signal) });

export function useCreateRun() {
    const client = useQueryClient();
    return useMutation({ mutationFn: (body: CreateRunRequest) => api.createRun(body), onSuccess: () => client.invalidateQueries({ queryKey: ['statement'] }) });
}

export function useDecideItem() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({ itemId, ...body }: DecisionRequest & { itemId: string }) => api.decide(itemId, body),
        onSuccess: () => Promise.all([
            client.invalidateQueries({ queryKey: ['run-items'] }),
            client.invalidateQueries({ queryKey: ['statement'] }),
            client.invalidateQueries({ queryKey: ['bank-transactions'] }),
            client.invalidateQueries({ queryKey: ['gl-entries'] }),
            client.invalidateQueries({ queryKey: ['rules'] }),
        ]),
    });
}

export function useResetDemo() {
    const client = useQueryClient();
    return useMutation({ mutationFn: () => api.resetDemo(), onSuccess: () => client.invalidateQueries() });
}
