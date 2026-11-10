"""Pydantic v2 schemas for all pipeline artifacts and API payloads."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)


# --- 1. Base Artifact Model ---

class ArtifactModel(BaseModel):
    """Base class for versioned JSON artifacts."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    schema_version: int = Field(default=1)


# --- 2. Ingest Artifacts (Stage 1) ---

class Chapter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: float
    end: float
    title: str


class HeatmapPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: float
    end: float
    value: float


class SourcePolicyMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str = Field(description="allow | block | none")
    matched_rule: str | None = None


class SourceInfo(ArtifactModel):
    """Artifact: source_info.json"""
    video_id: str
    url: str
    webpage_url: str
    title: str
    channel: str
    channel_url: str
    uploader: str
    upload_date: str = Field(description="YYYYMMDD")
    duration_s: float
    live_status: str
    license: str | None = None
    width: int
    height: int
    fps: float
    view_count: int | None = None
    like_count: int | None = None
    description_head: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    heatmap: list[HeatmapPoint] | None = None
    heatmap_avg_seg_s: float | None = None
    source_policy: SourcePolicyMatch = Field(default_factory=lambda: SourcePolicyMatch(status="none"))
    fetched_at: str


class Word(BaseModel):
    model_config = ConfigDict(extra="ignore")
    i: int
    w: str
    s: float
    e: float
    p: float = Field(default=1.0, description="Confidence probability 0.0 - 1.0")


class Sentence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    s: float
    e: float
    text: str
    w0: int
    w1: int
    wpm: float = 0.0


class Transcript(ArtifactModel):
    """Artifact: transcript.json"""
    language: str
    model: str
    duration_s: float
    words: list[Word] = Field(default_factory=list)
    sentences: list[Sentence] = Field(default_factory=list)
    fillers: list[int] = Field(default_factory=list)


# --- 3. Selection Artifacts (Stage 2) ---

