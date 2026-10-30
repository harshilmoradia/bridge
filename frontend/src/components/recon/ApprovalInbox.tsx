import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowUpRight, Check, EyeOff, Lock, ShieldAlert, X } from 'lucide-react';
import { toast } from 'sonner';
import { useDecideItem } from '../../api/hooks';
import type { EvidenceRef, Item } from '../../api/types';
import { buildOverride, validateEntry, type EntryDraft } from '../../lib/entry';
import { accountName, inTab, isTypingTarget, kindTitle, modelTier, nextSelection, stepSelection, type InboxTab } from '../../lib/inbox';
import { isNegative } from '../../lib/money';
import { decisionToastText, learnableReason, notLearnedNote, rulePreview } from '../../lib/rules';
import { rulesPanel } from '../../lib/rulesPanel';
import type { TxRow } from '../../lib/tableModel';
import { cn } from '../../lib/utils';
import { Money } from '../Money';
import { RuleChip } from '../RuleChip';
import { StatusChip } from '../StatusChip';
import { Button } from '../ui/button';
import { Switch } from '../ui/switch';

// Per-item edit state lives in the inbox (keyed by item id) so an item restored after a failed decision keeps it.
interface ItemUi { editing: boolean; draft: EntryDraft | null; remember: boolean; showSent: boolean }
type Decide = (item: Item, decision: 'approve' | 'reject') => void;

const toDraft = (item: Item): EntryDraft | null => item.proposed_entry && {
    debit_account: item.proposed_entry.debit_account, credit_account: item.proposed_entry.credit_account,
    amount: item.proposed_entry.amount, memo: item.proposed_entry.memo,
};
const freshUi = (item: Item): ItemUi => ({ editing: false, remember: false, showSent: false, draft: toDraft(item) });

const TIER_TEXT = { code: 'text-tier-code', nano: 'text-tier-nano', super: 'text-tier-super', ultra: 'text-tier-ultra' } as const;
export const TierTag = ({ tier, title }: { tier: keyof typeof TIER_TEXT; title?: string }) => (
    <span title={title} className={cn('rounded-[3px] border border-current px-1 font-mono text-[10px] leading-[15px] font-semibold uppercase', TIER_TEXT[tier])}>{tier}</span>
);

const Kbd = ({ children }: { children: string }) => (
    <kbd className="rounded-[4px] border border-current px-1 font-mono text-[10.5px] leading-[15px] opacity-60">{children}</kbd>
);

function FlagChips({ item }: { item: Item }) {
    return <>
        {item.flags.includes('injection_flagged') && (
            <span data-testid="injection-chip" className="inline-flex items-center gap-1 rounded-full bg-destructive-soft px-1.5 text-[11px] leading-[18px] font-semibold text-destructive">
                <ShieldAlert className="size-3" aria-hidden="true" />Injection flagged
            </span>
        )}
        {item.flags.includes('pii_redacted') && (
            <span data-testid="pii-redacted-badge" title="Personal data was masked before any model saw this item"
                className="inline-flex items-center gap-1 rounded-full bg-violet-soft px-1.5 text-[11px] leading-[18px] font-semibold text-violet">
                <EyeOff className="size-3" aria-hidden="true" />PII masked
            </span>
        )}
    </>;
}

function QueueRow({ item, selected, onSelect }: { item: Item; selected: boolean; onSelect: () => void }) {
    return (
        <li data-item-id={item.id}>
            <button type="button" role="option" aria-selected={selected} onClick={onSelect}
                className={cn('grid w-full grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 rounded-md border border-transparent px-3 py-2.5 text-left transition-colors',
                    selected ? 'border-primary-line bg-primary-soft' : 'hover:bg-muted')}>
                <span className="min-w-0 truncate text-[13.5px] font-semibold">{kindTitle(item.kind)}</span>
                <Money value={item.amount_delta} className="text-right text-[13px] font-semibold" />
                <span className="col-span-2 line-clamp-2 text-[12.5px] text-muted-foreground">{item.reasoning}</span>
                <span className="col-span-2 flex flex-wrap gap-1 empty:hidden">
                    {item.status !== 'needs_approval' && <StatusChip status={item.status} />}
                    <RuleChip item={item} interactive={false} />
                    <FlagChips item={item} />
                </span>
            </button>
        </li>
    );
}

