// Tiny store for the learned-rules sheet, so a toast action or a rule chip anywhere can open it at one rule.
export interface RulesPanelState { open: boolean; focusId: number | null }

let state: RulesPanelState = { open: false, focusId: null };
const listeners = new Set<() => void>();
const emit = () => { for (const l of listeners) l(); };

export const rulesPanel = {
    get: () => state,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    open(focusId: number | null = null) { state = { open: true, focusId }; emit(); },
    close() { state = { open: false, focusId: null }; emit(); },
};
