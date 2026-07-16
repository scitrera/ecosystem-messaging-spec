"""Tests for the dynamic tool_call_progress part (live progress bar).

Mirrors go/progress_test.go and typescript/test/progress.test.ts.
"""
from __future__ import annotations

from scitrera_messaging_spec import (
    DYNAMIC_TOOL_CALL_PROGRESS,
    ToolCallProgressPayload,
    make_tool_call_progress_part,
)


def test_build_progress_part_defaults():
    part = make_tool_call_progress_part(
        ToolCallProgressPayload(bar_id="stqdm_0", desc="Scoring", n=42, total=100)
    )
    assert part.type == "dynamic"
    assert part.kind == DYNAMIC_TOOL_CALL_PROGRESS
    assert part.interactive is False
    assert part.payload["bar_id"] == "stqdm_0"
    assert part.payload["n"] == 42
    assert part.payload["total"] == 100
    assert part.payload["status"] == "running"
    assert part.payload["unit"] == "it"


def test_build_progress_part_from_dict_passthrough():
    part = make_tool_call_progress_part({"bar_id": "b", "n": 10, "total": 10, "status": "done"})
    assert part.kind == DYNAMIC_TOOL_CALL_PROGRESS
    assert part.payload["status"] == "done"
