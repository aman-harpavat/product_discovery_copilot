from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from typing import Any, Optional, Tuple

from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem

DEFAULT_GOOGLE_PLAY_APP_ID = "com.spotify.music"
DEFAULT_GOOGLE_PLAY_COUNTRY = "us"
DEFAULT_GOOGLE_PLAY_LANGUAGE = "en"
DEFAULT_GOOGLE_PLAY_BATCH_SIZE = 100
DEFAULT_GOOGLE_PLAY_MAX_REVIEWS = 500

GooglePlayFetcher = Callable[..., Tuple[list[dict[str, Any]], Optional[str]]]
logger = logging.getLogger(__name__)


def _default_fetcher(
    *,
    app_id: str,
    country: str,
    lang: str,
    count: int,
    continuation_token: Any = None,
) -> Tuple[list[dict[str, Any]], Optional[str]]:
    try:
        from google_play_scraper import Sort, reviews
    except ImportError as exc:  # pragma: no cover - exercised through pipeline warning
        raise RuntimeError(
            "google-play-scraper is not installed; install dependencies before collecting Google Play reviews."
        ) from exc

    items, continuation_token = reviews(
        app_id,
        lang=lang,
        country=country,
        sort=Sort.NEWEST,
        count=count,
        continuation_token=continuation_token,
    )
    return items, continuation_token


def _coerce_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_review_url(app_id: str) -> str:
    return f"https://play.google.com/store/apps/details?id={app_id}&showAllReviews=true"


def normalize_google_play_review(
    review: dict[str, Any],
    *,
    app_id: str = DEFAULT_GOOGLE_PLAY_APP_ID,
    country: str = DEFAULT_GOOGLE_PLAY_COUNTRY,
) -> RawFeedbackItem:
    review_id = str(review.get("reviewId") or review.get("at") or review.get("userName") or "unknown")
    content = str(review.get("content") or "").strip()
    date_value = _coerce_datetime(review.get("at"))
    thumbs_up = int(review.get("thumbsUpCount") or 0)
    score = int(review.get("score") or 0)

    return RawFeedbackItem(
        feedback_id=f"fb_google_play_{review_id}",
        source="google_play",
        source_type="review",
        date=date_value,
        text=content,
        url=_build_review_url(app_id),
        rating=score or None,
        engagement=Engagement(thumbs_up=thumbs_up),
        metadata=FeedbackMetadata(
            app_version=(
                str(review.get("reviewCreatedVersion"))
                if review.get("reviewCreatedVersion") is not None
                else None
            ),
            title=str(review.get("title")) if review.get("title") else None,
            country=country,
            storefront="google_play",
        ),
    )


def collect_google_play_reviews(
    *,
    app_id: str = DEFAULT_GOOGLE_PLAY_APP_ID,
    country: str = DEFAULT_GOOGLE_PLAY_COUNTRY,
    lang: str = DEFAULT_GOOGLE_PLAY_LANGUAGE,
    count: int = DEFAULT_GOOGLE_PLAY_MAX_REVIEWS,
    batch_size: int = DEFAULT_GOOGLE_PLAY_BATCH_SIZE,
    fetcher: Optional[GooglePlayFetcher] = None,
) -> list[RawFeedbackItem]:
    active_fetcher = fetcher or _default_fetcher
    remaining = max(count, 0)
    continuation_token: Any = None
    collected_items: list[dict[str, Any]] = []
    page = 0

    logger.info("google_play collection started app_id=%s target_reviews=%s", app_id, count)

    while remaining > 0:
        page += 1
        fetch_count = min(batch_size, remaining)
        items, continuation_token = active_fetcher(
            app_id=app_id,
            country=country,
            lang=lang,
            count=fetch_count,
            continuation_token=continuation_token,
        )

        if not items:
            logger.info(
                "google_play page=%s returned no items cumulative_reviews=%s",
                page,
                len(collected_items),
            )
            break

        collected_items.extend(items)
        remaining = count - len(collected_items)
        logger.info(
            "google_play page=%s fetched=%s cumulative_reviews=%s remaining=%s",
            page,
            len(items),
            len(collected_items),
            remaining,
        )

        if continuation_token is None:
            break

    normalized_items = [
        normalize_google_play_review(review, app_id=app_id, country=country)
        for review in collected_items[:count]
        if str(review.get("content") or "").strip()
    ]
    logger.info(
        "google_play collection completed normalized_reviews=%s",
        len(normalized_items),
    )
    return normalized_items
