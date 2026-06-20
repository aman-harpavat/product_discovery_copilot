from __future__ import annotations

from app.schemas import AnalyzeFeedbackRequest, RawFeedbackItem

DEFAULT_DISCOVERY_KEYWORDS = {
    "recommendation",
    "recommendations",
    "discover",
    "discovery",
    "discover weekly",
    "release radar",
    "playlist",
    "personalization",
    "personalised",
    "personalized",
    "algorithm",
    "artist",
    "artists",
    "new music",
    "find music",
    "finding music",
    "shuffle",
    "smart shuffle",
    "novelty",
    "fresh",
    "variety",
}

SPOTIFY_DISCOVERY_ANCHORS = {
    "spotify",
    "discover weekly",
    "release radar",
    "daily mix",
    "daylist",
    "made for you",
    "smart shuffle",
}

DISCOVERY_CONTEXT_TERMS = {
    "music",
    "songs",
    "artists",
    "albums",
    "playlist",
    "spotify",
    "shuffle",
    "novelty",
    "variety",
}

DISCOVERY_SCOPE_TERMS = {
    "recommendation",
    "recommendations",
    "discover",
    "discovery",
    "discover weekly",
    "release radar",
    "daily mix",
    "daylist",
    "made for you",
    "shuffle",
    "smart shuffle",
    "playlist",
    "playlists",
    "personalization",
    "personalized",
    "personalised",
    "novelty",
    "variety",
    "repeat",
    "repetitive",
    "same songs",
    "same artists",
}

GENERIC_COMPLAINT_TERMS = {
    "crash",
    "crashes",
    "bug",
    "bugs",
    "login",
    "password",
    "billing",
    "price",
    "pricing",
    "premium",
    "subscription",
    "ads",
    "advertisements",
    "payment",
    "support",
    "slow",
}

OPPORTUNITY_SIGNAL_TERMS = {
    "repetitive",
    "repeat",
    "repeats",
    "same songs",
    "same artists",
    "stale",
    "bad",
    "worse",
    "worst",
    "issue",
    "issues",
    "problem",
    "problems",
    "frustrating",
    "annoying",
    "hate",
    "broken",
    "limited",
    "difficult",
    "hard",
    "can't",
    "cannot",
    "wish",
    "needs",
    "need",
    "should",
    "request",
    "better",
    "improve",
    "more control",
    "less control",
    "too narrow",
    "too broad",
    "keeps playing",
    "stops recommending",
    "doesn't recommend",
    "not enough variety",
    "more variety",
}

POSITIVE_SIGNAL_TERMS = {
    "love",
    "great",
    "amazing",
    "best",
    "awesome",
    "perfect",
    "magic",
    "helpful",
    "useful",
    "good",
}


def _normalize_terms(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value and value.strip()]


def _is_spotify_specific(item: RawFeedbackItem, text: str) -> bool:
    if item.source in {"google_play", "app_store"}:
        return True

    subreddit = (item.metadata.subreddit or "").lower()
    if "spotify" in subreddit:
        return True

    return any(anchor in text for anchor in SPOTIFY_DISCOVERY_ANCHORS)


def _term_matches(text: str, terms: set[str] | list[str]) -> list[str]:
    return [term for term in terms if term in text]


def _is_reddit_contamination(item: RawFeedbackItem, text: str) -> tuple[bool, str]:
    if item.source != "reddit":
        return False, ""

    spotify_anchor_matches = _term_matches(text, SPOTIFY_DISCOVERY_ANCHORS | {"spotify"})
    discovery_matches = _term_matches(text, DISCOVERY_SCOPE_TERMS)
    generic_only = _term_matches(text, GENERIC_COMPLAINT_TERMS)
    subreddit = (item.metadata.subreddit or "").lower()

    if "spotify" not in subreddit and len(spotify_anchor_matches) < 1:
        return True, "reddit_missing_spotify_anchor"
    if len(discovery_matches) < 2 and not any(
        phrase in text
        for phrase in [
            "discover weekly",
            "release radar",
            "smart shuffle",
            "music discovery",
            "new music",
            "same songs",
            "same artists",
        ]
    ):
        return True, "reddit_weak_discovery_signal"
    if generic_only and len(discovery_matches) <= 1:
        return True, "reddit_generic_spotify_complaint"
    return False, ""


