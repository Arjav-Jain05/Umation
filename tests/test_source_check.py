"""Unit tests for Stage 1 source_check metadata inspection and policy enforcement."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.errors import LiveNotFinished, SourceBlocked, TooLong
from app.pipeline.s1_ingest import source_check


def test_source_check_live_not_finished(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify live_status in is_live/is_upcoming/post_live raises LiveNotFinished."""
    ctx = MagicMock()
    ctx.artifact_ok.return_value = False
    ctx.job = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "id": "test_job"}
    ctx.settings.max_source_hours = 12

    mock_info = {
        "id": "dQw4w9WgXcQ",
        "live_status": "is_live",
        "duration": 3600,
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl.__enter__.return_value = mock_ydl

    monkeypatch.setattr("yt_dlp.YoutubeDL", lambda *args, **kwargs: mock_ydl)

    with pytest.raises(LiveNotFinished, match="livestream has not ended"):
        source_check.run(ctx)

    mock_info["live_status"] = "post_live"
    with pytest.raises(LiveNotFinished, match="processing the livestream replay"):
        source_check.run(ctx)


def test_source_check_too_long(monkeypatch: pytest.MonkeyPatch):
    """Verify duration exceeding max_source_hours raises TooLong."""
    ctx = MagicMock()
    ctx.artifact_ok.return_value = False
    ctx.job = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "id": "test_job"}
    ctx.settings.max_source_hours = 4  # 4 hours

    mock_info = {
        "id": "dQw4w9WgXcQ",
        "live_status": "not_live",
        "duration": 5 * 3600 + 10,  # 5 hours
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl.__enter__.return_value = mock_ydl
    monkeypatch.setattr("yt_dlp.YoutubeDL", lambda *args, **kwargs: mock_ydl)

    with pytest.raises(TooLong):
        source_check.run(ctx)


def test_source_check_blocked_policy(tmp_path: Path):
    """Verify channel on block list raises SourceBlocked."""
    policy_file = tmp_path / "source_policy.yaml"
    policy_file.write_text(
        "block:\n  - name: 'ForbiddenChannel'\n    channel_id: 'UC_BAD123'\n    note: 'Infringing channel'\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceBlocked, match="ForbiddenChannel"):
        source_check._check_source_policy("UC_BAD123", "ForbiddenChannel", policy_file, is_cc=False)


def test_source_check_heatmap_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify heatmap is parsed into HeatmapPoint objects with avg_segment_seconds."""
    ctx = MagicMock()
    ctx.artifact_ok.return_value = False
    ctx.job = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "id": "test_job"}
    ctx.settings.max_source_hours = 12
    ctx.settings.project_root = tmp_path
    ctx.db_path = tmp_path / "app.db"
    ctx.options.max_source_height = 1080

    mock_info = {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "live_status": "not_live",
        "duration": 100,
        "channel_id": "UC123",
        "channel": "TestChannel",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "heatmap": [
            {"start_time": 0.0, "end_time": 10.0, "value": 0.2},
            {"start_time": 10.0, "end_time": 20.0, "value": 0.8},
        ],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl.__enter__.return_value = mock_ydl
    monkeypatch.setattr("yt_dlp.YoutubeDL", lambda *args, **kwargs: mock_ydl)

    monkeypatch.setattr("app.pipeline.s1_ingest.source_check.update_job", lambda *args, **kwargs: None)
    saved_artifact = {}

    def mock_write(name, artifact):
        saved_artifact[name] = artifact

    ctx.write_artifact.side_effect = mock_write

    source_check.run(ctx)
    info = saved_artifact.get("source_info.json")
    assert info is not None
    assert info.heatmap is not None
    assert len(info.heatmap) == 2
    assert info.heatmap[0].value == 0.2
    assert info.heatmap[1].value == 0.8
    assert info.heatmap_avg_seg_s == 50.0


def test_source_check_heatmap_missing_null(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify missing heatmap results in heatmap=None and avg_segment_seconds=None."""
    ctx = MagicMock()
    ctx.artifact_ok.return_value = False
    ctx.job = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "id": "test_job"}
    ctx.settings.max_source_hours = 12
    ctx.settings.project_root = tmp_path
    ctx.db_path = tmp_path / "app.db"
    ctx.options.max_source_height = 1080

    mock_info = {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "live_status": "not_live",
        "duration": 100,
        "channel_id": "UC123",
        "channel": "TestChannel",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "heatmap": None,
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl.__enter__.return_value = mock_ydl
    monkeypatch.setattr("yt_dlp.YoutubeDL", lambda *args, **kwargs: mock_ydl)

    monkeypatch.setattr("app.pipeline.s1_ingest.source_check.update_job", lambda *args, **kwargs: None)
    saved_artifact = {}

    def mock_write(name, artifact):
        saved_artifact[name] = artifact

    ctx.write_artifact.side_effect = mock_write

    source_check.run(ctx)
    info = saved_artifact.get("source_info.json")
    assert info is not None
    assert info.heatmap is None
    assert info.heatmap_avg_seg_s is None

