"""B-08 slice 1: PII masking over bank and GL descriptions.

Expected strings are written by hand from reading the raw rows in demo-data/.
"""

import time

import pytest

from app.guardrails import mask_pii
from scripts.seed import load_bank, load_gl

DATASET = "northbrook-2026-10"


@pytest.fixture(scope="module")
def bank() -> dict[str, str]:
    return {r["txn_id"]: r["description"] for r in load_bank(DATASET)}


@pytest.fixture(scope="module")
def gl() -> dict[str, str]:
    return {r["entry_id"]: r["description"] for r in load_gl(DATASET)}


# --- The three planted PII rows -------------------------------------------------


def test_bank004_account_and_person_masked(bank):
    assert bank["BANK004"] == "ACH DEBIT REIMB SARAH PATEL ACCT 000123456789"
    assert mask_pii(bank["BANK004"]) == "ACH DEBIT REIMB [PERSON] ACCT ****6789"


def test_bank068_email_and_phone_masked_vendor_and_ref_kept(bank):
    assert mask_pii(bank["BANK068"]) == (
        "WIRE OUT XYZ INDUSTRIAL SUP FED REF 781382 BNF CONTACT [EMAIL] [PHONE]"
    )


def test_bank113_person_and_phone_masked_masked_account_kept(bank):
    assert mask_pii(bank["BANK113"]) == (
        "ZELLE FROM [PERSON] ACCT ****4417 PH [PHONE] MEMO OCT ORDER"
    )


# --- Other people-payee rows in demo-data ---------------------------------------


@pytest.mark.parametrize(
    ("txn_id", "expected"),
    [
        ("BANK024", "ACH DEBIT REIMB [PERSON]"),
        ("BANK099", "ACH DEBIT REIMB [PERSON]"),
        ("BANK070", "ACH DEBIT PAYROLL [PERSON] 781505"),
    ],
)
def test_other_person_payee_bank_rows(bank, txn_id, expected):
    assert mask_pii(bank[txn_id]) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Employee Reimbursement - Sarah Patel", "Employee Reimbursement - [PERSON]"),
        ("Employee Salary - Michael Chen", "Employee Salary - [PERSON]"),
        (
            "Travel Expense Reimbursement - David Okafor",
            "Travel Expense Reimbursement - [PERSON]",
        ),
        (
            "Payroll Advance - Payroll advance - James Wilson",
            "Payroll Advance - Payroll advance - [PERSON]",
        ),
        (
            "Employee Bonus Distribution - Employee bonus - Maria Gonzalez",
            "Employee Bonus Distribution - Employee bonus - [PERSON]",
        ),
    ],
)
def test_person_payee_gl_descriptions(gl, raw, expected):
    assert raw in gl.values()
    assert mask_pii(raw) == expected


# --- Whole-file sweeps: only the hand-identified rows change --------------------


def test_only_person_and_pii_bank_rows_change(bank):
    changed = {tid for tid, d in bank.items() if mask_pii(d) != d}
    assert changed == {"BANK004", "BANK024", "BANK068", "BANK070", "BANK099", "BANK113"}


def test_only_employee_gl_rows_change(gl):
    changed = {d for d in gl.values() if mask_pii(d) != d}
    assert changed == {
        "Employee Reimbursement - Sarah Patel",
        "Employee Salary - Michael Chen",
        "Travel Expense Reimbursement - David Okafor",
        "Employee Travel Reimbursement - David Okafor",
        "Payroll Advance - Payroll advance - James Wilson",
        "Employee Bonus Distribution - Employee bonus - Maria Gonzalez",
    }


def test_idempotent_over_all_descriptions(bank, gl):
    for d in [*bank.values(), *gl.values()]:
        once = mask_pii(d)
        assert mask_pii(once) == once


# --- Negative cases --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "ONLINE PMT TECHSOLNS INC CONF#780589",  # vendor name and confirmation number
        "ACH DEBIT PAYFLOW PAYROLL 780982",  # payroll vendor, not a person
        "Client Reimbursement - Acme Retail Group",  # business after a reimbursement word
        "Insurance Claim Reimbursement - Granite Mutual Insurance",
        "CHECK 3105",  # check number
        "REMOTE DEPOSIT CHK 3116",
        "Check Payment - Office Supplies - DeskPro Supply",
        "ONLINE XFER TO SAV ...8802 780725",
        "Bank Account Transfer - Transfer to Savings x8802",
        "WIDGET CO PMT 1,234.51 ON 2026-10-01",  # amount and date in text
        "REFUND -8900.00 POSTED 10/07/2026",
    ],
)
def test_non_pii_text_unchanged(text):
    assert mask_pii(text) == text


