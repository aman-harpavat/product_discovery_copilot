from datetime import datetime

from app.collectors.google_play import collect_google_play_reviews, normalize_google_play_review


def _fake_fetcher(**kwargs):
    return (
        [
            {
                "reviewId": "gp_1",
                "content": "Spotify helps me discover new artists every week.",
                "score": 4,
                "thumbsUpCount": 7,
                "at": datetime(2026, 2, 15, 12, 0, 0),
                "reviewCreatedVersion": "9.0.1",
            },
            {
                "reviewId": "gp_2",
                "content": "Discover Weekly repeats the same songs too often.",
                "score": 2,
                "thumbsUpCount": 12,
                "at": datetime(2026, 2, 20, 12, 0, 0),
                "reviewCreatedVersion": "9.0.2",
            },
        ],
        None,
    )


def test_normalize_google_play_review_maps_fields_to_raw_feedback_schema() -> None:
    review = {
        "reviewId": "gp_123",
        "content": "Great for finding music, but recommendations get stale.",
        "score": 3,
        "thumbsUpCount": 5,
        "at": datetime(2026, 1, 10, 8, 30, 0),
        "reviewCreatedVersion": "8.9.10",
    }

    normalized = normalize_google_play_review(review, country="us")

    assert normalized.feedback_id == "fb_google_play_gp_123"
    assert normalized.source == "google_play"
    assert normalized.source_type == "review"
    assert normalized.rating == 3
    assert normalized.engagement.thumbs_up == 5
    assert normalized.metadata.app_version == "8.9.10"
    assert normalized.metadata.storefront == "google_play"
    assert normalized.metadata.country == "us"
    assert normalized.url.startswith("https://play.google.com/store/apps/details?id=")


def test_collect_google_play_reviews_filters_empty_content_and_normalizes_records() -> None:
    records = collect_google_play_reviews(fetcher=_fake_fetcher)

    assert len(records) == 2
    assert records[0].source == "google_play"
    assert records[1].feedback_id == "fb_google_play_gp_2"


def test_collect_google_play_reviews_pages_until_cap_or_exhaustion() -> None:
    calls: list[object] = []

    def _paged_fetcher(**kwargs):
        calls.append(kwargs.get("continuation_token"))
        if kwargs.get("continuation_token") is None:
            return (
                [
                    {
                        "reviewId": "gp_1",
                        "content": "First page review",
                        "score": 4,
                        "thumbsUpCount": 2,
                        "at": datetime(2026, 2, 1, 12, 0, 0),
                    }
                ],
                "token_2",
            )
        if kwargs.get("continuation_token") == "token_2":
            return (
                [
                    {
                        "reviewId": "gp_2",
                        "content": "Second page review",
                        "score": 2,
                        "thumbsUpCount": 1,
                        "at": datetime(2026, 2, 2, 12, 0, 0),
                    }
                ],
                None,
            )
        return ([], None)

    records = collect_google_play_reviews(count=2, batch_size=1, fetcher=_paged_fetcher)

    assert len(records) == 2
    assert [record.feedback_id for record in records] == [
        "fb_google_play_gp_1",
        "fb_google_play_gp_2",
    ]
    assert calls == [None, "token_2"]
