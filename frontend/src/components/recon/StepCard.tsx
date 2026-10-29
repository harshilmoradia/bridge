import { Circle, CircleCheck, CircleX, LoaderCircle } from 'lucide-react';
import type { ModelTier, RunStep, StepStatus } from '../../api/types';
import { Badge } from '../ui/badge';
import { cn } from '../../lib/utils';
import { formatLatency, formatTokens, STEP_STATUS_LABEL, stepDetail } from '../../lib/stepper';

const TIER_CLASS: Record<ModelTier, string> = {
    code: 'bg-muted text-muted-foreground',
    nano: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
    super: 'bg-violet-500/15 text-violet-700 dark:text-violet-300',
    ultra: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
};

function StatusIcon({ status }: { status: StepStatus }) {
    const label = STEP_STATUS_LABEL[status];
    if (status === 'running') return <LoaderCircle aria-label={label} role="img" className="size-4 shrink-0 text-primary motion-safe:animate-spin" />;
    if (status === 'completed') return <CircleCheck aria-label={label} role="img" className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />;
    if (status === 'failed') return <CircleX aria-label={label} role="img" className="size-4 shrink-0 text-destructive" />;
    return <Circle aria-label={label} role="img" className="size-4 shrink-0 text-muted-foreground" />;
}

export function StepCard({ step, showModel = false }: { step: RunStep; showModel?: boolean }) {
    const tokens = formatTokens(step);
    const detail = stepDetail(step);
    return (
        <li data-testid="run-step" data-step-id={step.id} data-step-status={step.status}
            className={cn('min-w-0 space-y-1 rounded-md border px-3 py-2 text-sm', step.status === 'running' && 'border-primary/60', step.status === 'failed' && 'border-destructive/60', step.status === 'pending' && 'opacity-60')}>
            <div className="flex items-center gap-2">
                <StatusIcon status={step.status} />
                <span className="min-w-0 flex-1 truncate font-medium" title={step.label}>{step.label}</span>
                <Badge variant="outline" className={cn('border-transparent uppercase', TIER_CLASS[step.tier])} title={step.model ?? 'No model: runs as code'}>{step.tier}</Badge>
            </div>
            <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                <span>{formatLatency(step)}</span>
                {tokens && <span>{tokens}</span>}
                {showModel && <span className="font-mono" data-testid="step-model">{step.model ?? 'no model (code)'}</span>}
            </div>
            {detail && <p className={cn('text-xs', step.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>{detail}</p>}
        </li>
    );
}