# --- Generic patterns ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SSN 123-45-6789 ON FILE", "SSN [SSN] ON FILE"),
        ("CALL (312) 555-0147", "CALL [PHONE]"),
        ("CALL 312.555.0147", "CALL [PHONE]"),
        ("MAIL First.Last+ap@vendor.co.uk", "MAIL [EMAIL]"),
        ("ACCT# 9876543210", "ACCT# ****3210"),
        ("WIRE IN BNF 4400112233445566 REF 77", "WIRE IN BNF ****5566 REF 77"),
    ],
)
def test_generic_patterns(raw, expected):
    assert mask_pii(raw) == expected


# --- Follow-up: case, long names, more formats, email backtracking ---------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zelle from j martinez", "zelle from [PERSON]"),
        ("Zelle From J Martinez", "Zelle From [PERSON]"),
        ("Zelle From J Martinez acct ****4417", "Zelle From [PERSON] acct ****4417"),
        ("zelle to j martinez Memo rent", "zelle to [PERSON] Memo rent"),
        ("ach debit reimb d okafor ph 312-555-0186", "ach debit reimb [PERSON] ph [PHONE]"),
        ("ZELLE FROM J MARTINEZ Id 55", "ZELLE FROM [PERSON] Id 55"),
    ],
)
def test_person_cue_is_case_insensitive(raw, expected):
    assert mask_pii(raw) == expected


def test_upper_case_payroll_cue_masks_any_case_name():
    assert mask_pii("PAYROLL m chen Ref 781505") == "PAYROLL [PERSON] Ref 781505"


def test_known_limit_title_case_payroll_is_not_a_cue():
    # PAYROLL is a name cue only in upper case, so chart-of-accounts and GL wording
    # such as "Payroll Expense" or "Payroll Taxes" is not masked. The cost: a
    # title-case bank memo with a person's name after "Payroll" passes through.
    assert mask_pii("Payroll M Chen 781505") == "Payroll M Chen 781505"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PH 312-555-0147, MEMO", "PH [PHONE], MEMO"),
        ("PH 312-555-0147,", "PH [PHONE],"),
        ("CONTACT 312-555-0147, ap@x.com", "CONTACT [PHONE], [EMAIL]"),
        ("PH 312-555-0147/ OCT", "PH [PHONE]/ OCT"),
        ("PH (312) 555-0147.", "PH [PHONE]."),
        ("CARD 4111-1111-1111-1111.", "CARD ****1111."),
        ("CARD 4111 1111 1111 1111, EXP", "CARD ****1111, EXP"),
        ("ACCT 0001-2345-6789, MEMO", "ACCT ****6789, MEMO"),
        ("4400112233445566, REF", "****5566, REF"),
        ("PH 312-555-0147/0148", "PH [PHONE]/0148"),
    ],
)
def test_number_followed_by_punctuation_masked(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    "text",
    ["1,234,567.89", "10/15/2026", "AMT 0147.50", "PH 312-555-0147.50", "CARD 4111-1111-1111,2222", "ID 123456789012.5"],
)
def test_punctuation_that_continues_a_number_still_blocks(text):
    assert mask_pii(text) == text


def test_non_breaking_space_between_name_words():
    assert mask_pii("ZELLE FROM\xa0JOHN\xa0SMITH") == "ZELLE FROM\xa0[PERSON]"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ZELLE TO MARIA DE LA CRUZ GARCIA", "ZELLE TO [PERSON]"),
        ("ZELLE TO MARIA DE LA CRUZ GARCIA MEMO RENT", "ZELLE TO [PERSON] MEMO RENT"),
        ("ACH DEBIT REIMB ANA MARIA DE LA CRUZ 781505", "ACH DEBIT REIMB [PERSON] 781505"),
    ],
)
def test_long_names_masked_whole(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PH 312 555 0147", "PH [PHONE]"),
        ("PH 1-312-555-0147", "PH [PHONE]"),
        ("PH +1 312-555-0147", "PH [PHONE]"),
        ("SSN 123 45 6789", "SSN [SSN]"),
        ("CARD 4111 1111 1111 1111", "CARD ****1111"),
        ("CARD 4111-1111-1111-1111", "CARD ****1111"),
        ("ACCT 0001-2345-6789", "ACCT ****6789"),
    ],
)
def test_more_phone_ssn_and_card_formats(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        "WIRE IN 1,234,567.89 RECEIVED",
        "POSTED 10/15/2026",
        "POSTED 2026-10-15",
        "FED REF 781382 CONF#780589",
        "CHECK 3105",
        "CHECK 3105 AMT 1,200.00 ON 10/15/2026",
    ],
)
def test_new_formats_do_not_over_match(text):
    assert mask_pii(text) == text


