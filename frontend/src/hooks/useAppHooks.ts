import { useState, useEffect, useCallback, useRef } from 'react';

export const useTimeouts = () => {
    const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
    useEffect(() => () => {
        timers.current.forEach(clearTimeout);
        timers.current.clear();
    }, []);
    return useCallback((callback: () => void, delay: number) => {
        const timer = setTimeout(() => {
            timers.current.delete(timer);
            callback();
        }, delay);
        timers.current.add(timer);
    }, []);
};

export const useKeyboardShortcuts = (handlers: Record<string, () => void>) => {
    const handlersRef = useRef(handlers);
    useEffect(() => { handlersRef.current = handlers; }, [handlers]);
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Ctrl+K → focus chat
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                handlersRef.current['ctrl+k']?.();
            }
            // Escape → close modal
            if (e.key === 'Escape') {
                handlersRef.current['escape']?.();
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);
};

export const useToast = () => {
    const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'info' }[]>([]);
    const schedule = useTimeouts();

    const addToast = useCallback((message: string, type: 'success' | 'info' = 'success') => {
        const id = crypto.randomUUID();
        setToasts(prev => [...prev, { id, message, type }]);
        schedule(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 3000);
    }, [schedule]);

    return { toasts, addToast };
};
