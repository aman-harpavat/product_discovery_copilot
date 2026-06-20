from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx

from app.config import settings
from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem

DEFAULT_APP_STORE_APP_ID = "324684580"
DEFAULT_APP_STORE_COUNTRY = "us"
DEFAULT_APP_STORE_PAGE_SIZE = 50
DEFAULT_APP_STORE_MAX_PAGES = 10
DEFAULT_APP_STORE_LIMIT = DEFAULT_APP_STORE_PAGE_SIZE * DEFAULT_APP_STORE_MAX_PAGES
DEFAULT_APP_STORE_USER_AGENT = "ai-product-discovery-copilot/0.1"
APP_STORE_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "im": "http://itunes.apple.com/rss",
}

AppStoreFetcher = Callable[[str], str]
logger = logging.getLogger(__name__)


def _default_fetcher(url: str) -> str:
    response = httpx.get(
        url,
        headers={"User-Agent": DEFAULT_APP_STORE_USER_AGENT},
        timeout=settings.outbound_request_timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def build_app_store_reviews_url(
    app_id: str = DEFAULT_APP_STORE_APP_ID,
    country: str = DEFAULT_APP_STORE_COUNTRY,
    page: int = 1,
) -> str:
    page_segment = f"page={page}/" if page > 1 else ""
    return (
        "https://itunes.apple.com/"
        f"{country}/rss/customerreviews/{page_segment}id={app_id}/sortby=mostrecent/xml"
    )


def _parse_rating(entry: ElementTree.Element) -> int | None:
    rating_text = entry.findtext("im:rating", default="", namespaces=APP_STORE_NS)
    try:
        return int(rating_text)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_review_id(entry_id: str) -> str:
    if not entry_id:
        return "unknown"

    query_values = parse_qs(urlparse(entry_id).query)
    review_ids = query_values.get("reviewId")
    if review_ids and review_ids[0].strip():
        return review_ids[0].strip()

    return entry_id.rstrip("/").split("/")[-1] or "unknown"


def normalize_app_store_entry(
    entry: ElementTree.Element,
    *,
    country: str = DEFAULT_APP_STORE_COUNTRY,
    app_id: str = DEFAULT_APP_STORE_APP_ID,
) -> RawFeedbackItem:
    entry_id = (
        entry.findtext("atom:id", default="", namespaces=APP_STORE_NS).strip()
        or "unknown"
    )
    title = (
        entry.findtext("atom:title", default="", namespaces=APP_STORE_NS).strip()
    )
    content = (
        entry.findtext("atom:content", default="", namespaces=APP_STORE_NS).strip()
    )
    parts = [part for part in [title, content] if part]
    url = (
        entry.findtext("atom:link", default="", namespaces=APP_STORE_NS).strip()
        or build_app_store_reviews_url(app_id=app_id, country=country)
    )
    updated = _parse_date(
        entry.findtext("atom:updated", default="", namespaces=APP_STORE_NS)
    )
    app_version = entry.findtext(
        "im:version", default="", namespaces=APP_STORE_NS
    ).strip()

    return RawFeedbackItem(
        feedback_id=f"fb_app_store_{_extract_review_id(entry_id)}",
        source="app_store",
        source_type="review",
        date=updated,
        text="\n\n".join(parts),
        url=url,
        rating=_parse_rating(entry),
        engagement=Engagement(score=0, comments=0, thumbs_up=0),
        metadata=FeedbackMetadata(
            app_version=app_version or None,
            title=title or None,
            country=country,
            storefront="app_store",
        ),
    )


def collect_app_store_reviews(
    *,
    app_id: str = DEFAULT_APP_STORE_APP_ID,
    country: str = DEFAULT_APP_STORE_COUNTRY,
    limit: int = DEFAULT_APP_STORE_LIMIT,
    max_pages: int = DEFAULT_APP_STORE_MAX_PAGES,
    fetcher: Optional[AppStoreFetcher] = None,
) -> list[RawFeedbackItem]:
    active_fetcher = fetcher or _default_fetcher
    feedback_items: list[RawFeedbackItem] = []
    seen_feedback_ids: set[str] = set()

    logger.info(
        "app_store collection started app_id=%s target_reviews=%s max_pages=%s",
        app_id,
        limit,
        max_pages,
    )

    for page in range(1, max_pages + 1):
        payload = active_fetcher(
            build_app_store_reviews_url(app_id=app_id, country=country, page=page)
        )
        root = ElementTree.fromstring(payload)
        entries = root.findall("atom:entry", APP_STORE_NS)

        if not entries:
            logger.info(
                "app_store page=%s returned no entries cumulative_reviews=%s",
                page,
                len(feedback_items),
            )
            break

        page_added = 0
        for entry in entries:
            normalized = normalize_app_store_entry(entry, country=country, app_id=app_id)
            if not normalized.text.strip():
                continue
            if normalized.feedback_id in seen_feedback_ids:
                continue

            seen_feedback_ids.add(normalized.feedback_id)
            feedback_items.append(normalized)
            page_added += 1

            if len(feedback_items) >= limit:
                logger.info(
                    "app_store reached cap page=%s cumulative_reviews=%s",
                    page,
                    len(feedback_items),
                )
                return feedback_items[:limit]

        logger.info(
            "app_store page=%s entries=%s added=%s cumulative_reviews=%s",
            page,
            len(entries),
            page_added,
            len(feedback_items),
        )
        if page_added == 0:
            break

    logger.info(
        "app_store collection completed normalized_reviews=%s",
        len(feedback_items),
    )
    return feedback_items
