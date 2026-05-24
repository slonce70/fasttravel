"""Tests for src.infra.metrics — the decorator wraps any async callable
and emits the run + duration metrics. Direct Prometheus assertions read
back from REGISTRY.
"""

from __future__ import annotations

import pytest

from src.infra.metrics import JOB_DURATION, JOB_RUNS, track_job_metrics


def _counter_value(job: str, outcome: str) -> float:
    return JOB_RUNS.labels(job=job, outcome=outcome)._value.get()  # noqa: SLF001


def _hist_sum(job: str) -> float:
    """Total seconds observed for *job* across all buckets."""
    samples = JOB_DURATION.collect()
    for metric in samples:
        for s in metric.samples:
            if s.name.endswith("_sum") and s.labels.get("job") == job:
                return float(s.value)
    return 0.0


@pytest.mark.asyncio
async def test_track_job_metrics_counts_success_and_records_duration():
    @track_job_metrics("unit_test_ok")
    async def ok() -> str:
        return "fine"

    before_runs = _counter_value("unit_test_ok", "success")
    before_dur = _hist_sum("unit_test_ok")

    result = await ok()

    assert result == "fine"
    assert _counter_value("unit_test_ok", "success") == before_runs + 1
    assert _hist_sum("unit_test_ok") >= before_dur


@pytest.mark.asyncio
async def test_track_job_metrics_records_failure_and_still_raises():
    @track_job_metrics("unit_test_boom")
    async def boom() -> None:
        raise RuntimeError("nope")

    before = _counter_value("unit_test_boom", "failure")

    with pytest.raises(RuntimeError, match="nope"):
        await boom()

    # Failure outcome incremented, duration still recorded.
    assert _counter_value("unit_test_boom", "failure") == before + 1
    assert _hist_sum("unit_test_boom") > 0
