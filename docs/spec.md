# spec_PHASE1_COMPLETE.md — AI Product Discovery Copilot Phase 1

## 0. Purpose of This Spec

This file is the implementation source of truth for Codex.

Codex must use this file to:
1. Generate `docs/architecture.md`.
2. Implement the Phase 1 backend step by step.
3. Generate the Custom GPT Action OpenAPI schema.
4. Generate the Custom GPT instruction prompt.
5. Keep product/PM strategy unchanged unless a technical blocker requires a change.

The system supports a Custom GPT workflow for the NextLeap Graduation Project. The workflow analyzes public user feedback for Spotify's music discovery experience and returns structured feedback clusters, metrics, charts, and evidence that the Custom GPT uses to generate a PM research report and opportunity validation briefs.

---

## 1. Product Context

### Selected product
Spotify

### Research scope
Music Discovery

### Research goal
Opportunity Discovery

### Phase 1 output
The Phase 1 workflow ends after producing:
- source summary
- processed feedback clusters
- metrics and chart-ready data
- PM research report
- ranked opportunity areas
- opportunity validation briefs for recommended opportunities
- suggested interview recruitment criteria and interview areas

### Explicitly out of scope for Phase 1
The system must not generate:
- final problem statement
- Problem Framing Canvas
- PRD
- MVP solution concept
- product roadmap

Those happen after interviews in Phase 2.

---

## 2. Final Architecture

### Chosen architecture
Custom GPT + Hosted Backend Action/API.

### Why
- User/evaluator can test using a Custom GPT link.
- No manual CSV upload or handoff.
- GPT acts as the reasoning and report-generation layer.
- Backend handles source discovery, data collection, preprocessing, clustering, metrics, and chart data.
- This is evaluator-friendly and avoids unnecessary frontend build complexity.

### Component split

#### Custom GPT responsibilities
- Accept natural-language user request.
- Clarify missing brief fields.
- Call backend Action only after required fields are complete.
- Interpret backend evidence.
- Generate PM research report.
- Generate opportunity ranking.
- Generate opportunity validation briefs.

#### Backend responsibilities
- Validate request.
- Discover sources and search queries.
- Collect public feedback.
- Normalize raw feedback.
- Clean text.
- Filter for research-scope relevance.
- Deduplicate exact and near-duplicate items.
- Cluster related feedback.
- Generate source summaries.
- Generate metrics.
- Generate chart-ready data.
- Return structured JSON to Custom GPT.

---

## 3. User Flow

1. User opens Custom GPT.
2. User says: `Analyze Spotify's music discovery experience`.
3. GPT identifies missing/implicit fields:
   - product = Spotify
   - research_scope = Music Discovery
   - research_goal = Opportunity Discovery
   - analysis_time_window = ask user or default to last 12 months with confirmation
   - included_topics = infer and confirm
   - excluded_topics = infer and confirm
4. GPT asks targeted clarifying question if any field is missing or ambiguous.
5. Once locked, GPT calls backend endpoint `/analyze-feedback`.
6. Backend collects and processes public feedback.
7. Backend returns structured response.
8. GPT generates report and validation briefs using only backend evidence.

---

## 4. Repository / Folder Structure

Codex should create this structure:

```text
ai-product-discovery-copilot/
  backend/
    app/
      __init__.py
      main.py
      schemas.py
      config.py
      collectors/
        __init__.py
        reddit.py
        google_play.py
        app_store.py
      processing/
        __init__.py
        cleaner.py
        relevance.py
        dedupe.py
        clustering.py
        metrics.py
      services/
        __init__.py
        source_discovery.py
        pipeline.py
      utils/
        __init__.py
        dates.py
        text.py
        ids.py
    tests/
      test_health.py
      test_validation.py
      test_relevance.py
      test_dedupe.py
      test_clustering.py
    requirements.txt
    README.md
  docs/
    architecture.md
    spec.md
    custom_gpt_instructions.md
    openapi_schema.yaml
    sample_request.json
    sample_response.json
```

