"""Tests for SubagentPart + cross-thread MessageRef."""
from __future__ import annotations

import pytest

from scitrera_messaging_spec import (
    ChatMessage,
    MessageAddress,
    MessageBuilder,
    MessageRef,
    StreamEvent,
    SubagentPart,
    TextPart,
    apply_event,
)


def test_subagent_part_roundtrip() -> None:
    msg = ChatMessage(
        id="msg_p",
        role="assistant",
        addr=MessageAddress(workspace_id="w1", thread_id="thr_main"),
        content=[
            TextPart(text="Delegating to researcher..."),
            SubagentPart(
                id="sub_1",
                name="researcher",
                thread_id="thr_sub_001",
                input={"query": "Q3 revenue"},
                status="running",
                started_at="2026-05-26T15:30:00Z",
            ),
        ],
    )
    raw = msg.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    assert back.model_dump() == msg.model_dump()
    sub = back.content[1]
    assert isinstance(sub, SubagentPart)
    assert sub.thread_id == "thr_sub_001"
    assert sub.status == "running"


def test_message_ref_cross_thread_fields() -> None:
    child = ChatMessage(
        id="msg_c",
        role="user",
        content=[TextPart(text="research Q3")],
        addr=MessageAddress(thread_id="thr_sub_001"),
        ref=MessageRef(parent_thread_id="thr_main", parent_message_id="msg_p"),
    )
    raw = child.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    assert back.ref is not None
    assert back.ref.parent_thread_id == "thr_main"
    assert back.ref.parent_message_id == "msg_p"


def test_builder_subagent_lifecycle_replays_correctly() -> None:
    """Builder emit sequence for a subagent lifecycle reconstructs."""
    events: list[StreamEvent] = []
    b = MessageBuilder.start(
        id="msg_p",
        role="assistant",
        addr=MessageAddress(thread_id="thr_main"),
        sink=events.append,
    )
    b.add_text("Delegating to researcher.")
    b.add_subagent(
        id="sub_1",
        name="researcher",
        thread_id="thr_sub_001",
        input={"query": "Q3 revenue"},
        status="running",
    )
    b.update_subagent_status("sub_1", "completed", summary="Q3 revenue was $4.2M")
    b.add_text("Got it.")
    final = b.finalize()

    state: dict[str, ChatMessage] = {}
    for ev in events:
        state = apply_event(state, ev)
    assert state[final.id].model_dump() == final.model_dump()


def test_builder_rejects_duplicate_subagent_id() -> None:
    events: list[StreamEvent] = []
    b = MessageBuilder.start(id="m", sink=events.append)
    b.add_subagent("s1", "researcher", "thr_a")
    with pytest.raises(ValueError):
        b.add_subagent("s1", "writer", "thr_b")


def test_update_subagent_status_requires_known_id() -> None:
    events: list[StreamEvent] = []
    b = MessageBuilder.start(id="m", sink=events.append)
    with pytest.raises(KeyError):
        b.update_subagent_status("nope", "completed")


def test_subagent_indexed_in_known_part_types() -> None:
    """Ensure ``subagent`` is in the discriminator's known set."""
    msg = ChatMessage.model_validate(
        {
            "id": "m",
            "role": "assistant",
            "content": [
                {
                    "type": "subagent",
                    "id": "sub_1",
                    "name": "x",
                    "thread_id": "thr_x",
                    "status": "pending",
                }
            ],
        }
    )
    assert isinstance(msg.content[0], SubagentPart)
