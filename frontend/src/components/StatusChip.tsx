import type { ReconStatus } from '../api/types';
import { STATUS_LABEL } from '../lib/statusLabel';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';

const TONE: Record<ReconStatus, string> = {
    matched: 'bg-good-soft text-good',
    auto_resolved: 'bg-good-soft text-good',
    reconciling_item: 'bg-muted text-muted-foreground',
    needs_approval: 'bg-warn-soft text-warn',
    approved: 'bg-good-soft text-good',
    rejected: 'bg-destructive-soft text-destructive',
    unmatched: 'border-border bg-transparent text-muted-foreground',
};

export function StatusChip({ status, className }: { status: ReconStatus; className?: string }) {
    return <Badge variant="ghost" data-status={status} className={cn('font-semibold', TONE[status], className)}>{STATUS_LABEL[status]}</Badge>;
}
