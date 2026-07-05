from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Lock
from time import sleep
import math
from typing import Any

from app.config import settings
from app.schemas import AnalyzeFeedbackRequest, ArtifactManifest, RunStatusResponse
from app.services.artifacts import build_artifact_manifest, ensure_run_dir
from app.services.pipeline import build_mock_analysis_response
from app.utils.dates import relative_window_months_equivalent
from app.utils.ids import make_run_id

_STATUS_FILENAME = "_run_status.json"
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=settings.background_worker_count)
_STATUS_LOCK = Lock()
logger = logging.getLogger(__name__)


def start_analysis_run(request: AnalyzeFeedbackRequest) -> RunStatusResponse:
    run_id = make_run_id()
    now = datetime.now(timezone.utc)
    estimated_total_seconds = _estimate_total_runtime_seconds(request)
    _reset_run_log(run_id)
    _write_status_record(
        run_id,
        {
            "run_id": run_id,
            "status": "queued",
            "current_stage": "queued",
            "progress_percent": 0,
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "estimated_total_seconds": estimated_total_seconds,
            "message": "Analysis run accepted and queued.",
            "warnings": [],
            "error_message": None,
        },
    )
    _append_run_log(
        run_id,
        f"run accepted status=queued estimated_total_seconds={estimated_total_seconds}",
    )
    _RUN_EXECUTOR.submit(_execute_analysis_run, run_id, request.model_dump())
    return get_run_status(run_id)


def get_run_status(run_id: str, *, wait_seconds: int = 0) -> RunStatusResponse:
    capped_wait = max(0, min(wait_seconds, settings.async_run_poll_wait_cap_seconds))
    elapsed_wait = 0
    status_record = _read_status_record(run_id)
    while (
        capped_wait > 0
        and status_record["status"] in {"queued", "running"}
        and elapsed_wait < capped_wait
    ):
        sleep(2)
        elapsed_wait += 2
        status_record = _read_status_record(run_id)
    return _build_public_status(status_record)


