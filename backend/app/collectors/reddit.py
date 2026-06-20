from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
from time import sleep
from typing import Any, Callable, Optional, Tuple
from urllib.parse import quote_plus, urlparse
import hashlib
from xml.etree import ElementTree

import httpx

from app.config import settings
from app.schemas import Engagement, FeedbackMetadata, RawFeedbackItem

DEFAULT_REDDIT_BASE_URL = "https://www.reddit.com"
DEFAULT_REDDIT_RESULT_LIMIT = 200
DEFAULT_REDDIT_USER_AGENT = "ai-product-discovery-copilot/0.1"
DEFAULT_REDDIT_QUERY_DELAY_SECONDS = settings.reddit_query_delay_seconds
DEFAULT_REDDIT_MAX_RETRIES = settings.reddit_max_retries
DEFAULT_REDDIT_BACKOFF_SECONDS = settings.reddit_backoff_seconds
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

RedditFetcher = Callable[[str], Tuple[str, dict[str, str]]]
SleepFn = Callable[[float], None]
logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self.parts)


def _default_fetcher(url: str) -> Tuple[str, dict[str, str]]:
    response = httpx.get(
        url,
        headers={"User-Agent": DEFAULT_REDDIT_USER_AGENT},
        timeout=settings.outbound_request_timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text, dict(response.headers)


def _is_rate_limited(exc: Exception) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code == 429
    )


def _cache_path_for_query(query: str) -> Path:
    cache_dir = Path(settings.cache_dir_path) / "reddit"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _load_cached_query_result(query: str) -> Optional[tuple[str, dict[str, str]]]:
    cache_path = _cache_path_for_query(query)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    cached_at = float(payload.get("cached_at") or 0)
    age_seconds = datetime.now(timezone.utc).timestamp() - cached_at
    if age_seconds > settings.reddit_cache_ttl_seconds:
        return None

    text = payload.get("text")
    headers = payload.get("headers")
    if not isinstance(text, str) or not isinstance(headers, dict):
        return None

    return text, {str(key): str(value) for key, value in headers.items()}


def _store_cached_query_result(
    query: str,
    text: str,
    headers: dict[str, str],
) -> None:
    cache_path = _cache_path_for_query(query)
    payload = {
        "cached_at": datetime.now(timezone.utc).timestamp(),
        "text": text,
        "headers": headers,
    }
    try:
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("reddit cache_write_failed query=%s path=%s", query, cache_path)


def build_reddit_search_url(query: str) -> str:
    encoded_query = quote_plus(query)
    return f"{DEFAULT_REDDIT_BASE_URL}/search.rss?q={encoded_query}&sort=new&t=year"


def build_reddit_aggregate_query(
    queries: list[str],
    *,
    max_terms: int = 6,
) -> str:
    terms: list[str] = []
    for query in queries:
        for term in query.split():
            cleaned = term.strip()
            if cleaned and cleaned not in terms:
                terms.append(cleaned)
            if len(terms) >= max_terms:
                break
        if len(terms) >= max_terms:
            break
    return " ".join(terms) if terms else "Spotify music discovery"


def _extract_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(unescape(value))
    return parser.text().strip()


def _extract_subreddit(url: str) -> Optional[str]:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "r":
        return path_parts[1]
    return None


def _entry_link(entry: ElementTree.Element) -> str:
    link_element = entry.find("atom:link", ATOM_NS)
    if link_element is not None:
        href = link_element.attrib.get("href")
        if href:
            return href
    return DEFAULT_REDDIT_BASE_URL


def _entry_text(entry: ElementTree.Element) -> str:
    title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
    content = (
        entry.findtext("atom:content", default="", namespaces=ATOM_NS)
        or entry.findtext("atom:summary", default="", namespaces=ATOM_NS)
        or ""
    )
    content_text = _extract_text(content)
    parts = [part for part in [title, content_text] if part]
    return "\n\n".join(parts)


