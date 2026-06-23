"""Tests for the universal ChatMessage spec reference implementation."""
from __future__ import annotations

import json

import pytest

from scitrera_messaging_spec import (
    SCHEMA_VERSION,
    ChatMessage,
    CitationPart,
    DynamicPart,
    FilePart,
    ImagePart,
    MessageAddress,
    MessageFinalized,
    MessageStarted,
    PartAppended,
    PartUpdated,
    ReasoningPart,
    TextPart,
    TokenDelta,
    ToolCallPart,
    ToolResultPart,
    UnknownPart,
    apply_event,
    from_cowork_blocks,
    from_rt_envelope,
    to_anthropic_messages,
    to_openai_chat_completion,
)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def _fixture_message() -> ChatMessage:
    return ChatMessage(
        id="msg_1",
        role="assistant",
        addr=MessageAddress(
            tenant_id="t1",
            workspace_id="w1",
            user_id="u1",
            thread_id="th1",
            agent_id="ag1",
            request_id="req_1",
        ),
        content=[
            TextPart(text="Looking up the report."),
            ToolCallPart(id="call_1", name="vfs_fetch", args={"path": "/r.pdf"}, status="running"),
            ToolResultPart(call_id="call_1", name="vfs_fetch", output={"ok": True}, output_text="ok"),
            TextPart(text="Done."),
            CitationPart(id="cit_1", source="vfs://r.pdf", title="Q3 Report", snippet="..."),
            FilePart(vfs_ref="vfs://r.pdf", mime="application/pdf", file_name="r.pdf", purpose="document"),
            ImagePart(uri="https://example.com/img.png", mime="image/png"),
            DynamicPart(kind="jsx", payload={"component": "Chart"}),
            ReasoningPart(text="user wants a summary", redacted=False),
        ],
        meta={"scitrera": {"feedback": "thumbs_up"}, "x-cowork": {"trace": "abc"}},
    )


def test_schema_version_is_v1() -> None:
    assert SCHEMA_VERSION == "1.0"
    assert ChatMessage(id="x", role="user").schema_version == "1.0"


def test_roundtrip_identity() -> None:
    m = _fixture_message()
    raw = m.model_dump_json()
    m2 = ChatMessage.model_validate_json(raw)
    assert m2.model_dump() == m.model_dump()


def test_discriminator_picks_concrete_classes() -> None:
    m = _fixture_message()
    raw = m.model_dump_json()
    m2 = ChatMessage.model_validate_json(raw)
    type_names = [type(p).__name__ for p in m2.content]
    assert type_names == [
        "TextPart",
        "ToolCallPart",
        "ToolResultPart",
        "TextPart",
        "CitationPart",
        "FilePart",
        "ImagePart",
        "DynamicPart",
        "ReasoningPart",
    ]


def test_unknown_part_survives_roundtrip_verbatim() -> None:
    """Forward-compat invariant: unknown ``type`` values must round-trip."""
    raw = {
        "id": "msg_unknown",
        "role": "assistant",
        "content": [
            {"type": "screencast", "url": "https://x", "duration_ms": 1234, "extra": {"k": "v"}},
            {"type": "text", "text": "hi"},
            {"type": "future_widget", "anything": [1, 2, 3]},
        ],
    }
    m = ChatMessage.model_validate(raw)
    assert isinstance(m.content[0], UnknownPart)
    assert isinstance(m.content[1], TextPart)
    assert isinstance(m.content[2], UnknownPart)

    dumped = m.model_dump(exclude_none=True)
    sc = dumped["content"][0]
    assert sc["type"] == "screencast"
    assert sc["url"] == "https://x"
    assert sc["duration_ms"] == 1234
    assert sc["extra"] == {"k": "v"}

    fw = dumped["content"][2]
    assert fw["type"] == "future_widget"
    assert fw["anything"] == [1, 2, 3]


def test_meta_extension_namespaces_preserved() -> None:
    m = _fixture_message()
    raw = m.model_dump_json()
    m2 = ChatMessage.model_validate_json(raw)
    assert m2.meta["scitrera"] == {"feedback": "thumbs_up"}
    assert m2.meta["x-cowork"] == {"trace": "abc"}


def test_tool_call_args_are_structured_not_string() -> None:
    """Spec §3.4: tool_call.args is a dict, not a JSON string."""
    raw_json = ChatMessage(
        id="m",
        role="assistant",
        content=[ToolCallPart(id="c", name="t", args={"a": 1, "b": [2, 3]})],
    ).model_dump_json()
    parsed = json.loads(raw_json)
    assert parsed["content"][0]["args"] == {"a": 1, "b": [2, 3]}


