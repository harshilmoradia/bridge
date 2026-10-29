// Mock-only item rows: [id suffix, kind, amount_delta, account, memo]. Accounts must exist in demo-data/chart_of_accounts.csv.
export const MOCK_EXTRA_ROWS: ReadonlyArray<readonly [string, string, string, string, string]> = [
    ['9001', 'deposit_in_transit', '900.00', '1200', 'Record deposit in transit'],
    ['9002', 'outstanding_check', '-30.00', '2000', 'Record outstanding check'],
    ['9003', 'interest_missing_in_gl', '6.59', '4100', 'Record interest income'],
];
