"""Prompt-injection flagging for bank and GL descriptions.

`detect_injection` is a pure, deterministic regex check over one description,
NFKC-normalised first so fullwidth look-alikes (`＜system＞`, `ＩＧＮＯＲＥ`) match
too. It flags and never strips: a flagged row is still matched by code, and its
text still reaches prompts inside `<untrusted>` tags (see `app.guardrails.untrusted`).
Each heuristic has a reason name, so the UI and audit log can say why a row was
flagged:

- `addresses_ai`: text written to the model ("NOTE TO AI AGENT", "message for the
  assistant", "AI AGENT", a vocative such as "Assistant," or "AI:", "Nemotron").
  A vendor named "AI ..." or a shipping agent is not one.
- `override_instructions`: ignore, disregard, forget, override or bypass followed
  within a few words by instructions, rules, prompts, guidelines or policies, or
  "ignore the above", "disregard everything", "ignore previous".
- `role_marker`: chat-template or role tags (`<system>`, `</untrusted>`, `[INST]`,
  `<|im_start|>`), "system prompt", "system note", "admin override".
- `role_override`: "you are now", "pretend to be", "new instructions", "from now on".
- `blanket_action`: approve, resolve, close, mark, post, reconcile or pay followed by
  all, every, everything, each or any.
- `suppress_review`: "do not escalate", "skip review", "without approval" and alike.
- `exfiltrate`: "reveal your system prompt" and alike.

Some patterns are weak: real bank memos use them ("CLOSE ALL ACCOUNTS FEE",
"SYSTEM: ADP PAYROLL", "ACT AS AGENT COMMISSION"). A weak match (`blanket_action`,
"system:", "act as") never flags on its own; it is reported only next to a strong one.

Architecture also plans a Nano yes/no check on rows these heuristics flag; that
model call belongs with the agents (B-09), not here.
"""

import re
import unicodedata
from dataclasses import dataclass

_I = re.IGNORECASE
_AI = r"(?:ai|llm|assistant|agent|model|bot|chatbot|gpt)s?"

PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "addresses_ai": [
        re.compile(rf"\b(?:note|message|instructions?|memo|reminder)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?{_AI}\b", _I),
        re.compile(r"\b(?:ai|llm)\s+(?:agent|assistant|model|system|bot)s?\b", _I),
        re.compile(rf"\b(?:dear|attention|attn:?|hey|hello)\s+(?:the\s+)?{_AI}\b", _I),
        # Vocatives: "AI:" or "LLM," anywhere; "Assistant," only at the start or after punctuation.
        re.compile(r"\b(?:ai|llm|chatbot)\s*[,:]", _I),
        re.compile(r"(?:^|[^\w\s]\s*)(?:assistant|agent|model|bot)\s*,", _I),
        re.compile(r"\bnemotron\b", _I),
    ],
    "override_instructions": [
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b(?:\W+\w+){0,3}?\W+"
            r"(?:instructions?|rules?|prompts?|directions?|guidelines?|polic(?:y|ies)|guardrails?)\b",
            _I,
        ),
        re.compile(r"\b(?:ignore|disregard)\s+(?:the\s+)?(?:above|everything|previous|prior)\b", _I),
    ],
    "role_marker": [
        re.compile(r"<\s*/?\s*(?:system|assistant|user|developer|untrusted|instructions?)\b[^>]*>", _I),
        re.compile(r"\[/?INST\]|<\|im_(?:start|end)\|>", _I),
        re.compile(r"\b(?:system|developer)\s*(?:prompt|message|note|override|instructions?)s?\b", _I),
        re.compile(r"\badmin(?:istrator)?\s+(?:override|note|message|instructions?|command)s?\b", _I),
    ],
    "role_override": [
        re.compile(r"\byou\s+are\s+now\b|\bpretend\s+(?:to\s+be|you)\b", _I),
        re.compile(r"\bnew\s+instructions?\b|\bfrom\s+now\s+on\b", _I),
    ],
    "suppress_review": [
        re.compile(
            r"\b(?:do\s+not|don'?t|never|no\s+need\s+to)\s+"
            r"(?:flag|escalate|review|report|question|check|verify)\b",
            _I,
        ),
        re.compile(r"\b(?:skip|bypass|without)\s+(?:the\s+|any\s+)?(?:review|approval|checks?|verification|escalation)\b", _I),
    ],
    "exfiltrate": [
        re.compile(
            r"\b(?:reveal|print|show|repeat|output|leak)\s+(?:me\s+)?(?:your|the)\s+"
            r"(?:system\s+)?(?:prompt|instructions)\b",
            _I,
        ),
    ],
}


# Weak patterns: reported only when a strong pattern also matched.
WEAK_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "blanket_action": [
        re.compile(
            r"\b(?:auto[-\s]?)?(?:approve|resolve|close|clear|accept|mark|post|reconcile|pay)"
            r"\s+(?:all|every|everything|each|any)\b",
            _I,
        ),
    ],
    "role_marker": [re.compile(r"\bsystem\s*:", _I)],
    "role_override": [re.compile(r"\bact\s+as\b", _I)],
}


def _matching(patterns: dict[str, list[re.Pattern[str]]], text: str) -> set[str]:
    return {name for name, ps in patterns.items() if any(p.search(text) for p in ps)}


@dataclass(frozen=True)
class InjectionResult:
    flagged: bool
    reasons: tuple[str, ...]  # sorted reason names from PATTERNS and WEAK_PATTERNS


def detect_injection(text: str) -> InjectionResult:
    """Flag `text` when it reads as instructions to the model rather than bank data."""
    text = unicodedata.normalize("NFKC", text)
    strong = _matching(PATTERNS, text)
    if not strong:
        return InjectionResult(flagged=False, reasons=())
    return InjectionResult(flagged=True, reasons=tuple(sorted(strong | _matching(WEAK_PATTERNS, text))))
