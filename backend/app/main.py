from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.logging_config import configure_logging
from app.schemas import (
    AnalyzeFeedbackRequest,
    AnalyzeFeedbackResponse,
    ArtifactManifest,
    ErrorResponse,
    HealthResponse,
)
from app.services.artifacts import ARTIFACT_DEFINITIONS, artifact_path, build_artifact_manifest
from app.services.pipeline import build_mock_analysis_response

configure_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API for AI Product Discovery Copilot.",
)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["servers"] = [
        {
            "url": "https://YOUR_BACKEND_URL",
            "description": "Replace with the public HTTPS base URL of your deployed or tunneled backend.",
        }
    ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


class FinalReportRequest(BaseModel):
    markdown: str


class FinalReportResponse(BaseModel):
    artifact_name: str
    url: str


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    missing_fields: set[str] = set()
    for error in exc.errors():
        location = error.get("loc", [])
        if len(location) >= 2 and location[0] == "body":
            missing_fields.add(str(location[1]))

    payload = ErrorResponse(
        error_type="validation_error",
        message="Request validation failed",
        missing_fields=sorted(missing_fields),
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
        timestamp_utc=datetime.now(timezone.utc),
    )


@app.post(
    "/analyze-feedback",
    response_model=AnalyzeFeedbackResponse,
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
        }
    },
)
async def analyze_feedback(
    request: AnalyzeFeedbackRequest,
) -> AnalyzeFeedbackResponse:
    return build_mock_analysis_response(request)


@app.get("/runs/{run_id}/manifest", response_model=ArtifactManifest)
async def get_run_manifest(run_id: str) -> ArtifactManifest:
    manifest = build_artifact_manifest(run_id)
    if not manifest.artifacts:
        raise HTTPException(status_code=404, detail="Run artifacts not found")
    return manifest


@app.get("/runs/{run_id}/artifact/{artifact_name}")
async def get_run_artifact(run_id: str, artifact_name: str) -> FileResponse:
    if artifact_name not in ARTIFACT_DEFINITIONS:
        raise HTTPException(status_code=404, detail="Unknown artifact")
    if "/" in artifact_name or ".." in artifact_name:
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    try:
        path = artifact_path(run_id, artifact_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown artifact") from None

    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type, _ = ARTIFACT_DEFINITIONS[artifact_name]
    return FileResponse(path=path, media_type=media_type, filename=artifact_name)


@app.post("/runs/{run_id}/final-report", response_model=FinalReportResponse)
async def save_final_report(
    run_id: str,
    request: FinalReportRequest,
) -> FinalReportResponse:
    if not request.markdown.strip():
        raise HTTPException(status_code=422, detail="markdown is required")
    path = artifact_path(run_id, "final_report.md")
    path.write_text(request.markdown, encoding="utf-8")
    return FinalReportResponse(
        artifact_name="final_report.md",
        url=f"/runs/{run_id}/artifact/final_report.md",
    )
