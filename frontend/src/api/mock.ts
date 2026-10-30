// Mock mode (VITE_USE_MOCKS=true): serves JSON fixtures shaped like API v1. Decisions and runs mutate an in-memory copy.
import datasets from './fixtures/datasets.json';
import bankTransactions from './fixtures/bank-transactions.json';
import glEntries from './fixtures/gl-entries.json';
import statementFixture from './fixtures/statement.json';
import runCompletedFixture from './fixtures/run-completed.json';
import { MOCK_REPORT } from './mockReport';
import itemsFixture from './fixtures/items.json';
import auditFixture from './fixtures/run-audit.json';
import { applyRules, isSeeded, mockLearnable } from '../lib/rules';
import { postToStatement, settleRuleItems } from '../lib/statementPost';
import rulesFixture from './fixtures/rules.json';
import { ApiError, type RequestOptions } from './http';
import { MOCK_EXTRA_ROWS } from './mockExtras';
import { MockRunPoller, mockStageCount } from './mockProgress';
import { fromCents, toCents } from '../lib/cents';
import type {
    AuditEntry, BankTransaction, Run, DecisionRequest, DecisionResponse, DemoResetResponse, ForgetAllRulesResponse, ForgetRuleResponse,
    GlEntry, Item, RagChatRequest, RagChatResponse, RagChatSource, ReconStatus, Rule, Statement,
} from './types';

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
    evidence: [{ type: 'policy', id: 'always_escalate_kinds', note: null }], flags: [], model: null, confidence: null, rule_id: null, learnable: false,
    proposed_entry: { id: `5c0e7d3a-mock-${n}`, debit_account: delta.startsWith('-') ? account : '1010', credit_account: delta.startsWith('-') ? '1010' : account, amount: delta.replace('-', ''), memo, status: 'draft' },
    created_at: '2026-10-26T15:01:00Z',
}));
const withLearnable = (list: Item[]): Item[] => list.map(i => ({ ...i, learnable: mockLearnable(i) }));
const initialItems = (): Item[] => withLearnable([...copy<Item[]>(itemsFixture), ...extraItems()]);
let items = initialItems();
// Seeded fixture rules are display-only and can't be forgotten. Rules learned by approving with remember survive a
// reset (B-14), as on the real backend; the next run applies them. Ids are never reused, like a Postgres serial.
const seededRules = (): Rule[] => copy<Rule[]>(rulesFixture);
let learnedRules: (Rule & { amount_sign: 1 | -1 })[] = [];
let nextRuleId = Math.max(0, ...seededRules().map(r => r.id)) + 1;
const allRules = (): Rule[] => [...seededRules(), ...learnedRules.map(({ amount_sign: _sign, ...rule }) => rule)];
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

function mockRagChat(request: RagChatRequest): RagChatResponse {
    if (!(datasets as { id: string }[]).some(dataset => dataset.id === request.dataset)) throw notFound('Dataset', 'dataset_not_found');
    const bank = withItems(bankTransactions as BankTransaction[], row => row.txn_id, 'bank_ids');
    const gl = withItems(glEntries as GlEntry[], row => row.entry_id, 'gl_ids');
    const query = request.question.trim().toLocaleLowerCase();
    const tokens = query.split(/[^a-z0-9]+/).filter(token => token.length > 1);
    const semanticGroups = [
        ['fee', 'fees', 'charge', 'charges', 'service', 'maintenance'],
        ['salary', 'payroll', 'wage', 'wages'],
        ['deposit', 'receipt', 'credit'],
        ['rent', 'lease'],
    ];
    const expanded = new Set(tokens);
    for (const group of semanticGroups) if (group.some(word => expanded.has(word))) group.forEach(word => expanded.add(word));
    const itemById = new Map(items.map(item => [item.id, item]));
    const candidates: RagChatSource[] = [
        ...bank.filter(row => (!request.source_type || request.source_type === 'bank_transaction')
            && (!request.date_from || row.posted_date >= request.date_from)
            && (!request.date_to || row.posted_date <= request.date_to)
            && (!request.amount || row.amount === request.amount)
            && (!request.status || row.recon_status === request.status)
            && (row.txn_id.toLocaleLowerCase() === query || [...expanded].some(token => `${row.description} ${row.type} ${row.txn_id}`.toLocaleLowerCase().includes(token))))
            .map(row => ({
                source_type: 'bank_transaction' as const, source_id: row.txn_id, date: row.posted_date,
                amount: row.amount, description: row.description, type: row.type, check_number: row.check_number,
                running_balance: row.running_balance, account: null, counter_account: null, counterparty: null,
                guardrail: row.guardrail, status: row.recon_status, item: row.item_id ? (itemById.get(row.item_id) ?? null) : null,
                score: row.txn_id.toLocaleLowerCase() === query ? 0.06 : 0.04,
                matched_by: row.txn_id.toLocaleLowerCase() === query ? ['exact'] : ['full_text', 'vector'],
            })),
        ...gl.filter(row => (!request.source_type || request.source_type === 'gl_entry')
            && (!request.date_from || row.date >= request.date_from)
            && (!request.date_to || row.date <= request.date_to)
            && (!request.amount || row.amount === request.amount)
            && (!request.status || row.recon_status === request.status)
            && (row.entry_id.toLocaleLowerCase() === query || [...expanded].some(token => `${row.description} ${row.method} ${row.entry_id} ${row.account}`.toLocaleLowerCase().includes(token))))
            .map(row => ({
                source_type: 'gl_entry' as const, source_id: row.entry_id, date: row.date,
                amount: row.amount, description: row.description, type: row.method, check_number: row.check_number,
                running_balance: null, account: row.account, counter_account: row.counter_account,
                counterparty: row.counterparty, guardrail: row.guardrail, status: row.recon_status,
                item: row.item_id ? (itemById.get(row.item_id) ?? null) : null,
                score: row.entry_id.toLocaleLowerCase() === query ? 0.06 : 0.04,
                matched_by: row.entry_id.toLocaleLowerCase() === query ? ['exact'] : ['full_text', 'vector'],
            })),
    ].slice(0, 8);
    const noEvidence = candidates.length === 0;
    return {
        message: {
            role: 'assistant',
            content: noEvidence
                ? 'I could not find a matching record in this demo dataset. Try a transaction ID, amount, date, or related description.'
                : `I found ${candidates.length} related record${candidates.length === 1 ? '' : 's'} in the selected dataset. Review the source cards below for the current transaction and reconciliation status.`,
        },
        model: 'bridge-demo-search', sources: candidates, citations: [], no_evidence: noEvidence,
    };
}