function Guardrails({ item, rows, ui, setUi }: { item: Item; rows: Map<string, TxRow>; ui: ItemUi; setUi: (p: Partial<ItemUi>) => void }) {
    const linked = [...item.bank_ids, ...item.gl_ids].map(id => rows.get(id)).filter((r): r is TxRow => Boolean(r));
    const injected = linked.filter(r => r.guardrail?.injection_flagged);
    const masked = linked.filter(r => r.guardrail?.pii_masked);
    return <>
        {item.flags.includes('injection_flagged') && (
            <div role="note" className="grid grid-cols-[18px_1fr] gap-2.5 rounded-lg border border-destructive bg-destructive-soft px-3 py-2.5 text-[13px]">
                <ShieldAlert className="size-[18px] text-destructive" aria-hidden="true" />
                <div className="min-w-0">
                    <p className="font-semibold">Prompt injection blocked</p>
                    <p>This text was passed to the agents as untrusted data and they ignored it. Bridge always holds a flagged row for a person.</p>
                    {/* Untrusted text: rendered as text only, never HTML. */}
                    {injected.map(r => <p key={r.id} className="mt-1.5 rounded-md border bg-card px-2 py-1.5 font-mono text-xs break-words"><span className="text-faint">{r.id} · </span>{r.original?.description ?? r.description}</p>)}
                </div>
            </div>
        )}
        {masked.length > 0 && (
            <div role="note" className="grid grid-cols-[18px_1fr] gap-2.5 rounded-lg bg-violet-soft px-3 py-2.5 text-[13px]">
                <EyeOff className="size-[18px] text-violet" aria-hidden="true" />
                <div className="min-w-0">
                    <p className="font-semibold">Personal data masked before any model saw it</p>
                    <label className="mt-1 flex items-center gap-2 text-xs">
                        <input type="checkbox" checked={ui.showSent} onChange={e => setUi({ showSent: e.target.checked })} /> Show what was sent to the model
                    </label>
                    {masked.map(r => <p key={r.id} data-testid="sent-to-model" className="mt-1.5 rounded-md border bg-card px-2 py-1.5 font-mono text-xs break-words">
                        <span className="text-faint">{r.id} · </span>{ui.showSent ? r.guardrail!.sent_to_model : (r.original?.description ?? r.description)}
                    </p>)}
                </div>
            </div>
        )}
    </>;
}

const cellInput = 'h-8 w-full rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-2 focus-visible:outline-primary';

function AccountCell({ value, editing, label, onChange }: { value: string; editing: boolean; label: string; onChange: (v: string) => void }) {
    const name = accountName(value);
    if (!editing) return <><span className="mr-2 font-mono font-semibold">{value}</span>{name}</>;
    return (
        <span className="flex items-center gap-2">
            <input className={cn(cellInput, 'w-24 font-mono')} aria-label={`${label} account`} value={value} onChange={e => onChange(e.target.value)} />
            <span className="truncate text-muted-foreground">{name ?? 'Not in the chart of accounts'}</span>
        </span>
    );
}

