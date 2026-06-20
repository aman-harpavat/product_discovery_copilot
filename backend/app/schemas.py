from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


DEFAULT_SPOTIFY_RESEARCH_QUESTIONS = [
    "Why do users struggle to discover new music?",
    "What are the most common frustrations with recommendations?",
    "What listening behaviors are users trying to achieve?",
    "What causes repetitive listening?",
    "Which user segments experience different discovery challenges?",
    "What unmet needs emerge consistently?",
]


class AnalysisTimeWindow(BaseModel):
    type: str = Field(..., description="Time window type, e.g. relative")
    value: str = Field(..., description="Time window value, e.g. 12_months")

    @model_validator(mode="after")
    def validate_time_window(self) -> "AnalysisTimeWindow":
        if self.type != "relative":
            raise ValueError("analysis_time_window.type must be 'relative'")

        if not self.value or "_" not in self.value:
            raise ValueError(
                "analysis_time_window.value must look like '12_months'"
            )

        number, unit = self.value.split("_", 1)
        if not number.isdigit() or int(number) <= 0:
            raise ValueError(
                "analysis_time_window.value must start with a positive integer"
            )

        allowed_units = {"days", "weeks", "months", "years"}
        if unit not in allowed_units:
            raise ValueError(
                "analysis_time_window.value unit must be one of days, weeks, months, years"
            )

        return self


class AnalyzeFeedbackRequest(BaseModel):
    product: str = Field(..., min_length=1)
    research_scope: str = Field(..., min_length=1)
    research_goal: str = Field(..., min_length=1)
    analysis_time_window: AnalysisTimeWindow
    included_topics: list[str] = Field(..., min_length=1)
    excluded_topics: list[str] = Field(..., min_length=1)
    research_questions: list[str] = Field(..., min_length=1)
    success_criteria: list[str] = Field(..., min_length=1)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)
    debug: bool = False

    @model_validator(mode="after")
    def validate_fixed_product_scope(self) -> "AnalyzeFeedbackRequest":
        if self.product.strip().lower() != "spotify":
            raise ValueError(
                "This implementation is currently fixed to Spotify. Set product to 'Spotify'."
            )
        self.product = "Spotify"
        return self


class Engagement(BaseModel):
    score: int = 0
    comments: int = 0
    thumbs_up: int = 0


class FeedbackMetadata(BaseModel):
    subreddit: Optional[str] = None
    query_used: Optional[str] = None
    app_version: Optional[str] = None
    title: Optional[str] = None
    country: Optional[str] = None
    storefront: Optional[str] = None


class RawFeedbackItem(BaseModel):
    feedback_id: str
    source: str
    source_type: str
    date: str
    text: str
    url: str
    rating: Optional[int] = None
    engagement: Engagement = Field(default_factory=Engagement)
    metadata: FeedbackMetadata = Field(default_factory=FeedbackMetadata)


class SourceDateRange(BaseModel):
    start: str
    end: str


class SourceSummaryItem(BaseModel):
    source_name: str
    source_type: str
    queries_used: list[str]
    records_collected: int
    records_relevant: int
    date_range: SourceDateRange
    notes: str


class QuoteItem(BaseModel):
    text: str
    source: str
    url: str
    date: str


class ClusterItem(BaseModel):
    cluster_id: str
    cluster_name: str
    cluster_summary: str
    cluster_tier: str = "tier_1"
    cluster_size: int = 0
    cluster_cohesion_score: float = 0.0
    frequency: int
    dominant_signal: str = "mixed"
    pain_point_evidence_count: int = 0
    positive_validation_count: int = 0
    request_signal_count: int = 0
    mixed_signal_flag: bool = False
    source_distribution: dict[str, int]
    time_distribution: dict[str, int]
    representative_quotes: list[QuoteItem]
    example_feedback_ids: list[str]
    keywords: list[str]
    mapped_research_questions: list[str] = Field(default_factory=list)
    mapped_success_criteria: list[str] = Field(default_factory=list)
    repeat_listening_cause_tags: list[str] = Field(default_factory=list)
    relevance_score: float


class TopClusterMetric(BaseModel):
    cluster_id: str
    cluster_name: str
    frequency: int


class MetricsPayload(BaseModel):
    total_records_collected: int
    records_after_cleaning: int
    records_relevant: int
    records_after_deduplication: int
    exact_duplicates_removed: int = 0
    normalized_duplicates_removed: int = 0
    near_duplicates_removed: int = 0
    cluster_count: int
    dominant_signal_distribution: dict[str, int] = Field(default_factory=dict)
    source_distribution: dict[str, int]
    rating_distribution: dict[str, int]
    top_clusters: list[TopClusterMetric]


class ChartValueBySource(BaseModel):
    source: str
    count: int


class ChartValueOverTime(BaseModel):
    month: str
    count: int


class ChartClusterValue(BaseModel):
    cluster_name: str
    frequency: int


class ChartRatingValue(BaseModel):
    rating: str
    count: int


class SourceDistributionByCluster(BaseModel):
    cluster_name: str
    reddit: int = 0
    google_play: int = 0
    app_store: int = 0


class ClusterSignalValue(BaseModel):
    signal: str
    count: int


class ChartsDataPayload(BaseModel):
    feedback_by_source: list[ChartValueBySource]
    feedback_over_time: list[ChartValueOverTime]
    top_clusters: list[ChartClusterValue]
    rating_distribution: list[ChartRatingValue]
    source_distribution_by_cluster: list[SourceDistributionByCluster]
    cluster_signal_distribution: list[ClusterSignalValue]


