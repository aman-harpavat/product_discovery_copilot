from app.processing.cleaner import clean_feedback_items
from app.processing.relevance import (
    filter_relevant_feedback,
    score_opportunity_signal,
    score_relevance,
)
from app.services.pipeline import _split_feedback_by_time_window
from app.schemas import AnalyzeFeedbackRequest, Engagement, FeedbackMetadata, RawFeedbackItem


def _request() -> AnalyzeFeedbackRequest:
    return AnalyzeFeedbackRequest(
        product="Spotify",
        research_scope="Music Discovery",
        research_goal="Opportunity Discovery",
        analysis_time_window={"type": "relative", "value": "12_months"},
        included_topics=["recommendations", "Discover Weekly", "personalization"],
        excluded_topics=["pricing", "billing", "podcasts"],
        success_criteria=[
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        max_runtime_seconds=120,
        debug=False,
    )


def _item(feedback_id: str, text: str) -> RawFeedbackItem:
    return RawFeedbackItem(
        feedback_id=feedback_id,
        source="reddit",
        source_type="discussion",
        date="2026-02-01T00:00:00Z",
        text=text,
        url="https://example.com",
        rating=None,
        engagement=Engagement(),
        metadata=FeedbackMetadata(subreddit="spotify", query_used="Spotify Music Discovery"),
    )


def test_clean_feedback_items_removes_empty_and_noise_records() -> None:
    items = [
        _item("fb_1", "   Spotify recommendations keep repeating the same songs.   "),
        _item("fb_2", "test"),
        _item("fb_3", "!!!"),
    ]

    cleaned = clean_feedback_items(items)

    assert len(cleaned) == 1
    assert cleaned[0].text == "Spotify recommendations keep repeating the same songs."


def test_score_relevance_includes_discovery_feedback() -> None:
    relevant, score, reason = score_relevance(
        _item("fb_1", "Spotify recommendations and Discover Weekly feel repetitive."),
        _request(),
    )

    assert relevant is True
    assert score >= 0.25
    assert reason == "matched_discovery_scope"


def test_score_relevance_excludes_out_of_scope_feedback() -> None:
    relevant, score, reason = score_relevance(
        _item("fb_2", "Spotify pricing is too high and billing is confusing."),
        _request(),
    )

    assert relevant is False
    assert reason == "matched_excluded_topic"


def test_filter_relevant_feedback_keeps_only_scope_relevant_items() -> None:
    items = [
        _item("fb_1", "Spotify recommendations keep surfacing the same artists."),
        _item("fb_2", "Billing support is slow and pricing is too high."),
        _item("fb_3", "Discover Weekly helps me find new music."),
    ]

    relevant_items, debug_notes = filter_relevant_feedback(items, _request(), debug=True)

    assert [item.feedback_id for item in relevant_items] == ["fb_1", "fb_3"]
    assert len(debug_notes) == 3


def test_score_relevance_rejects_generic_music_chatter_without_spotify_anchor() -> None:
    generic_item = RawFeedbackItem(
        feedback_id="fb_generic",
        source="reddit",
        source_type="discussion",
        date="2026-02-01T00:00:00Z",
        text="I am always listening to music and recommendations are always welcome.",
        url="https://example.com",
        rating=None,
        engagement=Engagement(),
        metadata=FeedbackMetadata(subreddit="MakeFriendsOver30", query_used="Spotify music discovery"),
    )

    relevant, score, reason = score_relevance(generic_item, _request())

    assert relevant is False
    assert score == 0.0
    assert reason == "reddit_missing_spotify_anchor"


def test_opportunity_signal_scores_problem_feedback_above_praise() -> None:
    complaint = _item(
        "fb_problem",
        "Spotify recommendations are repetitive and I wish I had more control.",
    )
    praise = _item(
        "fb_praise",
        "Spotify recommendations are amazing and I love discovering music here.",
    )

    assert score_opportunity_signal(complaint) > score_opportunity_signal(praise)


def test_score_relevance_rejects_reddit_contamination_story_post() -> None:
    contaminated = RawFeedbackItem(
        feedback_id="fb_story",
        source="reddit",
        source_type="discussion",
        date="2026-02-01T00:00:00Z",
        text="A long unrelated story about a spaceship and a river with no product context at all.",
        url="https://example.com",
        rating=None,
        engagement=Engagement(),
        metadata=FeedbackMetadata(subreddit="epicmaker", query_used="Spotify recommendations repetitive"),
    )

    relevant, score, reason = score_relevance(contaminated, _request())

    assert relevant is False
    assert score == 0.0
    assert reason == "reddit_missing_spotify_anchor"


def test_split_feedback_by_time_window_excludes_old_records() -> None:
    items = [
        _item("fb_recent", "Spotify recommendations keep surfacing the same artists."),
        RawFeedbackItem(
            feedback_id="fb_old",
            source="reddit",
            source_type="discussion",
            date="2024-01-01T00:00:00Z",
            text="Spotify recommendations were repetitive.",
            url="https://example.com",
            rating=None,
            engagement=Engagement(),
            metadata=FeedbackMetadata(subreddit="spotify", query_used="Spotify recommendations repetitive"),
        ),
    ]

    in_window, out_of_window = _split_feedback_by_time_window(items, _request())

    assert [item.feedback_id for item in in_window] == ["fb_recent"]
    assert [item.feedback_id for item in out_of_window] == ["fb_old"]
