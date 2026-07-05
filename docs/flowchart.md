# AI Product Discovery Copilot Flow Chart

This document shows the current end-to-end workflow for the async AI Product Discovery Copilot, including the Custom GPT interaction loop, backend analysis pipeline, artifact generation, and evidence retrieval path.

## 1. End-to-End Workflow

```mermaid
flowchart TD
    U[User submits research request] --> G0[Custom GPT / Agent 0]

    G0 --> D0[Infer draft brief from prompt]
    D0 --> B1{Are all required brief fields locked?}

    B1 -- No --> Q1[Ask user follow-up questions]
    Q1 --> L1[Update locked brief]
    L1 --> B1

    B1 -- Yes --> C0[Show full locked brief]
    C0 --> C1{User said go ahead?}
    C1 -- No --> C2[Apply user edits]
    C2 --> C0
    C1 -- Yes --> A1[POST /analyze-feedback/start]
    A1 --> R1[Backend validates request]
    R1 --> R2[Create run_id and queued status]
    R2 --> R3[Return run_id, status, ETA minutes]

    R3 --> G1[GPT reads run_id and ETA]
    G1 --> P1[GET /runs/{run_id}/status?wait_seconds=35]
    P1 --> B2{Run completed?}

    B2 -- No --> G2[GPT tells user analysis is still processing and shares conservative ETA in minutes]
    G2 --> U2[User comes back later]
    U2 --> P2[GET /runs/latest/status or GET /runs/{run_id}/status]
    P2 --> B3{Run completed now?}
    B3 -- No --> G2
    B3 -- Yes --> M1[GET /runs/{run_id}/manifest]

    B2 -- Yes --> M1

    M1 --> C1[Read compact_gpt_payload.json first]
    C1 --> E1[Retrieve required evidence artifacts]
    E1 --> S1[GPT answers research questions]
    S1 --> S2[GPT synthesizes segments, JTBDs, needs, pains, contradictions, repeat-listening analysis]
    S2 --> S3[GPT ranks opportunities using evidence artifacts]
    S3 --> S4[GPT writes final Markdown report in chat]
    S4 --> U3[User receives downloadable Markdown-style output in chat]
```

## 2. Brief Locking Flow

```mermaid
flowchart TD
    A[Incoming user prompt] --> B[Extract candidate brief fields]
    B --> B2[Infer likely missing fields]
    B2 --> C{Missing or ambiguous fields?}

    C -- Yes --> D[Ask targeted follow-up question]
    D --> E[User clarifies]
    E --> B

    C -- No --> F[Present full locked brief]
    F --> G{User says go ahead?}
    G -- No --> H[Revise locked brief with user]
    H --> F
    G -- Yes --> J[Locked brief complete]

    J --> K[Required fields locked and approved]
    K --> K1[product]
    K --> K2[research_scope]
    K --> K3[research_goal]
    K --> K4[analysis_time_window]
    K --> K5[included_topics]
    K --> K6[excluded_topics]
    K --> K7[research_questions]
    K --> K8[success_criteria]
```

## 3. Async Backend Run Flow

```mermaid
flowchart TD
    S[POST /analyze-feedback/start] --> V[Validate request schema]
    V --> X{Valid?}

    X -- No --> VE[Return 422 validation error with missing fields]

    X -- Yes --> Q[Create run folder and run.log]
    Q --> Q2[Write queued status]
    Q2 --> BG[Submit background worker]
    BG --> ST1[Stage: collecting_sources]
    ST1 --> ST2[Stage: cleaning_feedback]
    ST2 --> ST3[Stage: filtering_relevance]
    ST3 --> ST4[Stage: deduplicating_feedback]
    ST4 --> ST5[Stage: clustering_feedback]
    ST5 --> ST6[Stage: writing_artifacts]
    ST6 --> ST7[Stage: completed or partial_success]
```

## 4. Source Collection Flow

