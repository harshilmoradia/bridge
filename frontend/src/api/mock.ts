// Mock mode (VITE_USE_MOCKS=true): serves JSON fixtures shaped like API v1. Decisions and runs mutate an in-memory copy.
import datasets from './fixtures/datasets.json';
import bankTransactions from './fixtures/bank-transactions.json';
import glEntries from './fixtures/gl-entries.json';
import statementFixture from './fixtures/statement.json';
import runCompleted from './fixtures/run-completed.json';
import runRunning from './fixtures/run-running.json';
import itemsFixture from './fixtures/items.json';
import rulesFixture from './fixtures/rules.json';
import { ApiError, type RequestOptions } from './http';
import { fromCents, toCents } from '../lib/cents';
import type { BankTransaction, DecisionRequest, DecisionResponse, GlEntry, Item, Rule, Statement } from './types';

const DELAY_MS = 250;
const delay = () => new Promise(resolve => setTimeout(resolve, DELAY_MS));
const copy = <T,>(value: unknown): T => structuredClone(value) as T;

const initialStatement = (): Statement => ({ ...copy<Statement>(statementFixture), run_id: runCompleted.id });
let items = copy<Item[]>(itemsFixture);
let rules = copy<Rule[]>(rulesFixture);
let statement = initialStatement();
// After POST /runs the run reports "running" for a few polls, then "completed", so the live step list can be seen.
let pollsUntilDone = 0;

const notFound = (what: string) => new ApiError('not_found', `${what} not found`, 404);
const inRange = (date: string, from?: string, to?: string) => (!from || date >= from) && (!to || date <= to);

export async function mockRequest<T>(path: string, { method = 'GET', query = {}, body }: RequestOptions = {}): Promise<T> {
    await delay();
    return copy<T>(route(path, method, query, body));
}

function route(path: string, method: string, query: Record<string, string | undefined>, body: unknown): unknown {
    if (method === 'GET' && path === '/datasets') return datasets;
    if (method === 'GET' && path === '/bank-transactions') return (bankTransactions as BankTransaction[]).filter(r => inRange(r.posted_date, query.from, query.to));
    if (method === 'GET' && path === '/gl-entries') return (glEntries as GlEntry[]).filter(r => inRange(r.date, query.from, query.to));
    if (method === 'GET' && path === '/statement') return statement;
    if (method === 'GET' && path === '/rules') return rules;
    if (method === 'POST' && path === '/demo/reset') {
        items = copy(itemsFixture); rules = copy(rulesFixture); statement = initialStatement(); pollsUntilDone = 0;
        return { status: 'reset' };
    }
    if (method === 'POST' && path === '/runs') {
        pollsUntilDone = 3;
        return { id: runRunning.id, status: 'queued' };
    }
    const runMatch = /^\/runs\/([^/]+)(\/items)?$/.exec(path);
    if (method === 'GET' && runMatch) {
        if (runMatch[1] !== runCompleted.id) throw notFound('Run');
        if (runMatch[2]) return items.filter(i => !query.status || i.status === query.status);
        if (pollsUntilDone > 0) { pollsUntilDone -= 1; return runRunning; }
        return runCompleted;
    }
    const decisionMatch = /^\/items\/([^/]+)\/decision$/.exec(path);
    if (method === 'POST' && decisionMatch) {
        const item = items.find(i => i.id === decisionMatch[1]);
        if (!item) throw notFound('Item');
        const request = body as DecisionRequest;
        const approved = request.decision === 'approve';
        item.status = approved ? 'approved' : 'rejected';
        if (item.proposed_entry) item.proposed_entry.status = item.status;
        if (approved) {
            statement.book.lines.push({ item_id: item.id, kind: item.kind, label: item.proposed_entry?.memo ?? item.kind, amount: item.amount_delta, status: 'approved', applied: true, bank_ids: item.bank_ids, gl_ids: item.gl_ids });
            statement.book.adjusted_balance = fromCents(toCents(statement.book.adjusted_balance) + toCents(item.amount_delta));
            statement.unreconciled_difference = fromCents(toCents(statement.unreconciled_difference) - toCents(item.amount_delta));
        }
        if (request.remember) {
            rules.push({ id: rules.length + 1, kind: item.kind, pattern: { description_regex: item.proposed_entry?.memo ?? item.kind }, action: { debit: item.proposed_entry?.debit_account, credit: item.proposed_entry?.credit_account }, source_item: item.id, created_by: 'demo@bridge.ai', active: true, created_at: new Date().toISOString() });
        }
        const response: DecisionResponse = { item, statement };
        return response;
    }
    throw notFound(`${method} ${path}`);
}
