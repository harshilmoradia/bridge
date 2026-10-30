import { liveRequest, USE_MOCKS, type RequestOptions } from './http';
import { mockRequest } from './mock';
import type {
    AuditEntry, BankTransaction, CreateRunRequest, CreateRunResponse, Dataset, DecisionRequest, DecisionResponse, DemoResetResponse,
    ForgetAllRulesResponse, ForgetRuleResponse,
    GlEntry, Item, RagChatRequest, RagChatResponse, RangeParams, ReconStatus, Rule, Run, Statement,
} from './types';

function request<T>(path: string, options?: RequestOptions): Promise<T> {
    return USE_MOCKS ? mockRequest<T>(path, options) : liveRequest<T>(path, options);
}

export const api = {
    datasets: (signal?: AbortSignal) => request<Dataset[]>('/datasets', { signal }),
    bankTransactions: ({ dataset, from, to }: RangeParams, signal?: AbortSignal) =>
        request<BankTransaction[]>('/bank-transactions', { query: { dataset, from, to }, signal }),
    glEntries: ({ dataset, from, to }: RangeParams, signal?: AbortSignal) =>
        request<GlEntry[]>('/gl-entries', { query: { dataset, from, to }, signal }),
    statement: (dataset: string, runId?: string, signal?: AbortSignal) =>
        request<Statement>('/statement', { query: { dataset, run_id: runId }, signal }),
    createRun: (body: CreateRunRequest) => request<CreateRunResponse>('/runs', { method: 'POST', body }),
    run: (id: string, signal?: AbortSignal) => request<Run>(`/runs/${encodeURIComponent(id)}`, { signal }),
    runItems: (id: string, status?: ReconStatus, signal?: AbortSignal) =>
        request<Item[]>(`/runs/${encodeURIComponent(id)}/items`, { query: { status }, signal }),
    decide: (itemId: string, body: DecisionRequest) =>
        request<DecisionResponse>(`/items/${encodeURIComponent(itemId)}/decision`, { method: 'POST', body }),
    runAudit: (id: string, signal?: AbortSignal) => request<AuditEntry[]>(`/runs/${encodeURIComponent(id)}/audit`, { signal }),
    rules: (signal?: AbortSignal) => request<Rule[]>('/rules', { signal }),
    forgetRule: (id: number) => request<ForgetRuleResponse>(`/rules/${id}`, { method: 'DELETE' }),
    forgetAllRules: () => request<ForgetAllRulesResponse>('/rules', { method: 'DELETE' }),
    resetDemo: () => request<DemoResetResponse>('/demo/reset', { method: 'POST' }),
    ragChat: (body: RagChatRequest) => request<RagChatResponse>('/chat/ask', { method: 'POST', body }),
};
