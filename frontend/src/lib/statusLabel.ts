import type { ReconStatus } from '../api/types.ts';

export const STATUS_LABEL: Record<ReconStatus, string> = {
    matched: 'Matched',
    auto_resolved: 'Auto-resolved',
    reconciling_item: 'Reconciling item',
    needs_approval: 'Needs approval',
    approved: 'Approved',
    rejected: 'Rejected',
    unmatched: 'Unmatched',
};