function JournalEntry({ item, ui, setUi }: { item: Item; ui: ItemUi; setUi: (p: Partial<ItemUi>) => void }) {
    const original = toDraft(item);
    if (!original) {
        return <p className="rounded-lg border px-3 py-2.5 text-sm text-muted-foreground">No journal entry needed. Approving confirms the agents' decision.</p>;
    }
    const editing = ui.editing && ui.draft !== null;
    const shown = editing ? ui.draft! : original;
    const error = editing ? validateEntry(shown) : null;
    const patch = (p: Partial<EntryDraft>) => ui.draft && setUi({ draft: { ...ui.draft, ...p } });
    const amount = <Money value={shown.amount} />;
    return (
        <div className="space-y-2">
            <div className="overflow-hidden rounded-lg border">
                <div className="overflow-x-auto">
                    <table className="w-full min-w-[440px] border-collapse text-sm" aria-label="Draft journal entry">
                        <thead className="bg-muted text-left">
                            <tr className="eyebrow"><th className="px-3 py-2 font-semibold">Account</th><th className="w-36 px-3 py-2 text-right font-semibold">Debit</th><th className="w-36 px-3 py-2 text-right font-semibold">Credit</th></tr>
                        </thead>
                        <tbody>
                            <tr className="border-t">
                                <td className="px-3 py-2.5"><AccountCell value={shown.debit_account} editing={editing} label="Debit" onChange={v => patch({ debit_account: v })} /></td>
                                <td className="px-3 py-2.5 text-right">{editing ? <input className={cn(cellInput, 'text-right tabular-nums')} aria-label="Amount" inputMode="decimal" value={shown.amount} onChange={e => patch({ amount: e.target.value })} /> : amount}</td>
                                <td className="px-3 py-2.5 text-right text-faint">—</td>
                            </tr>
                            <tr className="border-t">
                                <td className="py-2.5 pr-3 pl-7"><AccountCell value={shown.credit_account} editing={editing} label="Credit" onChange={v => patch({ credit_account: v })} /></td>
                                <td className="px-3 py-2.5 text-right text-faint">—</td>
                                <td className="px-3 py-2.5 text-right">{amount}</td>
                            </tr>
                        </tbody>
                        <tfoot className="bg-muted text-[13px] font-semibold">
                            <tr className="border-t">
                                <td className="px-3 py-2">{!error && <span className="inline-flex items-center gap-1 rounded-full bg-good-soft px-1.5 text-[11px] leading-[18px] text-good"><Check className="size-3" aria-hidden="true" />Balanced</span>}</td>
                                <td className="px-3 py-2 text-right">{amount}</td>
                                <td className="px-3 py-2 text-right">{amount}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
                <div className="flex items-center gap-2 border-t px-3 py-2.5 text-[13px] text-muted-foreground">
                    <span className="eyebrow">Memo</span>
                    {editing ? <input className={cellInput} aria-label="Memo" value={shown.memo} onChange={e => patch({ memo: e.target.value })} /> : <span>{shown.memo}</span>}
                </div>
            </div>
            {error && <p role="alert" className="text-[12.5px] text-destructive">{error}</p>}
        </div>
    );
}

// The remember switch. Disabled with a reason when the backend says this item can't teach a rule; when on, it previews what will be saved.
function RememberRule({ item, ui, setUi }: { item: Item; ui: ItemUi; setUi: (p: Partial<ItemUi>) => void }) {
    const reason = learnableReason(item);
    const on = ui.remember && reason === null;
    const editing = ui.editing && ui.draft !== null;
    const preview = on ? rulePreview(item, editing ? ui.draft : toDraft(item)) : null;
    const id = `remember-${item.id}`;
    return (
        <div data-testid="remember-rule" data-learnable={reason === null}
            className={cn('rounded-lg border p-3 transition-colors', on && 'border-violet/40 bg-violet-soft/60', reason !== null && 'bg-muted/50')}>
            <div className="flex items-start gap-3">
                <Switch id={id} checked={on} disabled={reason !== null} onCheckedChange={checked => setUi({ remember: checked })}
                    aria-describedby={`${id}-hint`} className="mt-0.5 data-checked:bg-violet" />
                <div className="min-w-0 flex-1">
                    <label htmlFor={id} className={cn('flex items-center gap-2 text-[13.5px] font-semibold', reason === null ? 'cursor-pointer' : 'text-muted-foreground')}>
                        Remember this as a rule
                        {reason === null && <span className={cn('rounded-full px-1.5 text-[10.5px] leading-[17px] font-semibold uppercase', on ? 'bg-violet text-card' : 'bg-muted text-muted-foreground')}>{on ? 'On' : 'Off'}</span>}
                        {reason !== null && <Lock className="size-3.5" aria-hidden="true" />}
                    </label>
                    <p id={`${id}-hint`} data-testid="remember-hint" className="text-[12.5px] text-muted-foreground">
                        {reason ?? (on ? 'When you approve, Bridge saves this rule. Next run, matching items close automatically and name it.' : 'Switch on to close items like this automatically next time.')}
                    </p>
                    {preview && (
                        <dl data-testid="rule-preview" className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 rounded-md border border-violet/30 bg-card px-3 py-2 text-[12.5px]">
                            <dt className="text-faint">Kind</dt><dd className="font-semibold">{kindTitle(preview.kind)}</dd>
                            <dt className="text-faint">Direction</dt><dd>Money {preview.direction} of the bank</dd>
                            <dt className="text-faint">Entry</dt>
                            <dd className="flex flex-wrap items-center gap-x-2">
                                <span><span className="text-faint">DR</span> <span className="font-mono font-semibold">{preview.debit}</span></span>
                                <span><span className="text-faint">CR</span> <span className="font-mono font-semibold">{preview.credit}</span></span>
                                <Money value={preview.amount} className="font-semibold" />
                            </dd>
                        </dl>
                    )}
                </div>
            </div>
        </div>
    );
}

