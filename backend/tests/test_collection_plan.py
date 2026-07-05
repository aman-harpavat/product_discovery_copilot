from app.schemas import AnalyzeFeedbackRequest
from app.services.pipeline import _build_collection_plan


def _request(max_runtime_seconds: int) -> AnalyzeFeedbackRequest:
    return AnalyzeFeedbackRequest(
        product="Spotify",
        research_scope="Music Discovery",
        research_goal="Opportunity Discovery",
        analysis_time_window={"type": "relative", "value": "12_months"},
        included_topics=["recommendations", "music discovery", "personalization"],
        excluded_topics=["pricing", "billing", "podcasts"],
        research_questions=[
            "Why do users struggle to discover new music?",
            "What are the most common frustrations with recommendations?",
            "What listening behaviors are users trying to achieve?",
            "What causes repetitive listening?",
            "Which user segments experience different discovery challenges?",
            "What unmet needs emerge consistently?",
        ],
        success_criteria=[
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        max_runtime_seconds=max_runtime_seconds,
        debug=False,
    )


def test_collection_plan_uses_fast_mode_caps_for_interactive_runtime() -> None:
    plan = _build_collection_plan(_request(120))

    assert plan["fast_mode"] is True
    assert plan["time_window_value"] == "12_months"
    assert plan["google_play_max_pages"] == 190
    assert plan["app_store_max_pages"] == 128
    assert plan["google_play_timeout_seconds"] == 90.0
    assert plan["app_store_timeout_seconds"] == 90.0
    assert plan["reddit_query_count"] == 3
    assert plan["reddit_max_retries"] == 1
    assert plan["reddit_max_total_seconds"] == 20.0


def test_collection_plan_uses_full_mode_caps_for_longer_runtime() -> None:
    plan = _build_collection_plan(_request(300))

    assert plan["fast_mode"] is False
    assert plan["time_window_value"] == "12_months"
    assert plan["google_play_max_pages"] == 190
    assert plan["app_store_max_pages"] == 128
    assert plan["google_play_timeout_seconds"] == 150.0
    assert plan["app_store_timeout_seconds"] == 120.0
    assert plan["reddit_query_count"] == 5
    assert plan["reddit_max_retries"] == 2
    assert plan["reddit_max_total_seconds"] == 90.0
