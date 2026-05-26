from __future__ import annotations

from src.jobs.cleanup_partitions import _FALLBACK_LIST_OLD


def test_fallback_partition_regex_accepts_partman_daily_suffix() -> None:
    sql = str(_FALLBACK_LIST_OLD)

    assert "p([0-9]{4}_[0-9]{2}_[0-9]{2})$" in sql
    assert "YYYY_MM_DD" in sql