def normalize_reddit_entry(
    entry: ElementTree.Element,
    query_used: str,
) -> RawFeedbackItem:
    link = _entry_link(entry)
    entry_id = (
        entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
        or link.rstrip("/").split("/")[-1]
        or "unknown"
    )
    published = (
        entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        or entry.findtext("atom:published", default="", namespaces=ATOM_NS)
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    subreddit = _extract_subreddit(link)

    return RawFeedbackItem(
        feedback_id=f"fb_reddit_{entry_id}",
        source="reddit",
        source_type="discussion",
        date=published,
        text=_entry_text(entry),
        url=link,
        rating=None,
        engagement=Engagement(score=0, comments=0, thumbs_up=0),
        metadata=FeedbackMetadata(
            subreddit=subreddit,
            query_used=query_used,
        ),
    )


def collect_reddit_feedback_with_warnings(
    queries: list[str],
    *,
    limit: int = DEFAULT_REDDIT_RESULT_LIMIT,
    fetcher: Optional[RedditFetcher] = None,
    query_delay_seconds: float = DEFAULT_REDDIT_QUERY_DELAY_SECONDS,
    max_retries: int = DEFAULT_REDDIT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_REDDIT_BACKOFF_SECONDS,
    sleep_fn: SleepFn = sleep,
) -> tuple[list[RawFeedbackItem], list[str]]:
    active_fetcher = fetcher or _default_fetcher
    use_cache = fetcher is None
    feedback_items: list[RawFeedbackItem] = []
    seen_feedback_ids: set[str] = set()
    warnings: list[str] = []
    consecutive_rate_limits = 0

    query_list = queries or [build_reddit_aggregate_query([])]
    logger.info(
        "reddit collection started queries=%s target_records=%s",
        len(query_list),
        limit,
    )
    for index, query in enumerate(query_list):
        url = build_reddit_search_url(query)
        payload_text = None
        headers: dict[str, str] = {}
        logger.info(
            "reddit query_start index=%s/%s query=%s",
            index + 1,
            len(query_list),
            query,
        )

        cached_result = _load_cached_query_result(query) if use_cache else None
        if cached_result is not None:
            payload_text, headers = cached_result
            consecutive_rate_limits = 0
            logger.info(
                "reddit query_cache_hit index=%s/%s query=%s cumulative_records=%s",
                index + 1,
                len(query_list),
                query,
                len(feedback_items),
            )

        if payload_text is None:
            for attempt in range(max_retries + 1):
                try:
                    payload_text, headers = active_fetcher(url)
                    if use_cache:
                        _store_cached_query_result(query, payload_text, headers)
                    consecutive_rate_limits = 0
                    logger.info(
                        "reddit query_success index=%s/%s attempt=%s cumulative_records=%s",
                        index + 1,
                        len(query_list),
                        attempt + 1,
                        len(feedback_items),
                    )
                    break
                except Exception as exc:
                    if _is_rate_limited(exc):
                        if attempt < max_retries:
                            backoff_delay = backoff_seconds * (2**attempt)
                            logger.info(
                                "reddit query_rate_limited index=%s/%s attempt=%s backoff_seconds=%.2f",
                                index + 1,
                                len(query_list),
                                attempt + 1,
                                backoff_delay,
                            )
                            sleep_fn(backoff_delay)
                            continue
                        consecutive_rate_limits += 1
                    else:
                        consecutive_rate_limits = 0

                    warnings.append(
                        "Reddit query collection failed; continuing with partial Reddit results. "
                        f"Query: {query}. Reason: {exc}"
                    )
                    logger.warning(
                        "reddit query_failed index=%s/%s query=%s reason=%s",
                        index + 1,
                        len(query_list),
                        query,
                        exc,
                    )
                    payload_text = None
                    break

        if payload_text is None:
            if consecutive_rate_limits >= settings.reddit_max_consecutive_rate_limits:
                warnings.append(
                    "Reddit collection stopped early after repeated rate limits on public RSS search."
                )
                logger.warning(
                    "reddit early_stop consecutive_rate_limits=%s threshold=%s",
                    consecutive_rate_limits,
                    settings.reddit_max_consecutive_rate_limits,
                )
                break
            continue

        root = ElementTree.fromstring(payload_text)
        entries = root.findall("atom:entry", ATOM_NS)
        if not entries:
            logger.info(
                "reddit query_empty index=%s/%s cumulative_records=%s",
                index + 1,
                len(query_list),
                len(feedback_items),
            )
            if index < len(query_list) - 1:
                sleep_fn(query_delay_seconds)
            continue

        added = 0
        for entry in entries:
            normalized = normalize_reddit_entry(entry, query)
            if not normalized.text.strip():
                continue
            if normalized.feedback_id in seen_feedback_ids:
                continue

            seen_feedback_ids.add(normalized.feedback_id)
            feedback_items.append(normalized)
            added += 1

            if len(feedback_items) >= limit:
                logger.info(
                    "reddit reached cap index=%s/%s cumulative_records=%s",
                    index + 1,
                    len(query_list),
                    len(feedback_items),
                )
                return feedback_items[:limit], warnings

        logger.info(
            "reddit query_complete index=%s/%s entries=%s added=%s cumulative_records=%s",
            index + 1,
            len(query_list),
            len(entries),
            added,
            len(feedback_items),
        )
        if index < len(query_list) - 1:
            sleep_fn(query_delay_seconds)

    logger.info(
        "reddit collection completed records=%s warnings=%s",
        len(feedback_items),
        len(warnings),
    )
    return feedback_items, warnings


def collect_reddit_feedback(
    queries: list[str],
    *,
    limit: int = DEFAULT_REDDIT_RESULT_LIMIT,
    fetcher: Optional[RedditFetcher] = None,
) -> list[RawFeedbackItem]:
    feedback_items, _warnings = collect_reddit_feedback_with_warnings(
        queries,
        limit=limit,
        fetcher=fetcher,
    )
    return feedback_items
