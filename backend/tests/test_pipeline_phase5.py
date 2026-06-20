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
        "debug": True,
    }


def test_analyze_feedback_applies_cleaning_and_relevance(monkeypatch) -> None:
    from app.collectors.app_store import APP_STORE_NS, normalize_app_store_entry
    from app.collectors.google_play import normalize_google_play_review
    from app.collectors.reddit import ATOM_NS, normalize_reddit_entry
    from app.services import pipeline

    sample_google_play = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify recommendations keep repeating the same artists.",
                "score": 2,
                "thumbsUpCount": 3,
                "at": datetime(2026, 2, 1, 12, 0, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        ),
        normalize_google_play_review(
            {
                "reviewId": "gp_2",
                "content": "test",
                "score": 3,
                "thumbsUpCount": 0,
                "at": datetime(2026, 2, 2, 12, 0, 0),
                "reviewCreatedVersion": "9.0.1",
            }
        ),
    ]
    reddit_entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>t3_rd_1</id>
          <title>Spotify pricing is getting too expensive</title>
          <updated>2026-02-01T00:00:00+00:00</updated>
          <link href="https://www.reddit.com/r/spotify/comments/rd_1/test/" />
          <content type="html">&lt;p&gt;Billing is frustrating.&lt;/p&gt;</content>
        </entry>
        </feed>"""
    ).find("atom:entry", ATOM_NS)
    assert reddit_entry is not None
    sample_reddit = [normalize_reddit_entry(reddit_entry, "Spotify pricing")]
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
    assert body["metrics"]["total_records_collected"] == 4
    assert body["metrics"]["records_after_cleaning"] == 3
    assert body["metrics"]["records_relevant"] == 2
    assert body["metrics"]["source_distribution"]["reddit"] == 0
    assert body["metrics"]["source_distribution"]["google_play"] == 1
    assert body["metrics"]["source_distribution"]["app_store"] == 1
    assert body["source_summary"][0]["records_relevant"] == 0
    assert body["source_summary"][1]["records_relevant"] == 1
    assert body["source_summary"][2]["records_relevant"] == 1
    assert any("Phase 5 applies cleaning" in note for note in body["processing_notes"])
    quotes = body["compact_gpt_payload"]["representative_quotes"]
    assert len(quotes) >= 1
    assert any(
        phrase in quotes[0]["text"].lower()
        for phrase in ["repeating", "repetitive", "same artists"]
    )
