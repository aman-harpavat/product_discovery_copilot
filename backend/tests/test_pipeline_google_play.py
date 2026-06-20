from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def valid_payload() -> dict:
    return {
        "product": "Spotify",
        "research_scope": "Music Discovery",
        "research_goal": "Opportunity Discovery",
        "analysis_time_window": {"type": "relative", "value": "12_months"},
        "included_topics": ["recommendations", "music discovery", "personalization"],
        "excluded_topics": ["pricing", "billing", "podcasts"],
        "research_questions": [
            "Why do users struggle to discover new music?",
            "What are the most common frustrations with recommendations?",
            "What listening behaviors are users trying to achieve?",
            "What causes repetitive listening?",
            "Which user segments experience different discovery challenges?",
            "What unmet needs emerge consistently?",
        ],
        "success_criteria": [
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        "max_runtime_seconds": 120,
        "debug": False,
    }


def test_analyze_feedback_includes_google_play_counts(monkeypatch) -> None:
    from app.collectors.google_play import normalize_google_play_review
    from app.services import pipeline

    sample_reviews = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify discovery feels repetitive lately.",
                "score": 2,
                "thumbsUpCount": 10,
                "at": datetime(2026, 1, 5, 12, 0, 0),
                "reviewCreatedVersion": "9.1.0",
            }
        ),
        normalize_google_play_review(
            {
                "reviewId": "gp_2",
                "content": "I still find great new artists through Release Radar.",
                "score": 5,
                "thumbsUpCount": 4,
                "at": datetime(2026, 2, 7, 12, 0, 0),
                "reviewCreatedVersion": "9.1.1",
            }
        ),
    ]

    monkeypatch.setattr(
        pipeline,
        "collect_google_play_reviews",
        lambda app_id: sample_reviews,
    )
    monkeypatch.setattr(
        pipeline,
        "collect_reddit_feedback",
        lambda queries: [],
    )
    monkeypatch.setattr(
        pipeline,
        "collect_app_store_reviews",
        lambda app_id: [],
    )

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["metrics"]["total_records_collected"] == 2
    assert body["metrics"]["source_distribution"]["google_play"] == 2
    assert body["source_summary"][1]["records_collected"] == 2
    assert body["charts_data"]["feedback_by_source"][1]["count"] == 2
    assert body["charts_data"]["rating_distribution"][1]["count"] == 1
    assert body["charts_data"]["rating_distribution"][4]["count"] == 1


def test_analyze_feedback_warns_when_google_play_collection_fails(monkeypatch) -> None:
    from app.services import pipeline

    def _raiser(app_id):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", _raiser)
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_success"
    assert body["metrics"]["source_distribution"]["google_play"] == 0
    assert "Google Play collection failed" in body["warnings"][0]
