"""Integration tests for Stage 3 final clip rendering and QA verification."""

from pathlib import Path

import pytest

from app.core.schemas import LayoutArtifact, WordClip
from app.pipeline.s3_build import audio_clean, captions, final_render, layout
from app.utils.ffmpeg import probe, run_ffmpeg


def test_final_render_gameplay_integration(tmp_path: Path):
    """Render a 15-second cut of synthetic.mp4 through the gameplay layout pipeline."""
    synthetic_src = Path("tests/fixtures/synthetic.mp4")
    if not synthetic_src.is_file():
        pytest.skip("tests/fixtures/synthetic.mp4 fixture missing")

    clip_dir = tmp_path / "c01"
    clip_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create 15-second cut.mkv from synthetic fixture (with 48kHz audio)
    cut_video = clip_dir / "cut.mkv"
    cut_args = [
        "-ss", "0.0",
        "-i", str(synthetic_src),
        "-t", "15.0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "pcm_s16le",
        "-ar", "48000",
        str(cut_video),
    ]
    run_ffmpeg(cut_args, check=True)
    assert cut_video.is_file()

    # 2. Render gameplay layout (1080x1920 framed.mp4)
    layout_art = LayoutArtifact(clip_id="c01", layout="gameplay", confidence=1.0)
    framed_video = layout.build_framed_clip(cut_video, layout_art, clip_dir)
    assert framed_video.is_file()

    # Verify framed dimensions
    f_info = probe(framed_video)
    assert f_info.width == 1080
    assert f_info.height == 1920

    # 3. Clean audio (audio_clean.wav)
    clean_audio = clip_dir / "audio_clean.wav"
    audio_clean.clean_audio(cut_video, layout="gameplay", out_wav=clean_audio)
    assert clean_audio.is_file()

    # 4. Generate captions.ass
    words = [
        WordClip(w="Vice", s_clip=1.0, e_clip=2.0),
        WordClip(w="City", s_clip=2.1, e_clip=3.0),
        WordClip(w="stunt", s_clip=3.1, e_clip=4.0),
        WordClip(w="jump!", s_clip=4.1, e_clip=5.5),
    ]
    chunks = captions.chunk_words(words)
    ass_file = clip_dir / "captions.ass"
    captions.write_ass(chunks, layout="gameplay", out_path=ass_file, mask_profanity_flag=False)
    assert ass_file.is_file()

    # 5. Final render (loudnorm + ASS burn-in + NVENC / libx264)
    out_clip, qa_report = final_render.render_final(
        clip_dir=clip_dir,
        fps=30.0,
        has_captions=True,
    )

    assert out_clip.is_file()
    assert out_clip.stat().st_size > 50000

    # 6. Verify final probe metrics
    c_info = probe(out_clip)
    assert c_info.width == 1080
    assert c_info.height == 1920
    assert c_info.vcodec in ("h264", "avc1")
    assert c_info.acodec in ("aac", "mp4a")
    assert 14.5 <= c_info.duration <= 16.5
    assert 29.0 <= c_info.fps <= 31.0

    # Verify QA report
    assert qa_report.metrics["width"] == 1080
    assert qa_report.metrics["height"] == 1920
    assert qa_report.metrics["acodec"] == "aac"
    assert qa_report.passed is True
