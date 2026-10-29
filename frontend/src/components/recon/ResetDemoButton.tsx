import { useState } from 'react';
import { toast } from 'sonner';
import { useResetDemo } from '../../api/hooks';
import { ApiError } from '../../api/http';
import { afterReset, resetErrorText, resetSuccessText } from '../../lib/demoReset';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';

// Reset needs a confirm step: it deletes every run and learned rule for the demo dataset.
export function ResetDemoButton({ disabled, onReset }: { disabled?: boolean; onReset: () => void }) {
    const [open, setOpen] = useState(false);
    const reset = useResetDemo();
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
                    <DialogDescription>This deletes every run on this dataset, with its decisions, and the rules learned from them. Seeded data stays.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button variant="outline" disabled={reset.isPending} onClick={() => setOpen(false)}>Cancel</Button>
                    <Button variant="destructive" disabled={reset.isPending} onClick={confirm}>{reset.isPending ? 'Resetting...' : 'Reset demo'}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
