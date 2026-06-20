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
    assert plan["google_play_review_cap"] == 200
    assert plan["app_store_review_cap"] == 200
    assert plan["app_store_max_pages"] == 4


def test_collection_plan_uses_full_mode_caps_for_longer_runtime() -> None:
    plan = _build_collection_plan(_request(300))

    assert plan["fast_mode"] is False
    assert plan["google_play_review_cap"] == 500
    assert plan["app_store_review_cap"] == 500
    assert plan["app_store_max_pages"] == 10
