# FLOWCHARTS

Mermaid diagrams (render in GitHub, VS Code with a Mermaid extension, and most Markdown viewers). Text fallbacks are given where useful. Spec: `.agents/skills/shorts-engine/references/`.

## 1. End-to-end system flow

```mermaid
flowchart TD
  U["User pastes YouTube link and ticks acknowledgement"] --> API["POST /api/jobs"]
  API --> Q["Job queued in SQLite"]
  Q --> W["Worker thread picks job"]
  W --> S1["source_check: metadata, license, heatmap, policy"]
  S1 --> S2["audio_download: 16 kHz mono wav"]
  S2 --> S3["transcribe: faster-whisper large-v3 on CUDA, 30 min chunks"]
  S3 --> S4["tidy transcript: sentences, fillers"]
  S4 --> S5["nominate: Gemini per 20 min chunk"]
  S5 --> S6["refine: trim hook, tail, padding, length"]
  S6 --> S7["judge: Gemini rubric x2, average"]
  S7 --> S8["signals: heatmap, audio energy, speech ratio"]
  S8 --> S9["blend and plan: ALL clips above bar, tiers, dedupe"]
  S9 --> S10["part splitter for long stories"]
  S10 --> S11["risk flags"]
  S11 --> S12["segments: download only needed ranges"]
  S12 --> LOOP{"For each clip, best score first"}
  LOOP --> B1["cut: remove filler and dead air, crossfade"]
  B1 --> B2["layout: gameplay, facecam or talking head"]
  B2 --> B3["captions ASS and SRT, audio clean"]
  B3 --> D1["director: edit list from Gemini or fallback"]
  D1 --> D2["locate targets, track, draw effects"]
  D2 --> P1["final render: captions, loudnorm, NVENC"]
  P1 --> P2["metadata, credit block, thumbnails"]
  P2 --> P3["package folder and checklist"]
  P3 --> LOOP
  LOOP --> DONE["Job status: review"]
  DONE --> R["Review UI: preview, edit text, approve, copy, download"]
  R --> M["User uploads manually"]
```

## 2. Job state machine

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> running: worker picks job
  running --> review: all clips finished
  running --> failed: fatal error
  running --> canceled: user cancels
  running --> queued: restart or Gemini quota pause
  review --> queued: resume or re-plan
  failed --> queued: user retries
  review --> [*]
  failed --> [*]
  canceled --> [*]
```

## 3. Layout decision tree

```mermaid
flowchart TD
  A["Sample frame every 2 s, run face detector"] --> B{"Stable face in 40 percent or more of samples?"}
  B -- no --> G["gameplay: blurred background plus full 16:9 foreground at y 560"]
  B -- yes --> C{"Median face area 6 percent or more and near centre?"}
  C -- yes --> T["talking_head: 9:16 crop following smoothed face"]
  C -- no --> D{"Area 0.4 to 6 percent, in outer border, stable position?"}
  D -- yes --> F["facecam: gameplay panel on top, cam panel below"]
  D -- no --> G
  O["User option overrides auto"] -.-> B
```

## 4. Selection and scoring

```mermaid
flowchart LR
  T["Transcript sentences"] --> N["Gemini nominates moments per chunk"]
  N --> R["Code refines boundaries"]
  R --> J["Gemini judges with rubric, 2 runs"]
  H["YouTube replay heatmap"] --> X["Blend"]
  A["Audio energy"] --> X
  J --> X
  SP["Speech ratio, glossary hits"] --> X
  X --> P["Planner: threshold 60, tiers A 80 and B 70, dedupe, soft cap"]
  P --> Z["Part splitter then risk flags"]
```

## 5. Director and effects

```mermaid
flowchart TD
  W["words.json and clip metadata"] --> G["Gemini director prompt"]
  G -->|valid JSON| V["validate_and_fix: density, safe zone, snapping"]
  G -->|fails 3 times| F["fallback director rules"]
  F --> V
  V --> PT{"Pointer moments?"}
  PT -- yes --> L["Gemini vision locates target box"]
  L --> VR["verify crop"]
  VR -- fail --> DROP["drop arrow"]
  VR -- pass --> TR["CSRT tracker if moving"]
  PT -- no --> E["edit_list.json"]
  TR --> E
  DROP --> E
  E --> C["compositor draws effects on framed video"]
  C --> FX["fx.mp4"]
```

## 6. Packaging and thumbnails

```mermaid
flowchart TD
  C["clip.mp4 passes QA"] --> M["Gemini metadata, 3 titles"]
  M --> CR["credit block from source_info only"]
  C --> TC["thumbnail concept: original artwork idea"]
  TC --> G1{"Gemini image model works?"}
  G1 -- yes --> IMG["generated art"]
  G1 -- no --> G2{"Local SDXL enabled?"}
  G2 -- yes --> IMG
  G2 -- no --> G3["Pillow graphic"]
  G3 --> IMG
  IMG --> AF{"Hash differs from all clip frames?"}
  AF -- no --> G3
  AF -- yes --> TX["add text with Pillow: 16x9 and 9x16"]
  TX --> PK["package folder and checklist"]
  CR --> PK
```

## 7. Agent work loop (how Gemini must build every unit)

```mermaid
flowchart TD
  R["Read spec section and FILE-MAP row"] --> LV["Verify library APIs against installed packages"]
  LV --> I["Implement one module"]
  I --> T["Write and run tests, ruff"]
  T -->|red| I
  T -->|green| RN["Run it for real, capture output"]
  RN --> SR["Self-review diff against spec line by line"]
  SR --> RV["Hostile reviewer pass: try to break it"]
  RV -->|issues| I
  RV -->|clean| REC["Update TRACEABILITY, PROGRESS, DECISIONS"]
  REC --> RP["Report with evidence"]
  RP --> G{"Milestone gate?"}
  G -- yes --> WAIT["Stop, ask user to approve"]
  G -- no --> R
```

## 8. Milestone order

`M0 scaffold and env` -> `M1 ingest, selection, basic UI` -> `M2 build clips` -> `M3 director and effects` -> `M4 packaging, thumbnails, results` -> `M5 editor, polish, performance` -> final audit.