---

## 5. API Contract

### Endpoint
`POST /analyze-feedback`

### Required request body

```json
{
  "product": "Spotify",
  "research_scope": "Music Discovery",
  "research_goal": "Opportunity Discovery",
  "analysis_time_window": {
    "type": "relative",
    "value": "12_months"
  },
  "included_topics": [
    "recommendations",
    "music discovery",
    "personalization",
    "artist discovery",
    "playlist discovery",
    "Discover Weekly",
    "Release Radar"
  ],
  "excluded_topics": [
    "pricing",
    "billing",
    "podcasts",
    "account settings",
    "playlist cover editing",
    "pure playback bugs"
  ],
  "max_runtime_seconds": 120,
  "debug": false
}
```

### Validation rules
- Backend must not guess missing strategic fields.
- If a required field is absent, return validation error.
- If time window is malformed, return validation error.
- If included/excluded topics are empty, backend can continue but must add a warning.

### Error response

```json
{
  "status": "error",
  "error_type": "validation_error",
  "message": "Missing required field: research_scope",
  "missing_fields": ["research_scope"]
}
```

### Success response

```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "locked_brief": {},
  "source_summary": [],
  "processing_summary": {},
  "feedback_clusters": [],
  "metrics": {},
  "charts_data": {},
  "representative_quotes": [],
  "processing_notes": [],
  "warnings": []
}
```

### Partial success response
If one source fails, do not fail the whole run.

```json
{
  "run_id": "run_abc123",
  "status": "partial_success",
  "locked_brief": {},
  "source_summary": [],
  "processing_summary": {},
  "feedback_clusters": [],
  "metrics": {},
  "charts_data": {},
  "representative_quotes": [],
  "processing_notes": [],
  "warnings": ["App Store collection failed; results use Reddit and Google Play only."]
}
```

For interactive Action reliability, the backend may compact transport-heavy response fields such as cluster detail and quote length, but it must still return the required sections: `source_summary`, `feedback_clusters`, `metrics`, `charts_data`, `representative_quotes`, `processing_notes`, and `warnings`. If compaction is applied, it must be disclosed in warnings or processing notes, and the underlying metrics/charts must still reflect the full analyzed result set.

---

## 6. Data Sources and Collection

### Source discovery principle
The backend should generate source queries dynamically using:
- product
- research_scope
- research_goal
- included_topics
- excluded_topics

Do not hardcode only `r/spotify`. Use it if discovered or relevant, but source discovery should be query-driven.

### MVP supported sources
1. Reddit
2. Google Play reviews
3. App Store reviews

### Reddit collector
Collect posts/comments related to the locked scope.

Fields:
- source = `reddit`
- source_type = `discussion`
- subreddit
- post_title
- text
- url
- created_at
- score
- num_comments
- query_used

Suggested query seeds:
- `{product} {research_scope}`
- `{product} recommendations repetitive`
- `{product} Discover Weekly repetitive`
- `{product} algorithm recommendations`
- `{product} new music discovery`
- `{product} recommendations bad`
- `{product} playlist discovery`
- `{product} Release Radar`
- `{product} personalization`

Implementation options:
- Reddit API if credentials available.
- Reddit JSON endpoints where feasible.
- Public search fallback if API unavailable.

Failure rule:
If Reddit fails, add warning and continue.

### Google Play collector
Collect Spotify app reviews.

Suggested package:
- `google-play-scraper`

Fields:
- source = `google_play`
- source_type = `review`
- rating
- text
- created_at
- app_version if available
- thumbs_up_count if available

Failure rule:
If limited by package/API, disclose in warnings.

Coverage rule:
Do not stop at a single fetch page when the source supports more. Continue source collection until the source is exhausted, inaccessible, or a documented source-level cap is reached.