interface DetailProps { item: Item; rows: Map<string, TxRow>; ui: ItemUi; setUi: (p: Partial<ItemUi>) => void; onEvidence: (item: Item, ev: EvidenceRef) => void; onDecide: Decide; busy: boolean }

function ItemDetail({ item, rows, ui, setUi, onEvidence, onDecide, busy }: DetailProps) {
    const pending = item.status === 'needs_approval';
    const original = toDraft(item);
    const editing = ui.editing && ui.draft !== null;
    const invalid = editing && validateEntry(ui.draft!) !== null;
    const tier = modelTier(item.model);
    return (
        <article className="flex min-w-0 flex-col" data-testid="approval-detail" data-item-id={item.id} aria-label={kindTitle(item.kind)}>
            <div className="flex flex-1 flex-col gap-5 px-4 py-5 sm:px-6">
                <header className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                        <h3 className="text-lg font-semibold tracking-tight">{kindTitle(item.kind)}</h3>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            <StatusChip status={item.status} />
                            <RuleChip item={item} />
                            <FlagChips item={item} />
                            {item.model && <span className="inline-flex items-center gap-1 rounded-full bg-muted px-1.5 text-[11px] leading-[18px] font-semibold text-muted-foreground">Drafted by <TierTag tier={tier} title={item.model} /></span>}
                            {item.confidence !== null && <span title="Shown for context. Policy and code checks decide what closes automatically." className="rounded-full bg-muted px-1.5 text-[11px] leading-[18px] font-semibold text-muted-foreground">Confidence {Math.round(item.confidence * 100)}%</span>}
                        </div>
                    </div>
                    <div className="sm:text-right">
                        <Money value={item.amount_delta} className={cn('block text-2xl leading-tight font-semibold', !isNegative(item.amount_delta) && 'text-foreground')} />
                        <span className="text-xs text-muted-foreground">Effect on the difference</span>
                    </div>
                </header>

                {/* Model output: rendered as text only. */}
                <p className="max-w-[68ch] text-[14.5px] leading-relaxed">{item.reasoning}</p>

                <Guardrails item={item} rows={rows} ui={ui} setUi={setUi} />

                {item.evidence.length > 0 && (
                    <section className="space-y-2">
                        <h4 className="eyebrow">Evidence · click to find the rows</h4>
                        <ul className="flex flex-wrap gap-1.5" aria-label="Evidence">
                            {item.evidence.map(ev => {
                                const clickable = ev.type === 'bank_transaction' || ev.type === 'gl_entry';
                                return (
                                    <li key={`${ev.type}:${ev.id}`}>
                                        {clickable
                                            ? <button type="button" onClick={() => onEvidence(item, ev)} title={ev.note ?? undefined} className="inline-flex h-[26px] items-center gap-1.5 rounded-md border bg-card px-2 font-mono text-xs hover:border-primary hover:text-primary"><ArrowUpRight className="size-3" aria-hidden="true" />{ev.id}</button>
                                            : <span title={ev.note ?? undefined} className="inline-flex h-[26px] items-center rounded-md border border-dashed px-2 text-xs text-muted-foreground">{ev.type === 'policy' ? `policy: ${ev.id}` : `${ev.type}: ${ev.id}`}</span>}
                                    </li>
                                );
                            })}
                        </ul>
                    </section>
                )}

                <section className="space-y-2">
                    <h4 className="eyebrow">{original ? 'Draft journal entry' : 'Proposed action'}</h4>
                    <JournalEntry item={item} ui={ui} setUi={setUi} />
                </section>

                {pending && <RememberRule item={item} ui={ui} setUi={setUi} />}
            </div>
            {pending && (
                <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t bg-card px-4 py-3 sm:px-6">
                    <span className="mr-auto hidden text-xs text-faint sm:inline"><Kbd>J</Kbd> <Kbd>K</Kbd> to move</span>
                    {original && <Button variant="outline" disabled={busy} onClick={() => setUi({ editing: !ui.editing, draft: original })}>{ui.editing ? 'Cancel edit' : 'Edit entry'} <Kbd>E</Kbd></Button>}
                    <Button variant="outline" disabled={busy} onClick={() => onDecide(item, 'reject')} className="hover:border-destructive hover:bg-destructive-soft hover:text-destructive"><X aria-hidden="true" />Reject <Kbd>R</Kbd></Button>
                    <Button size="lg" disabled={busy || invalid} onClick={() => onDecide(item, 'approve')} className="bg-good px-4 text-card hover:bg-good/90">
                        <Check aria-hidden="true" />{editing ? 'Approve with edits' : original ? 'Approve & post' : 'Approve'} <Kbd>A</Kbd>
                    </Button>
                </div>
            )}
        </article>
    );
}

