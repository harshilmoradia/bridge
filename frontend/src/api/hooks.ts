import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { keys, writeStatement } from './keys';
import { RUN_POLL_MS, isRunActive } from '../lib/workspace';
import type { CreateRunRequest, DecisionRequest, Item, RangeParams, ReconStatus } from './types';

export { keys };

export const useDatasets = () => useQuery({ queryKey: keys.datasets, queryFn: ({ signal }) => api.datasets(signal) });

export const useBankTransactions = (params: RangeParams | undefined) =>
    useQuery({ queryKey: keys.bank(params ?? { dataset: '' }), queryFn: ({ signal }) => api.bankTransactions(params!, signal), enabled: Boolean(params) });

export const useGlEntries = (params: RangeParams | undefined) =>
    useQuery({ queryKey: keys.gl(params ?? { dataset: '' }), queryFn: ({ signal }) => api.glEntries(params!, signal), enabled: Boolean(params) });

export const useStatement = (dataset: string | undefined, runId?: string) =>
    useQuery({ queryKey: keys.statement(dataset ?? '', runId), queryFn: ({ signal }) => api.statement(dataset!, runId, signal), enabled: Boolean(dataset) });

// Polls every 1.5s while the run is in flight so the step list updates live.
export const useRun = (id: string | undefined) =>
    useQuery({
        queryKey: keys.run(id ?? ''), queryFn: ({ signal }) => api.run(id!, signal), enabled: Boolean(id),
        refetchInterval: query => (isRunActive(query.state.data?.status) ? RUN_POLL_MS : false),
    });

export const useRunItems = (id: string | undefined, status?: ReconStatus) =>
    useQuery({ queryKey: keys.items(id ?? '', status), queryFn: ({ signal }) => api.runItems(id!, status, signal), enabled: Boolean(id) });

// Polls while the run is active (pass the run's status); a decision invalidates it too.
export const useRunAudit = (id: string | undefined, active = false) =>
    useQuery({
        queryKey: keys.audit(id ?? ''), queryFn: ({ signal }) => api.runAudit(id!, signal), enabled: Boolean(id),
        refetchInterval: active ? RUN_POLL_MS : false,
    });

export const useRules = () => useQuery({ queryKey: keys.rules, queryFn: ({ signal }) => api.rules(signal) });

export function useCreateRun() {
    const client = useQueryClient();
    return useMutation({ mutationFn: (body: CreateRunRequest) => api.createRun(body), onSuccess: () => client.invalidateQueries({ queryKey: keys.statements }) });
}

// Optimistic: the item flips to approved/rejected immediately and is restored if the call fails.
export function useDecideItem() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({ itemId, ...body }: DecisionRequest & { itemId: string }) => api.decide(itemId, body),
        onMutate: async ({ itemId, decision }) => {
            await Promise.all([client.cancelQueries({ queryKey: keys.runItems }), client.cancelQueries({ queryKey: keys.statements })]);
            const snapshot = client.getQueriesData<Item[]>({ queryKey: keys.runItems });
            const status: ReconStatus = decision === 'approve' ? 'approved' : 'rejected';
            client.setQueriesData<Item[]>({ queryKey: keys.runItems }, old => old?.map(i => (i.id === itemId ? { ...i, status } : i)));
            return { snapshot };
        },
        onError: (_error, _vars, context) => { for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data); },
        onSuccess: response => writeStatement(client, response.statement),
        onSettled: () => Promise.all([
            client.invalidateQueries({ queryKey: keys.runItems }),
            client.invalidateQueries({ queryKey: keys.statements }),
            client.invalidateQueries({ queryKey: keys.banks }),
            client.invalidateQueries({ queryKey: keys.gls }),
            client.invalidateQueries({ queryKey: keys.rules }),
            client.invalidateQueries({ queryKey: ['run-audit'] }),
        ]),
    });
}

// No invalidation here: the caller clears page state first (afterReset), then invalidates, so the deleted run is never refetched.
export function useResetDemo() {
    const client = useQueryClient();
    const invalidateAll = () => {
        client.removeQueries({ queryKey: ['run'] });
        client.removeQueries({ queryKey: keys.runItems });
        client.removeQueries({ queryKey: ['run-audit'] });
        return client.invalidateQueries();
    };
    return { ...useMutation({ mutationFn: () => api.resetDemo() }), invalidateAll };
}
