"""Tests for clip packaging folder layout and 07 checklist verification (07 s9)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.core import paths
from app.core.schemas import Clip, JobOptions, SourceInfo, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s5_package import package


def test_package_clip_folder_layout(tmp_path, monkeypatch):
    """Verify package_clip outputs all 9 required files according to 07 s9."""
    # Mock paths
    output_dir = tmp_path / "output"
    monkeypatch.setattr(paths, "output_dir", lambda *a: output_dir)

    job_id = "job_test_pkg"
    clip_id = "c01"

    # Set up source clip work dir
    clip_dir = tmp_path / "work" / job_id / "clips" / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "clip_dir", lambda *a: clip_dir)

    # Synthetic final mp4
    final_mp4 = clip_dir / "final.mp4"
    final_mp4.write_bytes(b"\x00" * 4096)  # Mock video bytes

    # Synthetic srt
    srt_file = clip_dir / "captions.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello world\n", encoding="utf-8")

    # Mock JobContext
    ctx = MagicMock(spec=JobContext)
    ctx.job_id = job_id
    ctx.options = JobOptions()
    ctx.publish = MagicMock()

    source = SourceInfo(
        video_id="pkg_vid_123",
        url="https://www.youtube.com/watch?v=pkg_vid_123",
        webpage_url="https://www.youtube.com/watch?v=pkg_vid_123",
        title="Epic GTA 6 Chase",
        channel="GamerX",
        channel_url="https://www.youtube.com/channel/UC123",
        uploader="GamerX",
        upload_date="20260101",
        duration_s=120.0,
        live_status="not_live",
        width=1920,
        height=1080,
        fps=60.0,
        fetched_at="2026-01-01T00:00:00Z",
    )
    clip = Clip(
        id=clip_id,
        idx=0,
        start=10.0,
        end=45.0,
        duration=35.0,
        topic="Police chase",
        hook_text="They never saw this coming",
        tier="A",
        final_score=88.0,
        llm_score=88.0,
    )

    def mock_read_artifact(name, model=None):
        if "source_info" in name:
            return source
        if "words" in name:
            return WordsArtifact(clip_id=clip_id, words=[])
        return None

    ctx.read_artifact.side_effect = mock_read_artifact

    # Mock qa.check_clip_file to pass
    from app.core.schemas import QAReport
    monkeypatch.setattr(package, "check_clip_file", lambda p: QAReport(passed=True))

    # Mock DB update_clip
    monkeypatch.setattr(package, "update_clip", lambda *a, **kw: None)

    # Run packaging
    pkg_dir = package.package_clip(ctx, clip)

    assert pkg_dir.is_dir()
    expected_files = [
        "clip.mp4",
        "thumb_16x9.jpg",
        "cover_9x16.jpg",
        "metadata.txt",
        "metadata.json",
        "captions.srt",
        "edit_list.json",
        "credit.txt",
        "notes.txt",
    ]
    for ef in expected_files:
        f = pkg_dir / ef
        assert f.is_file(), f"Missing required packaged file: {ef}"

    # Verify metadata.json content
    meta_json = json.loads((pkg_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta_json["clip_id"] == clip_id
    assert len(meta_json["titles"]) == 3
    assert "https://youtu.be/pkg_vid_123" in meta_json["description_youtube"]
    assert "Original video:" in meta_json["credit_block"]

    # Verify metadata.txt starts with title options
    meta_txt = (pkg_dir / "metadata.txt").read_text(encoding="utf-8")
    assert "=== YOUTUBE TITLE OPTIONS ===" in meta_txt
    assert "=== YOUTUBE DESCRIPTION ===" in meta_txt
    assert "=== PINNED COMMENT ===" in meta_txt
