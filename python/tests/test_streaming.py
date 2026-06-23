"""Tests for the sender-side MessageBuilder."""
from __future__ import annotations

import pytest

from scitrera_messaging_spec import (
    ChatMessage,
    MessageAddress,
    MessageBuilder,
    StreamEvent,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    apply_event,
)


def _collect_sink() -> tuple[list[StreamEvent], MessageBuilder]:
    events: list[StreamEvent] = []
    b = MessageBuilder.start(
        id="msg_1",
        role="assistant",
        addr=MessageAddress(workspace_id="w1", thread_id="th1"),
        sink=events.append,
    )
    return events, b


def test_builder_finalize_matches_apply_event_reconstruction() -> None:
    """The canonical invariant: builder-emitted events, when replayed
    through apply_event, must rebuild the same final message."""
    events, b = _collect_sink()
    txt = b.add_text()
    b.append_token(txt, "Looking up the report.")
    b.add_tool_call(id="c1", name="vfs_fetch", args={"path": "/r.pdf"})
    b.update_tool_status("c1", "running")
    b.update_tool_status("c1", "completed", finished_at="2026-05-26T00:00:00Z")
    b.add_tool_result("c1", name="vfs_fetch", output_text="Q3: $4.2M")
    txt2 = b.add_text()
    b.append_token(txt2, "Q3 revenue was ")
    b.append_token(txt2, "**$4.2M**.")
    b.add_citation(source="vfs://r.pdf", title="Q3 Report", snippet="Total: $4.2M")
    final = b.finalize()

    state: dict[str, ChatMessage] = {}
    for e in events:
        state = apply_event(state, e)
    assert state[final.id].model_dump() == final.model_dump()


def test_builder_message_started_carries_empty_content() -> None:
    events, _ = _collect_sink()
    assert events[0].event == "message_started"  # type: ignore[union-attr]
    assert events[0].message.content == []  # type: ignore[union-attr]


def test_builder_start_stamps_created_at() -> None:
    """start() must auto-stamp created_at so the frontend can sort messages."""
    events, b = _collect_sink()
    # created_at must be set on the in-flight message
    assert b.message.created_at is not None
    assert b.message.created_at != ""
    # …and must be present in the message_started event payload
    assert events[0].message.created_at is not None  # type: ignore[union-attr]


def test_builder_start_respects_explicit_created_at() -> None:
    """An explicitly-passed created_at must not be overwritten."""
    events: list[StreamEvent] = []
    explicit_ts = "2026-01-01T00:00:00+00:00"
    b = MessageBuilder.start(id="m", sink=events.append, created_at=explicit_ts)
    assert b.message.created_at == explicit_ts


def test_builder_indexes_tool_calls_for_status_updates() -> None:
    events, b = _collect_sink()
    idx = b.add_tool_call(id="c1", name="t", args={"x": 1})
    b.update_tool_status("c1", "running")
    b.update_tool_status("c1", "completed")
    b.finalize()

    msg = events[-1].message  # MessageFinalized.message  # type: ignore[union-attr]
    assert msg.content[idx].status == "completed"  # type: ignore[union-attr]


def test_builder_rejects_duplicate_tool_call_id() -> None:
    _, b = _collect_sink()
    b.add_tool_call(id="c1", name="t")
    with pytest.raises(ValueError):
        b.add_tool_call(id="c1", name="t2")


def test_builder_update_tool_status_requires_known_id() -> None:
    _, b = _collect_sink()
    with pytest.raises(KeyError):
        b.update_tool_status("nope", "completed")


def test_builder_append_token_rejects_non_text_part() -> None:
    _, b = _collect_sink()
    idx = b.add_tool_call(id="c1", name="t")
    with pytest.raises(TypeError):
        b.append_token(idx, "x")


def test_builder_append_token_empty_string_is_noop() -> None:
    events, b = _collect_sink()
    idx = b.add_text()
    starting_len = len(events)
    b.append_token(idx, "")  # empty → no event
    assert len(events) == starting_len


def test_builder_context_manager_finalizes_on_exit() -> None:
    events: list[StreamEvent] = []
    with MessageBuilder.start(id="m", sink=events.append) as b:
        b.add_text("hi")
    # message_finalized must have been emitted automatically.
    assert events[-1].event == "message_finalized"  # type: ignore[union-attr]


def test_builder_finalize_is_idempotent() -> None:
    events: list[StreamEvent] = []
    b = MessageBuilder.start(id="m", sink=events.append)
    b.add_text("x")
    f1 = b.finalize()
    f2 = b.finalize()
    assert f1.model_dump() == f2.model_dump()
    # Only one MessageFinalized in the event stream.
    finalized = [e for e in events if e.event == "message_finalized"]  # type: ignore[union-attr]
    assert len(finalized) == 1


def test_builder_emits_part_appended_for_each_helper() -> None:
    events, b = _collect_sink()
    b.add_text("t")
    b.add_image(uri="https://x")
    b.add_file(vfs_ref="vfs://x", purpose="document")
    b.add_dynamic("jsx", payload={"x": 1})
    b.add_reasoning("thinking", redacted=False)
    b.add_citation(source="vfs://x")
    b.finalize()

    part_appended_count = sum(1 for e in events if e.event == "part_appended")  # type: ignore[union-attr]
    assert part_appended_count == 6


def test_builder_user_role_works_for_inbound_messages() -> None:
    """A user message with attachments still uses the builder."""
    events: list[StreamEvent] = []
    b = MessageBuilder.start(
        id="msg_user",
        role="user",
        addr=MessageAddress(workspace_id="w1", user_id="u1", thread_id="th1"),
        sink=events.append,
    )
    b.add_text("Please summarize.")
    b.add_file(vfs_ref="vfs://a", purpose="attachment")
    final = b.finalize()
    assert final.role == "user"
    assert len(final.content) == 2
    assert isinstance(final.content[0], TextPart)


def test_patch_part_morphs_type_via_validator() -> None:
    events, b = _collect_sink()
    idx = b.add_text("hi")
    b.patch_part(idx, {"type": "reasoning", "redacted": False})
    msg = b.message
    assert msg.content[idx].type == "reasoning"  # type: ignore[union-attr]


def test_message_property_returns_independent_snapshot() -> None:
    _, b = _collect_sink()
    b.add_text("hello")
    snap = b.message
    b.add_text("world")
    # Snapshot was a deep copy → unaffected by subsequent mutations.
    assert len(snap.content) == 1
    assert len(b.message.content) == 2


def test_builder_keeps_inline_tool_result_pairing() -> None:
    """Tool result parts live inline on the assistant message (spec preference)."""
    _, b = _collect_sink()
    b.add_text("calling tool")
    b.add_tool_call(id="c1", name="t", args={})
    b.add_tool_result("c1", output_text="ok")
    b.add_text("done")
    final = b.finalize()
    type_names = [type(p).__name__ for p in final.content]
    assert type_names == ["TextPart", "ToolCallPart", "ToolResultPart", "TextPart"]
