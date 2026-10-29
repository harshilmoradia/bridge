import { useId, useState } from 'react';
import { EyeOff, ShieldAlert } from 'lucide-react';
import type { Guardrail } from '../../api/types';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../ui/tooltip';

export const INJECTION_TIP = 'Possible prompt injection: treated as data, never followed';

// Shield badge for a row whose text read like an instruction to the model. Focusable, so the tooltip works by keyboard.
export function InjectionBadge() {
    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <button type="button" aria-label={INJECTION_TIP} data-testid="injection-badge"
                        onClick={e => e.stopPropagation()}
                        className="inline-flex items-center gap-1 rounded-4xl border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        <ShieldAlert className="size-3" aria-hidden="true" />Injection
                    </button>
                </TooltipTrigger>
                <TooltipContent>{INJECTION_TIP}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

interface Props {
    guardrail: Guardrail | undefined;
    original?: { description: string; counterparty: string | null };
    defaultExpanded?: boolean;
}

// Injection badge, and for PII rows a "masked" chip plus a "Sent to model" toggle that opens the masked text
// beside the stored original. Text is always rendered as text, never HTML.
export function GuardrailCallouts({ guardrail, original, defaultExpanded = false }: Props) {
    const [open, setOpen] = useState(defaultExpanded);
    const panelId = useId();
    if (!guardrail || (!guardrail.injection_flagged && !guardrail.pii_masked)) return null;
    return (
        <div className="mt-1 space-y-1" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-1.5">
                {guardrail.injection_flagged && <InjectionBadge />}
                {guardrail.pii_masked && (
                    <>
                        <span data-testid="masked-chip" className="inline-flex items-center gap-1 rounded-4xl border px-2 py-0.5 text-xs text-muted-foreground">
                            <EyeOff className="size-3" aria-hidden="true" />masked
                        </span>
                        <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(o => !o)}
                            className="rounded-md px-1 text-xs underline underline-offset-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                            Sent to model
                        </button>
                    </>
                )}
            </div>
            {guardrail.pii_masked && (
                <dl id={panelId} hidden={!open} data-testid="sent-to-model" className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 rounded-md border bg-muted/40 p-2 text-xs">
                    <dt className="text-muted-foreground">Original</dt>
                    <dd className="break-words">{original?.description ?? 'Not available'}</dd>
                    <dt className="text-muted-foreground">Sent to model</dt>
                    <dd className="break-words font-medium">{guardrail.sent_to_model}</dd>
                    {guardrail.sent_counterparty !== null && original?.counterparty != null && guardrail.sent_counterparty !== original.counterparty && (
                        <>
                            <dt className="text-muted-foreground">Counterparty</dt>
                            <dd className="break-words">{original.counterparty} <span aria-hidden="true">→</span> <span className="font-medium">{guardrail.sent_counterparty}</span></dd>
                        </>
                    )}
                </dl>
            )}
        </div>
    );
}
