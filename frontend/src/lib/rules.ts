// Pure helpers for learned rules (B-13): the "Applied rule #N" chip, item grouping and the rules table rows.
import type { Item, Rule } from '../api/types.ts';

export const RULE_TOOLTIP = 'Auto-resolved by a rule you approved earlier';
const MAX_CHARS = 120;
const clip = (s: string) => (s.length > MAX_CHARS ? `${s.slice(0, MAX_CHARS)}…` : s);

export const isRuleApplied = (item: Pick<Item, 'flags'>) => item.flags.includes('rule_applied');

/** The rule number to show, or null when no rule was applied. A rule_applied flag without an id still shows a plain chip. */
export const appliedRuleLabel = (item: Pick<Item, 'flags' | 'rule_id'>): string | null =>
    isRuleApplied(item) ? (item.rule_id !== null ? `Applied rule #${item.rule_id}` : 'Applied rule') : null;

/** Auto-resolved by a rule, as opposed to auto-resolved by policy. */
export const isRuleAutoResolved = (item: Pick<Item, 'flags' | 'status'>) => item.status === 'auto_resolved' && isRuleApplied(item);

const textOf = (v: unknown): string => (v === null || v === undefined ? '-' : typeof v === 'object' ? JSON.stringify(v) : String(v));

/** Rule pattern as short text: the description regex when there is one, else key=value pairs. */
export function patternText(pattern: Record<string, unknown>): string {
    const regex = pattern.description_regex;
    if (typeof regex === 'string') return clip(regex);
    const parts = Object.entries(pattern).slice(0, 5).map(([k, v]) => `${k}=${textOf(v)}`);
    return clip(parts.join(', ')) || '-';
}

/** Rule action as "DR x / CR y" when it has accounts. */
export function accountsText(action: Record<string, unknown>): string {
    const debit = action.debit ?? action.debit_account;
    const credit = action.credit ?? action.credit_account;
    if (debit === undefined && credit === undefined) return '-';
    return clip(`DR ${textOf(debit)} / CR ${textOf(credit)}`);
}

export interface RuleRow { id: number; kind: string; pattern: string; accounts: string; createdBy: string; createdAt: string; active: boolean }

export const ruleRows = (rules: Rule[]): RuleRow[] =>
    [...rules].sort((a, b) => a.id - b.id).map(r => ({
        id: r.id, kind: r.kind.replaceAll('_', ' '), pattern: patternText(r.pattern), accounts: accountsText(r.action),
        createdBy: r.created_by.replace(/^user:/, ''), createdAt: r.created_at, active: r.active,
    }));

const NEVER_BY_RULE = new Set(['unknown', 'duplicate_gl_entry', 'unidentified_receipt', 'transposition']);
type LearnedRule = Pick<Rule, 'id' | 'kind' | 'active'> & { amount_sign?: 1 | -1 };
const signOf = (amount: string): 1 | -1 => (amount.startsWith('-') ? -1 : 1);

/**
 * Mock only: the next run auto-resolves still-open items that an active learned rule covers.
 * Kind + sign only in the mock; pattern, dataset and accounts are matched by the backend.
 */
export function applyRules(items: Item[], rules: LearnedRule[]): Item[] {
    return items.map(item => {
        const rule = item.status === 'needs_approval' && !NEVER_BY_RULE.has(item.kind)
            ? rules.find(r => r.active && r.kind === item.kind && (r.amount_sign === undefined || r.amount_sign === signOf(item.amount_delta)))
            : undefined;
        if (!rule) return item;
        return {
            ...item, status: 'auto_resolved', resolution: 'auto_resolve', flags: [...item.flags, 'rule_applied'], rule_id: rule.id,
            reasoning: `Auto-resolved by rule #${rule.id}, which you approved earlier.`,
            evidence: [...item.evidence.filter(e => e.type !== 'policy'), { type: 'rule', id: String(rule.id), note: null }],
            proposed_entry: item.proposed_entry ? { ...item.proposed_entry, status: 'posted' } : null, learnable: false,
        };
    });
}

/**
 * Mock only: mirrors the backend's rule for `Item.learnable`. An open item can teach a rule when it has a draft
 * entry, bank or GL text to take a pattern from, a kind rules may close, and no injection flag.
 */
export const mockLearnable = (item: Pick<Item, 'status' | 'kind' | 'flags' | 'proposed_entry' | 'bank_ids' | 'gl_ids'>): boolean =>
    item.status === 'needs_approval' && item.proposed_entry !== null && !NEVER_BY_RULE.has(item.kind)
    && !item.flags.includes('injection_flagged') && item.bank_ids.length + item.gl_ids.length > 0;

// ---- Remember-rule UI (U-12) ----

export const isSeeded = (rule: Pick<Rule, 'origin'>) => rule.origin === 'seeded';
export const learnedOnly = <R extends Pick<Rule, 'origin'>>(rules: R[]): R[] => rules.filter(r => !isSeeded(r));

const ONE_OFF_KINDS = new Set(['duplicate_gl_entry', 'transposition']);

/** Why the remember switch is off for this item, or null when it can learn. The backend's `learnable` is the source of truth. */
export function learnableReason(item: Pick<Item, 'learnable' | 'kind' | 'flags' | 'proposed_entry'>): string | null {
    if (item.learnable) return null;
    if (item.flags.includes('injection_flagged')) return 'Flagged text never becomes a rule.';
    if (isRuleApplied(item)) return 'A rule already covers this item.';
    if (ONE_OFF_KINDS.has(item.kind)) return "Duplicates and transpositions are one-off corrections, so Bridge won't learn a rule from them.";
    if (item.kind === 'unidentified_receipt') return "An unidentified receipt has no known payer to match next time, so Bridge won't learn a rule from it.";
    if (item.kind === 'unknown') return "Bridge couldn't tell what this item is, so there is no pattern to learn.";
    if (!item.proposed_entry) return "There's no journal entry to repeat, so there is nothing to learn.";
    return "This item has no bank or ledger text to match next time, so Bridge won't learn a rule from it.";
}

export interface RulePreview { kind: string; direction: 'in' | 'out'; debit: string; credit: string; amount: string }

/** What remembering would save: kind, direction (sign of the item's delta), and the entry's accounts and amount (decimal strings, untouched). */
export function rulePreview(item: Pick<Item, 'kind' | 'amount_delta'>, entry: { debit_account: string; credit_account: string; amount: string } | null): RulePreview | null {
    if (!entry) return null;
    return { kind: item.kind, direction: signOf(item.amount_delta) === -1 ? 'out' : 'in', debit: entry.debit_account, credit: entry.credit_account, amount: entry.amount };
}

/** Toast after a decision. Claims a saved rule only when the response carries its id. */
export function decisionToastText(title: string, decision: 'approve' | 'reject', ruleId: number | null): string {
    const base = `${title} ${decision === 'approve' ? 'approved' : 'rejected'}`;
    return ruleId !== null ? `${base} · Rule #${ruleId} saved` : base;
}

/** Extra line when the reviewer asked to remember but no rule came back. */
export function notLearnedNote(remember: boolean, decision: 'approve' | 'reject', ruleId: number | null): string | null {
    if (!remember || ruleId !== null) return null;
    return decision === 'reject' ? 'Rejections never become rules.' : 'No rule was saved for this item.';
}