class Chunk(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    s: float
    e: float
    sentence_ids: list[int] = Field(description="[first_id, last_id] inclusive")


class ChunksArtifact(ArtifactModel):
    """Artifact: chunks.json"""
    chunks: list[Chunk] = Field(default_factory=list)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cid: str
    chunk_id: str
    start_sid: int
    end_sid: int
    hook_sid: int
    s: float
    e: float
    reason: str
    llm_hint_score: float = 0.0


class CandidatesArtifact(ArtifactModel):
    """Artifact: candidates.json"""
    candidates: list[Candidate] = Field(default_factory=list)


class JudgedScores(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hook: float = 0.0
    payoff: float = 0.0
    clarity: float = 0.0
    emotion: float = 0.0
    novelty: float = 0.0
    shareability: float = 0.0
    pace: float = 0.0


class JudgedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cid: str
    s: float
    e: float
    start_sid: int
    end_sid: int
    hook_text: str
    scores: JudgedScores = Field(default_factory=JudgedScores)
    needs_context: bool = False
    context_fix: str | None = None
    is_story: bool = False
    topic: str = ""
    entities: list[str] = Field(default_factory=list)
    content_flags: list[str] = Field(default_factory=list)
    reasons: dict[str, Any] = Field(default_factory=dict)
    llm_score: float = 0.0
    runs: int = 1


class JudgedArtifact(ArtifactModel):
    """Artifact: judged.json"""
    items: list[JudgedItem] = Field(default_factory=list)


class Signals(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cid: str
    heat: float | None = None
    audio: float = 0.0
    speech_ratio: float = 0.0
    burst_count: int = 0
    topical_hits: int = 0


class SignalsArtifact(ArtifactModel):
    """Artifact: signals.json"""
    signals: dict[str, Signals] = Field(default_factory=dict)


class Clip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    parent_id: str | None = None
    part_index: int | None = None
    part_total: int | None = None
    start: float
    end: float
    duration: float
    tier: str = Field(description="A | B | C")
    final_score: float
    llm_score: float
    heat: float | None = None
    audio: float = 0.0
    speech_ratio: float = 0.0
    hook_text: str = ""
    topic: str = ""
    risk: str = Field(default="low", description="low | medium | high")
    risk_flags: list[str] = Field(default_factory=list)
    needs_context: bool = False
    context_fix: str | None = None
    recap_line: str | None = None


class Plan(ArtifactModel):
    """Artifact: plan.json"""
    job_id: str
    generated_at: str
    weights: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list)


# --- 4. Build Artifacts (Stage 3) ---

class Segment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    s: float
    e: float
    path: str
    clip_ids: list[str] = Field(default_factory=list)


class SegmentsArtifact(ArtifactModel):
    """Artifact: segments.json"""
    segments: list[Segment] = Field(default_factory=list)


class WordClip(BaseModel):
    """Per-clip word timestamped in clip-relative timeline."""
    model_config = ConfigDict(extra="ignore")
    w: str
    s_clip: float
    e_clip: float
    emphasis: bool = False


class WordsClipArtifact(ArtifactModel):
    """Artifact: clips/<clip_id>/words.json"""
    clip_id: str
    words: list[WordClip] = Field(default_factory=list)


WordsArtifact = WordsClipArtifact


class CutInterval(BaseModel):
    model_config = ConfigDict(extra="ignore")
    s: float
    e: float
    dur: float


class CutsArtifact(ArtifactModel):
    """Artifact: clips/<clip_id>/cuts.json"""
    clip_id: str
    intervals: list[CutInterval] = Field(default_factory=list)
    total_source_duration: float = 0.0
    total_cut_duration: float = 0.0
    removed_duration: float = 0.0
    removed_pct: float = 0.0


class LayoutArtifact(ArtifactModel):
    """Artifact: clips/<clip_id>/layout.json"""
    clip_id: str
    layout: str = Field(description="gameplay | talking_head | facecam")
    confidence: float = 1.0
    cam_rect: list[float] | None = None  # [x, y, w, h] normalized
    samples_count: int = 0


class QAReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    passed: bool
    failures: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


# --- 5. Director Artifacts (Stage 4) ---

class EditEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    type: str = Field(description="hook_card | zoom_punch | arrow | highlight_box | emoji_pop | part_label | recap_line | progress_bar | sfx")
    t: float
    dur: float
    params: dict[str, Any] = Field(default_factory=dict)


class EditList(ArtifactModel):
    """Artifact: clips/<clip_id>/edit_list.json"""
    clip_id: str
    fps: int = 30
    duration: float
    layout: str = "gameplay"
    caption_emphasis: list[int | str] = Field(default_factory=list)
    events: list[EditEvent] = Field(default_factory=list)


# --- 6. Package Artifacts (Stage 5) ---

class TitleOption(BaseModel):
    model_config = ConfigDict(extra="ignore")
    style: str = Field(description="curiosity | direct | bold")
    text: str


class ThumbnailConcept(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str = ""
    visual_description: str = ""
    focal_point: str = "center"
    palette: list[str] = Field(default_factory=list)


class ThumbnailInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    concept: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)
    generator: str = "pillow"


class Metadata(ArtifactModel):
    """Artifact: clips/<clip_id>/metadata.json"""
    clip_id: str
    titles: list[TitleOption] = Field(default_factory=list)
    hook_line: str = ""
    context: str = ""
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    instagram_caption: str = ""
    pinned_comment: str = ""
    credit_block: str = ""
    description_youtube: str = ""
    description_instagram: str = ""
    tags_youtube: str = ""
    risk: str = "low"
    risk_flags: list[str] = Field(default_factory=list)
    thumbnail: ThumbnailInfo = Field(default_factory=ThumbnailInfo)


# --- 7. API Request / Response Models ---

class JobOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")
    min_tier: str = Field(default="C", description="Minimum tier threshold: A | B | C")
    max_clip_s: int = Field(default=60, description="Max clip duration in seconds")
    layout: str = Field(default="auto", description="auto | gameplay | facecam | talking_head")
    effects: bool = Field(default=True, description="Enable AI director and effects")
    second_look: bool = Field(default=False, description="Run an extra candidate pass")
    fast_mode: bool = Field(default=False, description="Batch 6 instead of 4 candidates")
    max_height: int = Field(default=1080, description="Video download resolution height")


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    ack_fair_use: bool = Field(description="User must acknowledge fair use policy")
    options: JobOptions = Field(default_factory=JobOptions)


class StageProgress(BaseModel):
    name: str
    status: str
    progress: float = 0.0


class JobOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    url: str
    video_id: str | None = None
    title: str | None = None
    channel: str | None = None
    status: str
    stage: str | None = None
    progress: float = 0.0
    message: str | None = None
    options: JobOptions
    ack_fair_use: bool
    ack_at: str | None = None
    created_at: str
    updated_at: str
    error: str | None = None
    stages: list[StageProgress] = Field(default_factory=list)
    clips_total: int = 0
    clips_ok: int = 0
    clips_failed: int = 0


class ClipOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_id: str
    id: str
    idx: int
    parent_id: str | None = None
    part_index: int | None = None
    part_total: int | None = None
    start: float
    end: float
    tier: str
    final_score: float
    risk: str
    status: str
    decision: str = "pending"
    title_choice: int = 0
    title_override: str | None = None
    description_override: str | None = None
    folder: str | None = None
    error: str | None = None
    video_url: str | None = None
    thumb_url: str | None = None


class ErrorOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    error: dict[str, Any]


# --- 8. Artifact Serialization & Deserialization Helpers ---

def read_artifact[T: BaseModel](path: Path | str, model_cls: type[T]) -> T:
    """Read a JSON artifact into a validated Pydantic model."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Artifact not found: {p}")
    text = p.read_text(encoding="utf-8")
    data = json.loads(text)
    return model_cls.model_validate(data)


def write_artifact(path: Path | str, obj: BaseModel | dict[str, Any] | list[Any]) -> Path:
    """Write an artifact atomically using a temp file and os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")

    data = obj.model_dump(mode="json", by_alias=True) if isinstance(obj, BaseModel) else obj

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, p)
    return p
