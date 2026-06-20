# AI Product Discovery Copilot Architecture

## 1. System Architecture

### 1.1 Objective
Phase 1 delivers a backend-powered research workflow for analyzing public feedback about Spotify's music discovery experience and returning structured evidence that a Custom GPT can use to generate a PM research report, ranked opportunity areas, opportunity validation briefs, and suggested interview planning inputs.

This architecture preserves the product strategy defined in the spec:
- Backend handles collection, cleaning, filtering, deduplication, clustering, metrics, and chart-ready data.
- Custom GPT handles PM reasoning and report generation.
- No manual CSV upload is required.
- Metrics, charts, source summaries, representative quotes, and validation briefs remain mandatory outputs.
- For Custom GPT Action reliability, the backend may compact the transport payload by truncating quote text and limiting returned cluster detail, but it must not remove required output sections or alter the full-result metrics/charts computation.

### 1.2 High-Level Component Model

```text
User
  -> Custom GPT
      -> Clarifies and locks brief
      -> Calls backend POST /analyze-feedback
          -> FastAPI app
              -> Request validation
              -> Source discovery
              -> Collectors
                  -> Reddit
                  -> Google Play
                  -> App Store
              -> Processing pipeline
                  -> Normalize
                  -> Clean
                  -> Relevance filter
                  -> Deduplicate
                  -> Cluster
                  -> Representative quotes
                  -> Metrics
                  -> Chart-ready data
              -> Structured JSON response
      -> PM interpretation and report generation
          -> Source summary
          -> Segments / JTBDs / needs
          -> Opportunity ranking
          -> Validation briefs
```

### 1.3 Runtime Flow
1. User asks the Custom GPT to analyze Spotify's music discovery experience.
2. Custom GPT collects and confirms the required brief fields.
3. Custom GPT calls `POST /analyze-feedback` only after the brief is locked.
4. Backend validates the request and creates a `run_id`.
5. Backend generates source queries from product, scope, goal, included topics, and excluded topics.
6. Backend collects feedback from Reddit, Google Play, and App Store.
7. Backend normalizes all records into one raw feedback schema.
8. Backend runs cleaning, relevance filtering, deduplication, clustering, quote selection, metrics generation, and chart-data generation.
9. Backend returns structured evidence plus warnings, processing notes, diagnostics, and artifact URLs.
10. Custom GPT uses only backend evidence for quantitative claims, then returns the final Markdown report directly in chat as a downloadable Markdown output.

### 1.4 Architectural Boundaries

#### Backend owns
- Input validation
- Source discovery and query generation
- Public feedback collection
- Data normalization
- Data cleaning
- Scope relevance filtering
- Time-window purity enforcement
- Exact and near-duplicate removal
- Clustering quality improvement and semantic cluster merging
- Representative quote extraction
- Source summaries
- Metrics
- Chart-ready JSON
- Quality diagnostics
- Partial failure handling

#### Custom GPT owns
- Brief clarification
- Confirming defaults with the user
- PM interpretation of backend evidence
- Segment/JTBD/need inference
- Opportunity framing and ranking
- Validation brief generation
- Final report structure and narrative

### 1.5 Deployment Shape
- One deployable FastAPI backend service.
- One Custom GPT configured with:
  - Action schema for `POST /analyze-feedback`
  - Instruction prompt enforcing brief-locking and evidence-based output
- No separate frontend is required for Phase 1.

### 1.6 Phase 1 Scope Boundary
The architecture supports the full end-state workflow, but implementation begins with the spec's Phase 1 deliverable:
- FastAPI app
- `GET /health`
- `POST /analyze-feedback`
- request validation
- mock response matching schema
- tests

The remaining modules are still designed now so later phases can be added without changing the PM workflow.

## 2. Backend Module Design

### 2.1 Target Repository Layout

```text
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
```

### 2.2 Module Responsibilities

#### `app/main.py`
- FastAPI application entrypoint
- route registration
- health endpoint
- analyze endpoint
- exception handling and HTTP error mapping

#### `app/schemas.py`
- Pydantic request/response models
- validation rules for required brief fields
- schema definitions for:
  - locked brief
  - source summary
  - processing summary
  - machine-readable source warning semantics
  - feedback clusters
  - metrics
  - charts data
  - representative quotes
  - warnings and error responses

#### `app/config.py`
- runtime configuration
- source toggles
- default limits/timeouts
- debug behavior
- optional credentials or environment-driven settings

