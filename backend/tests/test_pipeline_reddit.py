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


def test_analyze_feedback_includes_reddit_counts(monkeypatch) -> None:
    from app.collectors.google_play import normalize_google_play_review
    from app.collectors.reddit import normalize_reddit_entry
    from app.services import pipeline
    from xml.etree import ElementTree

    from app.collectors.reddit import ATOM_NS

    sample_google_play = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify still helps me discover artists.",
                "score": 4,
                "thumbsUpCount": 3,
                "at": datetime(2026, 2, 1, 12, 0, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        )
    ]
    entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>t3_rd_1</id>
          <title>Discover Weekly is repetitive</title>
          <updated>2026-02-01T00:00:00+00:00</updated>
          <link href="https://www.reddit.com/r/spotify/comments/rd_1/test/" />
          <content type="html">&lt;p&gt;It keeps recommending familiar artists.&lt;/p&gt;</content>
        </entry>
        </feed>"""
    ).find("atom:entry", ATOM_NS)
    assert entry is not None
    sample_reddit = [
        normalize_reddit_entry(
            entry,
            "Spotify Discover Weekly repetitive",
        )
    ]

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
        lambda app_id: [],
    )

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["metrics"]["total_records_collected"] == 2
    assert body["metrics"]["source_distribution"]["reddit"] == 1
    assert body["metrics"]["source_distribution"]["google_play"] == 1
    assert body["source_summary"][0]["records_collected"] == 1
    assert body["charts_data"]["feedback_by_source"][0]["count"] == 1


def test_analyze_feedback_warns_when_reddit_collection_fails(monkeypatch) -> None:
    from app.services import pipeline

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: [])
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])

    def _raise_reddit(queries):
        raise RuntimeError("reddit unavailable")

    monkeypatch.setattr(pipeline, "collect_reddit_feedback", _raise_reddit)

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_success"
    assert body["processing_summary"]["source_failures"] == ["reddit"]
    assert body["processing_summary"]["source_warning_codes"]["reddit"] == ["reddit_failed"]
    assert "[reddit_failed]" in body["warnings"][0]
    assert "Reddit collection failed" in body["warnings"][0]


def test_analyze_feedback_marks_reddit_partial_when_some_results_survive(monkeypatch) -> None:
    from app.collectors.google_play import normalize_google_play_review
    from app.collectors.reddit import normalize_reddit_entry
    from app.services import pipeline
    from xml.etree import ElementTree

    from app.collectors.reddit import ATOM_NS

    sample_google_play = [
        normalize_google_play_review(
            {
                "reviewId": "gp_1",
                "content": "Spotify still helps me discover artists.",
                "score": 4,
                "thumbsUpCount": 3,
                "at": datetime(2026, 2, 1, 12, 0, 0),
                "reviewCreatedVersion": "9.0.0",
            }
        )
    ]
    entry = ElementTree.fromstring(
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>t3_rd_1</id>
          <title>Discover Weekly is repetitive</title>
          <updated>2026-02-01T00:00:00+00:00</updated>
          <link href="https://www.reddit.com/r/spotify/comments/rd_1/test/" />
          <content type="html">&lt;p&gt;It keeps recommending familiar artists.&lt;/p&gt;</content>
        </entry>
        </feed>"""
    ).find("atom:entry", ATOM_NS)
    assert entry is not None
    sample_reddit = [normalize_reddit_entry(entry, "Spotify Discover Weekly repetitive")]

    monkeypatch.setattr(pipeline, "collect_google_play_reviews", lambda app_id: sample_google_play)
    monkeypatch.setattr(
        pipeline,
        "collect_reddit_feedback",
        lambda queries: (
            sample_reddit,
            [
                "Reddit query collection failed; continuing with partial Reddit results. "
                "Query: Spotify recommendations repetitive. Reason: rate limited"
            ],
        ),
    )
    monkeypatch.setattr(pipeline, "collect_app_store_reviews", lambda app_id: [])

    response = client.post("/analyze-feedback", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["processing_summary"]["source_failures"] == []
    assert body["processing_summary"]["source_warning_codes"]["reddit"] == ["reddit_partial"]
    assert "[reddit_partial]" in body["warnings"][0]
    assert any(
        limitation["source"] == "reddit"
        for limitation in body["source_limitations"]
    )
