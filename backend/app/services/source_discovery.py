from __future__ import annotations

from app.config import settings
from app.schemas import AnalyzeFeedbackRequest


def build_query_seeds(request: AnalyzeFeedbackRequest) -> list[str]:
    """Generate auditable source queries from the locked brief."""
    seeds = [
        f"{request.product} {request.research_scope}",
        f"{request.product} {request.research_goal}",
    ]

    seeds.extend(
        f"{request.product} {topic}" for topic in request.included_topics if topic
    )
    seeds.extend(
        f"{request.product} {question}" for question in request.research_questions if question
    )

    seen: set[str] = set()
    unique_seeds: list[str] = []
    for seed in seeds:
        normalized = seed.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_seeds.append(normalized)
    return unique_seeds


def build_reddit_query_seeds(
    request: AnalyzeFeedbackRequest,
    *,
    expanded: bool = False,
) -> list[str]:
    """Generate Reddit-oriented discovery queries from the locked brief."""
    seeds = [
        f"{request.product} recommendations repetitive",
        f"{request.product} Discover Weekly repetitive",
        f"{request.product} smart shuffle repetitive",
        f"{request.product} playlist discovery",
    ]

    seeds.extend(
        f"{request.product} {topic}" for topic in request.included_topics if topic
    )
    seeds.extend(
        f"{request.product} {question}" for question in request.research_questions[:2] if question
    )

    seeds.extend(
        [
            f"{request.product} algorithm recommendations",
            f"{request.product} new music discovery",
            f"{request.product} personalization",
            f"{request.product} Release Radar",
            f"{request.product} recommendations bad",
            f"{request.product} same songs recommendations",
            f"{request.product} same artists recommendations",
            f"{request.product} discovery novelty",
            f"{request.product} shuffle discovery",
            f"{request.product} {request.research_scope}",
        ]
    )

    seen: set[str] = set()
    unique_seeds: list[str] = []
    for seed in seeds:
        normalized = " ".join(seed.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_seeds.append(normalized)
    limit = (
        settings.reddit_expanded_max_queries_per_run
        if expanded
        else settings.reddit_max_queries_per_run
    )
    return unique_seeds[:limit]
