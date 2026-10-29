import { useState } from 'react';
import { toast } from 'sonner';
import { useDecideItem } from '../../api/hooks';
import type { EvidenceRef, Item } from '../../api/types';
import { buildOverride, validateEntry, type EntryDraft } from '../../lib/entry';
import { Money } from '../Money';
import { Button } from '../ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '../ui/sheet';

const input = 'h-8 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

type Decide = (item: Item, decision: 'approve' | 'reject', remember: boolean, override: ReturnType<typeof buildOverride>) => void;
// Per-card edit state lives in the drawer (keyed by item id) so a card restored after a failed decision keeps it.
interface CardUi { editing: boolean; draft: EntryDraft | null; remember: boolean }
interface CardProps { item: Item; ui: CardUi | undefined; setUi: (patch: Partial<CardUi>) => void; onEvidence: (item: Item, evidence: EvidenceRef) => void; onDecide: Decide; busy: boolean }

const freshUi = (item: Item): CardUi => ({
    editing: false, remember: false,
    draft: item.proposed_entry && { debit_account: item.proposed_entry.debit_account, credit_account: item.proposed_entry.credit_account, amount: item.proposed_entry.amount, memo: item.proposed_entry.memo },
});

function ApprovalCard({ item, ui, setUi, onEvidence, onDecide, busy }: CardProps) {
    const entry = item.proposed_entry;
    const original: EntryDraft | null = entry && { debit_account: entry.debit_account, credit_account: entry.credit_account, amount: entry.amount, memo: entry.memo };
    const { editing, draft, remember } = ui ?? { editing: false, draft: original, remember: false };
    const setRemember = (r: boolean) => setUi({ remember: r });
    const error = editing && draft ? validateEntry(draft) : null;
    const shown = editing && draft ? draft : original;

    const submit = (decision: 'approve' | 'reject') =>
        onDecide(item, decision, remember, decision === 'approve' && editing && original && draft ? buildOverride(original, draft) : undefined);
    const patch = (p: Partial<EntryDraft>) => draft && setUi({ draft: { ...draft, ...p } });

    return (
        <article className="space-y-3 rounded-lg border p-3" data-item-id={item.id} aria-label={item.kind.replaceAll('_', ' ')}>
            <header className="flex items-baseline justify-between gap-2">
                <h3 className="font-medium">{item.kind.replaceAll('_', ' ')}</h3>
                <Money value={item.amount_delta} className="font-medium" />
            </header>
            <p className="text-sm text-muted-foreground">{item.reasoning}</p>

            {item.evidence.length > 0 && (
                <ul className="flex flex-wrap gap-1" aria-label="Evidence">
                    {item.evidence.map(ev => {
                        const clickable = ev.type === 'bank_transaction' || ev.type === 'gl_entry';
                        return (
                            <li key={`${ev.type}:${ev.id}`}>
                                {clickable
                                    ? <button type="button" onClick={() => onEvidence(item, ev)} title={ev.note ?? undefined} className="rounded-md border px-2 py-0.5 text-xs underline-offset-2 hover:bg-muted hover:underline">{ev.id}</button>
                                    : <span title={ev.note ?? undefined} className="rounded-md border border-dashed px-2 py-0.5 text-xs text-muted-foreground">{ev.type === 'policy' ? `policy: ${ev.id}` : ev.id}</span>}
                            </li>
                        );
                    })}
                </ul>
            )}

            {shown ? (
                <div className="space-y-2">
                    <table className="w-full text-sm" aria-label="Draft journal entry">
                        <thead><tr className="text-left text-xs text-muted-foreground"><th className="w-12 font-medium">DR/CR</th><th className="font-medium">Account</th><th className="text-right font-medium">Amount</th></tr></thead>
                        <tbody>
                            <tr><td>DR</td><td>{editing && draft ? <input className={input} aria-label="Debit account" value={draft.debit_account} onChange={e => patch({ debit_account: e.target.value })} /> : shown.debit_account}</td>
                                <td className="text-right" rowSpan={2}>{editing && draft ? <input className={`${input} text-right`} aria-label="Amount" inputMode="decimal" value={draft.amount} onChange={e => patch({ amount: e.target.value })} /> : <Money value={shown.amount} />}</td></tr>
                            <tr><td>CR</td><td>{editing && draft ? <input className={input} aria-label="Credit account" value={draft.credit_account} onChange={e => patch({ credit_account: e.target.value })} /> : shown.credit_account}</td></tr>
                        </tbody>
                    </table>
                    {editing && draft
                        ? <input className={input} aria-label="Memo" value={draft.memo} onChange={e => patch({ memo: e.target.value })} />
                        : <p className="text-xs text-muted-foreground">{shown.memo}</p>}
                    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
                </div>
            ) : <p className="text-xs text-muted-foreground">No draft entry for this item.</p>}

            <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} /> Remember this rule
            </label>
            <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy || Boolean(error)} onClick={() => submit('approve')}>{editing ? 'Approve with edits' : 'Approve'}</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => submit('reject')}>Reject</Button>
                {original && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => setUi({ editing: !editing, draft: original })}>{editing ? 'Cancel edit' : 'Edit'}</Button>
                )}
            </div>
        </article>
    );
}

interface DrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    items: Item[]; // needs_approval items
    onEvidence: (item: Item, evidence: EvidenceRef) => void;
}

export function ApprovalDrawer({ open, onOpenChange, items, onEvidence }: DrawerProps) {
    // The mutation lives here, not in the cards: an optimistic update removes the card before the toast would fire.
    const decide = useDecideItem();
    const [uiById, setUiById] = useState<Record<string, CardUi>>({});
    const onDecide: Decide = (item, decision, remember, override) =>
        decide.mutateAsync({ itemId: item.id, decision, remember, note: null, ...(override ? { entry_override: override } : {}) }).then(
            () => { toast.success(`${item.kind.replaceAll('_', ' ')} ${decision === 'approve' ? 'approved' : 'rejected'}`); },
            (e: Error) => { toast.error(`Could not ${decision} ${item.kind.replaceAll('_', ' ')}; restored. ${e.message}`); },
        );
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-full overflow-y-auto sm:max-w-lg" data-testid="approval-drawer">
                <SheetHeader>
                    <SheetTitle>Needs approval ({items.length})</SheetTitle>
                    <SheetDescription>Review each draft entry. Approving posts it to the statement.</SheetDescription>
                </SheetHeader>
                <div className="space-y-3 px-4 pb-4">
                    {items.length === 0
                        ? <p className="text-sm text-muted-foreground">Nothing is waiting for approval.</p>
                        : items.map(item => <ApprovalCard key={item.id} item={item} ui={uiById[item.id]}
                            setUi={patch => setUiById(all => ({ ...all, [item.id]: { ...(all[item.id] ?? freshUi(item)), ...patch } }))}
                            onEvidence={onEvidence} onDecide={onDecide} busy={decide.isPending} />)}
                </div>
            </SheetContent>
        </Sheet>
    );
}