#### `app/collectors/reddit.py`
- generate or consume Reddit search queries from source discovery
- collect publicly accessible Reddit discussions related to locked scope across multiple query-driven search passes
- normalize Reddit-specific fields into raw feedback input format
- deduplicate overlapping results returned by different search queries
- apply per-query retry and backoff behavior on short-lived rate limits
- cap each run to a smaller prioritized public-query set
- cache recent public-query results on disk to reduce repeated live hits
- stop early after repeated public RSS rate limits to avoid long hangs
- preserve already collected Reddit results when later queries fail
- return warnings instead of crashing the full run when Reddit fails

#### `app/collectors/google_play.py`
- collect Spotify Android reviews
- continue through review pages with continuation tokens until exhaustion or source cap
- normalize source-specific review fields
- disclose source limitations when package/API behavior constrains coverage

#### `app/collectors/app_store.py`
- collect Spotify iOS reviews where feasible
- iterate paginated public RSS review pages until exhaustion or source cap
- normalize fields into raw feedback format
- fail gracefully and allow partial success

#### `app/processing/cleaner.py`
- remove empty/noisy records
- normalize whitespace and text artifacts
- preserve original quote-safe text
- optionally support non-English filtering when feasible

#### `app/processing/relevance.py`
- implement rule-based relevance filtering for MVP
- apply included/excluded topic logic
- optionally attach `relevance_score`
- optionally record include/exclude reasons in debug mode

#### `app/processing/dedupe.py`
- exact deduplication
- normalized-text deduplication
- near-duplicate detection using TF-IDF similarity threshold

#### `app/processing/clustering.py`
- vectorize relevant feedback
- cluster semantically similar records
- derive deterministic cluster names from keywords/examples
- generate cluster summaries without shifting PM reasoning into the backend
- select representative quotes per cluster
- preserve mixed positive and negative evidence within the same theme via cluster-level signal counts and flags

#### `app/processing/metrics.py`
- processing counters
- source distribution
- rating distribution
- cluster frequencies
- chart-ready aggregation outputs

#### `app/services/source_discovery.py`
- generate source queries dynamically from locked brief fields
- avoid hardcoding a single subreddit or single fixed search path
- provide query metadata for auditing and source summaries

#### `app/services/pipeline.py`
- orchestrate the end-to-end run
- execute source collection in parallel, then run downstream processing stages in order
- accumulate warnings and processing notes
- determine `completed` vs `partial_success`
- build the final response payload
- stop per-source collection only when the source is exhausted, inaccessible, or reaches a documented source cap
- preserve partial source evidence when later pages or queries are rate-limited
- treat partial source degradation as warnings when usable records were still collected; reserve run-level partial success for full source outages
- apply runtime-aware source caps for interactive requests and disclose them explicitly to avoid silent sampling
- expand Google Play and App Store coverage before analysis when relevant in-window evidence is too thin
- keep Reddit as a depth source, not the primary scale source

#### `app/utils/dates.py`
- relative time window parsing
- date normalization and bucketing for chart data

#### `app/utils/text.py`
- shared text normalization helpers
- keyword normalization
- quote-safe trimming helpers

#### `app/utils/ids.py`
- deterministic or stable-enough IDs for:
  - `run_id`
  - `feedback_id`
  - `cluster_id`

### 2.3 Internal Data Shapes

#### Request brief
Locked strategic input from the Custom GPT. The backend must validate but must not invent missing strategy fields.

#### Raw feedback item
Canonical normalized record created after collection, before PM inference.

#### Processed feedback item
Intermediate internal structure that may include cleaned text, relevance flags, dedupe markers, cluster assignment, and optional debug notes.

#### Cluster artifact
Backend evidence object containing frequency, source distribution, time distribution, keywords, representative quotes, and example feedback IDs.

#### Final analysis response
Strict JSON contract returned to the Custom GPT for report generation, plus artifact URLs for deep evidence retrieval.

## 3. API Contract

### 3.1 Endpoints

#### `GET /health`
Purpose:
- simple health verification for deployment and tests

Expected behavior:
- returns a healthy status payload
- does not depend on external collectors being available

#### `POST /analyze-feedback`
Purpose:
- accept a locked PM research brief
- run the collection and analysis pipeline
- return a compact structured payload for the Custom GPT
- persist full evidence artifacts for later retrieval

#### `GET /runs/{run_id}/manifest`
Purpose:
- return the artifact manifest for a completed run