Resilience rule:
If a source is partially rate-limited, preserve already collected records and continue where feasible instead of failing the entire source payload.

Warning semantics rule:
Expose machine-readable source warning semantics so downstream GPT/reporting logic can distinguish full source failure from partial source coverage.
For example, source warning codes may distinguish `reddit_partial` from `reddit_failed`.
Runs with partial source coverage may still return `completed` if the source produced usable records; reserve `partial_success` for full source outages.

Public Reddit optimization rule:
For the MVP public-collection path, prefer a smaller prioritized query set, short-lived query-result caching, and early stop after repeated rate limits over aggressive fan-out that causes long hangs.

Runtime budget rule:
For interactive runs, the backend may apply documented per-source collection caps based on `max_runtime_seconds` to keep the request within a practical action/demo window. This must be disclosed in warnings or processing notes and must never be silent.

For the same Action path, the backend may also apply transport-safe response compaction when necessary to avoid oversized response failures. This can include truncating quote text and limiting returned cluster detail, but must not silently drop the required output sections or alter the underlying computed metrics/charts.

The preferred pattern is:
- return a compact GPT-safe payload in the main response
- persist full evidence artifacts for the run
- expose artifact retrieval endpoints so the GPT can fetch deeper evidence on demand

Research-question rule:
- the request should support explicit `research_questions`
- if they are omitted for Spotify music discovery, use the default research-question set
- the backend must compute `research_question_coverage` so the final report answers the brief directly rather than only summarizing clusters

Artifact rule:
- all relevant feedback must still be analyzed
- all clusters must be preserved in run artifacts even if only a compact top-cluster subset is returned in the main response
- required run artifacts include raw feedback, cleaned feedback, all clusters, compact payload, chart data, coverage analysis, processing notes, and evidence appendix files

### App Store collector
Collect Spotify iOS reviews.

Fields:
- source = `app_store`
- source_type = `review`
- rating
- title
- text
- created_at
- app_version if available
- country/storefront if available

Implementation options:
- public RSS/feed route if available.
- scraping/library if feasible.

Coverage rule:
If the RSS/feed path supports page iteration, paginate until exhausted or source cap instead of reading only the first page.

Failure rule:
If App Store collection fails, return partial success.

---

## 7. Raw Feedback Schema

Every collected item must normalize to:

```json
{
  "feedback_id": "fb_001",
  "source": "reddit|google_play|app_store|forum",
  "source_type": "discussion|review",
  "date": "2026-01-01T00:00:00Z",
  "text": "string",
  "url": "string",
  "rating": 1,
  "engagement": {
    "score": 0,
    "comments": 0,
    "thumbs_up": 0
  },
  "metadata": {
    "subreddit": "spotify",
    "query_used": "Spotify recommendations repetitive"
  }
}
```

Raw feedback does **not** get a confidence score.

---

## 8. Processing Pipeline

### Step 1 — Normalize
Convert source-specific fields to raw feedback schema.

### Step 2 — Clean
- Remove empty feedback.
- Normalize whitespace.
- Remove obvious spam/noise.
- Preserve original text for quotes.
- Optionally filter non-English content if language detection is available.

### Step 3 — Relevance filter
Keep only feedback relevant to locked scope.

For Spotify Music Discovery, relevant examples:
- recommendations
- music discovery
- playlist discovery
- personalization
- algorithm
- Discover Weekly
- Release Radar
- finding new artists
- repetitive recommendations
- mood/context discovery
- exploration outside existing taste

Excluded examples:
- billing
- pricing
- podcasts only
- account login
- pure playback bugs unless connected to discovery
- playlist cover editing

Implementation guidance:
- Start with keyword/rule-based relevance for MVP.
- Require stronger Spotify-specific anchors for discussion sources so generic music chatter is excluded.
- Allow positive validation to remain as evidence, but prioritize complaints, requests, frustrations, and unmet-need language as stronger opportunity signals.
- Add `relevance_score` if using embeddings or keyword scoring.
- Store why an item was included/excluded if debug is true.

