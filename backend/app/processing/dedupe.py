from __future__ import annotations

import hashlib
from typing import Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.processing.cleaner import normalize_text
from app.schemas import RawFeedbackItem


DuplicateStats = dict[str, int]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized_text(text: str) -> str:
    return normalize_text(text).lower()


def deduplicate_feedback_items(
    feedback_items: list[RawFeedbackItem],
    *,
    similarity_threshold: float = 0.75,
    debug: bool = False,
) -> tuple[list[RawFeedbackItem], list[str], DuplicateStats]:
    if not feedback_items:
        return [], [], {
            "exact_duplicates_removed": 0,
            "normalized_duplicates_removed": 0,
            "near_duplicates_removed": 0,
        }

    unique_items: list[RawFeedbackItem] = []
    debug_notes: list[str] = []
    stats: DuplicateStats = {
        "exact_duplicates_removed": 0,
        "normalized_duplicates_removed": 0,
        "near_duplicates_removed": 0,
    }

    raw_hashes: set[str] = set()
    normalized_hashes: set[str] = set()

    for item in feedback_items:
        raw_hash = _hash_text(item.text)
        normalized_hash = _hash_text(_normalized_text(item.text))

        if raw_hash in raw_hashes:
            stats["exact_duplicates_removed"] += 1
            if debug:
                debug_notes.append(f"{item.feedback_id}: removed_exact_duplicate")
            continue

        if normalized_hash in normalized_hashes:
            stats["normalized_duplicates_removed"] += 1
            if debug:
                debug_notes.append(f"{item.feedback_id}: removed_normalized_duplicate")
            continue

        raw_hashes.add(raw_hash)
        normalized_hashes.add(normalized_hash)
        unique_items.append(item)

    if len(unique_items) <= 1:
        return unique_items, debug_notes, stats

    texts = [_normalized_text(item.text) for item in unique_items]
    word_vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
    word_matrix = word_vectorizer.fit_transform(texts)
    word_similarity = cosine_similarity(word_matrix)

    char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    char_matrix = char_vectorizer.fit_transform(texts)
    char_similarity = cosine_similarity(char_matrix)

    deduped_items: list[RawFeedbackItem] = []
    removed_indices: set[int] = set()

    for i, item in enumerate(unique_items):
        if i in removed_indices:
            continue
        deduped_items.append(item)
        for j in range(i + 1, len(unique_items)):
            if j in removed_indices:
                continue
            similarity = max(word_similarity[i][j], char_similarity[i][j])
            if similarity >= similarity_threshold:
                removed_indices.add(j)
                stats["near_duplicates_removed"] += 1
                if debug:
                    debug_notes.append(
                        f"{unique_items[j].feedback_id}: removed_near_duplicate_of={item.feedback_id} similarity={similarity:.2f}"
                    )

    return deduped_items, debug_notes, stats
