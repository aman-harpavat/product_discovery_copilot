from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from typing import Any, Optional, Tuple

from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem
from app.utils.dates import is_within_relative_window

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
    country: str | None,
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

    kwargs: dict[str, Any] = {
        "lang": lang,
        "sort": Sort.NEWEST,
        "count": count,
        "continuation_token": continuation_token,
    }
    if country:
        kwargs["country"] = country

    items, continuation_token = reviews(
        app_id,
        **kwargs,
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
    country: str | None = DEFAULT_GOOGLE_PLAY_COUNTRY,
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
    country: str | None = DEFAULT_GOOGLE_PLAY_COUNTRY,
    lang: str = DEFAULT_GOOGLE_PLAY_LANGUAGE,
    count: int | None = DEFAULT_GOOGLE_PLAY_MAX_REVIEWS,
    batch_size: int = DEFAULT_GOOGLE_PLAY_BATCH_SIZE,
    time_window_value: str | None = None,
    max_pages: int | None = None,
    fetcher: Optional[GooglePlayFetcher] = None,
) -> list[RawFeedbackItem]:
    active_fetcher = fetcher or _default_fetcher
    continuation_token: Any = None
    normalized_items: list[RawFeedbackItem] = []
    seen_feedback_ids: set[str] = set()
    page = 0

    logger.info(
        "google_play collection started app_id=%s target_reviews=%s country=%s",
        app_id,
        count,
        country or "none",
    )

    while True:
        if max_pages is not None and page >= max_pages:
            logger.info(
                "google_play reached page safety cap pages=%s cumulative_reviews=%s",
                page,
                len(normalized_items),
            )
            break
        page += 1
        fetch_count = min(batch_size, count - len(normalized_items)) if count is not None else batch_size
        if fetch_count <= 0:
            break
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
                len(normalized_items),
            )
            break

        page_reached_window_boundary = False
        page_added = 0
        for review in items:
            if not str(review.get("content") or "").strip():
                continue

            normalized = normalize_google_play_review(review, app_id=app_id, country=country)
            if normalized.feedback_id in seen_feedback_ids:
                continue

            if time_window_value and not is_within_relative_window(
                normalized.date,
                time_window_value,
            ):
                page_reached_window_boundary = True
                continue

            seen_feedback_ids.add(normalized.feedback_id)
            normalized_items.append(normalized)
            page_added += 1

            if count is not None and len(normalized_items) >= count:
                logger.info(
                    "google_play reached review cap page=%s cumulative_reviews=%s",
                    page,
                    len(normalized_items),
                )
                return normalized_items[:count]

        logger.info(
            "google_play page=%s fetched=%s cumulative_reviews=%s remaining=%s",
            page,
            len(items),
            len(normalized_items),
            (count - len(normalized_items)) if count is not None else "open",
        )

        if time_window_value and page_reached_window_boundary:
            logger.info(
                "google_play reached time-window boundary page=%s cumulative_reviews=%s",
                page,
                len(normalized_items),
            )
            break

        if page_added == 0:
            break

        if continuation_token is None:
            break

    logger.info(
        "google_play collection completed normalized_reviews=%s",
        len(normalized_items),
    )
    return normalized_items
