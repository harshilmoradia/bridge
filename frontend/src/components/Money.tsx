import { formatMoney, isNegative } from '../lib/money';
import { cn } from '../lib/utils';

// Decimal-string money; outflows (negative) render red. Never parsed to a float.
export const Money = ({ value, className }: { value: string; className?: string }) => (
    <span className={cn('tabular-nums', isNegative(value) && 'text-destructive', className)}>{formatMoney(value)}</span>
);
