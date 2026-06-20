from app.schemas import ClusterItem, QuoteItem
from app.services.pipeline import _compact_clusters_for_response, _truncate_text


def _cluster(index: int, quote_text: str) -> ClusterItem:
    return ClusterItem(
        cluster_id=f"cluster_{index:03d}",
        cluster_name=f"Cluster {index}",
        cluster_summary="Summary",
        cluster_tier="tier_1",
        cluster_size=10 - index,
        cluster_cohesion_score=0.42,
        frequency=10 - index,
        dominant_signal="pain",
        pain_point_evidence_count=1,
        positive_validation_count=0,
        request_signal_count=1,
        mixed_signal_flag=False,
        source_distribution={"reddit": 1, "google_play": 1, "app_store": 1},
        time_distribution={"2026-06": 3},
        representative_quotes=[
            QuoteItem(
                text=quote_text,
                source="reddit",
                url="https://www.reddit.com/r/spotify/comments/test",
                date="2026-06-20T00:00:00Z",
            )
            for _ in range(4)
        ],
        example_feedback_ids=["fb_1", "fb_2", "fb_3", "fb_4"],
        keywords=["discovery", "recommendations"],
        mapped_research_questions=["Why do users struggle to discover new music?"],
        mapped_success_criteria=["Improve meaningful music discovery"],
        repeat_listening_cause_tags=["algorithmic repetition"],
        relevance_score=1.0,
    )


def test_truncate_text_adds_ellipsis_when_needed() -> None:
    text = "a" * 400

    truncated = _truncate_text(text, 50)

    assert len(truncated) == 50
    assert truncated.endswith("...")


def test_compact_clusters_limits_cluster_payload_shape() -> None:
    clusters = [_cluster(index, "b" * 500) for index in range(1, 25)]

    compacted, applied = _compact_clusters_for_response(clusters)

    assert applied is True
    assert len(compacted) == 6
    assert all(len(cluster.representative_quotes) <= 2 for cluster in compacted)
    assert all(len(cluster.example_feedback_ids) <= 3 for cluster in compacted)
    assert all(len(cluster.representative_quotes[0].text) <= 280 for cluster in compacted)
