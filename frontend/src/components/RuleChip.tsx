import type { Item } from '../api/types';
import { appliedRuleLabel, RULE_TOOLTIP } from '../lib/rules';
import { Badge } from './ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip';

/** "Applied rule #N" chip for items a learned rule resolved; renders nothing otherwise. */
export function RuleChip({ item, interactive = true }: { item: Pick<Item, 'flags' | 'rule_id'>; interactive?: boolean }) {
    const label = appliedRuleLabel(item);
    if (!label) return null;
    const chip = <Badge variant="outline" tabIndex={interactive ? 0 : undefined} data-testid="rule-chip" aria-label={`${label}. ${RULE_TOOLTIP}`} className="border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300">{label}</Badge>;
    // Inside a button the chip is plain text: no extra tab stop and no tooltip trigger.
    if (!interactive) return chip;
    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    {chip}
                </TooltipTrigger>
                <TooltipContent>{RULE_TOOLTIP}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
