import { useEffect, useState, useSyncExternalStore } from 'react';
import { BookMarked, Lock, Sparkles, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useForgetAllRules, useForgetRule, useRules } from '../api/hooks';
import type { Rule } from '../api/types';
import { accountName, kindTitle } from '../lib/inbox';
import { isSeeded, learnedOnly, patternText } from '../lib/rules';
import { rulesPanel } from '../lib/rulesPanel';
import { cn } from '../lib/utils';
import { Money } from './Money';
import { QueryState } from './QueryState';
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from './ui/alert-dialog';
import { Button } from './ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from './ui/sheet';

const useRulesPanel = () => useSyncExternalStore(rulesPanel.subscribe, rulesPanel.get);

const str = (v: unknown): string | null => (typeof v === 'string' || typeof v === 'number' ? String(v) : null);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

function Account({ side, code }: { side: 'DR' | 'CR'; code: string | null }) {
    if (!code) return null;
    const name = accountName(code);
    return <span><span className="text-faint">{side}</span> <span className="font-mono font-semibold">{code}</span>{name && <span className="text-muted-foreground"> {name}</span>}</span>;
}

function RuleRow({ rule, focused }: { rule: Rule; focused: boolean }) {
    const forget = useForgetRule();
    const [confirming, setConfirming] = useState(false);
    const seeded = isSeeded(rule);
    const debit = str(rule.action.debit ?? rule.action.debit_account);
    const credit = str(rule.action.credit ?? rule.action.credit_account);
    const amount = str(rule.action.amount);
    const direction = str(rule.pattern.direction);
    const onForget = () => {
        setConfirming(false);
        forget.mutate(rule.id, {
            onSuccess: () => toast.success(`Rule #${rule.id} forgotten. Future runs won't use it.`),
            onError: e => toast.error(`Could not forget rule #${rule.id}; it is back in the list. ${e.message}`),
        });
    };
    return (
        <li data-testid="rule-row" data-rule-id={rule.id} data-origin={seeded ? 'seeded' : 'learned'}
            className={cn('space-y-1.5 rounded-lg border bg-card px-3 py-2.5 transition-shadow', focused && 'border-violet ring-2 ring-violet/30')}>
            <div className="flex items-start gap-2">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                    <span className="font-mono text-[12px] font-semibold text-violet">#{rule.id}</span>
                    <span className="text-[13.5px] font-semibold">{kindTitle(rule.kind)}</span>
                    {seeded
                        ? <span data-testid="seeded-badge" title="Part of the demo data. It can't be forgotten." className="inline-flex items-center gap-1 rounded-full bg-muted px-1.5 text-[11px] leading-[18px] font-semibold text-muted-foreground"><Lock className="size-3" aria-hidden="true" />seeded</span>
                        : <span className="inline-flex items-center gap-1 rounded-full bg-violet-soft px-1.5 text-[11px] leading-[18px] font-semibold text-violet"><Sparkles className="size-3" aria-hidden="true" />learned</span>}
                    {!rule.active && <span className="text-[11px] text-muted-foreground">(inactive)</span>}
                </div>
                {!seeded && (confirming
                    ? <span className="inline-flex shrink-0 items-center gap-1 text-[12.5px]" role="group" aria-label={`Confirm forgetting rule #${rule.id}`}>
                        Forget?
                        <Button size="xs" variant="destructive" onClick={onForget} autoFocus>Yes</Button>
                        <Button size="xs" variant="outline" onClick={() => setConfirming(false)}>No</Button>
                    </span>
                    : <Button size="xs" variant="ghost" className="shrink-0 text-muted-foreground hover:text-destructive" disabled={forget.isPending} onClick={() => setConfirming(true)} aria-label={`Forget rule #${rule.id}`}>
                        <Trash2 aria-hidden="true" />Forget
                    </Button>)}
            </div>
            {/* Pattern text came from bank or ledger rows: rendered as text only. */}
            <p className="font-mono text-[12px] break-words text-muted-foreground">
                {patternText(rule.pattern)}{direction && <span className="text-faint"> · money {direction}</span>}
            </p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12.5px]">
                <Account side="DR" code={debit} />
                <Account side="CR" code={credit} />
                {amount && <Money value={amount} className="ml-auto font-semibold" />}
            </div>
            <p className="text-[11.5px] text-faint">
                {seeded ? 'Seeded with the demo' : `Learned from your approval · ${rule.created_by.replace(/^user:/, '')}`} · <time dateTime={rule.created_at}>{new Date(rule.created_at).toLocaleString()}</time>
            </p>
        </li>
    );
}

