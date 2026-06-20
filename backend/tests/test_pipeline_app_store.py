from datetime import datetime
from xml.etree import ElementTree

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
        "success_criteria": [
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        "max_runtime_seconds": 120,
        "debug": False,
    }


def test_analyze_feedback_includes_app_store_counts(monkeypatch) -> None:
    from app.collectors.app_store import APP_STORE_NS, normalize_app_store_entry
    from app.collectors.google_play import normalize_google_play_review
    from app.collectors.reddit import normalize_reddit_entry
    from app.services import pipeline

    sample_google_play = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify helps me discover artists.",
                "score": 4,
                "thumbsUpCount": 3,
                "at": datetime(2026, 2, 1, 12, 0, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        )
    ]
    reddit_entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>t3_rd_1</id>
          <title>Discover Weekly is repetitive</title>
          <updated>2026-02-01T00:00:00+00:00</updated>
          <link href="https://www.reddit.com/r/spotify/comments/rd_1/test/" />
          <content type="html">&lt;p&gt;It keeps recommending familiar artists.&lt;/p&gt;</content>
        </entry>
        </feed>"""
    ).find("atom:entry", {"atom": "http://www.w3.org/2005/Atom"})
    assert reddit_entry is not None
    sample_reddit = [
        normalize_reddit_entry(reddit_entry, "Spotify Discover Weekly repetitive")
    ]
    app_store_entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
        <entry>
          <id>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</id>
          <title>Good discovery, but gets repetitive</title>
          <content>Release Radar is useful, but recommendations loop too much.</content>
          <updated>2026-02-10T12:00:00-07:00</updated>
          <link>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</link>
          <im:rating>3</im:rating>
          <im:version>9.2.0</im:version>
        </entry>
        </feed>"""
    ).find("atom:entry", APP_STORE_NS)
    assert app_store_entry is not None
    sample_app_store = [normalize_app_store_entry(app_store_entry)]

    monkeypatch.setattr(
        pipeline,
        "collect_google_play_reviews",
        lambda app_id: sample_google_play,
    )
    monkeypatch.setattr(
        pipeline,
        "collect_reddit_feedback",
        lambda queries: sample_reddit,
    )
    monkeypatch.setattr(
        pipeline,
        "collect_app_store_reviews",
        lambda app_id: sample_app_store,
    )

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["metrics"]["total_records_collected"] == 3
    assert body["metrics"]["source_distribution"]["app_store"] == 1
    assert body["source_summary"][2]["records_collected"] == 1
    assert body["charts_data"]["feedback_by_source"][2]["count"] == 1


def test_analyze_feedback_warns_when_app_store_collection_fails(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: [])

    def _raise_app_store(app_id):
        raise RuntimeError("app store unavailable")

    monkeypatch.setattr(pipeline, "collect_app_store_reviews", _raise_app_store)

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_success"
    assert body["processing_summary"]["source_failures"] == ["app_store"]
    assert "App Store collection failed" in body["warnings"][0]
