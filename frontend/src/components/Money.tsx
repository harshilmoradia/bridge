import { formatMoney, isNegative } from '../lib/money';
import { cn } from '../lib/utils';

// Decimal-string money; outflows (negative) render red. Never parsed to a float.
export const Money = ({ value, className }: { value: string; className?: string }) => (
    <span className={cn('tabular-nums', isNegative(value) && 'text-red-600 dark:text-red-400', className)}>{formatMoney(value)}</span>
);