```mermaid
flowchart TD
    CS[Collect sources in parallel] --> GP[Google Play collector]
    CS --> AS[App Store collector]
    CS --> RD[Reddit collector]

    GP --> GP1[Page through reviews until exhausted, timeout, or cap]
    GP1 --> GP2[Normalize into RawFeedbackItem]

    AS --> AS1[Fetch RSS review pages until exhausted, timeout, or cap]
    AS1 --> AS2[Normalize into RawFeedbackItem]
    AS2 --> AS3{App Store page failure?}
    AS3 -- Yes --> ASW[Return warning and continue run]
    AS3 -- No --> ASN[Continue]

    RD --> RD1[Run prioritized public search queries]
    RD1 --> RD2[Use cache when available]
    RD2 --> RD3{429 rate limit?}
    RD3 -- Yes --> RD4[Apply retry + backoff]
    RD4 --> RD5{Still limited?}
    RD5 -- Yes --> RDW[Return partial Reddit data plus warning]
    RD5 -- No --> RD6[Continue collection]
    RD3 -- No --> RD6
    RD6 --> RD7[Normalize into RawFeedbackItem]

    GP2 --> M[Merge all collected records]
    ASN --> M
    ASW --> M
    RD7 --> M
    RDW --> M
```

## 5. Processing Pipeline Flow

```mermaid
flowchart TD
    RF[Raw merged feedback] --> C1[Cleaning and normalization]
    C1 --> TW[Time-window purity filter]
    TW --> REL[Discovery relevance filter]
    REL --> DD[Deduplication]
    DD --> CL[Semantic clustering]
    CL --> QQ[Representative quote selection]
    QQ --> MT[Metrics generation]
    MT --> CH[Chart-ready data generation]
    CH --> RQ[Research-question coverage mapping]
    RQ --> OP[Opportunity traceability and success-criteria impact mapping]
    OP --> SG[Evidence-backed segment generation]
    SG --> QD[Quality diagnostics]
```

## 6. Clustering Logic Flow

```mermaid
flowchart TD
    I1[Relevant deduplicated records] --> T1[Normalize text]
    T1 --> T2[TF-IDF vectorization]
    T2 --> T3[Sparse similarity matrix]
    T3 --> T4[Threshold similarity graph]
    T4 --> T5[Connected component grouping]
    T5 --> T6[Targeted singleton attachment]
    T6 --> T7[Compute cluster keywords]
    T7 --> T8[Compute cluster cohesion]
    T8 --> T9[Assign cluster name and summary]
    T9 --> T10[Sort clusters by frequency]
```

## 7. Artifact Generation Flow

```mermaid
flowchart TD
    P[Processed evidence structures ready] --> A1[Write all_feedback_raw.csv]
    A1 --> A2[Write all_feedback_clean.csv]
    A2 --> A3[Write all_clusters.csv]
    A3 --> A4[Write all_clusters.json]
    A4 --> A5[Write all_clusters_compact.json]
    A5 --> A6[Write source_summary.csv]
    A6 --> A7[Write charts_data.json]
    A7 --> A8[Write quality_diagnostics.json]
    A8 --> A9[Write research_question_coverage.json]
    A9 --> A10[Write opportunity_traceability.json]
    A10 --> A11[Write opportunity_traceability_compact.json]
    A11 --> A12[Write segment_evidence.json]
    A12 --> A13[Write success_criteria_impact_mapping.json]
    A13 --> A14[Write success_criteria_impact_mapping_compact.json]
    A14 --> A15[Write compact_gpt_payload.json]
    A15 --> A16[Write processing_notes.md]
    A16 --> A17[Write evidence_appendix.md]
    A17 --> A18[Manifest becomes available]
```

## 8. GPT Evidence Retrieval Flow

```mermaid
flowchart TD
    M[GET manifest] --> CG[Read compact_gpt_payload.json]
    CG --> REQ[Retrieve required evidence files]

    REQ --> R1[research_question_coverage.json]
    REQ --> R2[all_clusters_compact.json]
    REQ --> R3[charts_data.json]
    REQ --> R4[opportunity_traceability_compact.json]
    REQ --> R5[success_criteria_impact_mapping_compact.json]
    REQ --> R6[segment_evidence.json]
    REQ --> R7[quality_diagnostics.json]

    R1 --> SYN[Evidence-backed synthesis]
    R2 --> SYN
    R3 --> SYN
    R4 --> SYN
    R5 --> SYN
    R6 --> SYN
    R7 --> SYN

    SYN --> OUT[Final PM report and validation briefs]
```

