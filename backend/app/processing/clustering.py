from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from scipy import sparse
from scipy.sparse.csgraph import connected_components

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

EDGE_SIMILARITY_THRESHOLD = 0.16
OPPOSING_SIGNAL_EDGE_THRESHOLD = 0.17
MERGE_SIMILARITY_THRESHOLD = 0.13
SINGLETON_ATTACH_THRESHOLD = 0.10
MIN_THEME_OVERLAP = 1


@dataclass
class _WorkingCluster:
    member_indexes: list[int]
    keyword_set: set[str]
    dominant_signal: str


def cluster_feedback_items(
    feedback_items: list[RawFeedbackItem],
    *,
    debug: bool = False,
) -> tuple[list[ClusterItem], list[str]]:
    if not feedback_items:
        return [], []

    if len(feedback_items) == 1:
        return [_build_cluster(feedback_items, 0)], []

    texts = [normalize_text(item.text).lower() or "general discovery feedback" for item in feedback_items]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
    matrix = vectorizer.fit_transform(texts)
    similarity_matrix = _similarity_matrix(matrix)
    labels = _cluster_labels(feedback_items, similarity_matrix)
    working_clusters = _merge_cluster_groups(
        labels,
        feedback_items,
        vectorizer,
        matrix,
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

def _cluster_labels(
    items: list[RawFeedbackItem],
    similarity_matrix: sparse.csr_matrix,
) -> np.ndarray:
    n_items = len(items)
    if n_items == 1:
        return np.array([0], dtype=int)
    if n_items == 2:
        similarity = _pair_similarity(similarity_matrix, 0, 1)
        if similarity >= 0.17 or _record_edge_allowed(items[0], items[1], similarity):
            return np.array([0, 0], dtype=int)
        return np.arange(n_items, dtype=int)

    adjacency = _threshold_similarity_graph(items, similarity_matrix)
    _, labels = connected_components(adjacency, directed=False, return_labels=True)
    return labels


def _merge_cluster_groups(
    labels: np.ndarray,
    items: list[RawFeedbackItem],
    vectorizer: TfidfVectorizer,
    matrix: sparse.csr_matrix,
    similarity_matrix: sparse.csr_matrix,
) -> list[_WorkingCluster]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        grouped[int(label)].append(index)

    clusters = [
        _make_working_cluster(indexes, items, vectorizer, matrix)
        for _, indexes in sorted(grouped.items())
    ]
    clusters = _attach_targeted_singletons(
        clusters,
        items,
        vectorizer,
        matrix,
        similarity_matrix,
    )

    return sorted(
        clusters,
        key=lambda cluster: (-len(cluster.member_indexes), cluster.member_indexes[0]),
    )


def _cluster_pair_similarity(
    left: _WorkingCluster,
    right: _WorkingCluster,
    similarity_matrix: sparse.csr_matrix,
) -> float:
    left_indexes = left.member_indexes
    right_indexes = right.member_indexes
    avg_similarity = _average_cross_similarity(similarity_matrix, left_indexes, right_indexes)

    overlap = len(left.keyword_set & right.keyword_set)
    overlap_bonus = 0.05 * min(overlap, 3) if overlap >= MIN_THEME_OVERLAP else 0.0

    same_signal_bonus = 0.04 if left.dominant_signal == right.dominant_signal else 0.0
    left_repeat_terms = _repeat_theme_terms(left.keyword_set)
    right_repeat_terms = _repeat_theme_terms(right.keyword_set)
    repeat_overlap = len(left_repeat_terms & right_repeat_terms)
    thematic_bonus = 0.08 if repeat_overlap >= 1 else 0.0
    same_repeat_family_bonus = 0.09 if left_repeat_terms and right_repeat_terms else 0.0
    opposing_penalty = 0.08 if _signals_are_opposed(left.dominant_signal, right.dominant_signal) else 0.0
    return (
        avg_similarity
        + overlap_bonus
        + same_signal_bonus
        + thematic_bonus
        + same_repeat_family_bonus
        - opposing_penalty
    )


def _attach_targeted_singletons(
    clusters: list[_WorkingCluster],
    items: list[RawFeedbackItem],
    vectorizer: TfidfVectorizer,
    matrix: sparse.csr_matrix,
    similarity_matrix: sparse.csr_matrix,
) -> list[_WorkingCluster]:
    if not clusters:
        return clusters

    cluster_by_item: dict[int, int] = {}
    keyword_index: defaultdict[str, set[int]] = defaultdict(set)
    repeat_index: defaultdict[str, set[int]] = defaultdict(set)
    active_clusters: set[int] = set()

    def register(cluster_index: int) -> None:
        cluster = clusters[cluster_index]
        active_clusters.add(cluster_index)
        for item_index in cluster.member_indexes:
            cluster_by_item[item_index] = cluster_index
        for keyword in cluster.keyword_set:
            keyword_index[keyword].add(cluster_index)
        for repeat_term in _repeat_theme_terms(cluster.keyword_set):
            repeat_index[repeat_term].add(cluster_index)

    def unregister(cluster_index: int) -> None:
        if cluster_index not in active_clusters:
            return
        cluster = clusters[cluster_index]
        active_clusters.discard(cluster_index)
        for item_index in cluster.member_indexes:
            cluster_by_item.pop(item_index, None)
        for keyword in cluster.keyword_set:
            keyword_index[keyword].discard(cluster_index)
            if not keyword_index[keyword]:
                keyword_index.pop(keyword, None)
        for repeat_term in _repeat_theme_terms(cluster.keyword_set):
            repeat_index[repeat_term].discard(cluster_index)
            if not repeat_index[repeat_term]:
                repeat_index.pop(repeat_term, None)

    for cluster_index in range(len(clusters)):
        register(cluster_index)

    singleton_indexes = [
        cluster_index
        for cluster_index, cluster in enumerate(clusters)
        if len(cluster.member_indexes) == 1
    ]

    for cluster_index in singleton_indexes:
        if cluster_index not in active_clusters:
            continue
        singleton = clusters[cluster_index]
        candidate_indexes = _candidate_cluster_indexes(
            singleton,
            cluster_index,
            clusters,
            cluster_by_item,
            keyword_index,
            repeat_index,
            similarity_matrix,
        )
        if not candidate_indexes:
            continue

        best_target = None
        best_score = -1.0
        for target_index in candidate_indexes:
            score = _cluster_pair_similarity(
                singleton,
                clusters[target_index],
                similarity_matrix,
            )
            if score > best_score:
                best_score = score
                best_target = target_index

        if best_target is None or best_score < SINGLETON_ATTACH_THRESHOLD:
            continue

        merged_members = sorted(
            clusters[best_target].member_indexes + singleton.member_indexes
        )
        unregister(best_target)
        unregister(cluster_index)
        clusters[best_target] = _make_working_cluster(
            merged_members,
            items,
            vectorizer,
            matrix,
        )
        register(best_target)

    return [clusters[index] for index in sorted(active_clusters)]


def _candidate_cluster_indexes(
    singleton: _WorkingCluster,
    cluster_index: int,
    clusters: list[_WorkingCluster],
    cluster_by_item: dict[int, int],
    keyword_index: dict[str, set[int]],
    repeat_index: dict[str, set[int]],
    similarity_matrix: sparse.csr_matrix,
) -> list[int]:
    item_index = singleton.member_indexes[0]
    candidates: set[int] = set()

    row = similarity_matrix.getrow(item_index)
    neighbor_order = np.argsort(row.data)[::-1] if row.data.size else np.array([], dtype=int)
    for position in neighbor_order[:15]:
        neighbor_item = int(row.indices[position])
        target_cluster_index = cluster_by_item.get(neighbor_item)
        if target_cluster_index is None or target_cluster_index == cluster_index:
            continue
        candidates.add(target_cluster_index)

    for keyword in singleton.keyword_set:
        for target_cluster_index in keyword_index.get(keyword, set()):
            if target_cluster_index != cluster_index:
                candidates.add(target_cluster_index)

    for repeat_term in _repeat_theme_terms(singleton.keyword_set):
        for target_cluster_index in repeat_index.get(repeat_term, set()):
            if target_cluster_index != cluster_index:
                candidates.add(target_cluster_index)

    return sorted(candidates, key=lambda index: (-len(clusters[index].member_indexes), index))


def _make_working_cluster(
    member_indexes: list[int],
    items: list[RawFeedbackItem],
    vectorizer: TfidfVectorizer,
    matrix: sparse.csr_matrix,
) -> _WorkingCluster:
    keywords = set(_cluster_terms_from_indexes(member_indexes, vectorizer, matrix, limit=6))
    dominant_signal = _dominant_item_signal(items, member_indexes)
    return _WorkingCluster(
        member_indexes=member_indexes,
        keyword_set=keywords,
        dominant_signal=dominant_signal,
    )


def _dominant_item_signal(items: list[RawFeedbackItem], indexes: list[int]) -> str:
    counts = Counter(classify_evidence_signal(items[index]) for index in indexes)
    return _dominant_signal(counts)


def _similarity_matrix(matrix: sparse.csr_matrix) -> sparse.csr_matrix:
    similarity = (matrix @ matrix.T).tocsr()
    similarity.setdiag(0.0)
    similarity.eliminate_zeros()
    return similarity


def _threshold_similarity_graph(
    items: list[RawFeedbackItem],
    similarity_matrix: sparse.csr_matrix,
) -> sparse.csr_matrix:
    coo = similarity_matrix.tocoo()
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for row, col, value in zip(coo.row, coo.col, coo.data):
        if row >= col:
            continue
        score = float(value)
        if _record_edge_allowed(items[row], items[col], score):
            rows.extend([row, col])
            cols.extend([col, row])
            data.extend([1.0, 1.0])
    size = len(items)
    if not rows:
        return sparse.identity(size, dtype=float, format="csr")
    graph = sparse.csr_matrix((data, (rows, cols)), shape=(size, size))
    graph = graph + sparse.identity(size, dtype=float, format="csr")
    graph.eliminate_zeros()
    return graph


def _record_edge_allowed(left: RawFeedbackItem, right: RawFeedbackItem, similarity: float) -> bool:
    left_signal = classify_evidence_signal(left)
    right_signal = classify_evidence_signal(right)
    threshold = EDGE_SIMILARITY_THRESHOLD
    if _signals_are_opposed(left_signal, right_signal):
        threshold = OPPOSING_SIGNAL_EDGE_THRESHOLD
    return similarity >= threshold


def _signals_are_opposed(left_signal: str, right_signal: str) -> bool:
    return {left_signal, right_signal} == {"pain", "positive"}


def _pair_similarity(similarity_matrix: sparse.csr_matrix, left: int, right: int) -> float:
    return float(similarity_matrix[left, right])


def _average_cross_similarity(
    similarity_matrix: sparse.csr_matrix,
    left_indexes: list[int],
    right_indexes: list[int],
) -> float:
    cross = similarity_matrix[left_indexes][:, right_indexes]
    comparisons = cross.shape[0] * cross.shape[1]
    if comparisons == 0:
        return 0.0
    return float(cross.sum()) / comparisons


def _repeat_theme_terms(keywords: set[str]) -> set[str]:
    theme_markers = {
        "recommend",
        "discover weekly",
        "repet",
        "same songs",
        "same artists",
        "fresh",
        "variety",
        "novelty",
        "release radar",
    }
    matched: set[str] = set()
    for keyword in keywords:
        if any(marker in keyword for marker in theme_markers):
            matched.add(keyword)
    return matched


def _cluster_cohesion_score(cluster_vectors: sparse.spmatrix) -> float:
    if cluster_vectors.shape[0] <= 1:
        return 0.0
    similarity = (cluster_vectors @ cluster_vectors.T).toarray()
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
    if vectorizer is None:
        local_vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, stop_words="english"
        )
        matrix = local_vectorizer.fit_transform(texts)
        return _rank_terms_from_matrix(matrix, local_vectorizer, limit=3)

    matrix = vectorizer.transform(texts)
    return _rank_terms_from_matrix(matrix, vectorizer, limit=3)


def _cluster_terms_from_indexes(
    indexes: list[int],
    vectorizer: TfidfVectorizer,
    matrix: sparse.csr_matrix,
    *,
    limit: int,
) -> list[str]:
    subset = matrix[indexes]
    return _rank_terms_from_matrix(subset, vectorizer, limit=limit)


def _rank_terms_from_matrix(
    matrix: sparse.spmatrix,
    vectorizer: TfidfVectorizer,
    *,
    limit: int,
) -> list[str]:
    if matrix.shape[1] == 0:
        return ["general discovery"]
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
        if len(ranked) == limit:
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