#### `GET /runs/{run_id}/artifact/{artifact_name}`
Purpose:
- return a known artifact file for a completed run
- expose full evidence without forcing it into a single GPT payload

#### `POST /runs/{run_id}/final-report`
Purpose:
- save the final GPT-generated Markdown report as `final_report.md`

### 3.2 Request Contract

Required body:

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
  "research_questions": [
    "Why do users struggle to discover new music?",
    "What are the most common frustrations with recommendations?"
  ],
  "success_criteria": [
    "Improve meaningful music discovery",
    "Reduce repetitive listening",
    "Improve recommendation relevance and novelty balance"
  ],
  "max_runtime_seconds": 120,
  "debug": false
}
```

Validation rules:
- `product`, `research_scope`, `research_goal`, and `analysis_time_window` are required.
- `success_criteria` is required and must be locked by the GPT before the backend call.
- Backend must not guess missing strategic fields.
- Backend must never infer or default `success_criteria`.
- malformed time window returns validation error.
- empty `included_topics` or `excluded_topics` are allowed, but must generate warnings.

### 3.3 Success Contract

```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "locked_brief": {},
  "source_summary": [],
  "processing_summary": {},
  "research_question_coverage": [],
  "feedback_clusters": [],
  "metrics": {},
  "charts_data": {},
  "representative_quotes": [],
  "compact_gpt_payload": {},
  "artifact_manifest": {},
  "processing_notes": [],
  "source_limitations": [],
  "warnings": []
}
```

Required response characteristics:
- structured JSON only
- includes metrics and chart-ready data
- includes source summaries
- includes representative quotes
- includes research-question coverage
- includes artifact manifest
- includes warnings and notes
- contains no invented counts or quotes
- may compact transport-heavy fields for Action reliability, with explicit disclosure in warnings or processing notes

### 3.4 Partial Success Contract
If one or more sources fail, the backend must still return usable evidence from successful sources.

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
  "warnings": [
    "App Store collection failed; results use Reddit and Google Play only."
  ]
}
```

### 3.5 Error Contract

```json
{
  "status": "error",
  "error_type": "validation_error",
  "message": "Missing required field: research_scope",
  "missing_fields": ["research_scope"]
}
```

Design rules:
- validation errors are explicit
- source failures are warnings, not fatal request errors
- hard failures should be reserved for invalid input or unrecoverable internal errors

### 3.6 Schema Coverage Expectations
The response schema must support the downstream GPT requirements for:
- source summary interpretation
- cluster interpretation
- JTBD and need inference
- segmentation
- pain points and workarounds
- opportunity mining and ranking
- interview validation briefs
- metrics and chart presentation

## 4. Data Pipeline

### 4.1 Pipeline Stages

#### Stage 1: Request validation
- validate required brief fields
- validate time window shape
- register warnings for empty topic lists

#### Stage 2: Source discovery
- generate dynamic search queries from:
  - product
  - research scope
  - research goal
  - included topics
  - excluded topics
- attach queries used for traceability and source summaries

#### Stage 3: Collection
- collect from Reddit
- collect from Google Play
- collect from App Store
- isolate source failures and convert them to warnings

#### Stage 4: Normalization
Normalize each collected item to the raw feedback schema:

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

Important rule:
- raw feedback items do not get confidence scores

#### Stage 5: Cleaning
- remove empty feedback
- normalize whitespace
- remove obvious spam/noise
- preserve original text for quote usage
- optionally filter non-English if feasible

#### Stage 6: Relevance filtering
- keep only feedback related to the locked research scope
- begin with keyword/rule-based logic for MVP
- require Spotify-specific product anchors for discussion sources so broad music chatter does not pass as product evidence
- apply included and excluded topic rules
- score discovery intent separately from generic product discussion
- prioritize complaints, requests, frustrations, and workaround-style language as stronger opportunity signals
- allow positive validation to remain as supporting evidence, but not as a direct opportunity-frequency booster
- optionally record reasons in debug mode

#### Stage 7: Deduplication
- exact raw-text hash removal
- normalized-text hash removal
- near-duplicate removal via TF-IDF cosine similarity threshold
- preserve duplicate-pressure counts in the response so repeated dissatisfaction remains visible even when analysis uses a unique canonical set

#### Stage 8: Clustering
- group semantically similar relevant feedback
- use TF-IDF + clustering for MVP, with keyword fallback if needed
- produce deterministic cluster names
- keep PM interpretation out of the backend
- preserve mixed positive and negative evidence on the same theme so later opportunity ranking can reduce weight when validation and pain signals conflict