def score_opportunity_signal(item: RawFeedbackItem) -> float:
    text = item.text.lower()
    score = 0.0

    matches = [term for term in OPPORTUNITY_SIGNAL_TERMS if term in text]
    score += min(0.8, 0.15 * len(matches))

    if item.rating is not None:
        if item.rating <= 2:
            score += 0.4
        elif item.rating == 3:
            score += 0.2
        elif item.rating >= 5:
            score -= 0.15

    positive_matches = [term for term in POSITIVE_SIGNAL_TERMS if term in text]
    if positive_matches and not matches:
        score -= min(0.2, 0.05 * len(positive_matches))

    return max(0.0, min(score, 1.0))


def score_positive_validation(item: RawFeedbackItem) -> float:
    text = item.text.lower()
    score = 0.0

    matches = [term for term in POSITIVE_SIGNAL_TERMS if term in text]
    score += min(0.5, 0.08 * len(matches))

    if item.rating is not None:
        if item.rating >= 5:
            score += 0.4
        elif item.rating == 4:
            score += 0.25
        elif item.rating <= 2:
            score -= 0.2

    if "love" in text or "amazing" in text or "great" in text:
        score += 0.1

    return max(0.0, min(score, 1.0))


def count_request_signals(item: RawFeedbackItem) -> int:
    text = item.text.lower()
    request_terms = [
        "wish",
        "needs",
        "need",
        "should",
        "request",
        "please change",
        "more control",
        "more variety",
        "would like",
    ]
    return sum(1 for term in request_terms if term in text)


def classify_evidence_signal(item: RawFeedbackItem) -> str:
    opportunity = score_opportunity_signal(item)
    positive = score_positive_validation(item)

    if opportunity >= 0.4 and positive >= 0.25:
        return "mixed"
    if opportunity >= 0.35:
        return "pain"
    if positive >= 0.3:
        return "positive"
    return "neutral"


def score_relevance(
    item: RawFeedbackItem,
    request: AnalyzeFeedbackRequest,
) -> tuple[bool, float, str]:
    text = item.text.lower()
    included_terms = _normalize_terms(request.included_topics)
    excluded_terms = _normalize_terms(request.excluded_topics)

    if excluded_terms and any(term in text for term in excluded_terms):
        if not any(keyword in text for keyword in DEFAULT_DISCOVERY_KEYWORDS):
            return False, 0.0, "matched_excluded_topic"

    matched_included = [term for term in included_terms if term in text]
    matched_default = [term for term in DEFAULT_DISCOVERY_KEYWORDS if term in text]
    matched_scope_terms = _term_matches(text, DISCOVERY_SCOPE_TERMS)
    spotify_specific = _is_spotify_specific(item, text)
    opportunity_score = score_opportunity_signal(item)
    contaminated, contamination_reason = _is_reddit_contamination(item, text)

    if contaminated:
        return False, 0.0, contamination_reason

    if not spotify_specific:
        return False, 0.0, "not_spotify_specific"

    if not matched_included and not matched_default and len(matched_scope_terms) < 2:
        return False, 0.0, "insufficient_discovery_signal"

    if _term_matches(text, GENERIC_COMPLAINT_TERMS) and len(matched_scope_terms) < 2:
        return False, 0.0, "generic_spotify_complaint"

    score = 0.0
    if spotify_specific:
        score += 0.2
    if matched_included:
        score += min(0.7, 0.2 * len(matched_included))
    if matched_default:
        score += min(0.5, 0.1 * len(matched_default))
    if matched_scope_terms:
        score += min(0.4, 0.08 * len(matched_scope_terms))

    if any(term in text for term in DISCOVERY_CONTEXT_TERMS):
        score += 0.1

    score += 0.15 * opportunity_score

    score = min(score, 1.0)
    is_relevant = score >= 0.45

    if is_relevant:
        return True, score, "matched_discovery_scope"
    if excluded_terms and any(term in text for term in excluded_terms):
        return False, score, "matched_excluded_topic"
    return False, score, "insufficient_scope_match"


def filter_relevant_feedback(
    feedback_items: list[RawFeedbackItem],
    request: AnalyzeFeedbackRequest,
    *,
    debug: bool = False,
) -> tuple[list[RawFeedbackItem], list[str]]:
    relevant_items: list[RawFeedbackItem] = []
    debug_notes: list[str] = []

    for item in feedback_items:
        is_relevant, score, reason = score_relevance(item, request)
        if is_relevant:
            relevant_items.append(item)
        if debug:
            debug_notes.append(
                f"{item.feedback_id}: relevant={is_relevant} score={score:.2f} opportunity={score_opportunity_signal(item):.2f} reason={reason}"
            )

    return relevant_items, debug_notes
