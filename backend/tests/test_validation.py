from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def valid_payload() -> dict:
    return {
        "product": "Spotify",
        "research_scope": "Music Discovery",
        "research_goal": "Opportunity Discovery",
        "analysis_time_window": {"type": "relative", "value": "12_months"},
        "included_topics": [
            "recommendations",
            "music discovery",
            "personalization",
        ],
        "excluded_topics": ["pricing", "billing", "podcasts"],
        "success_criteria": [
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        "max_runtime_seconds": 120,
        "debug": False,
    }


def test_analyze_feedback_accepts_valid_request(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])
    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["locked_brief"]["product"] == "Spotify"
    assert len(payload["locked_brief"]["research_questions"]) == 6
    assert "source_summary" in payload
    assert "metrics" in payload
    assert "charts_data" in payload
    assert "representative_quotes" in payload
    assert "compact_gpt_payload" in payload
    assert "artifact_manifest" in payload
    assert payload["compact_gpt_payload"]["success_criteria"] == payload["locked_brief"]["success_criteria"]
    assert "source_warning_codes" in payload["processing_summary"]


def test_analyze_feedback_rejects_missing_required_field() -> None:
    payload = valid_payload()
    del payload["research_scope"]

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["error_type"] == "validation_error"
    assert "research_scope" in body["missing_fields"]


def test_analyze_feedback_rejects_malformed_time_window() -> None:
    payload = valid_payload()
    payload["analysis_time_window"] = {"type": "relative", "value": "foo"}

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["error_type"] == "validation_error"


def test_analyze_feedback_warns_when_topic_lists_are_empty(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])
    payload = valid_payload()
    payload["included_topics"] = []
    payload["excluded_topics"] = []

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body["warnings"]) >= 3
    assert any("Runtime-aware source caps were applied" in warning for warning in body["warnings"])


def test_analyze_feedback_rejects_non_spotify_product() -> None:
    payload = valid_payload()
    payload["product"] = "YouTube Music"

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["error_type"] == "validation_error"


def test_analyze_feedback_accepts_custom_research_questions(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])
    payload = valid_payload()
    payload["research_questions"] = ["What causes repeat listening loops?"]

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["locked_brief"]["research_questions"] == [
        "What causes repeat listening loops?"
    ]


def test_analyze_feedback_rejects_missing_success_criteria(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])
    payload = valid_payload()
    del payload["success_criteria"]

    response = client.post("/analyze-feedback", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert "success_criteria" in body["missing_fields"]