def test_email_pattern_has_no_catastrophic_backtracking():
    text = "a" * 10000 + "@" + "b" * 10000
    start = time.perf_counter()
    mask_pii(text)
    assert time.perf_counter() - start < 0.1


# --- Last pass: punctuation, extensions, veto, chart of accounts, long emails ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ZELLE FROM JOHN SMITH, OCT RENT", "ZELLE FROM [PERSON], OCT RENT"),
        ("ZELLE FROM JOHN SMITH/OCT", "ZELLE FROM [PERSON]/OCT"),
        ("ZELLE FROM JOHN SMITH; MEMO X", "ZELLE FROM [PERSON]; MEMO X"),
        ("ZELLE FROM JOHN SMITH (OCT)", "ZELLE FROM [PERSON] (OCT)"),
        ("ZELLE FROM JOHN SMITH - OCT RENT", "ZELLE FROM [PERSON] - OCT RENT"),
        ("ZELLE FROM J. MARTINEZ", "ZELLE FROM [PERSON]"),
    ],
)
def test_name_followed_by_punctuation_masked(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PH 312-555-0147x22", "PH [PHONE]"),
        ("PH 312-555-0147 ext 22", "PH [PHONE]"),
        ("PH 312-555-0147 ext. 22", "PH [PHONE]"),
        ("PH 312-555-0147 EXT 22", "PH [PHONE]"),
    ],
)
def test_phone_extension_masked(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ZELLE FROM JOHN CO", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM J CO", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM ANH CO", "ZELLE FROM [PERSON]"),
        ("REIMB ANH CO", "REIMB [PERSON]"),
        ("ZELLE FROM GRP SMITH", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM J INC", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM MARIA GROUP", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM ANNA INC", "ZELLE FROM [PERSON]"),
        ("ZELLE FROM ACME CO", "ZELLE FROM [PERSON]"),
    ],
)
def test_business_veto_does_not_shield_people(raw, expected):
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        "ACH DEBIT PAYFLOW PAYROLL SERVICES",
        "ACH Payroll - Bi-Weekly - PayFlow Payroll Services",
        "Payroll ACH Transfer - PayFlow Payroll Services",
        "Payroll Processing - PayFlow Payroll Services",
        "ZELLE FROM ACME RETAIL GRP",
        "Payroll Advance - Payroll advance",
        "Payroll Taxes - IRS EFTPS",
        "Payroll Expense",
        "Payroll Taxes",
        "QTY 2@5.00",
    ],
)
def test_business_and_account_names_unchanged(text):
    assert mask_pii(text) == text


def test_chart_of_accounts_unchanged():
    import csv

    from scripts.seed import DATA_DIR

    with (DATA_DIR / "chart_of_accounts.csv").open(newline="", encoding="utf-8") as f:
        values = [v for row in csv.DictReader(f) for v in row.values() if v]
    assert len(values) == 32 * 3
    assert [v for v in values if mask_pii(v) != v] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "MAIL user@sub1.sub2.sub3.sub4.sub5.sub6.sub7.sub8.sub9.sub10.example.com OK",
            "MAIL [EMAIL] OK",
        ),
        ("MAIL " + "q" * 70 + "@vendor.com OK", "MAIL [EMAIL] OK"),
        ("MAIL john@localhost OK", "MAIL [EMAIL] OK"),
    ],
)
def test_long_emails_masked_whole(raw, expected):
    assert mask_pii(raw) == expected


def test_deterministic():
    raw = "ZELLE FROM J MARTINEZ ACCT ****4417 PH 312-555-0186 MEMO OCT ORDER"
    assert {mask_pii(raw) for _ in range(5)} == {mask_pii(raw)}
