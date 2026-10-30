// Pure text helpers for the demo reset button: what the toasts say.
import type { DemoResetResponse } from '../api/types.ts';

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

export function resetSuccessText(r: Pick<DemoResetResponse, 'runs_deleted' | 'rules_kept'>): string {
    const kept = r.rules_kept === 0 ? 'No learned rules to keep.' : `${plural(r.rules_kept, 'learned rule')} kept for the next run.`;
    return `Demo reset: ${plural(r.runs_deleted, 'run')} deleted. ${kept}`;
}

// What the reset dialog says about rules, before the user confirms.
export function resetKeepsText(learned: number): string {
    if (learned === 0) return 'You have no learned rules yet, so the next run starts from policy alone.';
    return `Your ${plural(learned, 'learned rule')} ${learned === 1 ? 'is' : 'are'} kept. The next run will use ${learned === 1 ? 'it' : 'them'}.`;
}

// Error code -> friendly text. Unknown errors keep their own message.
export function resetErrorText(error: { code?: string; message: string }): string {
    if (error.code === 'demo_reset_disabled') return 'Demo reset is turned off on this server, so nothing was changed.';
    if (error.code === 'unauthenticated') return 'Sign in to reset the demo.';
    if (error.code === 'network_error') return 'Could not reach the server. Nothing was reset; try again.';
    return `Could not reset the demo: ${error.message}`;
}

// Clear page state first so nothing refetches the deleted run, then invalidate.
export function afterReset(clearState: () => void, invalidate: () => unknown): void {
    clearState();
    invalidate();
}
