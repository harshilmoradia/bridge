import type { ReconStatus } from '../api/types';
import { STATUS_LABEL } from '../lib/statusLabel';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';

const TONE: Record<ReconStatus, string> = {
    matched: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
    auto_resolved: 'bg-teal-500/15 text-teal-700 dark:text-teal-400',
    reconciling_item: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
    needs_approval: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
    approved: 'bg-green-600/15 text-green-700 dark:text-green-400',
    rejected: 'bg-red-500/15 text-red-700 dark:text-red-400',
    unmatched: 'border-border bg-transparent text-muted-foreground',
};

export function StatusChip({ status, className }: { status: ReconStatus; className?: string }) {
    return <Badge variant="ghost" data-status={status} className={cn(TONE[status], className)}>{STATUS_LABEL[status]}</Badge>;
}
