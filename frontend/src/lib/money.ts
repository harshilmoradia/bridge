// Display formatting for decimal-string money. String manipulation only: no float parsing.
export const isNegative = (value: string) => value.startsWith('-') && /[1-9]/.test(value);

export function formatMoney(value: string): string {
    const [whole, fraction = ''] = value.replace(/^[-+]/, '').split('.');
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${isNegative(value) ? '-' : ''}$${grouped}.${(fraction + '00').slice(0, 2)}`;
}
