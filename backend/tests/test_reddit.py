from xml.etree import ElementTree

import httpx

from app.collectors.reddit import (
    ATOM_NS,
    build_reddit_aggregate_query,
    build_reddit_search_url,
    collect_reddit_feedback,
    collect_reddit_feedback_with_warnings,
    normalize_reddit_entry,
)
from app.schemas import AnalyzeFeedbackRequest
from app.services.source_discovery import build_reddit_query_seeds


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_abc123</id>
    <title>Spotify discovery feels repetitive</title>
    <updated>2026-02-01T12:00:00+00:00</updated>
    <link href="https://www.reddit.com/r/spotify/comments/abc123/test_post/" />
    <content type="html">&lt;p&gt;Discover Weekly keeps repeating familiar artists.&lt;/p&gt;</content>
  </entry>
</feed>
"""


def _fake_fetcher(url: str):
    return ATOM_FEED, {"content-type": "application/atom+xml"}


def _request() -> AnalyzeFeedbackRequest:
    return AnalyzeFeedbackRequest(
        product="Spotify",
        research_scope="Music Discovery",
        research_goal="Opportunity Discovery",
        analysis_time_window={"type": "relative", "value": "12_months"},
        included_topics=["recommendations", "Discover Weekly"],
        excluded_topics=["pricing"],
        success_criteria=[
            "Improve meaningful music discovery",
            "Reduce repetitive listening",
            "Improve recommendation relevance and novelty balance",
        ],
        max_runtime_seconds=120,
        debug=False,
    )


def test_build_reddit_query_seeds_includes_spec_queries() -> None:
    queries = build_reddit_query_seeds(_request())

    assert "Spotify recommendations repetitive" in queries
    assert "Spotify Discover Weekly repetitive" in queries
    assert "Spotify Discover Weekly" in queries
    assert len(queries) <= 5


def test_build_reddit_aggregate_query_stays_query_driven() -> None:
    aggregate = build_reddit_aggregate_query(build_reddit_query_seeds(_request()))

    assert "Spotify" in aggregate
    assert "Music" in aggregate or "recommendations" in aggregate


def test_build_reddit_search_url_encodes_query() -> None:
    url = build_reddit_search_url("Spotify music discovery")

    assert "search.rss" in url
    assert "q=Spotify+music+discovery" in url


def test_normalize_reddit_entry_maps_fields_to_raw_feedback_schema() -> None:
    root = ElementTree.fromstring(ATOM_FEED)
    entry = root.find("atom:entry", ATOM_NS)
    assert entry is not None

    normalized = normalize_reddit_entry(entry, "Spotify recommendations repetitive")

    assert normalized.feedback_id == "fb_reddit_t3_abc123"
    assert normalized.source == "reddit"
    assert normalized.source_type == "discussion"
    assert normalized.metadata.subreddit == "spotify"
    assert normalized.metadata.query_used == "Spotify recommendations repetitive"
    assert normalized.url.startswith("https://www.reddit.com/r/spotify/comments/")
    assert "Spotify discovery feels repetitive" in normalized.text


def test_collect_reddit_feedback_parses_atom_feed() -> None:
    records = collect_reddit_feedback(
        ["Spotify recommendations repetitive"],
        fetcher=_fake_fetcher,
    )

    assert len(records) == 1
    assert records[0].source == "reddit"
    assert "Discover Weekly keeps repeating familiar artists." in records[0].text


def test_collect_reddit_feedback_queries_multiple_searches_and_deduplicates() -> None:
    second_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_def456</id>
    <title>Spotify recommendations miss new artists</title>
    <updated>2026-02-02T12:00:00+00:00</updated>
    <link href="https://www.reddit.com/r/truespotify/comments/def456/test_post/" />
    <content type="html">&lt;p&gt;I want better discovery for fresh artists.&lt;/p&gt;</content>
  </entry>
</feed>
"""
    seen_urls: list[str] = []

    def _multi_fetcher(url: str):
        seen_urls.append(url)
        if "Discover+Weekly" in url:
            return second_feed, {"content-type": "application/atom+xml"}
        return ATOM_FEED, {"content-type": "application/atom+xml"}

    records = collect_reddit_feedback(
        ["Spotify recommendations repetitive", "Spotify Discover Weekly repetitive"],
        fetcher=_multi_fetcher,
    )

    assert len(records) == 2
    assert {record.feedback_id for record in records} == {
        "fb_reddit_t3_abc123",
        "fb_reddit_t3_def456",
    }
    assert len(seen_urls) == 2


def test_collect_reddit_feedback_keeps_partial_results_when_one_query_fails() -> None:
    seen_urls: list[str] = []

    def _partial_fetcher(url: str):
        seen_urls.append(url)
        if "Discover+Weekly" in url:
            request = httpx.Request("GET", url)
            response = httpx.Response(status_code=429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return ATOM_FEED, {"content-type": "application/atom+xml"}

    records, warnings = collect_reddit_feedback_with_warnings(
        ["Spotify recommendations repetitive", "Spotify Discover Weekly repetitive"],
        fetcher=_partial_fetcher,
        query_delay_seconds=0.0,
        max_retries=0,
        backoff_seconds=0.0,
        sleep_fn=lambda _: None,
    )

    assert len(records) == 1
    assert records[0].feedback_id == "fb_reddit_t3_abc123"
    assert len(warnings) == 1
    assert "continuing with partial Reddit results" in warnings[0]
    assert len(seen_urls) == 2


def test_collect_reddit_feedback_retries_rate_limited_query_then_succeeds() -> None:
    attempts = {"count": 0}

    def _retry_fetcher(url: str):
        attempts["count"] += 1
        if attempts["count"] == 1:
            request = httpx.Request("GET", url)
            response = httpx.Response(status_code=429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return ATOM_FEED, {"content-type": "application/atom+xml"}

    records, warnings = collect_reddit_feedback_with_warnings(
        ["Spotify recommendations repetitive"],
        fetcher=_retry_fetcher,
        query_delay_seconds=0.0,
        max_retries=1,
        backoff_seconds=0.0,
        sleep_fn=lambda _: None,
    )

    assert len(records) == 1
    assert warnings == []
    assert attempts["count"] == 2


def test_collect_reddit_feedback_stops_early_after_consecutive_rate_limits() -> None:
    seen_urls: list[str] = []

    def _rate_limited_fetcher(url: str):
        seen_urls.append(url)
        request = httpx.Request("GET", url)
        response = httpx.Response(status_code=429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    records, warnings = collect_reddit_feedback_with_warnings(
        [
            "Spotify recommendations repetitive",
            "Spotify Discover Weekly repetitive",
            "Spotify algorithm recommendations",
        ],
        fetcher=_rate_limited_fetcher,
        query_delay_seconds=0.0,
        max_retries=0,
        backoff_seconds=0.0,
        sleep_fn=lambda _: None,
    )

    assert records == []
    assert len(seen_urls) == 2
    assert any("stopped early after repeated rate limits" in warning for warning in warnings)
