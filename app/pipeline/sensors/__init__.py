"""Layer 1 Sensors and Audience Signals package."""

from app.pipeline.sensors.audio_energy import (
    AudioEnergyProfile,
    extract_audio_energy,
    score_audio_window,
)
from app.pipeline.sensors.scene_motion import (
    MotionProfile,
    extract_video_motion,
    score_motion_window,
)
from app.pipeline.sensors.sound_events import (
    SoundEventItem,
    SoundEventsProfile,
    extract_sound_events,
    score_sound_events_window,
)
from app.pipeline.sensors.timeline_generator import (
    HotZone,
    TimelineEvent,
    format_timeline_for_prompt,
    generate_timeline_and_hot_zones,
)
from app.pipeline.sensors.topic_segmenter import compute_candidate_overlap, detect_topic_boundaries
from app.pipeline.sensors.visual_evidence import VisualEvidenceResult, inspect_candidate_visuals
from app.pipeline.sensors.voice_emotion import (
    compute_window_wpm,
    match_hype_lexicon,
    score_voice_emotion,
)

__all__ = [
    "AudioEnergyProfile",
    "HotZone",
    "MotionProfile",
    "SoundEventItem",
    "SoundEventsProfile",
    "TimelineEvent",
    "VisualEvidenceResult",
    "compute_candidate_overlap",
    "compute_window_wpm",
    "detect_topic_boundaries",
    "extract_audio_energy",
    "extract_sound_events",
    "extract_video_motion",
    "format_timeline_for_prompt",
    "generate_timeline_and_hot_zones",
    "inspect_candidate_visuals",
    "match_hype_lexicon",
    "score_audio_window",
    "score_motion_window",
    "score_sound_events_window",
    "score_voice_emotion",
]