### Step 4 — Deduplicate
Remove:
- exact duplicates
- normalized duplicates
- near duplicates

Suggested implementation:
- exact hash of raw text
- normalized hash of cleaned text
- TF-IDF cosine similarity threshold for near duplicates
- Preserve duplicate-pressure counts even when near duplicates are collapsed for analysis, so repeated dissatisfaction is not lost as a scale signal.

### Step 5 — Cluster
Cluster semantically similar feedback.

Acceptable MVP approaches:
- TF-IDF vectorization + KMeans/Agglomerative clustering
- Sentence embeddings + clustering if feasible
- Keyword-assisted grouping as fallback

Cluster naming:
- Generate deterministic cluster names using top keywords + representative examples.
- Avoid using LLM in backend unless deliberately added.
- If cluster naming is weak, backend can provide keyword-based names and GPT can refine them in report.
- Preserve mixed positive and negative evidence inside the same theme instead of forcing everything into pure pain buckets.
- Cluster frequency should reflect deduplicated thematic evidence, while duplicate-pressure metrics remain available separately.

### Step 6 — Representative quotes
For each cluster, return 3–5 representative quotes.

Rules:
- Do not invent quotes.
- Preserve source URL when available.
- Prefer quotes with enough context and relevance.
- When ranking quotes for PM review, prioritize pain points, requests, unmet needs, and workaround signals over generic praise.

### Step 7 — Metrics
Generate counts/distributions.

### Step 8 — Chart data
Generate chart-ready JSON. Backend only prepares data; GPT/report layer decides presentation.

---

## 9. Feedback Cluster Schema

```json
{
  "cluster_id": "cluster_001",
  "cluster_name": "Repetitive recommendations",
  "cluster_summary": "Users complain that Spotify repeatedly recommends the same artists, genres, or songs.",
  "frequency": 128,
  "dominant_signal": "pain|positive|mixed",
  "pain_point_evidence_count": 110,
  "positive_validation_count": 18,
  "request_signal_count": 22,
  "mixed_signal_flag": true,
  "source_distribution": {
    "reddit": 58,
    "google_play": 50,
    "app_store": 20
  },
  "time_distribution": {
    "2026-01": 14,
    "2026-02": 18
  },
  "representative_quotes": [
    {
      "text": "string",
      "source": "reddit",
      "url": "string",
      "date": "2026-01-01T00:00:00Z"
    }
  ],
  "example_feedback_ids": ["fb_001", "fb_002"],
  "keywords": ["recommendations", "same", "repetitive"],
  "relevance_score": 0.91
}
```

---

## 10. Metrics Schema

```json
{
  "total_records_collected": 1000,
  "records_after_cleaning": 900,
  "records_relevant": 520,
  "records_after_deduplication": 470,
  "exact_duplicates_removed": 12,
  "normalized_duplicates_removed": 9,
  "near_duplicates_removed": 29,
  "cluster_count": 18,
  "dominant_signal_distribution": {
    "pain": 10,
    "positive": 4,
    "mixed": 4
  },
  "source_distribution": {
    "reddit": 200,
    "google_play": 220,
    "app_store": 100
  },
  "rating_distribution": {
    "1": 120,
    "2": 80,
    "3": 90,
    "4": 100,
    "5": 130
  },
  "top_clusters": [
    {
      "cluster_id": "cluster_001",
      "cluster_name": "Repetitive recommendations",
      "frequency": 128
    }
  ]
}
```

---

## 11. Charts Data Schema

