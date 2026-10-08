from app.ai import reply_progress
from app.ai.reply_progress import ReplyProgress


def test_progress_keeps_snapshots_independent_and_does_not_complete_failed_reads(monkeypatch):
    ticks = [10.0]
    monkeypatch.setattr(reply_progress, "monotonic", lambda: ticks[0])
    events = []
    progress = ReplyProgress(events.append, "run")
    progress.step("think", "正在思考", "先核对来源。")
    original = events[-1]["process"]
    ticks[0] += 1.5
    progress.emit({"type": "status", "message": "正在读取公开来源", "step_key": "read"})
    progress.emit(
        {
            "type": "status",
            "message": "读取公开来源",
            "step_key": "read",
            "step_state": "failed",
            "detail": "地址不可读取。",
        }
    )
    result = progress.finish({"status": "answered"})
    assert result["elapsed_ms"] == 1500 and result["state"] == "completed"
    assert result["steps"][-1]["state"] == "failed"
    assert original["steps"][0]["state"] == "running"
    assert len(result["steps"]) == 2


def test_source_change_clears_previous_private_process_details():
    progress = ReplyProgress(lambda _: None, "run")
    progress.step("read", "私人来源", "本轮资料摘要")
    result = progress.finish({"status": "unavailable", "error_code": "REPLY_SOURCE_CHANGED"})
    assert result["state"] == "failed" and len(result["steps"]) == 1
    assert "私人来源" not in str(result) and "本轮资料摘要" not in str(result)


def test_long_process_is_bounded_and_stop_does_not_become_success():
    progress = ReplyProgress(lambda _: None, "run")
    for index in range(30):
        progress.step(str(index), "步骤", "摘要")
    assert len(progress.steps) == 16
    assert progress.steps[0]["key"] == "14" and progress.steps[-1]["key"] == "29"
    assert progress.snapshot()["earlier_steps_omitted"] == 14
    result = progress.finish({"status": "unavailable", "error_code": "REPLY_CANCELLED"})
    assert result["state"] == "stopped"
