import { useEffect, useRef, useState } from 'react';
import { interpolateMoney } from '../lib/workspace';

const DURATION_MS = 700;

// Animates a decimal-string amount from the value currently shown to `target`. First render and reduced-motion show the target directly.
export function useCountUp(target: string): string {
    const [shown, setShown] = useState(target);
    const shownRef = useRef(target);
    useEffect(() => {
        if (shownRef.current === target) return;
        const duration = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 1 : DURATION_MS;
        const from = shownRef.current;
        const start = performance.now();
        let frame = 0;
        const tick = (now: number) => {
            const t = Math.min((now - start) / duration, 1);
            const value = interpolateMoney(from, target, 1 - (1 - t) ** 3);
            shownRef.current = value; setShown(value);
            if (t < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [target]);
    return shown;
}