## 9. Failure and Fallback Flow

```mermaid
flowchart TD
    F0[During run] --> F1{Validation failure?}
    F1 -- Yes --> F2[Return 422 and missing fields]

    F1 -- No --> F3{One source fails?}
    F3 -- Yes --> F4[Record warning and continue]
    F4 --> F5[Return partial_success if needed]

    F3 -- No --> F6{Reddit rate limited?}
    F6 -- Yes --> F7[Backoff, reduce intensity, keep partial depth data]
    F7 --> F8[Add source limitation warning]

    F6 -- No --> F9{Tunnel unavailable?}
    F9 -- Yes --> F10[GPT cannot reach backend until tunnel URL is live again]

    F9 -- No --> F11{Run still processing after short poll?}
    F11 -- Yes --> F12[GPT pauses and asks user to return later]
    F12 --> F13[Resume with GET /runs/latest/status]
```

## 10. Key Design Principles Captured by the Flow

- Backend prepares evidence; GPT performs PM reasoning.
- GPT must not call the backend until the full brief is locked.
- GPT must not rank opportunities using compact payload alone.
- Compact payload is the summary layer; artifacts are the deep evidence layer.
- Reddit is treated as a qualitative depth source, not the primary scale source.
- Partial source failures should degrade gracefully, not fail the full run.
- Async execution avoids single-call GPT timeout pressure.
- Final report is returned directly in chat as downloadable Markdown-style output.

## 11. Non-Technical High-Level Version

This version is meant for product, ops, or stakeholder review.

### 11.1 What The AI Does vs What The Backend Does

```mermaid
flowchart LR
    U[User asks for analysis] --> AI1[AI clarifies the brief]
    AI1 --> AI2[AI confirms research questions and success criteria]
    AI2 --> BE1[Backend collects public feedback and prepares evidence]
    BE1 --> AI3[AI reads the evidence]
    AI3 --> AI4[AI answers the research questions]
    AI4 --> AI5[AI identifies and ranks opportunity areas]
    AI5 --> AI6[AI writes the final PM report]
```

### 11.2 Backend Responsibilities

The backend script is responsible for the evidence pipeline only.

```mermaid
flowchart TD
    B1[Receive a fully locked brief] --> B2[Collect reviews and public discussions]
    B2 --> B3[Clean and organize the data]
    B3 --> B4[Filter to only relevant discovery-related feedback]
    B4 --> B5[Remove duplicates while preserving pressure signals]
    B5 --> B6[Group similar feedback into clusters]
    B6 --> B7[Create metrics, charts, diagnostics, and evidence files]
    B7 --> B8[Return a compact summary plus deeper artifacts]
```

### 11.3 AI Responsibilities

The AI is responsible for reasoning, interpretation, and report generation.

```mermaid
flowchart TD
    A1[Understand the user's objective] --> A2[Ask follow-up questions if the brief is incomplete]
    A2 --> A3[Lock the final research brief]
    A3 --> A4[Start the backend analysis]
    A4 --> A5[Wait for the backend to finish and retrieve evidence]
    A5 --> A6[Answer each research question using evidence]
    A6 --> A7[Interpret segments, needs, pain points, and repeat-listening issues]
    A7 --> A8[Rank opportunities]
    A8 --> A9[Write the final PM report and validation briefs]
```

### 11.4 Simple End-to-End Story

```mermaid
flowchart TD
    S1[1. User asks for product discovery analysis] --> S2[2. AI makes sure the brief is complete]
    S2 --> S3[3. Backend gathers and processes public feedback]
    S3 --> S4[4. Backend stores evidence files and summary outputs]
    S4 --> S5[5. AI reads the evidence]
    S5 --> S6[6. AI turns evidence into PM insights and recommendations]
    S6 --> S7[7. User receives the final report]
```

### 11.5 Plain-English Summary

- The backend acts like the research operations engine. It gathers, cleans, filters, groups, and measures the feedback.
- The AI acts like the product researcher. It interprets the prepared evidence, answers the research questions, and writes the final report.
- The backend does not decide the PM strategy or recommendations on its own.
- The AI does not invent evidence on its own. It must use what the backend prepared.