```json
{
  "feedback_by_source": [
    {"source": "reddit", "count": 200},
    {"source": "google_play", "count": 220},
    {"source": "app_store", "count": 100}
  ],
  "feedback_over_time": [
    {"month": "2026-01", "count": 80},
    {"month": "2026-02", "count": 95}
  ],
  "top_clusters": [
    {"cluster_name": "Repetitive recommendations", "frequency": 128},
    {"cluster_name": "Poor discovery control", "frequency": 90}
  ],
  "rating_distribution": [
    {"rating": "1", "count": 120},
    {"rating": "2", "count": 80}
  ],
  "source_distribution_by_cluster": [
    {
      "cluster_name": "Repetitive recommendations",
      "reddit": 58,
      "google_play": 50,
      "app_store": 20
    }
  ],
  "cluster_signal_distribution": [
    {"signal": "pain", "count": 10},
    {"signal": "positive", "count": 4},
    {"signal": "mixed", "count": 4}
  ]
}
```

---

## 12. Source Summary Schema

```json
{
  "source_name": "Reddit",
  "source_type": "discussion",
  "queries_used": ["Spotify music discovery", "Spotify recommendations repetitive"],
  "records_collected": 120,
  "records_relevant": 72,
  "date_range": {
    "start": "2025-06-01",
    "end": "2026-06-01"
  },
  "notes": "Collected public posts/comments related to recommendations and discovery."
}
```

---

## 13. Custom GPT Instructions — Full Prompt

Codex must create `docs/custom_gpt_instructions.md` with the following content, adapted only for formatting if needed.

```text
You are AI Product Discovery Copilot, a PM research assistant for analyzing public user feedback and generating opportunity insights.

Your job is to help a PM move from public user feedback to opportunity validation planning.

You must not generate final problem statements, PRDs, MVP ideas, roadmaps, or solution concepts in Phase 1. Phase 1 ends at opportunity ranking and interview validation briefs.

Core workflow:
1. Clarify the research brief.
2. Call the backend action only after the required brief fields are locked.
3. Use backend output as the only source of quantitative evidence.
4. Generate a PM research report with metrics, charts, source coverage, representative quotes, and confidence rationale.
5. Generate opportunity validation briefs for recommended opportunities.

Required brief fields:
- product
- research_scope
- research_goal
- analysis_time_window
- included_topics
- excluded_topics

If any required field is missing or ambiguous, ask a targeted clarification question. Do not call the backend until the brief is complete.

Default guidance:
- For strategic opportunity discovery, suggest a 12-month time window if the user does not specify one.
- Ask for confirmation before using defaults.
- For Spotify music discovery, included topics may include recommendations, music discovery, personalization, artist discovery, playlist discovery, Discover Weekly, Release Radar.
- For Spotify music discovery, excluded topics may include pricing, billing, podcasts, account settings, playlist cover editing, pure playback bugs.

After the backend returns data, never invent counts, quotes, source coverage, or metrics.

Report structure:
1. Executive Summary
2. Source Summary
3. User Segments
4. JTBDs
5. Needs
6. Discovery Journey Analysis
7. Pain Points
8. Workarounds
9. Contradictions & Tensions
10. Opportunity Areas
11. Opportunity Ranking
12. Metrics & Charts
13. Recommended Opportunity Validation Briefs
14. Suggested Interview Recruitment Criteria
15. Suggested Interview Areas
16. Appendix: Evidence Samples

Evidence rule:
Every major insight must include supporting evidence from backend clusters, metrics, source coverage, and representative quotes.

Segmentation rule:
Segments must emerge from data. Do not invent decorative personas. Segment users based on discovery intent, discovery behavior, engagement level, pain patterns, and workaround behavior.

Opportunity rule:
Do not treat complaints as opportunities. Convert needs + pain points into opportunity statements.
Do not let positive validation inflate opportunity frequency. If positive and negative evidence discuss the same theme, treat that as mixed evidence and reduce the strength of the opportunity recommendation relative to a pure pain-signal cluster.

Opportunity ranking framework:
Opportunity Strength dimensions:
- Frequency
- Severity
- JTBD Importance
- Opportunity Gap
- Workaround Strength

Solution Potential dimensions:
- AI Leverage
- Segment Coverage

All opportunities remain in the report. Ranking is for recommendation, not filtering.

Confidence framework:
Confidence applies only to inferred insights such as segments, JTBDs, needs, pain points, and opportunities. It does not apply to individual feedback items.
Use High / Medium / Low confidence labels, supported by source coverage, evidence volume, evidence depth, recency, consistency, and caveats.

Interview planning rule:
Generate validation briefs for recommended top opportunities. Use recommendation language, not instruction language.
Say "Suggested recruitment criteria" and "Suggested interview areas", not "Recruit these users" or "Ask these questions".

The segment for interviews should come from the selected opportunity. Interviews should be conducted with users belonging to the primary affected segment.

Do not finalize the problem statement before interviews.
Do not propose MVP solutions in Phase 1.
Do not hide source failures or limitations.
If the backend returns partial results, disclose the limitation clearly.
```

