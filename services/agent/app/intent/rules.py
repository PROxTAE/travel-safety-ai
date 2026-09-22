"""Deterministic intent rules — Phase 2 (`feat/03-intent-extraction`).

Implements the precedence order in `docs/intent-and-required-fields.md` §1: every rule here is a
plain keyword substring scan or a structural field check, never NLU. That is what makes it safe
against prompt injection by construction — the text is only ever scanned for membership in a fixed
keyword list, never interpreted as instructions — and what makes it something a reviewer can
verify completely by reading the keyword lists in §3 of that doc.
"""

from __future__ import annotations

import re
import unicodedata

from app.graph.state import InputSection, Intent

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_EMERGENCY_KEYWORDS = (
    "ฉุกเฉิน",
    "ช่วยด้วย",
    "ช่วยฉันด้วย",
    "อุบัติเหตุ",
    "บาดเจ็บ",
    "เลือดออก",
    "ติดอยู่",
    "ตายแล้ว",
    "โทรตำรวจ",
    "โทรรถพยาบาล",
    "หายใจไม่ออก",
    "ถูกทำร้าย",
    "emergency",
    "help me",
    "sos",
    "accident",
    "injured",
    "injury",
    "bleeding",
    "trapped",
    "dying",
    "can't breathe",
    "cannot breathe",
    "call police",
    "call an ambulance",
    "attacked",
)

_CHECK_SAFETY_KEYWORDS = (
    "ปลอดภัย",
    "อันตราย",
    "เสี่ยง",
    "น้ำท่วม",
    "พายุ",
    "แผ่นดินไหว",
    "เตือนภัย",
    "ปิดถนน",
    "ภัยพิบัติ",
    "safe",
    "safety",
    "dangerous",
    "danger",
    "risk",
    "risky",
    "flood",
    "storm",
    "earthquake",
    "warning",
    "alert",
    "closure",
    "closed road",
    "hazard",
)


def normalize_question(question: str) -> str:
    """Lowercase, strip control characters, collapse whitespace — for keyword matching only.
    Never used to mutate the stored `question`: the agent never rewrites the user's own text.
    """
    stripped = _CONTROL_CHARS.sub(" ", question)
    stripped = unicodedata.normalize("NFKC", stripped)
    return " ".join(stripped.lower().split())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_deterministic(input_section: InputSection) -> Intent | None:
    """The Intent a deterministic rule matched, or `None` if the question is ambiguous — callers
    (the `classify_intent` node) decide what to do with `None`: try the LLM classifier, or fall
    back to `ASK_INFORMATION`. This function never guesses.
    """
    question = input_section.travel_request.question
    normalized = normalize_question(question) if question is not None else None

    if normalized is not None and _contains_any(normalized, _EMERGENCY_KEYWORDS):
        return Intent.EMERGENCY

    request = input_section.travel_request
    if request.conversation_id is not None and input_section.approved_context_refs:
        return Intent.FOLLOW_UP

    if normalized is not None and _contains_any(normalized, _CHECK_SAFETY_KEYWORDS):
        return Intent.CHECK_SAFETY

    if question is None:
        return Intent.PLAN_TRIP

    return None