class ProcessingSummary(BaseModel):
    records_collected: int
    records_after_cleaning: int
    records_relevant: int
    records_after_deduplication: int
    exact_duplicates_removed: int = 0
    normalized_duplicates_removed: int = 0
    near_duplicates_removed: int = 0
    source_failures: list[str] = Field(default_factory=list)
    source_warning_codes: dict[str, list[str]] = Field(default_factory=dict)
    expanded_collection_applied: bool = False
    expanded_collection_reason: Optional[str] = None


class QualityDiagnostics(BaseModel):
    total_collected: int
    in_window_records: int
    out_of_window_records: int
    relevant_records: int
    relevant_rate: float
    dedupe_rate: float
    cluster_count: int
    average_records_per_cluster: float
    single_record_cluster_count: int
    source_contamination_warnings: list[str] = Field(default_factory=list)
    time_window_violations: int = 0
    expanded_collection_applied: bool = False
    expanded_collection_reason: Optional[str] = None


class ResearchQuestionCoverage(BaseModel):
    question_id: Optional[str] = None
    question: str
    evidence_strength: str
    relevant_cluster_ids: list[str] = Field(default_factory=list)
    source_coverage: dict[str, int] = Field(default_factory=dict)
    record_count: int = 0
    summary: str
    evidence_gaps: list[str] = Field(default_factory=list)


class SourceLimitation(BaseModel):
    source: str
    limitation: str
    severity: str = "medium"


class SuccessCriteriaImpactItem(BaseModel):
    criterion: str
    impact_level: str
    rationale: str
    supporting_cluster_ids: list[str] = Field(default_factory=list)


class SupportingResearchQuestionItem(BaseModel):
    question_id: str
    question: str
    support_level: str
    supporting_cluster_ids: list[str] = Field(default_factory=list)
    evidence_summary: str


class OpportunityItem(BaseModel):
    opportunity_id: str
    opportunity_name: str
    opportunity_statement: str
    derived_from_cluster_id: str
    dominant_signal: str
    frequency: int
    source_distribution: dict[str, int]
    supporting_cluster_ids: list[str] = Field(default_factory=list)
    supporting_research_questions: list[SupportingResearchQuestionItem] = Field(
        default_factory=list
    )
    success_criteria_impact: list[SuccessCriteriaImpactItem] = Field(default_factory=list)
    brief_alignment_score: str
    brief_alignment_rationale: str
    representative_quotes: list[QuoteItem] = Field(default_factory=list)
    top_pain_points: list[str] = Field(default_factory=list)


class EvidenceBackedSegment(BaseModel):
    segment_name: str
    description: str
    estimated_record_count: int
    percentage_of_relevant_records: float
    source_distribution: dict[str, int]
    supporting_cluster_ids: list[str] = Field(default_factory=list)
    representative_quotes: list[QuoteItem] = Field(default_factory=list)
    primary_JTBDs: list[str] = Field(default_factory=list)
    top_pain_points: list[str] = Field(default_factory=list)
    confidence_level: str
    confidence_rationale: str


class ArtifactItem(BaseModel):
    name: str
    type: str
    description: str
    url: str


class ArtifactManifest(BaseModel):
    run_id: str
    artifacts: list[ArtifactItem]


class CompactGPTPayload(BaseModel):
    locked_brief: dict[str, Any]
    success_criteria: list[str]
    source_summary: list[SourceSummaryItem]
    processing_summary: ProcessingSummary
    quality_diagnostics: QualityDiagnostics
    research_question_coverage: list[ResearchQuestionCoverage]
    top_clusters: list[ClusterItem]
    top_opportunities: list[OpportunityItem] = Field(default_factory=list)
    top_metrics: dict[str, Any]
    charts_data_summary: dict[str, Any]
    representative_quotes: list[QuoteItem]
    opportunity_traceability_summary: list[dict[str, Any]] = Field(default_factory=list)
    success_criteria_impact_summary: list[dict[str, Any]] = Field(default_factory=list)
    evidence_backed_segments: list[EvidenceBackedSegment] = Field(default_factory=list)
    brief_alignment_summary: dict[str, Any] = Field(default_factory=dict)
    source_limitations: list[str]
    artifact_manifest: ArtifactManifest


class AnalyzeFeedbackResponse(BaseModel):
    run_id: str
    status: str
    locked_brief: dict[str, Any]
    source_summary: list[SourceSummaryItem]
    processing_summary: ProcessingSummary
    quality_diagnostics: QualityDiagnostics
    research_question_coverage: list[ResearchQuestionCoverage]
    feedback_clusters: list[ClusterItem]
    opportunities: list[OpportunityItem] = Field(default_factory=list)
    evidence_backed_segments: list[EvidenceBackedSegment] = Field(default_factory=list)
    metrics: MetricsPayload
    charts_data: ChartsDataPayload
    representative_quotes: list[QuoteItem]
    compact_gpt_payload: CompactGPTPayload
    artifact_manifest: ArtifactManifest
    processing_notes: list[str]
    source_limitations: list[SourceLimitation]
    warnings: list[str]


class ErrorResponse(BaseModel):
    status: str = "error"
    error_type: str
    message: str
    missing_fields: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp_utc: datetime
