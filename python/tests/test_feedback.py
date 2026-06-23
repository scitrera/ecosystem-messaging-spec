"""Tests for FeedbackPart (user feedback carried as a content part).

Spec §3.12. A feedback message is a ChatMessage whose ``content`` is a
single FeedbackPart and whose ``ref.message_id`` points at the target
message being rated. Carrier role: ``user``. Carrier ref.relationship:
``"feedback"``.

Coverage:
  - FeedbackPart roundtrips through JSON unchanged.
  - ``feedback`` is in the discriminator's known set (NOT routed to
    UnknownPart).
  - Unknown integer sentiment values (e.g. ``-2``, ``+2``) round-trip
    verbatim — sentiment is *not* validated as an enum.
  - to_lc_messages skips feedback-only ChatMessages (the model never
    sees feedback as conversational input on resume).
  - Mixed-content messages (feedback + text/tool parts) preserve the
    non-feedback parts in the LC output and drop the feedback parts.
  - to_memorylayer_payload preserves a feedback message (analytics is
    the whole point of persisting it).
"""
from __future__ import annotations

import json

import pytest

from scitrera_messaging_spec import (
    ChatMessage,
    FeedbackPart,
    MessageAddress,
    MessageRef,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    UnknownPart,
)
from scitrera_messaging_spec.memorylayer import (
    from_memorylayer_message,
    to_memorylayer_payload,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _feedback_message(
    *,
    sentiment: int = 1,
    text: str | None = None,
    target_id: str = "msg_target_1",
) -> ChatMessage:
    """Build a canonical feedback ChatMessage (spec §3.12 shape)."""
    return ChatMessage(
        id="msg_feedback_1",
        role="user",
        addr=MessageAddress(
            tenant_id="t1",
            workspace_id="w1",
            user_id="u1",
            thread_id="thr_1",
        ),
        content=[FeedbackPart(sentiment=sentiment, text=text)],
        ref=MessageRef(message_id=target_id, relationship="feedback"),  # type: ignore[call-arg]
    )


# ── round-trip ────────────────────────────────────────────────────────────


def test_feedback_part_roundtrip_thumbs_up() -> None:
    m = _feedback_message(sentiment=1, text="great answer")
    raw = m.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    assert back.model_dump() == m.model_dump()
    part = back.content[0]
    assert isinstance(part, FeedbackPart)
    assert part.sentiment == 1
    assert part.text == "great answer"


def test_feedback_part_roundtrip_thumbs_down_no_text() -> None:
    m = _feedback_message(sentiment=-1)
    raw = m.model_dump_json()
    back = ChatMessage.model_validate_json(raw)
    part = back.content[0]
    assert isinstance(part, FeedbackPart)
    assert part.sentiment == -1
    assert part.text is None


def test_feedback_part_cleared_sentiment_zero() -> None:
    """sentiment=0 means user cleared their feedback (no opinion)."""
    m = _feedback_message(sentiment=0)
    back = ChatMessage.model_validate_json(m.model_dump_json())
    part = back.content[0]
    assert isinstance(part, FeedbackPart)
    assert part.sentiment == 0


def test_feedback_part_serialized_wire_shape() -> None:
    m = _feedback_message(sentiment=1, text="why")
    raw = json.loads(m.model_dump_json())
    assert raw["role"] == "user"
    assert raw["content"][0] == {
        "type": "feedback",
        "sentiment": 1,
        "text": "why",
    }


# ── discriminator routes to FeedbackPart (not UnknownPart) ───────────────


def test_feedback_part_indexed_in_known_part_types() -> None:
    msg = ChatMessage.model_validate(
        {
            "id": "m",
            "role": "user",
            "content": [{"type": "feedback", "sentiment": 1}],
        }
    )
    assert isinstance(msg.content[0], FeedbackPart)
    assert not isinstance(msg.content[0], UnknownPart)


def test_feedback_part_sentiment_required() -> None:
    """``sentiment`` has no default — missing → validation error."""
    with pytest.raises(Exception):
        FeedbackPart()  # type: ignore[call-arg]


def test_feedback_part_allows_extra_fields() -> None:
    """Per ``extra="allow"``: future fields (rating axes, tags) round-trip."""
    raw = {
        "id": "m",
        "role": "user",
        "content": [
            {
                "type": "feedback",
                "sentiment": 1,
                "text": "good",
                "tags": ["accurate", "concise"],
                "confidence": 0.95,
            }
        ],
    }
    m = ChatMessage.model_validate(raw)
    part = m.content[0]
    assert isinstance(part, FeedbackPart)
    dumped = m.model_dump(exclude_none=True)["content"][0]
    assert dumped["tags"] == ["accurate", "concise"]
    assert dumped["confidence"] == 0.95


# ── forward-compat: sentiment is an open int, NOT an enum ───────────────


def test_unknown_sentiment_values_roundtrip_verbatim() -> None:
    """Wider scales (e.g. ``-2..+2``) must round-trip unchanged. The spec
    intentionally does NOT validate ``sentiment`` as an enum to leave room
    for richer scales.
    """
    raw = {
        "id": "m",
        "role": "user",
        "content": [
            {"type": "feedback", "sentiment": 2},
            {"type": "feedback", "sentiment": -2, "text": "very bad"},
            {"type": "feedback", "sentiment": 5},
        ],
    }
    m = ChatMessage.model_validate(raw)
    sentiments = [p.sentiment for p in m.content]  # type: ignore[union-attr]
    assert sentiments == [2, -2, 5]
    back = ChatMessage.model_validate_json(m.model_dump_json())
    sentiments_back = [p.sentiment for p in back.content]  # type: ignore[union-attr]
    assert sentiments_back == [2, -2, 5]


# ── ref.relationship is the spec convention for the feedback link ─────


def test_feedback_message_carries_ref_to_target() -> None:
    m = _feedback_message(target_id="msg_assistant_xyz")
    assert m.ref is not None
    # ref carries the target message id via the standard MessageRef field
    # (we use extra="allow" to add ``message_id`` + ``relationship`` —
    # MessageRef.model_config = ConfigDict(extra="allow")).
    dumped = m.model_dump(exclude_none=True)
    assert dumped["ref"]["message_id"] == "msg_assistant_xyz"
    assert dumped["ref"]["relationship"] == "feedback"


# ── distinction from UnknownPart ─────────────────────────────────────────


def test_feedback_part_is_not_unknown_part() -> None:
    msg = ChatMessage.model_validate(
        {
            "id": "m",
            "role": "user",
            "content": [{"type": "feedback", "sentiment": 1}],
        }
    )
    assert not isinstance(msg.content[0], UnknownPart)
    assert isinstance(msg.content[0], FeedbackPart)


# ── LangChain conversion skips feedback-only messages ────────────────────


def test_to_lc_skips_feedback_only_messages() -> None:
    """Feedback messages are non-conversational metadata; the model should
    never see them as input on resume."""
    pytest.importorskip("langchain_core")
    from langchain_core.messages import HumanMessage  # noqa: PLC0415
    from scitrera_messaging_spec.langchain import to_lc_messages  # noqa: PLC0415

    msgs = [
        ChatMessage(id="u1", role="user", content=[TextPart(text="hi")]),
        _feedback_message(sentiment=1, text="great answer"),
        ChatMessage(id="u2", role="user", content=[TextPart(text="follow-up")]),
    ]
    lc = to_lc_messages(msgs)
    # The feedback message is dropped: only the two user text messages survive.
    assert len(lc) == 2
    assert all(isinstance(m, HumanMessage) for m in lc)
    assert [m.content for m in lc] == ["hi", "follow-up"]


def test_to_lc_keeps_non_feedback_parts_when_mixed() -> None:
    """If a message MIXES feedback + other parts (shouldn't happen — pure
    feedback messages are the spec-native shape), the non-feedback parts
    survive and the feedback parts are dropped."""
    pytest.importorskip("langchain_core")
    from langchain_core.messages import HumanMessage  # noqa: PLC0415
    from scitrera_messaging_spec.langchain import to_lc_messages  # noqa: PLC0415

    # Mixed user message: text + feedback. Spec doesn't forbid it; the
    # adapter routes the text into LC and drops the feedback silently.
    mixed = ChatMessage(
        id="m_mixed",
        role="user",
        content=[
            TextPart(text="hello"),
            FeedbackPart(sentiment=1),
        ],
    )
    lc = to_lc_messages([mixed])
    assert len(lc) == 1
    assert isinstance(lc[0], HumanMessage)
    assert lc[0].content == "hello"


def test_to_lc_empty_content_message_still_emits_aimessage() -> None:
    """The feedback-only filter must NOT short-circuit empty assistant
    turns (gap #5 — empty assistant turns emit one AIMessage)."""
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage  # noqa: PLC0415
    from scitrera_messaging_spec.langchain import to_lc_messages  # noqa: PLC0415

    empty_assistant = ChatMessage(id="m_empty", role="assistant", content=[])
    lc = to_lc_messages([empty_assistant])
    assert len(lc) == 1
    assert isinstance(lc[0], AIMessage)


def test_to_lc_assistant_turn_with_tool_pair_is_unaffected() -> None:
    """Sanity: feedback-skip logic doesn't interfere with normal turns."""
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage, ToolMessage  # noqa: PLC0415
    from scitrera_messaging_spec.langchain import to_lc_messages  # noqa: PLC0415

    msgs = [
        ChatMessage(
            id="m_asst",
            role="assistant",
            content=[
                TextPart(text="calling"),
                ToolCallPart(id="c1", name="t", args={}, status="completed"),
                ToolResultPart(call_id="c1", output_text="ok"),
                TextPart(text="done"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    kinds = [type(m).__name__ for m in lc]
    assert kinds == ["AIMessage", "ToolMessage", "AIMessage"]
    assert isinstance(lc[0], AIMessage)
    assert isinstance(lc[1], ToolMessage)


# ── MemoryLayer adapter preserves feedback (analytics is the point) ──


def test_to_memorylayer_payload_preserves_feedback() -> None:
    """Feedback messages must round-trip through MemoryLayer — they exist
    precisely so analytics consumers can read them later."""
    m = _feedback_message(sentiment=1, text="great answer")
    payload = to_memorylayer_payload(m)

    assert payload["role"] == "user"
    assert isinstance(payload["content"], list)
    assert payload["content"][0]["type"] == "feedback"
    # Non-text parts stash structure under ``data``.
    assert payload["content"][0]["data"]["sentiment"] == 1
    assert payload["content"][0]["data"]["text"] == "great answer"
    # spec metadata namespace carries id + addr + ref so we can find it later.
    sc = payload["metadata"]["scitrera"]
    assert sc["message_id"] == "msg_feedback_1"
    assert sc["ref"]["message_id"] == "msg_target_1"
    assert sc["ref"]["relationship"] == "feedback"


def test_memorylayer_round_trip_preserves_feedback_part() -> None:
    m = _feedback_message(sentiment=-1, text="not helpful")
    payload = to_memorylayer_payload(m)
    ml_record = {
        "id": "ml_id_1",
        "thread_id": m.addr.thread_id,
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
    }
    back = from_memorylayer_message(ml_record)
    assert back.role == "user"
    assert isinstance(back.content[0], FeedbackPart)
    assert back.content[0].sentiment == -1
    assert back.content[0].text == "not helpful"
    assert back.ref is not None
    assert back.ref.model_dump(exclude_none=True)["message_id"] == "msg_target_1"
