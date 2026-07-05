from xml.etree import ElementTree

import httpx

from app.collectors.app_store import (
    APP_STORE_NS,
    build_app_store_reviews_url,
    collect_app_store_reviews,
    normalize_app_store_entry,
)


APP_STORE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
  <entry>
    <id>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</id>
    <title>Good discovery, but gets repetitive</title>
    <content>Release Radar is useful, but recommendations loop too much.</content>
    <updated>2026-02-10T12:00:00-07:00</updated>
    <link>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=1001</link>
    <im:rating>3</im:rating>
    <im:version>9.2.0</im:version>
  </entry>
</feed>
"""


def _fake_fetcher(url: str) -> str:
    return APP_STORE_FEED


def test_build_app_store_reviews_url_uses_public_rss_feed() -> None:
    url = build_app_store_reviews_url()

    assert "itunes.apple.com" in url
    assert "customerreviews" in url
    assert "id=324684580" in url


def test_build_app_store_reviews_url_supports_page_iteration() -> None:
    url = build_app_store_reviews_url(page=2)

    assert "page=2/" in url


def test_normalize_app_store_entry_maps_fields_to_raw_feedback_schema() -> None:
    root = ElementTree.fromstring(APP_STORE_FEED)
    entry = root.find("atom:entry", APP_STORE_NS)
    assert entry is not None

    normalized = normalize_app_store_entry(entry)

    assert normalized.source == "app_store"
    assert normalized.source_type == "review"
    assert normalized.rating == 3
    assert normalized.metadata.app_version == "9.2.0"
    assert normalized.metadata.storefront == "app_store"
    assert normalized.metadata.country == "us"
    assert "Good discovery, but gets repetitive" in normalized.text


def test_collect_app_store_reviews_parses_feed() -> None:
    records = collect_app_store_reviews(fetcher=_fake_fetcher)

    assert len(records) == 1
    assert records[0].source == "app_store"
    assert records[0].feedback_id.startswith("fb_app_store_")
    assert records[0].url.startswith("https://itunes.apple.com/us/review")


def test_collect_app_store_reviews_pages_until_limit() -> None:
    page_one = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
  <entry>
    <id>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=2001</id>
    <title>Page one</title>
    <content>One</content>
    <updated>2026-02-10T12:00:00-07:00</updated>
    <link>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=2001</link>
    <im:rating>4</im:rating>
  </entry>
</feed>
"""
    page_two = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
  <entry>
    <id>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=2002</id>
    <title>Page two</title>
    <content>Two</content>
    <updated>2026-02-11T12:00:00-07:00</updated>
    <link>https://itunes.apple.com/us/review?id=324684580&amp;reviewId=2002</link>
    <im:rating>2</im:rating>
  </entry>
</feed>
"""
    seen_urls: list[str] = []

    def _paged_fetcher(url: str) -> str:
        seen_urls.append(url)
        if "page=2/" in url:
            return page_two
        if "page=3/" in url:
            return """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss"></feed>"""
        return page_one

    records = collect_app_store_reviews(limit=2, max_pages=3, fetcher=_paged_fetcher)

    assert len(records) == 2
    assert [record.feedback_id for record in records] == [
        "fb_app_store_2001",
        "fb_app_store_2002",
    ]
    assert any("page=2/" in url for url in seen_urls)


def test_collect_app_store_reviews_preserves_partial_results_on_pagination_boundary() -> None:
    seen_urls: list[str] = []

    def _boundary_fetcher(url: str) -> str:
        seen_urls.append(url)
        if "page=11/" in url:
            request = httpx.Request("GET", url)
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError(
                "boundary",
                request=request,
                response=response,
            )
        page_number = 1
        if "page=" in url:
            page_number = int(url.split("page=")[1].split("/")[0])
        return APP_STORE_FEED.replace("reviewId=1001", f"reviewId={1000 + page_number}")

    records = collect_app_store_reviews(
        limit=None,
        max_pages=12,
        fetcher=_boundary_fetcher,
    )

    assert len(records) == 10
    assert any("page=11/" in url for url in seen_urls)
