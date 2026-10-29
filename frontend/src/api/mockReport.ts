// Mock-only Ultra report for the completed demo run. Numbers match the fixture statement and counts:
// 48,547.99 bank, 47,683.90 book, raw difference 864.09, five approvals summing to 864.09 (final 0.00).
export const MOCK_REPORT = `## Northbrook Goods Co. bank reconciliation, Oct 1-10 2026

The bank closed at **48,547.99** and the book at **47,683.90**, a raw difference of **864.09**. Once the five pending items are approved, the unreconciled difference is **0.00**.

### Outcome

| Result | Count |
| --- | ---: |
| Matched by rule | 96 |
| Auto-resolved by policy | 2 |
| Reconciling items (timing) | 2 |
| Need approval | 5 |

### What needs your approval

| Item | Amount | Draft entry |
| --- | ---: | --- |
| Deposit in transit | 900.00 | Record deposit in transit |
| Bank fee missing in the ledger | -25.00 | Record October monthly service fee |
| Outstanding check | -30.00 | Record outstanding check |
| Interest missing in the ledger | 12.50 | Record October interest income |
| Interest missing in the ledger | 6.59 | Record interest income |

These five amounts sum to 864.09, the whole raw difference.

### Notes

- Every draft entry passed the code checks. A person approves each one before it posts.
- Reconciling items stay open until the bank clears them.
`;
