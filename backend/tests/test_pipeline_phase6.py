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
        "debug": True,
    }


def test_analyze_feedback_applies_deduplication(monkeypatch) -> None:
    from app.collectors.app_store import APP_STORE_NS, normalize_app_store_entry
    from app.collectors.google_play import normalize_google_play_review
    from app.collectors.reddit import ATOM_NS, normalize_reddit_entry
    from app.services import pipeline

    sample_google_play = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify keeps recommending the same artists in Discover Weekly.",
                "score": 2,
                "thumbsUpCount": 2,
                "at": datetime(2026, 2, 1, 12, 0, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        ),
        normalize_google_play_review(
            {
                "reviewId": "gp_2",
                "content": "Discover Weekly keeps recommending the same artists on Spotify.",
                "score": 2,
                "thumbsUpCount": 1,
                "at": datetime(2026, 2, 1, 12, 5, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        ),
    ]
    reddit_entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>t3_rd_1</id>
          <title>Release Radar helps me find new music</title>
          <updated>2026-02-02T00:00:00+00:00</updated>
          <link href="https://www.reddit.com/r/spotify/comments/rd_1/test/" />
          <content type="html">&lt;p&gt;Still would like more control over recommendations.&lt;/p&gt;</content>
        </entry>
        </feed>"""
    ).find("atom:entry", ATOM_NS)
    assert reddit_entry is not None
    sample_reddit = [normalize_reddit_entry(reddit_entry, "Spotify recommendations")]
    app_store_entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
        <entry>
          <id>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</id>
          <title>Discover Weekly still helps me find new music</title>
          <content>The recommendations are useful for artist discovery.</content>
          <updated>2026-02-10T12:00:00-07:00</updated>
          <link>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</link>
          <im:rating>4</im:rating>
          <im:version>9.2.0</im:version>
        </entry>
        </feed>"""
    ).find("atom:entry", APP_STORE_NS)
    assert app_store_entry is not None
    sample_app_store = [normalize_app_store_entry(app_store_entry)]

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: sample_google_play)
    monkeypatch.setattr(pipeline, "collect_reddit_feedback", lambda queries: sample_reddit)
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: sample_app_store)

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["records_relevant"] == 4
    assert body["metrics"]["records_after_deduplication"] == 3
    assert body["metrics"]["near_duplicates_removed"] == 1
    assert body["processing_summary"]["near_duplicates_removed"] == 1
    assert body["metrics"]["cluster_count"] >= 1
    assert any("removed_near_duplicate" in note for note in body["processing_notes"])
