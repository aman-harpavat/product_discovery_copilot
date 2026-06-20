import json
from pathlib import Path

from app.main import app


def test_generated_openapi_schema_file_matches_app_contract() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2] / "docs" / "openapi_schema.yaml"
    )
    exported_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    runtime_schema = app.openapi()

    assert exported_schema["openapi"] == "3.1.0"
    assert exported_schema["servers"][0]["url"] == "https://YOUR_BACKEND_URL"
    assert "/analyze-feedback" in exported_schema["paths"]
    assert exported_schema["paths"]["/analyze-feedback"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalyzeFeedbackResponse"
    }
    assert exported_schema["paths"]["/analyze-feedback"]["post"]["responses"]["422"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "/runs/{run_id}/manifest" in runtime_schema["paths"]
    assert "/runs/{run_id}/artifact/{artifact_name}" in runtime_schema["paths"]
    assert (
        runtime_schema["paths"]["/analyze-feedback"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        == {"$ref": "#/components/schemas/AnalyzeFeedbackResponse"}
    )