const TABS: { id: InboxTab; label: string }[] = [
    { id: 'pending', label: 'Needs you' }, { id: 'policy', label: 'Closed by policy' }, { id: 'decided', label: 'Decided' },
];

interface InboxProps {
    items: Item[]; // every item of the run except plain matches
    rows: Map<string, TxRow>; // bank and GL rows by id, for guardrail text
    onSelect: (item: Item) => void;
    onEvidence: (item: Item, evidence: EvidenceRef) => void;
    footer?: ReactNode; // shown in the empty state, e.g. a report link
}

export function ApprovalInbox({ items, rows, onSelect, onEvidence, footer }: InboxProps) {
    // The mutation lives here, not in the detail: an optimistic update removes the item before the toast would fire.
    const decide = useDecideItem();
    const [tab, setTab] = useState<InboxTab>('pending');
    // The chosen id and its position: when a decision removes it, the item now at that position is selected.
    const [chosen, setChosen] = useState<{ id: string | null; index: number }>({ id: null, index: 0 });
    const [uiById, setUiById] = useState<Record<string, ItemUi>>({});

    const list = inTab(items, tab);
    const ids = list.map(i => i.id);
    const selectedId = nextSelection(ids, chosen.id, chosen.index);
    const selected = list.find(i => i.id === selectedId) ?? null;

    const select = (id: string | null) => {
        setChosen({ id, index: id ? Math.max(0, ids.indexOf(id)) : 0 });
        const item = id ? items.find(i => i.id === id) : undefined;
        if (item) onSelect(item);
    };
    const uiFor = (item: Item) => uiById[item.id] ?? freshUi(item);
    const setUi = (item: Item) => (patch: Partial<ItemUi>) => setUiById(all => ({ ...all, [item.id]: { ...(all[item.id] ?? freshUi(item)), ...patch } }));

    const onDecide: Decide = (item, decision) => {
        const ui = uiFor(item);
        const original = toDraft(item);
        const override = decision === 'approve' && ui.editing && original && ui.draft ? buildOverride(original, ui.draft) : undefined;
        if (decision === 'approve' && ui.editing && ui.draft && validateEntry(ui.draft)) return;
        const title = kindTitle(item.kind);
        const remember = ui.remember && item.learnable && decision === 'approve';
        decide.mutateAsync({ itemId: item.id, decision, remember, note: null, ...(override ? { entry_override: override } : {}) }).then(
            response => {
                // The rule claim comes from the response only; nothing is promised when rule_id is null.
                const ruleId = response.rule_id ?? null;
                toast.success(decisionToastText(title, decision, ruleId), {
                    description: notLearnedNote(remember, decision, ruleId) ?? undefined,
                    action: ruleId !== null ? { label: 'View rule', onClick: () => rulesPanel.open(ruleId) } : undefined,
                });
            },
            (e: Error) => { toast.error(`Could not ${decision} ${title.toLowerCase()}; restored. ${e.message}`); },
        );
    };

    // Keyboard: J/K move, A approve, R reject, E edit. Ignored while typing or when a dialog is open.
    const latest = { ids, selected, tab, busy: decide.isPending, select, onDecide, uiFor, setUi };
    const keys = useRef(latest);
    useEffect(() => { keys.current = latest; });
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target as HTMLElement) || document.querySelector('[role="dialog"]')) return;
            const k = keys.current;
            const key = e.key.toLowerCase();
            if (key === 'j' || key === 'k') { e.preventDefault(); k.select(stepSelection(k.ids, k.selected?.id ?? null, key === 'j' ? 1 : -1)); return; }
            if (!k.selected || k.tab !== 'pending' || k.busy) return;
            const ui = k.uiFor(k.selected);
            if (key === 'a' && !(ui.editing && ui.draft && validateEntry(ui.draft))) k.onDecide(k.selected, 'approve');
            else if (key === 'r') k.onDecide(k.selected, 'reject');
            else if (key === 'e' && k.selected.proposed_entry) k.setUi(k.selected)({ editing: !ui.editing, draft: toDraft(k.selected) });
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const pendingCount = inTab(items, 'pending').length;

    return (
        <section aria-label="Approvals" data-testid="approval-inbox" className="min-w-0 rounded-lg border bg-card shadow-card">
            <div className="flex flex-wrap items-center gap-2.5 border-b px-4 py-3">
                <h2 className="text-sm font-semibold">Approvals</h2>
                <div role="tablist" aria-label="Item groups" className="flex gap-0.5 rounded-[7px] bg-muted p-[3px]">
                    {TABS.map(t => (
                        <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => { setTab(t.id); setChosen({ id: null, index: 0 }); }}
                            className={cn('inline-flex items-center gap-1.5 rounded-[5px] px-2.5 py-1 text-[12.5px] font-semibold', tab === t.id ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
                            {t.label}<span className="font-mono text-[11px] text-faint">{inTab(items, t.id).length}</span>
                        </button>
                    ))}
                </div>
                <span className="flex-1" />
                <span className="hidden text-xs text-muted-foreground lg:inline">Policy and code checks decide what closes automatically. Confidence is shown for context only.</span>
            </div>
            <div className="grid min-h-[480px] md:grid-cols-[minmax(280px,360px)_1fr]">
                <div className="max-h-[280px] overflow-y-auto border-b md:max-h-[640px] md:border-r md:border-b-0">
                    {list.length === 0
                        ? <p className="p-6 text-center text-sm text-muted-foreground">{tab === 'pending' ? 'Nothing is waiting for you.' : tab === 'decided' ? 'Approved and rejected items show here.' : 'Nothing was closed by policy.'}</p>
                        : <ul role="listbox" aria-label={TABS.find(t => t.id === tab)!.label} className="flex flex-col gap-0.5 p-1.5">
                            {list.map(item => <QueueRow key={item.id} item={item} selected={item.id === selectedId} onSelect={() => select(item.id)} />)}
                        </ul>}
                </div>
                {selected
                    ? <ItemDetail key={selected.id} item={selected} rows={rows} ui={uiFor(selected)} setUi={setUi(selected)} onEvidence={onEvidence} onDecide={onDecide} busy={decide.isPending} />
                    : (
                        <div className="grid place-items-center px-6 py-12 text-center text-muted-foreground">
                            {tab === 'pending' && pendingCount === 0
                                ? <div className="flex flex-col items-center gap-2">
                                    <span className="grid size-11 place-items-center rounded-full bg-good-soft text-good"><Check className="size-5" aria-hidden="true" /></span>
                                    <h3 className="text-base font-semibold text-foreground">All caught up</h3>
                                    <p>Every item the agents could not close has a decision.</p>
                                    {footer}
                                </div>
                                : <p>Select an item to see its details.</p>}
                        </div>
                    )}
            </div>
        </section>
    );
}