def test_role_tool_with_tool_result() -> None:
    m = ChatMessage(
        id="m",
        role="tool",
        content=[ToolResultPart(call_id="c1", output="ok")],
    )
    assert m.role == "tool"
    assert isinstance(m.content[0], ToolResultPart)


# ---------------------------------------------------------------------------
# events / apply_event
# ---------------------------------------------------------------------------


def test_apply_event_reconstructs_matching_final_message() -> None:
    """Replaying [started, appended..., delta..., updated..., finalized]
    must yield a message equal to the MessageFinalized payload."""
    final = _fixture_message()

    events: list = [
        MessageStarted(
            message=ChatMessage(
                id=final.id,
                role=final.role,
                addr=final.addr,
                meta=final.meta,
                content=[],
            )
        ),
    ]
    for i, part in enumerate(final.content):
        if isinstance(part, TextPart):
            events.append(
                PartAppended(message_id=final.id, index=i, part=TextPart(text=""))
            )
            events.append(TokenDelta(message_id=final.id, index=i, text=part.text))
        elif isinstance(part, ToolCallPart):
            initial = ToolCallPart(
                id=part.id, name=part.name, args=part.args, status="pending"
            )
            events.append(PartAppended(message_id=final.id, index=i, part=initial))
            events.append(
                PartUpdated(
                    message_id=final.id,
                    index=i,
                    patch={"status": part.status},
                )
            )
        else:
            events.append(PartAppended(message_id=final.id, index=i, part=part))
    events.append(MessageFinalized(message_id=final.id, message=final))

    state: dict[str, ChatMessage] = {}
    for ev in events:
        state = apply_event(state, ev)

    rebuilt = state[final.id]
    assert rebuilt.model_dump() == final.model_dump()


def test_apply_event_accepts_raw_dict_events() -> None:
    msg = ChatMessage(id="m", role="assistant", content=[])
    state: dict[str, ChatMessage] = {}
    state = apply_event(state, {"event": "message_started", "message": msg.model_dump()})
    state = apply_event(
        state,
        {
            "event": "part_appended",
            "message_id": "m",
            "index": 0,
            "part": {"type": "text", "text": ""},
        },
    )
    state = apply_event(
        state, {"event": "token_delta", "message_id": "m", "index": 0, "text": "hello"}
    )
    assert state["m"].content[0].text == "hello"  # type: ignore[union-attr]


def test_token_delta_is_noop_on_non_text_part() -> None:
    msg = ChatMessage(
        id="m",
        role="assistant",
        content=[ToolCallPart(id="c", name="t")],
    )
    state = {msg.id: msg}
    state2 = apply_event(state, TokenDelta(message_id="m", index=0, text="x"))
    assert state2[msg.id].content[0].model_dump() == msg.content[0].model_dump()


def test_part_updated_can_morph_part_type() -> None:
    msg = ChatMessage(
        id="m",
        role="assistant",
        content=[TextPart(text="hi")],
    )
    state = {msg.id: msg}
    state2 = apply_event(
        state,
        PartUpdated(
            message_id="m",
            index=0,
            patch={"type": "reasoning", "redacted": False},
        ),
    )
    assert isinstance(state2[msg.id].content[0], ReasoningPart)


def test_apply_event_does_not_mutate_input() -> None:
    msg = ChatMessage(id="m", role="assistant", content=[TextPart(text="")])
    state = {msg.id: msg}
    apply_event(state, TokenDelta(message_id="m", index=0, text="!"))
    assert state[msg.id].content[0].text == ""  # type: ignore[union-attr]


def test_apply_event_raises_on_unknown_event_kind() -> None:
    """Strict dispatch: unknown event kinds are caller error."""
    msg = ChatMessage(id="m", role="assistant", content=[TextPart(text="x")])
    state = {msg.id: msg}
    with pytest.raises(Exception):
        apply_event(state, {"event": "future_event", "message_id": "m"})


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------


def test_from_rt_envelope_text_and_attachments() -> None:
    env = {
        "source": {"tenant": "t1", "workspace": "w1", "user": "u1", "agent": "ag1"},
        "content": {
            "text": "hello",
            "role": "user",
            "attachments": ["vfs://a"],
            "documents": ["vfs://d"],
            "dynamic": {"k": "v"},
        },
        "workspace": "w1",
        "request_id": "req_1",
    }
    m = from_rt_envelope(env)
    assert m.role == "user"
    assert m.addr.tenant_id == "t1"
    assert m.addr.workspace_id == "w1"
    assert m.id == "req_1"

    types = [type(p).__name__ for p in m.content]
    assert types == ["TextPart", "FilePart", "FilePart", "DynamicPart"]
    assert m.content[1].purpose == "attachment"  # type: ignore[union-attr]
    assert m.content[2].purpose == "document"  # type: ignore[union-attr]