---

## 14. Custom GPT Prompt Chain

The GPT should follow this staged chain internally.

### Stage 0 — Brief clarification
Input: user request.
Output: locked brief.

Prompt behavior:
- Extract product, research scope, research goal, time window, included topics, excluded topics.
- Ask user only for missing/ambiguous fields.
- Confirm defaults.

Example clarification:
> I can analyze Spotify's music discovery experience. To scope this properly, I will use Opportunity Discovery as the goal and last 12 months as the default time window. Should I proceed with that, and should I exclude podcasts, billing, pricing, and account issues?

### Stage 1 — Backend action call
Call `/analyze-feedback` with locked brief.

### Stage 2 — Source summary interpretation
Summarize:
- sources collected
- records collected
- relevant records
- date range
- failed sources
- warnings

### Stage 3 — Cluster interpretation
For each major cluster, identify:
- theme
- frequency
- source spread
- representative evidence
- likely discovery journey stage

### Stage 4 — JTBD extraction
For each JTBD:
- JTBD statement
- supporting clusters
- evidence count
- source coverage

### Stage 5 — Need extraction
For each need:
- need statement
- linked JTBD
- linked clusters
- supporting quotes

### Stage 6 — Segmentation
For each segment:
- segment name
- behavioral characteristics
- estimated size based on clusters
- primary JTBDs
- top pain points
- supporting clusters
- source coverage

### Stage 7 — Pain point and workaround analysis
For each pain point:
- pain point statement
- frequency signal
- severity signal
- associated segment
- associated JTBD
- supporting quotes

For each workaround:
- workaround
- effort required
- associated pain point
- evidence support

### Stage 8 — Contradiction detection
Identify tensions, for example:
- personalization vs novelty
- convenience vs control
- passive listening vs active exploration

### Stage 9 — Opportunity mining
For each opportunity:
- opportunity name
- opportunity statement
- linked need
- linked pain point
- primary segment
- supporting evidence

### Stage 10 — Opportunity ranking
Score each opportunity qualitatively High/Medium/Low or 1–5 on:
- Frequency
- Severity
- JTBD Importance
- Opportunity Gap
- Workaround Strength
- AI Leverage
- Segment Coverage

Generate:
- Opportunity Strength
- Solution Potential
- Overall recommendation rationale

### Stage 11 — Interview planning
For recommended opportunities, generate:
- validation objectives
- descriptive hypotheses
- behavioral hypotheses
- outcome hypotheses
- suggested recruitment criteria
- suggested interview areas
- confirming signals
- refuting signals

### Stage 12 — Report generation
Generate final report with all required sections, metrics, charts, quotes, and caveats.

---

## 15. GPT Output Quality Bar

The final GPT output must be detailed. It must not be a short summary.

It should look like a PM research artifact, not a chatbot answer.

Must include:
- tables
- chart-ready summaries
- counts
- source distribution
- quotes
- ranking rationale
- caveats
- interview validation briefs

---

## 16. OpenAPI Schema Requirement

Codex must generate `docs/openapi_schema.yaml` for Custom GPT Actions.

