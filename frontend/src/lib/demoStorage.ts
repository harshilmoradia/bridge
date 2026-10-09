import type { Ledger } from './transactions';

let available = true;
const listeners = new Set<() => void>();

export const storageIsAvailable = () => available;
export const subscribeToStorage = (listener: () => void) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
};

export function saveDemoLedger(ledger: Ledger) {
    const previous = available;
    try {
        localStorage.setItem('bridge-demo-ledger-v1', JSON.stringify(ledger));
        available = true;
    } catch {
        available = false;
    }
    if (previous !== available) listeners.forEach(listener => listener());
}
