from app.processing.clustering import cluster_feedback_items
from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem


def _item(feedback_id: str, text: str, rating: int = 2, source: str = "google_play") -> RawFeedbackItem:
    return RawFeedbackItem(
        feedback_id=feedback_id,
        source=source,
        source_type="review" if source != "reddit" else "discussion",
        date="2026-06-19T00:00:00Z",
        text=text,
        url="https://example.com",
        rating=rating,
        engagement=Engagement(),
        metadata=FeedbackMetadata(storefront=source, country="us", subreddit="spotify"),
    )


def test_cluster_feedback_items_splits_distinct_themes() -> None:
    items = [
        _item("fb_1", "Spotify keeps recommending the same artists in Discover Weekly.", 2),
        _item("fb_2", "Discover Weekly repeats the same songs and needs more variety.", 2),
        _item("fb_3", "I love how Spotify helps me discover new artists every week.", 5),
        _item("fb_4", "Release Radar is amazing for finding new music on Fridays.", 5),
    ]

    clusters, notes = cluster_feedback_items(items, debug=True)

    assert len(clusters) >= 2
    assert any(cluster.dominant_signal == "pain" for cluster in clusters)
    assert any(cluster.dominant_signal == "positive" for cluster in clusters)
    assert any("cluster_" in note for note in notes)


def test_cluster_feedback_items_marks_mixed_signal_clusters() -> None:
    items = [
        _item("fb_1", "Spotify recommendations are repetitive and need more control.", 2),
        _item("fb_2", "I love Spotify recommendations when they work and they are amazing for discovery.", 5),
    ]

    clusters, _ = cluster_feedback_items(items)

    assert len(clusters) >= 1
    assert any(cluster.mixed_signal_flag for cluster in clusters)


def test_cluster_feedback_items_merges_similar_repetition_feedback() -> None:
    items = [
        _item("fb_1", "Spotify keeps recommending the same songs in Discover Weekly.", 2),
        _item("fb_2", "Discover Weekly repeats the same artists over and over again.", 2),
        _item("fb_3", "My recommendations are too repetitive and not fresh enough.", 2),
    ]

    clusters, _ = cluster_feedback_items(items)

    assert len(clusters) == 1
    assert clusters[0].cluster_size == 3
    assert clusters[0].cluster_cohesion_score >= 0.0