It must define:
- endpoint `/analyze-feedback`
- request schema
- success response schema
- error response schema
- field descriptions

Use OpenAPI 3.1.0 if possible.

---

## 17. Non-Functional Requirements

- Simple and reliable.
- Easy to deploy.
- Clear logs or processing notes.
- Fail gracefully if one source fails.
- Do not block entire run if one source fails.
- Return partial results with warnings.
- Complete within reasonable demo time.
- No silent sampling.
- No invented data.
- Avoid overengineering.

---

## 18. Suggested Tech Stack

- Python
- FastAPI
- pandas
- scikit-learn
- google-play-scraper
- requests/httpx
- BeautifulSoup if needed
- Uvicorn
- sentence-transformers optional, only if feasible

Deployment options:
- Render
- Railway
- Replit
- Fly.io

---

## 19. Phase-Wise Development Plan

### Phase 1 — API Skeleton
Deliver:
- FastAPI app
- `/health`
- `/analyze-feedback`
- request validation
- mock response matching schema
- tests

### Phase 2 — Google Play Collector
Deliver:
- Spotify reviews collector
- normalized raw feedback
- unit test

### Phase 3 — Reddit Collector
Deliver:
- query generation
- Reddit feedback collection
- normalized posts/comments
- failure handling

### Phase 4 — App Store Collector
Deliver:
- App Store review collection attempt
- graceful failure
- normalized reviews if available

### Phase 5 — Cleaning and Relevance Filtering
Deliver:
- cleaner
- relevance filter
- Spotify-specific anchor checks for discussion sources
- included/excluded logic
- opportunity-oriented weighting that surfaces pain points and requests ahead of generic praise
- tests

### Phase 6 — Deduplication
Deliver:
- exact duplicate removal
- normalized duplicate removal
- near duplicate removal
- duplicate-pressure counts preserved in output for later prioritization
- tests

### Phase 7 — Clustering
Deliver:
- clustering module
- deterministic cluster names
- cluster summaries
- mixed-signal preservation inside themes
- representative quote ranking per cluster
- representative quotes
- tests

### Phase 8 — Metrics and Chart Data
Deliver:
- source summary
- processing summary
- metrics
- chart-ready JSON
- cluster-aware signal distributions and internally consistent top-cluster outputs

### Phase 9 — End-to-End Pipeline
Deliver:
- full `/analyze-feedback` connected
- warnings and processing notes
- sample response

### Phase 10 — Custom GPT Integration
Deliver:
- OpenAPI schema
- custom GPT instructions
- README instructions for GPT setup

---

## 20. Codex Deliverables

Codex must produce:
1. `docs/architecture.md`
2. working FastAPI backend
3. modular collectors
4. processing pipeline
5. API response matching schema
6. OpenAPI schema
7. Custom GPT instruction draft
8. README with setup and deployment steps
9. tests for validation, relevance, dedupe, clustering
10. sample request and sample response

---

## 21. Guardrails

- Do not change PM strategy.
- Do not decide a new product direction.
- Do not generate Phase 2 product ideas.
- Do not remove metrics or charts.
- Do not invent quotes.
- Do not invent source counts.
- Do not silently drop failed sources.
- Do not silently sample without disclosure.
- Do not force all analysis into backend; GPT handles PM synthesis.
- Backend returns evidence; GPT performs PM interpretation.

---

## 22. Success Criteria

The implementation is successful when:
1. `/health` returns healthy status.
2. `/analyze-feedback` accepts the Spotify music discovery brief.
3. Backend returns structured clusters and metrics.
4. Source failures are handled gracefully.
5. Output can be used by Custom GPT to generate a report.
6. No manual CSV upload is required.
7. OpenAPI schema can be added to Custom GPT Actions.
8. Custom GPT instructions are complete enough to run the prompt chain.
9. The final output supports detailed PM analysis with metrics and evidence.