#### Stage 9: Representative quotes
- return 3 to 5 quotes per cluster when available
- preserve source URL and date
- never invent quotes
- prefer quotes with stronger opportunity signal over generic praise when ranking evidence for PM review

#### Stage 10: Metrics and chart data
Generate:
- processing counters
- source distribution
- rating distribution
- top clusters
- feedback over time
- source distribution by cluster
- cluster dominant-signal distribution

#### Stage 11: Final response assembly
Build:
- `locked_brief`
- `source_summary`
- `processing_summary`
- `feedback_clusters`
- `metrics`
- `charts_data`
- `representative_quotes`
- `processing_notes`
- `warnings`

### 4.2 Processing Summary Expectations
The processing summary should help the GPT explain:
- how much data was collected
- how much was removed during cleaning
- how much remained after relevance filtering
- how much remained after deduplication
- whether any source coverage gaps or limitations exist

### 4.3 Observability and Traceability
Each run should expose enough notes to explain:
- which sources were attempted
- which queries were used
- which sources failed
- whether debug information was requested
- what major filtering behavior occurred

This supports evaluator trust and aligns with the spec's no-silent-failure rule.

## 5. Custom GPT Integration

### 5.1 Integration Model
The Custom GPT is the primary user interface. It must not upload files manually or rely on offline handoff. Instead:
- user provides the research request conversationally
- GPT clarifies and locks the brief
- GPT may infer likely success criteria from the user prompt, but must ask for confirmation before calling the backend
- GPT calls the backend action
- GPT synthesizes from the compact payload first
- GPT fetches deeper evidence artifacts only when needed
- GPT transforms backend evidence into the PM artifact
- GPT saves the final Markdown report back to the backend as `final_report.md`

### 5.2 Required GPT Behavior
- Ask targeted clarification questions for missing or ambiguous brief fields.
- Suggest the 12-month window only as a default and ask for confirmation.
- Do not call the backend until the brief is complete.
- Use backend output as the only source of quantitative evidence.
- Disclose partial results, failed sources, and caveats.
- Do not generate final problem statements, PRDs, MVP concepts, or roadmaps in Phase 1.

### 5.3 Action Contract
The Custom GPT Action will point to the backend `POST /analyze-feedback` endpoint and use the OpenAPI schema generated later in the implementation sequence.

The action payload should mirror the locked brief exactly. The GPT should not transform strategic intent into a different product scope.

### 5.4 Backend-to-GPT Handoff
The backend is intentionally evidence-oriented. It returns:
- source coverage
- research-question coverage
- compact top clusters
- compact top opportunities
- evidence-backed segments
- compact metrics and chart summaries
- quotes
- artifact manifest for full evidence retrieval
- warnings and source limitations

The GPT then performs:
- JTBD extraction
- segmentation
- needs analysis
- pain point analysis
- contradiction analysis
- opportunity mining
- opportunity ranking
- validation brief generation

### 5.5 Failure and Caveat Behavior
If the backend returns partial results:
- GPT must disclose the limitation clearly
- GPT must avoid overstating confidence
- GPT must still use available evidence for the report

## 6. Phase-Wise Implementation Plan

### 6.1 Guiding Principle
Implementation must be phased and testable after each phase. Earlier phases establish the contract and scaffolding so later work can be added without changing the PM workflow.

### 6.2 Planned Phases

#### Phase 1: API Skeleton
Deliver:
- FastAPI app
- `GET /health`
- `POST /analyze-feedback`
- request validation
- mock response matching schema
- tests

Testability:
- health endpoint test
- request validation tests
- contract-level response shape tests

#### Phase 2: Google Play Collector
Deliver:
- Spotify review collector
- raw feedback normalization
- unit test

Testability:
- collector returns normalized records
- source warning behavior is visible when collection is constrained

#### Phase 3: Reddit Collector
Deliver:
- query generation integration
- Reddit feedback collection
- normalized discussion records
- graceful failure handling

Testability:
- source discovery output test
- collector normalization test
- failure-to-warning behavior test

#### Phase 4: App Store Collector
Deliver:
- App Store review collection attempt
- graceful failure path
- normalized records if available

Testability:
- collector interface test
- partial success behavior test when App Store is unavailable

#### Phase 5: Cleaning and Relevance Filtering
Deliver:
- cleaner
- rule-based relevance filter
- Spotify-specific anchor checks for discussion sources
- included/excluded topic logic
- opportunity-oriented weighting so pain points and requests surface ahead of generic praise
- tests

