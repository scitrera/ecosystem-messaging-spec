"""Tests for ControlPart (in-band control signals on chat messages)."""
from __future__ import annotations

import json

import pytest

from scitrera_messaging_spec import (
    ChatMessage,
    ControlPart,
    MessageAddress,
    TextPart,
    UnknownPart,
)


def _cancel_message(task_id: str = "task-zzz") -> ChatMessage:
    return ChatMessage(
        id="msg_cancel_1",
        role="system",
        addr=MessageAddress(
            tenant_id="t1",
            workspace_id="w1",
            user_id="u1",
            thread_id="th1",
            task_id=task_id,
            request_id="win-1",
        ),
        content=[ControlPart(kind="cancel", task_id=task_id)],
    )


# ── round-trip ────────────────────────────────────────────────────────


def test_control_part_roundtrip_cancel() -> None:
    m = _cancel_message()
    raw = m.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    assert back.model_dump() == m.model_dump()
    part = back.content[0]
    assert isinstance(part, ControlPart)
    assert part.kind == "cancel"
    assert part.task_id == "task-zzz"


def test_control_part_serialized_wire_shape() -> None:
    m = _cancel_message()
    raw = json.loads(m.model_dump_json())
    assert raw["role"] == "system"
    assert raw["content"][0] == {
        "type": "control",
        "kind": "cancel",
        "task_id": "task-zzz",
    }


def test_control_part_indexed_in_known_part_types() -> None:
    """Ensure ``control`` is in the discriminator's known set."""
    msg = ChatMessage.model_validate(
        {
            "id": "m",
            "role": "system",
            "content": [
                {"type": "control", "kind": "cancel", "task_id": "task-1"}
            ],
        }
    )
    assert isinstance(msg.content[0], ControlPart)


# ── validation ────────────────────────────────────────────────────────


def test_control_part_kind_required() -> None:
    """``kind`` has no default — missing → validation error."""
    with pytest.raises(Exception):
        ControlPart()  # type: ignore[call-arg]


def test_control_cancel_task_id_optional_at_schema_layer() -> None:
    """Spec schema permits task_id to be omitted (so unknown control kinds
    don't all need it). The cancel-specific requirement is enforced by the
    bridge handler, not the schema.
    """
    p = ControlPart(kind="cancel")
    assert p.kind == "cancel"
    assert p.task_id is None


def test_control_part_allows_extra_fields_for_future_extension() -> None:
    """Per ``extra="allow"`` policy, unknown fields on a control part are
    preserved on round-trip — e.g., a future ``reason`` or ``requester``.
    """
    raw = {
        "id": "m",
        "role": "system",
        "content": [
            {
                "type": "control",
                "kind": "cancel",
                "task_id": "t-1",
                "reason": "user_clicked_cancel",
                "requester": "u-alice",
            }
        ],
    }
    m = ChatMessage.model_validate(raw)
    part = m.content[0]
    assert isinstance(part, ControlPart)
    dumped = m.model_dump(exclude_none=True)["content"][0]
    assert dumped["reason"] == "user_clicked_cancel"
    assert dumped["requester"] == "u-alice"


# ── forward compat for unknown kinds ──────────────────────────────────


def test_unknown_control_kind_roundtrips_as_control_part() -> None:
    """Unknown ``kind`` values still parse as ControlPart (kind is open
    registry) and round-trip verbatim.
    """
    raw = {
        "id": "m",
        "role": "system",
        "content": [
            {"type": "control", "kind": "pause", "task_id": "t-1"},
            {"type": "control", "kind": "future_signal", "payload": {"x": 1}},
        ],
    }
    m = ChatMessage.model_validate(raw)
    for part in m.content:
        assert isinstance(part, ControlPart)
    dumped = m.model_dump(exclude_none=True)
    assert dumped["content"][0]["kind"] == "pause"
    assert dumped["content"][1]["kind"] == "future_signal"
    assert dumped["content"][1]["payload"] == {"x": 1}


# ── mixed with other parts ────────────────────────────────────────────


def test_control_part_alongside_text_part() -> None:
    """A message may carry both text and control parts in the same
    content list. The spec doesn't forbid this; routing precedence is
    consumer-defined (the bridge routes on the first control part).
    """
    m = ChatMessage(
        id="m",
        role="system",
        content=[
            TextPart(text="(internal cancel signal)"),
            ControlPart(kind="cancel", task_id="t-1"),
        ],
    )
    raw = m.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    type_names = [type(p).__name__ for p in back.content]
    assert type_names == ["TextPart", "ControlPart"]


# ── distinction from UnknownPart (control is a known type) ───────────


def test_control_part_is_not_unknown_part() -> None:
    msg = ChatMessage.model_validate(
        {
            "id": "m",
            "role": "system",
            "content": [{"type": "control", "kind": "cancel", "task_id": "t"}],
        }
    )
    assert not isinstance(msg.content[0], UnknownPart)
    assert isinstance(msg.content[0], ControlPart)
