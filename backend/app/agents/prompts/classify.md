# classify

You classify the lines a bank reconciliation could not match. Code already matched everything that ties by amount and date. You receive the leftover bank lines and leftover general-ledger (GL) lines, plus, for some lines, matched lines that look similar.

Group the leftover lines into items and give each item one kind. Every leftover ID must appear in exactly one item. Kinds:

- `outstanding_check`: one GL check payment that has not cleared the bank yet (`check_facts` shows `cleared_by_bank: null`). If `cleared_by_bank` names a bank line, the check already cleared, so this GL line is not outstanding; when `similar_matched` shows an identical matched GL line, it is a `duplicate_gl_entry`.
- `deposit_in_transit`: one GL deposit near period end that the bank has not posted yet.
- `bank_fee_missing_in_gl`: one bank fee or service charge with no GL entry.
- `interest_missing_in_gl`: one bank interest credit with no GL entry.
- `unidentified_receipt`: one bank credit with no GL entry and no clear source.
- `duplicate_gl_entry`: one GL line that is a second copy of a line that already matched (see `similar_matched`).
- `transposition`: one bank line and one GL line for the same payment where the digits of the amount were swapped when booking (for example 925.00 against 952.00). Put both IDs in one item.
- `nsf_pair`: one returned-item (NSF) bank line and its GL reversal.
- `unknown`: anything else, or when you are not sure.

Do not do arithmetic; use only the amounts given. Prefer `unknown` to a guess.

Reply with only a JSON object: `{"items": [{"bank_ids": ["BANK019"], "gl_ids": ["GL023"], "kind": "transposition"}]}`.
