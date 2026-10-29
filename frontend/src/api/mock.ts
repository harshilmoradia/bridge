// Mock mode (VITE_USE_MOCKS=true): serves JSON fixtures shaped like API v1. Decisions and runs mutate an in-memory copy.
import datasets from './fixtures/datasets.json';
import bankTransactions from './fixtures/bank-transactions.json';
import glEntries from './fixtures/gl-entries.json';
import statementFixture from './fixtures/statement.json';
import runCompletedFixture from './fixtures/run-completed.json';
import { MOCK_REPORT } from './mockReport';
import itemsFixture from './fixtures/items.json';
import auditFixture from './fixtures/run-audit.json';
import { applyRules } from '../lib/rules';
import { postToStatement, settleRuleItems } from '../lib/statementPost';
import rulesFixture from './fixtures/rules.json';
import { ApiError, type RequestOptions } from './http';
import { MOCK_EXTRA_ROWS } from './mockExtras';
import { MockRunPoller, mockStageCount } from './mockProgress';
import { fromCents, toCents } from '../lib/cents';
import type { AuditEntry, BankTransaction, Run, DecisionRequest, DecisionResponse, DemoResetResponse, GlEntry, Item, ReconStatus, Rule, Statement } from './types';

// The fixture's short report is replaced here with the fuller mock one; docs fixtures stay untouched.
const runCompleted = { ...runCompletedFixture, report: MOCK_REPORT };

const DELAY_MS = 250;
const delay = () => new Promise(resolve => setTimeout(resolve, DELAY_MS));
const copy = <T,>(value: unknown): T => structuredClone(value) as T;

const initialStatement = (): Statement => ({ ...copy<Statement>(statementFixture), run_id: runCompleted.id });
// Mock-only extras so the five needs_approval items' deltas sum to the 864.09 difference and the card can reach 0.00.
const extraItems = (): Item[] => MOCK_EXTRA_ROWS.map(([n, kind, delta, account, memo]) => ({
    id: `0b6d1f1e-6c55-4f0a-8a51-1d1d7f3f${n}`, run_id: runCompleted.id, kind, resolution: 'escalate', status: 'needs_approval' as const,
    bank_ids: [], gl_ids: [], amount_delta: delta, reasoning: `Mock-only item (${kind.replaceAll('_', ' ')}) so the demo difference can reach 0.00.`,
    evidence: [{ type: 'policy', id: 'always_escalate_kinds', note: null }], flags: [], model: null, confidence: null, rule_id: null,
    proposed_entry: { id: `5c0e7d3a-mock-${n}`, debit_account: delta.startsWith('-') ? account : '1010', credit_account: delta.startsWith('-') ? '1010' : account, amount: delta.replace('-', ''), memo, status: 'draft' },
    created_at: '2026-10-26T15:01:00Z',
}));
const initialItems = (): Item[] => [...copy<Item[]>(itemsFixture), ...extraItems()];
let items = initialItems();
let rules = copy<Rule[]>(rulesFixture);
// Rules learned by approving with remember in this mock session; the next run applies them. The seeded fixture rule is display-only.
let learnedRules: (Rule & { amount_sign: 1 | -1 })[] = [];
let statement = initialStatement();
const initialAudit = () => copy<AuditEntry[]>(auditFixture);
let audit = initialAudit();
// After POST /runs the run advances one stage per poll, then reports "completed", so the live step list can be seen.
const poller = new MockRunPoller(runCompleted.id, mockStageCount(runCompleted as Run));

const notFound = (what: string, code = 'not_found') => new ApiError(code, `${what} not found`, 404);
const inRange = (date: string, from?: string, to?: string) => (!from || date >= from) && (!to || date <= to);

// Rows are fixtures with no item links; once the (mock) run is done, tag them from the in-memory items so highlighting and live statuses work.
function withItems<R extends { recon_status: ReconStatus; item_id: string | null }>(rows: R[], idOf: (row: R) => string, side: 'bank_ids' | 'gl_ids'): R[] {
    if (poller.active) return copy<R[]>(rows);
    const byRow = new Map<string, Item>();
    for (const item of items) for (const id of item[side]) byRow.set(id, item);
    return rows.map(row => {
        const item = byRow.get(idOf(row));
        return item ? { ...row, item_id: item.id, recon_status: item.status } : { ...row };
    });
}

export async function mockRequest<T>(path: string, { method = 'GET', query = {}, body }: RequestOptions = {}): Promise<T> {
    await delay();
    return copy<T>(route(path, method, query, body));
}