def test_from_cowork_blocks_full_turn() -> None:
    blocks = [
        {"type": "text", "data": {"text": "Looking up."}},
        {
            "type": "tool_call",
            "data": {"id": "c1", "name": "vfs_fetch", "args": {"p": 1}, "status": "running"},
        },
        {
            "type": "tool_result",
            "data": {"tool_call_id": "c1", "name": "vfs_fetch", "output": {"ok": True}},
        },
        {"type": "citation", "data": {"source": "vfs://r", "title": "R", "snippet": "..."}},
        {"type": "attachment", "data": {"vfs_ref": "vfs://a", "file_name": "a.pdf"}},
        {"type": "document", "data": {"vfs_ref": "vfs://d", "file_name": "d.pdf"}},
        {"type": "dynamic", "data": {"kind": "jsx", "payload": {"x": 1}}},
        {"type": "future_thing", "data": {"weird": True}},
    ]
    m = from_cowork_blocks(blocks, role="assistant", message_id="msg_x")
    assert m.id == "msg_x"
    types = [type(p).__name__ for p in m.content]
    assert types == [
        "TextPart",
        "ToolCallPart",
        "ToolResultPart",
        "CitationPart",
        "FilePart",
        "FilePart",
        "DynamicPart",
        "UnknownPart",
    ]
    assert m.content[4].purpose == "attachment"  # type: ignore[union-attr]
    assert m.content[5].purpose == "document"  # type: ignore[union-attr]


def test_from_cowork_blocks_coerces_string_args() -> None:
    blocks = [
        {
            "type": "tool_call",
            "data": {"id": "c", "name": "t", "args": '{"a": 1}', "status": "completed"},
        }
    ]
    m = from_cowork_blocks(blocks)
    tc = m.content[0]
    assert isinstance(tc, ToolCallPart)
    assert tc.args == {"a": 1}


def test_to_openai_chat_completion_assistant_with_tools() -> None:
    m = ChatMessage(
        id="m",
        role="assistant",
        content=[
            TextPart(text="Calling tool."),
            ToolCallPart(id="c1", name="t", args={"x": 1}, status="completed"),
            ToolResultPart(call_id="c1", output={"ok": True}),
            TextPart(text="Done."),
        ],
    )
    out = to_openai_chat_completion(m)
    assert len(out) == 2

    asst = out[0]
    assert asst["role"] == "assistant"
    assert asst["content"] == "Calling tool.\nDone."
    assert asst["tool_calls"][0]["id"] == "c1"
    assert asst["tool_calls"][0]["function"]["name"] == "t"
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {"x": 1}

    tool = out[1]
    assert tool["role"] == "tool"
    assert tool["tool_call_id"] == "c1"
    assert json.loads(tool["content"]) == {"ok": True}


def test_to_openai_chat_completion_drops_citations_and_dynamic() -> None:
    m = ChatMessage(
        id="m",
        role="assistant",
        content=[
            TextPart(text="hi"),
            CitationPart(source="x"),
            DynamicPart(kind="jsx", payload={"y": 1}),
        ],
    )
    out = to_openai_chat_completion(m)
    assert out == [{"role": "assistant", "content": "hi"}]


def test_to_openai_chat_completion_image_uses_content_blocks() -> None:
    m = ChatMessage(
        id="m",
        role="user",
        content=[
            TextPart(text="look"),
            ImagePart(uri="https://example.com/i.png", mime="image/png"),
        ],
    )
    out = to_openai_chat_completion(m)
    assert out[0]["role"] == "user"
    assert out[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "https://example.com/i.png"}},
    ]


def test_to_anthropic_messages_assistant_tool_call_split() -> None:
    m = ChatMessage(
        id="m",
        role="assistant",
        content=[
            TextPart(text="checking"),
            ToolCallPart(id="c1", name="t", args={"x": 1}),
            ToolResultPart(call_id="c1", output={"ok": True}),
        ],
    )
    out = to_anthropic_messages(m)
    assert len(out) == 2
    assert out[0]["role"] == "assistant"
    assert out[0]["content"][0] == {"type": "text", "text": "checking"}
    assert out[0]["content"][1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "t",
        "input": {"x": 1},
    }
    assert out[1]["role"] == "user"
    assert out[1]["content"][0]["type"] == "tool_result"
    assert out[1]["content"][0]["tool_use_id"] == "c1"


def test_to_anthropic_messages_data_uri_image() -> None:
    m = ChatMessage(
        id="m",
        role="user",
        content=[ImagePart(data_uri="data:image/png;base64,AAAA")],
    )
    out = to_anthropic_messages(m)
    src = out[0]["content"][0]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/png"
    assert src["data"] == "AAAA"
