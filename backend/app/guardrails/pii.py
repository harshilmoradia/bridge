"""PII masking for bank and GL descriptions.

`mask_pii` is a pure, deterministic and idempotent function over one description
string. When a case is ambiguous it masks: losing some match signal on a business
name is cheaper than leaking a person's name. It masks:

- account and card numbers, to the last 4 digits (`****4417`): a run of 5+
  digits after ACCT/ACCOUNT, a standalone run of 9-17 digits, or 3-5 groups of
  4-6 digits joined by one consistent space or hyphen (12+ digits in all);
- emails (`[EMAIL]`): the whole whitespace-delimited token around an `@` whose
  domain side holds a letter;
- phone numbers (`[PHONE]`, with any `+1`/`1-` prefix and `x`/`ext`/`ext.`
  extension) and SSNs (`[SSN]`, hyphen or space separated);
- individual payee names (`[PERSON]`), found by context rather than a name list:
  - bank style: the name words after `REIMB`, `ZELLE FROM` or `ZELLE TO` (any
    case) or `PAYROLL` (upper case only, so `Payroll Expense` and other GL or
    chart-of-accounts wording is not a cue). The name runs until a stop word
    (ACCT, PH, MEMO, ...), a token with a digit, punctuation or the end. It is
    left alone only when it reads as a business: a single business word
    (`SERVICES`), or a business word after two or more full words
    (`ACME RETAIL GRP`);
  - GL style: the trailing `- First Last` segment of a description that mentions
    `Employee`, `Payroll advance` or `Travel Expense`.

Business counterparties, amounts, dates, check numbers and reference numbers are
left as they are: matching needs them.
"""

import re

# Starts only at a token boundary, so a long run without a match stays linear.
EMAIL = re.compile(r"(?<!\S)[^\s@]+@\S+")
SSN = re.compile(r"(?<![\w-])\d{3}([-\s])\d{2}\1\d{4}(?![\w-])")
# Trailing `.`, `,` or `/` blocks a match only when a digit follows it (`0147.50`,
# `1111,2222`, a date); as sentence punctuation (`0147, MEMO`) it does not.
_NUMBER_END = r"(?![\w-]|[.,/]\d)"
GROUPED_DIGITS = re.compile(
    rf"(?<![\w.,*/-])\d{{4,6}}([-\s])\d{{4,6}}(?:\1\d{{4,6}}){{1,3}}{_NUMBER_END}"
)
PHONE = re.compile(
    r"(?<![\w+.,/-])(?:\+?1[-.\s])?(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}"
    # A phone cannot be part of a date, so `/` after it does not block (`0147/0148`).
    rf"(?:\s?(?i:x|ext\.?)\s?\d{{1,6}})?(?![\w-]|[.,]\d)"
)
ACCOUNT_AFTER_KEYWORD = re.compile(r"\b(ACCT|ACCOUNT)(#?\s*)(\d{5,})\b", re.IGNORECASE)
LONG_DIGITS = re.compile(r"(?<![\d.,*-])\d{9,17}(?![\d-]|[.,/]\d)")

_STOP = r"(?i:ACCT|ACCOUNT|PH|MEMO|REF|CONF|ID|INV|FED|BNF)\b"
# A name word: letters, with inner hyphens, apostrophes or dots, and an optional
# trailing dot for initials (`J.`). Punctuation after it ends the name.
_NAME_WORD = rf"(?!{_STOP})[A-Za-z](?:[A-Za-z']|[-.](?=[A-Za-z]))*\.?(?![\w@])"
BANK_PERSON = re.compile(
    # Separators: any whitespace except a newline (so a non-breaking space counts).
    rf"\b((?i:REIMB|ZELLE[^\S\n]+FROM|ZELLE[^\S\n]+TO)|PAYROLL)([^\S\n]+)"
    rf"({_NAME_WORD}(?:[^\S\n]+{_NAME_WORD})*)"
)
BUSINESS_WORDS = {"INC", "LLC", "LTD", "CORP", "GROUP", "GRP", "SERVICES", "SERVICE", "SVC", "SVCS"}
GL_PERSON_CONTEXT = re.compile(r"\b(?:employee|payroll advance|travel expense)\b", re.IGNORECASE)
GL_PERSON = re.compile(r"( - )([A-Z][a-z'-]+(?: [A-Z][a-z'-]+){1,2})$")

PERSON = "[PERSON]"


def _last4(digits: str) -> str:
    return "****" + digits[-4:]


def _mask_email(m: re.Match[str]) -> str:
    domain = m[0].split("@", 1)[1]
    return "[EMAIL]" if re.search(r"[A-Za-z]", domain) else m[0]


def _mask_grouped(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m[0])
    return _last4(digits) if len(digits) >= 12 else m[0]


def _reads_as_business(words: list[str]) -> bool:
    """A lone business word, or a business word after two or more full words."""
    if words[-1] not in BUSINESS_WORDS:
        return False
    full_words_before = [w for w in words[:-1] if len(w) > 1]
    return len(words) == 1 or len(full_words_before) >= 2


def _mask_bank_person(m: re.Match[str]) -> str:
    cue, separator, name = m[1], m[2], m[3]
    words = [w.strip(".").upper() for w in name.split()]
    if _reads_as_business(words):
        return m[0]
    return cue + separator + PERSON


def mask_pii(text: str) -> str:
    """Return `text` with account numbers, contact details and person names masked."""
    text = EMAIL.sub(_mask_email, text)
    text = SSN.sub("[SSN]", text)
    text = GROUPED_DIGITS.sub(_mask_grouped, text)
    text = PHONE.sub("[PHONE]", text)
    text = ACCOUNT_AFTER_KEYWORD.sub(lambda m: m[1] + m[2] + _last4(m[3]), text)
    text = LONG_DIGITS.sub(lambda m: _last4(m[0]), text)
    text = BANK_PERSON.sub(_mask_bank_person, text)
    if GL_PERSON_CONTEXT.search(text):
        text = GL_PERSON.sub(lambda m: m[1] + PERSON, text)
    return text
