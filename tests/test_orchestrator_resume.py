"""Unit tests for orchestrator stage execution and resumability."""

from unittest.mock import MagicMock

from app.core.schemas import Plan
from app.pipeline.context import JobContext
from app.pipeline.orchestrator import STAGES, StageDef, run_pipeline


def test_orchestrator_skips_existing_valid_artifacts(tmp_path):
    """Verify orchestrator skips stage execution when artifact exists and validates."""
    ctx = MagicMock(spec=JobContext)
    ctx.job_id = "test_job_1"
    ctx.job = {"url": "https://youtube.com/watch?v=123", "id": "test_job_1"}
    ctx.db_path = tmp_path / "app.db"
    ctx.check_cancel.return_value = None

    # All artifacts are reported as valid
    ctx.artifact_ok.return_value = True
    ctx.read_artifact.return_value = Plan(job_id="test_job_1", generated_at="2026-01-01T00:00:00Z", clips=[])

    mock_stages = [
        StageDef("source_check", 0.5, MagicMock(), "source_info.json"),
        StageDef("audio_download", 0.5, MagicMock(), "audio.wav"),
    ]

    # Temporarily replace STAGES
    orig_stages = list(STAGES)
    try:
        STAGES.clear()
        STAGES.extend(mock_stages)

        # Mock get_conn and broadcaster
        from unittest.mock import patch

        with (
            patch("app.pipeline.orchestrator.get_conn"),
            patch("app.pipeline.orchestrator.update_job"),
            patch("app.pipeline.orchestrator.broadcaster"),
        ):
            run_pipeline(ctx)

        # Both stage functions should be skipped because artifact_ok is True
        assert mock_stages[0].fn.call_count == 0
        assert mock_stages[1].fn.call_count == 0
    finally:
        STAGES.clear()
        STAGES.extend(orig_stages)


def test_orchestrator_executes_missing_or_corrupt_artifacts(tmp_path):
    """Verify orchestrator runs stage function when artifact is missing or corrupted."""
    ctx = MagicMock(spec=JobContext)
    ctx.job_id = "test_job_2"
    ctx.job = {"url": "https://youtube.com/watch?v=123", "id": "test_job_2"}
    ctx.db_path = tmp_path / "app.db"
    ctx.check_cancel.return_value = None

    # First stage artifact missing (False), second stage artifact exists (True)
    ctx.artifact_ok.side_effect = lambda art: art == "audio.wav"
    ctx.read_artifact.return_value = Plan(job_id="test_job_1", generated_at="2026-01-01T00:00:00Z", clips=[])

    mock_stages = [
        StageDef("source_check", 0.5, MagicMock(), "source_info.json"),
        StageDef("audio_download", 0.5, MagicMock(), "audio.wav"),
    ]

    orig_stages = list(STAGES)
    try:
        STAGES.clear()
        STAGES.extend(mock_stages)

        from unittest.mock import patch

        with (
            patch("app.pipeline.orchestrator.get_conn"),
            patch("app.pipeline.orchestrator.update_job"),
            patch("app.pipeline.orchestrator.broadcaster"),
        ):
            run_pipeline(ctx)

        # First stage ran, second was skipped
        assert mock_stages[0].fn.call_count == 1
        assert mock_stages[1].fn.call_count == 0
    finally:
        STAGES.clear()
        STAGES.extend(orig_stages)


def test_artifact_ok_validation_real_files(tmp_path):
    """Verify JobContext.artifact_ok returns False on empty/corrupted files and True on valid models."""
    from app.core.schemas import Plan
    from app.pipeline.context import JobContext

    work_dir = tmp_path / "job_work"
    work_dir.mkdir(parents=True)

    job_dict = {
        "id": "job_real_test",
        "url": "https://youtube.com/watch?v=123",
        "options_json": "{}",
    }

    ctx = JobContext(job=job_dict)
    ctx.work_dir = work_dir

    # 1. Non-existent file
    assert not ctx.artifact_ok("plan.json", Plan)

    # 2. Empty file (0 bytes)
    empty_file = work_dir / "plan.json"
    empty_file.write_text("", encoding="utf-8")
    assert not ctx.artifact_ok("plan.json", Plan)

    # 3. Corrupted / invalid JSON
    empty_file.write_text("CORRUPTED INVALID JSON", encoding="utf-8")
    assert not ctx.artifact_ok("plan.json", Plan)

    # 4. Valid Plan artifact
    valid_plan = Plan(job_id="job_real_test", generated_at="2026-01-01T00:00:00Z", clips=[])
    ctx.write_artifact("plan.json", valid_plan)
    assert ctx.artifact_ok("plan.json", Plan)