function ForgetAll({ count }: { count: number }) {
    const forgetAll = useForgetAllRules();
    if (count === 0) return null;
    const confirm = () => forgetAll.mutate(undefined, {
        onSuccess: r => toast.success(`Forgot ${plural(r.rules_deleted, 'learned rule')}. The next run starts from policy alone.`),
        onError: e => toast.error(`Could not forget the rules; they are back in the list. ${e.message}`),
    });
    return (
        <AlertDialog>
            <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" disabled={forgetAll.isPending} className="hover:border-destructive hover:text-destructive" data-testid="forget-all">
                    <Trash2 aria-hidden="true" />Forget all
                </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Forget {plural(count, 'learned rule')}?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Future runs will send these items back to you for approval. Items already closed keep their history, and seeded rules stay.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel>Keep them</AlertDialogCancel>
                    <AlertDialogAction variant="destructive" onClick={confirm}>Forget all</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

/** The rules list with Forget controls; used on the run trace page and in the sheet. */
export function RulesList({ rules, focusId = null }: { rules: Rule[]; focusId?: number | null }) {
    const learned = learnedOnly(rules).length;
    useEffect(() => {
        if (focusId === null) return;
        const frame = requestAnimationFrame(() => document.querySelector(`[data-rule-id="${focusId}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
        return () => cancelAnimationFrame(frame);
    }, [focusId]);
    const sorted = [...rules].sort((a, b) => Number(isSeeded(a)) - Number(isSeeded(b)) || b.id - a.id);
    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
                <p className="text-[12.5px] text-muted-foreground">{plural(learned, 'learned rule')}{rules.length > learned && `, ${rules.length - learned} seeded`}</p>
                <span className="flex-1" />
                <ForgetAll count={learned} />
            </div>
            {learned === 0 && (
                <div data-testid="rules-empty" className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-6 text-center">
                    <span className="grid size-9 place-items-center rounded-full bg-violet-soft text-violet"><BookMarked className="size-4" aria-hidden="true" /></span>
                    <p className="text-sm font-semibold">No learned rules yet</p>
                    <p className="max-w-[40ch] text-[12.5px] text-muted-foreground">Approve an item with "Remember this as a rule" switched on. The next run closes items like it automatically and names the rule.</p>
                </div>
            )}
            {sorted.length > 0 && <ul className="space-y-2" data-testid="rules-list">{sorted.map(r => <RuleRow key={r.id} rule={r} focused={r.id === focusId} />)}</ul>}
        </div>
    );
}

export function LearnedRulesPanel({ focusId }: { focusId?: number | null }) {
    const rules = useRules();
    return <QueryState query={rules}>{list => <RulesList rules={list} focusId={focusId} />}</QueryState>;
}

/** Mounted once in the layout; any toast action, chip or button opens it through `rulesPanel`. */
export function LearnedRulesSheet() {
    const { open, focusId } = useRulesPanel();
    return (
        <Sheet open={open} onOpenChange={o => (o ? rulesPanel.open(focusId) : rulesPanel.close())}>
            <SheetContent className="w-full gap-0 sm:max-w-md" data-testid="rules-sheet">
                <SheetHeader className="border-b">
                    <SheetTitle>Learned rules</SheetTitle>
                    <SheetDescription>Patterns you approved with "remember". Runs use them to close matching items, and they survive a demo reset.</SheetDescription>
                </SheetHeader>
                <div className="flex-1 overflow-y-auto p-4"><LearnedRulesPanel focusId={focusId} /></div>
            </SheetContent>
        </Sheet>
    );
}

export function LearnedRulesButton() {
    const rules = useRules();
    const count = rules.data ? learnedOnly(rules.data).length : null;
    return (
        <Button variant="outline" onClick={() => rulesPanel.open()} data-testid="rules-button">
            <BookMarked aria-hidden="true" />Learned rules{count !== null && <span className="font-mono text-[11px] text-faint">{count}</span>}
        </Button>
    );
}