export async function mockRequest<T>(path: string, { method = 'GET', query = {}, body }: RequestOptions = {}): Promise<T> {
    await delay();
    return copy<T>(route(path, method, query, body));
}

function route(path: string, method: string, query: Record<string, string | undefined>, body: unknown): unknown {
    if (method === 'POST' && path === '/chat/ask') return mockRagChat(body as RagChatRequest);
    if (method === 'GET' && path === '/datasets') return datasets;
    if (method === 'GET' && path === '/bank-transactions') return withItems(bankTransactions as BankTransaction[], r => r.txn_id, 'bank_ids').filter(r => inRange(r.posted_date, query.from, query.to));
    if (method === 'GET' && path === '/gl-entries') return withItems(glEntries as GlEntry[], r => r.entry_id, 'gl_ids').filter(r => inRange(r.date, query.from, query.to));
    if (method === 'GET' && path === '/statement') return statement;
    if (method === 'GET' && path === '/rules') return allRules();
    if (method === 'DELETE' && path === '/rules') {
        const response: ForgetAllRulesResponse = { rules_deleted: learnedRules.length };
        learnedRules = [];
        return response;
    }
    const ruleMatch = /^\/rules\/([^/]+)$/.exec(path);
    if (method === 'DELETE' && ruleMatch) {
        const id = Number(ruleMatch[1]);
        const seeded = seededRules().find(r => r.id === id);
        if (seeded && isSeeded(seeded)) throw new ApiError('rule_not_deletable', `Rule ${id} is seeded and can't be forgotten`, 409);
        if (!learnedRules.some(r => r.id === id)) throw notFound(`Rule ${ruleMatch[1]}`, 'rule_not_found');
        learnedRules = learnedRules.filter(r => r.id !== id);
        const response: ForgetRuleResponse = { rule_id: id };
        return response;
    }
    if (method === 'POST' && path === '/demo/reset') {
        items = initialItems(); poller.reset(runCompleted.id); statement = initialStatement(); audit = initialAudit();
        const response: DemoResetResponse = { dataset: statement.dataset, runs_deleted: 1, rules_kept: learnedRules.length };
        return response;
    }
    if (method === 'POST' && path === '/runs') {
        const id = crypto.randomUUID(); // a fresh id per run, as the real API gives
        poller.start(id);
        items = withLearnable(applyRules(initialItems().map(i => ({ ...i, run_id: id })), learnedRules)); audit = [];
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
        const learnable = item.learnable;
        item.status = approved ? 'approved' : 'rejected';
        item.learnable = false;
        if (item.proposed_entry) item.proposed_entry.status = item.status;
        if (approved) {
            postToStatement(statement, item, delta);
        }
        // Only an approval of a learnable item saves a rule; anything else returns rule_id null.
        let ruleId: number | null = null;
        if (request.remember && approved && learnable && item.proposed_entry) {
            const entry = item.proposed_entry;
            const direction = toCents(item.amount_delta) < 0n ? 'out' : 'in';
            const learned: Rule & { amount_sign: 1 | -1 } = {
                id: nextRuleId++, kind: item.kind, pattern: { description_regex: entry.memo, direction },
                action: { debit: entry.debit_account, credit: entry.credit_account, amount: entry.amount }, amount_sign: direction === 'out' ? -1 : 1,
                source_item: item.id, created_by: 'user:demo@bridge.local', active: true, created_at: new Date().toISOString(), dataset: statement.dataset, origin: 'learned',
            };
            learnedRules.push(learned); ruleId = learned.id;
        }
        audit.push({
            id: Math.max(0, ...audit.map(e => e.id)) + 1, run_id: item.run_id, entity_type: 'item', entity_id: item.id, action: request.decision,
            actor: 'user:demo@bridge.local', model: null, created_at: new Date().toISOString(),
            detail: { decision_id: crypto.randomUUID(), remember: Boolean(request.remember), note: request.note ?? null, entry_override: override ?? null },
        });
        const response: DecisionResponse = copy<DecisionResponse>({ item, statement, rule_id: ruleId });
        return response;
    }
    throw notFound(`${method} ${path}`);
}
