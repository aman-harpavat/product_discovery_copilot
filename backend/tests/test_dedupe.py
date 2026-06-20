from app.processing.dedupe import deduplicate_feedback_items
from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem


def _item(feedback_id: str, text: str) -> RawFeedbackItem:
    return RawFeedbackItem(
        feedback_id=feedback_id,
        source="google_play",
        source_type="review",
        date="2026-06-19T00:00:00Z",
        text=text,
        url="https://example.com",
        rating=2,
        engagement=Engagement(),
        metadata=FeedbackMetadata(storefront="google_play", country="us"),
    )


def test_deduplicate_feedback_items_removes_exact_duplicates() -> None:
    items = [
        _item("fb_1", "Spotify recommendations keep repeating the same songs."),
        _item("fb_2", "Spotify recommendations keep repeating the same songs."),
    ]

    deduped, notes, stats = deduplicate_feedback_items(items, debug=True)

    assert [item.feedback_id for item in deduped] == ["fb_1"]
    assert stats["exact_duplicates_removed"] == 1
    assert any("removed_exact_duplicate" in note for note in notes)


def test_deduplicate_feedback_items_removes_normalized_duplicates() -> None:
    items = [
        _item("fb_1", "Spotify recommendations keep repeating the same songs."),
        _item("fb_2", "  spotify recommendations keep repeating the same songs.  "),
    ]

    deduped, notes, stats = deduplicate_feedback_items(items, debug=True)

    assert [item.feedback_id for item in deduped] == ["fb_1"]
    assert stats["normalized_duplicates_removed"] == 1
    assert any("removed_normalized_duplicate" in note for note in notes)


def test_deduplicate_feedback_items_removes_near_duplicates() -> None:
    items = [
        _item("fb_1", "Spotify keeps recommending the same artists in Discover Weekly."),
        _item("fb_2", "Discover Weekly keeps recommending the same artists on Spotify."),
        _item("fb_3", "Release Radar helps me find new music."),
    ]

    deduped, notes, stats = deduplicate_feedback_items(items, debug=True, similarity_threshold=0.70)

    assert [item.feedback_id for item in deduped] == ["fb_1", "fb_3"]
    assert stats["near_duplicates_removed"] == 1
    assert any("removed_near_duplicate_of=fb_1" in note for note in notes)
