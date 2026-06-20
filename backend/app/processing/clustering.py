from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from scipy import sparse

from app.processing.cleaner import normalize_text
from app.processing.relevance import (
    classify_evidence_signal,
    count_request_signals,
    score_opportunity_signal,
    score_positive_validation,
)
from app.schemas import ClusterItem, QuoteItem, RawFeedbackItem

DOMAIN_STOP_WORDS = {
    "spotify",
    "music",
    "songs",
    "song",
    "artist",
    "artists",
    "playlist",
    "playlists",
    "app",
}

MERGE_SIMILARITY_THRESHOLD = 0.15
SINGLETON_ATTACH_THRESHOLD = 0.11
MIN_THEME_OVERLAP = 1


@dataclass
class _WorkingCluster:
    member_indexes: list[int]


def cluster_feedback_items(
    feedback_items: list[RawFeedbackItem],
    *,
    debug: bool = False,
) -> tuple[list[ClusterItem], list[str]]:
    if not feedback_items:
        return [], []

    if len(feedback_items) == 1:
        return [_build_cluster(feedback_items, 0)], []

    texts = [normalize_text(item.text).lower() for item in feedback_items]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
    matrix = vectorizer.fit_transform(texts)

    dense_matrix = matrix.toarray()
    labels = _cluster_labels(dense_matrix)
    similarity_matrix = np.nan_to_num(
        cosine_similarity(matrix),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    working_clusters = _merge_cluster_groups(
        labels,
        feedback_items,
        dense_matrix,
        similarity_matrix,
    )

    clusters: list[ClusterItem] = []
    debug_notes: list[str] = []
    for idx, working_cluster in enumerate(working_clusters):
        cluster_items = [feedback_items[item_index] for item_index in working_cluster.member_indexes]
        cluster_vectors = matrix[working_cluster.member_indexes]
        cohesion = _cluster_cohesion_score(cluster_vectors)
        clusters.append(
            _build_cluster(
                cluster_items,
                idx,
                vectorizer=vectorizer,
                cluster_cohesion_score=cohesion,
            )
        )
        if debug:
            debug_notes.append(
                "cluster_"
                f"{idx + 1:03d}: size={len(cluster_items)} cohesion={cohesion:.2f} "
                f"name={clusters[-1].cluster_name}"
            )

    clusters.sort(key=lambda cluster: cluster.frequency, reverse=True)
    # Reassign IDs after sorting so top clusters are deterministic in rank order.
    for idx, cluster in enumerate(clusters, start=1):
        cluster.cluster_id = f"cluster_{idx:03d}"

    return clusters, debug_notes


def _cluster_labels(matrix: np.ndarray) -> np.ndarray:
    n_items = len(matrix)
    if n_items == 1:
        return np.array([0])
    if n_items == 2:
        similarity = cosine_similarity(matrix)[0][1]
        if similarity >= 0.12:
            return np.array([0, 0])
        return np.arange(n_items)

    model = AgglomerativeClustering(
        metric="cosine",
        linkage="average",
        distance_threshold=0.8,
        n_clusters=None,
    )
    labels = model.fit_predict(matrix)

    # If the threshold yields a single huge cluster for 3+ items, force a small split.
    if len(set(labels.tolist())) == 1 and n_items >= 4:
        forced_clusters = min(3, max(2, n_items // 2))
        model = AgglomerativeClustering(
            metric="cosine",
            linkage="average",
            n_clusters=forced_clusters,
        )
        labels = model.fit_predict(matrix)

    return labels


def _merge_cluster_groups(
    labels: np.ndarray,
    items: list[RawFeedbackItem],
    matrix: np.ndarray,
    similarity_matrix: np.ndarray,
) -> list[_WorkingCluster]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        grouped[int(label)].append(index)

    clusters = [_WorkingCluster(member_indexes=indexes[:]) for _, indexes in sorted(grouped.items())]
    changed = True
    while changed and len(clusters) > 1:
        changed = False
        best_pair: tuple[int, int] | None = None
        best_score = -1.0
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                score = _cluster_pair_similarity(
                    clusters[left],
                    clusters[right],
                    items,
                    matrix,
                    similarity_matrix,
                )
                if score > best_score:
                    best_score = score
                    best_pair = (left, right)
        if best_pair and best_score >= MERGE_SIMILARITY_THRESHOLD:
            left, right = best_pair
            merged = sorted(
                clusters[left].member_indexes + clusters[right].member_indexes
            )
            clusters[left] = _WorkingCluster(member_indexes=merged)
            del clusters[right]
            changed = True

    singleton_indexes = [
        cluster_index
        for cluster_index, cluster in enumerate(clusters)
        if len(cluster.member_indexes) == 1
    ]
    for cluster_index in sorted(singleton_indexes, reverse=True):
        singleton = clusters[cluster_index]
        best_target = None
        best_score = -1.0
        for target_index, candidate in enumerate(clusters):
            if target_index == cluster_index:
                continue
            score = _cluster_pair_similarity(
                singleton,
                candidate,
                items,
                matrix,
                similarity_matrix,
            )
            if score > best_score:
                best_score = score
                best_target = target_index
        if best_target is not None and best_score >= SINGLETON_ATTACH_THRESHOLD:
            target_members = sorted(
                clusters[best_target].member_indexes + singleton.member_indexes
            )
            clusters[best_target] = _WorkingCluster(member_indexes=target_members)
            del clusters[cluster_index]

    return sorted(clusters, key=lambda cluster: (-len(cluster.member_indexes), cluster.member_indexes[0]))


def _cluster_pair_similarity(
    left: _WorkingCluster,
    right: _WorkingCluster,
    items: list[RawFeedbackItem],
    matrix: np.ndarray,
    similarity_matrix: np.ndarray,
) -> float:
    left_indexes = left.member_indexes
    right_indexes = right.member_indexes
    pairwise = similarity_matrix[np.ix_(left_indexes, right_indexes)]
    avg_similarity = float(pairwise.mean()) if pairwise.size else 0.0

    left_keywords = set(_surface_terms([items[index].text for index in left_indexes]))
    right_keywords = set(_surface_terms([items[index].text for index in right_indexes]))
    overlap = len(left_keywords & right_keywords)
    overlap_bonus = 0.05 * min(overlap, 3) if overlap >= MIN_THEME_OVERLAP else 0.0

    same_signal_bonus = 0.04 if _dominant_item_signal(items, left_indexes) == _dominant_item_signal(items, right_indexes) else 0.0
    thematic_bonus = 0.08 if _shares_repeat_theme(items, left_indexes, right_indexes) else 0.0
    return avg_similarity + overlap_bonus + same_signal_bonus + thematic_bonus


def _surface_terms(texts: list[str]) -> list[str]:
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
    matrix = vectorizer.fit_transform(texts)
    scores = np.asarray(matrix.mean(axis=0)).ravel()
    features = vectorizer.get_feature_names_out()
    ranked: list[str] = []
    for index in np.argsort(scores)[::-1]:
        term = features[index]
        if term in ENGLISH_STOP_WORDS or term in DOMAIN_STOP_WORDS:
            continue
        if any(stop in term.split() for stop in DOMAIN_STOP_WORDS):
            continue
        ranked.append(term)
        if len(ranked) == 6:
            break
    return ranked


def _dominant_item_signal(items: list[RawFeedbackItem], indexes: list[int]) -> str:
    counts = Counter(classify_evidence_signal(items[index]) for index in indexes)
    return _dominant_signal(counts)


def _shares_repeat_theme(
    items: list[RawFeedbackItem],
    left_indexes: list[int],
    right_indexes: list[int],
) -> bool:
    theme_terms = [
        "recommend",
        "discover weekly",
        "repet",
        "same songs",
        "same artists",
        "fresh",
        "variety",
    ]
    left_text = " ".join(items[index].text.lower() for index in left_indexes)
    right_text = " ".join(items[index].text.lower() for index in right_indexes)
    left_matches = sum(1 for term in theme_terms if term in left_text)
    right_matches = sum(1 for term in theme_terms if term in right_text)
    return left_matches >= 2 and right_matches >= 2


def _cluster_cohesion_score(cluster_vectors: sparse.spmatrix) -> float:
    if cluster_vectors.shape[0] <= 1:
        return 0.0
    similarity = np.nan_to_num(
        cosine_similarity(cluster_vectors),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    upper_triangle = similarity[np.triu_indices(cluster_vectors.shape[0], k=1)]
    if upper_triangle.size == 0:
        return 0.0
    return round(float(upper_triangle.mean()), 3)


def _build_cluster(
    items: list[RawFeedbackItem],
    index: int,
    *,
    vectorizer: TfidfVectorizer | None = None,
    cluster_cohesion_score: float = 0.0,
) -> ClusterItem:
    name_keywords = _cluster_keywords(items, vectorizer=vectorizer)
    signal_counts = Counter(classify_evidence_signal(item) for item in items)
    dominant_signal = _dominant_signal(signal_counts)
    request_count = sum(count_request_signals(item) for item in items)
    quotes = _representative_quotes(items)

    return ClusterItem(
        cluster_id=f"cluster_{index + 1:03d}",
        cluster_name=_cluster_name(name_keywords, dominant_signal),
        cluster_summary=_cluster_summary(items, name_keywords, signal_counts),
        cluster_size=len(items),
        cluster_cohesion_score=cluster_cohesion_score,
        frequency=len(items),
        dominant_signal=dominant_signal,
        pain_point_evidence_count=signal_counts.get("pain", 0),
        positive_validation_count=signal_counts.get("positive", 0),
        request_signal_count=request_count,
        mixed_signal_flag=(
            signal_counts.get("pain", 0) > 0 and signal_counts.get("positive", 0) > 0
        )
        or signal_counts.get("mixed", 0) > 0,
        source_distribution=_source_distribution(items),
        time_distribution=_time_distribution(items),
        representative_quotes=quotes,
        example_feedback_ids=[item.feedback_id for item in items[:5]],
        keywords=name_keywords,
        relevance_score=1.0,
    )


def _cluster_keywords(
    items: list[RawFeedbackItem],
    *,
    vectorizer: TfidfVectorizer | None = None,
) -> list[str]:
    texts = [normalize_text(item.text).lower() for item in items]
    local_vectorizer = vectorizer or TfidfVectorizer(
        ngram_range=(1, 2), min_df=1, stop_words="english"
    )
    matrix = local_vectorizer.fit_transform(texts)
    scores = np.asarray(matrix.mean(axis=0)).ravel()
    features = local_vectorizer.get_feature_names_out()

    ranked: list[str] = []
    for index in np.argsort(scores)[::-1]:
        term = features[index]
        if term in ENGLISH_STOP_WORDS or term in DOMAIN_STOP_WORDS:
            continue
        if any(stop in term.split() for stop in DOMAIN_STOP_WORDS):
            continue
        ranked.append(term)
        if len(ranked) == 3:
            break

    return ranked or ["general discovery"]


def _dominant_signal(signal_counts: Counter) -> str:
    if signal_counts.get("pain", 0) > signal_counts.get("positive", 0):
        return "pain"
    if signal_counts.get("positive", 0) > signal_counts.get("pain", 0):
        return "positive"
    return "mixed"


def _cluster_name(keywords: list[str], dominant_signal: str) -> str:
    core = keywords[0].title()
    if dominant_signal == "pain":
        return f"{core} frustrations"
    if dominant_signal == "positive":
        return f"{core} works well"
    return f"{core} mixed signals"


def _cluster_summary(
    items: list[RawFeedbackItem],
    keywords: list[str],
    signal_counts: Counter,
) -> str:
    if signal_counts.get("pain", 0) > signal_counts.get("positive", 0):
        return (
            f"Users repeatedly describe pain points related to {', '.join(keywords[:2])}, "
            "including dissatisfaction, missing control, or repetitive discovery behavior."
        )
    if signal_counts.get("positive", 0) > signal_counts.get("pain", 0):
        return (
            f"Users frequently validate what works well in {', '.join(keywords[:2])}, "
            "while offering lighter improvement signals."
        )
    return (
        f"Users discuss {', '.join(keywords[:2])} with mixed evidence, combining positive validation "
        "and dissatisfaction that should temper later opportunity weighting."
    )


def _representative_quotes(items: list[RawFeedbackItem]) -> list[QuoteItem]:
    ranked = sorted(
        items,
        key=lambda item: (
            score_opportunity_signal(item),
            score_positive_validation(item),
            max(
                item.engagement.thumbs_up,
                item.engagement.score,
                item.engagement.comments,
            ),
        ),
        reverse=True,
    )
    return [
        QuoteItem(text=item.text, source=item.source, url=item.url, date=item.date)
        for item in ranked[:5]
    ]


def _source_distribution(items: list[RawFeedbackItem]) -> dict[str, int]:
    counts = {"reddit": 0, "google_play": 0, "app_store": 0}
    for item in items:
        if item.source in counts:
            counts[item.source] += 1
    return counts


def _time_distribution(items: list[RawFeedbackItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        month = item.date[:7]
        counts[month] = counts.get(month, 0) + 1
    return dict(sorted(counts.items()))
