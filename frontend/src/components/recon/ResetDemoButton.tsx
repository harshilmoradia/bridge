import { useState } from 'react';
import { toast } from 'sonner';
import { useResetDemo, useRules } from '../../api/hooks';
import { ApiError } from '../../api/http';
import { afterReset, resetErrorText, resetKeepsText, resetSuccessText } from '../../lib/demoReset';
import { learnedOnly } from '../../lib/rules';
import { rulesPanel } from '../../lib/rulesPanel';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';

// Reset needs a confirm step: it deletes every run on the demo dataset. Learned rules are kept (B-14); Forget lives in the rules panel.
export function ResetDemoButton({ disabled, onReset }: { disabled?: boolean; onReset: () => void }) {
    const [open, setOpen] = useState(false);
    const reset = useResetDemo();
    const rules = useRules();
    const learned = rules.data ? learnedOnly(rules.data).length : null;
    const confirm = () => reset.mutate(undefined, {
        onSuccess: response => { setOpen(false); afterReset(onReset, reset.invalidateAll); toast.success(resetSuccessText(response)); },
        onError: error => { setOpen(false); toast.error(resetErrorText({ code: error instanceof ApiError ? error.code : undefined, message: error.message })); },
    });
    return (
        <Dialog open={open} onOpenChange={o => { if (!reset.isPending) setOpen(o); }}>
            <DialogTrigger asChild><Button variant="outline" disabled={disabled || reset.isPending}>Reset demo</Button></DialogTrigger>
            <DialogContent showCloseButton={!reset.isPending}>
                <DialogHeader>
                    <DialogTitle>Reset the demo?</DialogTitle>
                    <DialogDescription>This deletes every run on this dataset, with its items and decisions. Seeded data stays.</DialogDescription>
                </DialogHeader>
                <div data-testid="reset-rules-note" className="rounded-lg bg-violet-soft px-3 py-2.5 text-[13px]">
                    <p className="font-semibold text-violet">{learned === null ? 'Learned rules are kept.' : resetKeepsText(learned)}</p>
                    {learned !== 0 && (
                        <p className="mt-0.5 text-muted-foreground">Want a clean slate?{' '}
                            <button type="button" className="font-medium text-primary underline underline-offset-2" disabled={reset.isPending}
                                onClick={() => { setOpen(false); rulesPanel.open(); }}>Forget all rules</button> first.
                        </p>
                    )}
                </div>
                <DialogFooter>
                    <Button variant="outline" disabled={reset.isPending} onClick={() => setOpen(false)}>Cancel</Button>
                    <Button variant="destructive" disabled={reset.isPending} onClick={confirm}>{reset.isPending ? 'Resetting...' : 'Reset demo'}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
