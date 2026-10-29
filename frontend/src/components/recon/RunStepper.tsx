import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { Run } from '../../api/types';
import { StepCard } from './StepCard';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';
import { COLUMNS, groupSteps, stepsDone } from '../../lib/stepper';

export function RunStepper({ run }: { run: Run }) {
    const [choice, setChoice] = useState<boolean | null>(null);
    const open = choice ?? true;
    const groups = groupSteps(run.steps);
    return (
        <section aria-label="Run progress" className="space-y-2" data-testid="run-stepper">
            <div className="flex items-center gap-2">
                <h2 className="text-sm font-medium">Agent steps <span className="font-normal text-muted-foreground">({stepsDone(run.steps)} of {run.steps.length} done)</span></h2>
                <Button variant="ghost" size="sm" className="ml-auto" aria-expanded={open} aria-controls="run-stepper-steps" onClick={() => setChoice(!open)}>
                    {open ? 'Hide' : 'Show'} steps
                    <ChevronDown className={cn('size-4 transition-transform motion-reduce:transition-none', open && 'rotate-180')} aria-hidden />
                </Button>
            </div>
            <div id="run-stepper-steps" hidden={!open}>
                {groups.length === 0
                    ? <p className="text-sm text-muted-foreground">Waiting for the first step...</p>
                    : (
                        <ol className="space-y-2">
                            {groups.map(group => (
                                <li key={group.position} data-testid="run-step-group" data-parallel={group.steps.length > 1}>
                                    <ul className={cn('grid gap-2', COLUMNS[Math.min(group.steps.length, 3)])}>
                                        {group.steps.map(step => <StepCard key={step.id} step={step} />)}
                                    </ul>
                                </li>
                            ))}
                        </ol>
                    )}
            </div>
        </section>
    );
}