def get_latest_run_status(*, wait_seconds: int = 0) -> RunStatusResponse:
    status_paths = sorted(
        Path(settings.runs_dir_path).glob("*/_run_status.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not status_paths:
        raise FileNotFoundError("No runs found")
    latest_run_id = status_paths[0].parent.name
    return get_run_status(latest_run_id, wait_seconds=wait_seconds)


def _execute_analysis_run(run_id: str, request_payload: dict[str, Any]) -> None:
    request = AnalyzeFeedbackRequest.model_validate(request_payload)
    _update_status(
        run_id,
        status="running",
        current_stage="collecting_sources",
        progress_percent=5,
        message="Collecting source feedback.",
    )
    try:
        response = build_mock_analysis_response(
            request,
            run_id=run_id,
            status_callback=lambda stage, progress, message: _update_status(
                run_id,
                status="running",
                current_stage=stage,
                progress_percent=progress,
                message=message or _default_message_for_stage(stage),
            ),
        )
        _update_status(
            run_id,
            status=response.status,
            current_stage="completed",
            progress_percent=100,
            message="Analysis completed and artifacts are ready.",
            warnings=response.warnings,
            error_message=None,
        )
    except Exception as exc:  # pragma: no cover - exercised through integration flow
        _update_status(
            run_id,
            status="failed",
            current_stage="failed",
            progress_percent=100,
            message="Analysis failed before artifact generation completed.",
            error_message=str(exc),
        )


def _build_public_status(status_record: dict[str, Any]) -> RunStatusResponse:
    now = datetime.now(timezone.utc)
    started_at = _parse_status_datetime(status_record["started_at"])
    updated_at = _parse_status_datetime(status_record["updated_at"])
    estimated_total_seconds = int(status_record.get("estimated_total_seconds", 0))
    elapsed_seconds = max(0, int((now - started_at).total_seconds()))
    if status_record["status"] in {"completed", "partial_success", "failed"}:
        estimated_seconds_remaining = 0
    else:
        estimated_seconds_remaining = _estimate_remaining_seconds(
            current_stage=status_record["current_stage"],
            estimated_total_seconds=estimated_total_seconds,
            elapsed_seconds=elapsed_seconds,
        )

    artifact_manifest: ArtifactManifest | None = None
    manifest_url: str | None = None
    if status_record["status"] in {"completed", "partial_success"}:
        artifact_manifest = build_artifact_manifest(status_record["run_id"])
        manifest_url = f"/runs/{status_record['run_id']}/manifest"

    return RunStatusResponse(
        run_id=status_record["run_id"],
        status=status_record["status"],
        current_stage=status_record["current_stage"],
        progress_percent=int(status_record["progress_percent"]),
        started_at=started_at,
        updated_at=updated_at,
        estimated_minutes_remaining=max(0, math.ceil(estimated_seconds_remaining / 60)),
        estimated_seconds_remaining=estimated_seconds_remaining,
        message=status_record["message"],
        warnings=list(status_record.get("warnings", [])),
        error_message=status_record.get("error_message"),
        manifest_url=manifest_url,
        artifact_manifest=artifact_manifest,
    )


def _estimate_total_runtime_seconds(request: AnalyzeFeedbackRequest) -> int:
    months_equivalent = relative_window_months_equivalent(
        request.analysis_time_window.value
    )
    google_play_pages = _estimate_store_page_cap(
        months_equivalent=months_equivalent,
        hard_cap=settings.google_play_page_safety_cap,
        minimum_pages=10,
        pages_per_month=15,
    )
    app_store_pages = _estimate_store_page_cap(
        months_equivalent=months_equivalent,
        hard_cap=settings.app_store_page_safety_cap,
        minimum_pages=8,
        pages_per_month=10,
    )
    reddit_query_count = (
        settings.fast_mode_reddit_max_queries
        if request.max_runtime_seconds <= 120
        else settings.reddit_max_queries_per_run
    )
    reddit_max_total_seconds = (
        settings.fast_mode_reddit_max_total_seconds
        if request.max_runtime_seconds <= 120
        else settings.full_mode_reddit_max_total_seconds
    )

    google_play_seconds = min(75.0, google_play_pages * 0.45)
    app_store_seconds = min(12.0, min(app_store_pages, 10) * 0.8)
    reddit_seconds = min(
        reddit_max_total_seconds,
        12.0 + (reddit_query_count * 7.0) + max(0, reddit_query_count - 1) * 4.0,
    )
    processing_seconds = 18.0
    conservative_buffer_seconds = 25.0

    estimate_seconds = int(
        google_play_seconds
        + app_store_seconds
        + reddit_seconds
        + processing_seconds
        + conservative_buffer_seconds
    )
    return min(request.max_runtime_seconds, max(90, estimate_seconds))


def _estimate_remaining_seconds(
    *,
    current_stage: str,
    estimated_total_seconds: int,
    elapsed_seconds: int,
) -> int:
    stage_floor_seconds = {
        "queued": max(30, estimated_total_seconds),
        "collecting_sources": max(30, estimated_total_seconds - elapsed_seconds),
        "cleaning_feedback": 20,
        "filtering_relevance": 14,
        "deduplicating_feedback": 10,
        "clustering_feedback": 8,
        "writing_artifacts": 3,
    }
    if current_stage in stage_floor_seconds:
        if current_stage == "collecting_sources":
            return stage_floor_seconds[current_stage]
        return max(1, stage_floor_seconds[current_stage])
    return max(5, estimated_total_seconds - elapsed_seconds)


def _estimate_store_page_cap(
    *,
    months_equivalent: float,
    hard_cap: int,
    minimum_pages: int,
    pages_per_month: int,
) -> int:
    estimated_pages = minimum_pages + int(math.ceil(months_equivalent * pages_per_month))
    return max(minimum_pages, min(hard_cap, estimated_pages))


def _update_status(
    run_id: str,
    *,
    status: str,
    current_stage: str,
    progress_percent: int,
    message: str,
    warnings: list[str] | None = None,
    error_message: str | None = None,
) -> None:
    status_record = _read_status_record(run_id)
    status_record.update(
        {
            "status": status,
            "current_stage": current_stage,
            "progress_percent": progress_percent,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "error_message": error_message,
        }
    )
    if warnings is not None:
        status_record["warnings"] = warnings
    _write_status_record(run_id, status_record)
    warning_count = len(status_record.get("warnings", []))
    _append_run_log(
        run_id,
        f"status={status} stage={current_stage} progress={progress_percent} message={message} warnings={warning_count}",
    )
    if status in {"completed", "partial_success", "failed"}:
        logger.info(
            "run status finalized run_id=%s status=%s stage=%s progress=%s warnings=%s error=%s",
            run_id,
            status,
            current_stage,
            progress_percent,
            warning_count,
            error_message,
        )


def _read_status_record(run_id: str) -> dict[str, Any]:
    path = _status_path(run_id)
    if not path.exists():
        raise FileNotFoundError(run_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_status_record(run_id: str, payload: dict[str, Any]) -> None:
    path = _status_path(run_id)
    temp_path = path.with_name(f"{path.name}.tmp")
    with _STATUS_LOCK:
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(path)


def _reset_run_log(run_id: str) -> None:
    run_dir = ensure_run_dir(run_id)
    log_path = run_dir / "run.log"
    log_path.write_text("", encoding="utf-8")


def _append_run_log(run_id: str, message: str) -> None:
    run_dir = ensure_run_dir(run_id)
    log_path = run_dir / "run.log"
    timestamp = datetime.now(timezone.utc).isoformat()
    with _STATUS_LOCK:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")


def _status_path(run_id: str) -> Path:
    return ensure_run_dir(run_id) / _STATUS_FILENAME


def _parse_status_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _default_message_for_stage(stage: str) -> str:
    return {
        "collecting_sources": "Collecting source feedback.",
        "cleaning_feedback": "Cleaning and normalizing collected feedback.",
        "filtering_relevance": "Filtering for discovery-relevant evidence.",
        "deduplicating_feedback": "Removing duplicates.",
        "clustering_feedback": "Clustering related feedback.",
        "writing_artifacts": "Writing artifacts for GPT retrieval.",
        "completed": "Analysis completed and artifacts are ready.",
        "failed": "Analysis failed.",
    }.get(stage, "Analysis is still running.")