function route(path: string, method: string, query: Record<string, string | undefined>, body: unknown): unknown {
    if (method === 'GET' && path === '/datasets') return datasets;
    if (method === 'GET' && path === '/bank-transactions') return withItems(bankTransactions as BankTransaction[], r => r.txn_id, 'bank_ids').filter(r => inRange(r.posted_date, query.from, query.to));
    if (method === 'GET' && path === '/gl-entries') return withItems(glEntries as GlEntry[], r => r.entry_id, 'gl_ids').filter(r => inRange(r.date, query.from, query.to));
    if (method === 'GET' && path === '/statement') return statement;
    if (method === 'GET' && path === '/rules') return rules;
    if (method === 'POST' && path === '/demo/reset') {
        const deletedRules = learnedRules.length;
        items = initialItems(); poller.reset(runCompleted.id); rules = copy(rulesFixture); learnedRules = []; statement = initialStatement(); audit = initialAudit();
        const response: DemoResetResponse = { dataset: statement.dataset, runs_deleted: 1, rules_deleted: deletedRules };
        return response;
    }
    if (method === 'POST' && path === '/runs') {
        const id = crypto.randomUUID(); // a fresh id per run, as the real API gives
        poller.start(id);
        items = applyRules(initialItems().map(i => ({ ...i, run_id: id })), learnedRules); audit = [];
        statement = { ...initialStatement(), run_id: id };
        settleRuleItems(statement, items);
        return { id, status: 'queued' };
    }
    const auditMatch = /^\/runs\/([^/]+)\/audit$/.exec(path);
    if (method === 'GET' && auditMatch) {
        if (auditMatch[1] !== runCompleted.id && auditMatch[1] !== poller.currentId) throw notFound('Run', 'run_not_found');
        return poller.active && auditMatch[1] === poller.currentId ? [] : audit.map(e => ({ ...e, run_id: auditMatch[1] }));
    }
    const runMatch = /^\/runs\/([^/]+)(\/items)?$/.exec(path);
    if (method === 'GET' && runMatch) {
        if (runMatch[1] !== runCompleted.id && runMatch[1] !== poller.currentId) throw notFound('Run', 'run_not_found');
        if (runMatch[2]) return poller.active ? [] : items.filter(i => !query.status || i.status === query.status);
        return poller.poll(runCompleted as Run, runMatch[1]);
    }
    const decisionMatch = /^\/items\/([^/]+)\/decision$/.exec(path);
    if (method === 'POST' && decisionMatch) {
        const item = items.find(i => i.id === decisionMatch[1]);
        if (!item) throw notFound('Item', 'item_not_found');
        if (item.status !== 'needs_approval') throw new ApiError('item_not_pending', `Item ${item.id} is ${item.status}; only needs_approval items can be decided`, 409);
        const request = body as DecisionRequest;
        const approved = request.decision === 'approve';
        const override = request.entry_override;
        if (override?.memo?.toLowerCase().includes('fail')) throw new ApiError('server_error', 'Mock failure (memo contains "fail").', 500);
        if (override && item.proposed_entry) Object.assign(item.proposed_entry, override);
        // The adjustment amount follows an edited entry amount, keeping the sign of the item's delta.
        const delta = override?.amount ? fromCents(toCents(item.amount_delta) < 0n ? -toCents(override.amount) : toCents(override.amount)) : item.amount_delta;
        item.status = approved ? 'approved' : 'rejected';
        if (item.proposed_entry) item.proposed_entry.status = item.status;
        if (approved) {
            postToStatement(statement, item, delta);
        }
        if (request.remember) {
            const learned: Rule & { amount_sign: 1 | -1 } = { id: Math.max(0, ...rules.map(r => r.id)) + 1, kind: item.kind, pattern: { description_regex: item.proposed_entry?.memo ?? item.kind }, action: { debit: item.proposed_entry?.debit_account, credit: item.proposed_entry?.credit_account }, amount_sign: toCents(item.amount_delta) < 0n ? -1 : 1, source_item: item.id, created_by: 'demo@bridge.ai', active: true, created_at: new Date().toISOString() };
            rules.push(learned); learnedRules.push(learned);
        }
        audit.push({
            id: Math.max(0, ...audit.map(e => e.id)) + 1, run_id: item.run_id, entity_type: 'item', entity_id: item.id, action: request.decision,
            actor: 'user:demo@bridge.local', model: null, created_at: new Date().toISOString(),
            detail: { decision_id: crypto.randomUUID(), remember: Boolean(request.remember), note: request.note ?? null, entry_override: override ?? null },
        });
        const response: DecisionResponse = copy<DecisionResponse>({ item, statement });
        return response;
    }
    throw notFound(`${method} ${path}`);
}
