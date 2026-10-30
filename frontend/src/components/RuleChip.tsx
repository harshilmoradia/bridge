import type { Item } from '../api/types';
import { appliedRuleLabel, RULE_TOOLTIP } from '../lib/rules';
import { rulesPanel } from '../lib/rulesPanel';
import { Badge } from './ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip';

const CHIP = 'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300';

/** "Applied rule #N" chip for items a learned rule resolved; renders nothing otherwise. Interactive chips open that rule in the learned rules panel. */
export function RuleChip({ item, interactive = true }: { item: Pick<Item, 'flags' | 'rule_id'>; interactive?: boolean }) {
    const label = appliedRuleLabel(item);
    if (!label) return null;
    // Inside a button the chip is plain text: no extra tab stop and no tooltip trigger.
    if (!interactive) return <Badge variant="outline" data-testid="rule-chip" className={CHIP}>{label}</Badge>;
    const tip = item.rule_id !== null ? `${RULE_TOOLTIP}. Click to see the rule.` : RULE_TOOLTIP;
    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <Badge asChild variant="outline" className={`${CHIP} cursor-pointer hover:bg-violet-500/20 focus-visible:ring-2 focus-visible:ring-violet/40`}>
                        <button type="button" data-testid="rule-chip" aria-label={`${label}. ${tip}`} onClick={() => rulesPanel.open(item.rule_id)}>{label}</button>
                    </Badge>
                </TooltipTrigger>
                <TooltipContent>{tip}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