Testability:
- empty/noise removal test
- relevance inclusion/exclusion tests
- off-topic Reddit false-positive rejection test
- problem-signal prioritization test

#### Phase 6: Deduplication
Deliver:
- exact duplicate removal
- normalized duplicate removal
- near-duplicate removal
- duplicate-pressure counts preserved for downstream prioritization
- tests

Testability:
- exact duplicate test
- normalized duplicate test
- similarity-threshold dedupe test

#### Phase 7: Clustering
Deliver:
- clustering module
- deterministic cluster names
- cluster summaries
- mixed-signal preservation inside theme clusters
- representative quotes
- tests

Testability:
- cluster formation test
- mixed-signal cluster test
- representative quote selection test

#### Phase 8: Metrics and Chart Data
Deliver:
- source summary
- processing summary
- metrics
- chart-ready JSON
- cluster-aware signal distributions and consistency checks across summaries, metrics, and charts

Testability:
- metrics schema tests
- chart-data aggregation tests

#### Phase 9: End-to-End Pipeline
Deliver:
- full pipeline connected to `/analyze-feedback`
- warnings and processing notes
- sample response

Testability:
- end-to-end response contract test
- partial-success path test

#### Phase 10: Custom GPT Integration
Deliver:
- OpenAPI schema
- Custom GPT instructions
- README guidance for GPT setup

Testability:
- OpenAPI validity check
- prompt completeness review against the spec

### 6.3 Current Execution Rule
Per the user instruction, implementation must stop after `docs/architecture.md` is completed and wait for approval before Phase 1 application code is written.

## 7. Risks and Fallback Behavior

### 7.1 Source Availability Risk
Risk:
- Reddit, App Store, or Google Play collection may fail or return uneven coverage.

Fallback:
- continue with remaining sources
- return `partial_success`
- add explicit warnings
- keep source summary honest about missing coverage

### 7.2 Query Coverage Risk
Risk:
- dynamic search queries may miss relevant conversations or over-collect noisy ones.

Fallback:
- keep query generation auditable through `queries_used`
- use included/excluded topics during relevance filtering
- expose processing notes for coverage limitations

### 7.3 Relevance Precision Risk
Risk:
- rule-based filtering may include false positives or exclude nuanced discovery-related comments.

Fallback:
- start with transparent MVP rules
- add debug explainability when requested
- preserve modular design so scoring can improve later without changing the API

### 7.4 Deduplication Risk
Risk:
- near-duplicate thresholds may over-merge distinct feedback or under-merge repeated complaints.

Fallback:
- separate exact, normalized, and near-duplicate steps
- keep thresholds configurable
- test against curated duplicate examples

### 7.5 Clustering Quality Risk
Risk:
- unsupervised clustering can create weak or mixed clusters.

Fallback:
- use deterministic keyword-based naming
- provide evidence-rich clusters even if names are imperfect
- let the GPT refine narrative phrasing while preserving backend evidence

### 7.6 Demo-Time Runtime Risk
Risk:
- multi-source collection and processing may exceed a comfortable demo runtime.

Fallback:
- keep MVP implementation simple
- support `max_runtime_seconds`
- prioritize partial usable output over full failure
- avoid silent sampling

### 7.7 PM Strategy Drift Risk
Risk:
- implementation may accidentally shift reasoning into the backend or introduce Phase 2 product work.

Fallback:
- keep backend evidence-only
- keep PM synthesis inside the GPT
- enforce report guardrails in GPT instructions and API contract design

### 7.8 Evidence Integrity Risk
Risk:
- generated reports could overstate confidence or invent evidence if the contract is loose.

Fallback:
- require source summaries, metrics, quotes, charts, and warnings in the backend response
- ensure the GPT instruction prompt explicitly forbids invented counts, quotes, and hidden failures

### 7.9 No-Frontend Constraint Risk
Risk:
- evaluators may expect a UI beyond the Custom GPT.

Fallback:
- use the Custom GPT link as the primary interface
- keep the backend deployable and testable independently via `/health` and `/analyze-feedback`

## Conclusion
This architecture preserves the exact Phase 1 strategy in the spec: the backend produces reliable evidence artifacts, the Custom GPT performs PM reasoning, and the workflow remains evaluator-friendly, phased, testable, and deployable without manual CSV uploads or unnecessary frontend scope.
