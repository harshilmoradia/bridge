import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MOCK_EXTRA_ROWS } from '../src/api/mockExtras.ts';

// Copy of demo-data/chart_of_accounts.csv account numbers.
const CHART = new Set(['1010', '1020', '1200', '1300', '1350', '1500', '2000', '2300', '2400', '4000', '4100', '4200', '4900', '5000', '6000', '6100', '6150', '6200', '6210', '6300', '6400', '6500', '6510', '6600', '6700', '6750', '6760', '6800', '6850', '6900', '6950', '6990']);

test('every mock extra item posts to an account in the chart of accounts', () => {
    for (const [n, , , account] of MOCK_EXTRA_ROWS) assert.ok(CHART.has(account), `${n}: ${account}`);
});
