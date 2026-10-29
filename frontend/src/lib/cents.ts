// Decimal-string arithmetic on integer cents, never floats.
export function toCents(value: string): bigint {
    const negative = value.startsWith('-');
    const [whole, fraction = ''] = value.replace(/^[-+]/, '').split('.');
    const cents = BigInt(whole) * 100n + BigInt((fraction + '00').slice(0, 2));
    return negative ? -cents : cents;
}

export function fromCents(cents: bigint): string {
    const abs = (cents < 0n ? -cents : cents).toString().padStart(3, '0');
    return `${cents < 0n ? '-' : ''}${abs.slice(0, -2)}.${abs.slice(-2)}`;
}
