from __future__ import annotations

import re

from app.schemas import RawFeedbackItem

WHITESPACE_RE = re.compile(r"\s+")
NOISE_PATTERNS = [
    re.compile(r"^n/?a$", re.IGNORECASE),
    re.compile(r"^test(?:ing)?$", re.IGNORECASE),
    re.compile(r"^[\W_]+$"),
]


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def is_obvious_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    if len(normalized) < 8:
        return True
    return any(pattern.match(normalized) for pattern in NOISE_PATTERNS)


def clean_feedback_item(item: RawFeedbackItem) -> RawFeedbackItem | None:
    cleaned_text = normalize_text(item.text)
    if is_obvious_noise(cleaned_text):
        return None
    return item.model_copy(update={"text": cleaned_text})


def clean_feedback_items(feedback_items: list[RawFeedbackItem]) -> list[RawFeedbackItem]:
    cleaned_items: list[RawFeedbackItem] = []
    for item in feedback_items:
        cleaned = clean_feedback_item(item)
        if cleaned is not None:
            cleaned_items.append(cleaned)
    return cleaned_items
